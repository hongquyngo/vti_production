# utils/supply_chain_production/material_readiness_checker.py

"""
Material Readiness Checker — KEY differentiating component of Production Planning.

For each manufacturing product with shortage, answers:
  "Can we produce it? If not, what's blocking and when will it unblock?"

Two-pass architecture:
  Pass 1: Check each product's BOM materials independently against supply
  Pass 2: Resolve contention when multiple products compete for the same material
           (allocate by priority score — higher priority gets first pick)

Inputs (all from GAP result, no DB queries):
  - bom_explosion_df: BOM materials per product
  - raw_gap_df: current raw material supply vs demand (net GAP)
  - raw_period_gap_df: future raw material supply timeline
  - alternative_analysis_df: which alternatives can cover shortages
  - PO Planning result (optional): PO arrival dates improve ETA

Output:
  Dict[product_id → ProductReadiness] with per-material breakdown
"""

import logging
from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, List, Optional, Set, Tuple

import numpy as np
import pandas as pd

from .production_config import ProductionConfig
from .production_interfaces import (
    MaterialReadiness,
    MaterialRequirement,
    ProductionInputItem,
    ProductReadiness,
)
from .production_validators import extract_material_requirements
from .production_validators import _period_to_date as _validators_period_to_date

logger = logging.getLogger(__name__)


class MaterialReadinessChecker:
    """
    Two-pass material readiness checker.

    Usage:
        checker = MaterialReadinessChecker(config)
        readiness_map = checker.check_all(items, gap_result, po_result)
        # readiness_map: Dict[product_id → ProductReadiness]
    """

    def __init__(self, config: ProductionConfig):
        self._config = config

    # =====================================================================
    # PUBLIC: Check all products
    # =====================================================================

    def check_all(
        self,
        items: List[ProductionInputItem],
        gap_result,
        po_result=None,
    ) -> Dict[int, ProductReadiness]:
        """
        Two-pass material readiness check for all production input items.

        Pass 1: Check each product independently
        Pass 2: Resolve contention (multiple products → same material)

        Returns: Dict[product_id → ProductReadiness]
        """
        if not items:
            return {}

        # Pre-build lookups from GAP result (once, shared across all products)
        supply_lookup = self._build_supply_lookup(gap_result)
        alt_lookup = self._build_alternative_lookup(gap_result)
        period_lookup = self._build_period_eta_lookup(gap_result)
        po_eta_lookup = self._build_po_eta_lookup(po_result)

        # === PASS 1: Individual readiness ===
        readiness_map: Dict[int, ProductReadiness] = {}
        material_demand_registry: Dict[int, List[Dict]] = defaultdict(list)

        for item in items:
            readiness = self._check_single_product(
                item, gap_result, supply_lookup, alt_lookup,
                period_lookup, po_eta_lookup,
            )
            readiness_map[item.product_id] = readiness

            # Register material demand for contention detection
            for mat in readiness.materials:
                if mat.is_primary and mat.status != 'READY':
                    material_demand_registry[mat.material_id].append({
                        'product_id': item.product_id,
                        'required_qty': mat.required_qty,
                        'priority_score': item.at_risk_value,  # temp proxy; real score set in scheduling
                    })

        # === PASS 2: Contention resolution ===
        contested = {
            mid: demands
            for mid, demands in material_demand_registry.items()
            if len(demands) > 1
        }

        if contested:
            logger.info(
                f"Material contention detected: {len(contested)} materials "
                f"shared by multiple products"
            )
            readiness_map = self._resolve_contention(
                readiness_map, contested, supply_lookup,
            )

        # Summary log
        statuses = defaultdict(int)
        for pr in readiness_map.values():
            statuses[pr.overall_status] += 1
        logger.info(
            f"Material readiness check complete: {len(readiness_map)} products — "
            + ", ".join(f"{s}: {c}" for s, c in sorted(statuses.items()))
        )

        return readiness_map

    # =====================================================================
    # PASS 1: Single product readiness
    # =====================================================================

    def _check_single_product(
        self,
        item: ProductionInputItem,
        gap_result,
        supply_lookup: Dict[int, float],
        alt_lookup: Dict[int, Dict],
        period_lookup: Dict[int, Optional[date]],
        po_eta_lookup: Dict[int, Optional[date]],
    ) -> ProductReadiness:
        """Check material readiness for one product."""

        # Extract BOM materials
        mat_requirements = extract_material_requirements(
            gap_result,
            product_id=item.product_id,
            shortage_qty=item.shortage_qty,
            bom_output_qty=item.bom_output_qty,
        )

        if not mat_requirements:
            # No BOM materials found — treat as ready (edge case)
            return ProductReadiness(
                product_id=item.product_id,
                pt_code=item.pt_code,
                product_name=item.product_name,
                bom_code=item.bom_code,
                bom_type=item.bom_type,
                overall_status='READY',
                can_start_production=True,
            )

        # Check each material
        material_readiness_list: List[MaterialReadiness] = []

        for mat_req in mat_requirements:
            mr = self._check_single_material(
                mat_req, supply_lookup, alt_lookup,
                period_lookup, po_eta_lookup,
            )
            material_readiness_list.append(mr)

        # Build ProductReadiness
        pr = ProductReadiness(
            product_id=item.product_id,
            pt_code=item.pt_code,
            product_name=item.product_name,
            bom_code=item.bom_code,
            bom_type=item.bom_type,
            materials=material_readiness_list,
        )

        # Compute max producible now
        pr.max_producible_now = self._calculate_max_producible(
            material_readiness_list, item.shortage_qty, item.bom_output_qty,
        )
        if item.shortage_qty > 0:
            pr.max_producible_pct = round(
                pr.max_producible_now / item.shortage_qty * 100, 1
            )

        pr.recompute_overall_status()
        return pr

    def _check_single_material(
        self,
        mat_req: MaterialRequirement,
        supply_lookup: Dict[int, float],
        alt_lookup: Dict[int, Dict],
        period_lookup: Dict[int, Optional[date]],
        po_eta_lookup: Dict[int, Optional[date]],
    ) -> MaterialReadiness:
        """Check readiness for one BOM material."""

        required = mat_req.required_qty
        available = supply_lookup.get(mat_req.material_id, 0.0)

        # Coverage
        if required <= 0:
            coverage_pct = 100.0
        else:
            coverage_pct = round(min(999.0, available / required * 100), 1)

        # Status
        if available >= required:
            status = 'READY'
        elif available > 0:
            status = 'PARTIAL'
        else:
            status = 'BLOCKED'

        shortage_qty = max(0, required - available)

        # ETA: when will full coverage be available?
        eta, coverage_source = self._resolve_eta(
            mat_req.material_id, period_lookup, po_eta_lookup, status,
        )

        # Alternative analysis
        has_alt = False
        alt_can_cover = False
        alt_info = alt_lookup.get(mat_req.material_id)
        if alt_info and mat_req.is_primary:
            has_alt = True
            alt_can_cover = alt_info.get('can_cover_shortage', False)

        return MaterialReadiness(
            material_id=mat_req.material_id,
            material_pt_code=mat_req.material_pt_code,
            material_name=mat_req.material_name,
            material_uom=mat_req.material_uom,
            material_type=mat_req.material_type,
            is_primary=mat_req.is_primary,
            required_qty=required,
            available_now=available,
            allocated_qty=available,       # Pass 1: allocated = available
            shortage_qty=shortage_qty,
            coverage_pct=coverage_pct,
            status=status,
            earliest_full_coverage=eta,
            coverage_source=coverage_source,
            has_alternative=has_alt,
            alternative_can_cover=alt_can_cover,
        )

    # =====================================================================
    # ETA RESOLUTION
    # =====================================================================

    def _resolve_eta(
        self,
        material_id: int,
        period_lookup: Dict[int, Optional[date]],
        po_eta_lookup: Dict[int, Optional[date]],
        current_status: str,
    ) -> Tuple[Optional[date], str]:
        """
        Determine when full material coverage will be available.

        Priority:
        1. IN_STOCK → no ETA needed (already available)
        2. PO arrival date (from PO Planning result) → most specific
        3. Period gap data (from GAP raw_period_gap_df) → approximate
        4. UNKNOWN → no ETA
        """
        if current_status == 'READY':
            return None, 'IN_STOCK'

        # Try PO arrival
        po_eta = po_eta_lookup.get(material_id)
        if po_eta is not None:
            return po_eta, 'PENDING_PO'

        # Try period gap (first period where supply covers demand)
        period_eta = period_lookup.get(material_id)
        if period_eta is not None:
            return period_eta, 'PO_SUGGESTED'

        return None, 'UNKNOWN'

    # =====================================================================
    # MAX PRODUCIBLE NOW (for partial production analysis)
    # =====================================================================

    def _calculate_max_producible(
        self,
        materials: List[MaterialReadiness],
        shortage_qty: float,
        bom_output_qty: float,
    ) -> float:
        """
        Calculate maximum producible quantity given current material availability.

        Limited by the material with the lowest coverage ratio.
        Only considers primary materials (alternatives are separate analysis).
        """
        if not materials or shortage_qty <= 0:
            return 0.0

        min_coverage_ratio = 999.0
        for mat in materials:
            if not mat.is_primary:
                continue
            if mat.required_qty <= 0:
                continue
            ratio = mat.available_now / mat.required_qty
            min_coverage_ratio = min(min_coverage_ratio, ratio)

        if min_coverage_ratio >= 999.0:
            return shortage_qty  # all materials unlimited or no primary materials

        max_producible = shortage_qty * min(1.0, min_coverage_ratio)

        # Round down to BOM output_qty multiple (can only produce full batches)
        if bom_output_qty > 0:
            full_batches = int(max_producible / bom_output_qty)
            max_producible = full_batches * bom_output_qty

        return max(0.0, max_producible)

    # =====================================================================
    # PASS 2: Contention resolution
    # =====================================================================

    def _resolve_contention(
        self,
        readiness_map: Dict[int, ProductReadiness],
        contested: Dict[int, List[Dict]],
        supply_lookup: Dict[int, float],
    ) -> Dict[int, ProductReadiness]:
        """
        Allocate contested materials by priority.

        For each contested material:
        1. Sort competing products by priority (higher at_risk_value = higher priority)
        2. Allocate available supply to highest priority first
        3. Lower-priority products get reduced allocation → may downgrade status
        """
        for material_id, demands in contested.items():
            available = supply_lookup.get(material_id, 0.0)

            # Sort: highest at_risk_value first (proxy for priority before scoring).
            # NOTE: This uses at_risk_value as proxy because real priority_score
            # is not yet computed (scheduling runs AFTER readiness check).
            # Higher at_risk_value = more business-critical = gets material first.
            # If refactoring to use real priority_score (lower=more urgent),
            # reverse the sort order.
            sorted_demands = sorted(
                demands, key=lambda d: d['priority_score'], reverse=True,
            )

            remaining = available
            for demand in sorted_demands:
                product_id = demand['product_id']
                required = demand['required_qty']
                allocated = min(remaining, required)
                remaining = max(0, remaining - allocated)

                # Update material allocation in the product's readiness
                pr = readiness_map.get(product_id)
                if pr is None:
                    continue

                for mat in pr.materials:
                    if mat.material_id == material_id and mat.is_primary:
                        mat.allocated_qty = allocated
                        mat.is_contested = True
                        mat.contention_products = len(sorted_demands)

                        # Recompute status based on allocation (not raw available)
                        if allocated >= mat.required_qty:
                            mat.status = 'READY'
                            mat.coverage_pct = 100.0
                        elif allocated > 0:
                            mat.status = 'PARTIAL'
                            mat.coverage_pct = round(
                                allocated / mat.required_qty * 100, 1
                            )
                        else:
                            mat.status = 'BLOCKED'
                            mat.coverage_pct = 0.0

                        mat.shortage_qty = max(0, mat.required_qty - allocated)
                        break

            # Recompute overall status for all affected products
            affected_pids = {d['product_id'] for d in sorted_demands}
            for pid in affected_pids:
                pr = readiness_map.get(pid)
                if pr:
                    pr.recompute_overall_status()

        return readiness_map

    # =====================================================================
    # LOOKUP BUILDERS (from GAP result, built once)
    # =====================================================================

    def _build_supply_lookup(self, gap_result) -> Dict[int, float]:
        """
        Build material_id → available_supply from raw_gap_df.

        Uses 'available_supply' column (already net of safety stock).
        Falls back to 'total_supply' if available_supply not present.
        """
        raw_gap = getattr(gap_result, 'raw_gap_df', None)
        if raw_gap is None or not isinstance(raw_gap, pd.DataFrame) or raw_gap.empty:
            return {}

        lookup = {}
        supply_col = 'available_supply' if 'available_supply' in raw_gap.columns else 'total_supply'
        if supply_col not in raw_gap.columns:
            return {}

        for _, row in raw_gap.iterrows():
            mid = row.get('material_id')
            if mid is None or pd.isna(mid):
                continue
            supply = float(row.get(supply_col, 0) or 0)
            mid_int = int(mid)
            # Accumulate (same material from different sources)
            lookup[mid_int] = lookup.get(mid_int, 0) + supply

        return lookup

    def _build_alternative_lookup(self, gap_result) -> Dict[int, Dict]:
        """
        Build primary_material_id → alternative analysis from alternative_analysis_df.

        Returns: {primary_material_id: {can_cover_shortage: bool, ...}}
        """
        alt_df = getattr(gap_result, 'alternative_analysis_df', None)
        if alt_df is None or not isinstance(alt_df, pd.DataFrame) or alt_df.empty:
            return {}

        if 'primary_material_id' not in alt_df.columns:
            return {}

        lookup = {}
        for _, row in alt_df.iterrows():
            pmid = row.get('primary_material_id')
            if pmid is None or pd.isna(pmid):
                continue
            pmid_int = int(pmid)

            can_cover = bool(row.get('can_cover_shortage', False))

            # Keep best (can_cover=True wins)
            existing = lookup.get(pmid_int, {})
            if can_cover or not existing.get('can_cover_shortage', False):
                lookup[pmid_int] = {
                    'can_cover_shortage': can_cover,
                    'alternative_material_id': row.get('alternative_material_id'),
                    'material_pt_code': row.get('material_pt_code', ''),
                }

        return lookup

    def _build_period_eta_lookup(self, gap_result) -> Dict[int, Optional[date]]:
        """
        Build material_id → earliest date when supply covers demand
        from raw_period_gap_df.

        Looks for first period where gap_quantity >= 0 for each material.
        """
        raw_period = getattr(gap_result, 'raw_period_gap_df', None)
        if raw_period is None or not isinstance(raw_period, pd.DataFrame) or raw_period.empty:
            return {}

        if 'material_id' not in raw_period.columns or 'gap_quantity' not in raw_period.columns:
            return {}

        lookup: Dict[int, Optional[date]] = {}

        for mid in raw_period['material_id'].unique():
            mat_periods = raw_period[raw_period['material_id'] == mid]
            # Find first period where gap >= 0 (supply covers demand)
            positive = mat_periods[mat_periods['gap_quantity'] >= 0]
            if positive.empty:
                continue

            first_period = positive.iloc[0].get('period')
            if first_period:
                eta = self._period_to_date(first_period)
                if eta:
                    lookup[int(mid)] = eta

        return lookup

    def _build_po_eta_lookup(self, po_result) -> Dict[int, Optional[date]]:
        """
        Build material_id → expected_arrival from PO Planning result.

        Only includes RAW_MATERIAL PO lines (not FG_TRADING).
        Uses earliest arrival date per material.
        """
        if po_result is None:
            return {}

        all_lines = getattr(po_result, 'all_lines', None)
        if not all_lines:
            return {}

        lookup: Dict[int, Optional[date]] = {}
        for line in all_lines:
            if getattr(line, 'shortage_source', '') != 'RAW_MATERIAL':
                continue
            pid = getattr(line, 'product_id', None)
            arrival = getattr(line, 'expected_arrival', None)
            if pid is None or arrival is None:
                continue

            pid_int = int(pid)
            arrival_date = self._to_date(arrival)
            if arrival_date is None:
                continue

            existing = lookup.get(pid_int)
            if existing is None or arrival_date < existing:
                lookup[pid_int] = arrival_date

        return lookup

    # =====================================================================
    # HELPERS
    # =====================================================================

    @staticmethod
    def _period_to_date(period_str: str) -> Optional[date]:
        """Convert period string → date. Delegates to production_validators."""
        return _validators_period_to_date(period_str)

    @staticmethod
    def _to_date(value) -> Optional[date]:
        """Convert various types to date."""
        if value is None:
            return None
        if isinstance(value, date) and not isinstance(value, pd.Timestamp):
            return value
        if isinstance(value, pd.Timestamp):
            return value.date() if not pd.isna(value) else None
        from datetime import datetime
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, str):
            try:
                return date.fromisoformat(value[:10])
            except (ValueError, IndexError):
                pass
        return None