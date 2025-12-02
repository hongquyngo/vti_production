# utils/production/completions/page.py
"""
Main UI orchestrator for Completions domain
Renders the Completions tab with dashboard, completion form, and receipts list

Version: 1.0.0
"""

import logging
from datetime import timedelta
from typing import Dict, Any, Optional

import streamlit as st
import pandas as pd

from .queries import CompletionQueries
from .dashboard import render_dashboard
from .forms import render_completion_form
from .dialogs import (
    show_receipt_details_dialog, show_update_quality_dialog,
    show_pdf_dialog, check_pending_dialogs
)
from .common import (
    format_number, create_status_indicator, get_yield_indicator,
    calculate_percentage, format_datetime, get_vietnam_today, get_vietnam_now,
    export_to_excel, get_date_filter_presets, CompletionConstants
)

logger = logging.getLogger(__name__)


# ==================== Session State ====================

def _init_session_state():
    """Initialize session state for completions tab"""
    defaults = {
        'completions_page': 1,
        'completions_view': 'receipts',  # 'receipts' or 'create'
    }
    
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


# ==================== Filter Bar ====================

def _render_filter_bar(queries: CompletionQueries) -> Dict[str, Any]:
    """Render filter bar and return selected filters"""
    presets = get_date_filter_presets()
    
    with st.expander("🔍 Filters", expanded=False):
        col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
        
        with col1:
            date_range = st.selectbox(
                "Date Range",
                options=list(presets.keys()),
                index=6,  # Last 30 Days
                key="completion_date_range"
            )
            from_date, to_date = presets[date_range]
        
        with col2:
            quality_options = ['All'] + [q[0] for q in CompletionConstants.QUALITY_STATUSES]
            quality_status = st.selectbox(
                "Quality Status",
                options=quality_options,
                key="completion_quality_filter"
            )
        
        with col3:
            products = queries.get_products()
            product_options = ["All Products"] + products['name'].tolist() if not products.empty else ["All Products"]
            selected_product = st.selectbox(
                "Product",
                options=product_options,
                key="completion_product_filter"
            )
            product_id = None
            if selected_product != "All Products" and not products.empty:
                product_id = int(products[products['name'] == selected_product]['id'].iloc[0])
        
        with col4:
            warehouses = queries.get_warehouses()
            warehouse_options = ["All Warehouses"] + warehouses['name'].tolist() if not warehouses.empty else ["All Warehouses"]
            selected_warehouse = st.selectbox(
                "Warehouse",
                options=warehouse_options,
                key="completion_warehouse_filter"
            )
            warehouse_id = None
            if selected_warehouse != "All Warehouses" and not warehouses.empty:
                warehouse_id = int(warehouses[warehouses['name'] == selected_warehouse]['id'].iloc[0])
        
        col5, col6 = st.columns(2)
        with col5:
            order_no = st.text_input(
                "🔍 Order No",
                placeholder="Search by order number...",
                key="completion_order_filter"
            )
        with col6:
            batch_no = st.text_input(
                "🔍 Batch No",
                placeholder="Search by batch number...",
                key="completion_batch_filter"
            )
    
    return {
        'from_date': from_date,
        'to_date': to_date,
        'quality_status': quality_status if quality_status != 'All' else None,
        'product_id': product_id,
        'warehouse_id': warehouse_id,
        'order_no': order_no if order_no else None,
        'batch_no': batch_no if batch_no else None
    }


# ==================== Receipts List ====================

def _render_receipts_list(queries: CompletionQueries, filters: Dict[str, Any]):
    """Render production receipts list"""
    page_size = CompletionConstants.DEFAULT_PAGE_SIZE
    page = st.session_state.completions_page
    
    receipts = queries.get_receipts(
        from_date=filters['from_date'],
        to_date=filters['to_date'],
        quality_status=filters['quality_status'],
        product_id=filters['product_id'],
        warehouse_id=filters['warehouse_id'],
        order_no=filters['order_no'],
        batch_no=filters['batch_no'],
        page=page,
        page_size=page_size
    )
    
    total_count = queries.get_receipts_count(
        from_date=filters['from_date'],
        to_date=filters['to_date'],
        quality_status=filters['quality_status'],
        product_id=filters['product_id'],
        warehouse_id=filters['warehouse_id'],
        order_no=filters['order_no'],
        batch_no=filters['batch_no']
    )
    
    if receipts.empty:
        st.info("📭 No production receipts found matching the filters")
        return
    
    # Summary metrics
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total Receipts", len(receipts))
    
    with col2:
        total_qty = receipts['quantity'].sum()
        st.metric("Total Quantity", format_number(total_qty, 0))
    
    with col3:
        passed = len(receipts[receipts['quality_status'] == 'PASSED'])
        pass_rate = calculate_percentage(passed, len(receipts), 1)
        indicator = get_yield_indicator(pass_rate)
        st.metric("Pass Rate", f"{pass_rate}% {indicator}")
    
    with col4:
        avg_yield = receipts['yield_rate'].mean()
        yield_indicator = get_yield_indicator(avg_yield)
        st.metric("Avg Yield Rate", f"{avg_yield:.1f}% {yield_indicator}")
    
    # Quality breakdown expander
    with st.expander("📈 Quality Breakdown", expanded=False):
        col1, col2, col3 = st.columns(3)
        passed_count = len(receipts[receipts['quality_status'] == 'PASSED'])
        pending_count = len(receipts[receipts['quality_status'] == 'PENDING'])
        failed_count = len(receipts[receipts['quality_status'] == 'FAILED'])
        
        total_receipts = len(receipts)
        
        with col1:
            st.metric("✅ PASSED", passed_count, 
                     f"{calculate_percentage(passed_count, total_receipts)}%")
        with col2:
            st.metric("⏳ PENDING", pending_count,
                     f"{calculate_percentage(pending_count, total_receipts)}%")
        with col3:
            st.metric("❌ FAILED", failed_count,
                     f"{calculate_percentage(failed_count, total_receipts)}%")
    
    st.markdown("---")
    st.markdown("### 📋 Receipts List")
    
    # Prepare display
    display_df = receipts.copy()
    display_df['receipt_date_display'] = pd.to_datetime(display_df['receipt_date']).dt.strftime('%d-%b-%Y')
    display_df['quality_display'] = display_df['quality_status'].apply(create_status_indicator)
    display_df['yield_display'] = display_df['yield_rate'].apply(
        lambda x: f"{x:.1f}% {get_yield_indicator(x)}"
    )
    display_df['qty_display'] = display_df.apply(
        lambda x: f"{format_number(x['quantity'], 0)} {x['uom']}", axis=1
    )
    
    # Display table
    st.dataframe(
        display_df[[
            'receipt_no', 'receipt_date_display', 'order_no', 'product_name',
            'qty_display', 'batch_no', 'quality_display', 'yield_display', 'warehouse_name'
        ]].rename(columns={
            'receipt_no': 'Receipt No',
            'receipt_date_display': 'Date',
            'order_no': 'Order No',
            'product_name': 'Product',
            'qty_display': 'Quantity',
            'batch_no': 'Batch',
            'quality_display': 'Quality',
            'yield_display': 'Yield',
            'warehouse_name': 'Warehouse'
        }),
        use_container_width=True,
        hide_index=True
    )
    
    st.markdown("---")
    st.markdown("### ⚡ Quick Actions")
    
    # Row actions
    col1, col2, col3 = st.columns([2, 2, 1])
    
    with col1:
        receipt_options = {
            f"{row['receipt_no']} | {row['order_no']} | {row['product_name']}": row
            for _, row in receipts.iterrows()
        }
        selected_label = st.selectbox(
            "Select Receipt",
            options=list(receipt_options.keys()),
            key="receipt_action_select"
        )
    
    with col2:
        action = st.selectbox(
            "Action",
            options=["View Details", "Update Quality", "Export PDF"],
            key="receipt_action_type"
        )
    
    with col3:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("Execute", type="primary", use_container_width=True,
                    key="receipt_execute_btn"):
            selected_receipt = receipt_options[selected_label]
            if action == "View Details":
                show_receipt_details_dialog(selected_receipt['id'])
            elif action == "Update Quality":
                show_update_quality_dialog(selected_receipt['id'])
            elif action == "Export PDF":
                show_pdf_dialog(selected_receipt['id'], selected_receipt['receipt_no'])
    
    # Pagination
    st.markdown("---")
    total_pages = max(1, (total_count + page_size - 1) // page_size)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col1:
        if st.button("⬅️ Previous", disabled=page <= 1, key="btn_prev_receipt"):
            st.session_state.completions_page = max(1, page - 1)
            st.rerun()
    
    with col2:
        st.write(f"Page {page} of {total_pages} | Total: {total_count} receipts")
    
    with col3:
        if st.button("Next ➡️", disabled=page >= total_pages, key="btn_next_receipt"):
            st.session_state.completions_page = page + 1
            st.rerun()


# ==================== Action Bar ====================

def _render_action_bar(queries: CompletionQueries, filters: Dict[str, Any]):
    """Render action bar"""
    col1, col2, col3 = st.columns([1, 1, 2])
    
    with col1:
        if st.button("✅ Record Output", type="primary", use_container_width=True,
                    key="btn_record_output"):
            st.session_state.completions_view = 'create'
            st.rerun()
    
    with col2:
        if st.button("📊 Export Excel", use_container_width=True, key="btn_export_receipts"):
            _export_receipts_excel(queries, filters)
    
    with col3:
        if st.button("🔄 Refresh", use_container_width=True, key="btn_refresh_completions"):
            st.rerun()


def _export_receipts_excel(queries: CompletionQueries, filters: Dict[str, Any]):
    """Export receipts to Excel"""
    with st.spinner("Exporting..."):
        receipts = queries.get_receipts(
            from_date=filters['from_date'],
            to_date=filters['to_date'],
            quality_status=filters['quality_status'],
            product_id=filters['product_id'],
            warehouse_id=filters['warehouse_id'],
            order_no=filters['order_no'],
            batch_no=filters['batch_no'],
            page=1,
            page_size=10000
        )
        
        if receipts.empty:
            st.warning("No receipts to export")
            return
        
        export_df = receipts[[
            'receipt_no', 'receipt_date', 'order_no', 'product_name', 'pt_code',
            'quantity', 'uom', 'batch_no', 'quality_status', 'yield_rate', 'warehouse_name'
        ]].copy()
        
        export_df.columns = [
            'Receipt No', 'Receipt Date', 'Order No', 'Product', 'PT Code',
            'Quantity', 'UOM', 'Batch', 'Quality Status', 'Yield Rate', 'Warehouse'
        ]
        
        excel_data = export_to_excel(export_df)
        
        filename = f"Production_Receipts_{get_vietnam_today().strftime('%Y%m%d')}.xlsx"
        
        st.download_button(
            label="💾 Download Excel",
            data=excel_data,
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_receipts_excel"
        )


# ==================== Main Render Function ====================

def render_completions_tab():
    """
    Main function to render the Completions tab
    Called from the main Production page
    """
    _init_session_state()
    
    # Check for pending dialogs
    check_pending_dialogs()
    
    queries = CompletionQueries()
    
    # Check current view
    if st.session_state.completions_view == 'create':
        if st.button("⬅️ Back to Receipts", key="btn_back_to_receipts"):
            st.session_state.completions_view = 'receipts'
            st.session_state.pop('completion_success', None)
            st.session_state.pop('completion_info', None)
            st.rerun()
        
        render_completion_form()
        return
    
    # Receipts view
    st.subheader("✅ Production Completions")
    
    # Dashboard
    render_dashboard()

    # Filters
    filters = _render_filter_bar(queries)

    # Action bar
    _render_action_bar(queries, filters)

    # Receipts list
    _render_receipts_list(queries, filters)
