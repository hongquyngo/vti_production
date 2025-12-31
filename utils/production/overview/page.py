# utils/production/overview/page.py
"""
Main UI orchestrator for Production Lifecycle Overview domain
Renders overview tab with lifecycle table, stage-by-stage drill-down, and analytics

Version: 2.0.0
Changes:
- v2.0.0: Redesigned with lifecycle stages, stage-by-stage drill-down, Plotly analytics
- v1.0.0: Initial version
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
    OverviewConstants, HealthStatus, calculate_days_variance, get_variance_display,
    # Lifecycle formatters
    format_schedule_display, format_material_stage_display,
    format_production_stage_display, format_qc_stage_display,
    # Chart helpers
    create_yield_by_product_chart, create_schedule_performance_chart,
    create_material_efficiency_chart, create_health_summary_chart,
    PLOTLY_AVAILABLE
)

logger = logging.getLogger(__name__)


# ==================== Session State ====================

def _init_session_state():
    """Initialize session state for overview tab"""
    defaults = {
        'overview_page': 1,
        'overview_selected_id': None,
        'overview_selected_idx': None,
        'overview_date_preset': OverviewConstants.DATE_PRESET_THIS_MONTH,
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


# ==================== Lifecycle Table ====================

def _render_lifecycle_table(queries: OverviewQueries, filters: Dict[str, Any]) -> Optional[pd.DataFrame]:
    """Render lifecycle table with stages side-by-side"""
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
        return None
    
    # Get total count
    total_count = queries.get_overview_count(
        from_date=filters['from_date'],
        to_date=filters['to_date'],
        status=filters['status'],
        search=filters['search']
    )
    
    # Check for empty data
    if df.empty:
        st.info("📭 No orders found matching the filters")
        return None
    
    # Initialize selected index
    if 'overview_selected_idx' not in st.session_state:
        st.session_state.overview_selected_idx = None
    
    # Prepare display dataframe
    display_df = df.copy()
    
    # Set Select column
    display_df['Select'] = False
    if st.session_state.overview_selected_idx is not None and st.session_state.overview_selected_idx < len(display_df):
        display_df.loc[st.session_state.overview_selected_idx, 'Select'] = True
    
    # Format columns for lifecycle stages - use standard format
    display_df['product_display'] = display_df.apply(format_product_display, axis=1)
    display_df['type_display'] = display_df['bom_type'].apply(
        lambda x: {'CUTTING': '✂️', 'REPACKING': '📦', 'KITTING': '🔧'}.get(x, '📋') + f' {x}'
    )
    
    # Planning stage
    display_df['plan_qty_display'] = display_df.apply(
        lambda r: f"{format_number(r['planned_qty'], 0)} {r['uom']}",
        axis=1
    )
    display_df['schedule_display'] = display_df.apply(format_schedule_display, axis=1)
    
    # Material stage - show progress bar
    display_df['material_pct'] = display_df['material_percentage'].fillna(0)
    display_df['material_detail'] = display_df.apply(
        lambda r: f"{format_number(r['total_material_issued'], 0)}/{format_number(r['total_material_required'], 0)}"
                  + (f" ↩️{format_number(r['total_returned'], 0)}" if r['total_returned'] > 0 else ""),
        axis=1
    )
    
    # Production stage - show progress bar
    display_df['prod_pct'] = display_df['progress_percentage'].fillna(0)
    display_df['prod_detail'] = display_df.apply(
        lambda r: f"{format_number(r['produced_qty'], 0)}/{format_number(r['planned_qty'], 0)} ({r['total_receipts']}📦)",
        axis=1
    )
    
    # QC stage
    display_df['qc_display'] = display_df.apply(
        lambda r: (f"✅ {r['quality_percentage']:.0f}%" if r['quality_percentage'] and r['quality_percentage'] >= 95
                   else (f"⚠️ {r['quality_percentage']:.0f}%" if r['quality_percentage'] and r['quality_percentage'] >= 80
                         else (f"❌ {r['quality_percentage']:.0f}%" if r['quality_percentage'] 
                               else "-"))) if r['total_receipts'] > 0 else "-",
        axis=1
    )
    
    # Health & Status
    display_df['health_display'] = display_df['health_status'].apply(get_health_indicator)
    display_df['status_display'] = display_df['status'].apply(create_status_indicator)
    
    # Render table using data_editor
    edited_df = st.data_editor(
        display_df[[
            'Select', 'order_no', 'product_display',
            'plan_qty_display', 'schedule_display',
            'material_pct', 'material_detail',
            'prod_pct', 'prod_detail',
            'qc_display', 'health_display'
        ]].rename(columns={
            'order_no': 'Order',
            'product_display': 'Product',
            'plan_qty_display': 'Plan Qty',
            'schedule_display': 'Schedule',
            'material_pct': 'Mat %',
            'material_detail': 'Mat Detail',
            'prod_pct': 'Prod %',
            'prod_detail': 'Prod Detail',
            'qc_display': 'QC',
            'health_display': 'Health'
        }),
        use_container_width=True,
        hide_index=True,
        disabled=['Order', 'Product', 'Plan Qty', 'Schedule', 'Mat %', 'Mat Detail', 
                  'Prod %', 'Prod Detail', 'QC', 'Health'],
        column_config={
            'Select': st.column_config.CheckboxColumn('✓', help='Select to view details', width='small'),
            'Order': st.column_config.TextColumn('Order', width='small'),
            'Product': st.column_config.TextColumn('Product', width='medium'),
            'Plan Qty': st.column_config.TextColumn('Plan', width='small'),
            'Schedule': st.column_config.TextColumn('Schedule', width='small'),
            'Mat %': st.column_config.ProgressColumn('Material', format='%.0f%%', min_value=0, max_value=100, width='small'),
            'Mat Detail': st.column_config.TextColumn('Detail', width='small'),
            'Prod %': st.column_config.ProgressColumn('Production', format='%.0f%%', min_value=0, max_value=100, width='small'),
            'Prod Detail': st.column_config.TextColumn('Detail', width='small'),
            'QC': st.column_config.TextColumn('QC', width='small'),
            'Health': st.column_config.TextColumn('Health', width='small'),
        },
        key="lifecycle_table_editor"
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
    
    # Show drill-down if row selected
    if st.session_state.overview_selected_idx is not None:
        selected_order = df.iloc[st.session_state.overview_selected_idx]
        _render_stage_drilldown(queries, selected_order)
    else:
        st.info("💡 Tick checkbox to select an order and view lifecycle details below")
    
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


# ==================== Stage-by-Stage Drill-down ====================

def _render_stage_drilldown(queries: OverviewQueries, order: pd.Series):
    """Render stage-by-stage drill-down panel (Option A)"""
    st.markdown("---")
    
    # Header
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        st.markdown(f"### 📋 {order['order_no']} - Lifecycle Detail")
    with col2:
        st.markdown(f"**{create_status_indicator(order['status'])}**")
    with col3:
        st.markdown(f"**{get_health_indicator(order['health_status'])}**")
    
    # Product info line - use standard format
    st.caption(format_product_display(order))
    
    st.markdown("---")
    
    # Stage cards in columns
    col1, col2, col3, col4 = st.columns(4)
    
    # Stage 1: Planning
    with col1:
        st.markdown("#### 📅 PLANNING")
        _render_planning_stage(order)
    
    # Stage 2: Material
    with col2:
        st.markdown("#### 📦 MATERIAL")
        _render_material_stage(queries, order)
    
    # Stage 3: Production
    with col3:
        st.markdown("#### 🏭 PRODUCTION")
        _render_production_stage(queries, order)
    
    # Stage 4: QC
    with col4:
        st.markdown("#### ✅ QUALITY")
        _render_qc_stage(queries, order)
    
    # Expandable details
    st.markdown("---")
    
    with st.expander("📦 Material Details", expanded=False):
        materials = queries.get_order_materials_detail(order['id'])
        if not materials.empty:
            # Format product display: PT_CODE (LEGACY or NEW) | NAME | PKG_SIZE (BRAND)
            materials['product_display'] = materials.apply(
                lambda r: format_product_display({
                    'pt_code': r['pt_code'],
                    'legacy_pt_code': r['legacy_pt_code'],
                    'product_name': r['material_name'],
                    'package_size': r['package_size'],
                    'brand_name': r['brand_name']
                }), axis=1
            )
            
            st.dataframe(
                materials[[
                    'product_display', 'required_qty', 'issued_qty', 
                    'returned_qty', 'net_used', 'uom', 'status'
                ]].rename(columns={
                    'product_display': 'Material',
                    'required_qty': 'Required',
                    'issued_qty': 'Issued',
                    'returned_qty': 'Returned',
                    'net_used': 'Net Used',
                    'uom': 'UOM',
                    'status': 'Status'
                }),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("No materials found")
    
    with st.expander("📋 Receipt Details", expanded=False):
        receipts = queries.get_order_receipts_detail(order['id'])
        if not receipts.empty:
            receipts['date_display'] = receipts['receipt_date'].apply(
                lambda x: format_datetime_vn(x, '%d/%m %H:%M')
            )
            st.dataframe(
                receipts[[
                    'receipt_no', 'date_display', 'quantity', 'uom',
                    'batch_no', 'quality_status', 'defect_type'
                ]].rename(columns={
                    'receipt_no': 'Receipt',
                    'date_display': 'Date',
                    'quantity': 'Qty',
                    'uom': 'UOM',
                    'batch_no': 'Batch',
                    'quality_status': 'QC Status',
                    'defect_type': 'Defect'
                }),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("No receipts found")
    
    with st.expander("📅 Event Timeline", expanded=False):
        timeline = queries.get_order_timeline(order['id'])
        if not timeline.empty:
            for _, event in timeline.iterrows():
                icon = {'ISSUE': '📦', 'RETURN': '↩️', 'RECEIPT': '✅'}.get(event['event_type'], '📌')
                event_date = format_datetime_vn(event['event_date'], '%d/%m %H:%M')
                st.markdown(f"**{event_date}** | {icon} {event['document_no']} - {event['description']}")
        else:
            st.info("No events found")


def _render_planning_stage(order: pd.Series):
    """Render planning stage card"""
    with st.container():
        st.metric("Planned Qty", f"{format_number(order['planned_qty'], 0)} {order['uom']}")
        st.write(f"**Order Date:** {format_date(order['order_date'])}")
        st.write(f"**Scheduled:** {format_date(order['scheduled_date'])}")
        
        if order['status'] == 'COMPLETED' and order.get('completion_date'):
            st.write(f"**Completed:** {format_date(order['completion_date'])}")
            st.success("✅ Done")
        elif order['status'] == 'IN_PROGRESS':
            variance = order.get('schedule_variance_days', 0) or 0
            if variance <= 0:
                st.success(f"✅ {get_variance_display(variance)}")
            elif variance <= 2:
                st.warning(f"⚠️ {get_variance_display(variance)}")
            else:
                st.error(f"🔴 {get_variance_display(variance)}")
        elif order['status'] == 'CANCELLED':
            st.error("❌ Cancelled")
        else:
            st.info(f"🕐 {order['status']}")
        
        st.write(f"**BOM:** {order['bom_type']}")


def _render_material_stage(queries: OverviewQueries, order: pd.Series):
    """Render material stage card"""
    with st.container():
        issued = order.get('total_material_issued', 0) or 0
        required = order.get('total_material_required', 0) or 0
        returned = order.get('total_returned', 0) or 0
        net_used = issued - returned
        
        pct = order.get('material_percentage', 0) or 0
        st.metric("Material Issued", f"{pct:.0f}%")
        
        st.write(f"**Required:** {format_number(required, 0)}")
        st.write(f"**Issued:** {format_number(issued, 0)}")
        st.write(f"**Returned:** {format_number(returned, 0)}")
        st.write(f"**Net Used:** {format_number(net_used, 0)}")
        
        if required > 0:
            efficiency = (net_used / required) * 100
            if efficiency <= 100:
                st.success(f"✅ Efficiency: {efficiency:.1f}%")
            else:
                st.warning(f"⚠️ Over-used: {efficiency:.1f}%")
        
        st.caption(f"{order.get('material_count', 0)} materials")


def _render_production_stage(queries: OverviewQueries, order: pd.Series):
    """Render production stage card"""
    with st.container():
        produced = order.get('produced_qty', 0) or 0
        planned = order.get('planned_qty', 0) or 0
        
        pct = order.get('progress_percentage', 0) or 0
        st.metric("Progress", f"{pct:.0f}%")
        
        st.write(f"**Produced:** {format_number(produced, 0)} {order['uom']}")
        st.write(f"**Planned:** {format_number(planned, 0)} {order['uom']}")
        st.write(f"**Remaining:** {format_number(planned - produced, 0)} {order['uom']}")
        
        total_receipts = order.get('total_receipts', 0) or 0
        st.write(f"**Receipts:** {total_receipts}")
        
        if planned > 0 and produced > 0:
            yield_rate = (produced / planned) * 100
            if yield_rate >= 95:
                st.success(f"✅ Yield: {yield_rate:.1f}%")
            elif yield_rate >= 80:
                st.warning(f"⚠️ Yield: {yield_rate:.1f}%")
            else:
                st.error(f"❌ Yield: {yield_rate:.1f}%")


def _render_qc_stage(queries: OverviewQueries, order: pd.Series):
    """Render QC stage card"""
    with st.container():
        passed = order.get('passed_qty', 0) or 0
        failed = order.get('failed_qty', 0) or 0
        pending = order.get('pending_qty', 0) or 0
        total = passed + failed + pending
        
        quality_pct = order.get('quality_percentage')
        
        if total > 0:
            st.metric("Pass Rate", f"{quality_pct:.0f}%" if quality_pct else "N/A")
            st.write(f"**✅ Passed:** {format_number(passed, 0)}")
            st.write(f"**❌ Failed:** {format_number(failed, 0)}")
            st.write(f"**⏳ Pending:** {format_number(pending, 0)}")
            
            if quality_pct is not None:
                if quality_pct >= 95:
                    st.success("✅ Excellent")
                elif quality_pct >= 80:
                    st.warning("⚠️ Acceptable")
                else:
                    st.error("❌ Below target")
        else:
            st.metric("Pass Rate", "-")
            st.info("No QC data yet")


# ==================== Analytics Section ====================

def _render_analytics_section(df: pd.DataFrame):
    """Render analytics section with Plotly charts - shown after dashboard"""
    if not PLOTLY_AVAILABLE:
        st.warning("📊 Charts require Plotly. Install with: `pip install plotly`")
        return
    
    if df is None or df.empty:
        return
    
    with st.expander("📈 Analytics", expanded=True):
        # Health summary bar at top
        health_chart = create_health_summary_chart(df)
        if health_chart:
            st.plotly_chart(health_chart, use_container_width=True)
        
        # Three charts in columns
        col1, col2, col3 = st.columns(3)
        
        with col1:
            yield_chart = create_yield_by_product_chart(df)
            if yield_chart:
                st.plotly_chart(yield_chart, use_container_width=True)
            else:
                st.info("No yield data")
        
        with col2:
            schedule_chart = create_schedule_performance_chart(df)
            if schedule_chart:
                st.plotly_chart(schedule_chart, use_container_width=True)
            else:
                st.info("No schedule data")
        
        with col3:
            efficiency_chart = create_material_efficiency_chart(df)
            if efficiency_chart:
                st.plotly_chart(efficiency_chart, use_container_width=True)
            else:
                st.info("No efficiency data")


# ==================== Action Bar ====================

def _render_action_bar(queries: OverviewQueries, filters: Dict[str, Any], data: Optional[pd.DataFrame]):
    """Render action bar with export and refresh"""
    col1, col2, col3 = st.columns([1, 1, 2])
    
    with col1:
        if st.button("📥 Export Excel", use_container_width=True, key="btn_export_overview"):
            _export_overview_excel(queries, filters)
    
    with col2:
        if st.button("🔄 Refresh", use_container_width=True, key="btn_refresh_overview"):
            st.session_state.overview_selected_idx = None
            st.rerun()
    
    with col3:
        timestamp = get_vietnam_now().strftime('%H:%M:%S')
        st.markdown(f"<div style='text-align:right; color:gray; padding-top:8px'>🕐 Last updated: {timestamp}</div>", 
                   unsafe_allow_html=True)


def _export_overview_excel(queries: OverviewQueries, filters: Dict[str, Any]):
    """Export overview to Excel with lifecycle data, material details, and metadata"""
    with st.spinner("Exporting..."):
        # Get lifecycle data
        df = queries.get_production_overview(
            from_date=filters['from_date'],
            to_date=filters['to_date'],
            status=filters['status'],
            search=filters['search'],
            page=1,
            page_size=10000
        )
        
        if df is None or df.empty:
            st.warning("No data to export")
            return
        
        # Get material details
        materials_df = queries.get_materials_for_export(
            from_date=filters['from_date'],
            to_date=filters['to_date'],
            status=filters['status'],
            search=filters['search']
        )
        
        # Prepare main data dataframe with lifecycle stages
        export_df = df[[
            'order_no', 'order_date', 'scheduled_date', 'completion_date',
            'status', 'priority', 'health_status',
            'pt_code', 'legacy_pt_code', 'product_name', 'package_size', 'brand_name', 'bom_type',
            'planned_qty', 'uom',
            'total_material_required', 'total_material_issued', 'total_returned', 'material_percentage',
            'produced_qty', 'progress_percentage', 'total_receipts',
            'passed_qty', 'failed_qty', 'pending_qty', 'quality_percentage',
            'source_warehouse', 'target_warehouse'
        ]].copy()
        
        export_df['net_material_used'] = export_df['total_material_issued'] - export_df['total_returned']
        export_df['remaining_qty'] = export_df['planned_qty'] - export_df['produced_qty']
        
        export_df.columns = [
            'Order No', 'Order Date', 'Scheduled Date', 'Completion Date',
            'Status', 'Priority', 'Health',
            'PT Code', 'Legacy Code', 'Product Name', 'Package Size', 'Brand', 'BOM Type',
            'Planned Qty', 'UOM',
            'Mat Required', 'Mat Issued', 'Mat Returned', 'Mat %',
            'Produced Qty', 'Progress %', 'Receipts',
            'QC Passed', 'QC Failed', 'QC Pending', 'QC Pass %',
            'Source WH', 'Target WH',
            'Net Material Used', 'Remaining Qty'
        ]
        
        # Prepare material details dataframe - separate columns for easy Excel filtering
        if not materials_df.empty:
            # Handle legacy code display (show "NEW" if empty)
            materials_df['legacy_display'] = materials_df['legacy_pt_code'].apply(
                lambda x: x if x and str(x).strip() else 'NEW'
            )
            
            materials_export_df = materials_df[[
                'order_no', 'order_date', 'order_status',
                'pt_code', 'legacy_display', 'material_name', 'package_size', 'brand_name',
                'required_qty', 'issued_qty', 'returned_qty', 'net_used',
                'uom', 'issue_percentage', 'material_status'
            ]].copy()
            
            materials_export_df.columns = [
                'Order No', 'Order Date', 'Order Status',
                'PT Code', 'Legacy Code', 'Material Name', 'Package Size', 'Brand',
                'Required', 'Issued', 'Returned', 'Net Used',
                'UOM', 'Issue %', 'Material Status'
            ]
        else:
            materials_export_df = pd.DataFrame(columns=[
                'Order No', 'Order Date', 'Order Status',
                'PT Code', 'Legacy Code', 'Material Name', 'Package Size', 'Brand',
                'Required', 'Issued', 'Returned', 'Net Used',
                'UOM', 'Issue %', 'Material Status'
            ])
        
        # Create metadata dataframe
        now = get_vietnam_now()
        
        # Get current user info (if available)
        current_user = "Unknown"
        if hasattr(st.session_state, 'user'):
            user = st.session_state.user
            if isinstance(user, dict):
                current_user = user.get('name') or user.get('username') or user.get('email', 'Unknown')
            elif hasattr(user, 'name'):
                current_user = user.name
        elif 'user_name' in st.session_state:
            current_user = st.session_state.user_name
        elif 'username' in st.session_state:
            current_user = st.session_state.username
        
        # Date preset description
        preset_labels = {
            OverviewConstants.DATE_PRESET_THIS_WEEK: "This Week",
            OverviewConstants.DATE_PRESET_THIS_MONTH: "This Month",
            OverviewConstants.DATE_PRESET_CUSTOM: "Custom Range",
        }
        date_preset = st.session_state.get('overview_date_preset', 'Unknown')
        date_preset_label = preset_labels.get(date_preset, date_preset)
        
        metadata = [
            ['Report Name', 'Production Lifecycle Overview'],
            ['Export Date', now.strftime('%Y-%m-%d')],
            ['Export Time', now.strftime('%H:%M:%S')],
            ['Exported By', current_user],
            ['', ''],
            ['Filter Conditions', ''],
            ['Date Preset', date_preset_label],
            ['From Date', format_date(filters.get('from_date'))],
            ['To Date', format_date(filters.get('to_date'))],
            ['Status Filter', filters.get('status') or 'All'],
            ['Health Filter', filters.get('health') or 'All'],
            ['Search Keyword', filters.get('search') or '-'],
            ['', ''],
            ['Data Summary', ''],
            ['Total MO Records', len(df)],
            ['Total Material Lines', len(materials_df)],
            ['Total Planned Qty', format_number(df['planned_qty'].sum(), 0)],
            ['Total Produced Qty', format_number(df['produced_qty'].sum(), 0)],
            ['Avg Progress %', f"{df['progress_percentage'].mean():.1f}%"],
            ['Avg Material %', f"{df['material_percentage'].mean():.1f}%"],
            ['', ''],
            ['Status Breakdown', ''],
            ['Draft', len(df[df['status'] == 'DRAFT'])],
            ['Confirmed', len(df[df['status'] == 'CONFIRMED'])],
            ['In Progress', len(df[df['status'] == 'IN_PROGRESS'])],
            ['Completed', len(df[df['status'] == 'COMPLETED'])],
            ['Cancelled', len(df[df['status'] == 'CANCELLED'])],
            ['', ''],
            ['Health Breakdown', ''],
            ['On Track', len(df[df['health_status'] == 'ON_TRACK'])],
            ['At Risk', len(df[df['health_status'] == 'AT_RISK'])],
            ['Delayed', len(df[df['health_status'] == 'DELAYED'])],
            ['Not Started', len(df[df['health_status'] == 'NOT_STARTED'])],
        ]
        
        metadata_df = pd.DataFrame(metadata, columns=['Field', 'Value'])
        
        # Export with multiple sheets (ordered: Export Info → Lifecycle Data → Material Details)
        excel_data = export_to_excel({
            'Export Info': metadata_df,
            'Lifecycle Data': export_df,
            'Material Details': materials_export_df
        })
        
        # Filename with timestamp
        timestamp = now.strftime('%Y%m%d_%H%M%S')
        filename = f"Production_Lifecycle_{timestamp}.xlsx"
        
        st.download_button(
            label="💾 Download Excel",
            data=excel_data,
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_overview_excel"
        )


# ==================== Material Details Tab ====================

def _render_material_details_tab(queries: OverviewQueries, filters: Dict[str, Any]):
    """Render Material Details tab with full material information"""
    
    # Get material data
    materials_df = queries.get_materials_for_export(
        from_date=filters['from_date'],
        to_date=filters['to_date'],
        status=filters['status'],
        search=filters['search']
    )
    
    if materials_df is None or materials_df.empty:
        st.info("📭 No material data found matching the filters")
        return
    
    # Create full product display format
    materials_df['material_display'] = materials_df.apply(
        lambda r: format_product_display({
            'pt_code': r['pt_code'],
            'legacy_pt_code': r['legacy_pt_code'],
            'product_name': r['material_name'],
            'package_size': r['package_size'],
            'brand_name': r['brand_name']
        }), axis=1
    )
    
    # Summary metrics
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        total_orders = materials_df['order_no'].nunique()
        st.metric("📋 Orders", format_number(total_orders, 0))
    
    with col2:
        total_lines = len(materials_df)
        st.metric("📦 Material Lines", format_number(total_lines, 0))
    
    with col3:
        total_issued = materials_df['issued_qty'].sum()
        total_required = materials_df['required_qty'].sum()
        avg_issue_pct = (total_issued / total_required * 100) if total_required > 0 else 0
        st.metric("📊 Avg Issue %", f"{avg_issue_pct:.1f}%")
    
    with col4:
        total_returned = materials_df['returned_qty'].sum()
        st.metric("↩️ Total Returned", format_number(total_returned, 0))
    
    st.markdown("---")
    
    # Prepare display dataframe
    display_df = materials_df[[
        'order_no', 'order_status', 'material_display',
        'required_qty', 'issued_qty', 'returned_qty', 'net_used',
        'uom', 'issue_percentage', 'material_status'
    ]].copy()
    
    # Add issue progress for visual
    display_df['issue_pct'] = display_df['issue_percentage'].fillna(0)
    
    # Status indicator
    display_df['status_display'] = display_df['material_status'].apply(create_status_indicator)
    
    # Render table
    st.dataframe(
        display_df[[
            'order_no', 'order_status', 'material_display',
            'required_qty', 'issued_qty', 'returned_qty', 'net_used',
            'uom', 'issue_pct', 'status_display'
        ]].rename(columns={
            'order_no': 'Order No',
            'order_status': 'Order Status',
            'material_display': 'Material',
            'required_qty': 'Required',
            'issued_qty': 'Issued',
            'returned_qty': 'Returned',
            'net_used': 'Net Used',
            'uom': 'UOM',
            'issue_pct': 'Issue %',
            'status_display': 'Status'
        }),
        use_container_width=True,
        hide_index=True,
        column_config={
            'Order No': st.column_config.TextColumn('Order No', width='small'),
            'Order Status': st.column_config.TextColumn('Order Status', width='small'),
            'Material': st.column_config.TextColumn('Material', width='large'),
            'Required': st.column_config.NumberColumn('Required', format='%.2f'),
            'Issued': st.column_config.NumberColumn('Issued', format='%.2f'),
            'Returned': st.column_config.NumberColumn('Returned', format='%.2f'),
            'Net Used': st.column_config.NumberColumn('Net Used', format='%.2f'),
            'UOM': st.column_config.TextColumn('UOM', width='small'),
            'Issue %': st.column_config.ProgressColumn('Issue %', format='%.0f%%', min_value=0, max_value=100),
            'Status': st.column_config.TextColumn('Status', width='small'),
        }
    )
    
    # Show record count
    st.caption(f"Showing {len(display_df)} material lines from {total_orders} orders")


# ==================== Main Render Function ====================

def render_overview_tab():
    """
    Main function to render the Production Lifecycle Overview tab
    Called from the main Production page
    """
    _init_session_state()
    
    queries = OverviewQueries()
    
    # Header
    st.subheader("📊 Production Lifecycle Overview")
    st.caption("Monitor complete production workflow: Planning → Material → Production → Quality")
    
    # Filters (get early to pass to dashboard and analytics)
    filters = _render_filter_bar()
    
    # Dashboard KPIs + Status Breakdown
    render_dashboard(from_date=filters['from_date'], to_date=filters['to_date'])
    
    st.markdown("---")
    
    # Action bar
    _render_action_bar(queries, filters, None)
    
    # Two tabs: Lifecycle Data | Material Details
    tab_lifecycle, tab_materials = st.tabs(["📋 Lifecycle Data", "📦 Material Details"])
    
    with tab_lifecycle:
        # Analytics section
        analytics_df = queries.get_production_overview(
            from_date=filters['from_date'],
            to_date=filters['to_date'],
            status=filters['status'],
            search=filters['search'],
            page=1,
            page_size=10000
        )
        
        if analytics_df is not None and not analytics_df.empty:
            _render_analytics_section(analytics_df)
        
        st.markdown("---")
        
        # Lifecycle table with drill-down
        _render_lifecycle_table(queries, filters)
    
    with tab_materials:
        _render_material_details_tab(queries, filters)