# pages/3_📊_Reports.py - Production Reports & Analytics
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, date, timedelta
from utils.auth import AuthManager
from modules.production import ProductionManager
from modules.inventory import InventoryManager
import logging

logger = logging.getLogger(__name__)

# Page config
st.set_page_config(
    page_title="Production Reports",
    page_icon="📊",
    layout="wide"
)

# Authentication
auth = AuthManager()
auth.require_auth()

# Initialize managers
prod_manager = ProductionManager()
inv_manager = InventoryManager()

# Page header
st.title("📊 Production Reports & Analytics")

# Report type selection
report_type = st.selectbox(
    "Select Report Type",
    ["Production Summary", "Material Consumption", "Inventory Impact", "Batch Tracking", "Performance Analysis"]
)

st.markdown("---")

if report_type == "Production Summary":
    st.subheader("📈 Production Summary Report")
    
    # Date range selector
    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        start_date = st.date_input("Start Date", value=date.today() - timedelta(days=30))
    with col2:
        end_date = st.date_input("End Date", value=date.today())
    with col3:
        st.markdown("<br>", unsafe_allow_html=True)
        generate = st.button("Generate Report", type="primary", use_container_width=True)
    
    if generate or 'report_generated' in st.session_state:
        st.session_state.report_generated = True
        
        # Get summary data
        summary = prod_manager.get_production_summary(start_date, end_date)
        
        # Key metrics
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric(
                "Total Orders",
                summary['total_orders'],
                delta=f"{summary['vs_previous_period']}% vs prev period"
            )
        with col2:
            st.metric(
                "Completed",
                summary['completed_orders'],
                delta=f"{summary['completion_rate']:.1f}% completion rate"
            )
        with col3:
            st.metric(
                "Total Output",
                f"{summary['total_output']:,.0f}",
                delta="Units produced"
            )
        with col4:
            st.metric(
                "Avg Lead Time",
                f"{summary['avg_lead_time']:.1f} days",
                delta=f"{summary['lead_time_trend']}% trend"
            )
        
        # Charts
        st.markdown("### Production Trends")
        
        # Daily production chart
        daily_data = prod_manager.get_daily_production(start_date, end_date)
        if not daily_data.empty:
            fig = px.line(
                daily_data,
                x='date',
                y='quantity',
                color='bom_type',
                title="Daily Production by Type",
                labels={'quantity': 'Units Produced', 'date': 'Date'}
            )
            st.plotly_chart(fig, use_container_width=True)
        
        # Production by type pie chart
        col1, col2 = st.columns(2)
        with col1:
            type_data = prod_manager.get_production_by_type(start_date, end_date)
            if not type_data.empty:
                fig = px.pie(
                    type_data,
                    values='quantity',
                    names='bom_type',
                    title="Production Distribution by Type"
                )
                st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            # Status distribution
            status_data = prod_manager.get_order_status_distribution(start_date, end_date)
            if not status_data.empty:
                fig = px.bar(
                    status_data,
                    x='status',
                    y='count',
                    title="Order Status Distribution",
                    color='status',
                    color_discrete_map={
                        'COMPLETED': '#00CC88',
                        'IN_PROGRESS': '#FFB800',
                        'CONFIRMED': '#0088FE',
                        'DRAFT': '#888888',
                        'CANCELLED': '#FF4444'
                    }
                )
                st.plotly_chart(fig, use_container_width=True)
        
        # Detailed table
        with st.expander("📋 Detailed Production Orders"):
            orders = prod_manager.get_detailed_orders(start_date, end_date)
            if not orders.empty:
                st.dataframe(
                    orders,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "order_no": "Order No.",
                        "order_date": st.column_config.DateColumn("Date"),
                        "product_name": "Product",
                        "planned_qty": st.column_config.NumberColumn("Planned", format="%d"),
                        "produced_qty": st.column_config.NumberColumn("Produced", format="%d"),
                        "status": "Status",
                        "completion_date": st.column_config.DateColumn("Completed")
                    }
                )
                
                # Export button
                csv = orders.to_csv(index=False)
                st.download_button(
                    label="📥 Download CSV",
                    data=csv,
                    file_name=f"production_orders_{start_date}_{end_date}.csv",
                    mime="text/csv"
                )

elif report_type == "Material Consumption":
    st.subheader("📦 Material Consumption Report")
    
    # Filters
    col1, col2, col3 = st.columns(3)
    with col1:
        start_date = st.date_input("Start Date", value=date.today() - timedelta(days=30))
    with col2:
        end_date = st.date_input("End Date", value=date.today())
    with col3:
        warehouse = st.selectbox("Warehouse", ["All"] + inv_manager.get_warehouse_list())
    
    if st.button("Generate Report", type="primary"):
        # Get consumption data
        consumption = prod_manager.get_material_consumption(
            start_date,
            end_date,
            warehouse_id=None if warehouse == "All" else warehouse
        )
        
        if not consumption.empty:
            # Summary metrics
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Materials Used", len(consumption))
            with col2:
                st.metric("Total Quantity", f"{consumption['total_consumed'].sum():,.0f}")
            with col3:
                st.metric("Unique Products", consumption['product_count'].sum())
            
            # Top consumed materials
            st.markdown("### Top 10 Most Consumed Materials")
            top_materials = consumption.nlargest(10, 'total_consumed')
            
            fig = px.bar(
                top_materials,
                x='material_name',
                y='total_consumed',
                title="Material Consumption",
                labels={'total_consumed': 'Quantity Consumed', 'material_name': 'Material'}
            )
            fig.update_xaxis(tickangle=-45)
            st.plotly_chart(fig, use_container_width=True)
            
            # Consumption trend
            st.markdown("### Daily Consumption Trend")
            daily_consumption = prod_manager.get_daily_material_consumption(start_date, end_date)
            if not daily_consumption.empty:
                fig = px.line(
                    daily_consumption,
                    x='date',
                    y='quantity',
                    title="Daily Material Consumption",
                    labels={'quantity': 'Total Quantity', 'date': 'Date'}
                )
                st.plotly_chart(fig, use_container_width=True)
            
            # Detailed table
            with st.expander("📋 Detailed Consumption Data"):
                st.dataframe(
                    consumption,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "material_name": "Material",
                        "total_consumed": st.column_config.NumberColumn("Total Consumed", format="%.2f"),
                        "uom": "UOM",
                        "product_count": st.column_config.NumberColumn("Used in # Products", format="%d"),
                        "avg_daily": st.column_config.NumberColumn("Avg Daily Usage", format="%.2f")
                    }
                )
        else:
            st.info("No consumption data found for the selected period")

elif report_type == "Inventory Impact":
    st.subheader("📊 Inventory Impact Analysis")
    
    # Date selector
    col1, col2 = st.columns(2)
    with col1:
        analysis_date = st.date_input("Analysis Date", value=date.today())
    with col2:
        comparison_days = st.number_input("Compare Previous Days", min_value=1, max_value=90, value=7)
    
    if st.button("Analyze Impact", type="primary"):
        # Get inventory changes
        impact = inv_manager.get_production_impact(
            analysis_date - timedelta(days=comparison_days),
            analysis_date
        )
        
        if not impact.empty:
            # Summary cards
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric(
                    "Products Affected",
                    len(impact),
                    help="Number of products with inventory changes"
                )
            with col2:
                total_in = impact[impact['net_change'] > 0]['net_change'].sum()
                st.metric(
                    "Total Inbound",
                    f"{total_in:,.0f}",
                    help="Total units added to inventory"
                )
            with col3:
                total_out = abs(impact[impact['net_change'] < 0]['net_change'].sum())
                st.metric(
                    "Total Outbound",
                    f"{total_out:,.0f}",
                    help="Total units consumed from inventory"
                )
            with col4:
                net = impact['net_change'].sum()
                st.metric(
                    "Net Change",
                    f"{net:+,.0f}",
                    delta="Overall inventory change"
                )
            
            # Impact visualization
            st.markdown("### Inventory Movement")
            
            # Separate inbound and outbound
            inbound = impact[impact['net_change'] > 0].nlargest(10, 'net_change')
            outbound = impact[impact['net_change'] < 0].nsmallest(10, 'net_change')
            
            col1, col2 = st.columns(2)
            with col1:
                if not inbound.empty:
                    fig = px.bar(
                        inbound,
                        x='net_change',
                        y='product_name',
                        orientation='h',
                        title="Top 10 Inventory Additions",
                        labels={'net_change': 'Quantity Added', 'product_name': 'Product'},
                        color_discrete_sequence=['#00CC88']
                    )
                    st.plotly_chart(fig, use_container_width=True)
            
            with col2:
                if not outbound.empty:
                    outbound['net_change'] = abs(outbound['net_change'])
                    fig = px.bar(
                        outbound,
                        x='net_change',
                        y='product_name',
                        orientation='h',
                        title="Top 10 Inventory Consumptions",
                        labels={'net_change': 'Quantity Consumed', 'product_name': 'Product'},
                        color_discrete_sequence=['#FF4444']
                    )
                    st.plotly_chart(fig, use_container_width=True)
            
            # Stock level warnings
            st.markdown("### Stock Level Alerts")
            low_stock = inv_manager.get_low_stock_items()
            if not low_stock.empty:
                st.warning(f"⚠️ {len(low_stock)} items are below minimum stock level")
                st.dataframe(
                    low_stock,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "product_name": "Product",
                        "current_stock": st.column_config.NumberColumn("Current Stock", format="%d"),
                        "min_stock": st.column_config.NumberColumn("Min Level", format="%d"),
                        "shortage": st.column_config.NumberColumn("Shortage", format="%d"),
                        "warehouse": "Warehouse"
                    }
                )
        else:
            st.info("No inventory impact data found")

elif report_type == "Batch Tracking":
    st.subheader("🔍 Batch Tracking & Traceability")
    
    # Search options
    search_type = st.radio("Search By", ["Batch Number", "Production Order", "Date Range"], horizontal=True)
    
    if search_type == "Batch Number":
        batch_no = st.text_input("Enter Batch Number", placeholder="e.g., KIT-20250106-001")
        
        if batch_no and st.button("Track Batch", type="primary"):
            # Get batch info
            batch_info = inv_manager.get_batch_info(batch_no)
            
            if batch_info:
                # Batch details
                st.markdown("### Batch Information")
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Product", batch_info['product_name'])
                with col2:
                    st.metric("Quantity", f"{batch_info['quantity']} {batch_info['uom']}")
                with col3:
                    st.metric("Created Date", batch_info['created_date'])
                with col4:
                    st.metric("Expiry Date", batch_info['expiry_date'] or "N/A")
                
                # Source materials
                st.markdown("### Source Materials (Genealogy)")
                sources = inv_manager.get_batch_sources(batch_no)
                if not sources.empty:
                    st.dataframe(
                        sources,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "material_name": "Material",
                            "quantity": st.column_config.NumberColumn("Quantity Used", format="%.2f"),
                            "source_batch": "Source Batch",
                            "expiry_date": st.column_config.DateColumn("Expiry")
                        }
                    )
                
                # Current location
                st.markdown("### Current Inventory Status")
                locations = inv_manager.get_batch_locations(batch_no)
                if not locations.empty:
                    st.dataframe(
                        locations,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "warehouse": "Warehouse",
                            "quantity": st.column_config.NumberColumn("Quantity", format="%.2f"),
                            "status": "Status",
                            "last_updated": st.column_config.DatetimeColumn("Last Updated")
                        }
                    )
            else:
                st.warning("Batch not found")
    
    elif search_type == "Production Order":
        # Get recent production orders
        recent_orders = prod_manager.get_recent_orders(limit=50)
        if not recent_orders.empty:
            order_no = st.selectbox("Select Production Order", recent_orders['order_no'].tolist())
            
            if st.button("View Batches", type="primary"):
                batches = prod_manager.get_order_batches(order_no)
                if not batches.empty:
                    st.dataframe(
                        batches,
                        use_container_width=True,
                        hide_index=True
                    )
                else:
                    st.info("No batches found for this order")
    
    else:  # Date Range
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("Start Date", value=date.today() - timedelta(days=7))
        with col2:
            end_date = st.date_input("End Date", value=date.today())
        
        if st.button("Search Batches", type="primary"):
            batches = inv_manager.get_batches_by_date(start_date, end_date)
            if not batches.empty:
                st.dataframe(
                    batches,
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.info("No batches found in the selected date range")

elif report_type == "Performance Analysis":
    st.subheader("📈 Production Performance Analysis")
    
    # KPI Dashboard
    st.markdown("### Key Performance Indicators")
    
    # Date range
    col1, col2 = st.columns(2)
    with col1:
        kpi_start = st.date_input("Start Date", value=date.today() - timedelta(days=30), key="kpi_start")
    with col2:
        kpi_end = st.date_input("End Date", value=date.today(), key="kpi_end")
    
    if st.button("Calculate KPIs", type="primary"):
        kpis = prod_manager.calculate_kpis(kpi_start, kpi_end)
        
        # Display KPIs
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric(
                "On-Time Delivery",
                f"{kpis['on_time_rate']:.1f}%",
                delta=f"{kpis['otd_trend']:+.1f}% vs prev",
                help="Orders completed by scheduled date"
            )
        with col2:
            st.metric(
                "Production Efficiency",
                f"{kpis['efficiency']:.1f}%",
                delta=f"{kpis['efficiency_trend']:+.1f}% vs prev",
                help="Actual vs planned output"
            )
        with col3:
            st.metric(
                "Quality Rate",
                f"{kpis['quality_rate']:.1f}%",
                delta=f"{kpis['quality_trend']:+.1f}% vs prev",
                help="Products passing quality check"
            )
        with col4:
            st.metric(
                "Utilization Rate",
                f"{kpis['utilization']:.1f}%",
                delta=f"{kpis['utilization_trend']:+.1f}% vs prev",
                help="Production capacity utilization"
            )
        
        # Performance trends
        st.markdown("### Performance Trends")
        
        # Get trend data
        trends = prod_manager.get_performance_trends(kpi_start, kpi_end)
        if not trends.empty:
            fig = go.Figure()
            
            # Add traces for each metric
            fig.add_trace(go.Scatter(
                x=trends['date'],
                y=trends['on_time_rate'],
                mode='lines+markers',
                name='On-Time Delivery %',
                yaxis='y'
            ))
            
            fig.add_trace(go.Scatter(
                x=trends['date'],
                y=trends['efficiency'],
                mode='lines+markers',
                name='Efficiency %',
                yaxis='y'
            ))
            
            fig.add_trace(go.Scatter(
                x=trends['date'],
                y=trends['daily_output'],
                mode='bars',
                name='Daily Output',
                yaxis='y2'
            ))
            
            # Update layout
            fig.update_layout(
                title="Production Performance Trends",
                xaxis_title="Date",
                yaxis=dict(title="Percentage (%)", side="left"),
                yaxis2=dict(title="Units", side="right", overlaying="y"),
                hovermode='x unified',
                height=500
            )
            
            st.plotly_chart(fig, use_container_width=True)
        
        # Efficiency by type
        st.markdown("### Efficiency by Production Type")
        eff_by_type = prod_manager.get_efficiency_by_type(kpi_start, kpi_end)
        if not eff_by_type.empty:
            fig = px.bar(
                eff_by_type,
                x='bom_type',
                y='efficiency',
                title="Production Efficiency by Type",
                labels={'efficiency': 'Efficiency %', 'bom_type': 'Production Type'},
                color='efficiency',
                color_continuous_scale='RdYlGn',
                range_color=[50, 100]
            )
            st.plotly_chart(fig, use_container_width=True)

# Footer with export options
st.markdown("---")
col1, col2, col3 = st.columns([2, 1, 2])
with col2:
    st.markdown(
        """
        <div style='text-align: center; color: #888;'>
        Report generated at: {}<br>
        Manufacturing Module v1.0
        </div>
        """.format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        unsafe_allow_html=True
    )