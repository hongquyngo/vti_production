# utils/supply_chain_gap/__init__.py
"""Supply Chain GAP Analysis Module — v2.3.1
Full multi-level analysis + Period GAP per tab with carry-forward
v2.3.1: Brand/product filter as display filter — Raw GAP always uses full data"""

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
    render_action_table, render_pagination,
    render_pivot_view, render_period_detail_table,
    show_product_detail_dialog, show_affected_customers_dialog,
    # Net GAP fragments
    fg_charts_fragment, fg_table_fragment,
    manufacturing_fragment, trading_fragment,
    raw_materials_fragment, actions_fragment,
    # Period GAP fragments (v2.3 — one per tab)
    fg_period_fragment, manufacturing_period_fragment,
    trading_period_fragment, raw_period_fragment,
    period_gap_fragment,  # backward compat alias
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
    get_period_sort_key, is_past_period, classify_product_type,
    create_pivot_data, filter_period_gap_by_product_ids,
    identify_critical_shortage_periods, identify_critical_shortage_products,
    get_product_period_timeline
)

__version__ = VERSION