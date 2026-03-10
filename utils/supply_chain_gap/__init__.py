# utils/supply_chain_gap/__init__.py

"""
Supply Chain GAP Analysis Module — v2.2.0
Full multi-level analysis + Period-based GAP with carry-forward
"""

from .constants import (
    VERSION, GAP_CATEGORIES, THRESHOLDS, STATUS_CONFIG,
    SUPPLY_SOURCES, DEMAND_SOURCES, PRODUCT_TYPES, BOM_TYPES,
    MATERIAL_TYPES, MATERIAL_CATEGORIES, MAX_BOM_LEVELS,
    ACTION_TYPES, RAW_MATERIAL_STATUS, UI_CONFIG,
    FIELD_TOOLTIPS, FORMULA_HELP, EXPORT_CONFIG,
    PERIOD_TYPES, PERIOD_CONFIG
)

from .state import SupplyChainStateManager, get_state

from .data_loader import SupplyChainDataLoader, get_data_loader

from .result import SupplyChainGAPResult, CustomerImpact, ActionRecommendation

from .calculator import SupplyChainGAPCalculator, get_calculator

from .filters import SupplyChainFilters, get_filters

from .components import (
    render_kpi_cards, render_status_summary, render_data_freshness,
    render_quick_filter, apply_quick_filter,
    render_fg_table, render_manufacturing_table, render_trading_table,
    render_raw_material_table, render_semi_finished_table,
    render_action_table, render_pagination, render_period_gap_table,
    show_product_detail_dialog, show_affected_customers_dialog,
    fg_charts_fragment, fg_table_fragment,
    manufacturing_fragment, trading_fragment,
    raw_materials_fragment, actions_fragment,
    period_gap_fragment,
)

from .help import (
    render_help_dialog, render_help_tab, render_help_popover,
    render_formula_help_section, render_field_tooltip
)

from .charts import SupplyChainCharts, get_charts

from .formatters import SupplyChainFormatter, get_formatter

from .export import export_to_excel, get_export_filename

from .period_calculator import (
    PeriodGAPCalculator, convert_to_period, format_period_display,
    get_period_sort_key, identify_critical_shortage_periods,
    identify_critical_shortage_products, get_product_period_timeline
)

__version__ = VERSION