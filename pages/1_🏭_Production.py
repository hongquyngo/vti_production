# pages/1_🏭_Production.py - Complete Production Management UI
"""
Production Management User Interface
Complete production cycle: Order → Issue → Return → Complete
"""

import streamlit as st
import pandas as pd
from datetime import datetime, date
from typing import Dict, List, Optional, Tuple
import time
import logging

from utils.auth import AuthManager
from modules.production import ProductionManager
from modules.inventory import InventoryManager
from modules.bom import BOMManager
from modules.common import (
    format_number, format_currency, create_status_indicator,
    export_to_excel, get_date_filter_presets, UIHelpers,
    SystemConstants
)

logger = logging.getLogger(__name__)

# ==================== Page Configuration ====================

st.set_page_config(
    page_title="Production Management",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ==================== Authentication ====================

auth = AuthManager()
auth.require_auth()

# ==================== Initialize Managers ====================

@st.cache_resource
def get_managers():
    """Initialize and cache managers"""
    return (
        ProductionManager(),
        InventoryManager(),
        BOMManager()
    )

prod_manager, inv_manager, bom_manager = get_managers()

# ==================== Session State ====================

def initialize_session_state():
    """Initialize session state variables"""
    defaults = {
        'current_view': 'list',
        'selected_order': None,
        'form_data': {},
        'filters': {},
        'page_number': 1
    }
    
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)

def set_view(view: str, order_id: Optional[int] = None):
    """Set current view and optionally selected order"""
    st.session_state.current_view = view
    if order_id is not None:
        st.session_state.selected_order = order_id

initialize_session_state()

# ==================== Header & Navigation ====================

def render_header():
    """Render page header"""
    col1, col2, col3 = st.columns([2, 4, 1])
    with col1:
        st.title("🏭 Production Management")
    with col3:
        if st.button("🔄 Refresh", use_container_width=True):
            st.cache_resource.clear()
            st.rerun()

def render_navigation():
    """Render navigation buttons"""
    nav_items = [
        ("📋 Order List", 'list'),
        ("➕ New Order", 'new'),
        ("📦 Material Issue", 'issue'),
        ("↩️ Material Return", 'return'),
        ("✅ Complete Order", 'complete'),
        ("📊 Dashboard", 'dashboard')
    ]
    
    cols = st.columns(len(nav_items))
    for idx, (label, view) in enumerate(nav_items):
        with cols[idx]:
            is_active = st.session_state.current_view == view
            if st.button(
                label,
                use_container_width=True,
                type="primary" if is_active else "secondary"
            ):
                set_view(view)

# ==================== Order List View ====================

def render_order_list():
    """Render order list view"""
    st.subheader("📋 Production Orders")
    
    # Filters
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        status = st.selectbox(
            "Status",
            ["All", "DRAFT", "CONFIRMED", "IN_PROGRESS", "COMPLETED", "CANCELLED"],
            index=0
        )
    
    with col2:
        order_type = st.selectbox(
            "Type",
            ["All", "KITTING", "CUTTING", "REPACKING"],
            index=0
        )
    
    with col3:
        presets = get_date_filter_presets()
        date_range = st.selectbox(
            "Date Range",
            list(presets.keys()),
            index=4  # This Month
        )
        from_date, to_date = presets[date_range]
    
    with col4:
        priority = st.selectbox(
            "Priority",
            ["All", "LOW", "NORMAL", "HIGH", "URGENT"],
            index=0
        )
    
    # Get orders
    orders = prod_manager.get_orders(
        status=None if status == "All" else status,
        order_type=None if order_type == "All" else order_type,
        from_date=from_date,
        to_date=to_date,
        priority=None if priority == "All" else priority,
        page=st.session_state.page_number
    )
    
    if orders.empty:
        st.info("No production orders found")
        return
    
    # Metrics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Orders", len(orders))
    with col2:
        completed = len(orders[orders['status'] == 'COMPLETED'])
        st.metric("Completed", completed)
    with col3:
        in_progress = len(orders[orders['status'] == 'IN_PROGRESS'])
        st.metric("In Progress", in_progress)
    with col4:
        completion_rate = (completed / len(orders) * 100) if len(orders) > 0 else 0
        st.metric("Completion Rate", f"{completion_rate:.1f}%")
    
    st.markdown("---")
    
    # Display table
    display_df = orders.copy()
    display_df['status'] = display_df['status'].apply(create_status_indicator)
    display_df['priority'] = display_df['priority'].apply(create_status_indicator)
    display_df['progress'] = display_df.apply(
        lambda x: f"{x['produced_qty']}/{x['planned_qty']}", axis=1
    )
    
    columns_to_show = ['order_no', 'order_date', 'bom_type', 'product_name',
                       'progress', 'status', 'priority', 'scheduled_date']
    
    st.dataframe(
        display_df[columns_to_show],
        use_container_width=True,
        hide_index=True
    )
    
    # Quick Actions
    st.markdown("### Quick Actions")
    col1, col2, col3 = st.columns([2, 2, 1])
    
    with col1:
        selected_order = st.selectbox(
            "Select Order",
            orders['order_no'].tolist()
        )
    
    if selected_order:
        order_row = orders[orders['order_no'] == selected_order].iloc[0]
        
        with col2:
            actions = get_available_actions(order_row['status'])
            action = st.selectbox("Action", actions)
        
        with col3:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Execute", type="primary", use_container_width=True):
                execute_action(action, order_row['id'], order_row['status'])

def get_available_actions(status: str) -> List[str]:
    """Get available actions based on status"""
    actions_map = {
        'DRAFT': ["View Details", "Confirm Order", "Issue Materials", "Cancel Order"],
        'CONFIRMED': ["View Details", "Issue Materials", "Cancel Order"],
        'IN_PROGRESS': ["View Details", "Return Materials", "Complete Production", "Cancel Order"],
        'COMPLETED': ["View Details"],
        'CANCELLED': ["View Details"]
    }
    return actions_map.get(status, ["View Details"])

def execute_action(action: str, order_id: int, status: str):
    """Execute selected action"""
    try:
        if action == "View Details":
            set_view('details', order_id)
            st.rerun()
        elif action == "Issue Materials":
            set_view('issue', order_id)
            st.rerun()
        elif action == "Return Materials":
            set_view('return', order_id)
            st.rerun()
        elif action == "Complete Production":
            set_view('complete', order_id)
            st.rerun()
        elif action == "Confirm Order":
            prod_manager.update_order_status(order_id, "CONFIRMED", st.session_state.user_id)
            UIHelpers.show_message("✅ Order confirmed!", "success")
            time.sleep(1)
            st.rerun()
        elif action == "Cancel Order":
            if UIHelpers.confirm_action(f"Cancel order?", f"cancel_{order_id}"):
                prod_manager.update_order_status(order_id, "CANCELLED", st.session_state.user_id)
                UIHelpers.show_message("Order cancelled", "success")
                time.sleep(1)
                st.rerun()
    except Exception as e:
        UIHelpers.show_message(f"Error: {str(e)}", "error")

# ==================== Create Order View ====================

def render_create_order():
    """Render create order form"""
    st.subheader("➕ Create New Production Order")
    
    # BOM Type selection
    prod_type = st.selectbox(
        "Production Type",
        ["KITTING", "CUTTING", "REPACKING"]
    )
    
    # Get BOMs
    boms = bom_manager.get_active_boms(bom_type=prod_type)
    
    if boms.empty:
        st.warning(f"No active BOMs found for {prod_type}")
        return
    
    with st.form("create_order_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            # BOM selection
            bom_options = {
                f"{row['bom_name']} ({row['bom_code']})": row['id']
                for _, row in boms.iterrows()
            }
            
            selected_bom = st.selectbox(
                "Select BOM",
                options=list(bom_options.keys())
            )
            
            bom_id = bom_options[selected_bom]
            
            # Get BOM info
            bom_info = bom_manager.get_bom_info(bom_id)
            if bom_info:
                st.info(f"Output: {bom_info['product_name']} - {bom_info['output_qty']} {bom_info['uom']}")
            
            # Quantity
            qty = st.number_input(
                "Quantity to Produce",
                min_value=1,
                value=1,
                step=1
            )
            
            # Scheduled date
            scheduled_date = st.date_input(
                "Scheduled Date",
                value=date.today(),
                min_value=date.today()
            )
        
        with col2:
            # Warehouses
            warehouses = inv_manager.get_warehouses()
            warehouse_names = warehouses['name'].tolist()
            
            source_warehouse = st.selectbox(
                "Source Warehouse",
                warehouse_names
            )
            
            target_warehouse = st.selectbox(
                "Target Warehouse",
                warehouse_names,
                index=1 if len(warehouse_names) > 1 else 0
            )
            
            # Priority
            priority = st.selectbox(
                "Priority",
                ["LOW", "NORMAL", "HIGH", "URGENT"],
                index=1
            )
            
            # Notes
            notes = st.text_area("Notes", height=100)
        
        # Material preview
        if bom_id and source_warehouse:
            source_id = warehouses[warehouses['name'] == source_warehouse]['id'].iloc[0]
            requirements = prod_manager.calculate_material_requirements(bom_id, qty)
            
            if not requirements.empty:
                st.markdown("### Material Requirements")
                
                # Check availability
                for idx, row in requirements.iterrows():
                    stock = inv_manager.get_stock_balance(row['material_id'], source_id)
                    requirements.loc[idx, 'available'] = stock
                    requirements.loc[idx, 'status'] = '✅' if stock >= row['required_qty'] else '❌'
                
                st.dataframe(
                    requirements[['material_name', 'required_qty', 'available', 'status']],
                    use_container_width=True,
                    hide_index=True
                )
        
        # Submit
        col1, col2, col3 = st.columns([3, 1, 1])
        with col2:
            submitted = st.form_submit_button("Create Order", type="primary", use_container_width=True)
        with col3:
            cancel = st.form_submit_button("Cancel", use_container_width=True)
        
        if submitted:
            try:
                order_data = {
                    'bom_header_id': bom_id,
                    'product_id': bom_info['product_id'],
                    'planned_qty': qty,
                    'uom': bom_info['uom'],
                    'warehouse_id': warehouses[warehouses['name'] == source_warehouse]['id'].iloc[0],
                    'target_warehouse_id': warehouses[warehouses['name'] == target_warehouse]['id'].iloc[0],
                    'scheduled_date': scheduled_date,
                    'priority': priority,
                    'notes': notes,
                    'created_by': st.session_state.user_id
                }
                
                order_no = prod_manager.create_order(order_data)
                UIHelpers.show_message(f"✅ Order {order_no} created successfully!", "success")
                time.sleep(1)
                set_view('list')
                st.rerun()
                
            except Exception as e:
                UIHelpers.show_message(f"Error: {str(e)}", "error")
        
        if cancel:
            set_view('list')
            st.rerun()

# ==================== Material Issue View ====================

def render_material_issue():
    """Render material issue view"""
    st.subheader("📦 Material Issue")
    
    # Get eligible orders
    orders = prod_manager.get_orders(status='DRAFT')
    confirmed = prod_manager.get_orders(status='CONFIRMED')
    
    if not orders.empty and not confirmed.empty:
        all_orders = pd.concat([orders, confirmed])
    elif not orders.empty:
        all_orders = orders
    elif not confirmed.empty:
        all_orders = confirmed
    else:
        st.info("No orders available for material issue")
        return
    
    # Order selection
    order_options = all_orders.apply(
        lambda x: f"{x['order_no']} - {x['product_name']} ({x['status']})",
        axis=1
    ).tolist()
    
    selected = st.selectbox("Select Production Order", order_options)
    
    if selected:
        idx = order_options.index(selected)
        order_id = all_orders.iloc[idx]['id']
        order_info = all_orders.iloc[idx]
        
        # Show order info
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Product", order_info['product_name'])
        with col2:
            st.metric("Quantity", f"{order_info['planned_qty']} {order_info['uom']}")
        with col3:
            st.metric("Type", order_info['bom_type'])
        with col4:
            st.metric("Status", order_info['status'])
        
        # Get materials
        materials = prod_manager.get_order_materials(order_id)
        
        if materials.empty:
            st.warning("No materials found for this order")
            return
        
        st.markdown("### Material Requirements")
        
        # Check availability
        for idx, mat in materials.iterrows():
            stock = inv_manager.get_stock_balance(
                mat['material_id'], 
                all_orders.iloc[0]['warehouse_id']
            )
            materials.loc[idx, 'available'] = stock
            materials.loc[idx, 'status'] = '✅' if stock >= mat['pending_qty'] else '❌'
        
        st.dataframe(
            materials[['material_name', 'required_qty', 'issued_qty', 
                      'pending_qty', 'available', 'status']],
            use_container_width=True,
            hide_index=True
        )
        
        # Issue button
        all_available = not any('❌' in str(s) for s in materials['status'])
        
        if all_available:
            st.success("✅ All materials available")
            if st.button("📤 Issue Materials", type="primary", use_container_width=True):
                try:
                    result = prod_manager.issue_materials(order_id, st.session_state.user_id)
                    UIHelpers.show_message(
                        f"✅ Materials issued! Issue No: {result['issue_no']}", 
                        "success"
                    )
                    
                    # Show details
                    with st.expander("Issue Details", expanded=True):
                        for detail in result['details']:
                            st.write(f"• {detail['material_name']}: {detail['quantity']} {detail['uom']} (Batch: {detail['batch_no']})")
                    
                    time.sleep(2)
                    st.rerun()
                    
                except Exception as e:
                    UIHelpers.show_message(f"Error: {str(e)}", "error")
        else:
            st.error("❌ Insufficient stock for some materials")

# ==================== Material Return View ====================

def render_material_return():
    """Render material return view"""
    st.subheader("↩️ Material Return")
    
    # Get orders with issued materials
    orders = prod_manager.get_orders(status='IN_PROGRESS')
    
    if orders.empty:
        st.info("No orders available for material return")
        return
    
    # Order selection
    order_options = orders.apply(
        lambda x: f"{x['order_no']} - {x['product_name']}",
        axis=1
    ).tolist()
    
    selected = st.selectbox("Select Production Order", order_options)
    
    if selected:
        idx = order_options.index(selected)
        order_id = orders.iloc[idx]['id']
        
        # Get returnable materials
        returnable = prod_manager.get_returnable_materials(order_id)
        
        if returnable.empty:
            st.info("No materials available for return")
            return
        
        st.markdown("### Returnable Materials")
        
        # Create return form
        with st.form("return_form"):
            returns = []
            
            for _, mat in returnable.iterrows():
                st.markdown(f"**{mat['material_name']}** - Batch: {mat['batch_no']}")
                
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    return_qty = st.number_input(
                        "Return Quantity",
                        min_value=0.0,
                        max_value=float(mat['returnable_qty']),
                        value=0.0,
                        key=f"return_{mat['issue_detail_id']}"
                    )
                
                with col2:
                    condition = st.selectbox(
                        "Condition",
                        ["GOOD", "DAMAGED", "EXPIRED"],
                        key=f"condition_{mat['issue_detail_id']}"
                    )
                
                with col3:
                    st.metric("Max Returnable", mat['returnable_qty'])
                
                if return_qty > 0:
                    returns.append({
                        'issue_detail_id': mat['issue_detail_id'],
                        'material_id': mat['material_id'],
                        'batch_no': mat['batch_no'],
                        'quantity': return_qty,
                        'uom': mat['uom'],
                        'condition': condition,
                        'expired_date': mat['expired_date']
                    })
            
            # Reason
            reason = st.selectbox(
                "Return Reason",
                ["EXCESS", "DEFECT", "WRONG_MATERIAL", "PLAN_CHANGE", "OTHER"]
            )
            
            # Submit
            submitted = st.form_submit_button("Process Return", type="primary", use_container_width=True)
            
            if submitted and returns:
                try:
                    result = prod_manager.return_materials(
                        order_id, returns, reason, st.session_state.user_id
                    )
                    UIHelpers.show_message(
                        f"✅ Materials returned! Return No: {result['return_no']}",
                        "success"
                    )
                    time.sleep(2)
                    st.rerun()
                    
                except Exception as e:
                    UIHelpers.show_message(f"Error: {str(e)}", "error")
            elif submitted:
                st.warning("No materials selected for return")

# ==================== Production Completion View ====================

def render_production_completion():
    """Render production completion view"""
    st.subheader("✅ Complete Production")
    
    # Get in-progress orders
    orders = prod_manager.get_orders(status='IN_PROGRESS')
    
    if orders.empty:
        st.info("No orders available for completion")
        return
    
    # Order selection
    order_options = orders.apply(
        lambda x: f"{x['order_no']} - {x['product_name']} ({x['planned_qty']} {x['uom']})",
        axis=1
    ).tolist()
    
    selected = st.selectbox("Select Production Order", order_options)
    
    if selected:
        idx = order_options.index(selected)
        order = orders.iloc[idx]
        
        # Show order info
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Product", order['product_name'])
        with col2:
            st.metric("Planned Quantity", f"{order['planned_qty']} {order['uom']}")
        with col3:
            st.metric("Target Warehouse", order['target_warehouse_name'])
        
        # Completion form
        with st.form("completion_form"):
            col1, col2 = st.columns(2)
            
            with col1:
                produced_qty = st.number_input(
                    "Produced Quantity",
                    min_value=0.0,
                    max_value=float(order['planned_qty']) * 1.1,  # 10% tolerance
                    value=float(order['planned_qty']),
                    step=1.0
                )
                
                batch_no = st.text_input(
                    "Batch Number",
                    value=f"B{datetime.now().strftime('%Y%m%d')}{order['id']:04d}"
                )
                
                expired_date = st.date_input(
                    "Expiry Date (optional)",
                    value=None,
                    min_value=date.today()
                )
            
            with col2:
                quality_status = st.selectbox(
                    "Quality Status",
                    ["PASSED", "FAILED", "PENDING"]
                )
                
                notes = st.text_area(
                    "Production Notes",
                    height=100
                )
            
            # Submit
            col1, col2, col3 = st.columns([3, 1, 1])
            with col2:
                submitted = st.form_submit_button("Complete", type="primary", use_container_width=True)
            with col3:
                cancel = st.form_submit_button("Cancel", use_container_width=True)
            
            if submitted:
                try:
                    result = prod_manager.complete_production(
                        order['id'],
                        produced_qty,
                        batch_no,
                        quality_status,
                        notes,
                        st.session_state.user_id,
                        expired_date
                    )
                    
                    UIHelpers.show_message(
                        f"✅ Production completed! Receipt No: {result['receipt_no']}",
                        "success"
                    )
                    
                    # Show completion details
                    with st.expander("Completion Details", expanded=True):
                        st.write(f"**Receipt No:** {result['receipt_no']}")
                        st.write(f"**Batch No:** {result['batch_no']}")
                        st.write(f"**Quantity:** {result['quantity']} {order['uom']}")
                        st.write(f"**Quality:** {result['quality_status']}")
                    
                    time.sleep(2)
                    st.rerun()
                    
                except Exception as e:
                    UIHelpers.show_message(f"Error: {str(e)}", "error")
            
            if cancel:
                st.rerun()

# ==================== Order Details View ====================

def render_order_details():
    """Render order details view"""
    if not st.session_state.selected_order:
        st.warning("No order selected")
        return
    
    order_id = st.session_state.selected_order
    order = prod_manager.get_order_details(order_id)
    
    if not order:
        st.error("Order not found")
        return
    
    st.subheader(f"Order Details: {order['order_no']}")
    
    # Order info
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Product", order['product_name'])
    with col2:
        st.metric("Status", order['status'])
    with col3:
        st.metric("Progress", f"{order['produced_qty']}/{order['planned_qty']} {order['uom']}")
    with col4:
        st.metric("Priority", order['priority'])
    
    # Additional info
    with st.expander("Order Information", expanded=True):
        col1, col2 = st.columns(2)
        with col1:
            st.write(f"**Order Date:** {order['order_date']}")
            st.write(f"**Scheduled Date:** {order['scheduled_date']}")
            st.write(f"**BOM:** {order['bom_name']}")
        with col2:
            st.write(f"**Type:** {order['bom_type']}")
            st.write(f"**Source:** {order['warehouse_name']}")
            st.write(f"**Target:** {order['target_warehouse_name']}")
    
    # Materials
    st.markdown("### Materials")
    materials = prod_manager.get_order_materials(order_id)
    
    if not materials.empty:
        st.dataframe(
            materials,
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("No materials found")
    
    # Actions
    if st.button("Back to List"):
        set_view('list')
        st.rerun()

# ==================== Dashboard View ====================

def render_dashboard():
    """Render production dashboard"""
    st.subheader("📊 Production Dashboard")
    
    # Date filter
    col1, col2, col3 = st.columns([1, 1, 3])
    with col1:
        from_date = st.date_input("From", value=date.today().replace(day=1))
    with col2:
        to_date = st.date_input("To", value=date.today())
    
    # Get orders for period
    orders = prod_manager.get_orders(from_date=from_date, to_date=to_date)
    
    if orders.empty:
        st.info("No orders found for selected period")
        return
    
    # Overall metrics
    st.markdown("### Overall Performance")
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total Orders", len(orders))
    
    with col2:
        completed = len(orders[orders['status'] == 'COMPLETED'])
        st.metric("Completed", completed)
    
    with col3:
        if completed > 0:
            on_time = len(orders[(orders['status'] == 'COMPLETED') & 
                                (orders['completion_date'] <= orders['scheduled_date'])])
            st.metric("On-Time Rate", f"{(on_time/completed*100):.1f}%")
        else:
            st.metric("On-Time Rate", "N/A")
    
    with col4:
        in_progress = len(orders[orders['status'] == 'IN_PROGRESS'])
        st.metric("In Progress", in_progress)
    
    # Status breakdown
    st.markdown("### Status Breakdown")
    status_counts = orders['status'].value_counts()
    
    col1, col2 = st.columns([1, 2])
    with col1:
        for status, count in status_counts.items():
            st.metric(status, count)
    
    # Type breakdown
    with col2:
        type_counts = orders['bom_type'].value_counts()
        st.markdown("**Production by Type**")
        for prod_type, count in type_counts.items():
            st.write(f"{prod_type}: {count}")
    
    # Priority analysis
    st.markdown("### Priority Analysis")
    priority_status = pd.crosstab(orders['priority'], orders['status'])
    st.dataframe(priority_status, use_container_width=True)
    
    # Export option
    if st.button("📥 Export Data"):
        excel_data = export_to_excel({
            'Orders': orders,
            'Status Summary': status_counts.to_frame(),
            'Type Summary': type_counts.to_frame(),
            'Priority Analysis': priority_status
        })
        
        st.download_button(
            label="Download Excel",
            data=excel_data,
            file_name=f"production_report_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

# ==================== Main Application ====================

def main():
    """Main application entry point"""
    # Render header
    render_header()
    
    # Render navigation
    render_navigation()
    
    st.markdown("---")
    
    # Route to appropriate view
    view_map = {
        'list': render_order_list,
        'new': render_create_order,
        'issue': render_material_issue,
        'return': render_material_return,
        'complete': render_production_completion,
        'details': render_order_details,
        'dashboard': render_dashboard
    }
    
    # Get current view handler
    view_handler = view_map.get(st.session_state.current_view, render_order_list)
    
    try:
        view_handler()
    except Exception as e:
        st.error(f"An error occurred: {str(e)}")
        logger.error(f"View rendering error: {e}", exc_info=True)
    
    # Footer
    st.markdown("---")
    st.caption("Manufacturing Module v2.0 - Production Management")


if __name__ == "__main__":
    main()