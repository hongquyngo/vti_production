# utils/production/issues/page.py
"""
Main UI orchestrator for Issues domain
Renders the Issues tab with dashboard, issue form, and history

Version: 1.0.0
"""

import logging
from datetime import timedelta
from typing import Dict, Any, Optional

import streamlit as st
import pandas as pd

from .queries import IssueQueries
from .dashboard import render_dashboard
from .forms import render_issue_form
from .dialogs import show_detail_dialog, show_pdf_dialog, check_pending_dialogs
from .common import (
    format_number, create_status_indicator, format_datetime,
    get_vietnam_today, export_to_excel, IssueConstants
)

logger = logging.getLogger(__name__)


# ==================== Session State ====================

def _init_session_state():
    """Initialize session state for issues tab"""
    defaults = {
        'issues_page': 1,
        'issues_view': 'history',  # 'history' or 'create'
    }
    
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


# ==================== Filter Bar ====================

def _render_filter_bar() -> Dict[str, Any]:
    """Render filter bar and return selected filters"""
    default_to = get_vietnam_today()
    default_from = default_to - timedelta(days=30)
    
    with st.expander("🔍 Filters", expanded=False):
        col1, col2, col3, col4 = st.columns([1, 1, 1, 2])
        
        with col1:
            from_date = st.date_input(
                "From Date",
                value=default_from,
                key="issue_filter_from"
            )
        
        with col2:
            to_date = st.date_input(
                "To Date",
                value=default_to,
                key="issue_filter_to"
            )
        
        with col3:
            status = st.selectbox(
                "Status",
                options=['All', 'CONFIRMED', 'CANCELLED'],
                key="issue_filter_status"
            )
        
        with col4:
            order_no = st.text_input(
                "🔍 Search Order No",
                placeholder="Enter order number...",
                key="issue_filter_order"
            )
    
    return {
        'from_date': from_date,
        'to_date': to_date,
        'status': status if status != 'All' else None,
        'order_no': order_no if order_no else None
    }


# ==================== Issue History ====================

def _render_issue_history(queries: IssueQueries, filters: Dict[str, Any]):
    """Render issue history list"""
    page_size = IssueConstants.DEFAULT_PAGE_SIZE
    page = st.session_state.issues_page
    
    issues = queries.get_issues(
        from_date=filters['from_date'],
        to_date=filters['to_date'],
        order_no=filters['order_no'],
        status=filters['status'],
        page=page,
        page_size=page_size
    )
    
    total_count = queries.get_issues_count(
        from_date=filters['from_date'],
        to_date=filters['to_date'],
        order_no=filters['order_no'],
        status=filters['status']
    )
    
    if issues.empty:
        st.info("📭 No issues found matching the filters")
        return
    
    # Prepare display
    display_df = issues.copy()
    display_df['status_display'] = display_df['status'].apply(create_status_indicator)
    display_df['issue_date_display'] = pd.to_datetime(display_df['issue_date']).dt.strftime('%d/%m/%Y %H:%M')
    display_df['product_display'] = display_df.apply(
        lambda x: f"{x['pt_code']} - {x['product_name']}" if x['pt_code'] else x['product_name'],
        axis=1
    )
    
    # Display table
    st.dataframe(
        display_df[[
            'issue_no', 'issue_date_display', 'order_no', 'product_display',
            'item_count', 'status_display', 'warehouse_name'
        ]].rename(columns={
            'issue_no': 'Issue No',
            'issue_date_display': 'Date',
            'order_no': 'Order',
            'product_display': 'Product',
            'item_count': 'Items',
            'status_display': 'Status',
            'warehouse_name': 'Warehouse'
        }),
        use_container_width=True,
        hide_index=True
    )
    
    # Row actions
    st.markdown("### Actions")
    
    issue_options = {
        f"{row['issue_no']} | {row['order_no']} | {row['product_name']}": row
        for _, row in issues.iterrows()
    }
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        selected_label = st.selectbox(
            "Select Issue",
            options=list(issue_options.keys()),
            key="issue_action_select"
        )
    
    selected_issue = issue_options[selected_label]
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("👁️ View Details", use_container_width=True, key="btn_view_issue"):
            show_detail_dialog(selected_issue['id'])
    
    with col2:
        if st.button("📄 Export PDF", use_container_width=True, key="btn_pdf_issue"):
            show_pdf_dialog(selected_issue['id'], selected_issue['issue_no'])
    
    # Pagination
    st.markdown("---")
    total_pages = max(1, (total_count + page_size - 1) // page_size)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col1:
        if st.button("⬅️ Previous", disabled=page <= 1, key="btn_prev_issue"):
            st.session_state.issues_page = max(1, page - 1)
            st.rerun()
    
    with col2:
        st.write(f"Page {page} of {total_pages} | Total: {total_count} issues")
    
    with col3:
        if st.button("Next ➡️", disabled=page >= total_pages, key="btn_next_issue"):
            st.session_state.issues_page = page + 1
            st.rerun()


# ==================== Action Bar ====================

def _render_action_bar(queries: IssueQueries, filters: Dict[str, Any]):
    """Render action bar"""
    col1, col2, col3 = st.columns([1, 1, 2])
    
    with col1:
        if st.button("📦 Issue Materials", type="primary", use_container_width=True,
                    key="btn_create_issue"):
            st.session_state.issues_view = 'create'
            st.rerun()
    
    with col2:
        if st.button("📊 Export Excel", use_container_width=True, key="btn_export_issues"):
            _export_issues_excel(queries, filters)
    
    with col3:
        if st.button("🔄 Refresh", use_container_width=True, key="btn_refresh_issues"):
            st.rerun()


def _export_issues_excel(queries: IssueQueries, filters: Dict[str, Any]):
    """Export issues to Excel"""
    with st.spinner("Exporting..."):
        issues = queries.get_issues(
            from_date=filters['from_date'],
            to_date=filters['to_date'],
            order_no=filters['order_no'],
            status=filters['status'],
            page=1,
            page_size=10000
        )
        
        if issues.empty:
            st.warning("No issues to export")
            return
        
        export_df = issues[[
            'issue_no', 'issue_date', 'order_no', 'product_name', 'pt_code',
            'item_count', 'status', 'warehouse_name', 'issued_by_name', 'received_by_name'
        ]].copy()
        
        export_df.columns = [
            'Issue No', 'Issue Date', 'Order No', 'Product', 'PT Code',
            'Items', 'Status', 'Warehouse', 'Issued By', 'Received By'
        ]
        
        excel_data = export_to_excel(export_df)
        
        filename = f"Material_Issues_{get_vietnam_today().strftime('%Y%m%d')}.xlsx"
        
        st.download_button(
            label="💾 Download Excel",
            data=excel_data,
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_issues_excel"
        )


# ==================== Main Render Function ====================

def render_issues_tab():
    """
    Main function to render the Issues tab
    Called from the main Production page
    """
    _init_session_state()
    
    # Check for pending dialogs (e.g., PDF dialog triggered from detail dialog)
    check_pending_dialogs()
    
    queries = IssueQueries()
    
    # Check current view
    if st.session_state.issues_view == 'create':
        if st.button("⬅️ Back to History", key="btn_back_to_issues_history"):
            st.session_state.issues_view = 'history'
            st.rerun()
        
        render_issue_form()
        return
    
    # History view
    st.subheader("📦 Material Issues")
    
    # Dashboard
    render_dashboard()

    # Filters
    filters = _render_filter_bar()

    # Action bar
    _render_action_bar(queries, filters)

    # Issue list
    _render_issue_history(queries, filters)
