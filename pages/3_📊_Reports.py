# pages/3_📊_Reports.py - Production Reports & Analytics (Refactored)
"""
Production Reports & Analytics
Aligned with the enhanced production module using actual methods and SQL views
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional
import logging

from utils.auth import AuthManager
from utils.db import get_db_engine
from modules.production import ProductionManager
from modules.inventory import InventoryManager
from modules.common import (
    format_number, format_currency, calculate_percentage,
    get_date_filter_presets, export_to_excel
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
def get_managers():
    """Initialize and cache managers"""
    return ProductionManager(), InventoryManager(), get_db_engine()

prod_manager, inv_manager, db_engine = get_managers()

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
            
            # Get production orders
            orders = prod_manager.get_orders(
                from_date=start_date,
                to_date=end_date
            )
            
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
                        'id': 'count'
                    }).reset_index()
                    type_summary.columns = ['Type', 'Quantity', 'Orders']
                    
                    fig = px.bar(
                        type_summary,
                        x='Type',
                        y='Quantity',
                        title="Production by Type",
                        text='Orders',
                        labels={'Quantity': 'Total Produced', 'Type': 'Production Type'}
                    )
                    st.plotly_chart(fig, use_container_width=True)
                
                # Daily trend
                st.markdown("### Daily Production Trend")
                
                # Group by date and status
                orders['order_date'] = pd.to_datetime(orders['order_date'])
                daily_orders = orders.groupby(['order_date', 'status']).size().reset_index(name='count')
                
                fig = px.line(
                    daily_orders,
                    x='order_date',
                    y='count',
                    color='status',
                    title="Orders by Status Over Time",
                    labels={'count': 'Number of Orders', 'order_date': 'Date'}
                )
                st.plotly_chart(fig, use_container_width=True)
                
                # Detailed table
                with st.expander("📋 Detailed Orders"):
                    display_cols = [
                        'order_no', 'order_date', 'product_name', 'bom_type',
                        'planned_qty', 'produced_qty', 'status', 'priority'
                    ]
                    
                    st.dataframe(
                        orders[display_cols],
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "order_no": "Order No.",
                            "order_date": st.column_config.DateColumn("Date"),
                            "product_name": "Product",
                            "bom_type": "Type",
                            "planned_qty": st.column_config.NumberColumn("Planned", format="%d"),
                            "produced_qty": st.column_config.NumberColumn("Produced", format="%d"),
                            "status": "Status",
                            "priority": "Priority"
                        }
                    )
                    
                    # Export button
                    excel_data = export_to_excel(orders[display_cols])
                    st.download_button(
                        label="📥 Download Excel",
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
        recent_orders = prod_manager.get_orders(page_size=100)
        if not recent_orders.empty:
            order_options = ["All"] + recent_orders['order_no'].tolist()
            selected_order = st.selectbox("Select Order", order_options)
        else:
            selected_order = None
            st.info("No orders available")
    
    with col2:
        material_filter = st.text_input("Material Name (contains)", "")
    
    with col3:
        usage_status = st.selectbox(
            "Usage Status",
            ["All", "OVERUSE", "EXACT", "UNDERUSE", "HIGH_OVERUSE", "HIGH_UNDERUSE"]
        )
    
    if st.button("Analyze Usage", type="primary", use_container_width=True):
        with st.spinner("Analyzing material usage..."):
            
            # Build query for the view
            query = "SELECT * FROM v_material_usage_tracking WHERE 1=1"
            params = []
            
            if selected_order and selected_order != "All":
                selected_order_id = recent_orders[recent_orders['order_no'] == selected_order]['id'].iloc[0]
                query += " AND mo_id = %s"
                params.append(selected_order_id)
            
            if material_filter:
                query += " AND material_name LIKE %s"
                params.append(f"%{material_filter}%")
            
            if usage_status != "All":
                query += " AND usage_status = %s"
                params.append(usage_status)
            
            # Execute query
            try:
                usage_data = pd.read_sql(query, db_engine, params=tuple(params) if params else None)
                
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
                        overuse_count = len(usage_data[usage_data['usage_status'].str.contains('OVERUSE')])
                        st.metric("Overuse Cases", overuse_count)
                    
                    with col4:
                        materials_count = usage_data['material_id'].nunique()
                        st.metric("Materials", materials_count)
                    
                    # Efficiency distribution
                    st.markdown("### Material Efficiency Distribution")
                    
                    fig = px.histogram(
                        usage_data,
                        x='usage_efficiency_pct',
                        nbins=20,
                        title="Efficiency Distribution",
                        labels={'usage_efficiency_pct': 'Usage Efficiency %', 'count': 'Number of Materials'}
                    )
                    fig.add_vline(x=100, line_dash="dash", line_color="green", annotation_text="Target")
                    st.plotly_chart(fig, use_container_width=True)
                    
                    # Top variances
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        top_overuse = usage_data.nlargest(10, 'quantity_variance')
                        if not top_overuse.empty:
                            fig = px.bar(
                                top_overuse,
                                x='quantity_variance',
                                y='material_name',
                                orientation='h',
                                title="Top 10 Material Overuse",
                                labels={'quantity_variance': 'Excess Quantity', 'material_name': 'Material'},
                                color_discrete_sequence=['#FF4444']
                            )
                            st.plotly_chart(fig, use_container_width=True)
                    
                    with col2:
                        top_underuse = usage_data.nsmallest(10, 'quantity_variance')
                        if not top_underuse.empty:
                            top_underuse['quantity_variance'] = abs(top_underuse['quantity_variance'])
                            fig = px.bar(
                                top_underuse,
                                x='quantity_variance',
                                y='material_name',
                                orientation='h',
                                title="Top 10 Material Underuse",
                                labels={'quantity_variance': 'Saved Quantity', 'material_name': 'Material'},
                                color_discrete_sequence=['#00CC88']
                            )
                            st.plotly_chart(fig, use_container_width=True)
                    
                    # Detailed table
                    with st.expander("📋 Detailed Usage Data"):
                        display_cols = [
                            'order_no', 'material_name', 'required_qty', 'issued_qty',
                            'returned_qty', 'actual_used_qty', 'usage_efficiency_pct',
                            'quantity_variance', 'usage_status'
                        ]
                        
                        st.dataframe(
                            usage_data[display_cols],
                            use_container_width=True,
                            hide_index=True,
                            column_config={
                                "order_no": "Order",
                                "material_name": "Material",
                                "required_qty": st.column_config.NumberColumn("Required", format="%.2f"),
                                "issued_qty": st.column_config.NumberColumn("Issued", format="%.2f"),
                                "returned_qty": st.column_config.NumberColumn("Returned", format="%.2f"),
                                "actual_used_qty": st.column_config.NumberColumn("Used", format="%.2f"),
                                "usage_efficiency_pct": st.column_config.NumberColumn("Efficiency %", format="%.1f"),
                                "quantity_variance": st.column_config.NumberColumn("Variance", format="%.2f"),
                                "usage_status": "Status"
                            }
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
            
            # Query the efficiency view
            query = """
                SELECT * FROM v_production_efficiency 
                WHERE order_date BETWEEN %s AND %s
                ORDER BY production_efficiency_pct DESC
            """
            
            try:
                efficiency_data = pd.read_sql(query, db_engine, params=(start_date, end_date))
                
                if not efficiency_data.empty:
                    # Overall KPIs
                    st.markdown("### Key Performance Indicators")
                    col1, col2, col3, col4 = st.columns(4)
                    
                    with col1:
                        avg_prod_eff = efficiency_data['production_efficiency_pct'].mean()
                        st.metric(
                            "Avg Production Efficiency",
                            f"{avg_prod_eff:.1f}%",
                            help="Average actual vs planned output"
                        )
                    
                    with col2:
                        avg_mat_eff = efficiency_data['avg_material_efficiency_pct'].mean()
                        st.metric(
                            "Avg Material Efficiency",
                            f"{avg_mat_eff:.1f}%",
                            help="Average material usage efficiency"
                        )
                    
                    with col3:
                        on_time = len(efficiency_data[efficiency_data['days_variance'] <= 0])
                        on_time_rate = calculate_percentage(on_time, len(efficiency_data))
                        st.metric(
                            "On-Time Delivery",
                            f"{on_time_rate:.1f}%",
                            help="Orders completed by scheduled date"
                        )
                    
                    with col4:
                        completed = len(efficiency_data[efficiency_data['status'] == 'COMPLETED'])
                        st.metric("Completed Orders", completed)
                    
                    # Efficiency by BOM type
                    st.markdown("### Efficiency by Production Type")
                    
                    type_efficiency = efficiency_data.groupby('bom_type').agg({
                        'production_efficiency_pct': 'mean',
                        'avg_material_efficiency_pct': 'mean',
                        'order_id': 'count'
                    }).reset_index()
                    type_efficiency.columns = ['Type', 'Production Efficiency', 'Material Efficiency', 'Orders']
                    
                    fig = go.Figure()
                    fig.add_trace(go.Bar(
                        x=type_efficiency['Type'],
                        y=type_efficiency['Production Efficiency'],
                        name='Production Efficiency',
                        marker_color='#00CC88'
                    ))
                    fig.add_trace(go.Bar(
                        x=type_efficiency['Type'],
                        y=type_efficiency['Material Efficiency'],
                        name='Material Efficiency',
                        marker_color='#0088FE'
                    ))
                    
                    fig.update_layout(
                        title="Efficiency Comparison by Type",
                        xaxis_title="Production Type",
                        yaxis_title="Efficiency %",
                        barmode='group',
                        hovermode='x unified'
                    )
                    st.plotly_chart(fig, use_container_width=True)
                    
                    # Time efficiency analysis
                    st.markdown("### Time Performance")
                    
                    completed_orders = efficiency_data[efficiency_data['status'] == 'COMPLETED'].copy()
                    if not completed_orders.empty:
                        completed_orders['delay_category'] = pd.cut(
                            completed_orders['days_variance'],
                            bins=[-float('inf'), 0, 1, 3, 7, float('inf')],
                            labels=['On Time', '1 Day Late', '2-3 Days Late', '4-7 Days Late', '>7 Days Late']
                        )
                        
                        delay_counts = completed_orders['delay_category'].value_counts().reset_index()
                        delay_counts.columns = ['Category', 'Count']
                        
                        fig = px.pie(
                            delay_counts,
                            values='Count',
                            names='Category',
                            title="Delivery Performance Distribution",
                            color_discrete_map={
                                'On Time': '#00CC88',
                                '1 Day Late': '#FFB800',
                                '2-3 Days Late': '#FF8800',
                                '4-7 Days Late': '#FF4444',
                                '>7 Days Late': '#CC0000'
                            }
                        )
                        st.plotly_chart(fig, use_container_width=True)
                    
                    # Top and bottom performers
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.markdown("#### Top 10 Performers")
                        top_performers = efficiency_data.nlargest(10, 'production_efficiency_pct')[
                            ['order_no', 'product_name', 'production_efficiency_pct', 'avg_material_efficiency_pct']
                        ]
                        st.dataframe(
                            top_performers,
                            use_container_width=True,
                            hide_index=True,
                            column_config={
                                "order_no": "Order",
                                "product_name": "Product",
                                "production_efficiency_pct": st.column_config.NumberColumn("Prod Eff %", format="%.1f"),
                                "avg_material_efficiency_pct": st.column_config.NumberColumn("Mat Eff %", format="%.1f")
                            }
                        )
                    
                    with col2:
                        st.markdown("#### Bottom 10 Performers")
                        bottom_performers = efficiency_data.nsmallest(10, 'production_efficiency_pct')[
                            ['order_no', 'product_name', 'production_efficiency_pct', 'avg_material_efficiency_pct']
                        ]
                        st.dataframe(
                            bottom_performers,
                            use_container_width=True,
                            hide_index=True,
                            column_config={
                                "order_no": "Order",
                                "product_name": "Product",
                                "production_efficiency_pct": st.column_config.NumberColumn("Prod Eff %", format="%.1f"),
                                "avg_material_efficiency_pct": st.column_config.NumberColumn("Mat Eff %", format="%.1f")
                            }
                        )
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
            # Get batch info
            batch_info = inv_manager.get_batch_info(batch_no)
            
            if batch_info:
                # Display batch details
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
                    details = {
                        "Batch Number": batch_info.get('batch_no'),
                        "Product Code": batch_info.get('product_code'),
                        "Created Date": batch_info.get('created_date'),
                        "Expiry Date": batch_info.get('expired_date', 'N/A'),
                        "Days to Expiry": batch_info.get('days_to_expiry', 'N/A')
                    }
                    
                    for key, value in details.items():
                        st.write(f"**{key}:** {value}")
            else:
                st.warning("Batch not found")
    
    elif search_type == "Production Order":
        # Get recent orders
        recent_orders = prod_manager.get_orders(status='COMPLETED', page_size=50)
        
        if not recent_orders.empty:
            order_no = st.selectbox(
                "Select Production Order",
                recent_orders['order_no'].tolist()
            )
            
            if st.button("View Order Details", type="primary"):
                # Get order efficiency
                order_id = recent_orders[recent_orders['order_no'] == order_no]['id'].iloc[0]
                efficiency = prod_manager.calculate_production_efficiency(order_id)
                
                if efficiency:
                    # Display efficiency metrics
                    st.markdown("### Order Performance")
                    col1, col2, col3, col4 = st.columns(4)
                    
                    with col1:
                        st.metric(
                            "Production Efficiency",
                            f"{efficiency['production_efficiency_pct']:.1f}%"
                        )
                    with col2:
                        st.metric(
                            "Material Efficiency",
                            f"{efficiency.get('material_efficiency_pct', 0):.1f}%"
                        )
                    with col3:
                        st.metric(
                            "Planned Qty",
                            efficiency['planned_qty']
                        )
                    with col4:
                        st.metric(
                            "Produced Qty",
                            efficiency['produced_qty']
                        )
                    
                    # Material details
                    if efficiency['material_details']:
                        st.markdown("### Material Usage")
                        materials_df = pd.DataFrame(efficiency['material_details'])
                        
                        st.dataframe(
                            materials_df,
                            use_container_width=True,
                            hide_index=True,
                            column_config={
                                "material_name": "Material",
                                "required_qty": st.column_config.NumberColumn("Required", format="%.2f"),
                                "issued_qty": st.column_config.NumberColumn("Issued", format="%.2f"),
                                "returned_qty": st.column_config.NumberColumn("Returned", format="%.2f"),
                                "actual_used_qty": st.column_config.NumberColumn("Used", format="%.2f"),
                                "usage_efficiency_pct": st.column_config.NumberColumn("Efficiency %", format="%.1f")
                            }
                        )
        else:
            st.info("No completed orders available")
    
    else:  # Product search
        products = pd.read_sql("SELECT id, name, pt_code FROM products WHERE delete_flag = 0", db_engine)
        
        if not products.empty:
            product_options = {
                f"{row['name']} ({row['pt_code']})": row['id']
                for _, row in products.iterrows()
            }
            
            selected_product = st.selectbox(
                "Select Product",
                list(product_options.keys())
            )
            
            if st.button("Track Inventory", type="primary"):
                product_id = product_options[selected_product]
                
                # Get current stock
                query = """
                    SELECT 
                        ih.batch_no,
                        ih.remain as quantity,
                        ih.expired_date,
                        w.name as warehouse,
                        ih.created_date,
                        CASE 
                            WHEN ih.expired_date < CURDATE() THEN 'EXPIRED'
                            WHEN ih.expired_date <= DATE_ADD(CURDATE(), INTERVAL 30 DAY) THEN 'WARNING'
                            ELSE 'OK'
                        END as status
                    FROM inventory_histories ih
                    JOIN warehouses w ON ih.warehouse_id = w.id
                    WHERE ih.product_id = %s
                        AND ih.remain > 0
                        AND ih.delete_flag = 0
                    ORDER BY ih.expired_date ASC, ih.created_date ASC
                """
                
                stock_data = pd.read_sql(query, db_engine, params=(product_id,))
                
                if not stock_data.empty:
                    st.markdown("### Current Inventory")
                    
                    # Summary
                    total_stock = stock_data['quantity'].sum()
                    st.metric("Total Stock", format_number(total_stock, 2))
                    
                    # Details
                    st.dataframe(
                        stock_data,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "batch_no": "Batch",
                            "quantity": st.column_config.NumberColumn("Quantity", format="%.2f"),
                            "expired_date": st.column_config.DateColumn("Expiry"),
                            "warehouse": "Warehouse",
                            "created_date": st.column_config.DateColumn("Created"),
                            "status": "Status"
                        }
                    )
                else:
                    st.info("No stock found for this product")

# ==================== Inventory Impact ====================

elif selected_report == "Inventory Impact":
    st.subheader("📊 Inventory Impact Analysis")
    
    start_date, end_date = get_date_range()
    
    if st.button("Analyze Impact", type="primary", use_container_width=True):
        with st.spinner("Analyzing inventory impact..."):
            
            # Query inventory movements
            query = """
                SELECT 
                    p.name as product_name,
                    p.pt_code as product_code,
                    ih.type as transaction_type,
                    DATE(ih.created_date) as date,
                    SUM(CASE 
                        WHEN ih.type IN ('stockInProduction', 'stockInProductionReturn') 
                        THEN ih.quantity 
                        WHEN ih.type = 'stockOutProduction' 
                        THEN -ih.quantity 
                        ELSE 0 
                    END) as net_quantity,
                    COUNT(DISTINCT ih.batch_no) as batch_count,
                    w.name as warehouse
                FROM inventory_histories ih
                JOIN products p ON ih.product_id = p.id
                JOIN warehouses w ON ih.warehouse_id = w.id
                WHERE ih.type IN ('stockOutProduction', 'stockInProduction', 'stockInProductionReturn')
                    AND DATE(ih.created_date) BETWEEN %s AND %s
                    AND ih.delete_flag = 0
                GROUP BY p.id, p.name, p.pt_code, ih.type, DATE(ih.created_date), w.name
                ORDER BY DATE(ih.created_date) DESC, ABS(net_quantity) DESC
            """
            
            try:
                movements = pd.read_sql(query, db_engine, params=(start_date, end_date))
                
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
                    
                    # Movement by type
                    st.markdown("### Movement by Transaction Type")
                    
                    type_summary = movements.groupby('transaction_type').agg({
                        'net_quantity': lambda x: abs(x.sum()),
                        'batch_count': 'sum'
                    }).reset_index()
                    
                    fig = px.bar(
                        type_summary,
                        x='transaction_type',
                        y='net_quantity',
                        title="Inventory Movement by Type",
                        labels={'net_quantity': 'Total Quantity', 'transaction_type': 'Type'},
                        color='transaction_type',
                        color_discrete_map={
                            'stockOutProduction': '#FF4444',
                            'stockInProduction': '#00CC88',
                            'stockInProductionReturn': '#FFB800'
                        }
                    )
                    st.plotly_chart(fig, use_container_width=True)
                    
                    # Top movers
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.markdown("#### Top Consumed Materials")
                        consumed = movements[movements['net_quantity'] < 0].groupby('product_name').agg({
                            'net_quantity': 'sum'
                        }).reset_index()
                        consumed['net_quantity'] = abs(consumed['net_quantity'])
                        consumed = consumed.nlargest(10, 'net_quantity')
                        
                        if not consumed.empty:
                            fig = px.bar(
                                consumed,
                                x='net_quantity',
                                y='product_name',
                                orientation='h',
                                title="Top 10 Consumed",
                                labels={'net_quantity': 'Quantity', 'product_name': 'Product'}
                            )
                            st.plotly_chart(fig, use_container_width=True)
                    
                    with col2:
                        st.markdown("#### Top Produced Items")
                        produced = movements[movements['net_quantity'] > 0].groupby('product_name').agg({
                            'net_quantity': 'sum'
                        }).reset_index()
                        produced = produced.nlargest(10, 'net_quantity')
                        
                        if not produced.empty:
                            fig = px.bar(
                                produced,
                                x='net_quantity',
                                y='product_name',
                                orientation='h',
                                title="Top 10 Produced",
                                labels={'net_quantity': 'Quantity', 'product_name': 'Product'}
                            )
                            st.plotly_chart(fig, use_container_width=True)
                    
                    # Daily trend
                    st.markdown("### Daily Movement Trend")
                    
                    daily_movement = movements.groupby(['date', 'transaction_type']).agg({
                        'net_quantity': lambda x: abs(x.sum())
                    }).reset_index()
                    
                    fig = px.line(
                        daily_movement,
                        x='date',
                        y='net_quantity',
                        color='transaction_type',
                        title="Daily Inventory Movement",
                        labels={'net_quantity': 'Quantity', 'date': 'Date'}
                    )
                    st.plotly_chart(fig, use_container_width=True)
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
            
            # Query the return analysis view
            query = """
                SELECT * FROM v_material_return_analysis
                WHERE order_id IN (
                    SELECT id FROM manufacturing_orders
                    WHERE order_date BETWEEN %s AND %s
                        AND delete_flag = 0
                )
                ORDER BY return_rate_pct DESC
            """
            
            try:
                returns_data = pd.read_sql(query, db_engine, params=(start_date, end_date))
                
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
                    
                    # Return rate distribution
                    st.markdown("### Return Rate Analysis")
                    
                    # Top materials by return rate
                    top_returns = returns_data[returns_data['return_rate_pct'] > 0].nlargest(15, 'return_rate_pct')
                    
                    if not top_returns.empty:
                        fig = px.bar(
                            top_returns,
                            x='return_rate_pct',
                            y='material_name',
                            orientation='h',
                            title="Top 15 Materials by Return Rate",
                            labels={'return_rate_pct': 'Return Rate %', 'material_name': 'Material'},
                            color='return_rate_pct',
                            color_continuous_scale='RdYlGn_r'
                        )
                        st.plotly_chart(fig, use_container_width=True)
                    
                    # Return condition analysis
                    st.markdown("### Return Condition Analysis")
                    
                    condition_summary = pd.DataFrame({
                        'Condition': ['Good', 'Damaged', 'Expired'],
                        'Quantity': [
                            returns_data['returned_good'].sum(),
                            returns_data['returned_damaged'].sum(),
                            returns_data['returned_expired'].sum()
                        ]
                    })
                    
                    condition_summary = condition_summary[condition_summary['Quantity'] > 0]
                    
                    if not condition_summary.empty:
                        fig = px.pie(
                            condition_summary,
                            values='Quantity',
                            names='Condition',
                            title="Returns by Condition",
                            color_discrete_map={
                                'Good': '#00CC88',
                                'Damaged': '#FFB800',
                                'Expired': '#FF4444'
                            }
                        )
                        st.plotly_chart(fig, use_container_width=True)
                    
                    # Detailed table
                    with st.expander("📋 Detailed Return Data"):
                        display_cols = [
                            'order_no', 'material_name', 'total_issued', 'total_returned',
                            'return_rate_pct', 'return_reasons', 'returned_good',
                            'returned_damaged', 'returned_expired'
                        ]
                        
                        st.dataframe(
                            returns_data[display_cols],
                            use_container_width=True,
                            hide_index=True,
                            column_config={
                                "order_no": "Order",
                                "material_name": "Material",
                                "total_issued": st.column_config.NumberColumn("Issued", format="%.2f"),
                                "total_returned": st.column_config.NumberColumn("Returned", format="%.2f"),
                                "return_rate_pct": st.column_config.NumberColumn("Return %", format="%.1f"),
                                "return_reasons": "Reasons",
                                "returned_good": st.column_config.NumberColumn("Good", format="%.2f"),
                                "returned_damaged": st.column_config.NumberColumn("Damaged", format="%.2f"),
                                "returned_expired": st.column_config.NumberColumn("Expired", format="%.2f")
                            }
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