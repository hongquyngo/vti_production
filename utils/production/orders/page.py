# utils/production/orders/page_optimized.py
"""
OPTIMIZED: Main UI orchestrator for Orders domain
Renders the Orders tab with dashboard, filters, list, and actions

Version: 2.0.0 - Performance Optimized
Changes:
- v2.0.0: Applied @st.fragment pattern throughout to minimize full page reruns
          + Dashboard isolated in fragment
          + Filters isolated in fragment with callback pattern
          + Order list + actions isolated in single fragment
          + Removed unnecessary st.rerun() calls
          + Used on_click callbacks for buttons
- v1.2.0: Added BOM conflict detection and warning

PERFORMANCE IMPROVEMENTS:
1. Fragment isolation: Each section reruns independently
2. Callback pattern: Buttons use on_click instead of inline if-block
3. Session state optimization: Minimize state changes that trigger reruns
4. Lazy loading: Only fetch data when needed
"""

import logging
from datetime import timedelta
from typing import Dict, Any, Optional, Callable

import streamlit as st
import pandas as pd

from .queries import OrderQueries
from .manager import OrderManager
from .dashboard import OrderDashboard
from .forms import render_create_form
from .dialogs import (
    show_detail_dialog, show_edit_dialog, show_confirm_dialog,
    show_cancel_dialog, show_delete_dialog, show_pdf_dialog,
    check_pending_dialogs
)
from .common import (
    format_number, create_status_indicator, calculate_percentage, format_datetime_vn,
    get_vietnam_today, export_to_excel, OrderConstants, OrderValidator,
    format_product_display
)

logger = logging.getLogger(__name__)


# ==================== Session State ====================

def _init_session_state():
    """Initialize session state for orders tab"""
    defaults = {
        'orders_page': 1,
        'orders_view': 'list',
        'orders_selected_id': None,
        'orders_selected_idx': None,
        'orders_conflicts_only': False,
        'orders_conflict_check_active_only': True,
        # Filter cache - avoid re-fetching on every rerun
        'orders_filters_cache': None,
        # Action flags - for dialog opening
        'pending_dialog': None,
        'pending_dialog_params': {},
    }
    
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


# ==================== Callback Functions ====================
# Using callbacks instead of inline if-blocks reduces reruns

def _on_create_order_click():
    """Callback for Create Order button"""
    st.session_state.orders_view = 'create'


def _on_back_to_list_click():
    """Callback for Back to List button"""
    st.session_state.orders_view = 'list'


def _on_refresh_click():
    """Callback for Refresh button - just clears cache"""
    st.session_state.pop('orders_data_cache', None)


def _on_page_change(direction: int):
    """Callback for pagination"""
    st.session_state.orders_page = max(1, st.session_state.orders_page + direction)
    st.session_state.orders_selected_idx = None


def _on_action_click(action: str, order_id: int, order_no: str):
    """
    Callback for action buttons - sets pending dialog
    Dialog will be opened on next fragment rerun, not full page rerun
    """
    st.session_state.pending_dialog = action
    st.session_state.pending_dialog_params = {
        'order_id': order_id,
        'order_no': order_no
    }


# ==================== Fragment: Dashboard ====================

@st.fragment
def _fragment_dashboard():
    """
    ISOLATED FRAGMENT: Dashboard metrics
    Only reruns when explicitly needed, not on every page interaction
    """
    # Get filter values from session state (set by filter fragment)
    conflict_check_active_only = st.session_state.get('orders_conflict_check_active_only', True)
    
    dashboard = OrderDashboard()
    dashboard.render(conflict_check_active_only=conflict_check_active_only)


# ==================== Fragment: Filters ====================

@st.fragment
def _fragment_filters() -> Dict[str, Any]:
    """
    ISOLATED FRAGMENT: Filter bar
    Changes here only rerun this fragment, not the entire page
    
    Returns filter values via session state for other fragments to use
    """
    queries = OrderQueries()
    filter_options = queries.get_filter_options()
    
    # Default date range
    default_to = get_vietnam_today()
    default_from = (default_to.replace(day=1) - timedelta(days=1)).replace(day=1)
    
    with st.expander("🔍 Filters", expanded=False):
        # Row 1: Main filters
        col1, col2, col3, col4, col5 = st.columns([1, 1, 1, 1, 2])
        
        with col1:
            status = st.selectbox(
                "Status",
                options=filter_options['statuses'],
                key="frag_filter_status"
            )
        
        with col2:
            order_type = st.selectbox(
                "Type",
                options=filter_options['order_types'],
                key="frag_filter_type"
            )
        
        with col3:
            priority = st.selectbox(
                "Priority",
                options=filter_options['priorities'],
                key="frag_filter_priority"
            )
        
        with col4:
            date_col1, date_col2 = st.columns(2)
            with date_col1:
                from_date = st.date_input(
                    "From",
                    value=default_from,
                    key="frag_filter_from"
                )
            with date_col2:
                to_date = st.date_input(
                    "To",
                    value=default_to,
                    key="frag_filter_to"
                )
        
        with col5:
            search = st.text_input(
                "🔍 Search",
                placeholder="Order, product, BOM, brand, size, notes, creator...",
                key="frag_filter_search",
                help="Search by: Order No, Product Name/Code, Package Size, Legacy Code, BOM Name/Code, Brand, Notes, Creator Name"
            )
        
        # Row 2: Conflict filters
        st.markdown("---")
        col1, col2, col3 = st.columns([1, 1, 2])
        
        with col1:
            conflicts_only = st.checkbox(
                "🔴 Conflicts Only",
                value=st.session_state.get('orders_conflicts_only', False),
                key="frag_filter_conflicts_only",
                help="Show only orders with BOM conflicts"
            )
        
        with col2:
            conflict_check_active_only = st.checkbox(
                "Check Active BOMs Only",
                value=st.session_state.get('orders_conflict_check_active_only', True),
                key="frag_filter_conflict_check_active",
                help="If checked, count only ACTIVE BOMs for conflict detection"
            )
        
        # Apply filters button - only updates when user explicitly clicks
        if st.button("🔄 Apply Filters", use_container_width=True, key="btn_apply_filters"):
            # Update session state with new filter values
            st.session_state.orders_conflicts_only = conflicts_only
            st.session_state.orders_conflict_check_active_only = conflict_check_active_only
            st.session_state.orders_page = 1  # Reset to first page
            st.session_state.orders_selected_idx = None  # Clear selection
    
    # Build and cache filter values
    filters = {
        'status': status if status != "All" else None,
        'order_type': order_type if order_type != "All" else None,
        'priority': priority if priority != "All" else None,
        'from_date': from_date,
        'to_date': to_date,
        'search': search if search else None,
        'conflicts_only': st.session_state.get('orders_conflicts_only', False),
        'conflict_check_active_only': st.session_state.get('orders_conflict_check_active_only', True)
    }
    
    # Store in session state for other fragments
    st.session_state.orders_filters_cache = filters
    
    return filters


# ==================== Fragment: Order List with Actions ====================

@st.fragment
def _fragment_order_list_with_actions():
    """
    ISOLATED FRAGMENT: Order list table + action buttons
    
    This is the main interactive area. Isolating it means:
    - Selecting rows only reruns this fragment
    - Clicking action buttons only reruns this fragment
    - Opening dialogs happens within fragment context
    """
    queries = OrderQueries()
    
    # Get filters from session state (set by filter fragment)
    filters = st.session_state.get('orders_filters_cache', {})
    if not filters:
        # Fallback defaults
        filters = {
            'status': None, 'order_type': None, 'priority': None,
            'from_date': None, 'to_date': None, 'search': None,
            'conflicts_only': False, 'conflict_check_active_only': True
        }
    
    # Check for pending dialog (from previous action click)
    _handle_pending_dialog()
    
    # Render conflict warning
    _render_conflict_warning_inline(queries, filters)
    
    # Action bar
    _render_action_bar_inline()
    
    # Get data
    page_size = OrderConstants.DEFAULT_PAGE_SIZE
    page = st.session_state.orders_page
    
    orders = queries.get_orders(
        status=filters.get('status'),
        order_type=filters.get('order_type'),
        priority=filters.get('priority'),
        from_date=filters.get('from_date'),
        to_date=filters.get('to_date'),
        search=filters.get('search'),
        conflicts_only=filters.get('conflicts_only', False),
        conflict_check_active_only=filters.get('conflict_check_active_only', True),
        page=page,
        page_size=page_size
    )
    
    # Handle connection error
    if orders is None:
        error_msg = queries.get_last_error() or "Cannot connect to database"
        st.error(f"🔌 **Database Connection Error**\n\n{error_msg}")
        st.info("💡 **Troubleshooting:**\n- Check if VPN is connected\n- Verify network connection")
        return
    
    total_count = queries.get_orders_count(
        status=filters.get('status'),
        order_type=filters.get('order_type'),
        priority=filters.get('priority'),
        from_date=filters.get('from_date'),
        to_date=filters.get('to_date'),
        search=filters.get('search'),
        conflicts_only=filters.get('conflicts_only', False),
        conflict_check_active_only=filters.get('conflict_check_active_only', True)
    )
    
    # Handle empty data
    if orders.empty:
        if filters.get('conflicts_only'):
            st.success("✅ No orders with BOM conflicts found!")
        else:
            st.info("📭 No orders found matching the filters")
        return
    
    # Render table with selection
    _render_order_table(orders)
    
    # Render action buttons for selected row
    _render_selected_row_actions(orders)
    
    # Pagination
    _render_pagination_inline(total_count, page_size, page)


def _handle_pending_dialog():
    """Handle any pending dialog from previous action click"""
    pending = st.session_state.get('pending_dialog')
    if not pending:
        return
    
    params = st.session_state.get('pending_dialog_params', {})
    order_id = params.get('order_id')
    order_no = params.get('order_no', '')
    
    # Clear pending state BEFORE opening dialog
    st.session_state.pending_dialog = None
    st.session_state.pending_dialog_params = {}
    
    if not order_id:
        return
    
    # Open the appropriate dialog
    if pending == 'view':
        show_detail_dialog(order_id)
    elif pending == 'edit':
        show_edit_dialog(order_id)
    elif pending == 'confirm':
        show_confirm_dialog(order_id, order_no)
    elif pending == 'cancel':
        show_cancel_dialog(order_id, order_no)
    elif pending == 'pdf':
        show_pdf_dialog(order_id, order_no)
    elif pending == 'delete':
        show_delete_dialog(order_id, order_no)


def _render_conflict_warning_inline(queries: OrderQueries, filters: Dict[str, Any]):
    """Render BOM conflict warning banner"""
    conflict_summary = queries.get_bom_conflict_summary(
        active_only=filters.get('conflict_check_active_only', True),
        from_date=filters.get('from_date'),
        to_date=filters.get('to_date')
    )
    
    conflict_count = conflict_summary['total_conflict_orders']
    affected_products = conflict_summary['affected_products']
    
    if conflict_count > 0:
        st.warning(
            f"⚠️ **Warning:** {conflict_count} order(s) have BOM conflicts "
            f"({affected_products} product(s) affected). "
            f"Use '🔴 Conflicts Only' filter to review."
        )


def _render_action_bar_inline():
    """Render action bar with callbacks"""
    col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
    
    with col1:
        # Use on_click callback instead of if-block
        st.button(
            "➕ Create Order",
            type="primary",
            use_container_width=True,
            key="frag_btn_create",
            on_click=_on_create_order_click
        )
    
    with col2:
        if st.button("📊 Export Excel", use_container_width=True, key="frag_btn_export"):
            _export_orders_excel_inline()
    
    with col3:
        st.button(
            "🔄 Refresh",
            use_container_width=True,
            key="frag_btn_refresh",
            on_click=_on_refresh_click
        )


def _render_order_table(orders: pd.DataFrame):
    """Render order table with selection"""
    display_df = orders.copy()
    
    # Set Select column
    display_df['Select'] = False
    selected_idx = st.session_state.get('orders_selected_idx')
    if selected_idx is not None and selected_idx < len(display_df):
        display_df.loc[display_df.index[selected_idx], 'Select'] = True
    
    # Format columns
    display_df['status_display'] = display_df['status'].apply(create_status_indicator)
    display_df['priority_display'] = display_df['priority'].apply(create_status_indicator)
    display_df['progress'] = display_df.apply(
        lambda x: f"{format_number(x['produced_qty'], 0)}/{format_number(x['planned_qty'], 0)} {x['uom']}",
        axis=1
    )
    display_df['product_display'] = display_df.apply(format_product_display, axis=1)
    display_df['scheduled'] = display_df['scheduled_date'].apply(
        lambda x: format_datetime_vn(x, '%d/%m/%Y') if x else ''
    )
    display_df['issues'] = display_df.apply(
        lambda row: f"🔴 {row.get('bom_conflict_count', 1)}" if row.get('bom_conflict_count', 1) > 1 else "-",
        axis=1
    )
    
    # Data editor - selection changes only trigger fragment rerun
    edited_df = st.data_editor(
        display_df[[
            'Select', 'order_no', 'product_display', 'progress',
            'status_display', 'priority_display', 'issues', 'scheduled',
            'warehouse_name', 'target_warehouse_name'
        ]].rename(columns={
            'order_no': 'Order No',
            'product_display': 'Product',
            'progress': 'Progress',
            'status_display': 'Status',
            'priority_display': 'Priority',
            'issues': 'Issues',
            'scheduled': 'Scheduled',
            'warehouse_name': 'Source',
            'target_warehouse_name': 'Target'
        }),
        use_container_width=True,
        hide_index=True,
        disabled=['Order No', 'Product', 'Progress', 'Status', 'Priority', 'Issues', 'Scheduled', 'Source', 'Target'],
        column_config={
            'Select': st.column_config.CheckboxColumn(
                '✓',
                help='Select row to perform actions',
                default=False,
                width='small'
            ),
            'Issues': st.column_config.TextColumn(
                'Issues',
                help='🔴 N = Product has N active BOMs (conflict)',
                width='small'
            )
        },
        key="frag_orders_table"
    )
    
    # Handle selection - NO st.rerun() needed within fragment
    selected_indices = edited_df[edited_df['Select'] == True].index.tolist()
    
    if selected_indices:
        # Convert DataFrame index to positional index
        new_idx = list(display_df.index).index(selected_indices[0]) if selected_indices[0] in display_df.index else 0
        
        # Only update if changed
        if st.session_state.orders_selected_idx != new_idx:
            st.session_state.orders_selected_idx = new_idx
            # Fragment will naturally rerun due to state change
    else:
        if st.session_state.orders_selected_idx is not None:
            st.session_state.orders_selected_idx = None


def _render_selected_row_actions(orders: pd.DataFrame):
    """Render action buttons for selected row"""
    selected_idx = st.session_state.get('orders_selected_idx')
    
    if selected_idx is None or selected_idx >= len(orders):
        st.info("💡 Tick checkbox to select an order and perform actions")
        return
    
    selected_order = orders.iloc[selected_idx]
    order_id = selected_order['id']
    order_no = selected_order['order_no']
    status = selected_order['status']
    bom_conflict_count = selected_order.get('bom_conflict_count', 1)
    
    st.markdown("---")
    
    # Selected order info
    selected_info = f"**Selected:** `{order_no}` | Status: {create_status_indicator(status)} | {selected_order['product_name']}"
    if bom_conflict_count > 1:
        selected_info += f" | ⚠️ **BOM Conflict ({bom_conflict_count} active BOMs)**"
    st.markdown(selected_info)
    
    # Action buttons with on_click callbacks - NO st.rerun() needed
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    
    with col1:
        st.button(
            "👁️ View",
            type="primary",
            use_container_width=True,
            key="frag_btn_view",
            on_click=lambda: _on_action_click('view', order_id, order_no)
        )
    
    with col2:
        st.button(
            "✏️ Edit",
            use_container_width=True,
            key="frag_btn_edit",
            disabled=not OrderValidator.can_edit(status),
            on_click=lambda: _on_action_click('edit', order_id, order_no)
        )
    
    with col3:
        st.button(
            "✅ Confirm",
            use_container_width=True,
            key="frag_btn_confirm",
            disabled=not OrderValidator.can_confirm(status),
            on_click=lambda: _on_action_click('confirm', order_id, order_no)
        )
    
    with col4:
        st.button(
            "❌ Cancel",
            use_container_width=True,
            key="frag_btn_cancel",
            disabled=not OrderValidator.can_cancel(status),
            on_click=lambda: _on_action_click('cancel', order_id, order_no)
        )
    
    with col5:
        st.button(
            "📄 PDF",
            use_container_width=True,
            key="frag_btn_pdf",
            on_click=lambda: _on_action_click('pdf', order_id, order_no)
        )
    
    with col6:
        st.button(
            "🗑️ Delete",
            use_container_width=True,
            key="frag_btn_delete",
            disabled=status not in ['DRAFT', 'CANCELLED'],
            on_click=lambda: _on_action_click('delete', order_id, order_no)
        )


def _render_pagination_inline(total_count: int, page_size: int, page: int):
    """Render pagination controls"""
    st.markdown("---")
    total_pages = max(1, (total_count + page_size - 1) // page_size)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col1:
        st.button(
            "⬅️ Previous",
            disabled=page <= 1,
            key="frag_btn_prev",
            on_click=lambda: _on_page_change(-1)
        )
    
    with col2:
        st.markdown(
            f"<div style='text-align:center'>Page {page} of {total_pages} | Total: {total_count} orders</div>",
            unsafe_allow_html=True
        )
    
    with col3:
        st.button(
            "Next ➡️",
            disabled=page >= total_pages,
            key="frag_btn_next",
            on_click=lambda: _on_page_change(1)
        )


def _export_orders_excel_inline():
    """Export orders to Excel"""
    queries = OrderQueries()
    filters = st.session_state.get('orders_filters_cache', {})
    
    with st.spinner("Exporting..."):
        orders = queries.get_orders(
            status=filters.get('status'),
            order_type=filters.get('order_type'),
            priority=filters.get('priority'),
            from_date=filters.get('from_date'),
            to_date=filters.get('to_date'),
            search=filters.get('search'),
            page=1,
            page_size=10000
        )
        
        if orders is None or orders.empty:
            st.warning("No orders to export")
            return
        
        export_df = orders.copy()
        export_df['product_display'] = export_df.apply(format_product_display, axis=1)
        
        export_df = export_df[[
            'order_no', 'order_date',
            'pt_code', 'legacy_pt_code', 'product_name', 'package_size', 'brand_name',
            'product_display',
            'bom_name', 'bom_type',
            'planned_qty', 'produced_qty', 'uom', 'status', 'priority',
            'scheduled_date', 'warehouse_name', 'target_warehouse_name',
            'created_by_name'
        ]].copy()
        
        export_df['legacy_pt_code'] = export_df['legacy_pt_code'].fillna('NEW').replace('', 'NEW')
        
        export_df.columns = [
            'Order No', 'Order Date',
            'PT Code', 'Legacy Code', 'Product Name', 'Package Size', 'Brand',
            'Product (Full)',
            'BOM', 'BOM Type',
            'Planned Qty', 'Produced Qty', 'UOM', 'Status', 'Priority',
            'Scheduled Date', 'Source Warehouse', 'Target Warehouse',
            'Created By'
        ]
        
        excel_data = export_to_excel(export_df)
        filename = f"Production_Orders_{get_vietnam_today().strftime('%Y%m%d')}.xlsx"
        
        st.download_button(
            label="💾 Download Excel",
            data=excel_data,
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="frag_download_excel"
        )


# ==================== Main Render Function ====================

def render_orders_tab():
    """
    OPTIMIZED: Main function to render the Orders tab
    
    Architecture:
    - Orchestrator only handles view switching and success messages
    - All interactive components are isolated in fragments
    - Fragments only rerun when their specific state changes
    """
    _init_session_state()
    
    # Check for pending dialogs from nested dialog scenario
    check_pending_dialogs()
    
    # Show success message if order was just created
    if st.session_state.get('order_created_success'):
        order_no = st.session_state.pop('order_created_success')
        st.success(f"✅ Order **{order_no}** created successfully!")
        st.balloons()
        st.info("""
        **Next Steps:**
        1. View order details to review materials
        2. Confirm the order when ready
        3. Issue materials to start production
        """)
    
    # View switching - this is the only thing that triggers full page rerun
    if st.session_state.orders_view == 'create':
        st.button(
            "⬅️ Back to List",
            key="btn_back_to_list",
            on_click=_on_back_to_list_click
        )
        render_create_form()
        return
    
    # List view - all components are fragments
    st.subheader("📋 Production Orders")
    
    # Fragment 1: Dashboard (isolated)
    _fragment_dashboard()
    
    # Fragment 2: Filters (isolated)
    _fragment_filters()
    
    # Fragment 3: Order list + actions (isolated)
    _fragment_order_list_with_actions()