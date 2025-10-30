# pages/1_🏭_Production.py
"""
Production Management User Interface - REFACTORED v3.0
Complete production cycle: Order → Issue → Return → Complete
WITH PRODUCTION OUTPUT TRACKING

IMPROVEMENTS v3.0 (Streamlined):
- Removed redundant Progress column
- Removed Dashboard view (metrics in Order List)
- Added Production Receipts navigation button
- Enhanced Output + Quality columns for complete tracking
- Cleaner, more focused UI
- Direct link to Production Receipts page

Previous versions:
v2.3: Added Production Output tab, output/quality columns
v2.0: Enhanced Order Details view
v1.0: Basic production management
"""
import streamlit as st
import pandas as pd
from datetime import datetime, date
from typing import Dict, List, Optional
import logging

# Production domain imports
from utils.auth import AuthManager
from utils.db import get_db_engine
from utils.production.manager import ProductionManager
from utils.production.inventory import InventoryManager
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
        ("✅ Complete Order", 'complete')
    ]
    
    # Main navigation
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
                st.rerun()

# ==================== Order List View ====================

def render_order_list():
    """Render order list view with output tracking"""
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
    
    # Enhance with output data
    orders = enhance_orders_with_output(orders)
    
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
        completion_rate = calculate_percentage(completed, len(orders))
        st.metric("Completion Rate", f"{completion_rate:.1f}%")
    
    st.markdown("---")
    
    # Display table
    display_df = orders.copy()
    
    # Format output and quality BEFORE transforming status
    # (because format functions check original status values)
    display_df['output'] = display_df.apply(format_output_column, axis=1)
    display_df['quality'] = display_df.apply(format_quality_column, axis=1)
    
    # DEBUG: Log formatted columns
    completed_orders = display_df[display_df['status'] == 'COMPLETED']
    if not completed_orders.empty:
        logger.info(f"Formatted output for {len(completed_orders)} completed orders:")
        logger.info(f"Sample formatted data:\n{completed_orders[['order_no', 'status', 'receipt_count', 'total_output', 'yield_rate', 'output', 'quality']].head().to_string()}")
    
    # Now transform status and priority for display
    display_df['status'] = display_df['status'].apply(create_status_indicator)
    display_df['priority'] = display_df['priority'].apply(create_status_indicator)
    
    # Select columns to display (removed progress)
    columns_to_show = ['order_no', 'order_date', 'bom_type', 'product_name',
                       'output', 'quality', 'status', 'priority', 'scheduled_date']
    
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
            orders['order_no'].tolist(),
            key="order_list_select"
        )
    
    if selected_order:
        order_row = orders[orders['order_no'] == selected_order].iloc[0]
        
        with col2:
            actions = get_available_actions(order_row['status'])
            action = st.selectbox("Action", actions, key="order_list_action")
        
        with col3:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Execute", type="primary", use_container_width=True):
                execute_action(action, order_row['id'], order_row['status'])

def enhance_orders_with_output(orders: pd.DataFrame) -> pd.DataFrame:
    """Enhance orders dataframe with production output data"""
    if orders.empty:
        return orders
    
    # Initialize columns with default values
    orders['total_output'] = 0.0
    orders['receipt_count'] = 0
    orders['yield_rate'] = 0.0
    orders['passed_count'] = 0
    orders['pending_count'] = 0
    orders['failed_count'] = 0
    
    # Only query for completed or in-progress orders
    relevant_orders = orders[orders['status'].isin(['COMPLETED', 'IN_PROGRESS'])]
    
    if relevant_orders.empty:
        logger.info("No COMPLETED or IN_PROGRESS orders to enhance")
        return orders
    
    # Get output summary for relevant orders
    order_ids = relevant_orders['id'].tolist()
    placeholders = ','.join(['%s'] * len(order_ids))
    
    # DEBUG: Log order IDs being queried
    logger.info(f"Enhancing {len(order_ids)} orders")
    logger.info(f"Order IDs to query: {order_ids}")
    logger.info(f"Order numbers: {relevant_orders['order_no'].tolist()}")
    
    query = f"""
        SELECT 
            mo.id as order_id,
            COALESCE(SUM(pr.quantity), 0) as total_output,
            COUNT(pr.id) as receipt_count,
            ROUND(COALESCE(SUM(pr.quantity) / NULLIF(mo.planned_qty, 0) * 100, 0), 1) as yield_rate,
            SUM(CASE WHEN pr.quality_status = 'PASSED' THEN 1 ELSE 0 END) as passed_count,
            SUM(CASE WHEN pr.quality_status = 'PENDING' THEN 1 ELSE 0 END) as pending_count,
            SUM(CASE WHEN pr.quality_status = 'FAILED' THEN 1 ELSE 0 END) as failed_count
        FROM manufacturing_orders mo
        LEFT JOIN production_receipts pr ON mo.id = pr.manufacturing_order_id
        WHERE mo.id IN ({placeholders})
        GROUP BY mo.id, mo.planned_qty
    """
    
    try:
        # Pass params as tuple
        output_df = pd.read_sql(query, prod_manager.engine, params=tuple(order_ids))
        
        # DEBUG: Log query results
        logger.info(f"Query returned {len(output_df)} rows with output data")
        if not output_df.empty:
            logger.info(f"Orders with receipts: {output_df['order_id'].tolist()}")
            logger.info(f"Receipt counts: {output_df[['order_id', 'receipt_count']].to_dict('records')}")
        else:
            logger.warning("Query returned empty - no production receipts found for these orders")
        
        if not output_df.empty:
            # Create mapping dictionary for each column separately
            for col in ['total_output', 'receipt_count', 'yield_rate', 'passed_count', 'pending_count', 'failed_count']:
                # Create simple column mapping
                col_map = dict(zip(output_df['order_id'], output_df[col]))
                
                # Update orders using map
                mask = orders['id'].isin(output_df['order_id'])
                orders.loc[mask, col] = orders.loc[mask, 'id'].map(col_map).fillna(0)
            
            # DEBUG: Log update results
            updated_orders = orders[orders['id'].isin(output_df['order_id'])]
            logger.info(f"Updated {len(updated_orders)} orders with output data")
            logger.info(f"Sample updated data: {updated_orders[['id', 'order_no', 'receipt_count', 'yield_rate']].head().to_dict('records')}")
        
    except Exception as e:
        logger.error(f"Error enhancing orders with output: {e}", exc_info=True)
    
    return orders

def format_output_column(row) -> str:
    """Format output column for display"""
    status = row['status']
    
    if status not in ['COMPLETED', 'IN_PROGRESS']:
        return "-"
    
    receipt_count = int(row.get('receipt_count', 0))
    
    # No receipts = no output
    if receipt_count == 0:
        return "-"
    
    output = float(row.get('total_output', 0))
    planned = float(row.get('planned_qty', 0))
    yield_rate = float(row.get('yield_rate', 0))
    
    if planned == 0:
        return "-"
    
    # Color coding based on yield
    if yield_rate >= 95:
        indicator = "✅"
    elif yield_rate >= 85:
        indicator = "⚠️"
    else:
        indicator = "❌"
    
    return f"{format_number(output, 0)}/{format_number(planned, 0)} {indicator}"

def format_quality_column(row) -> str:
    """Format quality column for display"""
    status = row['status']
    
    # Only show quality for completed orders
    if status != 'COMPLETED':
        return "-"
    
    receipt_count = int(row.get('receipt_count', 0))
    
    # No receipts = no quality data
    if receipt_count == 0:
        return "-"
    
    passed = int(row.get('passed_count', 0))
    pending = int(row.get('pending_count', 0))
    failed = int(row.get('failed_count', 0))
    
    # Show quality based on priority
    if failed > 0:
        return f"❌ {failed} Failed"
    elif pending > 0:
        return f"⚠️ {pending} Pending"
    else:
        return f"✅ All Passed ({passed})"

def get_available_actions(status: str) -> List[str]:
    """Get available actions based on status"""
    actions_map = {
        'DRAFT': ["View Details", "Confirm Order", "Issue Materials", "Cancel Order"],
        'CONFIRMED': ["View Details", "Issue Materials", "Cancel Order"],
        'IN_PROGRESS': ["View Details", "Return Materials", "Complete Production", "Cancel Order"],
        'COMPLETED': ["View Details", "View Production Output"],
        'CANCELLED': ["View Details"]
    }
    return actions_map.get(status, ["View Details"])

def execute_action(action: str, order_id: int, status: str):
    """Execute selected action"""
    if action == "View Details":
        set_view('details', order_id)
        st.rerun()
    elif action == "View Production Output":
        st.info("Navigate to Production Receipts page to view output details")
    elif action == "Confirm Order":
        try:
            prod_manager.update_order_status(order_id, 'CONFIRMED', st.session_state.user_id)
            UIHelpers.show_message("✅ Order confirmed", "success")
            st.rerun()
        except Exception as e:
            UIHelpers.show_message(f"❌ Error: {str(e)}", "error")
    elif action == "Issue Materials":
        set_view('issue', order_id)
        st.rerun()
    elif action == "Return Materials":
        set_view('return', order_id)
        st.rerun()
    elif action == "Complete Production":
        set_view('complete', order_id)
        st.rerun()
    elif action == "Cancel Order":
        if UIHelpers.confirm_action("Are you sure you want to cancel this order?", f"cancel_{order_id}"):
            try:
                prod_manager.update_order_status(order_id, 'CANCELLED', st.session_state.user_id)
                UIHelpers.show_message("✅ Order cancelled", "success")
                st.rerun()
            except Exception as e:
                UIHelpers.show_message(f"❌ Error: {str(e)}", "error")

# ==================== Create Order View ====================

def render_create_order():
    """Render create new order form"""
    st.subheader("➕ Create Production Order")
    
    with st.form("create_order_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("### Product & BOM")
            
            # Get active BOMs
            bom_type = st.selectbox("BOM Type", ["KITTING", "CUTTING", "REPACKING"])
            boms = prod_manager.get_active_boms(bom_type)
            
            if boms.empty:
                st.warning(f"No active BOMs found for {bom_type}")
                st.form_submit_button("Create Order", disabled=True)
                return
            
            bom_options = {f"{row['bom_name']} ({row['product_name']})": row['id'] 
                          for _, row in boms.iterrows()}
            selected_bom_label = st.selectbox("Select BOM", list(bom_options.keys()))
            bom_id = bom_options[selected_bom_label]
            
            # Get BOM info
            bom_info = prod_manager.get_bom_info(bom_id)
            if bom_info:
                st.info(f"Output: {bom_info['output_qty']} {bom_info['uom']}")
                product_id = bom_info['product_id']
                uom = bom_info['uom']
            
            planned_qty = st.number_input(
                "Planned Quantity",
                min_value=1.0,
                value=100.0,
                step=1.0
            )
        
        with col2:
            st.markdown("### Warehouse & Schedule")
            
            warehouses = inv_manager.get_warehouses()
            if warehouses.empty:
                st.error("No warehouses found")
                st.form_submit_button("Create Order", disabled=True)
                return
            
            warehouse_dict = {row['name']: row['id'] for _, row in warehouses.iterrows()}
            
            source_warehouse = st.selectbox(
                "Source Warehouse (Materials)",
                list(warehouse_dict.keys())
            )
            warehouse_id = warehouse_dict[source_warehouse]
            
            target_warehouse = st.selectbox(
                "Target Warehouse (Finished Goods)",
                list(warehouse_dict.keys())
            )
            target_warehouse_id = warehouse_dict[target_warehouse]
            
            scheduled_date = st.date_input(
                "Scheduled Date",
                value=date.today() + pd.Timedelta(days=1),
                min_value=date.today()
            )
            
            priority = st.selectbox(
                "Priority",
                ["LOW", "NORMAL", "HIGH", "URGENT"],
                index=1
            )
        
        notes = st.text_area("Notes", height=100)
        
        st.markdown("---")
        col1, col2, col3 = st.columns([3, 1, 1])
        
        with col2:
            submitted = st.form_submit_button("✅ Create Order", type="primary", use_container_width=True)
        
        with col3:
            cancel = st.form_submit_button("❌ Cancel", use_container_width=True)
        
        if submitted:
            try:
                order_data = {
                    'bom_header_id': bom_id,
                    'product_id': product_id,
                    'planned_qty': planned_qty,
                    'uom': uom,
                    'warehouse_id': warehouse_id,
                    'target_warehouse_id': target_warehouse_id,
                    'scheduled_date': scheduled_date,
                    'priority': priority,
                    'notes': notes,
                    'created_by': st.session_state.user_id
                }
                
                order_no = prod_manager.create_order(order_data)
                UIHelpers.show_message(f"✅ Order created: {order_no}", "success")
                set_view('list')
                st.rerun()
                
            except Exception as e:
                UIHelpers.show_message(f"❌ Error: {str(e)}", "error")
                logger.error(f"Order creation failed: {e}", exc_info=True)
        
        if cancel:
            set_view('list')
            st.rerun()

# ==================== Material Issue View ====================

def render_material_issue():
    """Render material issue interface"""
    st.subheader("📦 Issue Materials to Production")
    
    # Get orders ready for material issue
    orders = prod_manager.get_orders(status='DRAFT')
    confirmed_orders = prod_manager.get_orders(status='CONFIRMED')
    
    if not confirmed_orders.empty:
        orders = pd.concat([orders, confirmed_orders], ignore_index=True) if not orders.empty else confirmed_orders
    
    if orders.empty:
        st.info("No orders available for material issue")
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
    with st.expander("📋 Order Information", expanded=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            st.write(f"**Order No:** {order['order_no']}")
            st.write(f"**Product:** {order['product_name']}")
        with col2:
            st.write(f"**Quantity:** {order['planned_qty']} {order['uom']}")
            st.write(f"**Status:** {order['status']}")
        with col3:
            st.write(f"**Source:** {order['warehouse_name']}")
            st.write(f"**Target:** {order['target_warehouse_name']}")
    
    # Check material availability
    st.markdown("### 📊 Material Availability Check")
    
    availability = inv_manager.check_material_availability(
        order['bom_header_id'],
        order['planned_qty'],
        order['warehouse_id']
    )
    
    if not availability.empty:
        # Summary
        total_materials = len(availability)
        sufficient = len(availability[availability['availability_status'] == 'SUFFICIENT'])
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Materials", total_materials)
        with col2:
            st.metric("✅ Sufficient", sufficient)
        with col3:
            insufficient = total_materials - sufficient
            st.metric("❌ Insufficient", insufficient)
        
        # Display materials
        materials = availability.copy()
        materials['required_qty'] = materials.apply(
            lambda x: f"{format_number(x['required_qty'], 2)} {x['uom']}", axis=1
        )
        materials['available_qty'] = materials.apply(
            lambda x: f"{format_number(x['available_qty'], 2)} {x['uom']}", axis=1
        )
        materials['status'] = materials['availability_status'].apply(create_status_indicator)
        
        st.dataframe(
            materials[['material_name', 'required_qty', 'available_qty', 'status']],
            use_container_width=True,
            hide_index=True
        )
        
        # Check if all materials available
        all_available = not any('X' in str(s) for s in materials['status'])
        
        # Action section
        st.markdown("---")
        col1, col2 = st.columns([3, 1])
        
        with col1:
            if all_available:
                st.success("✅ All materials are available in stock")
            else:
                st.error("❌ Some materials have insufficient stock")
                st.info("""
                **Options:**
                1. Wait for stock replenishment
                2. Check if alternative materials are available
                3. Adjust production quantity
                """)
        
        with col2:
            if all_available and st.button("📦 Issue Materials", type="primary", use_container_width=True):
                try:
                    result = issue_materials(order_id, st.session_state.user_id)
                    
                    UIHelpers.show_message(
                        f"✅ Materials issued! Issue No: **{result['issue_no']}**",
                        "success"
                    )
                    
                    st.rerun()
                    
                except Exception as e:
                    UIHelpers.show_message(f"❌ Error: {str(e)}", "error")
                    logger.error(f"Material issue failed: {e}", exc_info=True)

# ==================== Material Return View ====================

def render_material_return():
    """Render material return interface"""
    st.subheader("↩️ Return Unused Materials")
    
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
    
    # Get returnable materials
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
    
    with st.form("return_materials_form"):
        returns = []
        
        for idx, row in returnable.iterrows():
            st.markdown(f"**{row['material_name']}** (Batch: {row['batch_no']})")
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                return_qty = st.number_input(
                    "Return Quantity",
                    min_value=0.0,
                    max_value=float(row['issued_qty']),
                    value=0.0,
                    step=0.1,
                    key=f"return_qty_{idx}"
                )
            
            with col2:
                condition = st.selectbox(
                    "Condition",
                    ["GOOD", "DAMAGED", "EXPIRED"],
                    key=f"condition_{idx}"
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
        
        reason = st.selectbox(
            "Return Reason",
            ["EXCESS", "DEFECT", "WRONG_MATERIAL", "PLAN_CHANGE", "OTHER"]
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
            else:
                try:
                    result = return_materials(order_id, returns, reason, st.session_state.user_id)
                    
                    UIHelpers.show_message(
                        f"✅ Materials returned! Return No: **{result['return_no']}**",
                        "success"
                    )
                    
                    st.rerun()
                    
                except Exception as e:
                    UIHelpers.show_message(f"❌ Error: {str(e)}", "error")
                    logger.error(f"Material return failed: {e}", exc_info=True)
        
        if cancel:
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
    with st.expander("📋 Order Information", expanded=True):
        col1, col2 = st.columns(2)
        with col1:
            st.write(f"**Order No:** {order['order_no']}")
            st.write(f"**Product:** {order['product_name']}")
            st.write(f"**BOM Type:** {order['bom_type']}")
        with col2:
            st.write(f"**Planned Quantity:** {order['planned_qty']} {order['uom']}")
            st.write(f"**Target Warehouse:** {order['target_warehouse_name']}")
            st.write(f"**Scheduled:** {order['scheduled_date']}")
    
    # Completion form
    st.markdown("---")
    
    with st.form("complete_production_form"):
        st.markdown("### 📊 Production Summary")
        
        col1, col2 = st.columns(2)
        
        with col1:
            # Production output
            produced_qty = st.number_input(
                "Produced Quantity",
                min_value=0.0,
                value=float(order['planned_qty']),
                step=1.0,
                help="Actual quantity produced"
            )
            
            # Calculate yield and show warnings
            yield_rate = (produced_qty / order['planned_qty'] * 100) if order['planned_qty'] > 0 else 0
            scrap_qty = order['planned_qty'] - produced_qty
            scrap_pct = (scrap_qty / order['planned_qty'] * 100) if order['planned_qty'] > 0 else 0
            
            # Yield display with color coding
            if yield_rate >= 95:
                yield_color = "🟢"
                yield_status = "Excellent"
            elif yield_rate >= 90:
                yield_color = "🟡"
                yield_status = "Good"
            elif yield_rate >= 85:
                yield_color = "🟠"
                yield_status = "Fair"
            else:
                yield_color = "🔴"
                yield_status = "Poor"
            
            st.metric(
                "Yield Rate",
                f"{yield_rate:.1f}% {yield_color}",
                f"{yield_status}"
            )
            
            st.metric(
                "Scrap/Loss",
                f"{format_number(scrap_qty, 2)} {order['uom']}",
                f"{scrap_pct:.1f}%"
            )
        
        with col2:
            # Quality information
            quality_status = st.selectbox(
                "Quality Status",
                ["PASSED", "PENDING", "FAILED"],
                index=0
            )
            
            batch_no = st.text_input(
                "Batch Number",
                value=f"BATCH-{datetime.now().strftime('%Y%m%d')}-{order_id}",
                help="Unique batch identifier for traceability"
            )
            
            # Calculate default expiry based on product shelf life
            default_expiry = date.today() + pd.Timedelta(days=730)  # 2 years default
            expired_date = st.date_input(
                "Expiry Date",
                value=default_expiry,
                min_value=date.today(),
                help="Product expiration date"
            )
        
        # Production notes
        st.markdown("### 📝 Production Notes")
        notes = st.text_area(
            "Notes",
            height=100,
            placeholder="Enter any notes about the production process, quality issues, or observations..."
        )
        
        # Warning alerts
        if yield_rate < 95:
            st.warning(f"""
            ⚠️ **Yield Below Target**
            - Current yield: {yield_rate:.1f}%
            - Target yield: 95%
            - Gap: {95 - yield_rate:.1f}%
            
            Please review production process for improvement opportunities.
            """)
        
        if quality_status == "FAILED":
            st.error("""
            ❌ **Quality Check Failed**
            
            This batch has failed quality inspection. Please document the issues in the notes section.
            Consider reviewing:
            - Material quality
            - Production parameters
            - Equipment calibration
            """)
        
        # Submit buttons
        st.markdown("---")
        col1, col2, col3 = st.columns([3, 1, 1])
        
        with col2:
            submitted = st.form_submit_button(
                "✅ Complete",
                type="primary",
                use_container_width=True
            )
        
        with col3:
            cancel = st.form_submit_button("❌ Cancel", use_container_width=True)
        
        if submitted:
            try:
                validate_positive_number(produced_qty, "Produced quantity")
                
                result = complete_production(
                    order['id'],
                    produced_qty,
                    batch_no,
                    quality_status,
                    notes,
                    st.session_state.user_id,
                    expired_date
                )
                
                # Success message with details
                UIHelpers.show_message(
                    f"✅ Production completed! Receipt No: **{result['receipt_no']}**",
                    "success"
                )
                
                # Show completion details
                with st.expander("📋 Completion Details", expanded=True):
                    st.write(f"**Receipt No:** {result['receipt_no']}")
                    st.write(f"**Batch No:** {result['batch_no']}")
                    st.write(f"**Quantity:** {result['quantity']} {order['uom']}")
                    st.write(f"**Quality:** {result['quality_status']}")
                    st.write(f"**Yield Rate:** {yield_rate:.1f}%")
                    
                    if yield_rate >= 95:
                        st.success("✅ Excellent yield achieved!")
                    elif yield_rate < 85:
                        st.warning("⚠️ Low yield - review recommended")
                
                st.info("💡 View full production output in **Production Receipts** page")
                
                st.rerun()
                
            except Exception as e:
                UIHelpers.show_message(f"❌ Error: {str(e)}", "error")
                logger.error(f"Production completion failed: {e}", exc_info=True)
        
        if cancel:
            st.rerun()

# ==================== Order Details View ====================

def render_order_details():
    """Render order details view with Production Output tab"""
    if not st.session_state.selected_order:
        st.warning("No order selected")
        if st.button("← Back to List"):
            set_view('list')
            st.rerun()
        return
    
    order_id = st.session_state.selected_order
    order = prod_manager.get_order_details(order_id)
    
    if not order:
        st.error("Order not found")
        if st.button("← Back to List"):
            set_view('list')
            st.rerun()
        return
    
    st.subheader(f"📋 Order Details: {order['order_no']}")
    
    # Order info summary
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Product", order['product_name'])
    with col2:
        st.metric("Status", order['status'])
    with col3:
        st.metric("Progress", f"{order['produced_qty']}/{order['planned_qty']} {order['uom']}")
    with col4:
        st.metric("Priority", order['priority'])
    
    st.markdown("---")
    
    # Tabs for different sections
    tab1, tab2, tab3, tab4 = st.tabs(["📄 Order Info", "📦 Materials", "🏭 Production Output", "📜 History"])
    
    # Tab 1: Order Information
    with tab1:
        col1, col2 = st.columns(2)
        with col1:
            st.write(f"**Order Date:** {order['order_date']}")
            st.write(f"**Scheduled Date:** {order['scheduled_date']}")
            st.write(f"**BOM:** {order['bom_name']}")
            st.write(f"**Type:** {order['bom_type']}")
        with col2:
            st.write(f"**Source Warehouse:** {order['warehouse_name']}")
            st.write(f"**Target Warehouse:** {order['target_warehouse_name']}")
            st.write(f"**Priority:** {order['priority']}")
            st.write(f"**Status:** {order['status']}")
    
    # Tab 2: Materials
    with tab2:
        materials = prod_manager.get_order_materials(order_id)
        
        if not materials.empty:
            st.dataframe(
                materials,
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("No materials found")
    
    # Tab 3: Production Output (NEW)
    with tab3:
        render_production_output_tab(order_id, order)
    
    # Tab 4: History
    with tab4:
        st.info("Order history tracking (to be implemented)")
    
    # Actions
    st.markdown("---")
    if st.button("← Back to List", use_container_width=True):
        set_view('list')
        st.rerun()

def render_production_output_tab(order_id: int, order: Dict):
    """Render production output tab with receipts and summary"""
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

# ==================== Main Application ====================

def main():
    """Main application entry point"""
    try:
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
            'details': render_order_details
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
    st.caption("Manufacturing Module v3.0 - Streamlined Production Management with Output Tracking")


if __name__ == "__main__":
    main()