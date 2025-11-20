# pages/2___Production.py
"""
Production Management User Interface - REFACTORED v6.0
Complete production cycle: Order → Issue → Return → Complete
WITH PRODUCTION OUTPUT TRACKING & ENHANCED MATERIAL DISPLAY

IMPROVEMENTS v6.0 (Inventory Tracking Fix):
- ✅ CRITICAL FIX: Updated to use keycloak_id for inventory_histories.created_by
- ✅ CRITICAL FIX: Added entity_id tracking for all inventory operations
- ✅ UPDATED: All material operations (issue/return/complete) now pass proper audit fields
- ✅ FIXED: Proper separation of user_id (manufacturing tables) vs keycloak_id (inventory tables)
- ✅ MAINTAINED: All v5.0 functionality including PDF dialogs and enhanced UX

IMPROVEMENTS v5.0 (PDF Dialog Integration Fix):
- ✅ CRITICAL FIX: Integrated with new @st.dialog-based PDF export
- ✅ Simplified PDF dialog flow - shows immediately after issue success
- ✅ Removed complex session state management for PDF dialogs
- ✅ Better error handling and user feedback
- ✅ Maintained ALL v4.0 functionality

Previous versions:
v4.0: Enhanced alternative materials display with detailed information
v3.1: Added PT code and Package size display in all material tables
v3.0: Streamlined UI, removed redundant columns, added Production Receipts navigation
v2.3: Added Production Output tab, output/quality columns
v2.0: Enhanced Order Details view
v1.0: Basic production management
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

prod_manager, inv_manager = get_managers()

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

@st.dialog("✅ Confirm Production Order", width="medium")
def show_confirm_order_dialog(order_id: int, order_no: str):
    """
    Dialog to confirm a DRAFT order
    
    Args:
        order_id: Order ID
        order_no: Order number for display
    """
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
                # Get user info
                user_id = st.session_state.get('user_id', 1)
                
                # Update order status
                success = prod_manager.update_order_status(order_id, 'CONFIRMED', user_id)
                
                if success:
                    st.success(f"✅ Order {order_no} confirmed successfully!")
                    logger.info(f"User {user_id} confirmed order {order_id} ({order_no})")
                    time.sleep(1.5)
                    st.cache_resource.clear()
                    st.rerun()
                else:
                    st.error("❌ Failed to confirm order")
                    logger.warning(f"Failed to confirm order {order_id}")
                    
            except ValueError as e:
                st.error(f"❌ Validation error: {str(e)}")
                logger.error(f"Validation error confirming order {order_id}: {e}")
            except Exception as e:
                st.error(f"❌ System error: {str(e)}")
                logger.error(f"System error confirming order {order_id}: {e}", exc_info=True)
    
    with col2:
        if st.button("❌ Cancel", use_container_width=True):
            st.rerun()

@st.dialog("Edit Production Order", width="large")
def show_edit_order_dialog(order_id: int, order: dict):
    """
    Dialog to edit a DRAFT or CONFIRMED order
    """
    st.markdown(f"### Edit Order: **{order['order_no']}**")
    
    # Use global managers (already initialized at module level)
    # prod_manager and inv_manager are available globally
    
    # Get warehouses
    warehouses = inv_manager.get_warehouses()
    if warehouses.empty:
        st.error("No warehouses available")
        return
    
    warehouse_options = {row['name']: row['id'] for _, row in warehouses.iterrows()}
    warehouse_id_to_name = {row['id']: row['name'] for _, row in warehouses.iterrows()}
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Planned Quantity
        new_planned_qty = st.number_input(
            "Planned Quantity",
            min_value=0.01,
            value=float(order['planned_qty']),
            step=1.0,
            format="%.2f",
            help="Quantity to produce"
        )
        
        # Scheduled Date
        current_date = order['scheduled_date']
        if isinstance(current_date, str):
            from datetime import datetime
            current_date = datetime.strptime(current_date, '%Y-%m-%d').date()
        
        new_scheduled_date = st.date_input(
            "Scheduled Date",
            value=current_date,
            help="Planned production date"
        )
        
        # Priority
        priority_options = ["LOW", "NORMAL", "HIGH", "URGENT"]
        current_priority_idx = priority_options.index(order['priority']) if order['priority'] in priority_options else 1
        
        new_priority = st.selectbox(
            "Priority",
            priority_options,
            index=current_priority_idx,
            help="Production priority"
        )
    
    with col2:
        # Source Warehouse
        current_source = warehouse_id_to_name.get(order['warehouse_id'], list(warehouse_options.keys())[0])
        new_source_warehouse = st.selectbox(
            "Source Warehouse",
            options=list(warehouse_options.keys()),
            index=list(warehouse_options.keys()).index(current_source) if current_source in warehouse_options else 0,
            help="Warehouse to issue materials from"
        )
        new_source_warehouse_id = warehouse_options[new_source_warehouse]
        
        # Target Warehouse
        current_target = warehouse_id_to_name.get(order['target_warehouse_id'], list(warehouse_options.keys())[0])
        new_target_warehouse = st.selectbox(
            "Target Warehouse",
            options=list(warehouse_options.keys()),
            index=list(warehouse_options.keys()).index(current_target) if current_target in warehouse_options else 0,
            help="Warehouse to receive finished goods"
        )
        new_target_warehouse_id = warehouse_options[new_target_warehouse]
        
        # Notes
        new_notes = st.text_area(
            "Notes",
            value=order.get('notes', '') or '',
            height=100,
            help="Additional notes or instructions"
        )
    
    # Show warning if quantity changed
    if new_planned_qty != float(order['planned_qty']):
        st.warning("⚠️ Changing planned quantity will recalculate all required materials.")
    
    st.markdown("---")
    
    # Action buttons
    col_cancel, col_save = st.columns(2)
    
    with col_cancel:
        if st.button("❌ Cancel", use_container_width=True):
            st.rerun()
    
    with col_save:
        if st.button("💾 Save Changes", type="primary", use_container_width=True):
            try:
                # Build update data
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
                
                # Get user info
                audit_info = get_user_audit_info()
                user_id = audit_info.get('user_id')
                
                # Update order
                success = prod_manager.update_order(order_id, update_data, user_id)
                
                if success:
                    st.success(f"✅ Order {order['order_no']} updated successfully!")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("Failed to update order")
                    
            except ValueError as e:
                st.error(f"❌ {str(e)}")
            except Exception as e:
                logger.error(f"Error updating order: {e}")
                st.error(f"❌ Error updating order: {str(e)}")

def set_view(view: str, order_id: Optional[int] = None):
    """Set current view and optionally selected order"""
    st.session_state.current_view = view
    if order_id is not None:
        st.session_state.selected_order = order_id

# ==================== Helper Functions for Audit Fields ====================

def get_user_audit_info() -> Dict[str, any]:
    """
    Get user audit information for database operations
    
    Returns:
        Dict with user_id (INT for manufacturing tables) 
        and keycloak_id (VARCHAR for inventory tables)
    """
    user_id = st.session_state.get('user_id', 1)
    keycloak_id = st.session_state.get('user_keycloak_id')
    
    # Log warning if keycloak_id is missing
    if not keycloak_id:
        logger.warning("⚠️ keycloak_id not found in session state - using fallback")
        # Fallback: try to get from employee_id or use user_id as string
        keycloak_id = str(user_id)  # Emergency fallback
    
    return {
        'user_id': user_id,
        'keycloak_id': keycloak_id
    }

# ==================== Header & Navigation ====================

def render_header():
    """Render page header"""
    col1, col2, col3 = st.columns([2, 4, 1])
    with col1:
        st.title("🏭 Production Management")
    with col3:
        if st.button("🔄 Refresh", key="refresh_main", use_container_width=True):
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
        ("📜 Issue History", 'history')
    ]
    
    # Main navigation
    cols = st.columns(len(nav_items))
    
    for idx, (label, view) in enumerate(nav_items):
        with cols[idx]:
            is_active = st.session_state.current_view == view
            if st.button(
                label,
                key=f"nav_{view}",  # ADDED KEY
                use_container_width=True,
                type="primary" if is_active else "secondary"
            ):
                set_view(view)
                st.rerun()
    
    # Secondary navigation - Production Receipts
    st.markdown("---")
    col_nav = st.columns([5, 1])
    with col_nav[1]:
        if st.button("📦 Production Receipts", key="nav_receipts", use_container_width=True):
            st.switch_page("pages/3_📦_Production_Receipts.py")


# ==================== Utilities ====================

def format_material_display_with_details(row) -> str:
    """Format material display with PT code and package size"""
    name = row.get('material_name', 'Unknown')
    pt_code = row.get('pt_code', 'N/A')
    package_size = row.get('package_size', '')
    
    # Build display string
    display = f"**{name}**"
    
    # Add PT code if available
    if pt_code and pt_code != 'N/A':
        display += f" | PT: {pt_code}"
    
    # Add package size if available
    if package_size and package_size != '':
        display += f" | Pack: {package_size}"
    
    return display

# ==================== Order List View ====================

def render_order_list():
    """Render production orders list with dynamic filters"""
    st.subheader("📋 Production Orders")
    
    # Get dynamic filter options from database
    filter_options = prod_manager.get_filter_options()
    
    # Default date range: last 1 month
    default_to = date.today()
    default_from = (default_to.replace(day=1) - timedelta(days=1)).replace(day=1)  # First day of last month
    
    # ==================== FILTERS ====================
    with st.expander("🔍 Filters", expanded=False):
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            status_filter = st.selectbox(
                "Status",
                filter_options['statuses'],
                index=0
            )
        
        with col2:
            type_filter = st.selectbox(
                "Order Type",
                filter_options['order_types'],
                index=0
            )
        
        with col3:
            priority_filter = st.selectbox(
                "Priority",
                filter_options['priorities'],
                index=0
            )
        
        with col4:
            # st.markdown("**Date Range**")
            date_col1, date_col2 = st.columns(2)
            with date_col1:
                from_date = st.date_input(
                    "From",
                    value=default_from,
                    key="filter_from_date"
                )
            with date_col2:
                to_date = st.date_input(
                    "To",
                    value=default_to,
                    key="filter_to_date"
                )
    
    # ==================== GET DATA ====================
    
    # Prepare filter parameters
    status = status_filter if status_filter != "All" else None
    order_type = type_filter if type_filter != "All" else None
    priority = priority_filter if priority_filter != "All" else None
    
    # Get orders with pagination
    page_size = 20
    page = st.session_state.page_number
    
    orders = prod_manager.get_orders(
        status=status,
        order_type=order_type,
        priority=priority,
        from_date=from_date,
        to_date=to_date,
        page=page,
        page_size=page_size
    )
    
    if orders.empty:
        st.info("No orders found matching the filters")
        return
    
    # ==================== SUMMARY METRICS ====================
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total Orders", len(orders))
    
    with col2:
        in_progress = len(orders[orders['status'] == 'IN_PROGRESS'])
        st.metric("In Progress", in_progress, delta_color="normal")
    
    with col3:
        urgent = len(orders[orders['priority'] == 'URGENT'])
        st.metric("Urgent", urgent, delta_color="inverse" if urgent > 0 else "off")
    
    with col4:
        completion_rate = calculate_percentage(
            len(orders[orders['status'] == 'COMPLETED']), len(orders)
        )
        st.metric("Completion Rate", f"{completion_rate}%")
    
    # ==================== ORDERS TABLE ====================
    
    # Format display columns
    display_orders = orders.copy()
    
    # Add status indicators
    display_orders['status_display'] = display_orders['status'].apply(create_status_indicator)
    display_orders['priority_display'] = display_orders['priority'].apply(create_status_indicator)
    
    # Format quantities
    display_orders['planned_qty_fmt'] = display_orders.apply(
        lambda x: f"{format_number(x['planned_qty'], 2)} {x['uom']}", axis=1
    )
    display_orders['produced_qty_fmt'] = display_orders.apply(
        lambda x: f"{format_number(x['produced_qty'], 2)} {x['uom']}", axis=1
    )
    
    # Calculate progress
    display_orders['progress'] = display_orders.apply(
        lambda x: calculate_percentage(x['produced_qty'], x['planned_qty']), axis=1
    )
    display_orders['progress_fmt'] = display_orders['progress'].apply(lambda x: f"{x}%")
    
    # Select and rename columns for display
    display_columns = {
        'order_no': 'Order No',
        'order_date': 'Order Date',
        'product_name': 'Product',
        'bom_type': 'Type',
        'status_display': 'Status',
        'priority_display': 'Priority',
        'planned_qty_fmt': 'Planned',
        'produced_qty_fmt': 'Produced',
        'progress_fmt': 'Progress',
        'scheduled_date': 'Scheduled',
        'warehouse_name': 'Source WH'
    }
    
    display_df = display_orders[list(display_columns.keys())].rename(columns=display_columns)
    
    # Display table
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        height=400
    )
    
    # ==================== ORDER SELECTION ====================
    st.markdown("---")
    
    # Create order selection dropdown
    order_options = {
        f"{row['order_no']} - {row['product_name']} ({row['status']})": row['id']
        for _, row in orders.iterrows()
    }
    
    selected_order = st.selectbox(
        "Select Order to View Details",
        options=list(order_options.keys()),
        key="order_selector"
    )
    
    if selected_order:
        order_id = order_options[selected_order]
        
        col1, col2, col3 = st.columns([1, 1, 2])
        
        with col1:
            if st.button("📋 View Details", type="primary", use_container_width=True):
                st.session_state.selected_order = order_id
                st.session_state.current_view = 'detail'
                st.rerun()
        
        with col2:
            # Get order status for conditional buttons
            order_status = orders[orders['id'] == order_id]['status'].iloc[0]
            
            if order_status == 'DRAFT':
                if st.button("✅ Confirm Order", use_container_width=True):
                    order_no = orders[orders['id'] == order_id]['order_no'].iloc[0]
                    show_confirm_order_dialog(order_id, order_no)
    
    # ==================== PAGINATION ====================
    st.markdown("---")
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col1:
        if st.button("◀ Previous", disabled=(page <= 1)):
            st.session_state.page_number = page - 1
            st.rerun()
    
    with col2:
        st.markdown(f"<center>Page {page}</center>", unsafe_allow_html=True)
    
    with col3:
        if st.button("Next ▶", disabled=(len(orders) < page_size)):
            st.session_state.page_number = page + 1
            st.rerun()
    
    # ==================== EXPORT ====================
    with st.expander("📥 Export Options"):
        col1, col2 = st.columns(2)
        
        with col1:
            excel_data = export_to_excel(orders)
            st.download_button(
                label="📥 Download Excel",
                data=excel_data,
                file_name=f"production_orders_{date.today().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )


# ==================== Order Details View ====================

def render_order_details():
    """Render detailed view of a single order - ENHANCED v6.1 with Confirm button"""
    order_id = st.session_state.get('selected_order')
    
    if not order_id:
        st.warning("No order selected")
        if st.button("← Back to List", key="back_no_order"):
            set_view('list')
            st.rerun()
        return
    
    # Get order details
    order = prod_manager.get_order_details(order_id)
    
    if not order:
        st.error("Order not found")
        if st.button("← Back to List", key="back_order_not_found"):
            set_view('list')
            st.rerun()
        return
    
    # ==================== ENHANCED: HEADER WITH CONFIRM BUTTON ====================
    col1, col2, col3 = st.columns([4, 1, 1])
    
    with col1:
        st.subheader(f"📋 Order Details: {order['order_no']}")
    
    # NEW: Add Confirm button for DRAFT orders
    with col2:
        if order['status'] == 'DRAFT':
            if st.button("✅ Confirm", type="primary", use_container_width=True,
                        help="Confirm this order to proceed"):
                show_confirm_order_dialog(order_id, order['order_no'])
    
    with col3:
        if st.button("🔄 Refresh", use_container_width=True):
            st.cache_resource.clear()
            st.rerun()
    
    # ==================== NEW: STATUS BANNER ====================
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
    elif order['status'] == 'CONFIRMED':
        st.success(status_msg)
    elif order['status'] == 'IN_PROGRESS':
        st.info(status_msg)
    elif order['status'] == 'COMPLETED':
        st.success(status_msg)
    elif order['status'] == 'CANCELLED':
        st.warning(status_msg)
    
    st.markdown("---")
    
    # ==================== TABS ====================
    tabs = st.tabs(["📄 Order Info", "📦 Materials", "🏭 Production Output", "📜 History"])
    
    # ==================== TAB 1: ORDER INFO ====================
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
        
        # Progress bar
        progress = calculate_percentage(order.get('produced_qty', 0), order['planned_qty'])
        st.progress(progress / 100)
        st.caption(f"{progress}% Complete")
        
        # Notes section
        if order.get('notes'):
            st.markdown("---")
            st.markdown("### Notes")
            st.text(order.get('notes'))
        
        # Action buttons based on status
        st.markdown("---")
        st.markdown("### Quick Actions")
        
        action_cols = st.columns(5)  # Changed from 4 to 5 columns
        
        with action_cols[0]:
            # NEW: Edit button for DRAFT/CONFIRMED orders
            if order['status'] in ['DRAFT', 'CONFIRMED']:
                if st.button("✏️ Edit Order", key="detail_edit_order", use_container_width=True):
                    show_edit_order_dialog(order_id, order)
        
        with action_cols[1]:
            if order['status'] in ['DRAFT', 'CONFIRMED']:
                if st.button("📦 Issue Materials", key="detail_issue_materials", use_container_width=True):
                    set_view('issue')
                    st.session_state.selected_order = order_id
                    st.rerun()
        
        with action_cols[2]:
            if order['status'] == 'IN_PROGRESS':
                if st.button("↩️ Return Materials", key="detail_return_materials", use_container_width=True):
                    set_view('return')
                    st.rerun()
        
        with action_cols[3]:
            if order['status'] == 'IN_PROGRESS':
                if st.button("✅ Complete Order", key="detail_complete_order", use_container_width=True):
                    set_view('complete')
                    st.rerun()
        
        with action_cols[4]:
            if st.button("← Back to List", key="back_from_actions", use_container_width=True):
                set_view('list')
                st.rerun()
    
    # ==================== TAB 2: MATERIALS ====================
    with tabs[1]:
        st.markdown("### Required Materials")
        materials = prod_manager.get_order_materials(order_id)
        
        if not materials.empty:
            # Try to get enhanced material info with PT code and package
            try:
                availability = inv_manager.check_material_availability(
                    order['bom_header_id'],
                    order['planned_qty'],
                    order['warehouse_id']
                )
                
                if not availability.empty:
                    # Format with PT code and package
                    display_df = availability.copy()
                    display_df['material_info'] = display_df.apply(format_material_display_with_details, axis=1)
                    
                    display_df['required_display'] = display_df['required_qty'].apply(lambda x: f"{x:.2f}")
                    display_df['available_display'] = display_df['available_qty'].apply(lambda x: f"{x:.2f}")
                    display_df['status_display'] = display_df['availability_status'].apply(create_status_indicator)
                    
                    st.dataframe(
                        display_df[['material_info', 'required_display', 'available_display', 
                                  'status_display', 'uom']].rename(columns={
                            'material_info': 'Material Info',
                            'required_display': 'Required',
                            'available_display': 'Available',
                            'status_display': 'Status',
                            'uom': 'UOM'
                        }),
                        use_container_width=True,
                        hide_index=True
                    )
                else:
                    # Fallback to original display
                    st.dataframe(
                        materials,
                        use_container_width=True,
                        hide_index=True
                    )
            except Exception as e:
                logger.warning(f"Could not get enhanced material display: {e}")
                # Fallback to original display
                st.dataframe(
                    materials,
                    use_container_width=True,
                    hide_index=True
                )
        else:
            st.info("No materials found")
    
    # ==================== TAB 3: PRODUCTION OUTPUT ====================
    with tabs[2]:
        render_production_output_tab(order_id, order)
    
    # ==================== TAB 4: HISTORY ====================
    with tabs[3]:
        st.info("Order history tracking (to be implemented)")
    
    # Actions at bottom
    st.markdown("---")
    if st.button("← Back to List", key="back_from_details", use_container_width=True):
        set_view('list')
        st.rerun()


# ==================== Create Order View ====================

def render_create_order():
    """Render new production order creation form"""
    st.subheader("➕ Create New Production Order")
    
    # ==================== BOM SELECTION ====================
    st.markdown("### Select BOM")
    
    bom_list = prod_manager.get_active_boms()
    
    if bom_list.empty:
        st.error("No BOMs available")
        return
    
    # Prepare BOM options
    bom_options = {
        f"{row['bom_name']} ({row['product_name']}) - {row['bom_type']}": row['id']
        for _, row in bom_list.iterrows()
    }
    
    selected_bom = st.selectbox(
        "BOM",
        options=list(bom_options.keys()),
        help="Select the BOM (Bill of Materials) for production"
    )
    
    selected_bom_id = bom_options[selected_bom]
    
    # Get BOM details
    selected_bom_details = prod_manager.get_bom_info(selected_bom_id)
    
    if not selected_bom_details:
        st.error("BOM details not found")
        return
    
    # Display BOM info
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.info(f"**Product:** {selected_bom_details['product_name']}")
    with col2:
        st.info(f"**Type:** {selected_bom_details['bom_type']}")
    with col3:
        st.info(f"**Output:** {selected_bom_details['output_qty']} {selected_bom_details['uom']}")
    
    st.markdown("---")
    
    # ==================== ORDER DETAILS ====================
    st.markdown("### Order Details")
    
    col1, col2 = st.columns(2)
    
    with col1:
        planned_qty = st.number_input(
            "Planned Quantity",
            min_value=0.01,
            value=float(selected_bom_details.get('output_qty', 1)),
            step=1.0,
            format="%.2f",
            help="Quantity to produce"
        )
        
        scheduled_date = st.date_input(
            "Scheduled Date",
            value=date.today() + timedelta(days=1),
            min_value=date.today(),
            help="Planned production date"
        )
        
        priority = st.selectbox(
            "Priority",
            ["LOW", "NORMAL", "HIGH", "URGENT"],
            index=1,
            help="Production priority"
        )
    
    with col2:
        # Warehouse selection
        warehouses = inv_manager.get_warehouses()
        
        if warehouses.empty:
            st.error("No warehouses available")
            return
        
        warehouse_options = {row['name']: row['id'] for _, row in warehouses.iterrows()}
        
        source_warehouse = st.selectbox(
            "Source Warehouse",
            options=list(warehouse_options.keys()),
            help="Warehouse to issue materials from"
        )
        source_warehouse_id = warehouse_options[source_warehouse]
        
        target_warehouse = st.selectbox(
            "Target Warehouse",
            options=list(warehouse_options.keys()),
            index=0 if len(warehouse_options) == 1 else 1,
            help="Warehouse to receive finished goods"
        )
        target_warehouse_id = warehouse_options[target_warehouse]
        
        notes = st.text_area(
            "Notes",
            height=100,
            help="Additional notes or instructions"
        )
    
    st.markdown("---")
    
    # ==================== MATERIAL AVAILABILITY CHECK ====================
    st.markdown("### Material Availability Check")
    
    # Check material availability
    with st.spinner("Checking material availability..."):
        availability = inv_manager.check_material_availability(
            selected_bom_id,
            planned_qty,
            source_warehouse_id
        )
    
    if not availability.empty:
        # Summary
        total = len(availability)
        sufficient = len(availability[availability['availability_status'] == 'SUFFICIENT'])
        partial = len(availability[availability['availability_status'] == 'PARTIAL'])
        insufficient = len(availability[availability['availability_status'] == 'INSUFFICIENT'])
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Materials", total)
        with col2:
            st.metric("✅ Sufficient", sufficient, delta_color="normal")
        with col3:
            st.metric("⚠️ Partial", partial, delta_color="normal")
        with col4:
            st.metric("❌ Insufficient", insufficient, delta_color="inverse")
        
        # Display materials with enhanced info
        with st.expander("View Material Details", expanded=False):
            # Status formatting with colors
            def color_status(status):
                return {'SUFFICIENT': '🟢', 'PARTIAL': '🟡', 
                       'INSUFFICIENT': '🔴'}.get(status, '⚪') + f" {status}"
            
            # Enhanced display with PT code and package size
            display_df = availability.copy()
            display_df['material_info'] = display_df.apply(format_material_display_with_details, axis=1)
            display_df['availability_status'] = display_df['availability_status'].apply(color_status)
            
            st.dataframe(
                display_df[['material_info', 'required_qty', 'available_qty', 'availability_status', 'uom']].rename(columns={
                    'material_info': 'Material',
                    'required_qty': 'Required',
                    'available_qty': 'Available',
                    'availability_status': 'Status',
                    'uom': 'UOM'
                }),
                use_container_width=True,
                hide_index=True
            )
    
    # ==================== ACTIONS ====================
    st.markdown("---")
    
    col_btn1, col_btn2 = st.columns(2)
    
    with col_btn1:
        if st.button("✅ Create Order", key="create_order_submit", type="primary", use_container_width=True):
            # Prepare order data
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
            
            # VALIDATE USING FormValidator
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
                
                # Clear cache after successful creation
                prod_manager.clear_bom_cache()
                
                time.sleep(2)
                set_view('list')
                st.rerun()
                
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")
                logger.error(f"Order creation failed: {e}", exc_info=True)
    
    with col_btn2:
        if st.button("❌ Cancel", key="cancel_create_order", use_container_width=True):
            set_view('list')
            st.rerun()

# ==================== Material Issue View ====================


def render_material_issue():
    """Render material issue view with PDF export and enhanced material display"""
    st.subheader("📦 Issue Materials to Production")
    
    # Get confirmed orders that need materials
    orders = prod_manager.get_orders(status='CONFIRMED')
    
    if orders.empty:
        st.info("No confirmed orders available for material issue")
        return
    
    # Order selection
    order_options = {
        f"{row['order_no']} - {row['product_name']} ({row['planned_qty']} {row['uom']})": row['id']
        for _, row in orders.iterrows()
    }
    
    selected_option = st.selectbox(
        "Select Production Order",
        options=list(order_options.keys())
    )
    
    if selected_option:
        order_id = order_options[selected_option]
        order = prod_manager.get_order_details(order_id)
        
        # Display order information
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
        
        # Check material availability
        st.markdown("### 📊 Material Availability Check")
        
        with st.spinner("Checking material availability..."):
            availability = inv_manager.check_material_availability(
                order['bom_header_id'],
                order['planned_qty'],
                order['warehouse_id']
            )
        
        if not availability.empty:
            # Summary metrics
            total_materials = len(availability)
            sufficient = len(availability[availability['availability_status'] == 'SUFFICIENT'])
            partial = len(availability[availability['availability_status'] == 'PARTIAL'])
            insufficient = len(availability[availability['availability_status'] == 'INSUFFICIENT'])
            
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Total Materials", total_materials)
            with col2:
                st.metric("✅ Sufficient", sufficient, delta_color="normal")
            with col3:
                st.metric("⚠️ Partial", partial, delta_color="normal")
            with col4:
                st.metric("❌ Insufficient", insufficient, delta_color="inverse")
            
            # Show materials table with enhanced display (PT code & package size)
            display_df = availability.copy()
            
            # Format material info with PT code and package size
            display_df['material_info'] = display_df.apply(format_material_display_with_details, axis=1)
            
            # Format quantities
            display_df['required_display'] = display_df['required_qty'].apply(lambda x: f"{x:.2f}")
            display_df['available_display'] = display_df['available_qty'].apply(lambda x: f"{x:.2f}")
            
            # Format status
            display_df['status_display'] = display_df['availability_status'].apply(
                lambda x: '✅ SUFFICIENT' if x == 'SUFFICIENT' 
                        else '⚠️ PARTIAL' if x == 'PARTIAL' 
                        else '❌ INSUFFICIENT'
            )
            
            # Display formatted table
            st.dataframe(
                display_df[['material_info', 'required_display', 'available_display', 
                          'status_display', 'uom']].rename(columns={
                    'material_info': 'Material Info',
                    'required_display': 'Required',
                    'available_display': 'Available',
                    'status_display': 'Status',
                    'uom': 'UOM'
                }),
                use_container_width=True,
                hide_index=True
            )
            
            # Issue materials section
            st.markdown("---")
            
            # Check if all materials are sufficient (including with alternatives)
            can_issue = False
            materials_with_alts = pd.DataFrame()
            
            # Check if there are any materials with PARTIAL or INSUFFICIENT status
            if partial > 0 or insufficient > 0:
                # Get materials that need alternatives
                if 'has_alternatives' in availability.columns:
                    materials_with_alts = availability[
                        (availability['availability_status'] != 'SUFFICIENT') & 
                        (availability.get('has_alternatives', False) == True)
                    ]
                    
                    # Check if all insufficient/partial materials can be fulfilled with alternatives
                    materials_needing_alts = availability[availability['availability_status'] != 'SUFFICIENT']
                    can_fulfill_with_alts = all(
                        row.get('alternatives_sufficient', False) 
                        for _, row in materials_needing_alts.iterrows()
                    )
                    
                    if can_fulfill_with_alts and not materials_needing_alts.empty:
                        can_issue = True
                        st.success(f"✅ All materials can be issued using {len(materials_with_alts)} alternative material(s)")
                    else:
                        # Count actual problems (both PARTIAL and INSUFFICIENT)
                        total_problems = partial + insufficient
                        st.error(f"❌ Cannot issue materials: {total_problems} material(s) have insufficient stock even with alternatives")
                    
                    # Show detailed alternatives information only if there are real alternatives
                    if not materials_with_alts.empty:
                        # Check if any alternative actually has quantity > 0
                        has_real_alternatives = False
                        for _, mat in materials_with_alts.iterrows():
                            if mat.get('alternative_total_qty', 0) > 0:
                                has_real_alternatives = True
                                break
                        
                        if has_real_alternatives:
                            UIHelpers.show_alternative_materials(availability)
                else:
                    # No alternatives column, so cannot issue if any material is not sufficient
                    total_problems = partial + insufficient
                    st.error(f"❌ Cannot issue materials: {total_problems} material(s) have insufficient stock")
            else:
                # All materials are SUFFICIENT
                can_issue = True
                st.success("✅ All materials are sufficient")
            
            # Issue button with improved confirmation flow
            if can_issue:
                col1, col2, col3 = st.columns([2, 2, 2])
                
                with col1:
                    # Check if we're in confirmation state
                    if not st.session_state.get('confirm_issue', False):
                        if st.button("🚀 Issue Materials", key="issue_materials_main", type="primary", use_container_width=True):
                            st.session_state['confirm_issue'] = True
                            st.rerun()
                
                with col2:
                    if st.button("🔄 Refresh Stock", key="refresh_stock", use_container_width=True):
                        st.cache_resource.clear()
                        st.rerun()
                
                with col3:
                    if st.button("← Back", key="back_from_confirmation", use_container_width=True):
                        set_view('list')
                        st.rerun()
                
                # Confirmation section with employee dropdowns
                if st.session_state.get('confirm_issue', False):
                    st.markdown("---")
                    st.warning(f"⚠️ **Confirm Issue Materials**")
                    st.info(f"Order: **{order['order_no']}** - {order['product_name']}")
                    
                    # Show what will happen with alternatives
                    if not materials_with_alts.empty:
                        st.info(f"📝 **Note:** {len(materials_with_alts)} material(s) will use alternatives automatically")
                    
                    # GET EMPLOYEES FOR DROPDOWNS
                    employees = prod_manager.get_active_employees()
                    
                    if employees.empty:
                        st.error("❌ No active employees found. Please check employee data.")
                        return
                    
                    # Create employee options dict
                    emp_options = {
                        f"{row['full_name']} ({row['position_name'] or 'N/A'})": row['id']
                        for _, row in employees.iterrows()
                    }
                    emp_options_list = ["-- Select --"] + list(emp_options.keys())
                    
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        issued_by_label = st.selectbox(
                            "Issued By (Warehouse Staff)",
                            options=emp_options_list,
                            key="issue_issued_by",
                            help="Warehouse staff who issues the materials"
                        )
                    
                    with col2:
                        received_by_label = st.selectbox(
                            "Received By (Production Staff)",
                            options=emp_options_list,
                            key="issue_received_by",
                            help="Production staff who receives the materials"
                        )
                    
                    # Notes field
                    notes = st.text_area(
                        "Notes (Optional)",
                        placeholder="Enter any notes about this material issue",
                        key="issue_notes",
                        height=80
                    )
                    
                    col_confirm, col_cancel = st.columns(2)
                    
                    with col_confirm:
                        if st.button("✅ Yes, Issue Now", key="confirm_issue_yes", type="primary", use_container_width=True):
                            # Validate selections
                            if issued_by_label == "-- Select --":
                                st.error("❌ Please select warehouse staff (Issued By)")
                            elif received_by_label == "-- Select --":
                                st.error("❌ Please select production staff (Received By)")
                            else:
                                try:
                                    audit_info = get_user_audit_info()
                                    
                                    # Get employee IDs from selections
                                    issued_by_id = emp_options[issued_by_label]
                                    received_by_id = emp_options[received_by_label]
                                    
                                    with st.spinner("Issuing materials..."):
                                        result = issue_materials(
                                            order_id=order_id,
                                            user_id=audit_info['user_id'],
                                            keycloak_id=audit_info['keycloak_id'],
                                            issued_by=issued_by_id,
                                            received_by=received_by_id,
                                            notes=notes.strip() if notes else None
                                        )
                                    
                                    # Clear confirm state
                                    st.session_state['confirm_issue'] = False
                                    
                                    # Show PDF dialog immediately
                                    PDFExportDialog.show_pdf_export_dialog(result)
                                    
                                except ValueError as e:
                                    st.error(f"❌ Failed to issue materials: {str(e)}")
                                    st.session_state['confirm_issue'] = False
                                except Exception as e:
                                    st.error(f"❌ An error occurred: {str(e)}")
                                    st.session_state['confirm_issue'] = False
                                    logger.error(f"Material issue error: {e}", exc_info=True)
                    
                    with col_cancel:
                        if st.button("❌ Cancel", key="cancel_issue", use_container_width=True):
                            st.session_state['confirm_issue'] = False
                            st.rerun()
            else:
                if st.button("← Back to List", key="back_after_issue", use_container_width=True):
                    set_view('list')
                    st.rerun()
        else:
            st.error("No materials found for this BOM")
            if st.button("← Back to List", key="back_no_materials", use_container_width=True):
                set_view('list')
                st.rerun()

# ==================== Material Return View ====================

def render_material_return():
    """Render material return interface"""
    st.subheader("↩️ Return Unused Materials")
    
    # Check if we just completed a return successfully
    if st.session_state.get('return_success'):
        return_info = st.session_state.get('return_info', {})
        
        st.success(f"""
        ✅ **Materials Returned Successfully!**
        
        • Return No: **{return_info.get('return_no', 'N/A')}**
        • Items Returned: **{return_info.get('item_count', 0)}**
        • Total Quantity: **{return_info.get('total_qty', 0)}**
        """)
        
        st.markdown("---")
        st.markdown("### What would you like to do next?")
        
        col1, col2, col3 = st.columns([1, 1, 2])
        
        with col1:
            if st.button("✅ Create Another Return", type="primary", use_container_width=True):
                st.session_state.pop('return_success', None)
                st.session_state.pop('return_info', None)
                st.rerun()
        
        with col2:
            if st.button("📋 Back to Order List", use_container_width=True):
                st.session_state.pop('return_success', None)
                st.session_state.pop('return_info', None)
                st.session_state.current_view = 'list'
                st.rerun()
        
        return
    
    # Get orders in progress
    orders = prod_manager.get_orders(status='IN_PROGRESS')
    
    if orders.empty:
        st.info("No orders with issued materials found")
        return
    
    # Order selection
    order_dict = {f"{row['order_no']} - {row['product_name']}": row['id'] 
                  for _, row in orders.iterrows()}
    
    selected_order_label = st.selectbox("Select Production Order", list(order_dict.keys()))
    order_id = order_dict[selected_order_label]
    
    # Get order details
    order = prod_manager.get_order_details(order_id)
    returnable = get_returnable_materials(order_id)
    
    if returnable.empty:
        st.info("No materials available for return")
        return
    
    # Display returnable materials
    st.markdown("### 📦 Issued Materials")
    
    display_returnable = returnable.copy()
    display_returnable['issued_qty'] = display_returnable.apply(
        lambda x: f"{format_number(x['issued_qty'], 2)} {x['uom']}", axis=1
    )
    
    st.dataframe(
        display_returnable[['material_name', 'batch_no', 'issued_qty', 'issue_date']],
        use_container_width=True,
        hide_index=True
    )
    
    # Return form
    st.markdown("### ↩️ Return Details")
    
    # GET EMPLOYEES FOR DROPDOWNS (outside form)
    employees = prod_manager.get_active_employees()
    
    if employees.empty:
        st.error("❌ No active employees found. Please check employee data.")
        return
    
    emp_options = {
        f"{row['full_name']} ({row['position_name'] or 'N/A'})": row['id']
        for _, row in employees.iterrows()
    }
    emp_options_list = ["-- Select --"] + list(emp_options.keys())
    
    with st.form("return_materials_form"):
        returns = []
        
        for idx, row in returnable.iterrows():
            st.markdown(f"**{row['material_name']}** (Batch: {row['batch_no']})")
            
            col1, col2 = st.columns([2, 1])
            
            with col1:
                return_qty = st.number_input(
                    f"Return Qty (max: {format_number(row['returnable_qty'], 2)} {row['uom']})",
                    min_value=0.0,
                    max_value=float(row['returnable_qty']),
                    value=0.0,
                    step=0.01,
                    key=f"return_qty_{row['issue_detail_id']}"
                )
            
            with col2:
                condition = st.selectbox(
                    "Condition",
                    ["GOOD", "DAMAGED"],
                    key=f"condition_{row['issue_detail_id']}"
                )
            
            if return_qty > 0:
                returns.append({
                    'issue_detail_id': row['issue_detail_id'],
                    'material_id': row['material_id'],
                    'batch_no': row['batch_no'],
                    'quantity': return_qty,
                    'uom': row['uom'],
                    'condition': condition,
                    'expired_date': row['expired_date']
                })
        
        st.markdown("---")
        
        # Reason and employee selections
        col1, col2 = st.columns(2)
        
        with col1:
            reason = st.selectbox(
                "Return Reason",
                ["EXCESS", "DEFECT", "WRONG_MATERIAL", "PLAN_CHANGE", "OTHER"]
            )
        
        with col2:
            pass  # Placeholder for layout
        
        # Employee dropdowns
        col1, col2 = st.columns(2)
        
        with col1:
            returned_by_label = st.selectbox(
                "Returned By (Production Staff)",
                options=emp_options_list,
                help="Production staff who returns the materials"
            )
        
        with col2:
            received_by_label = st.selectbox(
                "Received By (Warehouse Staff)",
                options=emp_options_list,
                help="Warehouse staff who receives the returned materials"
            )
        
        st.markdown("---")
        col1, col2, col3 = st.columns([3, 1, 1])
        
        with col2:
            submitted = st.form_submit_button("✅ Return", type="primary", use_container_width=True)
        
        with col3:
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
                    
                    # Get employee IDs from selections
                    returned_by_id = emp_options[returned_by_label]
                    received_by_id = emp_options[received_by_label]
                    
                    result = return_materials(
                        order_id=order_id,
                        returns=returns,
                        reason=reason,
                        user_id=audit_info['user_id'],
                        keycloak_id=audit_info['keycloak_id'],
                        returned_by=returned_by_id,
                        received_by=received_by_id
                    )
                    
                    st.session_state['return_success'] = True
                    st.session_state['return_info'] = {
                        'return_no': result['return_no'],
                        'item_count': len(returns),
                        'total_qty': sum(r['quantity'] for r in returns)
                    }
                    
                    st.rerun()
                    
                except Exception as e:
                    UIHelpers.show_message(f"❌ Error: {str(e)}", "error")
                    logger.error(f"Material return failed: {e}", exc_info=True)
        
        if cancel:
            st.session_state.current_view = 'list'
            st.rerun()

# ==================== Production Completion View ====================

def render_production_completion():
    """Render production completion interface with enhanced output preview"""
    st.subheader("✅ Complete Production Order")
    
    # Get orders in progress
    orders = prod_manager.get_orders(status='IN_PROGRESS')
    
    if orders.empty:
        st.info("No orders in progress")
        return
    
    # Order selection
    order_dict = {f"{row['order_no']} - {row['product_name']}": row['id'] 
                  for _, row in orders.iterrows()}
    
    selected_order_label = st.selectbox("Select Production Order", list(order_dict.keys()))
    order_id = order_dict[selected_order_label]
    
    # Get order details
    order = prod_manager.get_order_details(order_id)
    
    if not order:
        st.error("Order not found")
        return
    
    # Display order info
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
    
    # Get existing receipts
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
        
        # Show receipt details
        with st.expander("View Receipt Details"):
            receipts = output_manager.get_order_receipts(order_id)
            if not receipts.empty:
                st.dataframe(receipts[['receipt_no', 'receipt_date', 'quantity', 'batch_no', 'quality_status']], 
                           use_container_width=True, hide_index=True)
    
    st.markdown("---")
    
    # Production output form
    st.markdown("### 🏭 Record Production Output")
    
    with st.form("production_output_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            produced_qty = st.number_input(
                "Produced Quantity",
                min_value=0.01,
                max_value=float(order['planned_qty'] - order.get('produced_qty', 0)),
                value=float(order['planned_qty'] - order.get('produced_qty', 0)),
                step=0.1,
                help="Quantity produced in this batch"
            )
            
            batch_no = st.text_input(
                "Batch Number",
                value=f"BATCH-{datetime.now().strftime('%Y%m%d-%H%M')}",
                help="Unique batch identifier"
            )
            
            quality_status = st.selectbox(
                "Quality Status",
                ["PASSED", "PENDING", "FAILED"],
                help="Quality check status"
            )
        
        with col2:
            expired_date = st.date_input(
                "Expiry Date",
                value=date.today() + timedelta(days=365),
                min_value=date.today(),
                help="Product expiry date (optional)"
            )
            
            notes = st.text_area(
                "Production Notes",
                height=100,
                help="Any notes about this production batch"
            )
        
        # Preview section
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
        
        col1, col2, col3 = st.columns([3, 1, 1])
        
        with col2:
            submitted = st.form_submit_button("✅ Complete", type="primary", use_container_width=True)
        
        with col3:
            cancel = st.form_submit_button("❌ Cancel", use_container_width=True)
        
        if submitted:
            try:
                # ==================== v6.0 FIX: Get proper audit info ====================
                audit_info = get_user_audit_info()
                
                with st.spinner("Recording production output..."):
                    result = complete_production(
                        order_id=order_id,
                        produced_qty=produced_qty,
                        batch_no=batch_no,
                        warehouse_id=order['target_warehouse_id'],
                        quality_status=quality_status,
                        user_id=audit_info['user_id'],        # INT for manufacturing tables
                        keycloak_id=audit_info['keycloak_id'],  # VARCHAR for inventory tables
                        expiry_date=expired_date,
                        notes=notes
                    )
                
                UIHelpers.show_success_with_details(
                    title="Production Output Recorded!",
                    details={
                        "Receipt No": result['receipt_no'],
                        "Quantity": f"{produced_qty} {order['uom']}",
                        "Batch": batch_no,
                        "Status": "Order Completed" if result['order_completed'] else "In Progress"
                    }
                )
                
                time.sleep(2)
                
                if result['order_completed']:
                    set_view('list')
                
                st.rerun()
                
            except Exception as e:
                UIHelpers.show_message(f"❌ Error: {str(e)}", "error")
                logger.error(f"Production completion failed: {e}", exc_info=True)
        
        if cancel:
            set_view('list')
            st.rerun()

# ==================== Production Output Tab Function ====================

def render_production_output_tab(order_id: int, order: Dict):
    """Render production output tab with receipts and summary - STANDALONE FUNCTION"""
    st.markdown("### 🏭 Production Output Summary")
    
    # Get output summary
    summary = output_manager.get_order_output_summary(order_id)
    
    if not summary or summary['receipt_count'] == 0:
        st.info("📭 No production output recorded yet")
        
        if order['status'] == 'IN_PROGRESS':
            st.warning("⏳ Production is in progress. Output will appear after completion.")
        elif order['status'] in ['DRAFT', 'CONFIRMED']:
            st.info("🚀 Order has not started production yet.")
        
        return
    
    # Display summary metrics
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(
            "Total Produced",
            f"{format_number(summary['total_receipts'], 0)} {summary['uom']}"
        )
    
    with col2:
        st.metric(
            "Planned Quantity",
            f"{format_number(summary['planned_qty'], 0)} {summary['uom']}"
        )
    
    with col3:
        yield_rate = summary['yield_rate']
        yield_indicator = "✅" if yield_rate >= 95 else "⚠️" if yield_rate >= 85 else "❌"
        st.metric(
            "Yield Rate",
            f"{yield_rate:.1f}% {yield_indicator}"
        )
    
    with col4:
        st.metric(
            "Shortfall",
            f"{format_number(summary['shortfall'], 0)} {summary['uom']}"
        )
    
    # Quality breakdown
    st.markdown("---")
    st.markdown("### 📊 Quality Status")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        passed = summary['passed_qty']
        st.metric("✅ Passed", f"{format_number(passed, 0)} {summary['uom']}")
    
    with col2:
        pending = summary['pending_qty']
        st.metric("⚠️ Pending QC", f"{format_number(pending, 0)} {summary['uom']}")
    
    with col3:
        failed = summary['failed_qty']
        st.metric("❌ Failed", f"{format_number(failed, 0)} {summary['uom']}")
    
    # Yield warning
    if yield_rate < 95:
        st.warning(f"""
        ⚠️ **Yield Below Target**
        - Actual: {yield_rate:.1f}%
        - Target: 95%
        - Gap: {95 - yield_rate:.1f}%
        - Scrap/Loss: {format_number(summary['shortfall'], 0)} {summary['uom']}
        
        Review production process for improvement opportunities.
        """)
    
    # Receipts list
    st.markdown("---")
    st.markdown("### 📦 Production Receipts")
    
    receipts = output_manager.get_order_receipts(order_id)
    
    if not receipts.empty:
        # Format display
        display_receipts = receipts.copy()
        display_receipts['receipt_date'] = pd.to_datetime(display_receipts['receipt_date']).dt.strftime('%d-%b-%Y')
        display_receipts['quality_status'] = display_receipts['quality_status'].apply(create_status_indicator)
        display_receipts['qty_display'] = display_receipts.apply(
            lambda x: f"{format_number(x['quantity'], 0)} {x['uom']}", axis=1
        )
        display_receipts['yield_display'] = display_receipts['yield_rate'].apply(
            lambda x: f"{x:.1f}% {'✅' if x >= 95 else '⚠️' if x >= 85 else '❌'}"
        )
        
        st.dataframe(
            display_receipts[[
                'receipt_no', 'receipt_date', 'qty_display', 
                'batch_no', 'quality_status', 'yield_display', 'warehouse_name'
            ]].rename(columns={
                'receipt_no': 'Receipt No',
                'receipt_date': 'Date',
                'qty_display': 'Quantity',
                'batch_no': 'Batch',
                'quality_status': 'Quality',
                'yield_display': 'Yield',
                'warehouse_name': 'Warehouse'
            }),
            use_container_width=True,
            hide_index=True
        )
        
        st.info("💡 Click on **Production Receipts** page in navigation to view full details and material traceability")
    else:
        st.info("No receipts found")
    
    # Navigation reminder
    st.markdown("---")
    st.info("""
    📦 **Want more details?**
    
    Visit the **Production Receipts** page (in sidebar) for:
    - Complete material traceability
    - Batch tracking and expiry dates
    - Quality inspection history
    - Inventory impact analysis
    - Advanced filtering and reports
    """)

# ==================== Issue History View ====================

def render_issue_history():
    """Render material issue history with PDF download options"""
    st.subheader("📜 Material Issue History")
    
    # Date filter
    col1, col2, col3 = st.columns(3)
    with col1:
        from_date = st.date_input("From Date", date.today() - timedelta(days=30))
    with col2:
        to_date = st.date_input("To Date", date.today())
    with col3:
        status_filter = st.selectbox("Status", ["All", "CONFIRMED", "CANCELLED"])
    
    # Get issue history
    query = """
        SELECT 
            mi.id,
            mi.issue_no,
            mi.issue_date,
            mo.order_no,
            p.name as product_name,
            mo.planned_qty,
            mo.uom,
            mi.status,
            COUNT(mid.id) as material_count
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
    
    query += " GROUP BY mi.id ORDER BY mi.issue_date DESC"
    
    try:
        df = pd.read_sql(query, prod_manager.engine, params=tuple(params))
        
        if not df.empty:
            # Add action column
            for idx, row in df.iterrows():
                col1, col2 = st.columns([4, 1])
                
                with col1:
                    st.write(f"**{row['issue_no']}** - {row['order_no']}")
                    st.caption(f"{row['product_name']} | {row['issue_date'].strftime('%d/%m/%Y %H:%M')}")
                
                with col2:
                    # FIXED v5.0: Using updated QuickPDFButton with @st.dialog
                    QuickPDFButton.render(row['id'], row['issue_no'])
                
                st.markdown("---")
        else:
            st.info("No issue history found for the selected period")
            
    except Exception as e:
        st.error(f"Error loading history: {str(e)}")
        logger.error(f"Issue history error: {e}", exc_info=True)

# ==================== Main Application ====================

def main():
    """Main application entry point"""
    try:
        # Initialize session state first
        initialize_session_state()
        
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
            'history': render_issue_history
        }
        
        # Get current view handler
        view_handler = view_map.get(st.session_state.current_view, render_order_list)
        view_handler()
        
    except Exception as e:
        st.error(f"An error occurred: {str(e)}")
        logger.error(f"Application error: {e}", exc_info=True)
        
        if st.button("← Back to Order List"):
            set_view('list')
            st.rerun()
    
    # Footer
    st.markdown("---")
    st.caption("Manufacturing Module v6.0 - with Proper Inventory Tracking & Audit Fields")

# Run the application
if __name__ == "__main__":
    main()