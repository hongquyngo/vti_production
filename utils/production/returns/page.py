# utils/production/returns/page.py
"""
Main UI orchestrator for Returns domain
Version: 2.0.0 — client-side filtering, bulk load
"""

import logging
from datetime import timedelta
from typing import Dict, Any, Optional

import streamlit as st
import pandas as pd

from .queries import ReturnQueries
from .dashboard import render_dashboard_from_data
from .forms import render_return_form
from .dialogs import show_detail_dialog, show_pdf_dialog, check_pending_dialogs
from .common import (
    format_number, create_status_indicator, create_reason_display,
    format_datetime, format_datetime_vn, get_vietnam_today, export_to_excel, 
    ReturnConstants, format_product_display, format_material_display,
    PerformanceTimer
)

logger = logging.getLogger(__name__)


# ==================== Bootstrap Cache ====================

@st.cache_data(ttl=30, show_spinner=False)
def _cached_bootstrap() -> Dict[str, Any]:
    return ReturnQueries().bootstrap_all()


# ==================== Client-Side Helpers ====================

def _apply_filters(df: pd.DataFrame, filters: Dict[str, Any]) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    result = df.copy()
    
    from_date = filters.get('from_date')
    to_date = filters.get('to_date')
    if from_date and to_date:
        dt = pd.to_datetime(result['return_date'], errors='coerce')
        result = result[dt.between(pd.Timestamp(from_date),
                                    pd.Timestamp(to_date) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))]
    
    status = filters.get('status')
    if status:
        result = result[result['status'] == status]
    
    reason = filters.get('reason')
    if reason:
        result = result[result['reason'] == reason]
    
    order_no = filters.get('order_no')
    if order_no:
        result = result[result['order_no'].str.contains(order_no, case=False, na=False)]
    
    return result


def _derive_metrics(returns: Optional[pd.DataFrame], returnable_orders: int) -> Dict[str, Any]:
    empty = {'total_returns': 0, 'today_returns': 0, 'confirmed_count': 0,
             'returnable_orders': returnable_orders, 'total_units': 0, 'reason_breakdown': {}}
    if returns is None or returns.empty:
        return empty
    
    today = get_vietnam_today()
    today_ts = pd.Timestamp(today)
    today_end = today_ts + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    dt = pd.to_datetime(returns['return_date'], errors='coerce')
    
    reason_counts = returns['reason'].value_counts().to_dict()
    
    return {
        'total_returns': len(returns),
        'today_returns': int(dt.between(today_ts, today_end).sum()),
        'confirmed_count': int((returns['status'] == 'CONFIRMED').sum()),
        'returnable_orders': returnable_orders,
        'total_units': float(returns['total_qty'].sum()),
        'reason_breakdown': reason_counts,
    }


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

def _render_return_history(all_returns: Optional[pd.DataFrame], filters: Dict[str, Any]):
    """Render return history — client-side filtering, zero DB queries"""
    page_size = ReturnConstants.DEFAULT_PAGE_SIZE
    page = st.session_state.returns_page
    
    if all_returns is None:
        st.error("🔌 **Database Connection Error**")
        st.info("💡 Check VPN/network connection or contact IT support")
        return
    
    filtered = _apply_filters(all_returns, filters)
    total_count = len(filtered)
    
    if filtered.empty:
        st.info("📭 No returns found matching the filters")
        return
    
    offset = (page - 1) * page_size
    returns = filtered.iloc[offset:offset + page_size].reset_index(drop=True)
    
    # Initialize selected index in session state
    if 'returns_selected_idx' not in st.session_state:
        st.session_state.returns_selected_idx = None
    
    # Prepare display
    display_df = returns.copy()
    
    # Set Select column based on session state (single selection)
    display_df['Select'] = False
    if st.session_state.returns_selected_idx is not None and st.session_state.returns_selected_idx < len(display_df):
        display_df.loc[st.session_state.returns_selected_idx, 'Select'] = True
    
    display_df['status_display'] = display_df['status'].apply(create_status_indicator)
    display_df['reason_display'] = display_df['reason'].apply(create_reason_display)
    display_df['return_date_display'] = display_df['return_date'].apply(format_datetime_vn)
    display_df['product_display'] = display_df.apply(
        lambda x: format_product_display(
            pt_code=x['pt_code'],
            name=x['product_name'],
            legacy_pt_code=x.get('legacy_pt_code'),
            package_size=x.get('package_size'),
            brand_name=x.get('brand_name'),
            include_all=True
        ),
        axis=1
    )
    display_df['total_qty_display'] = display_df['total_qty'].apply(lambda x: format_number(x, 4))
    
    # Create editable dataframe with selection
    edited_df = st.data_editor(
        display_df[[
            'Select', 'return_no', 'return_date_display', 'order_no', 'product_display',
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
        hide_index=True,
        disabled=['Return No', 'Date', 'Order', 'Product', 'Reason', 'Items', 'Total Qty', 'Status'],
        column_config={
            'Select': st.column_config.CheckboxColumn(
                '✓',
                help='Select row to perform actions',
                default=False,
                width='small'
            )
        },
        key="returns_table_editor"
    )
    
    # Handle single selection - find newly selected row
    selected_indices = edited_df[edited_df['Select'] == True].index.tolist()
    
    if selected_indices:
        # If multiple selected (user clicked new one), keep only the newest
        if len(selected_indices) > 1:
            new_selection = [idx for idx in selected_indices if idx != st.session_state.returns_selected_idx]
            if new_selection:
                st.session_state.returns_selected_idx = new_selection[0]
                st.rerun()
        else:
            st.session_state.returns_selected_idx = selected_indices[0]
    else:
        st.session_state.returns_selected_idx = None
    
    # Action buttons - only show when row is selected
    if st.session_state.returns_selected_idx is not None:
        selected_return = returns.iloc[st.session_state.returns_selected_idx]
        
        st.markdown("---")
        st.markdown(f"**Selected:** `{selected_return['return_no']}` | {selected_return['order_no']} | {selected_return['product_name']}")
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            if st.button("👁️ View Details", type="primary", use_container_width=True, key="btn_view_return"):
                show_detail_dialog(selected_return['id'])
        
        with col2:
            if st.button("📄 Export PDF", use_container_width=True, key="btn_pdf_return"):
                show_pdf_dialog(selected_return['id'], selected_return['return_no'])
    else:
        st.info("💡 Tick checkbox to select a return and perform actions")
    
    # Pagination
    st.markdown("---")
    total_pages = max(1, (total_count + page_size - 1) // page_size)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col1:
        if st.button("⬅️ Previous", disabled=page <= 1, key="btn_prev_return"):
            st.session_state.returns_page = max(1, page - 1)
            st.session_state.returns_selected_idx = None  # Reset selection on page change
            st.rerun()
    
    with col2:
        st.markdown(f"<div style='text-align:center'>Page {page} of {total_pages} | Total: {total_count} returns</div>", unsafe_allow_html=True)
    
    with col3:
        if st.button("Next ➡️", disabled=page >= total_pages, key="btn_next_return"):
            st.session_state.returns_page = page + 1
            st.session_state.returns_selected_idx = None  # Reset selection on page change
            st.rerun()


# ==================== Action Bar ====================

def _render_action_bar(filters: Dict[str, Any]):
    """Render action bar"""
    col1, col2, col3 = st.columns([1, 1, 2])
    
    with col1:
        if st.button("↩️ Return Materials", type="primary", width='stretch',
                    key="btn_create_return"):
            st.session_state.returns_view = 'create'
            st.rerun()
    
    with col2:
        if st.button("📊 Export Excel", width='stretch', key="btn_export_returns"):
            _export_returns_excel(filters)
    
    with col3:
        if st.button("🔄 Refresh", width='stretch', key="btn_refresh_returns"):
            _cached_bootstrap.clear()
            st.rerun()


def _export_returns_excel(filters: Dict[str, Any]):
    """Export returns to Excel — uses cached data"""
    with st.spinner("Exporting..."):
        boot = _cached_bootstrap()
        all_returns = boot.get('returns')
        
        if all_returns is None or all_returns.empty:
            st.warning("No returns to export")
            return
        
        returns = _apply_filters(all_returns, filters)
        
        if returns.empty:
            st.warning("No returns to export")
            return
        
        # Create product display column with standardized format
        returns['product_display'] = returns.apply(
            lambda x: format_product_display(
                pt_code=x['pt_code'],
                name=x['product_name'],
                legacy_pt_code=x.get('legacy_pt_code'),
                package_size=x.get('package_size'),
                brand_name=x.get('brand_name'),
                include_all=True
            ),
            axis=1
        )
        
        export_df = returns[[
            'return_no', 'return_date', 'order_no', 'product_display',
            'reason', 'item_count', 'total_qty', 'status', 'warehouse_name',
            'returned_by_name', 'received_by_name'
        ]].copy()
        
        export_df.columns = [
            'Return No', 'Return Date', 'Order No', 'Product',
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
    """Main function to render the Returns tab"""
    _init_session_state()
    
    perf = PerformanceTimer("render_returns_tab")
    
    with perf.step("check_pending_dialogs"):
        check_pending_dialogs()
    
    if st.session_state.returns_view == 'create':
        if st.button("⬅️ Back to History", key="btn_back_to_returns_history"):
            st.session_state.returns_view = 'history'
            st.session_state.pop('return_success', None)
            st.session_state.pop('return_info', None)
            st.rerun()
        render_return_form()
        return
    
    st.subheader("↩️ Material Returns")
    
    with perf.step("bootstrap"):
        boot = _cached_bootstrap()
    
    all_returns = boot.get('returns')
    returnable_orders = boot.get('returnable_orders', 0)
    
    with perf.step("render_dashboard"):
        metrics = _derive_metrics(all_returns, returnable_orders)
        render_dashboard_from_data(metrics)
    
    with perf.step("render_filters"):
        filters = _render_filter_bar()
    
    with perf.step("render_action_bar"):
        _render_action_bar(filters)
    
    with perf.step("render_return_history"):
        _render_return_history(all_returns, filters)
    
    perf.summary()