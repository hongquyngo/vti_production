# utils/supply_chain_production/__init__.py

"""
Supply Chain Production Planning Module — v1.0.0
Layer 3 Phase 2: Manufacturing Order Suggestions

ZERO ASSUMPTION: All parameters from production_planning_config table.
No hardcoded defaults. Missing config = system stops with clear message.
"""

from .production_constants import (
    VERSION,
    BOM_TYPES, VALID_BOM_TYPES,
    READINESS_STATUS, MATERIAL_STATUS, COVERAGE_SOURCE,
    MO_URGENCY_LEVELS, MO_URGENCY_THRESHOLDS, URGENCY_LEVELS,
    MO_ACTION_TYPES, LEAD_TIME_SOURCE, YIELD_SOURCE,
    UNSCHEDULABLE_REASONS, CONFIG_GROUPS,
    PRODUCTION_UI,
)
from .production_config import (
    ProductionConfig, ProductionConfigLoader, get_config_loader,
)
from .production_interfaces import (
    ProductionInputItem, MaterialRequirement,
    MaterialReadiness, ProductReadiness, UnschedulableItem,
)
from .production_data_loader import (
    ProductionDataLoader, get_production_data_loader,
)
from .production_validators import (
    ValidationResult,
    validate_gap_result_for_production,
    extract_production_inputs,
    extract_demand_dates,
    extract_material_requirements,
    validate_gap_filters_for_production,
)
from .material_readiness_checker import MaterialReadinessChecker
from .mo_scheduling_engine import (
    MOSchedulingEngine,
    ConfigMissingError,
    LeadTimeResolution,
    YieldResolution,
    SchedulingResult,
)
from .mo_result import MOLineItem, MOSuggestionResult
from .mo_planner import MOPlanner
from .production_export import export_mo_suggestions_to_excel, get_mo_export_filename

__version__ = VERSION
