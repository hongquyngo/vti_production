# pages/2___Production.py
"""
Production Management User Interface - REFACTORED v7.0
Complete production cycle: Order → Issue → Return → Complete
WITH TAB-BASED UI AND INTEGRATED HISTORY/RECEIPTS

IMPROVEMENTS v7.0 (UI/UX Refactor):
- ✅ NEW: Tab-based navigation (4 main tabs)
- ✅ NEW: Sub-tabs for Issue/Return/Completion
- ✅ NEW: Integrated Issue History in Material Issue tab
- ✅ NEW: Integrated Return History in Material Return tab
- ✅ NEW: Integrated Receipts List in Completion tab
- ✅ REMOVED: Separate Production Receipts page navigation
- ✅ MAINTAINED: All v6.0 functionality including audit fields

Previous versions:
v6.0: Inventory tracking fix with keycloak_id
v5.0: PDF Dialog Integration Fix
v4.0: Enhanced alternative materials display
v3.0: Streamlined UI, Production Receipts navigation
"""
import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta
import time 
from typing import Dict, List, Optional
import logging

# Production domain imports
from utils.auth import AuthManager
from utils.db import get_db_engine
from utils.production.manager import ProductionManager
from utils.production.inventory import InventoryManager
from utils.production.receipts import ProductionReceiptManager  # NEW v7.0
from utils.production.pdf_ui import PDFExportDialog, QuickPDFButton
from utils.production.pdf_generator import pdf_generator
from utils.production.materials import (
    issue_materials,
    return_materials,
    complete_production,
    get_returnable_materials
)
from utils.production.common import (
    format_number,
    create_status_indicator,
    export_to_excel,
    get_date_filter_presets,
    calculate_percentage,
    UIHelpers,
    SystemConstants,
    get_vietnam_today,
    get_vietnam_now,
    validate_positive_number,
    validate_required_fields
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
    return ProductionManager(), InventoryManager()

@st.cache_resource
def get_receipt_manager():
    """Initialize and cache receipt manager"""
    return ProductionReceiptManager()

prod_manager, inv_manager = get_managers()
receipt_manager = get_receipt_manager()

# ==================== Production Output Manager ====================

class ProductionOutputManager:
    """Manager for production output/receipts queries"""
    
    def __init__(self):
        self.engine = get_db_engine()
    
    def get_order_receipts(self, order_id: int) -> pd.DataFrame:
        """Get all production receipts for an order"""
        query = """
            SELECT 
                pr.id,
                pr.receipt_no,
                DATE(pr.receipt_date) as receipt_date,
                pr.quantity,
                pr.uom,
                pr.batch_no,
                DATE(pr.expired_date) as expired_date,
                pr.quality_status,
                pr.notes,
                w.name as warehouse_name,
                ROUND((pr.quantity / mo.planned_qty * 100), 1) as yield_rate
            FROM production_receipts pr
            JOIN manufacturing_orders mo ON pr.manufacturing_order_id = mo.id
            JOIN warehouses w ON pr.warehouse_id = w.id
            WHERE mo.id = %s
            ORDER BY pr.receipt_date DESC
        """
        
        try:
            return pd.read_sql(query, self.engine, params=(order_id,))
        except Exception as e:
            logger.error(f"Error getting order receipts: {e}")
            return pd.DataFrame()
    
    def get_order_output_summary(self, order_id: int) -> Optional[Dict]:
        """Get summary of production output for an order"""
        query = """
            SELECT 
                mo.planned_qty,
                mo.produced_qty,
                mo.uom,
                COALESCE(SUM(pr.quantity), 0) as total_receipts,
                COUNT(pr.id) as receipt_count,
                ROUND((COALESCE(SUM(pr.quantity), 0) / mo.planned_qty * 100), 1) as yield_rate,
                (mo.planned_qty - COALESCE(SUM(pr.quantity), 0)) as shortfall,
                SUM(CASE WHEN pr.quality_status = 'PASSED' THEN pr.quantity ELSE 0 END) as passed_qty,
                SUM(CASE WHEN pr.quality_status = 'PENDING' THEN pr.quantity ELSE 0 END) as pending_qty,
                SUM(CASE WHEN pr.quality_status = 'FAILED' THEN pr.quantity ELSE 0 END) as failed_qty
            FROM manufacturing_orders mo
            LEFT JOIN production_receipts pr ON mo.id = pr.manufacturing_order_id
            WHERE mo.id = %s
            GROUP BY mo.id, mo.planned_qty, mo.produced_qty, mo.uom
        """
        
        try:
            result = pd.read_sql(query, self.engine, params=(order_id,))
            return result.iloc[0].to_dict() if not result.empty else None
        except Exception as e:
            logger.error(f"Error getting output summary: {e}")
            return None

@st.cache_resource
def get_output_manager():
    """Initialize and cache output manager"""
    return ProductionOutputManager()

output_manager = get_output_manager()

# ==================== Session State ====================

def initialize_session_state():
    """Initialize session state variables"""
    defaults = {
        'current_view': 'list',
        'selected_order': None,
        'page_number': 1,
    }
    
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)

def set_view(view: str, order_id: Optional[int] = None):
    """Set current view and optionally selected order"""
    st.session_state.current_view = view
    if order_id is not None:
        st.session_state.selected_order = order_id

# ==================== Dialog Functions ====================

@st.dialog("✅ Confirm Production Order", width="medium")
def show_confirm_order_dialog(order_id: int, order_no: str):
    """Dialog to confirm a DRAFT order"""
    st.markdown(f"""
    ### Confirm Order: **{order_no}**
    
    Thao tác này sẽ thay đổi trạng thái order từ **DRAFT** sang **CONFIRMED**.
    
    ⚠️ **Lưu ý:**
    - Sau khi confirm, order không thể chuyển lại về DRAFT
    - Materials có thể được issued sau khi confirm
    - Kiểm tra kỹ thông tin order trước khi confirm
    """)
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("✅ Confirm Order", type="primary", use_container_width=True):
            try:
                user_id = st.session_state.get('user_id', 1)
                success = prod_manager.update_order_status(order_id, 'CONFIRMED', user_id)
                
                if success:
                    st.success(f"✅ Order {order_no} confirmed successfully!")
                    logger.info(f"User {user_id} confirmed order {order_id} ({order_no})")
                    time.sleep(1.5)
                    st.cache_resource.clear()
                    st.rerun()
                else:
                    st.error("❌ Failed to confirm order")
                    
            except ValueError as e:
                st.error(f"❌ Validation error: {str(e)}")
            except Exception as e:
                st.error(f"❌ System error: {str(e)}")
                logger.error(f"System error confirming order {order_id}: {e}", exc_info=True)
    
    with col2:
        if st.button("❌ Cancel", use_container_width=True):
            st.rerun()

@st.dialog("Edit Production Order", width="large")
def show_edit_order_dialog(order_id: int, order: dict):
    """Dialog to edit a DRAFT or CONFIRMED order"""
    st.markdown(f"### Edit Order: **{order['order_no']}**")
    
    warehouses = inv_manager.get_warehouses()
    if warehouses.empty:
        st.error("No warehouses available")
        return
    
    warehouse_options = {row['name']: row['id'] for _, row in warehouses.iterrows()}
    warehouse_id_to_name = {row['id']: row['name'] for _, row in warehouses.iterrows()}
    
    col1, col2 = st.columns(2)
    
    with col1:
        new_planned_qty = st.number_input(
            "Planned Quantity",
            min_value=0.01,
            value=float(order['planned_qty']),
            step=1.0,
            format="%.2f"
        )
        
        current_date = order['scheduled_date']
        if isinstance(current_date, str):
            current_date = datetime.strptime(current_date, '%Y-%m-%d').date()
        
        new_scheduled_date = st.date_input("Scheduled Date", value=current_date)
        
        priority_options = ["LOW", "NORMAL", "HIGH", "URGENT"]
        current_priority_idx = priority_options.index(order['priority']) if order['priority'] in priority_options else 1
        new_priority = st.selectbox("Priority", priority_options, index=current_priority_idx)
    
    with col2:
        current_source = warehouse_id_to_name.get(order['warehouse_id'], list(warehouse_options.keys())[0])
        new_source_warehouse = st.selectbox(
            "Source Warehouse",
            options=list(warehouse_options.keys()),
            index=list(warehouse_options.keys()).index(current_source) if current_source in warehouse_options else 0
        )
        new_source_warehouse_id = warehouse_options[new_source_warehouse]
        
        current_target = warehouse_id_to_name.get(order['target_warehouse_id'], list(warehouse_options.keys())[0])
        new_target_warehouse = st.selectbox(
            "Target Warehouse",
            options=list(warehouse_options.keys()),
            index=list(warehouse_options.keys()).index(current_target) if current_target in warehouse_options else 0
        )
        new_target_warehouse_id = warehouse_options[new_target_warehouse]
        
        new_notes = st.text_area("Notes", value=order.get('notes', '') or '', height=100)
    
    if new_planned_qty != float(order['planned_qty']):
        st.warning("⚠️ Changing planned quantity will recalculate all required materials.")
    
    st.markdown("---")
    
    col_cancel, col_save = st.columns(2)
    
    with col_cancel:
        if st.button("❌ Cancel", use_container_width=True):
            st.rerun()
    
    with col_save:
        if st.button("💾 Save Changes", type="primary", use_container_width=True):
            try:
                update_data = {}
                
                if new_planned_qty != float(order['planned_qty']):
                    update_data['planned_qty'] = new_planned_qty
                if new_scheduled_date != current_date:
                    update_data['scheduled_date'] = new_scheduled_date
                if new_priority != order['priority']:
                    update_data['priority'] = new_priority
                if new_source_warehouse_id != order['warehouse_id']:
                    update_data['warehouse_id'] = new_source_warehouse_id
                if new_target_warehouse_id != order['target_warehouse_id']:
                    update_data['target_warehouse_id'] = new_target_warehouse_id
                if new_notes != (order.get('notes', '') or ''):
                    update_data['notes'] = new_notes
                
                if not update_data:
                    st.info("No changes detected")
                    return
                
                audit_info = get_user_audit_info()
                success = prod_manager.update_order(order_id, update_data, audit_info.get('user_id'))
                
                if success:
                    st.success(f"✅ Order {order['order_no']} updated successfully!")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("Failed to update order")
                    
            except Exception as e:
                logger.error(f"Error updating order: {e}")
                st.error(f"❌ Error updating order: {str(e)}")

# ==================== Helper Functions ====================

def get_user_audit_info() -> Dict[str, any]:
    """Get user audit information for database operations"""
    user_id = st.session_state.get('user_id', 1)
    keycloak_id = st.session_state.get('user_keycloak_id')
    
    if not keycloak_id:
        logger.warning("⚠️ keycloak_id not found in session state - using fallback")
        keycloak_id = str(user_id)
    
    return {'user_id': user_id, 'keycloak_id': keycloak_id}

def format_material_display_with_details(row) -> str:
    """Format material display with PT code and package size"""
    name = row.get('material_name', 'Unknown')
    pt_code = row.get('pt_code', 'N/A')
    package_size = row.get('package_size', '')
    
    display = f"**{name}**"
    if pt_code and pt_code != 'N/A':
        display += f" | PT: {pt_code}"
    if package_size and package_size != '':
        display += f" | Pack: {package_size}"
    
    return display

# ==================== Header ====================

def render_header():
    """Render page header"""
    col1, col2, col3 = st.columns([2, 4, 1])
    with col1:
        st.title("🏭 Production Management")
    with col3:
        if st.button("🔄 Refresh", key="refresh_main", use_container_width=True):
            st.cache_resource.clear()
            st.rerun()

# ==================== NEW v7.0: Tab-Based Navigation ====================

def render_navigation():
    """Render tab-based navigation - NEW v7.0"""
    if st.session_state.current_view == 'details' and st.session_state.selected_order:
        render_order_details()
        return
    
    tab_labels = ["📋 Orders", "📦 Material Issue", "↩️ Material Return", "✅ Completion"]
    tabs = st.tabs(tab_labels)
    
    with tabs[0]:
        render_orders_tab()
    with tabs[1]:
        render_material_issue_tab()
    with tabs[2]:
        render_material_return_tab()
    with tabs[3]:
        render_completion_tab()

def render_orders_tab():
    """Render Orders tab with list and create sub-tabs"""
    sub_tab1, sub_tab2 = st.tabs(["📋 Order List", "➕ Create Order"])
    with sub_tab1:
        render_order_list()
    with sub_tab2:
        render_create_order()

def render_material_issue_tab():
    """Render Material Issue tab with form and history sub-tabs"""
    sub_tab1, sub_tab2 = st.tabs(["📦 Issue Materials", "📜 Issue History"])
    with sub_tab1:
        render_material_issue_form()
    with sub_tab2:
        render_issue_history()

def render_material_return_tab():
    """Render Material Return tab with form and history sub-tabs"""
    sub_tab1, sub_tab2 = st.tabs(["↩️ Return Materials", "📜 Return History"])
    with sub_tab1:
        render_material_return_form()
    with sub_tab2:
        render_return_history()

def render_completion_tab():
    """Render Completion tab with form and receipts sub-tabs"""
    sub_tab1, sub_tab2 = st.tabs(["✅ Complete Order", "📦 Receipts"])
    with sub_tab1:
        render_production_completion_form()
    with sub_tab2:
        render_receipts_list()

# ==================== Order List View ====================

def render_order_list():
    """Render production orders list with dynamic filters"""
    st.subheader("📋 Production Orders")
    
    filter_options = prod_manager.get_filter_options()
    default_to = get_vietnam_today()
    default_from = (default_to.replace(day=1) - timedelta(days=1)).replace(day=1)
    
    with st.expander("🔍 Filters", expanded=False):
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            status_filter = st.selectbox("Status", filter_options['statuses'], index=0)
        with col2:
            type_filter = st.selectbox("Order Type", filter_options['order_types'], index=0)
        with col3:
            priority_filter = st.selectbox("Priority", filter_options['priorities'], index=0)
        with col4:
            st.markdown("**Date Range**")
            date_col1, date_col2 = st.columns(2)
            with date_col1:
                from_date = st.date_input("From", value=default_from, key="filter_from_date")
            with date_col2:
                to_date = st.date_input("To", value=default_to, key="filter_to_date")
    
    status = status_filter if status_filter != "All" else None
    order_type = type_filter if type_filter != "All" else None
    priority = priority_filter if priority_filter != "All" else None
    
    page_size = 20
    page = st.session_state.page_number
    
    orders = prod_manager.get_orders(
        status=status, order_type=order_type, priority=priority,
        from_date=from_date, to_date=to_date, page=page, page_size=page_size
    )
    
    if orders.empty:
        st.info("No orders found matching the filters")
        return
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Orders", len(orders))
    with col2:
        in_progress = len(orders[orders['status'] == 'IN_PROGRESS'])
        st.metric("In Progress", in_progress)
    with col3:
        urgent = len(orders[orders['priority'] == 'URGENT'])
        st.metric("Urgent", urgent, delta_color="inverse" if urgent > 0 else "off")
    with col4:
        completion_rate = calculate_percentage(len(orders[orders['status'] == 'COMPLETED']), len(orders))
        st.metric("Completion Rate", f"{completion_rate}%")
    
    display_df = orders.copy()
    display_df['status'] = display_df['status'].apply(create_status_indicator)
    display_df['priority'] = display_df['priority'].apply(create_status_indicator)
    display_df['progress'] = display_df.apply(
        lambda x: f"{format_number(x['produced_qty'], 1)}/{format_number(x['planned_qty'], 1)} {x['uom']}", axis=1
    )
    display_df['product_display'] = display_df.apply(
        lambda x: f"{x['pt_code']} | {x['product_name']} | {x['package_size'] or ''}", axis=1
    )
    
    display_columns = {
        'order_no': 'Order No', 'product_display': 'Product', 'progress': 'Progress',
        'status': 'Status', 'priority': 'Priority', 'scheduled_date': 'Scheduled',
        'warehouse_name': 'Source', 'target_warehouse_name': 'Target'
    }
    
    st.dataframe(
        display_df[list(display_columns.keys())].rename(columns=display_columns),
        use_container_width=True, hide_index=True
    )
    
    st.markdown("### Actions")
    order_dict = {
        f"{row['order_no']} ({row['status']}) | {row['pt_code']} | {row['product_name']}": row['id'] 
        for _, row in orders.iterrows()
    }
    
    col1, col2 = st.columns([3, 1])
    with col1:
        selected_order = st.selectbox("Select Order for Action", options=list(order_dict.keys()), key="order_action_select")
    with col2:
        if selected_order:
            if st.button("👁️ View Details", use_container_width=True):
                set_view('details', order_dict[selected_order])
                st.rerun()
    
    st.markdown("---")
    col1, col2, col3 = st.columns([1, 2, 1])
    with col1:
        if st.button("⬅️ Previous", disabled=page <= 1):
            st.session_state.page_number = max(1, page - 1)
            st.rerun()
    with col2:
        st.write(f"Page {page}")
    with col3:
        if st.button("Next ➡️", disabled=len(orders) < page_size):
            st.session_state.page_number = page + 1
            st.rerun()

# ==================== Order Details View ====================

def render_order_details():
    """Render detailed view of a single order"""
    order_id = st.session_state.get('selected_order')
    
    if not order_id:
        st.warning("No order selected")
        if st.button("← Back to List", key="back_no_order"):
            set_view('list')
            st.rerun()
        return
    
    order = prod_manager.get_order_details(order_id)
    
    if not order:
        st.error("Order not found")
        if st.button("← Back to List", key="back_order_not_found"):
            set_view('list')
            st.rerun()
        return
    
    col1, col2, col3 = st.columns([4, 1, 1])
    with col1:
        st.subheader(f"📋 Order Details: {order['order_no']}")
    with col2:
        if order['status'] == 'DRAFT':
            if st.button("✅ Confirm", type="primary", use_container_width=True):
                show_confirm_order_dialog(order_id, order['order_no'])
    with col3:
        if st.button("🔄 Refresh", use_container_width=True):
            st.cache_resource.clear()
            st.rerun()
    
    status_messages = {
        'DRAFT': '⚠️ The order is currently in DRAFT status. Click "✅ Confirm" to confirm the order.',
        'CONFIRMED': '✅ The order has been confirmed and is ready for material issuing.',
        'IN_PROGRESS': '🔄 Materials have been issued. Production is in progress.',
        'COMPLETED': '✅ Production has been completed.',
        'CANCELLED': '❌ The order has been cancelled.'
    }
    
    status_msg = status_messages.get(order['status'], f"Status: {order['status']}")
    
    if order['status'] == 'DRAFT':
        st.info(status_msg)
    elif order['status'] in ['CONFIRMED', 'COMPLETED']:
        st.success(status_msg)
    elif order['status'] == 'IN_PROGRESS':
        st.info(status_msg)
    elif order['status'] == 'CANCELLED':
        st.warning(status_msg)
    
    st.markdown("---")
    
    tabs = st.tabs(["📄 Order Info", "📦 Materials", "🏭 Production Output", "📜 History"])
    
    with tabs[0]:
        col1, col2 = st.columns(2)
        with col1:
            st.write(f"**Order Date:** {order['order_date']}")
            st.write(f"**Scheduled Date:** {order['scheduled_date']}")
            st.write(f"**BOM:** {order['bom_name']}")
            st.write(f"**Type:** {order['bom_type']}")
            st.write(f"**Planned Qty:** {order['planned_qty']} {order['uom']}")
            st.write(f"**Produced:** {order.get('produced_qty', 0)} {order['uom']}")
        with col2:
            st.write(f"**Source Warehouse:** {order['warehouse_name']}")
            st.write(f"**Target Warehouse:** {order['target_warehouse_name']}")
            st.write(f"**Priority:** {create_status_indicator(order['priority'])}")
            st.write(f"**Status:** {create_status_indicator(order['status'])}")
            if order.get('completion_date'):
                st.write(f"**Completed:** {order['completion_date']}")
        
        progress = calculate_percentage(order.get('produced_qty', 0), order['planned_qty'])
        st.progress(progress / 100)
        st.caption(f"{progress}% Complete")
        
        if order.get('notes'):
            st.markdown("---")
            st.markdown("### Notes")
            st.text(order.get('notes'))
        
        st.markdown("---")
        st.markdown("### Quick Actions")
        
        action_cols = st.columns(5)
        
        with action_cols[0]:
            if order['status'] in ['DRAFT', 'CONFIRMED']:
                if st.button("✏️ Edit Order", key="detail_edit_order", use_container_width=True):
                    show_edit_order_dialog(order_id, order)
        
        with action_cols[1]:
            if order['status'] in ['DRAFT', 'CONFIRMED']:
                if st.button("📦 Issue Materials", key="detail_issue_materials", use_container_width=True):
                    st.info("Please use the Material Issue tab")
        
        with action_cols[2]:
            if order['status'] == 'IN_PROGRESS':
                if st.button("↩️ Return Materials", key="detail_return_materials", use_container_width=True):
                    st.info("Please use the Material Return tab")
        
        with action_cols[3]:
            if order['status'] == 'IN_PROGRESS':
                if st.button("✅ Complete Order", key="detail_complete_order", use_container_width=True):
                    st.info("Please use the Completion tab")
        
        with action_cols[4]:
            if st.button("← Back to List", key="back_from_actions", use_container_width=True):
                set_view('list')
                st.rerun()
    
    with tabs[1]:
        st.markdown("### Required Materials")
        materials = prod_manager.get_order_materials(order_id)
        
        if not materials.empty:
            try:
                availability = inv_manager.check_material_availability(
                    order['bom_header_id'], order['planned_qty'], order['warehouse_id']
                )
                
                if not availability.empty:
                    display_df = availability.copy()
                    display_df['material_info'] = display_df.apply(format_material_display_with_details, axis=1)
                    display_df['required_display'] = display_df['required_qty'].apply(lambda x: f"{x:.2f}")
                    display_df['available_display'] = display_df['available_qty'].apply(lambda x: f"{x:.2f}")
                    display_df['status_display'] = display_df['availability_status'].apply(create_status_indicator)
                    
                    st.dataframe(
                        display_df[['material_info', 'required_display', 'available_display', 'status_display', 'uom']].rename(columns={
                            'material_info': 'Material Info', 'required_display': 'Required',
                            'available_display': 'Available', 'status_display': 'Status', 'uom': 'UOM'
                        }),
                        use_container_width=True, hide_index=True
                    )
                else:
                    st.dataframe(materials, use_container_width=True, hide_index=True)
            except Exception as e:
                logger.warning(f"Could not get enhanced material display: {e}")
                st.dataframe(materials, use_container_width=True, hide_index=True)
        else:
            st.info("No materials found")
    
    with tabs[2]:
        render_production_output_tab(order_id, order)
    
    with tabs[3]:
        st.info("Order history tracking (to be implemented)")
    
    st.markdown("---")
    if st.button("← Back to List", key="back_from_details", use_container_width=True):
        set_view('list')
        st.rerun()

# ==================== Create Order View ====================

def render_create_order():
    """Render new production order creation form"""
    st.subheader("➕ Create New Production Order")
    
    st.markdown("### Select BOM")
    bom_list = prod_manager.get_active_boms()
    
    if bom_list.empty:
        st.error("No BOMs available")
        return
    
    bom_options = {
        f"{row['bom_name']} ({row['product_name']}) - {row['bom_type']}": row['id']
        for _, row in bom_list.iterrows()
    }
    
    selected_bom = st.selectbox("BOM", options=list(bom_options.keys()))
    selected_bom_id = bom_options[selected_bom]
    selected_bom_details = prod_manager.get_bom_info(selected_bom_id)
    
    if not selected_bom_details:
        st.error("BOM details not found")
        return
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.info(f"**Product:** {selected_bom_details['product_name']}")
    with col2:
        st.info(f"**Type:** {selected_bom_details['bom_type']}")
    with col3:
        st.info(f"**Output:** {selected_bom_details['output_qty']} {selected_bom_details['uom']}")
    
    st.markdown("---")
    st.markdown("### Order Details")
    
    col1, col2 = st.columns(2)
    
    with col1:
        planned_qty = st.number_input(
            "Planned Quantity", min_value=0.01,
            value=float(selected_bom_details.get('output_qty', 1)), step=1.0, format="%.2f"
        )
        scheduled_date = st.date_input(
            "Scheduled Date", value=get_vietnam_today()
        )
        priority = st.selectbox("Priority", ["LOW", "NORMAL", "HIGH", "URGENT"], index=1)
    
    with col2:
        warehouses = inv_manager.get_warehouses()
        if warehouses.empty:
            st.error("No warehouses available")
            return
        
        warehouse_options = {row['name']: row['id'] for _, row in warehouses.iterrows()}
        
        source_warehouse = st.selectbox("Source Warehouse", options=list(warehouse_options.keys()))
        source_warehouse_id = warehouse_options[source_warehouse]
        
        target_warehouse = st.selectbox(
            "Target Warehouse", options=list(warehouse_options.keys()),
            index=0 if len(warehouse_options) == 1 else 1
        )
        target_warehouse_id = warehouse_options[target_warehouse]
        
        notes = st.text_area("Notes", height=100)
    
    st.markdown("---")
    st.markdown("### Material Availability Check")
    
    with st.spinner("Checking material availability..."):
        availability = inv_manager.check_material_availability(selected_bom_id, planned_qty, source_warehouse_id)
    
    if not availability.empty:
        total = len(availability)
        sufficient = len(availability[availability['availability_status'] == 'SUFFICIENT'])
        partial = len(availability[availability['availability_status'] == 'PARTIAL'])
        insufficient = len(availability[availability['availability_status'] == 'INSUFFICIENT'])
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Materials", total)
        with col2:
            st.metric("✅ Sufficient", sufficient)
        with col3:
            st.metric("⚠️ Partial", partial)
        with col4:
            st.metric("❌ Insufficient", insufficient)
        
        with st.expander("View Material Details", expanded=False):
            def color_status(status):
                return {'SUFFICIENT': '🟢', 'PARTIAL': '🟡', 'INSUFFICIENT': '🔴'}.get(status, '⚪') + f" {status}"
            
            display_df = availability.copy()
            display_df['material_info'] = display_df.apply(format_material_display_with_details, axis=1)
            display_df['availability_status'] = display_df['availability_status'].apply(color_status)
            
            st.dataframe(
                display_df[['material_info', 'required_qty', 'available_qty', 'availability_status', 'uom']].rename(columns={
                    'material_info': 'Material', 'required_qty': 'Required',
                    'available_qty': 'Available', 'availability_status': 'Status', 'uom': 'UOM'
                }),
                use_container_width=True, hide_index=True
            )
    
    st.markdown("---")
    
    col_btn1, col_btn2 = st.columns(2)
    
    with col_btn1:
        if st.button("✅ Create Order", key="create_order_submit", type="primary", use_container_width=True):
            order_data = {
                'bom_header_id': selected_bom_id,
                'product_id': selected_bom_details.get('product_id'),
                'planned_qty': planned_qty,
                'uom': selected_bom_details.get('uom'),
                'warehouse_id': source_warehouse_id,
                'target_warehouse_id': target_warehouse_id,
                'scheduled_date': scheduled_date,
                'priority': priority,
                'notes': notes,
                'created_by': st.session_state.get('user_id', 1)
            }
            
            from utils.production.common import FormValidator
            is_valid, error_msg = FormValidator.validate_create_order(order_data)
            
            if not is_valid:
                st.error(f"❌ Validation Error: {error_msg}")
                return
            
            try:
                with st.spinner("Creating order..."):
                    order_no = prod_manager.create_order(order_data)
                
                st.success(f"✅ Order **{order_no}** created!")
                st.balloons()
                prod_manager.clear_bom_cache()
                time.sleep(2)
                st.rerun()
                
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")
                logger.error(f"Order creation failed: {e}", exc_info=True)
    
    with col_btn2:
        if st.button("❌ Cancel", key="cancel_create_order", use_container_width=True):
            st.rerun()

# ==================== Material Issue Form ====================

def render_material_issue_form():
    """Render material issue form with adjustable quantities - REFACTORED v8.0"""
    st.subheader("📦 Issue Materials to Production")
    
    orders = prod_manager.get_orders(status='CONFIRMED')
    
    if orders.empty:
        st.info("No confirmed orders available for material issue")
        return
    
    order_options = {
        f"{row['order_no']} - {row['product_name']} ({row['planned_qty']} {row['uom']})": row['id']
        for _, row in orders.iterrows()
    }
    
    selected_option = st.selectbox("Select Production Order", options=list(order_options.keys()), key="issue_order_select")
    
    if selected_option:
        order_id = order_options[selected_option]
        order = prod_manager.get_order_details(order_id)
        
        st.markdown("### 📋 Order Information")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Order No", order['order_no'])
        with col2:
            st.metric("Product", order['product_name'])
        with col3:
            st.metric("Quantity", f"{order['planned_qty']} {order['uom']}")
        with col4:
            st.metric("Status", create_status_indicator(order['status']))
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.write(f"**Source:** {order['warehouse_name']}")
        with col2:
            st.write(f"**Target:** {order['target_warehouse_name']}")
        with col3:
            st.write(f"**BOM:** {order['bom_name']}")
        with col4:
            st.write(f"**Priority:** {create_status_indicator(order['priority'])}")
        
        st.markdown("---")
        st.markdown("### 📊 Material Requirements & Issue Quantities")
        st.caption("💡 System calculates suggested quantities. You can adjust issue amounts (usually issue more to ensure sufficient materials).")
        
        with st.spinner("Checking material availability..."):
            availability = inv_manager.check_material_availability(
                order['bom_header_id'], order['planned_qty'], order['warehouse_id']
            )
        
        if not availability.empty:
            total_materials = len(availability)
            sufficient = len(availability[availability['availability_status'] == 'SUFFICIENT'])
            partial = len(availability[availability['availability_status'] == 'PARTIAL'])
            insufficient = len(availability[availability['availability_status'] == 'INSUFFICIENT'])
            
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Total Materials", total_materials)
            with col2:
                st.metric("✅ Sufficient", sufficient)
            with col3:
                st.metric("⚠️ Partial", partial)
            with col4:
                st.metric("❌ Insufficient", insufficient)
            
            # Initialize session state for issue quantities if not exists
            if 'issue_quantities' not in st.session_state or st.session_state.get('issue_order_id') != order_id:
                st.session_state['issue_quantities'] = {}
                st.session_state['issue_order_id'] = order_id
                for _, row in availability.iterrows():
                    material_id = row['material_id']
                    # Default to required_qty, but capped at available_qty
                    suggested = min(float(row['required_qty']), float(row['available_qty']))
                    st.session_state['issue_quantities'][material_id] = suggested
            
            st.markdown("---")
            st.markdown("### 📝 Adjust Issue Quantities")
            
            # Create editable form for each material
            issue_valid = True
            warnings = []
            errors = []
            
            for idx, row in availability.iterrows():
                material_id = row['material_id']
                material_name = row['material_name']
                pt_code = row.get('pt_code', 'N/A')
                required_qty = float(row['required_qty'])
                available_qty = float(row['available_qty'])
                uom = row['uom']
                status = row['availability_status']
                
                # Status indicator
                if status == 'SUFFICIENT':
                    status_icon = "✅"
                elif status == 'PARTIAL':
                    status_icon = "⚠️"
                else:
                    status_icon = "❌"
                
                col1, col2, col3, col4, col5 = st.columns([3, 1.5, 1.5, 2, 1])
                
                with col1:
                    st.write(f"**{material_name}**")
                    st.caption(f"PT Code: {pt_code}")
                
                with col2:
                    st.write(f"Required: **{format_number(required_qty, 4)}**")
                    st.caption(uom)
                
                with col3:
                    st.write(f"Available: **{format_number(available_qty, 4)}**")
                    st.caption(f"{status_icon} {status}")
                
                with col4:
                    # Editable input for issue quantity
                    issue_qty = st.number_input(
                        f"Issue Qty",
                        min_value=0.0,
                        max_value=float(available_qty),  # Cannot exceed available
                        value=float(st.session_state['issue_quantities'].get(material_id, min(required_qty, available_qty))),
                        step=0.0001,
                        format="%.4f",
                        key=f"issue_qty_{material_id}",
                        label_visibility="collapsed"
                    )
                    st.session_state['issue_quantities'][material_id] = issue_qty
                
                with col5:
                    # Validation feedback
                    if issue_qty < required_qty:
                        st.warning("⚠️ Less")
                        warnings.append(f"{material_name}: issuing {format_number(issue_qty, 4)} < required {format_number(required_qty, 4)}")
                    elif issue_qty > required_qty:
                        st.info("📈 More")
                    else:
                        st.success("✅ Exact")
                    
                    if issue_qty > available_qty:
                        st.error("❌ Over")
                        errors.append(f"{material_name}: cannot issue {format_number(issue_qty, 4)} > available {format_number(available_qty, 4)}")
                        issue_valid = False
                
                # Check for alternatives if current material is insufficient
                if status != 'SUFFICIENT' and row.get('has_alternatives', False):
                    with st.expander(f"🔄 Alternatives for {material_name}", expanded=False):
                        if 'alternative_details' in row and row['alternative_details']:
                            for alt in row['alternative_details']:
                                st.write(
                                    f"• **{alt['name']}** (Priority {alt['priority']}): "
                                    f"{format_number(alt['available'], 4)} {alt['uom']} available"
                                )
                        else:
                            st.info("No alternatives available")
                
                st.markdown("---")
            
            # Summary and validation messages
            if errors:
                st.error("❌ **Errors - Cannot proceed:**")
                for err in errors:
                    st.write(f"• {err}")
            
            if warnings:
                st.warning("⚠️ **Warnings - Issue quantity less than required:**")
                for warn in warnings:
                    st.write(f"• {warn}")
                st.info("💡 Materials can be issued again later if needed. Consider issuing more to ensure sufficient production.")
            
            # Action buttons
            if issue_valid:
                col1, col2 = st.columns([1, 1])
                
                with col1:
                    if not st.session_state.get('confirm_issue', False):
                        if st.button("🚀 Issue Materials", key="issue_materials_main", type="primary", use_container_width=True):
                            st.session_state['confirm_issue'] = True
                            st.rerun()
                
                with col2:
                    if st.button("🔄 Reset to Suggested", key="reset_quantities", use_container_width=True):
                        st.session_state.pop('issue_quantities', None)
                        st.session_state.pop('issue_order_id', None)
                        st.rerun()
                
                if st.session_state.get('confirm_issue', False):
                    st.markdown("---")
                    st.warning(f"⚠️ **Confirm Issue Materials**")
                    st.info(f"Order: **{order['order_no']}** - {order['product_name']}")
                    
                    # Summary of what will be issued
                    st.markdown("**Materials to issue:**")
                    for _, row in availability.iterrows():
                        material_id = row['material_id']
                        issue_qty = st.session_state['issue_quantities'].get(material_id, 0)
                        if issue_qty > 0:
                            st.write(f"• {row['material_name']}: **{format_number(issue_qty, 4)}** {row['uom']}")
                    
                    employees = prod_manager.get_active_employees()
                    
                    if employees.empty:
                        st.error("❌ No active employees found.")
                        return
                    
                    emp_options = {
                        f"{row['full_name']} ({row['position_name'] or 'N/A'})": row['id']
                        for _, row in employees.iterrows()
                    }
                    emp_options_list = ["-- Select --"] + list(emp_options.keys())
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        issued_by_label = st.selectbox("Issued By (Warehouse Staff)", options=emp_options_list, key="issue_issued_by")
                    with col2:
                        received_by_label = st.selectbox("Received By (Production Staff)", options=emp_options_list, key="issue_received_by")
                    
                    notes = st.text_area("Notes (Optional)", placeholder="Enter any notes", key="issue_notes", height=80)
                    
                    col_confirm, col_cancel = st.columns(2)
                    
                    with col_confirm:
                        if st.button("✅ Yes, Issue Now", key="confirm_issue_yes", type="primary", use_container_width=True):
                            if issued_by_label == "-- Select --":
                                st.error("❌ Please select warehouse staff (Issued By)")
                            elif received_by_label == "-- Select --":
                                st.error("❌ Please select production staff (Received By)")
                            else:
                                try:
                                    audit_info = get_user_audit_info()
                                    issued_by_id = emp_options[issued_by_label]
                                    received_by_id = emp_options[received_by_label]
                                    
                                    # Prepare custom quantities for issue
                                    custom_quantities = st.session_state.get('issue_quantities', {})
                                    
                                    with st.spinner("Issuing materials..."):
                                        result = issue_materials(
                                            order_id=order_id,
                                            user_id=audit_info['user_id'],
                                            keycloak_id=audit_info['keycloak_id'],
                                            issued_by=issued_by_id,
                                            received_by=received_by_id,
                                            notes=notes.strip() if notes else None,
                                            custom_quantities=custom_quantities  # NEW: Pass custom quantities
                                        )
                                    
                                    # Clear session state
                                    st.session_state['confirm_issue'] = False
                                    st.session_state.pop('issue_quantities', None)
                                    st.session_state.pop('issue_order_id', None)
                                    
                                    PDFExportDialog.show_pdf_export_dialog(result)
                                    
                                except Exception as e:
                                    st.error(f"❌ Error: {str(e)}")
                                    st.session_state['confirm_issue'] = False
                                    logger.error(f"Material issue error: {e}", exc_info=True)
                    
                    with col_cancel:
                        if st.button("❌ Cancel", key="cancel_issue", use_container_width=True):
                            st.session_state['confirm_issue'] = False
                            st.rerun()
            else:
                st.error("❌ Cannot issue materials. Please fix the errors above.")
        else:
            st.error("No materials found for this BOM")

# ==================== Issue History ====================

def render_issue_history():
    """Render material issue history with PDF download options"""
    st.subheader("📜 Issue History")
    
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        from_date = st.date_input("From Date", value=get_vietnam_today() - timedelta(days=30), key="issue_history_from")
    with col2:
        to_date = st.date_input("To Date", value=get_vietnam_today(), key="issue_history_to")
    with col3:
        status_filter = st.selectbox("Status", ["All", "CONFIRMED", "CANCELLED"], key="issue_history_status")
    
    st.markdown("---")
    
    query = """
        SELECT mi.id, mi.issue_no, mi.issue_date, mi.status, mo.order_no, p.name as product_name,
               COUNT(mid.id) as item_count, SUM(mid.quantity) as total_qty
        FROM material_issues mi
        JOIN manufacturing_orders mo ON mi.manufacturing_order_id = mo.id
        JOIN products p ON mo.product_id = p.id
        LEFT JOIN material_issue_details mid ON mi.id = mid.material_issue_id
        WHERE DATE(mi.issue_date) BETWEEN %s AND %s
    """
    
    params = [from_date, to_date]
    if status_filter != "All":
        query += " AND mi.status = %s"
        params.append(status_filter)
    
    query += " GROUP BY mi.id, mi.issue_no, mi.issue_date, mi.status, mo.order_no, p.name ORDER BY mi.issue_date DESC"
    
    try:
        df = pd.read_sql(query, prod_manager.engine, params=tuple(params))
        
        if not df.empty:
            for idx, row in df.iterrows():
                col1, col2 = st.columns([4, 1])
                with col1:
                    st.write(f"**{row['issue_no']}** - {row['order_no']}")
                    st.caption(f"{row['product_name']} | {row['issue_date'].strftime('%d/%m/%Y %H:%M')}")
                with col2:
                    QuickPDFButton.render(row['id'], row['issue_no'])
                st.markdown("---")
        else:
            st.info("No issue history found for the selected period")
            
    except Exception as e:
        st.error(f"Error loading history: {str(e)}")
        logger.error(f"Issue history error: {e}", exc_info=True)

# ==================== Material Return Form ====================

def render_material_return_form():
    """Render material return form"""
    st.subheader("↩️ Return Unused Materials")
    
    if st.session_state.get('return_success'):
        return_info = st.session_state.get('return_info', {})
        st.success(f"""
        ✅ **Materials Returned Successfully!**
        • Return No: **{return_info.get('return_no', 'N/A')}**
        • Items Returned: **{return_info.get('item_count', 0)}**
        • Total Quantity: **{return_info.get('total_qty', 0)}**
        """)
        
        if st.button("✅ Create Another Return", type="primary", use_container_width=True):
            st.session_state.pop('return_success', None)
            st.session_state.pop('return_info', None)
            st.rerun()
        return
    
    orders = prod_manager.get_orders(status='IN_PROGRESS')
    
    if orders.empty:
        st.info("No orders with issued materials found")
        return
    
    order_dict = {f"{row['order_no']} - {row['product_name']}": row['id'] for _, row in orders.iterrows()}
    selected_order_label = st.selectbox("Select Production Order", list(order_dict.keys()), key="return_order_select")
    order_id = order_dict[selected_order_label]
    
    order = prod_manager.get_order_details(order_id)
    returnable = get_returnable_materials(order_id)
    
    if returnable.empty:
        st.info("No materials available for return")
        return
    
    st.markdown("### 📦 Issued Materials")
    display_returnable = returnable.copy()
    display_returnable['issued_qty'] = display_returnable.apply(
        lambda x: f"{format_number(x['issued_qty'], 2)} {x['uom']}", axis=1
    )
    st.dataframe(display_returnable[['material_name', 'batch_no', 'issued_qty', 'issue_date']], use_container_width=True, hide_index=True)
    
    st.markdown("### ↩️ Return Details")
    
    employees = prod_manager.get_active_employees()
    if employees.empty:
        st.error("❌ No active employees found.")
        return
    
    emp_options = {f"{row['full_name']} ({row['position_name'] or 'N/A'})": row['id'] for _, row in employees.iterrows()}
    emp_options_list = ["-- Select --"] + list(emp_options.keys())
    
    with st.form("return_materials_form"):
        returns = []
        
        for idx, row in returnable.iterrows():
            st.markdown(f"**{row['material_name']}** (Batch: {row['batch_no']})")
            col1, col2 = st.columns([2, 1])
            
            with col1:
                return_qty = st.number_input(
                    f"Return Qty (max: {format_number(row['returnable_qty'], 2)} {row['uom']})",
                    min_value=0.0, max_value=float(row['returnable_qty']), value=0.0, step=0.01,
                    key=f"return_qty_{row['issue_detail_id']}"
                )
            with col2:
                condition = st.selectbox("Condition", ["GOOD", "DAMAGED"], key=f"condition_{row['issue_detail_id']}")
            
            if return_qty > 0:
                returns.append({
                    'issue_detail_id': row['issue_detail_id'], 'material_id': row['material_id'],
                    'batch_no': row['batch_no'], 'quantity': return_qty, 'uom': row['uom'],
                    'condition': condition, 'expired_date': row['expired_date']
                })
        
        st.markdown("---")
        
        col1, col2 = st.columns(2)
        with col1:
            reason = st.selectbox("Return Reason", ["EXCESS", "DEFECT", "WRONG_MATERIAL", "PLAN_CHANGE", "OTHER"])
        
        col1, col2 = st.columns(2)
        with col1:
            returned_by_label = st.selectbox("Returned By (Production Staff)", options=emp_options_list)
        with col2:
            received_by_label = st.selectbox("Received By (Warehouse Staff)", options=emp_options_list)
        
        st.markdown("---")
        col1, col2 = st.columns([1, 1])
        with col1:
            submitted = st.form_submit_button("✅ Return", type="primary", use_container_width=True)
        with col2:
            cancel = st.form_submit_button("❌ Cancel", use_container_width=True)
        
        if submitted:
            if not returns:
                UIHelpers.show_message("⚠️ No materials selected for return", "warning")
            elif returned_by_label == "-- Select --":
                UIHelpers.show_message("⚠️ Please select production staff (Returned By)", "warning")
            elif received_by_label == "-- Select --":
                UIHelpers.show_message("⚠️ Please select warehouse staff (Received By)", "warning")
            else:
                try:
                    audit_info = get_user_audit_info()
                    returned_by_id = emp_options[returned_by_label]
                    received_by_id = emp_options[received_by_label]
                    
                    result = return_materials(
                        order_id=order_id, returns=returns, reason=reason,
                        user_id=audit_info['user_id'], keycloak_id=audit_info['keycloak_id'],
                        returned_by=returned_by_id, received_by=received_by_id
                    )
                    
                    st.session_state['return_success'] = True
                    st.session_state['return_info'] = {
                        'return_no': result['return_no'], 'item_count': len(returns),
                        'total_qty': sum(r['quantity'] for r in returns)
                    }
                    st.rerun()
                    
                except Exception as e:
                    UIHelpers.show_message(f"❌ Error: {str(e)}", "error")
                    logger.error(f"Material return failed: {e}", exc_info=True)
        
        if cancel:
            st.rerun()

# ==================== Return History ====================

def render_return_history():
    """Render material return history - NEW v7.0"""
    st.subheader("📜 Return History")
    
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        from_date = st.date_input("From Date", value=get_vietnam_today() - timedelta(days=30), key="return_history_from")
    with col2:
        to_date = st.date_input("To Date", value=get_vietnam_today(), key="return_history_to")
    with col3:
        status_filter = st.selectbox("Status", ["All", "CONFIRMED", "CANCELLED"], key="return_history_status")
    
    st.markdown("---")
    
    query = """
        SELECT mr.id, mr.return_no, mr.return_date, mr.status, mr.reason, mo.order_no, p.name as product_name,
               COUNT(mrd.id) as item_count, SUM(mrd.quantity) as total_qty
        FROM material_returns mr
        JOIN manufacturing_orders mo ON mr.manufacturing_order_id = mo.id
        JOIN products p ON mo.product_id = p.id
        LEFT JOIN material_return_details mrd ON mr.id = mrd.material_return_id
        WHERE DATE(mr.return_date) BETWEEN %s AND %s
    """
    
    params = [from_date, to_date]
    if status_filter != "All":
        query += " AND mr.status = %s"
        params.append(status_filter)
    
    query += " GROUP BY mr.id, mr.return_no, mr.return_date, mr.status, mr.reason, mo.order_no, p.name ORDER BY mr.return_date DESC"
    
    try:
        df = pd.read_sql(query, prod_manager.engine, params=tuple(params))
        
        if not df.empty:
            display_df = df.copy()
            display_df['return_date'] = pd.to_datetime(display_df['return_date']).dt.strftime('%d/%m/%Y %H:%M')
            display_df['total_qty'] = display_df['total_qty'].apply(lambda x: format_number(x, 2) if x else '0')
            display_df['status'] = display_df['status'].apply(create_status_indicator)
            
            st.dataframe(
                display_df[['return_no', 'return_date', 'order_no', 'product_name', 'reason', 'item_count', 'total_qty', 'status']].rename(columns={
                    'return_no': 'Return No', 'return_date': 'Date', 'order_no': 'Order No',
                    'product_name': 'Product', 'reason': 'Reason', 'item_count': 'Items',
                    'total_qty': 'Total Qty', 'status': 'Status'
                }),
                use_container_width=True, hide_index=True
            )
            
            st.markdown("---")
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Returns", len(df))
            with col2:
                st.metric("Total Items", int(df['item_count'].sum()))
            with col3:
                st.metric("Total Quantity", format_number(df['total_qty'].astype(float).sum(), 2))
        else:
            st.info("No return history found for the selected period")
            
    except Exception as e:
        st.error(f"Error loading return history: {str(e)}")
        logger.error(f"Return history error: {e}", exc_info=True)

# ==================== Production Completion Form ====================

def render_production_completion_form():
    """Render production completion form"""
    st.subheader("✅ Complete Production Order")
    
    orders = prod_manager.get_orders(status='IN_PROGRESS')
    
    if orders.empty:
        st.info("No orders in progress")
        return
    
    order_dict = {f"{row['order_no']} - {row['product_name']}": row['id'] for _, row in orders.iterrows()}
    selected_order_label = st.selectbox("Select Production Order", list(order_dict.keys()), key="complete_order_select")
    order_id = order_dict[selected_order_label]
    
    order = prod_manager.get_order_details(order_id)
    if not order:
        st.error("Order not found")
        return
    
    st.markdown("### 📋 Order Information")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.info(f"**Product:** {order['product_name']}")
        st.info(f"**Planned:** {order['planned_qty']} {order['uom']}")
    with col2:
        st.info(f"**Produced:** {order.get('produced_qty', 0)} {order['uom']}")
        remaining = order['planned_qty'] - order.get('produced_qty', 0)
        st.info(f"**Remaining:** {remaining} {order['uom']}")
    with col3:
        progress = calculate_percentage(order.get('produced_qty', 0), order['planned_qty'])
        st.info(f"**Progress:** {progress}%")
    
    output_summary = output_manager.get_order_output_summary(order_id)
    
    if output_summary and output_summary['receipt_count'] > 0:
        st.markdown("### 📦 Existing Production Receipts")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Receipts", f"{format_number(output_summary['total_receipts'], 1)} {order['uom']}")
        with col2:
            st.metric("Receipt Count", output_summary['receipt_count'])
        with col3:
            st.metric("Current Yield", f"{output_summary['yield_rate']}%")
        
        with st.expander("View Receipt Details"):
            receipts = output_manager.get_order_receipts(order_id)
            if not receipts.empty:
                st.dataframe(receipts[['receipt_no', 'receipt_date', 'quantity', 'batch_no', 'quality_status']], 
                           use_container_width=True, hide_index=True)
    
    st.markdown("---")
    st.markdown("### 🏭 Record Production Output")
    
    with st.form("production_output_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            produced_qty = st.number_input(
                "Produced Quantity", min_value=0.01,
                max_value=float(order['planned_qty'] - order.get('produced_qty', 0)),
                value=float(order['planned_qty'] - order.get('produced_qty', 0)), step=0.1
            )
            batch_no = st.text_input("Batch Number", value=f"BATCH-{get_vietnam_now().strftime('%Y%m%d-%H%M')}")
            quality_status = st.selectbox("Quality Status", ["PASSED", "PENDING", "FAILED"])
        
        with col2:
            expired_date = st.date_input("Expiry Date", value=get_vietnam_today() + timedelta(days=365))
            notes = st.text_area("Production Notes", height=100)
        
        st.markdown("---")
        st.markdown("### 📊 Output Preview")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            new_total = order.get('produced_qty', 0) + produced_qty
            st.info(f"**New Total:** {format_number(new_total, 1)} {order['uom']}")
        with col2:
            new_yield = calculate_percentage(new_total, order['planned_qty'])
            st.info(f"**New Yield:** {new_yield}%")
        with col3:
            will_complete = new_total >= order['planned_qty']
            st.info(f"**Status:** {'✅ Will Complete' if will_complete else '🔄 Partial'}")
        
        st.markdown("---")
        
        col1, col2 = st.columns([1, 1])
        with col1:
            submitted = st.form_submit_button("✅ Complete", type="primary", use_container_width=True)
        with col2:
            cancel = st.form_submit_button("❌ Cancel", use_container_width=True)
        
        if submitted:
            try:
                audit_info = get_user_audit_info()
                
                with st.spinner("Recording production output..."):
                    result = complete_production(
                        order_id=order_id, produced_qty=produced_qty, batch_no=batch_no,
                        warehouse_id=order['target_warehouse_id'], quality_status=quality_status,
                        user_id=audit_info['user_id'], keycloak_id=audit_info['keycloak_id'],
                        expiry_date=expired_date, notes=notes
                    )
                
                UIHelpers.show_success_with_details(
                    title="Production Output Recorded!",
                    details={
                        "Receipt No": result['receipt_no'], "Quantity": f"{produced_qty} {order['uom']}",
                        "Batch": batch_no, "Status": "Order Completed" if result['order_completed'] else "In Progress"
                    }
                )
                
                time.sleep(2)
                st.rerun()
                
            except Exception as e:
                UIHelpers.show_message(f"❌ Error: {str(e)}", "error")
                logger.error(f"Production completion failed: {e}", exc_info=True)
        
        if cancel:
            st.rerun()

# ==================== Receipts List ====================

def render_receipts_list():
    """Render production receipts list - NEW v7.0"""
    st.subheader("📦 Production Receipts")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        presets = get_date_filter_presets()
        date_range = st.selectbox("Date Range", list(presets.keys()), index=6, key="receipts_date_range")
        from_date, to_date = presets[date_range]
    with col2:
        quality_status = st.selectbox("Quality Status", ["All", "PENDING", "PASSED", "FAILED"], index=0, key="receipts_quality")
    with col3:
        products = receipt_manager.get_products()
        product_options = ["All Products"] + products['name'].tolist() if not products.empty else ["All Products"]
        selected_product = st.selectbox("Product", product_options, key="receipts_product")
        product_id = None
        if selected_product != "All Products" and not products.empty:
            product_id = products[products['name'] == selected_product]['id'].iloc[0]
    with col4:
        warehouses = receipt_manager.get_warehouses()
        warehouse_options = ["All Warehouses"] + warehouses['name'].tolist() if not warehouses.empty else ["All Warehouses"]
        selected_warehouse = st.selectbox("Warehouse", warehouse_options, key="receipts_warehouse")
        warehouse_id = None
        if selected_warehouse != "All Warehouses" and not warehouses.empty:
            warehouse_id = warehouses[warehouses['name'] == selected_warehouse]['id'].iloc[0]
    
    col5, col6 = st.columns([1, 1])
    with col5:
        order_no = st.text_input("🔍 Order No.", placeholder="Search by order number...", key="receipts_order_no")
    with col6:
        batch_no = st.text_input("🔍 Batch No.", placeholder="Search by batch number...", key="receipts_batch_no")
    
    st.markdown("---")
    
    receipts = receipt_manager.get_receipts(
        from_date=from_date, to_date=to_date,
        quality_status=quality_status if quality_status != "All" else None,
        product_id=product_id, warehouse_id=warehouse_id,
        order_no=order_no if order_no else None, batch_no=batch_no if batch_no else None
    )
    
    if receipts.empty:
        st.info("📭 No production receipts found for the selected filters")
        return
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        total_receipts = len(receipts)
        st.metric("Total Receipts", total_receipts)
    with col2:
        total_qty = receipts['quantity'].sum()
        st.metric("Total Quantity", f"{format_number(total_qty, 0)}")
    with col3:
        passed = len(receipts[receipts['quality_status'] == 'PASSED'])
        pass_rate = calculate_percentage(passed, total_receipts, 1)
        quality_delta = "✅" if pass_rate >= 95 else "⚠️" if pass_rate >= 90 else "❌"
        st.metric("Pass Rate", f"{pass_rate}% {quality_delta}")
    with col4:
        avg_yield = receipts['yield_rate'].mean()
        yield_delta = "✅" if avg_yield >= 95 else "⚠️" if avg_yield >= 90 else "❌"
        st.metric("Avg Yield Rate", f"{avg_yield:.1f}% {yield_delta}")
    
    with st.expander("📈 Quality Breakdown", expanded=False):
        col1, col2, col3 = st.columns(3)
        passed_count = len(receipts[receipts['quality_status'] == 'PASSED'])
        pending_count = len(receipts[receipts['quality_status'] == 'PENDING'])
        failed_count = len(receipts[receipts['quality_status'] == 'FAILED'])
        
        with col1:
            st.metric("✅ PASSED", passed_count, f"{calculate_percentage(passed_count, total_receipts)}%")
        with col2:
            st.metric("⚠️ PENDING", pending_count, f"{calculate_percentage(pending_count, total_receipts)}%")
        with col3:
            st.metric("❌ FAILED", failed_count, f"{calculate_percentage(failed_count, total_receipts)}%")
    
    st.markdown("---")
    st.markdown("### 📋 Receipts List")
    
    display_df = receipts.copy()
    display_df['receipt_date'] = pd.to_datetime(display_df['receipt_date']).dt.strftime('%d-%b-%Y')
    display_df['quality_status'] = display_df['quality_status'].apply(create_status_indicator)
    display_df['yield_display'] = display_df['yield_rate'].apply(
        lambda x: f"{x:.1f}% {'✅' if x >= 95 else '⚠️' if x >= 85 else '❌'}"
    )
    display_df['qty_display'] = display_df.apply(lambda x: f"{format_number(x['quantity'], 0)} {x['uom']}", axis=1)
    
    st.dataframe(
        display_df[['receipt_no', 'receipt_date', 'order_no', 'product_name', 'qty_display', 'batch_no', 'quality_status', 'yield_display', 'warehouse_name']].rename(columns={
            'receipt_no': 'Receipt No', 'receipt_date': 'Date', 'order_no': 'Order No',
            'product_name': 'Product', 'qty_display': 'Quantity', 'batch_no': 'Batch',
            'quality_status': 'Quality', 'yield_display': 'Yield', 'warehouse_name': 'Warehouse'
        }),
        use_container_width=True, hide_index=True
    )
    
    st.markdown("---")
    st.markdown("### ⚡ Quick Actions")
    
    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        receipt_options = receipts['receipt_no'].tolist()
        selected_receipt_no = st.selectbox("Select Receipt", receipt_options, key="receipt_list_select")
    with col2:
        action = st.selectbox("Action", ["View Details", "Update Quality"], key="receipt_action")
    with col3:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("Execute", type="primary", use_container_width=True, key="receipt_execute"):
            if selected_receipt_no:
                receipt_row = receipts[receipts['receipt_no'] == selected_receipt_no].iloc[0]
                if action == "View Details":
                    show_receipt_details_dialog(receipt_row['id'])
                elif action == "Update Quality":
                    show_update_quality_dialog(receipt_row['id'])
    
    if st.button("📥 Export to Excel", use_container_width=False, key="receipts_export"):
        excel_data = export_to_excel(receipts)
        st.download_button(
            label="Download Excel", data=excel_data,
            file_name=f"production_receipts_{get_vietnam_now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

# ==================== Receipt Dialog Functions ====================

@st.dialog("📦 Receipt Details", width="large")
def show_receipt_details_dialog(receipt_id: int):
    """Show receipt details in a dialog"""
    receipt = receipt_manager.get_receipt_details(receipt_id)
    
    if not receipt:
        st.error("Receipt not found")
        return
    
    st.markdown("### 📦 Output Information")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Receipt No:** {receipt['receipt_no']}")
        st.markdown(f"**Receipt Date:** {receipt['receipt_date']}")
        st.markdown(f"**Batch No:** {receipt['batch_no']}")
        st.markdown(f"**Product:** {receipt['product_name']}")
    with col2:
        st.markdown(f"**Quantity:** {format_number(receipt['quantity'], 2)} {receipt['uom']}")
        st.markdown(f"**Warehouse:** {receipt['warehouse_name']}")
        st.markdown(f"**Quality Status:** {create_status_indicator(receipt['quality_status'])}")
    
    st.markdown("---")
    st.markdown("### 📋 Order Information")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Order No:** {receipt['order_no']}")
        st.markdown(f"**BOM:** {receipt.get('bom_name', 'N/A')}")
    with col2:
        st.markdown(f"**Planned Qty:** {format_number(receipt['planned_qty'], 2)} {receipt['uom']}")
        st.markdown(f"**Produced Qty:** {format_number(receipt['produced_qty'], 2)} {receipt['uom']}")
    
    if receipt['planned_qty'] > 0:
        efficiency = calculate_percentage(receipt['produced_qty'], receipt['planned_qty'])
        st.progress(efficiency / 100)
        st.caption(f"Production Efficiency: {efficiency}%")
    
    if receipt.get('notes'):
        st.markdown("---")
        st.markdown("### 📝 Notes")
        st.text(receipt['notes'])
    
    st.markdown("---")
    with st.expander("📦 Material Usage", expanded=False):
        materials = receipt_manager.get_receipt_materials(receipt['manufacturing_order_id'])
        if not materials.empty:
            st.dataframe(materials, use_container_width=True, hide_index=True)
        else:
            st.info("No material usage data available")
    
    if st.button("Close", use_container_width=True):
        st.rerun()

@st.dialog("✏️ Update Quality Status", width="medium")
def show_update_quality_dialog(receipt_id: int):
    """Show quality update dialog"""
    receipt = receipt_manager.get_receipt_details(receipt_id)
    
    if not receipt:
        st.error("Receipt not found")
        return
    
    st.markdown(f"### Receipt: {receipt['receipt_no']}")
    
    col1, col2 = st.columns(2)
    with col1:
        st.info(f"**Product:** {receipt['product_name']}")
        st.info(f"**Quantity:** {format_number(receipt['quantity'], 2)} {receipt['uom']}")
    with col2:
        st.info(f"**Batch:** {receipt['batch_no']}")
        st.info(f"**Current Status:** {create_status_indicator(receipt['quality_status'])}")
    
    st.markdown("---")
    
    new_status = st.selectbox(
        "New Quality Status", ["PENDING", "PASSED", "FAILED"],
        index=["PENDING", "PASSED", "FAILED"].index(receipt['quality_status'])
    )
    notes = st.text_area("Quality Notes", value=receipt['notes'] or "", height=150)
    
    st.markdown("---")
    
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("✅ Update", type="primary", use_container_width=True):
            try:
                success = receipt_manager.update_quality_status(
                    receipt_id, new_status, notes, st.session_state.get('user_id')
                )
                if success:
                    st.success(f"✅ Quality status updated to {new_status}")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("❌ Failed to update quality status")
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")
                logger.error(f"Quality update failed: {e}", exc_info=True)
    with col2:
        if st.button("❌ Cancel", use_container_width=True):
            st.rerun()

# ==================== Production Output Tab ====================

def render_production_output_tab(order_id: int, order: Dict):
    """Render production output tab with receipts and summary"""
    st.markdown("### 🏭 Production Output Summary")
    
    summary = output_manager.get_order_output_summary(order_id)
    
    if not summary or summary['receipt_count'] == 0:
        st.info("📭 No production output recorded yet")
        
        if order['status'] == 'IN_PROGRESS':
            st.warning("⏳ Production is in progress. Output will appear after completion.")
        elif order['status'] in ['DRAFT', 'CONFIRMED']:
            st.info("🚀 Order has not started production yet.")
        return
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Produced", f"{format_number(summary['total_receipts'], 0)} {summary['uom']}")
    with col2:
        st.metric("Planned Quantity", f"{format_number(summary['planned_qty'], 0)} {summary['uom']}")
    with col3:
        yield_rate = summary['yield_rate']
        yield_indicator = "✅" if yield_rate >= 95 else "⚠️" if yield_rate >= 85 else "❌"
        st.metric("Yield Rate", f"{yield_rate:.1f}% {yield_indicator}")
    with col4:
        st.metric("Shortfall", f"{format_number(summary['shortfall'], 0)} {summary['uom']}")
    
    st.markdown("---")
    st.markdown("### 📊 Quality Status")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("✅ Passed", f"{format_number(summary['passed_qty'], 0)} {summary['uom']}")
    with col2:
        st.metric("⚠️ Pending QC", f"{format_number(summary['pending_qty'], 0)} {summary['uom']}")
    with col3:
        st.metric("❌ Failed", f"{format_number(summary['failed_qty'], 0)} {summary['uom']}")
    
    if yield_rate < 95:
        st.warning(f"""
        ⚠️ **Yield Below Target**
        - Actual: {yield_rate:.1f}%
        - Target: 95%
        - Gap: {95 - yield_rate:.1f}%
        - Scrap/Loss: {format_number(summary['shortfall'], 0)} {summary['uom']}
        """)
    
    st.markdown("---")
    st.markdown("### 📦 Production Receipts")
    
    receipts = output_manager.get_order_receipts(order_id)
    
    if not receipts.empty:
        display_receipts = receipts.copy()
        display_receipts['receipt_date'] = pd.to_datetime(display_receipts['receipt_date']).dt.strftime('%d-%b-%Y')
        display_receipts['quality_status'] = display_receipts['quality_status'].apply(create_status_indicator)
        display_receipts['qty_display'] = display_receipts.apply(lambda x: f"{format_number(x['quantity'], 0)} {x['uom']}", axis=1)
        display_receipts['yield_display'] = display_receipts['yield_rate'].apply(
            lambda x: f"{x:.1f}% {'✅' if x >= 95 else '⚠️' if x >= 85 else '❌'}"
        )
        
        st.dataframe(
            display_receipts[['receipt_no', 'receipt_date', 'qty_display', 'batch_no', 'quality_status', 'yield_display', 'warehouse_name']].rename(columns={
                'receipt_no': 'Receipt No', 'receipt_date': 'Date', 'qty_display': 'Quantity',
                'batch_no': 'Batch', 'quality_status': 'Quality', 'yield_display': 'Yield', 'warehouse_name': 'Warehouse'
            }),
            use_container_width=True, hide_index=True
        )
    else:
        st.info("No receipts found")

# ==================== Main Application ====================

def main():
    """Main application entry point - REFACTORED v7.0"""
    try:
        initialize_session_state()
        render_header()
        st.markdown("---")
        render_navigation()
        
    except Exception as e:
        st.error(f"An error occurred: {str(e)}")
        logger.error(f"Application error: {e}", exc_info=True)
        
        if st.button("🔄 Reload"):
            st.session_state.current_view = 'list'
            st.rerun()
    
    st.markdown("---")
    st.caption("Manufacturing Module v7.0 - Tab-based UI with Integrated History & Receipts")

if __name__ == "__main__":
    main()