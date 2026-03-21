# utils/production/orders/page.py
"""
Main UI orchestrator for Orders domain
Renders the Orders tab with dashboard, filters, list, and actions

Version: 2.0.0
Changes:
- v2.0.0: Client-side filtering — MAJOR performance overhaul
  - Single bulk DB query replaces ~13 per-render queries
  - All filtering, pagination, stats, filter options computed client-side
  - PerformanceTimer instrumentation throughout
- v1.6.0: Added Pivot View for data analysis
- v1.5.0: Advanced multiselect filters
- v1.3.0: Performance optimization with fragment isolation
"""

import logging
from datetime import timedelta
from typing import Dict, Any, Optional, List

import streamlit as st
import pandas as pd

from .queries import OrderQueries
from .manager import OrderManager
from .dashboard import render_dashboard_from_data
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
    format_product_display, format_date, get_date_filter_presets, get_default_date_range,
    PerformanceTimer
)

logger = logging.getLogger(__name__)


# ==================== Bootstrap Cache ====================

@st.cache_data(ttl=30, show_spinner=False)
def _cached_bootstrap() -> Dict[str, Any]:
    """
    Load ALL orders data in one cached call (TTL 30s).
    2 sequential DB queries, derive everything else client-side.
    """
    return OrderQueries().bootstrap_all()


# ==================== Client-Side Derived Data ====================

def _derive_filter_options(orders: pd.DataFrame) -> Dict[str, List[str]]:
    """Derive filter options from DataFrame — replaces get_filter_options() (3 queries)"""
    if orders is None or orders.empty:
        return {
            'statuses': ['DRAFT', 'CONFIRMED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED'],
            'order_types': [],
            'priorities': ['LOW', 'NORMAL', 'HIGH', 'URGENT']
        }
    
    status_order = ['DRAFT', 'CONFIRMED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED']
    statuses = [s for s in status_order if s in orders['status'].unique()]
    
    priority_order = ['LOW', 'NORMAL', 'HIGH', 'URGENT']
    priorities = [p for p in priority_order if p in orders['priority'].unique()]
    
    order_types = sorted(orders['bom_type'].dropna().unique().tolist())
    
    return {
        'statuses': statuses,
        'order_types': order_types,
        'priorities': priorities,
    }


def _derive_search_options(orders: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """Derive search filter options from DataFrame — replaces get_search_filter_options() (6 queries)"""
    empty = {
        'products': pd.DataFrame(),
        'boms': pd.DataFrame(),
        'brands': pd.DataFrame(),
        'source_warehouses': pd.DataFrame(),
        'target_warehouses': pd.DataFrame(),
        'order_nos': pd.DataFrame(),
    }
    
    if orders is None or orders.empty:
        return empty
    
    # Products
    products = orders[['product_id', 'pt_code', 'product_name', 'package_size', 'legacy_pt_code', 'brand_name']].drop_duplicates(
        subset=['product_id']
    ).rename(columns={'product_id': 'id'}).sort_values('product_name').reset_index(drop=True)
    
    # BOMs
    boms = orders[['bom_header_id', 'bom_code', 'bom_name', 'bom_type']].drop_duplicates(
        subset=['bom_header_id']
    ).rename(columns={'bom_header_id': 'id'}).sort_values('bom_name').reset_index(drop=True)
    
    # Brands
    brands = orders[['brand_id', 'brand_name']].drop_duplicates(
        subset=['brand_id']
    ).rename(columns={'brand_id': 'id'}).sort_values('brand_name').reset_index(drop=True)
    
    # Order numbers
    order_nos = orders[['order_no']].drop_duplicates().sort_values('order_no', ascending=False).head(500).reset_index(drop=True)
    
    # Warehouses (merged source + target for unified dropdown)
    all_wh = pd.concat([
        orders[['warehouse_id', 'warehouse_name']].rename(columns={'warehouse_id': 'id', 'warehouse_name': 'name'}),
        orders[['target_warehouse_id', 'target_warehouse_name']].rename(columns={'target_warehouse_id': 'id', 'target_warehouse_name': 'name'}),
    ]).drop_duplicates(subset=['id']).sort_values('name').reset_index(drop=True)
    
    return {
        'products': products,
        'boms': boms,
        'brands': brands,
        'source_warehouses': all_wh,
        'target_warehouses': all_wh,
        'order_nos': order_nos,
        'warehouses': all_wh,
    }


def _derive_metrics(orders: pd.DataFrame, from_date=None, to_date=None) -> Dict[str, Any]:
    """Derive order metrics from DataFrame — replaces get_order_metrics() query"""
    if orders is None or orders.empty:
        return {
            'total_orders': 0, 'draft_count': 0, 'confirmed_count': 0,
            'in_progress_count': 0, 'completed_count': 0, 'cancelled_count': 0,
            'urgent_count': 0, 'high_priority_count': 0, 'active_count': 0, 'completion_rate': 0
        }
    
    df = orders
    if from_date:
        dt_col = pd.to_datetime(df['order_date'], errors='coerce')
        df = df[dt_col >= pd.Timestamp(from_date)]
    if to_date:
        dt_col = pd.to_datetime(df['order_date'], errors='coerce')
        df = df[dt_col <= pd.Timestamp(to_date) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)]
    
    total = len(df)
    completed = int((df['status'] == 'COMPLETED').sum())
    in_progress = int((df['status'] == 'IN_PROGRESS').sum())
    confirmed = int((df['status'] == 'CONFIRMED').sum())
    
    return {
        'total_orders': total,
        'draft_count': int((df['status'] == 'DRAFT').sum()),
        'confirmed_count': confirmed,
        'in_progress_count': in_progress,
        'completed_count': completed,
        'cancelled_count': int((df['status'] == 'CANCELLED').sum()),
        'urgent_count': int((df['priority'] == 'URGENT').sum()),
        'high_priority_count': int((df['priority'] == 'HIGH').sum()),
        'active_count': in_progress + confirmed,
        'completion_rate': round((completed / total * 100), 1) if total > 0 else 0,
    }


def _derive_conflict_summary(orders: pd.DataFrame, active_only: bool = True,
                              from_date=None, to_date=None) -> Dict[str, Any]:
    """Derive BOM conflict summary from DataFrame — replaces get_bom_conflict_summary() query"""
    empty = {
        'total_conflict_orders': 0, 'affected_products': 0,
        'conflict_by_status': {'DRAFT': 0, 'CONFIRMED': 0, 'IN_PROGRESS': 0, 'COMPLETED': 0}
    }
    
    if orders is None or orders.empty:
        return empty
    
    df = orders
    if from_date:
        dt_col = pd.to_datetime(df['order_date'], errors='coerce')
        df = df[dt_col >= pd.Timestamp(from_date)]
    if to_date:
        dt_col = pd.to_datetime(df['order_date'], errors='coerce')
        df = df[dt_col <= pd.Timestamp(to_date) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)]
    
    conflicts = df[df['bom_conflict_count'] > 1]
    
    if conflicts.empty:
        return empty
    
    return {
        'total_conflict_orders': len(conflicts),
        'affected_products': conflicts['product_id'].nunique(),
        'conflict_by_status': {
            'DRAFT': int((conflicts['status'] == 'DRAFT').sum()),
            'CONFIRMED': int((conflicts['status'] == 'CONFIRMED').sum()),
            'IN_PROGRESS': int((conflicts['status'] == 'IN_PROGRESS').sum()),
            'COMPLETED': int((conflicts['status'] == 'COMPLETED').sum()),
        }
    }


def _apply_filters(df: pd.DataFrame, filters: Dict[str, Any]) -> pd.DataFrame:
    """Apply all filters client-side using pandas — replaces server-side WHERE clauses"""
    if df is None or df.empty:
        return pd.DataFrame()
    
    result = df.copy()
    
    # Status
    status = filters.get('status')
    if status:
        result = result[result['status'].isin(status)]
    
    # Order type
    order_type = filters.get('order_type')
    if order_type:
        result = result[result['bom_type'].isin(order_type)]
    
    # Priority
    priority = filters.get('priority')
    if priority:
        result = result[result['priority'].isin(priority)]
    
    # Product IDs
    product_ids = filters.get('product_ids')
    if product_ids:
        result = result[result['product_id'].isin(product_ids)]
    
    # BOM IDs
    bom_ids = filters.get('bom_ids')
    if bom_ids:
        result = result[result['bom_header_id'].isin(bom_ids)]
    
    # Brand IDs
    brand_ids = filters.get('brand_ids')
    if brand_ids:
        result = result[result['brand_id'].isin(brand_ids)]
    
    # Source warehouse IDs
    source_warehouse_ids = filters.get('source_warehouse_ids')
    if source_warehouse_ids:
        result = result[result['warehouse_id'].isin(source_warehouse_ids)]
    
    # Target warehouse IDs
    target_warehouse_ids = filters.get('target_warehouse_ids')
    if target_warehouse_ids:
        result = result[result['target_warehouse_id'].isin(target_warehouse_ids)]
    
    # Order numbers
    order_nos = filters.get('order_nos')
    if order_nos:
        result = result[result['order_no'].isin(order_nos)]
    
    # Date filter
    date_type = filters.get('date_type', 'scheduled')
    from_date = filters.get('from_date')
    to_date = filters.get('to_date')
    
    date_col = 'scheduled_date' if date_type == 'scheduled' else 'order_date'
    if from_date and to_date and date_col in result.columns:
        dt = pd.to_datetime(result[date_col], errors='coerce')
        from_ts = pd.Timestamp(from_date)
        to_ts = pd.Timestamp(to_date) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        result = result[dt.between(from_ts, to_ts)]
    
    # Conflicts only
    if filters.get('conflicts_only'):
        result = result[result['bom_conflict_count'] > 1]
    
    return result


# ==================== Session State ====================

def _init_session_state():
    """Initialize session state for orders tab"""
    defaults = {
        'orders_page': 1,
        'orders_view': 'list',  # 'list', 'create', or 'pivot'
        'orders_conflicts_only': False,
        'orders_conflict_check_active_only': True,
        'orders_date_type': 'scheduled',
    }
    
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


# ==================== View Switcher ====================

def _render_view_switcher() -> str:
    """Render view switcher tabs for List/Pivot views with Create Order button"""
    current_view = st.session_state.get('orders_view', 'list')
    
    if current_view == 'create':
        return current_view
    
    col1, col2, col3, col4 = st.columns([1, 1, 1, 3])
    
    with col1:
        list_selected = current_view == 'list'
        if st.button(
            "📋 List View",
            type="primary" if list_selected else "secondary",
            width='stretch',
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
            width='stretch',
            key="btn_view_pivot"
        ):
            if not pivot_selected:
                st.session_state.orders_view = 'pivot'
                st.rerun()
    
    with col3:
        if st.button("➕ Create Order", width='stretch',
                     key="btn_create_order_top"):
            st.session_state.orders_view = 'create'
            st.rerun()
    
    return current_view


# ==================== Filter Bar ====================


def _render_filter_bar(all_orders: Optional[pd.DataFrame]) -> Dict[str, Any]:
    """Render filter bar — all options derived from DataFrame (zero DB queries)"""
    filter_options = _derive_filter_options(all_orders)
    search_options = _derive_search_options(all_orders)
    
    date_type = st.session_state.get('orders_date_type', 'scheduled')
    default_from, default_to = get_default_date_range(date_type)
    desired_defaults = ['DRAFT', 'CONFIRMED', 'IN_PROGRESS']
    available_statuses = filter_options['statuses']
    default_statuses = [s for s in desired_defaults if s in available_statuses]
    
    with st.expander("🔍 Filters", expanded=True):
        st.markdown("##### 📋 Status & Type")
        col1, col2, col3 = st.columns([2, 1.5, 1.5])
        
        with col1:
            status_list = st.multiselect(
                "Status",
                options=available_statuses,
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

def _render_conflict_warning(all_orders: Optional[pd.DataFrame], filters: Dict[str, Any]):
    """Render BOM conflict warning banner — derived from DataFrame (zero DB)"""
    conflict_summary = _derive_conflict_summary(
        all_orders,
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
def _render_order_list(all_orders: Optional[pd.DataFrame], filters: Dict[str, Any]):
    """Render order list — client-side filtering, zero DB queries"""
    page = st.session_state.get('orders_page', 1)
    page_size = OrderConstants.DEFAULT_PAGE_SIZE
    
    # Client-side filter
    filtered = _apply_filters(all_orders, filters)
    total_count = len(filtered)
    
    if all_orders is None:
        st.error("❌ Failed to load orders")
        return
    
    if filtered.empty:
        st.info("📋 No orders found matching your filters")
        return
    
    # Paginate
    offset = (page - 1) * page_size
    orders = filtered.iloc[offset:offset + page_size].reset_index(drop=True)
    
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
        width='stretch',
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
            if st.button("👁️ View", type="primary", width='stretch', key="btn_view_order"):
                show_detail_dialog(order_id)
        
        with col2:
            if st.button("✏️ Edit", width='stretch', key="btn_edit_order",
                        disabled=not OrderValidator.can_edit(status)):
                show_edit_dialog(order_id)
        
        with col3:
            if st.button("✅ Confirm", width='stretch', key="btn_confirm_order",
                        disabled=not OrderValidator.can_confirm(status)):
                show_confirm_dialog(order_id, order_no)
        
        with col4:
            if st.button("❌ Cancel", width='stretch', key="btn_cancel_order",
                        disabled=not OrderValidator.can_cancel(status)):
                show_cancel_dialog(order_id, order_no)
        
        with col5:
            if st.button("📄 PDF", width='stretch', key="btn_pdf_order"):
                show_pdf_dialog(order_id, order_no)
        
        with col6:
            if st.button("🗑️ Delete", width='stretch', key="btn_delete_order",
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

def _render_action_bar(filters: Dict[str, Any]):
    """Render action bar with export and refresh"""
    col1, col2, col3 = st.columns([1, 1, 2])
    
    with col1:
        if st.button("📊 Export Excel", width='stretch', key="btn_export_excel"):
            _export_orders_excel(filters)
    
    with col2:
        if st.button("🔄 Refresh", width='stretch', key="btn_refresh_orders"):
            _cached_bootstrap.clear()
            st.rerun()


def _export_orders_excel(filters: Dict[str, Any]):
    """Export orders to Excel — uses cached data, zero extra DB hit"""
    with st.spinner("Exporting..."):
        boot = _cached_bootstrap()
        all_orders = boot.get('orders')
        
        if all_orders is None or all_orders.empty:
            st.warning("No orders to export")
            return
        
        orders = _apply_filters(all_orders, filters)
        
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
    """
    Main function to render the Orders tab.
    
    v2.0: Bootstrap cache — 2 sequential DB queries, derive everything else.
    """
    _init_session_state()
    
    perf = PerformanceTimer("render_orders_tab")
    
    with perf.step("check_pending_dialogs"):
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
        render_pivot_view()
    else:
        # Bootstrap: load all data (2 DB queries on cache miss, 0 on hit)
        with perf.step("bootstrap"):
            boot = _cached_bootstrap()
        
        all_orders = boot.get('orders')
        
        with perf.step("render_dashboard"):
            conflict_check_active_only = st.session_state.get('orders_conflict_check_active_only', True)
            metrics = _derive_metrics(all_orders)
            conflict_summary = _derive_conflict_summary(all_orders, active_only=conflict_check_active_only)
            render_dashboard_from_data(metrics, conflict_summary)
        
        with perf.step("render_filters"):
            filters = _render_filter_bar(all_orders)
        
        with perf.step("render_conflict_warning"):
            _render_conflict_warning(all_orders, filters)
        
        with perf.step("render_action_bar"):
            _render_action_bar(filters)
        
        with perf.step("render_order_list"):
            _render_order_list(all_orders, filters)
    
    perf.summary()