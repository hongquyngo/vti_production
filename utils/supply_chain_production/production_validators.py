# utils/supply_chain_production/production_validators.py

"""
Validation layer between Supply Chain GAP and Production Planning modules.

Responsibilities:
1. Validate GAP result structure for Production Planning consumption
2. Safely extract mo_suggestions → typed ProductionInputItem list
3. Extract per-product demand dates from GAP period data
4. Extract BOM material requirements per product
5. Validate GAP filter config (informed consent, same pattern as PO Planning)

This module is the SINGLE POINT where GAP's internal data structures are
converted to Production Planning's typed interfaces. If GAP changes
a field name, only this file needs updating.
"""

import pandas as pd
import logging
from datetime import date, datetime
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

from .production_interfaces import (
    ProductionInputItem,
    MaterialRequirement,
)

logger = logging.getLogger(__name__)


# =============================================================================
# VALIDATION RESULT
# =============================================================================

@dataclass
class ValidationResult:
    """Tracks extraction warnings, errors, and skip counts."""
    is_valid: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    items_extracted: int = 0
    items_skipped: int = 0

    def add_error(self, msg: str):
        self.errors.append(msg)
        self.is_valid = False

    def add_warning(self, msg: str):
        self.warnings.append(msg)

    def summary(self) -> str:
        parts = [f"extracted={self.items_extracted}, skipped={self.items_skipped}"]
        if self.errors:
            parts.append(f"errors={len(self.errors)}")
        if self.warnings:
            parts.append(f"warnings={len(self.warnings)}")
        return ', '.join(parts)


# =============================================================================
# SAFE FIELD EXTRACTION
# =============================================================================

def _safe_get(obj, field_name: str, expected_type=None, default=None):
    """
    Safely extract a field from any object with type coercion.
    Never throws. Returns default on any error.
    """
    try:
        value = getattr(obj, field_name, default)
        if value is None:
            return default
        if isinstance(value, float) and pd.isna(value):
            return default
        if expected_type is None:
            return value
        if expected_type == float:
            return float(value)
        if expected_type == int:
            return int(float(value))
        if expected_type == str:
            return str(value) if value is not None else default
        return value
    except (TypeError, ValueError, AttributeError):
        return default


def _safe_date(value) -> Optional[date]:
    """Convert various date types to date. Returns None on failure."""
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, pd.Timestamp):
        return value.date() if not pd.isna(value) else None
    if isinstance(value, str):
        try:
            return datetime.strptime(value[:10], '%Y-%m-%d').date()
        except (ValueError, IndexError):
            pass
    return None


# =============================================================================
# VALIDATE GAP RESULT STRUCTURE
# =============================================================================

def validate_gap_result_for_production(gap_result) -> ValidationResult:
    """
    Validate that a GAP result has the attributes Production Planning needs.

    Checks:
    - Object is not None
    - Has mo_suggestions attribute (list)
    - Has classification_df (for BOM info)
    - Has fg_gap_df (for at_risk_value, customer_count)
    - Has bom_explosion_df (for material requirements)
    """
    vr = ValidationResult()

    if gap_result is None:
        vr.add_error("GAP result is None")
        return vr

    # mo_suggestions — required
    if not hasattr(gap_result, 'mo_suggestions'):
        vr.add_error(
            "GAP result missing 'mo_suggestions'. "
            "Available: " + str([a for a in dir(gap_result) if not a.startswith('_')][:15])
        )
        return vr

    mo_suggestions = getattr(gap_result, 'mo_suggestions', None) or []
    if not isinstance(mo_suggestions, list):
        vr.add_error(f"mo_suggestions is not a list: {type(mo_suggestions)}")
        return vr

    if len(mo_suggestions) == 0:
        vr.add_warning("mo_suggestions is empty — no manufacturing products with shortage")

    # classification_df — needed for BOM info
    classification_df = getattr(gap_result, 'classification_df', None)
    if classification_df is None or (isinstance(classification_df, pd.DataFrame) and classification_df.empty):
        vr.add_warning(
            "classification_df missing or empty — "
            "BOM info (bom_id, bom_type, bom_output_qty) will be incomplete"
        )

    # fg_gap_df — needed for at_risk_value, customer_count
    fg_gap_df = getattr(gap_result, 'fg_gap_df', None)
    if fg_gap_df is None or (isinstance(fg_gap_df, pd.DataFrame) and fg_gap_df.empty):
        vr.add_warning(
            "fg_gap_df missing or empty — at_risk_value and customer_count will be 0"
        )

    # bom_explosion_df — needed for material requirements
    bom_df = getattr(gap_result, 'bom_explosion_df', None)
    if bom_df is None or (isinstance(bom_df, pd.DataFrame) and bom_df.empty):
        vr.add_warning(
            "bom_explosion_df missing or empty — material readiness check will be limited"
        )

    return vr


# =============================================================================
# EXTRACT PRODUCTION INPUTS (mo_suggestions → ProductionInputItem)
# =============================================================================

def extract_production_inputs(
    gap_result,
) -> Tuple[List[ProductionInputItem], ValidationResult]:
    """
    Safely extract manufacturing shortage items from GAP result and convert
    to typed ProductionInputItem list.

    Steps:
    1. Validate GAP result structure
    2. Build lookup tables from classification_df, fg_gap_df
    3. Extract demand dates from period data
    4. Convert each mo_suggestion → ProductionInputItem
    5. Skip items with missing required fields (product_id, quantity)

    Returns: (items, validation_result)
    """
    vr = validate_gap_result_for_production(gap_result)
    if not vr.is_valid:
        return [], vr

    mo_suggestions = getattr(gap_result, 'mo_suggestions', []) or []
    if not mo_suggestions:
        vr.items_extracted = 0
        return [], vr

    # Build lookups
    bom_lookup = _build_bom_lookup(gap_result)
    gap_lookup = _build_gap_lookup(gap_result)
    demand_dates = extract_demand_dates(gap_result)
    status_lookup = _build_production_status_lookup(gap_result)

    items = []
    for i, action in enumerate(mo_suggestions):
        try:
            item = _convert_action(action, i, bom_lookup, gap_lookup,
                                   demand_dates, status_lookup, vr)
            if item is not None:
                items.append(item)
                vr.items_extracted += 1
            else:
                vr.items_skipped += 1
        except Exception as e:
            vr.add_warning(f"mo_suggestions[{i}]: unexpected error: {e}")
            vr.items_skipped += 1

    logger.info(f"Production input extraction: {vr.summary()}")
    if vr.warnings:
        for w in vr.warnings[:10]:
            logger.warning(f"  ⚠️ {w}")
        if len(vr.warnings) > 10:
            logger.warning(f"  ... and {len(vr.warnings) - 10} more warnings")

    return items, vr


def _convert_action(
    action, index: int,
    bom_lookup: Dict, gap_lookup: Dict,
    demand_dates: Dict, status_lookup: Dict,
    vr: ValidationResult,
) -> Optional[ProductionInputItem]:
    """Convert one ActionRecommendation to ProductionInputItem."""

    if action is None:
        vr.add_warning(f"mo_suggestions[{index}]: action is None")
        return None

    # Required: product_id
    product_id = _safe_get(action, 'product_id', int, None)
    if product_id is None:
        vr.add_warning(f"mo_suggestions[{index}]: product_id is None")
        return None

    # Required: quantity (shortage)
    quantity = _safe_get(action, 'quantity', float, 0.0)
    if abs(quantity) <= 0:
        vr.add_warning(f"mo_suggestions[{index}]: quantity={quantity} ≤ 0, skipping")
        return None

    # BOM info from classification_df
    bom_info = bom_lookup.get(product_id, {})
    bom_type = bom_info.get('bom_type', '')

    # Validate BOM type
    from .production_constants import VALID_BOM_TYPES
    if bom_type and bom_type not in VALID_BOM_TYPES:
        vr.add_warning(
            f"mo_suggestions[{index}] ({_safe_get(action, 'pt_code', str, '')}): "
            f"unknown bom_type='{bom_type}'"
        )

    # GAP metrics
    gap_info = gap_lookup.get(product_id, {})

    # Production status
    status_info = status_lookup.get(product_id, {})

    return ProductionInputItem(
        product_id=product_id,
        pt_code=_safe_get(action, 'pt_code', str, ''),
        product_name=_safe_get(action, 'product_name', str, ''),
        brand=_safe_get(action, 'brand', str, ''),
        package_size=_safe_get(action, 'package_size', str, ''),
        uom=_safe_get(action, 'uom', str, ''),
        shortage_qty=abs(quantity),
        at_risk_value=gap_info.get('at_risk_value', 0.0),
        customer_count=gap_info.get('customer_count', 0),
        bom_id=bom_info.get('bom_id', 0),
        bom_code=bom_info.get('bom_code', ''),
        bom_type=bom_type,
        bom_output_qty=bom_info.get('bom_output_qty', 1.0),
        demand_date=demand_dates.get(product_id),
        has_sales_order=False,  # set later from existing_mo_summary
        gap_production_status=status_info.get('status', ''),
        gap_limiting_materials=status_info.get('limiting_materials', []),
    )


# =============================================================================
# LOOKUP BUILDERS
# =============================================================================

def _build_bom_lookup(gap_result) -> Dict[int, Dict[str, Any]]:
    """
    Build product_id → BOM info from classification_df.

    Extracts: bom_id, bom_code, bom_type, bom_output_qty
    """
    df = getattr(gap_result, 'classification_df', None)
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return {}

    lookup = {}
    for _, row in df.iterrows():
        pid = row.get('product_id')
        if pid is None or pd.isna(pid):
            continue
        lookup[int(pid)] = {
            'bom_id': int(row.get('bom_id', 0) or 0) if pd.notna(row.get('bom_id')) else 0,
            'bom_code': str(row.get('bom_code', '')) if pd.notna(row.get('bom_code')) else '',
            'bom_type': str(row.get('bom_type', '')) if pd.notna(row.get('bom_type')) else '',
            'bom_output_qty': float(row.get('bom_output_quantity', 1) or 1)
                if pd.notna(row.get('bom_output_quantity')) else 1.0,
        }
    return lookup


def _build_gap_lookup(gap_result) -> Dict[int, Dict[str, Any]]:
    """
    Build product_id → GAP metrics from fg_gap_df.

    Extracts: at_risk_value, customer_count
    """
    df = getattr(gap_result, 'fg_gap_df', None)
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return {}

    lookup = {}
    for _, row in df.iterrows():
        pid = row.get('product_id')
        if pid is None or pd.isna(pid):
            continue
        lookup[int(pid)] = {
            'at_risk_value': float(row.get('at_risk_value', 0) or 0),
            'customer_count': int(row.get('customer_count', 0) or 0),
        }
    return lookup


def _build_production_status_lookup(gap_result) -> Dict[int, Dict[str, Any]]:
    """
    Build product_id → production status from GAP's get_all_production_statuses.

    Extracts: can_produce, status, reason, limiting_materials
    """
    fn = getattr(gap_result, 'get_all_production_statuses', None)
    if fn is None or not callable(fn):
        return {}

    try:
        all_statuses = fn()
        if not isinstance(all_statuses, dict):
            return {}
        return all_statuses
    except Exception as e:
        logger.debug(f"Could not get production statuses: {e}")
        return {}


# =============================================================================
# DEMAND DATE EXTRACTION
# =============================================================================

def extract_demand_dates(gap_result) -> Dict[int, date]:
    """
    Extract earliest demand date per product from GAP period data.

    Priority:
    1. fg_period_gap_df — first shortage period per product
    2. None — caller uses config.planning_horizon_days as fallback

    Returns: Dict[product_id → date]
    """
    dates: Dict[int, date] = {}

    if gap_result is None:
        return dates

    period_df = getattr(gap_result, 'fg_period_gap_df', None)
    if period_df is not None and isinstance(period_df, pd.DataFrame) and not period_df.empty:
        if 'product_id' in period_df.columns and 'gap_quantity' in period_df.columns:
            try:
                shortage = period_df[period_df['gap_quantity'] < 0].copy()
                if not shortage.empty and 'period' in shortage.columns:
                    for pid in shortage['product_id'].unique():
                        prod_shortage = shortage[shortage['product_id'] == pid]
                        if prod_shortage.empty:
                            continue
                        first_period = prod_shortage.iloc[0]['period']
                        approx_date = _period_to_date(first_period)
                        if approx_date:
                            dates[int(pid)] = approx_date
            except Exception as e:
                logger.debug(f"Could not extract dates from FG period gap: {e}")

    logger.info(f"Extracted demand dates for {len(dates)} products from GAP period data")
    return dates


def _period_to_date(period_str: str) -> Optional[date]:
    """
    Convert period string → approximate date.
    'Week 15 - 2026' → Monday of that ISO week
    'Apr 2026' → first of that month
    """
    if not period_str or pd.isna(period_str):
        return None

    s = str(period_str).strip()
    try:
        if 'Week' in s and ' - ' in s:
            parts = s.split(' - ')
            week = int(parts[0].replace('Week ', '').strip())
            year = int(parts[1].strip())
            return date.fromisocalendar(year, week, 1)

        try:
            dt = datetime.strptime(f"01 {s}", "%d %b %Y")
            return dt.date()
        except ValueError:
            pass
    except Exception:
        pass

    return None


# =============================================================================
# MATERIAL REQUIREMENT EXTRACTION
# =============================================================================

def extract_material_requirements(
    gap_result,
    product_id: int,
    shortage_qty: float,
    bom_output_qty: float,
) -> List[MaterialRequirement]:
    """
    Extract BOM materials for a specific product from GAP's bom_explosion_df.

    Calculates required_qty per material:
      required_qty = (shortage_qty / bom_output_qty) × qty_per_output × (1 + scrap/100)

    Returns: List[MaterialRequirement]
    """
    bom_df = getattr(gap_result, 'bom_explosion_df', None)
    if bom_df is None or not isinstance(bom_df, pd.DataFrame) or bom_df.empty:
        return []

    id_col = 'output_product_id' if 'output_product_id' in bom_df.columns else 'fg_product_id'
    product_bom = bom_df[bom_df[id_col] == product_id]

    if product_bom.empty:
        return []

    materials = []
    bom_out = max(bom_output_qty, 0.001)  # prevent division by zero

    for _, row in product_bom.iterrows():
        qty_per = float(row.get('quantity_per_output', 1) or 1)
        scrap = float(row.get('scrap_rate', 0) or 0)
        effective = qty_per * (1 + scrap / 100)
        required = (shortage_qty / bom_out) * effective

        mat = MaterialRequirement(
            material_id=int(row.get('material_id', 0)),
            material_pt_code=str(row.get('material_pt_code', '')),
            material_name=str(row.get('material_name', '')),
            material_uom=str(row.get('material_uom', '')),
            material_type=str(row.get('material_type', 'RAW_MATERIAL')),
            is_primary=bool(row.get('is_primary', 1) in [1, True]),
            alternative_priority=int(row.get('alternative_priority', 0) or 0),
            primary_material_id=(
                int(row['primary_material_id'])
                if pd.notna(row.get('primary_material_id')) else None
            ),
            quantity_per_output=qty_per,
            scrap_rate=scrap,
            effective_qty_per_output=effective,
            bom_output_qty=bom_out,
            required_qty=round(required, 4),
        )
        materials.append(mat)

    return materials


# =============================================================================
# GAP FILTER VALIDATION (Informed Consent — same pattern as PO Planning)
# =============================================================================

def validate_gap_filters_for_production(gap_result) -> Dict[str, Any]:
    """
    Review GAP filters relevant to Production Planning.

    Same "informed consent" model as PO Planning:
    - Never blocks execution
    - Classifies risk
    - Returns structured review for UI

    Production Planning cares about:
    - MO_EXPECTED in supply sources (affects FG shortage level → MO suggestion qty)
    - Existing MO Demand (affects raw material GAP → material readiness accuracy)
    - Include Alternatives (affects material readiness check)
    - Track Backlog (affects demand date accuracy from period data)
    """
    review = {
        'all_complete': True,
        'has_high_risk': False,
        'items': [],
        'filters_used': {},
        'summary_text': '',
    }

    if gap_result is None:
        review['all_complete'] = False
        review['has_high_risk'] = True
        review['items'].append({
            'filter': 'GAP Result', 'label': 'GAP Result',
            'status': 'MISSING', 'risk': 'HIGH',
            'consequence': 'No GAP result — run Supply Chain GAP first',
        })
        review['summary_text'] = 'No GAP result'
        return review

    filters = getattr(gap_result, 'filters_used', None)
    if not filters:
        review['summary_text'] = 'Filter metadata unavailable — proceed with caution'
        return review

    review['filters_used'] = dict(filters)

    # Key checks for Production Planning
    supply_on = filters.get('supply_sources') or []

    # MO_EXPECTED — affects FG shortage qty
    if 'MO_EXPECTED' not in supply_on:
        review['all_complete'] = False
        review['items'].append({
            'filter': 'MO_EXPECTED', 'label': 'MO Expected Output',
            'category': 'Supply Source', 'status': 'OFF', 'risk': 'MEDIUM',
            'consequence': (
                'MO output not in FG supply → FG shortage is higher → '
                'MO suggestions will be larger than necessary'
            ),
        })

    # INVENTORY — critical
    if 'INVENTORY' not in supply_on:
        review['all_complete'] = False
        review['has_high_risk'] = True
        review['items'].append({
            'filter': 'INVENTORY', 'label': 'Inventory',
            'category': 'Supply Source', 'status': 'OFF', 'risk': 'HIGH',
            'consequence': 'Stock not counted → shortage overstated → MO suggestions inflated',
        })

    # PURCHASE_ORDER — critical
    if 'PURCHASE_ORDER' not in supply_on:
        review['all_complete'] = False
        review['has_high_risk'] = True
        review['items'].append({
            'filter': 'PURCHASE_ORDER', 'label': 'Purchase Order',
            'category': 'Supply Source', 'status': 'OFF', 'risk': 'HIGH',
            'consequence': 'Pending POs not counted → may suggest MO for products with PO arriving',
        })

    # Alternatives — affects material readiness
    if not filters.get('include_alternatives', True):
        review['all_complete'] = False
        review['items'].append({
            'filter': 'include_alternatives', 'label': 'Alternatives',
            'category': 'Option', 'status': 'OFF', 'risk': 'MEDIUM',
            'consequence': 'Alternative materials not in BOM data → material readiness check incomplete',
        })

    # Track backlog — affects demand date accuracy
    if filters.get('track_backlog') is False:
        review['all_complete'] = False
        review['items'].append({
            'filter': 'track_backlog', 'label': 'Track Backlog',
            'category': 'Period Analysis', 'status': 'OFF', 'risk': 'MEDIUM',
            'consequence': 'Backlog not carried forward → demand dates less accurate',
        })

    # Summary
    if review['all_complete']:
        review['summary_text'] = '✅ GAP config complete for Production Planning'
    else:
        count = len(review['items'])
        high = sum(1 for i in review['items'] if i.get('risk') == 'HIGH')
        review['summary_text'] = (
            f"{count} filter deviation(s)"
            + (f" ({high} high-risk)" if high else "")
            + " — MO suggestions may not reflect full picture"
        )

    return review
