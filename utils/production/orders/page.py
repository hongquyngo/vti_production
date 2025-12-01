# utils/production/orders/page.py
"""
Main UI orchestrator for Orders domain
Renders the Orders tab with dashboard, filters, list, and actions

Version: 1.0.0
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
    format_number, create_status_indicator, calculate_percentage,
    get_vietnam_today, export_to_excel, OrderConstants, OrderValidator
)

logger = logging.getLogger(__name__)


# ==================== Session State ====================

def _init_session_state():
    """Initialize session state for orders tab"""
    defaults = {
        'orders_page': 1,
        'orders_view': 'list',  # 'list' or 'create'
        'orders_selected_id': None,
    }
    
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
                placeholder="Order no, product...",
                key="order_filter_search"
            )
    
    return {
        'status': status if status != "All" else None,
        'order_type': order_type if order_type != "All" else None,
        'priority': priority if priority != "All" else None,
        'from_date': from_date,
        'to_date': to_date,
        'search': search if search else None
    }


# ==================== Order List ====================

def _render_order_list(queries: OrderQueries, filters: Dict[str, Any]):
    """Render order list with pagination"""
    page_size = OrderConstants.DEFAULT_PAGE_SIZE
    page = st.session_state.orders_page
    
    # Get orders
    orders = queries.get_orders(
        status=filters['status'],
        order_type=filters['order_type'],
        priority=filters['priority'],
        from_date=filters['from_date'],
        to_date=filters['to_date'],
        search=filters['search'],
        page=page,
        page_size=page_size
    )
    
    total_count = queries.get_orders_count(
        status=filters['status'],
        order_type=filters['order_type'],
        priority=filters['priority'],
        from_date=filters['from_date'],
        to_date=filters['to_date'],
        search=filters['search']
    )
    
    if orders.empty:
        st.info("📭 No orders found matching the filters")
        return
    
    # Prepare display dataframe
    display_df = orders.copy()
    display_df['status_display'] = display_df['status'].apply(create_status_indicator)
    display_df['priority_display'] = display_df['priority'].apply(create_status_indicator)
    display_df['progress'] = display_df.apply(
        lambda x: f"{format_number(x['produced_qty'], 0)}/{format_number(x['planned_qty'], 0)} {x['uom']}",
        axis=1
    )
    display_df['product_display'] = display_df.apply(
        lambda x: f"{x['pt_code']} | {x['product_name']}" + 
                  (f" | {x['package_size']}" if x['package_size'] else ""),
        axis=1
    )
    display_df['scheduled'] = pd.to_datetime(display_df['scheduled_date']).dt.strftime('%d/%m/%Y')
    
    # Display table
    st.dataframe(
        display_df[[
            'order_no', 'product_display', 'progress', 
            'status_display', 'priority_display', 'scheduled',
            'warehouse_name', 'target_warehouse_name'
        ]].rename(columns={
            'order_no': 'Order No',
            'product_display': 'Product',
            'progress': 'Progress',
            'status_display': 'Status',
            'priority_display': 'Priority',
            'scheduled': 'Scheduled',
            'warehouse_name': 'Source',
            'target_warehouse_name': 'Target'
        }),
        use_container_width=True,
        hide_index=True
    )
    
    # Row actions
    st.markdown("### Actions")
    
    order_options = {
        f"{row['order_no']} | {row['status']} | {row['pt_code']} - {row['product_name']}": row
        for _, row in orders.iterrows()
    }
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        selected_label = st.selectbox(
            "Select Order",
            options=list(order_options.keys()),
            key="order_action_select"
        )
    
    selected_order = order_options[selected_label]
    order_id = selected_order['id']
    order_no = selected_order['order_no']
    status = selected_order['status']
    
    # Action buttons
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    
    with col1:
        if st.button("👁️ View", use_container_width=True, key="btn_view_order"):
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
    
    # Pagination
    st.markdown("---")
    total_pages = max(1, (total_count + page_size - 1) // page_size)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col1:
        if st.button("⬅️ Previous", disabled=page <= 1, key="btn_prev_page"):
            st.session_state.orders_page = max(1, page - 1)
            st.rerun()
    
    with col2:
        st.write(f"Page {page} of {total_pages} | Total: {total_count} orders")
    
    with col3:
        if st.button("Next ➡️", disabled=page >= total_pages, key="btn_next_page"):
            st.session_state.orders_page = page + 1
            st.rerun()


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
        
        # Prepare export dataframe
        export_df = orders[[
            'order_no', 'order_date', 'product_name', 'pt_code',
            'planned_qty', 'produced_qty', 'uom', 'status', 'priority',
            'scheduled_date', 'warehouse_name', 'target_warehouse_name', 'bom_name'
        ]].copy()
        
        export_df.columns = [
            'Order No', 'Order Date', 'Product', 'PT Code',
            'Planned Qty', 'Produced Qty', 'UOM', 'Status', 'Priority',
            'Scheduled Date', 'Source Warehouse', 'Target Warehouse', 'BOM'
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
    render_dashboard()
    
    st.markdown("---")
    
    filters = _render_filter_bar(queries)
    
    st.markdown("---")
    
    _render_action_bar(queries, filters)
    
    st.markdown("---")
    
    _render_order_list(queries, filters)
