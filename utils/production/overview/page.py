# utils/production/overview/page.py
"""
Main UI orchestrator for Production Overview domain
Renders overview tab with dashboard, filters, summary table, and drill-down panel

Version: 1.0.0
"""

import logging
from datetime import date, timedelta
from typing import Dict, Any, Optional

import streamlit as st
import pandas as pd

from .queries import OverviewQueries
from .dashboard import render_dashboard
from .common import (
    format_number, format_percentage, format_date, format_datetime_vn,
    format_product_display, create_status_indicator, get_health_indicator,
    get_health_color, calculate_percentage, get_vietnam_today, get_vietnam_now,
    get_date_presets, get_preset_label, export_to_excel,
    OverviewConstants, HealthStatus, calculate_days_variance, get_variance_display
)

logger = logging.getLogger(__name__)


# ==================== Session State ====================

def _init_session_state():
    """Initialize session state for overview tab"""
    defaults = {
        'overview_page': 1,
        'overview_selected_id': None,
        'overview_date_preset': OverviewConstants.DATE_PRESET_THIS_MONTH,
        'overview_detail_tab': 'overview',
    }
    
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


# ==================== Filter Bar ====================

def _render_filter_bar() -> Dict[str, Any]:
    """Render filter bar and return selected filters"""
    presets = get_date_presets()
    today = get_vietnam_today()
    
    with st.expander("🔍 Filters", expanded=True):
        col1, col2, col3, col4, col5 = st.columns([1.5, 1, 1, 1, 1.5])
        
        with col1:
            # Date preset selector
            preset_options = [
                OverviewConstants.DATE_PRESET_THIS_MONTH,
                OverviewConstants.DATE_PRESET_THIS_WEEK,
                OverviewConstants.DATE_PRESET_CUSTOM,
            ]
            
            date_preset = st.selectbox(
                "📅 Period",
                options=preset_options,
                format_func=get_preset_label,
                index=preset_options.index(st.session_state.overview_date_preset),
                key="filter_date_preset"
            )
            st.session_state.overview_date_preset = date_preset
        
        with col2:
            # Determine date range based on preset
            if date_preset == OverviewConstants.DATE_PRESET_CUSTOM:
                from_date = st.date_input(
                    "From",
                    value=today.replace(day=1),
                    key="filter_from_date"
                )
            else:
                from_date = presets[date_preset][0]
                st.text_input("From", value=format_date(from_date), disabled=True)
        
        with col3:
            if date_preset == OverviewConstants.DATE_PRESET_CUSTOM:
                to_date = st.date_input(
                    "To",
                    value=today,
                    key="filter_to_date"
                )
            else:
                to_date = presets[date_preset][1]
                st.text_input("To", value=format_date(to_date), disabled=True)
        
        with col4:
            status_options = ['All', 'DRAFT', 'CONFIRMED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED']
            status = st.selectbox(
                "Status",
                options=status_options,
                key="filter_status"
            )
        
        with col5:
            health_options = ['All', 'ON_TRACK', 'AT_RISK', 'DELAYED', 'NOT_STARTED']
            health_labels = {
                'All': 'All Health',
                'ON_TRACK': '🟢 On Track',
                'AT_RISK': '🟡 At Risk',
                'DELAYED': '🔴 Delayed',
                'NOT_STARTED': '⚪ Not Started'
            }
            health = st.selectbox(
                "Health",
                options=health_options,
                format_func=lambda x: health_labels.get(x, x),
                key="filter_health"
            )
        
        # Search row
        search = st.text_input(
            "🔍 Search",
            placeholder="Order No, Product Name, PT Code, Legacy Code...",
            key="filter_search"
        )
    
    return {
        'from_date': from_date,
        'to_date': to_date,
        'status': status if status != 'All' else None,
        'health': health if health != 'All' else None,
        'search': search if search else None
    }


# ==================== Summary Table ====================

def _render_summary_table(queries: OverviewQueries, filters: Dict[str, Any]):
    """Render summary table with health indicators and progress"""
    page_size = OverviewConstants.DEFAULT_PAGE_SIZE
    page = st.session_state.overview_page
    
    # Get data
    df = queries.get_production_overview(
        from_date=filters['from_date'],
        to_date=filters['to_date'],
        status=filters['status'],
        health_filter=filters['health'],
        search=filters['search'],
        page=page,
        page_size=page_size
    )
    
    # Check for connection error
    if df is None:
        error_msg = queries.get_last_error() or "Cannot connect to database"
        st.error(f"🔌 **Database Connection Error**\n\n{error_msg}")
        st.info("💡 **Troubleshooting:**\n- Check if VPN is connected\n- Verify network connection\n- Contact IT support if issue persists")
        return
    
    # Get total count (without health filter for accurate pagination)
    total_count = queries.get_overview_count(
        from_date=filters['from_date'],
        to_date=filters['to_date'],
        status=filters['status'],
        search=filters['search']
    )
    
    # Check for empty data
    if df.empty:
        st.info("📭 No orders found matching the filters")
        return
    
    # Initialize selected index
    if 'overview_selected_idx' not in st.session_state:
        st.session_state.overview_selected_idx = None
    
    # Prepare display dataframe
    display_df = df.copy()
    
    # Set Select column
    display_df['Select'] = False
    if st.session_state.overview_selected_idx is not None and st.session_state.overview_selected_idx < len(display_df):
        display_df.loc[st.session_state.overview_selected_idx, 'Select'] = True
    
    # Format columns for display
    display_df['product_display'] = display_df.apply(format_product_display, axis=1)
    display_df['status_display'] = display_df['status'].apply(create_status_indicator)
    display_df['health_display'] = display_df['health_status'].apply(get_health_indicator)
    display_df['progress_display'] = display_df.apply(
        lambda x: f"{format_number(x['produced_qty'], 0)}/{format_number(x['planned_qty'], 0)} ({x['progress_percentage']}%)",
        axis=1
    )
    display_df['material_display'] = display_df.apply(
        lambda x: f"{x['material_percentage']}%" if x['material_percentage'] else "0%",
        axis=1
    )
    display_df['quality_display'] = display_df.apply(
        lambda x: f"{x['quality_percentage']}%" if pd.notna(x['quality_percentage']) else "-",
        axis=1
    )
    display_df['schedule_display'] = display_df.apply(
        lambda x: get_variance_display(x['schedule_variance_days']) if x['status'] == 'IN_PROGRESS' else "-",
        axis=1
    )
    
    # Render table
    edited_df = st.data_editor(
        display_df[[
            'Select', 'order_no', 'product_display', 'progress_display',
            'material_display', 'quality_display', 'schedule_display',
            'status_display', 'health_display'
        ]].rename(columns={
            'order_no': 'Order No',
            'product_display': 'Product',
            'progress_display': 'Progress',
            'material_display': 'Material',
            'quality_display': 'QC',
            'schedule_display': 'Schedule',
            'status_display': 'Status',
            'health_display': 'Health'
        }),
        use_container_width=True,
        hide_index=True,
        disabled=['Order No', 'Product', 'Progress', 'Material', 'QC', 'Schedule', 'Status', 'Health'],
        column_config={
            'Select': st.column_config.CheckboxColumn(
                '✓',
                help='Select to view details',
                default=False,
                width='small'
            ),
            'Product': st.column_config.TextColumn('Product', width='large'),
            'Progress': st.column_config.TextColumn('Progress', width='medium'),
        },
        key="overview_table_editor"
    )
    
    # Handle selection
    selected_indices = edited_df[edited_df['Select'] == True].index.tolist()
    
    if selected_indices:
        if len(selected_indices) > 1:
            new_selection = [idx for idx in selected_indices if idx != st.session_state.overview_selected_idx]
            if new_selection:
                st.session_state.overview_selected_idx = new_selection[0]
                st.rerun()
        else:
            st.session_state.overview_selected_idx = selected_indices[0]
    else:
        st.session_state.overview_selected_idx = None
    
    # Show detail panel if row selected
    if st.session_state.overview_selected_idx is not None:
        selected_order = df.iloc[st.session_state.overview_selected_idx]
        _render_detail_panel(queries, selected_order)
    else:
        st.info("💡 Tick checkbox to select an order and view details below")
    
    # Pagination
    st.markdown("---")
    total_pages = max(1, (total_count + page_size - 1) // page_size)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col1:
        if st.button("⬅️ Previous", disabled=page <= 1, key="btn_prev_overview"):
            st.session_state.overview_page = max(1, page - 1)
            st.session_state.overview_selected_idx = None
            st.rerun()
    
    with col2:
        st.markdown(
            f"<div style='text-align:center'>Page {page} of {total_pages} | Total: {total_count} orders</div>",
            unsafe_allow_html=True
        )
    
    with col3:
        if st.button("Next ➡️", disabled=page >= total_pages, key="btn_next_overview"):
            st.session_state.overview_page = page + 1
            st.session_state.overview_selected_idx = None
            st.rerun()
    
    return df


# ==================== Detail Panel ====================

def _render_detail_panel(queries: OverviewQueries, order: pd.Series):
    """Render inline detail panel for selected order"""
    st.markdown("---")
    
    # Header
    col1, col2, col3 = st.columns([2, 1, 1])
    
    with col1:
        st.markdown(f"### 📋 {order['order_no']}")
    with col2:
        st.markdown(f"**{create_status_indicator(order['status'])}**")
    with col3:
        st.markdown(f"**{get_health_indicator(order['health_status'])}**")
    
    # Product info
    st.caption(format_product_display(order))
    
    # Detail tabs
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Overview", "📦 Materials", "✅ Receipts", "📅 Timeline"])
    
    with tab1:
        _render_overview_tab(order)
    
    with tab2:
        _render_materials_tab(queries, order['id'])
    
    with tab3:
        _render_receipts_tab(queries, order['id'])
    
    with tab4:
        _render_timeline_tab(queries, order['id'])


def _render_overview_tab(order: pd.Series):
    """Render overview comparison tab"""
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### 📋 Planned")
        st.write(f"• **Quantity:** {format_number(order['planned_qty'], 0)} {order['uom']}")
        st.write(f"• **Order Date:** {format_date(order['order_date'])}")
        st.write(f"• **Scheduled End:** {format_date(order['scheduled_date'])}")
        st.write(f"• **BOM:** {order['bom_name']} ({order['bom_type']})")
    
    with col2:
        st.markdown("#### ✅ Actual")
        progress_pct = order['progress_percentage']
        st.write(f"• **Produced:** {format_number(order['produced_qty'], 0)} {order['uom']} ({progress_pct}%)")
        
        if order['status'] == 'COMPLETED' and order['completion_date']:
            st.write(f"• **Completed:** {format_date(order['completion_date'])} ✅")
        elif order['status'] == 'IN_PROGRESS':
            variance = order['schedule_variance_days']
            variance_text = get_variance_display(variance)
            variance_icon = "✅" if variance <= 0 else ("⚠️" if variance <= 2 else "🔴")
            st.write(f"• **Schedule:** {variance_text} {variance_icon}")
        else:
            st.write(f"• **Status:** {create_status_indicator(order['status'])}")
        
        # Quality summary
        if order['total_receipts'] > 0:
            quality_pct = order['quality_percentage'] or 0
            st.write(f"• **QC Pass Rate:** {quality_pct}%")
    
    st.markdown("---")
    
    # Summary metrics
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        material_pct = order['material_percentage'] or 0
        st.metric("Material Issued", f"{material_pct}%")
    
    with col2:
        st.metric("Progress", f"{order['progress_percentage']}%")
    
    with col3:
        quality_pct = order['quality_percentage']
        st.metric("QC Pass Rate", f"{quality_pct}%" if pd.notna(quality_pct) else "-")
    
    with col4:
        st.metric("Receipts", format_number(order['total_receipts'], 0))
    
    # Notes
    if order.get('notes'):
        st.markdown("---")
        st.markdown("**📝 Notes:**")
        st.text(order['notes'])


def _render_materials_tab(queries: OverviewQueries, order_id: int):
    """Render materials detail tab"""
    materials = queries.get_order_materials_detail(order_id)
    
    if materials.empty:
        st.info("No materials found for this order")
        return
    
    # Summary
    total_required = materials['required_qty'].sum()
    total_issued = materials['issued_qty'].sum()
    total_returned = materials['returned_qty'].sum()
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Required", format_number(total_required, 2))
    with col2:
        st.metric("Total Issued", format_number(total_issued, 2))
    with col3:
        st.metric("Total Returned", format_number(total_returned, 2))
    with col4:
        efficiency = calculate_percentage(total_issued - total_returned, total_required)
        st.metric("Efficiency", f"{efficiency}%")
    
    st.markdown("---")
    
    # Materials table
    display_df = materials.copy()
    display_df['material_display'] = display_df.apply(
        lambda x: f"{x['pt_code']} | {x['material_name']}" if x['pt_code'] else x['material_name'],
        axis=1
    )
    display_df['status_display'] = display_df['status'].apply(create_status_indicator)
    
    st.dataframe(
        display_df[[
            'material_display', 'required_qty', 'issued_qty', 
            'returned_qty', 'net_used', 'uom', 'issue_percentage', 'status_display'
        ]].rename(columns={
            'material_display': 'Material',
            'required_qty': 'Required',
            'issued_qty': 'Issued',
            'returned_qty': 'Returned',
            'net_used': 'Net Used',
            'uom': 'UOM',
            'issue_percentage': 'Issue %',
            'status_display': 'Status'
        }),
        use_container_width=True,
        hide_index=True
    )


def _render_receipts_tab(queries: OverviewQueries, order_id: int):
    """Render receipts detail tab"""
    receipts = queries.get_order_receipts_detail(order_id)
    
    if receipts.empty:
        st.info("No production receipts found for this order")
        return
    
    # Summary
    total_qty = receipts['quantity'].sum()
    passed_qty = receipts[receipts['quality_status'] == 'PASSED']['quantity'].sum()
    failed_qty = receipts[receipts['quality_status'] == 'FAILED']['quantity'].sum()
    pending_qty = receipts[receipts['quality_status'] == 'PENDING']['quantity'].sum()
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Produced", format_number(total_qty, 0))
    with col2:
        st.metric("✅ Passed", format_number(passed_qty, 0))
    with col3:
        st.metric("❌ Failed", format_number(failed_qty, 0))
    with col4:
        st.metric("⏳ Pending", format_number(pending_qty, 0))
    
    st.markdown("---")
    
    # Receipts table
    display_df = receipts.copy()
    display_df['date_display'] = display_df['receipt_date'].apply(
        lambda x: format_datetime_vn(x, '%d/%m %H:%M')
    )
    display_df['quality_display'] = display_df['quality_status'].apply(create_status_indicator)
    
    st.dataframe(
        display_df[[
            'receipt_no', 'date_display', 'quantity', 'uom',
            'batch_no', 'quality_display', 'defect_type', 'warehouse_name'
        ]].rename(columns={
            'receipt_no': 'Receipt No',
            'date_display': 'Date',
            'quantity': 'Quantity',
            'uom': 'UOM',
            'batch_no': 'Batch',
            'quality_display': 'Quality',
            'defect_type': 'Defect',
            'warehouse_name': 'Warehouse'
        }),
        use_container_width=True,
        hide_index=True
    )


def _render_timeline_tab(queries: OverviewQueries, order_id: int):
    """Render timeline events tab"""
    timeline = queries.get_order_timeline(order_id)
    
    if timeline.empty:
        st.info("No events found for this order")
        return
    
    # Event type icons
    event_icons = {
        'ISSUE': '📦',
        'RETURN': '↩️',
        'RECEIPT': '✅'
    }
    
    # Render as timeline
    for _, event in timeline.iterrows():
        icon = event_icons.get(event['event_type'], '📌')
        event_date = format_datetime_vn(event['event_date'], '%d/%m/%Y %H:%M')
        
        col1, col2, col3 = st.columns([1, 3, 1])
        
        with col1:
            st.markdown(f"**{event_date}**")
        with col2:
            st.markdown(f"{icon} **{event['document_no']}** - {event['description']}")
        with col3:
            st.markdown(f"`{event['status']}`")
    
    st.markdown("---")
    st.caption(f"Total events: {len(timeline)}")


# ==================== Action Bar ====================

def _render_action_bar(queries: OverviewQueries, filters: Dict[str, Any], data: Optional[pd.DataFrame]):
    """Render action bar with export and refresh"""
    col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
    
    with col1:
        if st.button("📥 Export Excel", use_container_width=True, key="btn_export_overview"):
            _export_overview_excel(queries, filters)
    
    with col2:
        if st.button("🔄 Refresh", use_container_width=True, key="btn_refresh_overview"):
            st.session_state.overview_selected_idx = None
            st.rerun()
    
    with col3:
        # Show last updated timestamp
        timestamp = get_vietnam_now().strftime('%H:%M:%S')
        st.markdown(f"<div style='text-align:center; color:gray; padding-top:8px'>🕐 {timestamp}</div>", 
                   unsafe_allow_html=True)


def _export_overview_excel(queries: OverviewQueries, filters: Dict[str, Any]):
    """Export overview to Excel"""
    with st.spinner("Exporting..."):
        df = queries.get_production_overview(
            from_date=filters['from_date'],
            to_date=filters['to_date'],
            status=filters['status'],
            search=filters['search'],
            page=1,
            page_size=10000  # Get all
        )
        
        if df is None or df.empty:
            st.warning("No data to export")
            return
        
        # Prepare export dataframe
        export_df = df[[
            'order_no', 'order_date', 'scheduled_date', 'status', 'priority',
            'pt_code', 'product_name', 'package_size', 'brand_name',
            'planned_qty', 'produced_qty', 'uom', 'progress_percentage',
            'material_percentage', 'quality_percentage',
            'total_receipts', 'health_status',
            'source_warehouse', 'target_warehouse'
        ]].copy()
        
        export_df.columns = [
            'Order No', 'Order Date', 'Scheduled Date', 'Status', 'Priority',
            'PT Code', 'Product Name', 'Package Size', 'Brand',
            'Planned Qty', 'Produced Qty', 'UOM', 'Progress %',
            'Material %', 'QC %',
            'Receipts', 'Health',
            'Source WH', 'Target WH'
        ]
        
        excel_data = export_to_excel(export_df)
        
        filename = f"Production_Overview_{get_vietnam_today().strftime('%Y%m%d')}.xlsx"
        
        st.download_button(
            label="💾 Download Excel",
            data=excel_data,
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_overview_excel"
        )


# ==================== Main Render Function ====================

def render_overview_tab():
    """
    Main function to render the Overview tab
    Called from the main Production page
    """
    _init_session_state()
    
    queries = OverviewQueries()
    
    # Header
    st.subheader("📊 Production Overview")
    
    # Filters (get date range for dashboard)
    filters = _render_filter_bar()
    
    # Dashboard with date range
    render_dashboard(from_date=filters['from_date'], to_date=filters['to_date'])
    
    st.markdown("---")
    
    # Action bar
    _render_action_bar(queries, filters, None)
    
    # Summary table with detail panel
    _render_summary_table(queries, filters)
