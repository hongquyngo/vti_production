# utils/supply_chain_production/mo_planner.py

"""
Core MO Planner — Layer 3 Phase 2 orchestrator.

Pipeline:
1. Validate config gate (ZERO ASSUMPTION — must be configured)
2. Extract mo_suggestions from GAP result (typed boundary)
3. Load supplementary data (existing MOs, historical stats)
4. Material readiness check (2-pass: individual + contention)
5. Schedule + prioritize (3-tier lead time, backward scheduling)
6. Build MOLineItems + categorize (Ready / Waiting / Blocked)
7. Reconciliation (input = output, no items disappear)

Usage:
    planner = MOPlanner.create_with_data_loader(config)
    result = planner.plan_from_gap_result(gap_result)
    # or
    planner = MOPlanner(config, lead_time_stats_df, existing_mo_df)
    result = planner.plan_from_gap_result(gap_result, po_result)
"""

import logging
from datetime import date, timedelta
from typing import Dict, Any, List, Optional, Tuple

import pandas as pd

from .production_config import ProductionConfig, ProductionConfigLoader
from .production_constants import MO_ACTION_TYPES, UNSCHEDULABLE_REASONS
from .production_interfaces import (
    ProductionInputItem,
    ProductReadiness,
    UnschedulableItem,
)
from .production_validators import (
    extract_production_inputs,
    validate_gap_filters_for_production,
    ValidationResult,
)
from .material_readiness_checker import MaterialReadinessChecker
from .mo_scheduling_engine import MOSchedulingEngine, SchedulingResult
from .mo_result import MOLineItem, MOSuggestionResult

logger = logging.getLogger(__name__)


class MOPlanner:
    """
    Core Production Planning engine.

    Orchestrates: GAP extraction → material readiness → scheduling → output.
    """

    def __init__(
        self,
        config: ProductionConfig,
        lead_time_stats_df: Optional[pd.DataFrame] = None,
        existing_mo_df: Optional[pd.DataFrame] = None,
        so_linkage_df: Optional[pd.DataFrame] = None,
    ):
        if not config.is_ready:
            raise ValueError(
                f"Config not ready — {len(config.missing_required)} missing, "
                f"{len(config.validation_errors)} errors. "
                f"Run config validation and fix before creating MOPlanner."
            )

        self._config = config
        self._readiness_checker = MaterialReadinessChecker(config)
        self._scheduling_engine = MOSchedulingEngine(config, lead_time_stats_df)

        # Existing MO lookup: product_id → summary row
        self._existing_mos: Dict[int, Dict[str, Any]] = {}
        if existing_mo_df is not None and not existing_mo_df.empty:
            for _, row in existing_mo_df.iterrows():
                pid = row.get('product_id')
                if pid is not None and not pd.isna(pid):
                    self._existing_mos[int(pid)] = row.to_dict()

        # SO linkage: product_id → has_sales_order
        self._so_linkage: Dict[int, bool] = {}
        if so_linkage_df is not None and not so_linkage_df.empty:
            for _, row in so_linkage_df.iterrows():
                pid = row.get('product_id')
                if pid is not None and not pd.isna(pid):
                    self._so_linkage[int(pid)] = bool(row.get('has_sales_order', False))

        logger.info(
            f"MOPlanner initialized: "
            f"{len(self._existing_mos)} products with existing MOs, "
            f"{len(self._so_linkage)} products with SO linkage"
        )

    # =====================================================================
    # MAIN ENTRY: FROM GAP RESULT
    # =====================================================================

    def plan_from_gap_result(
        self,
        gap_result,
        po_result=None,
        reference_date: Optional[date] = None,
    ) -> MOSuggestionResult:
        """
        Full production planning pipeline from GAP result.

        Args:
            gap_result: SupplyChainGAPResult
            po_result: POSuggestionResult (optional — improves material ETA)
            reference_date: Today (default: date.today())

        Returns: MOSuggestionResult
        """
        if reference_date is None:
            reference_date = date.today()

        logger.info("MOPlanner: starting production planning pipeline...")

        # Step 0: Filter review (informational — never blocks)
        filter_review = validate_gap_filters_for_production(gap_result)

        # Step 1: Extract production inputs from GAP
        items, validation = extract_production_inputs(gap_result)

        if not validation.is_valid:
            logger.error(f"GAP validation FAILED: {validation.errors}")
            result = MOSuggestionResult()
            result.metrics['validation_errors'] = validation.errors
            result.input_summary = {
                'source': 'GAP_RESULT',
                'total_items': 0,
                'filter_review': filter_review,
            }
            return result

        if not items:
            logger.info("No manufacturing shortage items — nothing to plan")
            result = MOSuggestionResult()
            result.input_summary = {
                'source': 'GAP_RESULT',
                'total_items': validation.items_skipped,
                'validation_skipped': validation.items_skipped,
                'filter_review': filter_review,
            }
            return result

        # Enrich items with SO linkage
        for item in items:
            item.has_sales_order = self._so_linkage.get(item.product_id, False)

        logger.info(
            f"MOPlanner: {len(items)} production inputs extracted "
            f"({validation.items_skipped} skipped validation)"
        )

        # Step 2: Material readiness check (2-pass)
        readiness_map = self._readiness_checker.check_all(items, gap_result, po_result)

        # Step 3: Schedule + prioritize
        scheduled, unschedulable = self._scheduling_engine.schedule_and_prioritize(
            items, readiness_map, reference_date,
        )

        # Step 4: Build MOLineItems
        all_lines: List[MOLineItem] = []
        processing_errors: List[str] = []

        for item, sched, readiness in scheduled:
            try:
                line = self._build_line_item(item, sched, readiness)
                all_lines.append(line)
            except Exception as e:
                error_msg = f"Error building MO line for {item.pt_code}: {e}"
                logger.error(error_msg, exc_info=True)
                processing_errors.append(error_msg)

        # Step 5: Build result
        result = MOSuggestionResult(
            all_lines=all_lines,
            unschedulable_items=unschedulable,
            readiness_map=readiness_map,
            input_summary={
                'source': 'GAP_RESULT',
                'total_items': len(items) + validation.items_skipped,
                'validation_skipped': validation.items_skipped,
                'validation_warnings': len(validation.warnings),
                'filter_review': filter_review,
                'po_result_available': po_result is not None,
                'existing_mos_loaded': len(self._existing_mos),
                'so_linkage_loaded': len(self._so_linkage),
            },
            config_snapshot={
                'lead_time_cutting': self._config.lead_time_cutting_days,
                'lead_time_repacking': self._config.lead_time_repacking_days,
                'lead_time_kitting': self._config.lead_time_kitting_days,
                'use_historical_lt': self._config.lead_time_use_historical,
                'use_historical_yield': self._config.yield_use_historical,
                'planning_horizon': self._config.planning_horizon_days,
                'allow_partial': self._config.allow_partial_production,
            },
        )

        # Step 6: Categorize
        result.categorize_lines()

        # Step 7: Metrics
        if processing_errors:
            result.metrics['processing_errors'] = processing_errors
        result.compute_metrics()

        logger.info(
            f"MOPlanner complete: "
            f"{len(all_lines)} MO suggestions "
            f"({len(result.ready_lines)} ready, "
            f"{len(result.waiting_lines)} waiting, "
            f"{len(result.blocked_lines)} blocked, "
            f"{len(unschedulable)} unschedulable)"
            f"{f', {len(processing_errors)} errors' if processing_errors else ''}"
        )

        return result

    # =====================================================================
    # BUILD MO LINE ITEM
    # =====================================================================

    def _build_line_item(
        self,
        item: ProductionInputItem,
        sched: SchedulingResult,
        readiness: ProductReadiness,
    ) -> MOLineItem:
        """Build one MOLineItem from item + scheduling + readiness."""

        # Existing MO context (informational only — NOT deducted)
        existing = self._existing_mos.get(item.product_id, {})
        existing_count = int(existing.get('active_mo_count', 0) or 0)
        existing_remaining = float(existing.get('total_remaining_qty', 0) or 0)

        # Action type
        action_type, action_desc = self._determine_action(readiness, sched)

        # Materials ready %
        materials_pct = 0.0
        if readiness.total_materials > 0:
            materials_pct = round(
                readiness.ready_materials / readiness.total_materials * 100, 1
            )

        return MOLineItem(
            # Product
            product_id=item.product_id,
            pt_code=item.pt_code,
            product_name=item.product_name,
            brand=item.brand,
            package_size=item.package_size,
            uom=item.uom,

            # BOM
            bom_id=item.bom_id,
            bom_code=item.bom_code,
            bom_type=item.bom_type,
            bom_output_qty=item.bom_output_qty,

            # Quantity
            shortage_qty=item.shortage_qty,
            suggested_qty=sched.suggested_qty,
            batches_needed=sched.batches_needed,
            yield_multiplier=sched.yield_multiplier,
            yield_source=sched.yield_source,

            # Readiness
            readiness_status=readiness.overall_status,
            can_start_now=readiness.can_start_production,
            materials_ready_pct=materials_pct,
            total_materials=readiness.total_materials,
            ready_materials=readiness.ready_materials,
            partial_materials=readiness.partial_materials,
            blocked_materials=readiness.blocked_materials,
            bottleneck_material=readiness.bottleneck_material_code,
            bottleneck_eta=readiness.bottleneck_eta,
            max_producible_now=readiness.max_producible_now,
            max_producible_pct=readiness.max_producible_pct,
            has_contention=readiness.has_contention,

            # Scheduling
            demand_date=sched.demand_date,
            must_start_by=sched.must_start_by,
            actual_start=sched.actual_start,
            expected_completion=sched.expected_completion,
            lead_time_days=sched.lead_time_days,
            lead_time_source=sched.lead_time_source,

            # Delay
            is_delayed=sched.is_delayed,
            delay_days=sched.delay_days,
            delay_reason=sched.delay_reason,

            # Urgency
            urgency_level=sched.urgency_level,
            urgency_priority=sched.urgency_priority,

            # Priority
            priority_score=sched.priority_score,

            # Value
            at_risk_value=item.at_risk_value,
            customer_count=item.customer_count,
            has_sales_order=item.has_sales_order,

            # GAP context
            gap_production_status=item.gap_production_status,
            gap_limiting_materials=item.gap_limiting_materials,

            # Existing MOs
            existing_mo_count=existing_count,
            existing_mo_remaining_qty=existing_remaining,

            # Action
            action_type=action_type,
            action_description=action_desc,
        )

    def _determine_action(
        self,
        readiness: ProductReadiness,
        sched: SchedulingResult,
    ) -> Tuple[str, str]:
        """Determine MO action type and description."""

        if readiness.overall_status == 'READY':
            return 'CREATE_MO', 'All materials available — create MO to start production'

        if readiness.overall_status == 'USE_ALTERNATIVE':
            return 'USE_ALTERNATIVE', (
                f"Use alternative material for {readiness.bottleneck_material_code} — "
                f"can start production"
            )

        if readiness.overall_status == 'PARTIAL_READY':
            if readiness.bottleneck_eta:
                eta_str = readiness.bottleneck_eta.isoformat()
                return 'WAIT_MATERIAL', (
                    f"Waiting for {readiness.bottleneck_material_code} "
                    f"(ETA: {eta_str}) — "
                    f"{readiness.ready_materials}/{readiness.total_materials} materials ready"
                )
            return 'WAIT_MATERIAL', (
                f"Partial materials — "
                f"{readiness.ready_materials}/{readiness.total_materials} ready, "
                f"max producible now: {readiness.max_producible_now:,.0f}"
            )

        # BLOCKED
        if sched.delay_reason == 'MATERIAL_BLOCKED_NO_ETA':
            return 'WAIT_MATERIAL', (
                f"Materials blocked with no ETA — "
                f"{readiness.blocked_materials} material(s) unavailable. "
                f"Check PO Planning for required purchases."
            )

        return 'WAIT_MATERIAL', (
            f"Materials not ready — "
            f"{readiness.blocked_materials} blocked, "
            f"{readiness.partial_materials} partial"
        )

    # =====================================================================
    # FACTORY: Create with data loader
    # =====================================================================

    @classmethod
    def create_with_data_loader(
        cls,
        config: ProductionConfig,
        data_loader=None,
    ) -> 'MOPlanner':
        """
        Factory: create MOPlanner with auto-loaded supplementary data.

        Usage:
            config = config_loader.load_and_validate()
            planner = MOPlanner.create_with_data_loader(config)
            result = planner.plan_from_gap_result(gap_result)
        """
        if data_loader is None:
            from .production_data_loader import get_production_data_loader
            data_loader = get_production_data_loader()

        logger.info("MOPlanner: loading supplementary data...")

        lt_stats = data_loader.load_lead_time_stats()
        existing_mos = data_loader.load_existing_mo_summary()
        so_linkage = data_loader.load_product_so_linkage()

        return cls(
            config=config,
            lead_time_stats_df=lt_stats,
            existing_mo_df=existing_mos,
            so_linkage_df=so_linkage,
        )
