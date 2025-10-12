# pages/3_📊_Reports.py - Production Reports & Analytics (Updated for Independent Domains)
"""
Production Reports & Analytics
Independent domain using direct SQL queries
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, date
import logging

# ==================== UPDATED IMPORTS - REPORT DOMAIN ONLY ====================
from utils.auth import AuthManager
from utils.db import get_db_engine

# Report domain imports - Independent queries
from utils.report.queries import (
    ReportQueries,
    get_orders_for_period,
    get_products_list
)
from utils.report.common import (
    format_number,
    format_currency,
    calculate_percentage,
    get_date_filter_presets,
    export_to_excel
)

logger = logging.getLogger(__name__)

# ==================== Page Configuration ====================

st.set_page_config(
    page_title="Production Reports",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ==================== Authentication ====================

auth = AuthManager()
auth.require_auth()

# ==================== Initialize ====================

@st.cache_resource
def get_report_manager():
    """Initialize and cache report manager"""
    return ReportQueries()

report_queries = get_report_manager()

# ==================== Session State ====================

if 'selected_report' not in st.session_state:
    st.session_state.selected_report = "Production Dashboard"
if 'date_range' not in st.session_state:
    st.session_state.date_range = "Last 30 Days"

# ==================== Header ====================

st.title("📊 Production Reports & Analytics")

# ==================== Report Navigation ====================

report_types = [
    "Production Dashboard",
    "Material Usage Analysis",
    "Efficiency Metrics",
    "Batch Tracking",
    "Inventory Impact",
    "Return Analysis"
]

selected_report = st.selectbox(
    "Select Report",
    report_types,
    index=report_types.index(st.session_state.selected_report)
)

st.session_state.selected_report = selected_report
st.markdown("---")

# ==================== Date Range Selection ====================

def get_date_range():
    """Common date range selector"""
    col1, col2, col3 = st.columns([2, 2, 2])
    
    with col1:
        preset = st.selectbox(
            "Quick Select",
            list(get_date_filter_presets().keys()),
            index=4  # Default to "This Month"
        )
    
    dates = get_date_filter_presets()[preset]
    
    with col2:
        start_date = st.date_input("Start Date", value=dates[0])
    
    with col3:
        end_date = st.date_input("End Date", value=dates[1])
    
    return start_date, end_date

# ==================== Production Dashboard ====================

if selected_report == "Production Dashboard":
    st.subheader("🏭 Production Dashboard")
    
    start_date, end_date = get_date_range()
    
    if st.button("Generate Dashboard", type="primary", use_container_width=True):
        with st.spinner("Loading dashboard data..."):
            
            # Get production orders using independent query
            orders = report_queries.get_production_orders(start_date, end_date)
            
            if not orders.empty:
                # Key Metrics
                st.markdown("### Key Metrics")
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    total_orders = len(orders)
                    st.metric("Total Orders", total_orders)
                
                with col2:
                    completed = len(orders[orders['status'] == 'COMPLETED'])
                    completion_rate = calculate_percentage(completed, total_orders)
                    st.metric(
                        "Completed",
                        completed,
                        delta=f"{completion_rate:.1f}% completion rate"
                    )
                
                with col3:
                    total_output = orders[orders['status'] == 'COMPLETED']['produced_qty'].sum()
                    st.metric("Total Output", format_number(total_output, 0))
                
                with col4:
                    in_progress = len(orders[orders['status'] == 'IN_PROGRESS'])
                    st.metric("In Progress", in_progress)
                
                # Charts
                st.markdown("### Production Analysis")
                
                # Status distribution
                col1, col2 = st.columns(2)
                
                with col1:
                    status_counts = orders['status'].value_counts().reset_index()
                    status_counts.columns = ['status', 'count']
                    
                    fig = px.pie(
                        status_counts,
                        values='count',
                        names='status',
                        title="Order Status Distribution",
                        color_discrete_map={
                            'COMPLETED': '#00CC88',
                            'IN_PROGRESS': '#FFB800',
                            'CONFIRMED': '#0088FE',
                            'DRAFT': '#888888',
                            'CANCELLED': '#FF4444'
                        }
                    )
                    st.plotly_chart(fig, use_container_width=True)
                
                with col2:
                    # Production by type
                    type_summary = orders.groupby('bom_type').agg({
                        'produced_qty': 'sum',
                        'order_no': 'count'
                    }).reset_index()
                    type_summary.columns = ['Type', 'Quantity', 'Orders']
                    
                    fig = px.bar(
                        type_summary,
                        x='Type',
                        y='Quantity',
                        title="Production by Type",
                        text='Orders'
                    )
                    st.plotly_chart(fig, use_container_width=True)
                
                # Export option
                if st.button("📥 Export Data"):
                    excel_data = export_to_excel(orders)
                    st.download_button(
                        label="Download Excel",
                        data=excel_data,
                        file_name=f"production_orders_{start_date}_{end_date}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
            else:
                st.info("No production orders found for the selected period")

# ==================== Material Usage Analysis ====================

elif selected_report == "Material Usage Analysis":
    st.subheader("📦 Material Usage Analysis")
    
    # Filter options
    col1, col2, col3 = st.columns(3)
    
    with col1:
        # Get orders for selection
        recent_orders = get_orders_for_period(
            date.today().replace(day=1),
            date.today(),
            status=None
        )
        
        if not recent_orders.empty:
            order_options = ["All"] + recent_orders['order_no'].tolist()
            selected_order = st.selectbox("Select Order", order_options)
            order_id = None
            if selected_order != "All":
                order_id = recent_orders[recent_orders['order_no'] == selected_order]['id'].iloc[0]
        else:
            selected_order = None
            order_id = None
            st.info("No orders available")
    
    with col2:
        material_filter = st.text_input("Material Name (contains)", "")
    
    with col3:
        usage_status = st.selectbox(
            "Usage Status",
            ["All", "OVERUSE", "EXACT", "UNDERUSE"]
        )
    
    if st.button("Analyze Usage", type="primary", use_container_width=True):
        with st.spinner("Analyzing material usage..."):
            
            try:
                # Get usage data using independent query
                usage_data = report_queries.get_material_usage_tracking(
                    order_id=order_id,
                    material_filter=material_filter,
                    usage_status=usage_status
                )
                
                if not usage_data.empty:
                    # Summary metrics
                    col1, col2, col3, col4 = st.columns(4)
                    
                    with col1:
                        avg_efficiency = usage_data['usage_efficiency_pct'].mean()
                        st.metric("Avg Efficiency", f"{avg_efficiency:.1f}%")
                    
                    with col2:
                        total_variance = usage_data['quantity_variance'].sum()
                        st.metric("Total Variance", format_number(total_variance, 2))
                    
                    with col3:
                        overuse_count = len(usage_data[usage_data['usage_status'].str.contains('OVERUSE', na=False)])
                        st.metric("Overuse Cases", overuse_count)
                    
                    with col4:
                        materials_count = usage_data['material_id'].nunique()
                        st.metric("Materials", materials_count)
                    
                    # Display table
                    st.markdown("### Material Usage Details")
                    st.dataframe(
                        usage_data[['order_no', 'material_name', 'required_qty', 'issued_qty',
                                   'returned_qty', 'actual_used_qty', 'usage_efficiency_pct', 'usage_status']],
                        use_container_width=True,
                        hide_index=True
                    )
                else:
                    st.info("No usage data found with the selected filters")
                    
            except Exception as e:
                st.error(f"Error loading usage data: {str(e)}")

# ==================== Efficiency Metrics ====================

elif selected_report == "Efficiency Metrics":
    st.subheader("📈 Production Efficiency Metrics")
    
    start_date, end_date = get_date_range()
    
    if st.button("Calculate Metrics", type="primary", use_container_width=True):
        with st.spinner("Calculating efficiency metrics..."):
            
            try:
                # Get efficiency data using independent query
                efficiency_data = report_queries.get_production_efficiency(start_date, end_date)
                
                if not efficiency_data.empty:
                    # Overall KPIs
                    st.markdown("### Key Performance Indicators")
                    col1, col2, col3, col4 = st.columns(4)
                    
                    with col1:
                        avg_prod_eff = efficiency_data['production_efficiency_pct'].mean()
                        st.metric("Avg Production Efficiency", f"{avg_prod_eff:.1f}%")
                    
                    with col2:
                        avg_mat_eff = efficiency_data['avg_material_efficiency_pct'].mean()
                        st.metric("Avg Material Efficiency", f"{avg_mat_eff:.1f}%")
                    
                    with col3:
                        on_time = len(efficiency_data[efficiency_data['days_variance'] <= 0])
                        on_time_rate = calculate_percentage(on_time, len(efficiency_data))
                        st.metric("On-Time Delivery", f"{on_time_rate:.1f}%")
                    
                    with col4:
                        completed = len(efficiency_data[efficiency_data['status'] == 'COMPLETED'])
                        st.metric("Completed Orders", completed)
                    
                    # Efficiency by type
                    st.markdown("### Efficiency by Production Type")
                    
                    type_efficiency = efficiency_data.groupby('bom_type').agg({
                        'production_efficiency_pct': 'mean',
                        'avg_material_efficiency_pct': 'mean'
                    }).reset_index()
                    
                    fig = go.Figure()
                    fig.add_trace(go.Bar(
                        x=type_efficiency['bom_type'],
                        y=type_efficiency['production_efficiency_pct'],
                        name='Production Efficiency',
                        marker_color='#00CC88'
                    ))
                    fig.add_trace(go.Bar(
                        x=type_efficiency['bom_type'],
                        y=type_efficiency['avg_material_efficiency_pct'],
                        name='Material Efficiency',
                        marker_color='#0088FE'
                    ))
                    
                    fig.update_layout(
                        title="Efficiency Comparison by Type",
                        xaxis_title="Production Type",
                        yaxis_title="Efficiency %",
                        barmode='group'
                    )
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("No efficiency data found for the selected period")
                    
            except Exception as e:
                st.error(f"Error loading efficiency data: {str(e)}")

# ==================== Batch Tracking ====================

elif selected_report == "Batch Tracking":
    st.subheader("🔍 Batch Tracking & Traceability")
    
    search_type = st.radio(
        "Search By",
        ["Batch Number", "Production Order", "Product"],
        horizontal=True
    )
    
    if search_type == "Batch Number":
        batch_no = st.text_input("Enter Batch Number", placeholder="e.g., B20241106001")
        
        if batch_no and st.button("Track Batch", type="primary"):
            # Get batch info using independent query
            batch_info = report_queries.get_batch_info(batch_no)
            
            if batch_info:
                st.markdown("### Batch Information")
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    st.metric("Product", batch_info.get('product_name', 'N/A'))
                with col2:
                    st.metric("Quantity", f"{batch_info.get('current_qty', 0)}")
                with col3:
                    st.metric("Warehouse", batch_info.get('warehouse_name', 'N/A'))
                with col4:
                    expiry_status = batch_info.get('expiry_status', 'OK')
                    st.metric("Expiry Status", expiry_status)
                
                # Additional details
                with st.expander("Detailed Information"):
                    st.write(f"**Batch Number:** {batch_info.get('batch_no')}")
                    st.write(f"**Product Code:** {batch_info.get('product_code')}")
                    st.write(f"**Created Date:** {batch_info.get('created_date')}")
                    st.write(f"**Expiry Date:** {batch_info.get('expired_date', 'N/A')}")
            else:
                st.warning("Batch not found")
    
    elif search_type == "Production Order":
        recent_orders = get_orders_for_period(
            date.today().replace(month=1, day=1),
            date.today(),
            status='COMPLETED'
        )
        
        if not recent_orders.empty:
            order_no = st.selectbox(
                "Select Production Order",
                recent_orders['order_no'].tolist()
            )
            
            if st.button("View Order Details", type="primary"):
                order_id = recent_orders[recent_orders['order_no'] == order_no]['id'].iloc[0]
                efficiency = report_queries.get_production_order_efficiency(order_id)
                
                if efficiency:
                    st.markdown("### Order Performance")
                    col1, col2, col3, col4 = st.columns(4)
                    
                    with col1:
                        st.metric("Production Efficiency", f"{efficiency['production_efficiency_pct']:.1f}%")
                    with col2:
                        mat_eff = efficiency.get('material_efficiency_pct', 0)
                        st.metric("Material Efficiency", f"{mat_eff:.1f}%")
                    with col3:
                        st.metric("Planned Qty", efficiency['planned_qty'])
                    with col4:
                        st.metric("Produced Qty", efficiency['produced_qty'])
                    
                    # Material details
                    if efficiency['material_details']:
                        st.markdown("### Material Usage")
                        materials_df = pd.DataFrame(efficiency['material_details'])
                        st.dataframe(materials_df, use_container_width=True, hide_index=True)
        else:
            st.info("No completed orders available")
    
    else:  # Product search
        products = get_products_list()
        
        if not products.empty:
            product_options = {
                f"{row['name']} ({row['code']})": row['id']
                for _, row in products.iterrows()
            }
            
            selected_product = st.selectbox("Select Product", list(product_options.keys()))
            
            if st.button("Track Inventory", type="primary"):
                product_id = product_options[selected_product]
                stock_data = report_queries.get_product_stock_by_batches(product_id)
                
                if not stock_data.empty:
                    st.markdown("### Current Inventory")
                    total_stock = stock_data['quantity'].sum()
                    st.metric("Total Stock", format_number(total_stock, 2))
                    st.dataframe(stock_data, use_container_width=True, hide_index=True)
                else:
                    st.info("No stock found for this product")

# ==================== Inventory Impact ====================

elif selected_report == "Inventory Impact":
    st.subheader("📊 Inventory Impact Analysis")
    
    start_date, end_date = get_date_range()
    
    if st.button("Analyze Impact", type="primary", use_container_width=True):
        with st.spinner("Analyzing inventory impact..."):
            
            try:
                movements = report_queries.get_inventory_movements(start_date, end_date)
                
                if not movements.empty:
                    # Summary metrics
                    st.markdown("### Summary")
                    col1, col2, col3, col4 = st.columns(4)
                    
                    with col1:
                        unique_products = movements['product_name'].nunique()
                        st.metric("Products Affected", unique_products)
                    
                    with col2:
                        total_out = abs(movements[movements['net_quantity'] < 0]['net_quantity'].sum())
                        st.metric("Total Consumed", format_number(total_out, 0))
                    
                    with col3:
                        total_in = movements[movements['net_quantity'] > 0]['net_quantity'].sum()
                        st.metric("Total Produced", format_number(total_in, 0))
                    
                    with col4:
                        net_change = movements['net_quantity'].sum()
                        st.metric("Net Change", format_number(net_change, 0))
                    
                    # Movement details
                    st.markdown("### Movement Details")
                    st.dataframe(movements, use_container_width=True, hide_index=True)
                else:
                    st.info("No inventory movements found for the selected period")
                    
            except Exception as e:
                st.error(f"Error analyzing inventory impact: {str(e)}")

# ==================== Return Analysis ====================

elif selected_report == "Return Analysis":
    st.subheader("↩️ Material Return Analysis")
    
    start_date, end_date = get_date_range()
    
    if st.button("Analyze Returns", type="primary", use_container_width=True):
        with st.spinner("Analyzing material returns..."):
            
            try:
                returns_data = report_queries.get_material_return_analysis(start_date, end_date)
                
                if not returns_data.empty:
                    # Summary metrics
                    st.markdown("### Return Summary")
                    col1, col2, col3, col4 = st.columns(4)
                    
                    with col1:
                        total_issued = returns_data['total_issued'].sum()
                        st.metric("Total Issued", format_number(total_issued, 0))
                    
                    with col2:
                        total_returned = returns_data['total_returned'].sum()
                        st.metric("Total Returned", format_number(total_returned, 0))
                    
                    with col3:
                        overall_return_rate = calculate_percentage(total_returned, total_issued)
                        st.metric("Return Rate", f"{overall_return_rate:.1f}%")
                    
                    with col4:
                        materials_with_returns = len(returns_data[returns_data['total_returned'] > 0])
                        st.metric("Materials with Returns", materials_with_returns)
                    
                    # Detailed table
                    st.markdown("### Return Details")
                    st.dataframe(
                        returns_data[['order_no', 'material_name', 'total_issued', 'total_returned', 'return_rate_pct']],
                        use_container_width=True,
                        hide_index=True
                    )
                else:
                    st.info("No return data found for the selected period")
                    
            except Exception as e:
                st.error(f"Error analyzing returns: {str(e)}")

# ==================== Footer ====================

st.markdown("---")
col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    st.caption(
        f"Report generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | "
        f"Manufacturing Module v2.0"
    )