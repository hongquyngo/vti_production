# utils/supply_chain_planning/validators.py

"""
Validation layer between Supply Chain GAP and PO Planning modules.

Provides:
1. Type-safe extraction of shortage items from GAP result
2. Null/type guards at module boundary
3. Validation of ActionRecommendation fields before processing
4. Detailed error reporting for debugging integration issues

This module exists because GAP and PO Planning are separate modules with
an implicit data contract via ActionRecommendation dataclass. Any field
rename or type change in GAP would silently break PO Planning without
this validation layer.
"""

import pandas as pd
import logging
from datetime import date, datetime
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# =============================================================================
# EXPECTED FIELD CONTRACTS
# =============================================================================

# Fields expected on ActionRecommendation from GAP module
# (field_name, expected_type, required, default_value)
ACTION_RECOMMENDATION_FIELDS = {
    'product_id':    (int,   True,  None),
    'pt_code':       (str,   False, ''),
    'product_name':  (str,   False, ''),
    'quantity':      (float, True,  0.0),
    'uom':           (str,   False, ''),
    'priority':      (int,   False, 99),
    'reason':        (str,   False, ''),
    'brand':         (str,   False, ''),
    'package_size':  (str,   False, ''),
    'action_type':   (str,   False, ''),
}

# Fields expected on SupplyChainGAPResult
GAP_RESULT_FIELDS = {
    'po_fg_suggestions':  (list, False, []),
    'po_raw_suggestions': (list, False, []),
    'mo_suggestions':     (list, False, []),
}


# =============================================================================
# VALIDATION RESULT
# =============================================================================

@dataclass
class ValidationResult:
    """Result of validation — tracks warnings and errors separately"""
    is_valid: bool = True
    errors: List[str] = None
    warnings: List[str] = None
    items_extracted: int = 0
    items_skipped: int = 0
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []
        if self.warnings is None:
            self.warnings = []
    
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
# CORE: VALIDATE GAP RESULT STRUCTURE
# =============================================================================

def validate_gap_result(gap_result) -> ValidationResult:
    """
    Validate that a GAP result object has the expected structure
    for PO Planning consumption.
    
    Checks:
    - Object is not None
    - Has po_fg_suggestions and/or po_raw_suggestions attributes
    - Each suggestion has required fields (product_id, quantity)
    
    Returns:
        ValidationResult with errors/warnings
    """
    vr = ValidationResult()
    
    if gap_result is None:
        vr.add_error("GAP result is None")
        return vr
    
    # Check top-level attributes
    has_fg = hasattr(gap_result, 'po_fg_suggestions')
    has_raw = hasattr(gap_result, 'po_raw_suggestions')
    
    if not has_fg and not has_raw:
        vr.add_error(
            "GAP result has neither 'po_fg_suggestions' nor 'po_raw_suggestions' attribute. "
            f"Available attributes: {[a for a in dir(gap_result) if not a.startswith('_')][:20]}"
        )
        return vr
    
    if not has_fg:
        vr.add_warning("GAP result missing 'po_fg_suggestions' — no Trading FG shortcuts will be processed")
    if not has_raw:
        vr.add_warning("GAP result missing 'po_raw_suggestions' — no Raw Material shortcuts will be processed")
    
    # Validate individual suggestions
    fg_suggestions = getattr(gap_result, 'po_fg_suggestions', []) or []
    raw_suggestions = getattr(gap_result, 'po_raw_suggestions', []) or []
    
    for i, action in enumerate(fg_suggestions):
        _validate_action(action, f"po_fg_suggestions[{i}]", vr)
    
    for i, action in enumerate(raw_suggestions):
        _validate_action(action, f"po_raw_suggestions[{i}]", vr)
    
    vr.items_extracted = len(fg_suggestions) + len(raw_suggestions)
    
    return vr


def _validate_action(action, path: str, vr: ValidationResult):
    """Validate a single ActionRecommendation object.
    
    Individual action issues are recorded as WARNINGS (not errors).
    Only structural issues at the GAP result level are errors.
    Bad items will be skipped during extraction, not halt the whole batch.
    """
    
    if action is None:
        vr.add_warning(f"{path}: action is None — will be skipped")
        return
    
    # Check required fields
    for field_name, (expected_type, required, default) in ACTION_RECOMMENDATION_FIELDS.items():
        value = getattr(action, field_name, None)
        
        if required and value is None:
            vr.add_warning(f"{path}.{field_name}: required field is None — item will be skipped")
            continue
        
        if value is not None and not isinstance(value, (expected_type, type(None))):
            # Allow numeric coercion (int ↔ float)
            if expected_type in (int, float) and isinstance(value, (int, float)):
                continue
            vr.add_warning(
                f"{path}.{field_name}: expected {expected_type.__name__}, "
                f"got {type(value).__name__} (value={value!r})"
            )
    
    # Business rule: quantity should be non-zero
    qty = getattr(action, 'quantity', None)
    if qty is not None and abs(qty) <= 0:
        vr.add_warning(f"{path}: quantity={qty} = 0 — will result in zero PO suggestion")


# =============================================================================
# SAFE EXTRACTION — Used by POPlanner instead of raw attribute access
# =============================================================================

def safe_extract_field(obj, field_name: str, expected_type=None, default=None):
    """
    Safely extract a field from an object with type coercion.
    
    Unlike raw getattr, this:
    - Handles None objects gracefully
    - Coerces types (str→float, int→float, etc.) 
    - Returns default on any error
    - Never throws
    """
    try:
        value = getattr(obj, field_name, default)
        
        if value is None:
            return default
        
        # Handle pandas NaN/NaT
        if isinstance(value, float) and pd.isna(value):
            return default
        
        if expected_type is None:
            return value
        
        # Type coercion
        if expected_type == float:
            return float(value)
        elif expected_type == int:
            return int(float(value))  # handles "123.0" strings
        elif expected_type == str:
            return str(value) if value is not None else default
        
        return value
    except (TypeError, ValueError, AttributeError) as e:
        logger.debug(f"safe_extract_field({field_name}): {e}, returning default={default}")
        return default


def safe_extract_shortage(action, shortage_source: str) -> Optional[Dict[str, Any]]:
    """
    Safely extract a shortage item from an ActionRecommendation.
    
    Returns dict with all fields guaranteed to be the correct type,
    or None if the action is fundamentally invalid (no product_id or quantity).
    
    This is the SINGLE POINT where GAP module's ActionRecommendation
    is converted to PO Planning's internal format.
    """
    if action is None:
        return None
    
    # Required fields — if these are missing/invalid, skip the item
    product_id = safe_extract_field(action, 'product_id', int, None)
    if product_id is None:
        logger.warning(f"Skipping action: product_id is None or invalid")
        return None
    
    quantity = safe_extract_field(action, 'quantity', float, 0.0)
    if abs(quantity) <= 0:
        logger.debug(f"Skipping action product_id={product_id}: quantity={quantity} = 0")
        return None
    
    # Optional fields — defaults if missing
    return {
        'product_id': product_id,
        'pt_code': safe_extract_field(action, 'pt_code', str, ''),
        'product_name': safe_extract_field(action, 'product_name', str, ''),
        'brand': safe_extract_field(action, 'brand', str, ''),
        'package_size': safe_extract_field(action, 'package_size', str, ''),
        'uom': safe_extract_field(action, 'uom', str, ''),
        'shortage_qty': abs(quantity),
        'shortage_source': shortage_source,
        'priority': safe_extract_field(action, 'priority', int, 99),
    }


def extract_all_shortages(
    gap_result,
    include_fg: bool = True,
    include_raw: bool = True
) -> Tuple[List[Dict[str, Any]], ValidationResult]:
    """
    Extract and validate ALL shortage items from a GAP result.
    
    This is the validated extraction used by POPlanner.plan_from_gap_result()
    instead of raw attribute access.
    
    Returns:
        (shortage_dicts, validation_result)
        
    Each dict in shortage_dicts has guaranteed types:
        product_id: int
        pt_code: str
        product_name: str
        brand: str
        package_size: str
        uom: str
        shortage_qty: float (positive)
        shortage_source: str ('FG_TRADING' or 'RAW_MATERIAL')
        priority: int
    """
    vr = validate_gap_result(gap_result)
    
    if not vr.is_valid:
        logger.error(f"GAP result validation failed: {vr.errors}")
        return [], vr
    
    shortages = []
    
    # Extract FG Trading shortages
    if include_fg:
        fg_suggestions = getattr(gap_result, 'po_fg_suggestions', []) or []
        for action in fg_suggestions:
            item = safe_extract_shortage(action, 'FG_TRADING')
            if item is not None:
                shortages.append(item)
            else:
                vr.items_skipped += 1
    
    # Extract Raw Material shortages
    if include_raw:
        raw_suggestions = getattr(gap_result, 'po_raw_suggestions', []) or []
        for action in raw_suggestions:
            item = safe_extract_shortage(action, 'RAW_MATERIAL')
            if item is not None:
                shortages.append(item)
            else:
                vr.items_skipped += 1
    
    # Sort by priority (most urgent first)
    shortages.sort(key=lambda s: s['priority'])
    
    vr.items_extracted = len(shortages)
    
    logger.info(
        f"Shortage extraction: {vr.summary()} "
        f"({sum(1 for s in shortages if s['shortage_source'] == 'FG_TRADING')} FG, "
        f"{sum(1 for s in shortages if s['shortage_source'] == 'RAW_MATERIAL')} Raw)"
    )
    
    if vr.warnings:
        for w in vr.warnings:
            logger.warning(f"  ⚠️ {w}")
    
    return shortages, vr


# =============================================================================
# FILTER CONTEXT VALIDATION — "Informed Consent" model
# =============================================================================
# Never blocks. Classifies risk, explains consequences, lets user decide.
# User may intentionally disable filters (e.g. no Forecast = only firm orders).
# =============================================================================

# All possible supply sources and their PO Planning impact when OFF
SUPPLY_SOURCE_IMPACT = {
    'PURCHASE_ORDER': {
        'label': 'Purchase Order',
        'icon': '📝',
        'risk': 'HIGH',
        'consequence': 'Shortage does NOT account for existing POs → may create DUPLICATE orders',
    },
    'INVENTORY': {
        'label': 'Inventory',
        'icon': '📦',
        'risk': 'HIGH',
        'consequence': 'Shortage does NOT account for warehouse stock → may buy items already in stock',
    },
    'CAN_PENDING': {
        'label': 'CAN Pending',
        'icon': '📋',
        'risk': 'MEDIUM',
        'consequence': 'Pre-confirmed supply not counted → PO quantities slightly overstated',
    },
    'WAREHOUSE_TRANSFER': {
        'label': 'Warehouse Transfer',
        'icon': '🚛',
        'risk': 'MEDIUM',
        'consequence': 'In-transit stock not counted → PO quantities slightly overstated',
    },
    'MO_EXPECTED': {
        'label': 'MO Expected',
        'icon': '🏭',
        'risk': 'MEDIUM',
        'consequence': 'Manufacturing output not in FG supply → FG shortage higher → raw material PO inflated',
    },
}

DEMAND_SOURCE_IMPACT = {
    'OC_PENDING': {
        'label': 'Confirmed Orders',
        'icon': '✔',
        'risk': 'INFO',
        'consequence': 'Confirmed customer orders not in demand → shortage understated',
    },
    'FORECAST': {
        'label': 'Forecast',
        'icon': '📊',
        'risk': 'INFO',
        'consequence': 'Only covers confirmed demand, not forecast — may be intentional',
    },
}

OPTION_IMPACT = {
    'include_fg_safety': {
        'label': 'FG Safety Stock',
        'risk': 'INFO',
        'consequence_when_off': 'No safety buffer → shortage is minimum-only (no safety margin)',
    },
    'include_raw_safety': {
        'label': 'Raw Safety Stock',
        'risk': 'INFO',
        'consequence_when_off': 'Raw material safety stock not considered',
    },
    'include_existing_mo': {
        'label': 'Existing MO Demand',
        'risk': 'MEDIUM',
        'consequence_when_off': 'Raw demand from existing MOs not included → raw PO may be too low',
    },
    'exclude_expired': {
        'label': 'Exclude Expired',
        'risk': 'INFO',
        'consequence_when_off': 'Expired stock counted in supply — may overstate availability',
    },
}


def validate_gap_filters(gap_result) -> Dict[str, Any]:
    """
    Review GAP filters for PO Planning — "Informed Consent" model.
    
    NEVER blocks execution. Instead:
    - Classifies each disabled filter by risk level (HIGH / MEDIUM / INFO)
    - Explains the consequence for PO Planning
    - Returns structured review for UI to display
    - User decides whether to proceed
    
    Returns:
        Dict with:
        - all_complete: bool — True if all filters ON (auto-proceed, no confirm needed)
        - has_high_risk: bool — True if any HIGH risk filter is OFF
        - items: List[Dict] — each disabled filter with risk/consequence
        - filters_used: Dict — raw filters from GAP result
        - supply_sources_on: List[str]
        - supply_sources_off: List[str]
        - demand_sources_on: List[str]
        - demand_sources_off: List[str]
        - options_off: List[Dict]
        - entity: str or None
        - summary_text: str — human-readable one-liner
    """
    review = {
        'all_complete': True,
        'has_high_risk': False,
        'has_filter_data': False,
        'items': [],
        'filters_used': {},
        'supply_sources_on': [],
        'supply_sources_off': [],
        'demand_sources_on': [],
        'demand_sources_off': [],
        'options_off': [],
        'entity': None,
        'summary_text': '',
    }
    
    if gap_result is None:
        review['all_complete'] = False
        review['has_high_risk'] = True
        review['items'].append({
            'filter': 'GAP Result',
            'label': 'GAP Result',
            'status': 'MISSING',
            'risk': 'HIGH',
            'consequence': 'No GAP result available — run Supply Chain GAP first',
            'icon': '🚫',
        })
        review['summary_text'] = 'No GAP result — run Supply Chain GAP first'
        return review
    
    filters = getattr(gap_result, 'filters_used', None)
    if not filters:
        # Can't verify — proceed with caution
        review['items'].append({
            'filter': 'filters_used',
            'label': 'Filter Data',
            'status': 'UNKNOWN',
            'risk': 'INFO',
            'consequence': 'GAP result has no filter metadata — cannot verify completeness',
            'icon': 'ℹ️',
        })
        review['summary_text'] = 'Filter metadata unavailable — proceed with caution'
        return review
    
    review['has_filter_data'] = True
    review['filters_used'] = dict(filters)
    review['entity'] = filters.get('entity', None)
    
    # Check supply sources
    supply_on = filters.get('supply_sources') or []
    for source_key, impact in SUPPLY_SOURCE_IMPACT.items():
        if source_key in supply_on:
            review['supply_sources_on'].append(source_key)
        else:
            review['supply_sources_off'].append(source_key)
            review['all_complete'] = False
            if impact['risk'] == 'HIGH':
                review['has_high_risk'] = True
            review['items'].append({
                'filter': source_key,
                'label': impact['label'],
                'category': 'Supply Source',
                'status': 'OFF',
                'risk': impact['risk'],
                'consequence': impact['consequence'],
                'icon': impact['icon'],
            })
    
    # Check demand sources
    demand_on = filters.get('demand_sources') or []
    for source_key, impact in DEMAND_SOURCE_IMPACT.items():
        if source_key in demand_on:
            review['demand_sources_on'].append(source_key)
        else:
            review['demand_sources_off'].append(source_key)
            review['all_complete'] = False
            review['items'].append({
                'filter': source_key,
                'label': impact['label'],
                'category': 'Demand Source',
                'status': 'OFF',
                'risk': impact['risk'],
                'consequence': impact['consequence'],
                'icon': impact['icon'],
            })
    
    # Check options
    for opt_key, impact in OPTION_IMPACT.items():
        val = filters.get(opt_key)
        if val is False or val == 0:
            review['options_off'].append({'key': opt_key, **impact})
            review['all_complete'] = False
            review['items'].append({
                'filter': opt_key,
                'label': impact['label'],
                'category': 'Option',
                'status': 'OFF',
                'risk': impact['risk'],
                'consequence': impact.get('consequence_when_off', ''),
                'icon': '⚙️',
            })
    
    # MO Expected + Existing MO consistency
    if 'MO_EXPECTED' not in supply_on and filters.get('include_existing_mo', False):
        review['items'].append({
            'filter': 'MO_EXPECTED+EXISTING_MO',
            'label': 'MO Double-Count Risk',
            'category': 'Consistency',
            'status': 'WARN',
            'risk': 'MEDIUM',
            'consequence': 'MO Expected OFF + Existing MO ON → raw material demand may double-count',
            'icon': '⚠️',
        })
        review['all_complete'] = False
    
    # Build summary text
    off_count = len(review['items'])
    if off_count == 0:
        review['summary_text'] = '✅ All filters complete — PO quantities are fully informed'
    else:
        high_count = sum(1 for i in review['items'] if i['risk'] == 'HIGH')
        med_count = sum(1 for i in review['items'] if i['risk'] == 'MEDIUM')
        parts = []
        if high_count:
            parts.append(f'{high_count} high-risk')
        if med_count:
            parts.append(f'{med_count} medium')
        info_count = off_count - high_count - med_count
        if info_count:
            parts.append(f'{info_count} info')
        review['summary_text'] = f'{off_count} filters OFF ({", ".join(parts)}) — PO quantities may not reflect full picture'
    
    # Log
    if review['all_complete']:
        logger.info(f"Filter review: all complete")
    else:
        logger.info(f"Filter review: {review['summary_text']}")
        for item in review['items']:
            level = 'warning' if item['risk'] in ('HIGH', 'MEDIUM') else 'info'
            getattr(logger, level)(f"  {item['risk']} — {item['label']}: {item['consequence']}")
    
    return review


# =============================================================================
# DEMAND DATE EXTRACTION FROM GAP RESULT
# =============================================================================

def extract_demand_dates(gap_result) -> Dict[int, date]:
    """
    Extract earliest demand date per product from GAP result.
    
    Priority:
    1. fg_period_gap_df — has period-level shortage with dates
    2. Fallback: None (caller uses default planning horizon)
    
    This replaces the fixed "today + 30 days" approach which caused
    55%+ of items to show OVERDUE because 30 days < avg lead time.
    
    Returns:
        Dict mapping product_id → earliest demand date
    """
    
    dates = {}
    
    if gap_result is None:
        return dates
    
    # Try period gap data — has per-product per-period shortage
    period_df = getattr(gap_result, 'fg_period_gap_df', None)
    if period_df is not None and not period_df.empty and 'product_id' in period_df.columns:
        try:
            # Get first shortage period per product
            shortage = period_df[period_df['gap_quantity'] < 0].copy()
            if not shortage.empty and 'period' in shortage.columns:
                # Convert period string → approximate date
                for pid in shortage['product_id'].unique():
                    prod_shortage = shortage[shortage['product_id'] == pid]
                    # Take earliest period with shortage
                    first_period = prod_shortage.iloc[0]['period']
                    approx_date = _period_to_date(first_period)
                    if approx_date:
                        dates[int(pid)] = approx_date
        except Exception as e:
            logger.debug(f"Could not extract dates from period gap: {e}")
    
    # Also try raw period gap for material IDs
    raw_period_df = getattr(gap_result, 'raw_period_gap_df', None)
    if raw_period_df is not None and not raw_period_df.empty and 'material_id' in raw_period_df.columns:
        try:
            shortage = raw_period_df[raw_period_df['gap_quantity'] < 0].copy()
            if not shortage.empty and 'period' in shortage.columns:
                for mid in shortage['material_id'].unique():
                    if int(mid) not in dates:
                        mat_shortage = shortage[shortage['material_id'] == mid]
                        first_period = mat_shortage.iloc[0]['period']
                        approx_date = _period_to_date(first_period)
                        if approx_date:
                            dates[int(mid)] = approx_date
        except Exception as e:
            logger.debug(f"Could not extract dates from raw period gap: {e}")
    
    if dates:
        logger.info(f"Extracted demand dates for {len(dates)} products from GAP period data")
    
    return dates


def _period_to_date(period_str: str) -> Optional[date]:
    """
    Convert period string → approximate date.
    'Week 15 - 2026' → Monday of that week
    'Apr 2026' → first of that month
    """
    
    if not period_str or pd.isna(period_str):
        return None
    
    s = str(period_str).strip()
    
    try:
        # Weekly: "Week N - YYYY"
        if 'Week' in s and ' - ' in s:
            parts = s.split(' - ')
            week = int(parts[0].replace('Week ', '').strip())
            year = int(parts[1].strip())
            return date.fromisocalendar(year, week, 1)  # Monday of ISO week
        
        # Monthly: "Apr 2026"
        try:
            dt = datetime.strptime(f"01 {s}", "%d %b %Y")
            return dt.date()
        except ValueError:
            pass
    except Exception:
        pass
    
    return None

# =============================================================================
# DEMAND COMPOSITION — Confirmed Orders vs Forecast
# =============================================================================

def extract_demand_composition(gap_result) -> Dict[int, Dict[str, Any]]:
    """
    Extract demand composition per product: confirmed orders vs forecast.
    
    Reads fg_gap_df columns 'demand_oc_pending' and 'demand_forecast'.
    
    Returns:
        Dict mapping product_id -> {
            'has_confirmed': bool, 'has_forecast': bool,
            'confirmed_qty': float, 'forecast_qty': float,
            'demand_tag': str
        }
    """
    result = {}
    if gap_result is None:
        return result
    
    fg_gap = getattr(gap_result, 'fg_gap_df', None)
    if fg_gap is None or fg_gap.empty:
        return result
    
    has_oc = 'demand_oc_pending' in fg_gap.columns
    has_fc = 'demand_forecast' in fg_gap.columns
    if not has_oc and not has_fc:
        return result
    
    try:
        for _, row in fg_gap.iterrows():
            pid = row.get('product_id')
            if pid is None or pd.isna(pid):
                continue
            oc_qty = float(row.get('demand_oc_pending', 0) or 0) if has_oc else 0
            fc_qty = float(row.get('demand_forecast', 0) or 0) if has_fc else 0
            has_confirmed = oc_qty > 0
            has_forecast = fc_qty > 0
            if has_confirmed and has_forecast:
                tag = 'Confirmed+Forecast'
            elif has_confirmed:
                tag = 'Confirmed'
            elif has_forecast:
                tag = 'Forecast Only'
            else:
                tag = ''
            result[int(pid)] = {
                'has_confirmed': has_confirmed, 'has_forecast': has_forecast,
                'confirmed_qty': oc_qty, 'forecast_qty': fc_qty, 'demand_tag': tag,
            }
    except Exception as e:
        logger.debug(f"Could not extract demand composition: {e}")
    
    return result