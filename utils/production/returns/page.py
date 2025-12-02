# utils/production/returns/page.py
"""
Main UI orchestrator for Returns domain
Renders the Returns tab with dashboard, return form, and history

Version: 1.0.0
"""

import logging
from datetime import timedelta
from typing import Dict, Any, Optional

import streamlit as st
import pandas as pd

from .queries import ReturnQueries
from .dashboard import render_dashboard
from .forms import render_return_form
from .dialogs import show_detail_dialog, show_pdf_dialog, check_pending_dialogs
from .common import (
    format_number, create_status_indicator, create_reason_display,
    format_datetime, get_vietnam_today, export_to_excel, ReturnConstants
)

logger = logging.getLogger(__name__)


# ==================== Session State ====================

def _init_session_state():
    """Initialize session state for returns tab"""
    defaults = {
        'returns_page': 1,
        'returns_view': 'history',  # 'history' or 'create'
    }
    
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


# ==================== Filter Bar ====================

def _render_filter_bar() -> Dict[str, Any]:
    """Render filter bar and return selected filters"""
    default_to = get_vietnam_today()
    default_from = default_to - timedelta(days=30)
    
    with st.expander("🔍 Filters", expanded=False):
        col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
        
        with col1:
            from_date = st.date_input(
                "From Date",
                value=default_from,
                key="return_filter_from"
            )
        
        with col2:
            to_date = st.date_input(
                "To Date",
                value=default_to,
                key="return_filter_to"
            )
        
        with col3:
            status = st.selectbox(
                "Status",
                options=['All', 'CONFIRMED', 'CANCELLED'],
                key="return_filter_status"
            )
        
        with col4:
            reason_options = ['All'] + [r[0] for r in ReturnConstants.REASONS]
            reason = st.selectbox(
                "Reason",
                options=reason_options,
                key="return_filter_reason"
            )
        
        order_no = st.text_input(
            "🔍 Search Order No",
            placeholder="Enter order number...",
            key="return_filter_order"
        )
    
    return {
        'from_date': from_date,
        'to_date': to_date,
        'status': status if status != 'All' else None,
        'reason': reason if reason != 'All' else None,
        'order_no': order_no if order_no else None
    }


# ==================== Return History ====================

def _render_return_history(queries: ReturnQueries, filters: Dict[str, Any]):
    """Render return history list"""
    page_size = ReturnConstants.DEFAULT_PAGE_SIZE
    page = st.session_state.returns_page
    
    returns = queries.get_returns(
        from_date=filters['from_date'],
        to_date=filters['to_date'],
        order_no=filters['order_no'],
        status=filters['status'],
        reason=filters['reason'],
        page=page,
        page_size=page_size
    )
    
    total_count = queries.get_returns_count(
        from_date=filters['from_date'],
        to_date=filters['to_date'],
        order_no=filters['order_no'],
        status=filters['status'],
        reason=filters['reason']
    )
    
    if returns.empty:
        st.info("📭 No returns found matching the filters")
        return
    
    # Prepare display
    display_df = returns.copy()
    display_df['status_display'] = display_df['status'].apply(create_status_indicator)
    display_df['reason_display'] = display_df['reason'].apply(create_reason_display)
    display_df['return_date_display'] = pd.to_datetime(display_df['return_date']).dt.strftime('%d/%m/%Y %H:%M')
    display_df['product_display'] = display_df.apply(
        lambda x: f"{x['pt_code']} - {x['product_name']}" if x['pt_code'] else x['product_name'],
        axis=1
    )
    display_df['total_qty_display'] = display_df['total_qty'].apply(lambda x: format_number(x, 4))
    
    # Display table
    st.dataframe(
        display_df[[
            'return_no', 'return_date_display', 'order_no', 'product_display',
            'reason_display', 'item_count', 'total_qty_display', 'status_display'
        ]].rename(columns={
            'return_no': 'Return No',
            'return_date_display': 'Date',
            'order_no': 'Order',
            'product_display': 'Product',
            'reason_display': 'Reason',
            'item_count': 'Items',
            'total_qty_display': 'Total Qty',
            'status_display': 'Status'
        }),
        use_container_width=True,
        hide_index=True
    )
    
    # Row actions
    st.markdown("### Actions")
    
    return_options = {
        f"{row['return_no']} | {row['order_no']} | {row['product_name']}": row
        for _, row in returns.iterrows()
    }
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        selected_label = st.selectbox(
            "Select Return",
            options=list(return_options.keys()),
            key="return_action_select"
        )
    
    selected_return = return_options[selected_label]
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("👁️ View Details", use_container_width=True, key="btn_view_return"):
            show_detail_dialog(selected_return['id'])
    
    with col2:
        if st.button("📄 Export PDF", use_container_width=True, key="btn_pdf_return"):
            show_pdf_dialog(selected_return['id'], selected_return['return_no'])
    
    # Pagination
    st.markdown("---")
    total_pages = max(1, (total_count + page_size - 1) // page_size)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col1:
        if st.button("⬅️ Previous", disabled=page <= 1, key="btn_prev_return"):
            st.session_state.returns_page = max(1, page - 1)
            st.rerun()
    
    with col2:
        st.write(f"Page {page} of {total_pages} | Total: {total_count} returns")
    
    with col3:
        if st.button("Next ➡️", disabled=page >= total_pages, key="btn_next_return"):
            st.session_state.returns_page = page + 1
            st.rerun()


# ==================== Action Bar ====================

def _render_action_bar(queries: ReturnQueries, filters: Dict[str, Any]):
    """Render action bar"""
    col1, col2, col3 = st.columns([1, 1, 2])
    
    with col1:
        if st.button("↩️ Return Materials", type="primary", use_container_width=True,
                    key="btn_create_return"):
            st.session_state.returns_view = 'create'
            st.rerun()
    
    with col2:
        if st.button("📊 Export Excel", use_container_width=True, key="btn_export_returns"):
            _export_returns_excel(queries, filters)
    
    with col3:
        if st.button("🔄 Refresh", use_container_width=True, key="btn_refresh_returns"):
            st.rerun()


def _export_returns_excel(queries: ReturnQueries, filters: Dict[str, Any]):
    """Export returns to Excel"""
    with st.spinner("Exporting..."):
        returns = queries.get_returns(
            from_date=filters['from_date'],
            to_date=filters['to_date'],
            order_no=filters['order_no'],
            status=filters['status'],
            reason=filters['reason'],
            page=1,
            page_size=10000
        )
        
        if returns.empty:
            st.warning("No returns to export")
            return
        
        export_df = returns[[
            'return_no', 'return_date', 'order_no', 'product_name', 'pt_code',
            'reason', 'item_count', 'total_qty', 'status', 'warehouse_name',
            'returned_by_name', 'received_by_name'
        ]].copy()
        
        export_df.columns = [
            'Return No', 'Return Date', 'Order No', 'Product', 'PT Code',
            'Reason', 'Items', 'Total Qty', 'Status', 'Warehouse',
            'Returned By', 'Received By'
        ]
        
        excel_data = export_to_excel(export_df)
        
        filename = f"Material_Returns_{get_vietnam_today().strftime('%Y%m%d')}.xlsx"
        
        st.download_button(
            label="💾 Download Excel",
            data=excel_data,
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_returns_excel"
        )


# ==================== Main Render Function ====================

def render_returns_tab():
    """
    Main function to render the Returns tab
    Called from the main Production page
    """
    _init_session_state()
    
    # Check for pending dialogs (e.g., PDF dialog triggered from detail dialog)
    check_pending_dialogs()
    
    queries = ReturnQueries()
    
    # Check current view
    if st.session_state.returns_view == 'create':
        if st.button("⬅️ Back to History", key="btn_back_to_returns_history"):
            st.session_state.returns_view = 'history'
            st.session_state.pop('return_success', None)
            st.session_state.pop('return_info', None)
            st.rerun()
        
        render_return_form()
        return
    
    # History view
    st.subheader("↩️ Material Returns")
    
    # Dashboard
    render_dashboard()
    
    st.markdown("---")
    
    # Filters
    filters = _render_filter_bar()
    
    st.markdown("---")
    
    # Action bar
    _render_action_bar(queries, filters)
    
    st.markdown("---")
    
    # Return list
    _render_return_history(queries, filters)
