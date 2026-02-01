# utils/production/orders/page.py
"""
Main UI orchestrator for Orders domain
Renders the Orders tab with dashboard, filters, list, and actions

Version: 1.3.0
Changes:
- v1.3.0: Performance optimization with fragment isolation
          + Migrated from st.data_editor to st.dataframe with selection_mode="single-row"
          + Wrapped order list in @st.fragment for isolated reruns
          + Row selection and pagination now only rerun the list fragment
          + Removed explicit st.rerun() calls - handled by fragment
          + Cleaner UX: click row to select instead of checkbox
- v1.2.0: Added BOM conflict detection and warning
          + Conflict warning banner at top
          + 'Conflicts Only' filter checkbox
          + 'Issues' column in order table showing BOM conflict count
          + Toggle for checking active BOMs only vs all BOMs
- v1.1.0: Enhanced search placeholder with help tooltip showing all searchable fields
"""

import logging
from datetime import timedelta
from typing import Dict, Any, Optional

import streamlit as st
import pandas as pd

from .queries import OrderQueries
from .manager import OrderManager
from .dashboard import render_dashboard
from .forms import render_create_form
from .dialogs import (
    show_detail_dialog, show_edit_dialog, show_confirm_dialog,
    show_cancel_dialog, show_delete_dialog, show_pdf_dialog,
    check_pending_dialogs
)
from .common import (
    format_number, create_status_indicator, calculate_percentage, format_datetime_vn,
    get_vietnam_today, export_to_excel, OrderConstants, OrderValidator,
    format_product_display, format_date
)

logger = logging.getLogger(__name__)


# ==================== Session State ====================

def _init_session_state():
    """Initialize session state for orders tab"""
    defaults = {
        'orders_page': 1,
        'orders_view': 'list',  # 'list' or 'create'
        'orders_conflicts_only': False,
        'orders_conflict_check_active_only': True,  # Default: check active BOMs only
    }
    # Note: orders_selected_idx removed - st.dataframe handles selection internally
    
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


# ==================== Filter Bar ====================

def _render_filter_bar(queries: OrderQueries) -> Dict[str, Any]:
    """
    Render filter bar and return selected filters
    
    Returns:
        Dictionary with filter values
    """
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
                key="order_filter_status"
            )
        
        with col2:
            order_type = st.selectbox(
                "Type",
                options=filter_options['order_types'],
                key="order_filter_type"
            )
        
        with col3:
            priority = st.selectbox(
                "Priority",
                options=filter_options['priorities'],
                key="order_filter_priority"
            )
        
        with col4:
            date_col1, date_col2 = st.columns(2)
            with date_col1:
                from_date = st.date_input(
                    "From",
                    value=default_from,
                    key="order_filter_from"
                )
            with date_col2:
                to_date = st.date_input(
                    "To",
                    value=default_to,
                    key="order_filter_to"
                )
        
        with col5:
            search = st.text_input(
                "🔍 Search",
                placeholder="Order, product, BOM, brand, size, notes, creator...",
                key="order_filter_search",
                help="Search by: Order No, Product Name/Code, Package Size, Legacy Code, BOM Name/Code, Brand, Notes, Creator Name"
            )
        
        # Row 2: Conflict filters
        st.markdown("---")
        col1, col2, col3 = st.columns([1, 1, 2])
        
        with col1:
            conflicts_only = st.checkbox(
                "🔴 Conflicts Only",
                value=st.session_state.get('orders_conflicts_only', False),
                key="order_filter_conflicts_only",
                help="Show only orders with BOM conflicts (multiple active BOMs for same product)"
            )
            st.session_state['orders_conflicts_only'] = conflicts_only
        
        with col2:
            conflict_check_active_only = st.checkbox(
                "Check Active BOMs Only",
                value=st.session_state.get('orders_conflict_check_active_only', True),
                key="order_filter_conflict_check_active",
                help="If checked, count only ACTIVE BOMs for conflict detection. If unchecked, count ALL BOMs."
            )
            st.session_state['orders_conflict_check_active_only'] = conflict_check_active_only
    
    return {
        'status': status if status != "All" else None,
        'order_type': order_type if order_type != "All" else None,
        'priority': priority if priority != "All" else None,
        'from_date': from_date,
        'to_date': to_date,
        'search': search if search else None,
        'conflicts_only': conflicts_only,
        'conflict_check_active_only': conflict_check_active_only
    }


# ==================== Order List ====================

def _render_conflict_warning(queries: OrderQueries, filters: Dict[str, Any]):
    """Render BOM conflict warning banner if there are conflicts"""
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


def _render_order_list(queries: OrderQueries, filters: Dict[str, Any]):
    """
    Render order list section
    Delegates to fragment for optimized rerun scope
    """
    _fragment_order_list(queries, filters)


@st.fragment
def _fragment_order_list(queries: OrderQueries, filters: Dict[str, Any]):
    """
    Fragment: Order list with single-row selection
    
    Benefits of fragment isolation:
    - Row selection only reruns this fragment, not entire page
    - Pagination only reruns this fragment
    - Dashboard and filters remain stable
    
    Uses st.dataframe with selection_mode="single-row" (Streamlit 1.35+)
    """
    page_size = OrderConstants.DEFAULT_PAGE_SIZE
    page = st.session_state.orders_page
    
    # Get conflict filter options
    conflicts_only = filters.get('conflicts_only', False)
    conflict_check_active_only = filters.get('conflict_check_active_only', True)
    
    # Get orders with conflict count
    orders = queries.get_orders(
        status=filters['status'],
        order_type=filters['order_type'],
        priority=filters['priority'],
        from_date=filters['from_date'],
        to_date=filters['to_date'],
        search=filters['search'],
        conflicts_only=conflicts_only,
        conflict_check_active_only=conflict_check_active_only,
        page=page,
        page_size=page_size
    )
    
    # Check for connection error (returns None)
    if orders is None:
        error_msg = queries.get_last_error() or "Cannot connect to database"
        st.error(f"🔌 **Database Connection Error**\n\n{error_msg}")
        st.info("💡 **Troubleshooting:**\n- Check if VPN is connected\n- Verify network connection\n- Contact IT support if issue persists")
        return
    
    total_count = queries.get_orders_count(
        status=filters['status'],
        order_type=filters['order_type'],
        priority=filters['priority'],
        from_date=filters['from_date'],
        to_date=filters['to_date'],
        search=filters['search'],
        conflicts_only=conflicts_only,
        conflict_check_active_only=conflict_check_active_only
    )
    
    # Check for empty data (returns empty DataFrame)
    if orders.empty:
        if conflicts_only:
            st.success("✅ No orders with BOM conflicts found!")
        else:
            st.info("📭 No orders found matching the filters")
        return
    
    # Prepare display dataframe (no Select column needed)
    display_df = orders.copy()
    
    display_df['status_display'] = display_df['status'].apply(create_status_indicator)
    display_df['priority_display'] = display_df['priority'].apply(create_status_indicator)
    display_df['progress'] = display_df.apply(
        lambda x: f"{format_number(x['produced_qty'], 0)}/{format_number(x['planned_qty'], 0)} {x['uom']}",
        axis=1
    )
    display_df['product_display'] = display_df.apply(format_product_display, axis=1)
    display_df['scheduled'] = display_df['scheduled_date'].apply(
        lambda x: format_date(x, '%d/%m/%Y') if x else ''
    )
    
    # Issues column - show BOM conflict count if > 1
    def format_issues(row):
        conflict_count = row.get('bom_conflict_count', 1)
        if conflict_count > 1:
            return f"🔴 {conflict_count}"
        return "-"
    
    display_df['issues'] = display_df.apply(format_issues, axis=1)
    
    # Prepare display columns
    display_columns = [
        'order_no', 'product_display', 'progress', 
        'status_display', 'priority_display', 'issues', 'scheduled',
        'warehouse_name', 'target_warehouse_name'
    ]
    
    column_labels = {
        'order_no': 'Order No',
        'product_display': 'Product',
        'progress': 'Progress',
        'status_display': 'Status',
        'priority_display': 'Priority',
        'issues': 'Issues',
        'scheduled': 'Scheduled',
        'warehouse_name': 'Source',
        'target_warehouse_name': 'Target'
    }
    
    # Use st.dataframe with selection_mode for cleaner single-row selection
    # on_select="rerun" triggers fragment-level rerun only (not full page)
    selection_event = st.dataframe(
        display_df[display_columns].rename(columns=column_labels),
        use_container_width=True,
        hide_index=True,
        selection_mode="single-row",
        on_select="rerun",
        column_config={
            'Issues': st.column_config.TextColumn(
                'Issues',
                help='🔴 N = Product has N active BOMs (conflict)',
                width='small'
            ),
            'Order No': st.column_config.TextColumn(
                'Order No',
                width='medium'
            ),
            'Product': st.column_config.TextColumn(
                'Product',
                width='large'
            ),
        },
        key="orders_table"
    )
    
    # Get selected row from event
    selected_rows = selection_event.selection.rows if selection_event.selection else []
    selected_idx = selected_rows[0] if selected_rows else None
    
    # Action buttons - only show when row is selected
    if selected_idx is not None:
        selected_order = orders.iloc[selected_idx]
        order_id = selected_order['id']
        order_no = selected_order['order_no']
        status = selected_order['status']
        bom_conflict_count = selected_order.get('bom_conflict_count', 1)
        
        st.markdown("---")
        
        # Show selected order info with conflict warning if applicable
        selected_info = f"**Selected:** `{order_no}` | Status: {create_status_indicator(status)} | {selected_order['product_name']}"
        if bom_conflict_count > 1:
            selected_info += f" | ⚠️ **BOM Conflict ({bom_conflict_count} active BOMs)**"
        st.markdown(selected_info)
        
        col1, col2, col3, col4, col5, col6 = st.columns(6)
        
        with col1:
            if st.button("👁️ View", type="primary", use_container_width=True, key="btn_view_order"):
                show_detail_dialog(order_id)
        
        with col2:
            if st.button("✏️ Edit", use_container_width=True, key="btn_edit_order",
                        disabled=not OrderValidator.can_edit(status)):
                show_edit_dialog(order_id)
        
        with col3:
            if st.button("✅ Confirm", use_container_width=True, key="btn_confirm_order",
                        disabled=not OrderValidator.can_confirm(status)):
                show_confirm_dialog(order_id, order_no)
        
        with col4:
            if st.button("❌ Cancel", use_container_width=True, key="btn_cancel_order",
                        disabled=not OrderValidator.can_cancel(status)):
                show_cancel_dialog(order_id, order_no)
        
        with col5:
            if st.button("📄 PDF", use_container_width=True, key="btn_pdf_order"):
                show_pdf_dialog(order_id, order_no)
        
        with col6:
            if st.button("🗑️ Delete", use_container_width=True, key="btn_delete_order",
                        disabled=status not in ['DRAFT', 'CANCELLED']):
                show_delete_dialog(order_id, order_no)
    else:
        st.info("💡 Click on a row to select an order and perform actions")
    
    # Pagination (inside fragment for isolated rerun)
    st.markdown("---")
    total_pages = max(1, (total_count + page_size - 1) // page_size)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col1:
        if st.button("⬅️ Previous", disabled=page <= 1, key="btn_prev_page"):
            st.session_state.orders_page = max(1, page - 1)
            # No explicit st.rerun() needed - fragment handles it
    
    with col2:
        st.markdown(f"<div style='text-align:center'>Page {page} of {total_pages} | Total: {total_count} orders</div>", unsafe_allow_html=True)
    
    with col3:
        if st.button("Next ➡️", disabled=page >= total_pages, key="btn_next_page"):
            st.session_state.orders_page = page + 1
            # No explicit st.rerun() needed - fragment handles it


# ==================== Action Bar ====================

def _render_action_bar(queries: OrderQueries, filters: Dict[str, Any]):
    """Render action bar with bulk actions"""
    col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
    
    with col1:
        if st.button("➕ Create Order", type="primary", use_container_width=True,
                    key="btn_create_order"):
            st.session_state.orders_view = 'create'
            st.rerun()
    
    with col2:
        if st.button("📊 Export Excel", use_container_width=True, key="btn_export_excel"):
            _export_orders_excel(queries, filters)
    
    with col3:
        if st.button("🔄 Refresh", use_container_width=True, key="btn_refresh_orders"):
            st.rerun()


def _export_orders_excel(queries: OrderQueries, filters: Dict[str, Any]):
    """Export orders to Excel"""
    with st.spinner("Exporting..."):
        # Get all orders (no pagination)
        orders = queries.get_orders(
            status=filters['status'],
            order_type=filters['order_type'],
            priority=filters['priority'],
            from_date=filters['from_date'],
            to_date=filters['to_date'],
            search=filters['search'],
            page=1,
            page_size=10000
        )
        
        if orders.empty:
            st.warning("No orders to export")
            return
        
        # Prepare export dataframe with full product info
        export_df = orders.copy()
        
        # Add formatted product display column
        export_df['product_display'] = export_df.apply(format_product_display, axis=1)
        
        # Select and rename columns
        export_df = export_df[[
            'order_no', 'order_date', 
            'pt_code', 'legacy_pt_code', 'product_name', 'package_size', 'brand_name',
            'product_display',
            'bom_name', 'bom_type',
            'planned_qty', 'produced_qty', 'uom', 'status', 'priority',
            'scheduled_date', 'warehouse_name', 'target_warehouse_name',
            'created_by_name'
        ]].copy()
        
        # Fill empty legacy codes with 'NEW'
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
            key="download_orders_excel"
        )


# ==================== Main Render Function ====================

def render_orders_tab():
    """
    Main function to render the Orders tab
    Called from the main Production page
    """
    _init_session_state()
    
    # Check for pending dialogs (e.g., confirm/cancel dialog triggered from detail dialog)
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
    
    queries = OrderQueries()
    
    # Check current view
    if st.session_state.orders_view == 'create':
        # Back button
        if st.button("⬅️ Back to List", key="btn_back_to_list"):
            st.session_state.orders_view = 'list'
            st.rerun()
        
        render_create_form()
        return
    
    # List view
    st.subheader("📋 Production Orders")
    
    # Render components
    # Get conflict check option from session state
    conflict_check_active_only = st.session_state.get('orders_conflict_check_active_only', True)
    render_dashboard(conflict_check_active_only=conflict_check_active_only)

    filters = _render_filter_bar(queries)
    
    # Render BOM conflict warning banner
    _render_conflict_warning(queries, filters)

    _render_action_bar(queries, filters)

    _render_order_list(queries, filters)