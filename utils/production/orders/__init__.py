# utils/production/orders/__init__.py
"""
Production Orders Module
Comprehensive order management with validation and pivot analysis

Version: 2.1.0

Components:
- queries.py: Database queries (OrderQueries)
- manager.py: Business logic with validation (OrderManager)
- validators.py: Comprehensive validation rules (OrderValidators)
- validation_ui.py: UI helpers for validation display
- forms.py: Create/Edit forms (OrderForms)
- dialogs.py: Action dialogs
- dashboard.py: Dashboard metrics
- pivot_view.py: Pivot analysis view
- page.py: Main page orchestrator
- common.py: Utilities and constants

Changes:
- v2.1.0: Added Pivot View for data analysis
          + OrderPivotView class for pivot table generation
          + render_pivot_view() convenience function
          + Time grouping: Daily, Weekly, Monthly, Quarterly
          + Multiple row dimensions and value metrics
"""

# Export main classes
from .queries import OrderQueries
from .manager import OrderManager
from .validators import (
    OrderValidators,
    ValidationResults,
    ValidationResult,
    ValidationLevel,
    validate_create_order,
    validate_edit_order,
    validate_confirm_order,
    validate_cancel_order,
    validate_delete_order
)
from .validation_ui import (
    ValidationUI,
    render_validation_blocks,
    render_validation_warnings,
    render_warning_acknowledgment,
    render_validation_summary
)
from .forms import OrderForms, render_create_form, render_edit_form
from .dialogs import (
    show_detail_dialog,
    show_edit_dialog,
    show_confirm_dialog,
    show_cancel_dialog,
    show_delete_dialog,
    show_pdf_dialog,
    check_pending_dialogs,
    handle_row_action
)
from .dashboard import OrderDashboard, render_dashboard
from .pivot_view import OrderPivotView, PivotViewConfig, render_pivot_view
from .page import render_orders_tab
from .common import (
    OrderConstants,
    OrderValidator,
    get_vietnam_now,
    get_vietnam_today,
    format_number,
    format_currency,
    format_date,
    format_datetime_vn,
    create_status_indicator,
    format_product_display,
    format_material_display,
    export_to_excel
)

__all__ = [
    # Main classes
    'OrderQueries',
    'OrderManager',
    'OrderValidators',
    'OrderForms',
    'OrderDashboard',
    'OrderPivotView',
    'PivotViewConfig',
    
    # Validation
    'ValidationResults',
    'ValidationResult',
    'ValidationLevel',
    'ValidationUI',
    'validate_create_order',
    'validate_edit_order',
    'validate_confirm_order',
    'validate_cancel_order',
    'validate_delete_order',
    'render_validation_blocks',
    'render_validation_warnings',
    'render_warning_acknowledgment',
    'render_validation_summary',
    
    # Forms & Dialogs
    'render_create_form',
    'render_edit_form',
    'show_detail_dialog',
    'show_edit_dialog',
    'show_confirm_dialog',
    'show_cancel_dialog',
    'show_delete_dialog',
    'show_pdf_dialog',
    'check_pending_dialogs',
    'handle_row_action',
    
    # Dashboard, Pivot & Page
    'render_dashboard',
    'render_pivot_view',
    'render_orders_tab',
    
    # Common utilities
    'OrderConstants',
    'OrderValidator',
    'get_vietnam_now',
    'get_vietnam_today',
    'format_number',
    'format_currency',
    'format_date',
    'format_datetime_vn',
    'create_status_indicator',
    'format_product_display',
    'format_material_display',
    'export_to_excel',
]