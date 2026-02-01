# utils/production/orders/page.py
"""
Main UI orchestrator for Orders domain
Renders the Orders tab with dashboard, filters, list, and actions

Version: 1.6.0
Changes:
- v1.6.0: Added Pivot View for data analysis
          + View switcher: List View / Pivot View
          + Pivot uses st.form + fragments for performance
          + No full page rerun when changing pivot options
- v1.5.0: Advanced multiselect filters
- v1.3.0: Performance optimization with fragment isolation
- v1.2.0: Added BOM conflict detection and warning
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
from .pivot_view import render_pivot_view
from .dialogs import (
    show_detail_dialog, show_edit_dialog, show_confirm_dialog,
    show_cancel_dialog, show_delete_dialog, show_pdf_dialog,
    check_pending_dialogs
)
from .common import (
    format_number, create_status_indicator, calculate_percentage, format_datetime_vn,
    get_vietnam_today, export_to_excel, OrderConstants, OrderValidator,
    format_product_display, format_date, get_date_filter_presets, get_default_date_range
)

logger = logging.getLogger(__name__)


# ==================== Session State ====================

def _init_session_state():
    """Initialize session state for orders tab"""
    defaults = {
        'orders_page': 1,
        'orders_view': 'pivot',  # 'list', 'create', or 'pivot'
        'orders_conflicts_only': False,
        'orders_conflict_check_active_only': True,
        'orders_date_type': 'scheduled',
    }
    
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


# ==================== View Switcher ====================

def _render_view_switcher() -> str:
    """Render view switcher tabs for List/Pivot views"""
    current_view = st.session_state.get('orders_view', 'list')
    
    if current_view == 'create':
        return current_view
    
    col1, col2, col3 = st.columns([1, 1, 4])
    
    with col1:
        list_selected = current_view == 'list'
        if st.button(
            "📋 List View",
            type="primary" if list_selected else "secondary",
            use_container_width=True,
            key="btn_view_list"
        ):
            if not list_selected:
                st.session_state.orders_view = 'list'
                st.rerun()
    
    with col2:
        pivot_selected = current_view == 'pivot'
        if st.button(
            "📊 Pivot View",
            type="primary" if pivot_selected else "secondary",
            use_container_width=True,
            key="btn_view_pivot"
        ):
            if not pivot_selected:
                st.session_state.orders_view = 'pivot'
                st.rerun()
    
    return current_view


# ==================== Filter Bar ====================

@st.cache_data(ttl=300)
def _get_search_options(_queries: OrderQueries) -> Dict[str, Any]:
    """Cache search filter options (5 min TTL)"""
    return _queries.get_search_filter_options()


def _render_filter_bar(queries: OrderQueries) -> Dict[str, Any]:
    """Render filter bar with multiselect widgets"""
    filter_options = queries.get_filter_options()
    search_options = _get_search_options(queries)
    
    date_type = st.session_state.get('orders_date_type', 'scheduled')
    default_from, default_to = get_default_date_range(date_type)
    default_statuses = ['DRAFT', 'CONFIRMED', 'IN_PROGRESS']
    
    with st.expander("🔍 Filters", expanded=True):
        st.markdown("##### 📋 Status & Type")
        col1, col2, col3 = st.columns([2, 1.5, 1.5])
        
        with col1:
            status_list = st.multiselect(
                "Status",
                options=filter_options['statuses'],
                default=default_statuses,
                key="order_filter_status",
                help="Select one or more statuses. Empty = All statuses"
            )
        
        with col2:
            order_type_list = st.multiselect(
                "Type",
                options=filter_options['order_types'],
                default=[],
                key="order_filter_type",
                help="Select BOM types. Empty = All types"
            )
        
        with col3:
            priority_list = st.multiselect(
                "Priority",
                options=filter_options['priorities'],
                default=[],
                key="order_filter_priority",
                help="Select priorities. Empty = All priorities"
            )
        
        st.markdown("---")
        st.markdown("##### 🔍 Search By")
        
        col1, col2 = st.columns(2)
        
        with col1:
            products_df = search_options.get('products', pd.DataFrame())
            if not products_df.empty:
                product_options = {
                    f"{row['pt_code']} | {row['product_name']} | {row['package_size'] or ''} ({row['brand_name']})": row['id']
                    for _, row in products_df.iterrows()
                }
                selected_products = st.multiselect(
                    "Products",
                    options=list(product_options.keys()),
                    default=[],
                    key="order_filter_products",
                    help="Filter by specific products"
                )
                product_ids = [product_options[p] for p in selected_products]
            else:
                st.multiselect("Products", options=[], key="order_filter_products_empty")
                product_ids = []
        
        with col2:
            boms_df = search_options.get('boms', pd.DataFrame())
            if not boms_df.empty:
                bom_options = {
                    f"{row['bom_code']} | {row['bom_name']} ({row['bom_type']})": row['id']
                    for _, row in boms_df.iterrows()
                }
                selected_boms = st.multiselect(
                    "BOMs",
                    options=list(bom_options.keys()),
                    default=[],
                    key="order_filter_boms",
                    help="Filter by specific BOMs"
                )
                bom_ids = [bom_options[b] for b in selected_boms]
            else:
                st.multiselect("BOMs", options=[], key="order_filter_boms_empty")
                bom_ids = []
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            brands_df = search_options.get('brands', pd.DataFrame())
            if not brands_df.empty:
                brand_options = {row['brand_name']: row['id'] for _, row in brands_df.iterrows()}
                selected_brands = st.multiselect(
                    "Brands",
                    options=list(brand_options.keys()),
                    default=[],
                    key="order_filter_brands"
                )
                brand_ids = [brand_options[b] for b in selected_brands]
            else:
                st.multiselect("Brands", options=[], key="order_filter_brands_empty")
                brand_ids = []
        
        with col2:
            warehouses_df = search_options.get('warehouses', pd.DataFrame())
            if not warehouses_df.empty:
                warehouse_options = {row['name']: row['id'] for _, row in warehouses_df.iterrows()}
                selected_source_wh = st.multiselect(
                    "Source Warehouse",
                    options=list(warehouse_options.keys()),
                    default=[],
                    key="order_filter_source_wh"
                )
                source_warehouse_ids = [warehouse_options[w] for w in selected_source_wh]
            else:
                st.multiselect("Source Warehouse", options=[], key="order_filter_source_wh_empty")
                source_warehouse_ids = []
        
        with col3:
            if not warehouses_df.empty:
                selected_target_wh = st.multiselect(
                    "Target Warehouse",
                    options=list(warehouse_options.keys()),
                    default=[],
                    key="order_filter_target_wh"
                )
                target_warehouse_ids = [warehouse_options[w] for w in selected_target_wh]
            else:
                st.multiselect("Target Warehouse", options=[], key="order_filter_target_wh_empty")
                target_warehouse_ids = []
        
        with col4:
            order_no_search = st.text_input(
                "Order No",
                placeholder="MO-2026...",
                key="order_filter_order_no"
            )
            order_nos = [order_no_search.strip()] if order_no_search.strip() else []
        
        st.markdown("---")
        st.markdown("##### 📅 Date Range")
        
        col1, col2, col3, col4 = st.columns([1, 1.5, 1.5, 2])
        
        with col1:
            date_type_display = st.selectbox(
                "Filter By",
                options=['scheduled', 'order'],
                format_func=lambda x: '📅 Scheduled Date' if x == 'scheduled' else '📋 Order Date',
                index=0 if date_type == 'scheduled' else 1,
                key="order_filter_date_type"
            )
            
            if date_type_display != date_type:
                st.session_state.orders_date_type = date_type_display
                default_from, default_to = get_default_date_range(date_type_display)
        
        with col2:
            from_date = st.date_input(
                "From Date",
                value=default_from,
                key="order_filter_from_date"
            )
        
        with col3:
            to_date = st.date_input(
                "To Date",
                value=default_to,
                key="order_filter_to_date"
            )
        
        with col4:
            include_future = date_type_display == 'scheduled'
            presets = get_date_filter_presets(include_future=include_future)
            preset_names = ["Custom"] + list(presets.keys())
            
            st.selectbox(
                "Quick Select",
                options=preset_names,
                index=0,
                key="order_filter_date_preset",
                help="Quick date range presets"
            )
        
        st.markdown("---")
        col1, col2, col3 = st.columns([1, 1, 2])
        
        with col1:
            conflicts_only = st.checkbox(
                "⚠️ Show Conflicts Only",
                value=st.session_state.get('orders_conflicts_only', False),
                key="order_filter_conflicts_only"
            )
            st.session_state.orders_conflicts_only = conflicts_only
        
        with col2:
            conflict_check_active = st.checkbox(
                "Check Active BOMs Only",
                value=st.session_state.get('orders_conflict_check_active_only', True),
                key="order_filter_conflict_active"
            )
            st.session_state.orders_conflict_check_active_only = conflict_check_active
    
    return {
        'status': status_list if status_list else None,
        'order_type': order_type_list if order_type_list else None,
        'priority': priority_list if priority_list else None,
        'product_ids': product_ids if product_ids else None,
        'bom_ids': bom_ids if bom_ids else None,
        'brand_ids': brand_ids if brand_ids else None,
        'source_warehouse_ids': source_warehouse_ids if source_warehouse_ids else None,
        'target_warehouse_ids': target_warehouse_ids if target_warehouse_ids else None,
        'order_nos': order_nos if order_nos else None,
        'from_date': from_date,
        'to_date': to_date,
        'date_type': date_type_display,
        'conflicts_only': conflicts_only,
        'conflict_check_active_only': conflict_check_active
    }


# ==================== BOM Conflict Warning ====================

def _render_conflict_warning(queries: OrderQueries, filters: Dict[str, Any]):
    """Render BOM conflict warning banner if conflicts exist"""
    conflict_summary = queries.get_bom_conflict_summary(
        active_only=filters.get('conflict_check_active_only', True),
        from_date=filters.get('from_date'),
        to_date=filters.get('to_date')
    )
    
    if conflict_summary['total_conflict_orders'] > 0:
        st.warning(f"""
        ⚠️ **BOM Conflict Alert:** {conflict_summary['total_conflict_orders']} order(s) 
        affecting {conflict_summary['affected_products']} product(s) have multiple active BOMs.
        """)


# ==================== Order List ====================

@st.fragment
def _render_order_list(queries: OrderQueries, filters: Dict[str, Any]):
    """Render order list table with selection and pagination (Fragment)"""
    page = st.session_state.get('orders_page', 1)
    page_size = OrderConstants.DEFAULT_PAGE_SIZE
    
    orders = queries.get_orders(
        status=filters.get('status'),
        order_type=filters.get('order_type'),
        priority=filters.get('priority'),
        product_ids=filters.get('product_ids'),
        bom_ids=filters.get('bom_ids'),
        brand_ids=filters.get('brand_ids'),
        source_warehouse_ids=filters.get('source_warehouse_ids'),
        target_warehouse_ids=filters.get('target_warehouse_ids'),
        order_nos=filters.get('order_nos'),
        from_date=filters.get('from_date'),
        to_date=filters.get('to_date'),
        date_type=filters.get('date_type', 'scheduled'),
        conflicts_only=filters.get('conflicts_only', False),
        conflict_check_active_only=filters.get('conflict_check_active_only', True),
        page=page,
        page_size=page_size
    )
    
    total_count = queries.get_orders_count(
        status=filters.get('status'),
        order_type=filters.get('order_type'),
        priority=filters.get('priority'),
        product_ids=filters.get('product_ids'),
        bom_ids=filters.get('bom_ids'),
        brand_ids=filters.get('brand_ids'),
        source_warehouse_ids=filters.get('source_warehouse_ids'),
        target_warehouse_ids=filters.get('target_warehouse_ids'),
        order_nos=filters.get('order_nos'),
        from_date=filters.get('from_date'),
        to_date=filters.get('to_date'),
        date_type=filters.get('date_type', 'scheduled'),
        conflicts_only=filters.get('conflicts_only', False),
        conflict_check_active_only=filters.get('conflict_check_active_only', True)
    )
    
    if orders is None:
        error_msg = queries.get_last_error() or "Failed to load orders"
        st.error(f"❌ {error_msg}")
        return
    
    if orders.empty:
        st.info("📋 No orders found matching your filters")
        return
    
    display_df = orders.copy()
    display_df['product_display'] = display_df.apply(format_product_display, axis=1)
    display_df['progress'] = display_df.apply(
        lambda r: f"{format_number(r['produced_qty'], 0)}/{format_number(r['planned_qty'], 0)} {r['uom']}", 
        axis=1
    )
    display_df['status_display'] = display_df['status'].apply(create_status_indicator)
    display_df['priority_display'] = display_df['priority'].apply(create_status_indicator)
    display_df['scheduled_display'] = display_df['scheduled_date'].apply(format_date)
    display_df['source_wh'] = display_df['warehouse_name'].apply(lambda x: x[:20] + '...' if len(str(x)) > 20 else x)
    display_df['target_wh'] = display_df['target_warehouse_name'].apply(lambda x: x[:20] + '...' if len(str(x)) > 20 else x)
    display_df['issues'] = display_df['bom_conflict_count'].apply(
        lambda x: f"⚠️ {x} BOMs" if x > 1 else "-"
    )
    
    display_columns = {
        'order_no': 'Order No',
        'product_display': 'Product',
        'progress': 'Progress',
        'status_display': 'Status',
        'priority_display': 'Priority',
        'issues': 'Issues',
        'scheduled_display': 'Scheduled',
        'source_wh': 'Source',
        'target_wh': 'Target'
    }
    
    table_df = display_df[list(display_columns.keys())].rename(columns=display_columns)
    
    selection = st.dataframe(
        table_df,
        use_container_width=True,
        hide_index=True,
        selection_mode="single-row",
        on_select="rerun",
        key="orders_table"
    )
    
    selected_rows = selection.selection.rows if selection.selection else []
    
    if selected_rows:
        selected_idx = selected_rows[0]
        selected_order = orders.iloc[selected_idx]
        
        order_id = selected_order['id']
        order_no = selected_order['order_no']
        status = selected_order['status']
        bom_conflict_count = selected_order.get('bom_conflict_count', 1)
        
        st.markdown("---")
        
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
    
    st.markdown("---")
    total_pages = max(1, (total_count + page_size - 1) // page_size)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col1:
        if st.button("⬅️ Previous", disabled=page <= 1, key="btn_prev_page"):
            st.session_state.orders_page = max(1, page - 1)
    
    with col2:
        st.markdown(f"<div style='text-align:center'>Page {page} of {total_pages} | Total: {total_count} orders</div>", unsafe_allow_html=True)
    
    with col3:
        if st.button("Next ➡️", disabled=page >= total_pages, key="btn_next_page"):
            st.session_state.orders_page = page + 1


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
        orders = queries.get_orders(
            status=filters.get('status'),
            order_type=filters.get('order_type'),
            priority=filters.get('priority'),
            product_ids=filters.get('product_ids'),
            bom_ids=filters.get('bom_ids'),
            brand_ids=filters.get('brand_ids'),
            source_warehouse_ids=filters.get('source_warehouse_ids'),
            target_warehouse_ids=filters.get('target_warehouse_ids'),
            order_nos=filters.get('order_nos'),
            from_date=filters.get('from_date'),
            to_date=filters.get('to_date'),
            date_type=filters.get('date_type', 'scheduled'),
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
            key="download_orders_excel"
        )


# ==================== Main Render Function ====================

def render_orders_tab():
    """Main function to render the Orders tab"""
    _init_session_state()
    
    check_pending_dialogs()
    
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
    
    if st.session_state.orders_view == 'create':
        if st.button("⬅️ Back to List", key="btn_back_to_list"):
            st.session_state.orders_view = 'list'
            st.rerun()
        
        render_create_form()
        return
    
    st.subheader("📋 Production Orders")
    
    current_view = _render_view_switcher()
    
    st.markdown("---")
    
    if current_view == 'pivot':
        # Pivot View - already uses fragments internally
        render_pivot_view()
    else:
        # List View
        conflict_check_active_only = st.session_state.get('orders_conflict_check_active_only', True)
        render_dashboard(conflict_check_active_only=conflict_check_active_only)
        
        filters = _render_filter_bar(queries)
        
        _render_conflict_warning(queries, filters)
        
        _render_action_bar(queries, filters)
        
        _render_order_list(queries, filters)