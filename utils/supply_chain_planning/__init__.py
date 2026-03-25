# utils/supply_chain_planning/__init__.py

"""
Supply Chain Planning Module — v1.1.0
Phase 1: PO Suggestion by Vendor

v1.1.0 Changes:
- Added validators.py (cross-module data contract enforcement)
- Adaptive lead time buffer (calibrated to vendor avg_delay_days)
- Item-level error handling in PO planner (no single-item crash)
- Professional Excel export formatting (openpyxl styles)
"""

from .planning_constants import (
    VERSION,
    URGENCY_LEVELS, URGENCY_THRESHOLDS,
    LEAD_TIME_DEFAULTS, LEAD_TIME_BUFFER_DAYS, LEAD_TIME_BUFFER_ADAPTIVE,
    VENDOR_RELIABILITY,
    MOQ_SPQ_CONFIG, PRICE_SOURCE, SHORTAGE_SOURCE,
    PO_SUGGESTION_STATUS, PO_PLANNING_UI,
)
from .planning_data_loader import PlanningDataLoader, get_planning_data_loader
from .po_pricing_resolver import POPricingResolver, VendorMatch, QuantitySuggestion
from .po_lead_time_calculator import (
    POLeadTimeCalculator, LeadTimeResult, OrderTimingResult
)
from .po_result import POLineItem, VendorPOGroup, POSuggestionResult
from .po_planner import POPlanner, ShortageItem
from .po_planning_export import export_po_suggestions_to_excel, get_po_export_filename
from .validators import (
    validate_gap_result, extract_all_shortages, safe_extract_shortage,
    safe_extract_field, ValidationResult
)

# UI components loaded lazily (require streamlit at runtime)
# from .po_planning_components import po_overview_fragment, ...

__version__ = VERSION