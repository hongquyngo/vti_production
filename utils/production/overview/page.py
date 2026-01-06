# utils/production/overview/page.py
"""
Main UI orchestrator for Production Lifecycle Overview domain
Renders overview tab with single Production Data table (combined MO + Materials)

Version: 4.0.0
Changes:
- v4.0.0: SIMPLIFIED - Removed Lifecycle Data tab, combined into single Production Data table
          - 1 row = 1 material line (full details)
          - Excel export: 2 sheets (Export Info + Production Data)
          - Clearer, no confusion between aggregate vs detail views
- v3.0.0: Fixed double-counting returns bug
- v2.0.0: Redesigned with lifecycle stages
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
    calculate_health_status,
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
        'overview_date_preset': OverviewConstants.DATE_PRESET_THIS_MONTH,
    }
    
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


# ==================== Filter Bar ====================

def _render_filter_bar() -> Dict[str, Any]:
    """Render filter bar and return selected filters"""
    presets = get_date_presets()
    today = get_vietnam_today()
    
    col1, col2, col3, col4, col5 = st.columns([1.5, 1, 1, 1, 1.5])
    
    with col1:
        # Include Custom option (not in presets dict)
        preset_options = [
            OverviewConstants.DATE_PRESET_THIS_MONTH,
            OverviewConstants.DATE_PRESET_THIS_WEEK,
            OverviewConstants.DATE_PRESET_CUSTOM,
        ]
        
        date_preset = st.selectbox(
            "📅 Date Range",
            options=preset_options,
            format_func=get_preset_label,
            index=preset_options.index(st.session_state.overview_date_preset) 
                  if st.session_state.overview_date_preset in preset_options else 0,
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
            "📋 Status",
            options=status_options,
            key="filter_status"
        )
    
    with col5:
        search = st.text_input(
            "🔍 Search",
            placeholder="Order No, Product, PT Code...",
            key="filter_search"
        )
    
    return {
        'from_date': from_date,
        'to_date': to_date,
        'status': status if status != 'All' else None,
        'search': search.strip() if search else None,
    }


# ==================== Analytics Section ====================

def _render_analytics_section(df: pd.DataFrame):
    """Render analytics charts section"""
    if not PLOTLY_AVAILABLE:
        st.info("📊 Charts require plotly. Install with: pip install plotly")
        return
    
    with st.expander("📈 Analytics Charts", expanded=False):
        col1, col2 = st.columns(2)
        
        with col1:
            # Yield by Product chart
            yield_chart = create_yield_by_product_chart(df)
            if yield_chart:
                st.plotly_chart(yield_chart, use_container_width=True)
            else:
                st.info("No yield data")
        
        with col2:
            # Schedule Performance chart
            schedule_chart = create_schedule_performance_chart(df)
            if schedule_chart:
                st.plotly_chart(schedule_chart, use_container_width=True)
            else:
                st.info("No schedule data")
        
        col3, col4 = st.columns(2)
        
        with col3:
            # Health Summary chart
            health_chart = create_health_summary_chart(df)
            if health_chart:
                st.plotly_chart(health_chart, use_container_width=True)
            else:
                st.info("No health data")
        
        with col4:
            # Material Efficiency chart
            efficiency_chart = create_material_efficiency_chart(df)
            if efficiency_chart:
                st.plotly_chart(efficiency_chart, use_container_width=True)
            else:
                st.info("No efficiency data")


# ==================== Action Bar ====================

def _render_action_bar(queries: OverviewQueries, filters: Dict[str, Any]):
    """Render action bar with export and refresh"""
    col1, col2, col3 = st.columns([1, 1, 2])
    
    with col1:
        if st.button("📥 Export Excel", use_container_width=True, key="btn_export_overview"):
            _export_production_data_excel(queries, filters)
    
    with col2:
        if st.button("🔄 Refresh", use_container_width=True, key="btn_refresh_overview"):
            st.rerun()
    
    with col3:
        timestamp = get_vietnam_now().strftime('%H:%M:%S')
        st.markdown(f"<div style='text-align:right; color:gray; padding-top:8px'>🕐 Last updated: {timestamp}</div>", 
                   unsafe_allow_html=True)


def _export_production_data_excel(queries: OverviewQueries, filters: Dict[str, Any]):
    """Export Production Data to Excel (2 sheets: Export Info + Production Data)"""
    with st.spinner("Exporting..."):
        # Get production data (1 row = 1 material line)
        df = queries.get_materials_for_export(
            from_date=filters['from_date'],
            to_date=filters['to_date'],
            status=filters['status'],
            search=filters['search']
        )
        
        if df is None or df.empty:
            st.warning("No data to export")
            return
        
        # Handle legacy code display (show "NEW" if empty)
        df['output_legacy_display'] = df['output_legacy_code'].apply(
            lambda x: x if x and str(x).strip() else 'NEW'
        )
        df['input_legacy_display'] = df['input_legacy_code'].apply(
            lambda x: x if x and str(x).strip() else 'NEW'
        )
        
        # Calculate health status for each row
        df['health_status'] = df.apply(
            lambda row: calculate_health_status(
                material_percentage=row.get('issue_percentage', 0) or 0,
                schedule_variance_days=row.get('schedule_variance_days', 0) or 0,
                quality_percentage=row.get('qc_pass_percentage'),
                status=row.get('order_status', '')
            ).value,
            axis=1
        )
        
        # Format has_alternatives as Yes/No
        df['alt_display'] = df['has_alternatives'].apply(lambda x: 'Yes' if x else 'No')
        
        # Prepare export dataframe with all columns
        export_df = df[[
            # MO Header
            'order_no', 'order_date', 'scheduled_date', 'completion_date', 
            'order_status', 'priority', 'health_status',
            # Output Product
            'output_pt_code', 'output_legacy_display', 'output_product_name', 
            'output_package_size', 'output_brand', 'bom_type',
            # MO Quantities & Progress
            'mo_planned_qty', 'mo_uom', 'mo_produced_qty', 'progress_percentage', 
            # QC & Receipts
            'total_receipts', 'passed_qty', 'failed_qty', 'pending_qty', 'qc_pass_percentage',
            # Warehouses
            'source_warehouse', 'target_warehouse',
            # Input Material
            'input_pt_code', 'input_legacy_display', 'input_material_name',
            'input_package_size', 'input_brand',
            # Input Material Quantities
            'required_qty', 'issued_actual', 'returned_actual', 'net_issued_qty',
            'material_uom', 'issue_percentage', 'last_issue_date', 'last_return_date',
            'material_status', 'alt_display'
        ]].copy()
        
        export_df.columns = [
            # MO Header
            'Order No', 'Order Date', 'Scheduled Date', 'Completion Date',
            'Status', 'Priority', 'Health',
            # Output Product
            'Output PT Code', 'Output Legacy Code', 'Output Product Name',
            'Output Package Size', 'Output Brand', 'BOM Type',
            # MO Quantities & Progress
            'Planned Qty', 'UOM', 'Produced Qty', 'Progress %',
            # QC & Receipts
            'Receipts', 'QC Passed', 'QC Failed', 'QC Pending', 'QC Pass %',
            # Warehouses
            'Source WH', 'Target WH',
            # Input Material
            'Input PT Code', 'Input Legacy Code', 'Input Material Name',
            'Input Package Size', 'Input Brand',
            # Input Material Quantities
            'Required (Equiv)', 'Issued (Actual)', 'Returned (Actual)', 'Net Issued (Equiv)',
            'Mat UOM', 'Issue %', 'Issue Date', 'Return Date',
            'Material Status', 'Has Alternatives'
        ]
        
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
        
        # Calculate summary metrics
        total_orders = df['order_no'].nunique()
        total_material_lines = len(df)
        total_required = df['required_qty'].sum()
        total_net_issued = df['net_issued_qty'].sum()
        total_returned = df['returned_actual'].sum()
        avg_issue_pct = (total_net_issued / total_required * 100) if total_required > 0 else 0
        
        # Status breakdown (by unique orders)
        orders_df = df.drop_duplicates(subset=['order_no'])
        
        metadata = [
            ['Report Name', 'Production Data Overview'],
            ['Export Date', now.strftime('%Y-%m-%d')],
            ['Export Time', now.strftime('%H:%M:%S')],
            ['Exported By', current_user],
            ['', ''],
            ['Filter Conditions', ''],
            ['Date Preset', date_preset_label],
            ['From Date', format_date(filters.get('from_date'))],
            ['To Date', format_date(filters.get('to_date'))],
            ['Status Filter', filters.get('status') or 'All'],
            ['Search Keyword', filters.get('search') or '-'],
            ['', ''],
            ['Data Summary', ''],
            ['Total Orders', total_orders],
            ['Total Material Lines', total_material_lines],
            ['Total Required (Equiv)', format_number(total_required, 2)],
            ['Total Net Issued (Equiv)', format_number(total_net_issued, 2)],
            ['Total Returned (Actual)', format_number(total_returned, 2)],
            ['Avg Issue %', f"{avg_issue_pct:.1f}%"],
            ['Lines with Alternatives', len(df[df['has_alternatives'] == 1])],
            ['', ''],
            ['Order Status Breakdown', ''],
            ['Draft', len(orders_df[orders_df['order_status'] == 'DRAFT'])],
            ['Confirmed', len(orders_df[orders_df['order_status'] == 'CONFIRMED'])],
            ['In Progress', len(orders_df[orders_df['order_status'] == 'IN_PROGRESS'])],
            ['Completed', len(orders_df[orders_df['order_status'] == 'COMPLETED'])],
            ['Cancelled', len(orders_df[orders_df['order_status'] == 'CANCELLED'])],
            ['', ''],
            ['Health Breakdown', ''],
            ['On Track', len(orders_df[orders_df['health_status'] == 'ON_TRACK'])],
            ['At Risk', len(orders_df[orders_df['health_status'] == 'AT_RISK'])],
            ['Delayed', len(orders_df[orders_df['health_status'] == 'DELAYED'])],
            ['Not Started', len(orders_df[orders_df['health_status'] == 'NOT_STARTED'])],
            ['', ''],
            ['Column Definitions', ''],
            ['Required (Equiv)', 'Required quantity in primary material equivalent units'],
            ['Issued (Actual)', 'Total physical units issued (primary + alternative)'],
            ['Returned (Actual)', 'Total physical units returned'],
            ['Net Issued (Equiv)', 'Net issued in equivalent units = issued_qty from table (accurate)'],
            ['Issue %', 'Net Issued / Required × 100'],
            ['Has Alternatives', 'Yes if alternative materials were used'],
        ]
        
        metadata_df = pd.DataFrame(metadata, columns=['Field', 'Value'])
        
        # Export with 2 sheets only
        excel_data = export_to_excel({
            'Export Info': metadata_df,
            'Production Data': export_df
        })
        
        # Filename with timestamp
        timestamp = now.strftime('%Y%m%d_%H%M%S')
        filename = f"Production_Data_{timestamp}.xlsx"
        
        st.download_button(
            label="💾 Download Excel",
            data=excel_data,
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_production_excel"
        )


# ==================== Production Data Table ====================

def _render_production_data_table(queries: OverviewQueries, filters: Dict[str, Any]):
    """
    Render Production Data table (combined MO + Material details)
    1 row = 1 material line
    """
    # Get production data
    df = queries.get_materials_for_export(
        from_date=filters['from_date'],
        to_date=filters['to_date'],
        status=filters['status'],
        search=filters['search']
    )
    
    return _render_production_data_table_with_data(queries, filters, df)


def _render_production_data_table_with_data(queries: OverviewQueries, filters: Dict[str, Any], df: Optional[pd.DataFrame]):
    """
    Render Production Data table with pre-fetched data
    1 row = 1 material line
    """
    
    if df is None or df.empty:
        st.info("📭 No production data found matching the filters")
        return
    
    # Calculate health status only if not already calculated
    if 'health_status' not in df.columns:
        df['health_status'] = df.apply(
            lambda row: calculate_health_status(
                material_percentage=row.get('issue_percentage', 0) or 0,
                schedule_variance_days=row.get('schedule_variance_days', 0) or 0,
                quality_percentage=row.get('qc_pass_percentage'),
                status=row.get('order_status', '')
            ).value,
            axis=1
        )
    
    # Create display columns
    # Output product display: PT_CODE (LEGACY or NEW) | NAME | PKG_SIZE (BRAND)
    df['output_display'] = df.apply(
        lambda r: format_product_display({
            'pt_code': r['output_pt_code'],
            'legacy_pt_code': r['output_legacy_code'],
            'product_name': r['output_product_name'],
            'package_size': r['output_package_size'],
            'brand_name': r['output_brand']
        }), axis=1
    )
    
    # Input material display
    df['material_display'] = df.apply(
        lambda r: format_product_display({
            'pt_code': r['input_pt_code'],
            'legacy_pt_code': r['input_legacy_code'],
            'product_name': r['input_material_name'],
            'package_size': r['input_package_size'],
            'brand_name': r['input_brand']
        }), axis=1
    )
    
    # Format dates
    df['issue_date_display'] = df['last_issue_date'].apply(
        lambda x: format_datetime_vn(x, '%d/%m/%Y') if pd.notna(x) else '-'
    )
    df['return_date_display'] = df['last_return_date'].apply(
        lambda x: format_datetime_vn(x, '%d/%m/%Y') if pd.notna(x) else '-'
    )
    
    # Status and health indicators
    df['status_display'] = df['order_status'].apply(create_status_indicator)
    df['health_display'] = df['health_status'].apply(get_health_indicator)
    df['alt_flag'] = df['has_alternatives'].apply(lambda x: '⚠️' if x else '')
    
    # Issue percentage for progress bar
    df['issue_pct'] = df['issue_percentage'].fillna(0)
    
    # Summary metrics
    st.markdown("### 📊 Summary")
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    
    with col1:
        total_orders = df['order_no'].nunique()
        st.metric("📋 Orders", format_number(total_orders, 0))
    
    with col2:
        total_lines = len(df)
        st.metric("📦 Material Lines", format_number(total_lines, 0))
    
    with col3:
        total_required = df['required_qty'].sum()
        st.metric("📝 Total Required", format_number(total_required, 0))
    
    with col4:
        total_net_issued = df['net_issued_qty'].sum()
        avg_issue_pct = (total_net_issued / total_required * 100) if total_required > 0 else 0
        st.metric("📊 Avg Issue %", f"{avg_issue_pct:.1f}%")
    
    with col5:
        total_returned = df['returned_actual'].sum()
        st.metric("↩️ Total Returned", format_number(total_returned, 0))
    
    with col6:
        alt_count = df['has_alternatives'].sum()
        st.metric("⚠️ With Alternatives", format_number(alt_count, 0))
    
    st.markdown("---")
    
    # Main data table
    st.markdown("### 📋 Production Data")
    st.caption("1 row = 1 material requirement per manufacturing order")
    
    # Prepare display dataframe
    display_df = df[[
        'order_no', 'order_status', 'health_display', 'output_display',
        'mo_planned_qty', 'mo_produced_qty', 'progress_percentage',
        'material_display', 'required_qty', 'issued_actual', 'returned_actual', 
        'net_issued_qty', 'issue_pct', 'material_uom', 'material_status', 'alt_flag'
    ]].copy()
    
    st.dataframe(
        display_df.rename(columns={
            'order_no': 'Order',
            'order_status': 'Status',
            'health_display': 'Health',
            'output_display': 'Output Product',
            'mo_planned_qty': 'Planned',
            'mo_produced_qty': 'Produced',
            'progress_percentage': 'Prod %',
            'material_display': 'Input Material',
            'required_qty': 'Required',
            'issued_actual': 'Issued (Act)',
            'returned_actual': 'Returned',
            'net_issued_qty': 'Net Issued',
            'issue_pct': 'Issue %',
            'material_uom': 'UOM',
            'material_status': 'Mat Status',
            'alt_flag': 'Alt'
        }),
        use_container_width=True,
        hide_index=True,
        column_config={
            'Order': st.column_config.TextColumn('Order', width='small'),
            'Status': st.column_config.TextColumn('Status', width='small'),
            'Health': st.column_config.TextColumn('Health', width='small'),
            'Output Product': st.column_config.TextColumn('Output Product', width='medium'),
            'Planned': st.column_config.NumberColumn('Planned', format='%.0f'),
            'Produced': st.column_config.NumberColumn('Produced', format='%.0f'),
            'Prod %': st.column_config.ProgressColumn('Prod %', format='%.0f%%', min_value=0, max_value=100),
            'Input Material': st.column_config.TextColumn('Input Material', width='medium'),
            'Required': st.column_config.NumberColumn('Required', format='%.2f'),
            'Issued (Act)': st.column_config.NumberColumn('Issued (Act)', format='%.2f'),
            'Returned': st.column_config.NumberColumn('Returned', format='%.2f'),
            'Net Issued': st.column_config.NumberColumn('Net Issued', format='%.2f'),
            'Issue %': st.column_config.ProgressColumn('Issue %', format='%.0f%%', min_value=0, max_value=100),
            'UOM': st.column_config.TextColumn('UOM', width='small'),
            'Mat Status': st.column_config.TextColumn('Mat Status', width='small'),
            'Alt': st.column_config.TextColumn('Alt', width='small'),
        },
        height=600
    )
    
    # Record count
    st.caption(f"Showing {len(display_df)} material lines from {total_orders} orders")
    
    # Return df for analytics
    return df


# ==================== Main Render Function ====================

def render_overview_tab():
    """
    Main function to render the Production Overview tab
    Single table view with all data combined
    """
    _init_session_state()
    
    queries = OverviewQueries()
    
    # Header
    st.subheader("📊 Production Overview")
    st.caption("Monitor production workflow: Orders → Materials → Production → Quality")
    
    # Filters
    filters = _render_filter_bar()
    
    # Dashboard KPIs
    render_dashboard(from_date=filters['from_date'], to_date=filters['to_date'])
    
    st.markdown("---")
    
    # Get data first for analytics
    df = queries.get_materials_for_export(
        from_date=filters['from_date'],
        to_date=filters['to_date'],
        status=filters['status'],
        search=filters['search']
    )
    
    # Analytics section (above table, like original layout)
    if df is not None and not df.empty:
        # Calculate health status for analytics
        df['health_status'] = df.apply(
            lambda row: calculate_health_status(
                material_percentage=row.get('issue_percentage', 0) or 0,
                schedule_variance_days=row.get('schedule_variance_days', 0) or 0,
                quality_percentage=row.get('qc_pass_percentage'),
                status=row.get('order_status', '')
            ).value,
            axis=1
        )
        
        # For analytics, we need order-level data
        orders_df = df.drop_duplicates(subset=['order_no']).copy()
        # Map columns to match what analytics functions expect
        orders_df['product_name'] = orders_df['output_product_name']
        orders_df['planned_qty'] = orders_df['mo_planned_qty']
        orders_df['produced_qty'] = orders_df['mo_produced_qty']
        orders_df['quality_percentage'] = orders_df['qc_pass_percentage']
        orders_df['material_percentage'] = orders_df['issue_percentage']
        orders_df['status'] = orders_df['order_status']
        
        _render_analytics_section(orders_df)
        
        st.markdown("---")
    
    # Action bar
    _render_action_bar(queries, filters)
    
    # Main Production Data table
    _render_production_data_table_with_data(queries, filters, df)