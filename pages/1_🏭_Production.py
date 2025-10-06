# pages/1_🏭_Production.py - Production Management Page (Enhanced)
import streamlit as st
import pandas as pd
from datetime import datetime, date
import time
from utils.auth import AuthManager
from modules.production import ProductionManager
from modules.inventory import InventoryManager
from modules.bom import BOMManager
import logging

logger = logging.getLogger(__name__)

# Page config
st.set_page_config(
    page_title="Production Management",
    page_icon="🏭",
    layout="wide"
)

# Authentication
auth = AuthManager()
auth.require_auth()

# Initialize managers
prod_manager = ProductionManager()
inv_manager = InventoryManager()
bom_manager = BOMManager()

# Page header
st.title("🏭 Production Management")

# Initialize session state
if 'current_view' not in st.session_state:
    st.session_state.current_view = 'new'  # Default to new order
if 'selected_order' not in st.session_state:
    st.session_state.selected_order = None
if 'bom_selection_key' not in st.session_state:
    st.session_state.bom_selection_key = 0

# Top navigation
col1, col2, col3, col4, col5, col6 = st.columns(6)
with col1:
    if st.button("📋 Order List", use_container_width=True, 
                type="primary" if st.session_state.current_view == 'list' else "secondary"):
        st.session_state.current_view = 'list'
with col2:
    if st.button("➕ New Order", use_container_width=True, 
                type="primary" if st.session_state.current_view == 'new' else "secondary"):
        st.session_state.current_view = 'new'
with col3:
    if st.button("📦 Material Issue", use_container_width=True, 
                type="primary" if st.session_state.current_view == 'issue' else "secondary"):
        st.session_state.current_view = 'issue'
with col4:
    if st.button("↩️ Material Return", use_container_width=True, 
                type="primary" if st.session_state.current_view == 'return' else "secondary"):
        st.session_state.current_view = 'return'
with col5:
    if st.button("✅ Complete Order", use_container_width=True, 
                type="primary" if st.session_state.current_view == 'complete' else "secondary"):
        st.session_state.current_view = 'complete'
with col6:
    if st.button("📊 Dashboard", use_container_width=True, 
                type="primary" if st.session_state.current_view == 'dashboard' else "secondary"):
        st.session_state.current_view = 'dashboard'

st.markdown("---")

# Helper functions
def format_order_status(status):
    """Format order status with color"""
    colors = {
        'DRAFT': '🔵',
        'CONFIRMED': '🟡',
        'IN_PROGRESS': '🟠',
        'COMPLETED': '🟢',
        'CANCELLED': '🔴'
    }
    return f"{colors.get(status, '⚪')} {status}"

# Content based on view
if st.session_state.current_view == 'new':
    # Create New Production Order
    st.subheader("➕ Create New Production Order")
    
    # Production type selection
    prod_type = st.selectbox(
        "Production Type",
        ["KITTING", "CUTTING", "REPACKING"],
        help="Select the type of production",
        key="prod_type_select"
    )
    
    # Get BOMs for selected type - with proper state management
    boms = bom_manager.get_active_boms(bom_type=prod_type)
    
    # Force refresh of BOM selection when type changes
    if f'last_prod_type_{st.session_state.bom_selection_key}' not in st.session_state:
        st.session_state[f'last_prod_type_{st.session_state.bom_selection_key}'] = prod_type
    
    if st.session_state[f'last_prod_type_{st.session_state.bom_selection_key}'] != prod_type:
        st.session_state.bom_selection_key += 1
        st.session_state[f'last_prod_type_{st.session_state.bom_selection_key}'] = prod_type
    
    col1, col2 = st.columns(2)
    
    with col1:
        if not boms.empty:
            # Create BOM options
            bom_options = {
                f"{row['bom_name']} ({row['bom_code']})": row['id'] 
                for _, row in boms.iterrows()
            }
            
            # BOM selection with unique key
            selected_bom = st.selectbox(
                "Select BOM",
                options=list(bom_options.keys()),
                key=f"bom_select_{st.session_state.bom_selection_key}"
            )
            
            if selected_bom:
                bom_id = bom_options[selected_bom]
                
                # Get and display BOM details
                bom_details = bom_manager.get_bom_details(bom_id)
                bom_info = bom_manager.get_bom_info(bom_id)
                
                # Show BOM info
                st.info(f"**Output:** {bom_info['product_name']} - {bom_info['output_qty']} {bom_info['uom']}")
            else:
                bom_id = None
        else:
            st.warning(f"No active BOMs found for {prod_type}")
            bom_id = None
        
        # Quantity to produce
        qty = st.number_input("Quantity to Produce", min_value=1, value=1, step=1)
        
        # Scheduled date
        scheduled_date = st.date_input("Scheduled Date", value=date.today())
    
    with col2:
        # Warehouse selection
        warehouses = inv_manager.get_warehouses()
        if not warehouses.empty:
            warehouse_options = dict(zip(warehouses['name'], warehouses['id']))
            
            source_warehouse = st.selectbox("Source Warehouse", options=list(warehouse_options.keys()))
            source_warehouse_id = warehouse_options[source_warehouse] if source_warehouse else None
            
            target_warehouse = st.selectbox("Target Warehouse", options=list(warehouse_options.keys()))
            target_warehouse_id = warehouse_options[target_warehouse] if target_warehouse else None
        else:
            st.error("No warehouses found")
            source_warehouse_id = None
            target_warehouse_id = None
        
        # Priority
        priority = st.selectbox("Priority", ["LOW", "NORMAL", "HIGH", "URGENT"], index=1)
        
        # Notes
        notes = st.text_area("Notes", height=100)
    
    # Material availability check section
    if bom_id and source_warehouse_id:
        with st.expander("📊 Material Requirements", expanded=True):
            # Calculate requirements
            requirements = prod_manager.calculate_material_requirements(bom_id, qty)
            
            if not requirements.empty:
                # Check availability
                availability_data = []
                all_available = True
                
                for _, row in requirements.iterrows():
                    stock = inv_manager.get_stock_balance(row['material_id'], source_warehouse_id)
                    is_available = stock >= row['required_qty']
                    if not is_available:
                        all_available = False
                    
                    availability_data.append({
                        'Material': row['material_name'],
                        'Required': f"{row['required_qty']:.2f}",
                        'Available': f"{stock:.2f}",
                        'Status': '✅' if is_available else '❌ Insufficient'
                    })
                
                # Display availability table
                availability_df = pd.DataFrame(availability_data)
                st.dataframe(availability_df, use_container_width=True, hide_index=True)
                
                if not all_available:
                    st.warning("⚠️ Some materials have insufficient stock")
    
    # Create order section
    st.markdown("---")
    col1, col2, col3 = st.columns([2, 1, 2])
    with col2:
        create_disabled = not (bom_id and source_warehouse_id and target_warehouse_id)
        
        if st.button("Create Order", type="primary", use_container_width=True, disabled=create_disabled):
            # Simple validation
            if not bom_id:
                st.error("Please select a BOM")
            elif qty <= 0:
                st.error("Quantity must be greater than 0")
            elif not source_warehouse_id or not target_warehouse_id:
                st.error("Please select both source and target warehouses")
            else:
                try:
                    # Create order data
                    order_data = {
                        'bom_header_id': bom_id,
                        'product_id': bom_info['product_id'],
                        'planned_qty': qty,
                        'uom': bom_info['uom'],
                        'warehouse_id': source_warehouse_id,
                        'target_warehouse_id': target_warehouse_id,
                        'scheduled_date': scheduled_date,
                        'priority': priority,
                        'notes': notes,
                        'created_by': st.session_state.user_id
                    }
                    
                    # Create order - validation will be done in the manager
                    order_no = prod_manager.create_order(order_data)
                    st.success(f"✅ Production Order {order_no} created successfully!")
                    st.balloons()
                    
                    # Reset form
                    time.sleep(2)
                    st.session_state.current_view = 'list'
                    st.rerun()
                    
                except Exception as e:
                    st.error(f"❌ Error creating order: {str(e)}")
                    logger.error(f"Order creation error: {e}")

elif st.session_state.current_view == 'list':
    # Production Order List
    st.subheader("📋 Production Orders")
    
    # Filters
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        filter_status = st.selectbox("Status", ["All", "DRAFT", "CONFIRMED", "IN_PROGRESS", "COMPLETED", "CANCELLED"])
    with col2:
        filter_type = st.selectbox("Type", ["All", "KITTING", "CUTTING", "REPACKING"])
    with col3:
        filter_from = st.date_input("From Date", value=date.today().replace(day=1))
    with col4:
        filter_to = st.date_input("To Date", value=date.today())
    
    # Get orders
    orders = prod_manager.get_orders(
        status=None if filter_status == "All" else filter_status,
        order_type=None if filter_type == "All" else filter_type,
        from_date=filter_from,
        to_date=filter_to
    )
    
    if not orders.empty:
        # Summary metrics
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
        
        # Display orders with better formatting
        display_df = orders.copy()
        display_df['status'] = display_df['status'].apply(format_order_status)
        display_df['order_date'] = pd.to_datetime(display_df['order_date']).dt.strftime('%Y-%m-%d')
        display_df['scheduled_date'] = pd.to_datetime(display_df['scheduled_date']).dt.strftime('%Y-%m-%d')
        
        # Column configuration
        column_config = {
            "order_no": "Order No.",
            "order_date": "Date",
            "bom_type": "Type",
            "product_name": "Product",
            "planned_qty": st.column_config.NumberColumn("Planned", format="%d"),
            "produced_qty": st.column_config.NumberColumn("Produced", format="%d"),
            "status": "Status",
            "scheduled_date": "Scheduled",
            "priority": "Priority"
        }
        
        # Select columns to display
        display_columns = ['order_no', 'order_date', 'bom_type', 'product_name', 
                          'planned_qty', 'produced_qty', 'status', 'scheduled_date', 'priority']
        
        st.dataframe(
            display_df[display_columns],
            use_container_width=True,
            hide_index=True,
            column_config=column_config
        )
        
        # Quick actions
        st.markdown("### Quick Actions")
        col1, col2, col3 = st.columns([2, 2, 1])
        
        with col1:
            order_no = st.selectbox("Select Order", orders['order_no'].tolist())
        
        with col2:
            selected_order = orders[orders['order_no'] == order_no].iloc[0]
            action_options = []
            
            # Dynamic actions based on status
            if selected_order['status'] == 'CONFIRMED':
                action_options = ["View Details", "Issue Materials", "Cancel Order"]
            elif selected_order['status'] == 'IN_PROGRESS':
                action_options = ["View Details", "Return Materials", "Complete Production"]
            else:
                action_options = ["View Details"]
            
            action = st.selectbox("Action", action_options)
        
        with col3:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Execute", type="primary", use_container_width=True):
                # Find order ID
                selected_order_id = orders[orders['order_no'] == order_no]['id'].iloc[0]
                st.session_state.selected_order = selected_order_id
                
                if action == "Issue Materials":
                    st.session_state.current_view = 'issue'
                elif action == "Return Materials":
                    st.session_state.current_view = 'return'
                elif action == "Complete Production":
                    st.session_state.current_view = 'complete'
                elif action == "View Details":
                    st.session_state.current_view = 'details'
                st.rerun()
    else:
        st.info("No production orders found for the selected criteria")

elif st.session_state.current_view == 'issue':
    # Material Issue
    st.subheader("📦 Material Issue")
    
    # Get pending orders
    pending_orders = prod_manager.get_orders(status='CONFIRMED')
    
    if not pending_orders.empty:
        # Order selection
        order_options = dict(zip(
            pending_orders['order_no'] + " - " + pending_orders['product_name'],
            pending_orders['id']
        ))
        
        # Use selected order if available
        default_key = None
        if st.session_state.selected_order and st.session_state.selected_order in pending_orders['id'].tolist():
            for key, value in order_options.items():
                if value == st.session_state.selected_order:
                    default_key = key
                    break
        
        selected_order_display = st.selectbox(
            "Select Production Order", 
            options=list(order_options.keys()),
            index=list(order_options.keys()).index(default_key) if default_key else 0
        )
        selected_order_id = order_options[selected_order_display]
        
        # Get order details
        order_info = prod_manager.get_order_details(selected_order_id)
        materials = prod_manager.get_order_materials(selected_order_id)
        
        # Display order info
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Product", order_info['product_name'])
        with col2:
            st.metric("Quantity", f"{order_info['planned_qty']} {order_info['uom']}")
        with col3:
            st.metric("Type", order_info['bom_type'])
        with col4:
            st.metric("Warehouse", order_info['warehouse_name'])
        
        # Materials to issue
        st.markdown("### Materials Required")
        
        if not materials.empty:
            # Check current status and stock
            materials_with_status = []
            all_available = True
            
            for _, mat in materials.iterrows():
                # Get current stock
                stock = inv_manager.get_stock_balance(mat['material_id'], order_info['warehouse_id'])
                remaining_to_issue = mat['required_qty'] - mat['issued_qty']
                
                # Check FEFO preview
                fefo_preview = inv_manager.preview_fefo_issue(
                    mat['material_id'], 
                    remaining_to_issue, 
                    order_info['warehouse_id']
                )
                
                status = "✅ Issued" if mat['issued_qty'] >= mat['required_qty'] else "⏳ Pending"
                stock_status = "✅" if stock >= remaining_to_issue else "❌"
                
                if stock < remaining_to_issue:
                    all_available = False
                
                materials_with_status.append({
                    'Material': mat['material_name'],
                    'Required': f"{mat['required_qty']:.2f}",
                    'Issued': f"{mat['issued_qty']:.2f}",
                    'Remaining': f"{remaining_to_issue:.2f}",
                    'Stock': f"{stock:.2f} {stock_status}",
                    'Status': status
                })
            
            materials_df = pd.DataFrame(materials_with_status)
            st.dataframe(materials_df, use_container_width=True, hide_index=True)
            
            # FEFO Preview (expandable)
            with st.expander("🔍 FEFO Issue Preview"):
                for _, mat in materials.iterrows():
                    remaining = mat['required_qty'] - mat['issued_qty']
                    if remaining > 0:
                        st.write(f"**{mat['material_name']}** - Need: {remaining:.2f}")
                        fefo_batches = inv_manager.preview_fefo_issue(
                            mat['material_id'], 
                            remaining, 
                            order_info['warehouse_id']
                        )
                        if not fefo_batches.empty:
                            st.dataframe(
                                fefo_batches[['batch_no', 'quantity', 'expired_date', 'expiry_status']],
                                use_container_width=True,
                                hide_index=True
                            )
                        else:
                            st.warning("No stock available")
                        st.markdown("---")
            
            # Issue materials button
            if any(mat['Status'] == '⏳ Pending' for mat in materials_with_status):
                col1, col2, col3 = st.columns([2, 1, 2])
                with col2:
                    if st.button("📤 Issue All Materials", type="primary", use_container_width=True, 
                                disabled=not all_available):
                        if not all_available:
                            st.error("❌ Cannot issue - insufficient stock for some materials")
                        else:
                            with st.spinner("Issuing materials..."):
                                try:
                                    # Create material issue
                                    issue_result = prod_manager.issue_materials(
                                        selected_order_id,
                                        st.session_state.user_id
                                    )
                                    
                                    st.success(f"✅ Materials issued successfully! Issue No: {issue_result['issue_no']}")
                                    
                                    # Show issued details
                                    st.markdown("### Issued Details")
                                    for detail in issue_result['details']:
                                        st.write(f"- {detail['material_name']}: {detail['quantity']} {detail['uom']}")
                                    
                                    # Update order status
                                    prod_manager.update_order_status(selected_order_id, 'IN_PROGRESS')
                                    
                                    time.sleep(2)
                                    st.rerun()
                                    
                                except Exception as e:
                                    st.error(f"❌ Error issuing materials: {str(e)}")
                                    logger.error(f"Material issue error: {e}")
            else:
                st.info("✅ All materials have been issued for this order")
        else:
            st.warning("No materials found for this order")
    else:
        st.info("No confirmed orders pending material issue")

elif st.session_state.current_view == 'return':
    # Material Return
    st.subheader("↩️ Material Return")
    
    # Get in-progress orders
    in_progress = prod_manager.get_orders(status='IN_PROGRESS')
    
    if not in_progress.empty:
        # Order selection
        order_options = dict(zip(
            in_progress['order_no'] + " - " + in_progress['product_name'],
            in_progress['id']
        ))
        
        selected_order_display = st.selectbox(
            "Select Production Order", 
            options=list(order_options.keys())
        )
        selected_order_id = order_options[selected_order_display]
        
        # Get order details
        order_info = prod_manager.get_order_details(selected_order_id)
        
        # Display order info
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Product", order_info['product_name'])
        with col2:
            st.metric("Planned Qty", f"{order_info['planned_qty']} {order_info['uom']}")
        with col3:
            st.metric("Type", order_info['bom_type'])
        with col4:
            st.metric("Warehouse", order_info['warehouse_name'])
        
        # Get issued materials that can be returned
        issued_materials = prod_manager.get_issued_materials(selected_order_id)
        
        if not issued_materials.empty:
            st.markdown("### Issued Materials Available for Return")
            
            # Initialize return items in session state
            if 'return_items' not in st.session_state:
                st.session_state.return_items = {}
            
            # Display materials with return options
            for idx, row in issued_materials.iterrows():
                with st.container():
                    col1, col2, col3, col4, col5 = st.columns([3, 1.5, 1.5, 1.5, 1])
                    
                    with col1:
                        st.write(f"**{row['material_name']}**")
                        st.caption(f"Batch: {row['batch_no']}")
                    
                    with col2:
                        st.write(f"Issued: {row['issued_qty']:.2f}")
                        st.caption(f"Returned: {row['returned_qty']:.2f}")
                    
                    with col3:
                        max_return = row['returnable_qty']
                        return_qty = st.number_input(
                            "Return Qty",
                            min_value=0.0,
                            max_value=float(max_return),
                            value=0.0,
                            step=0.01,
                            key=f"return_qty_{idx}"
                        )
                    
                    with col4:
                        condition = st.selectbox(
                            "Condition",
                            ["GOOD", "DAMAGED", "EXPIRED"],
                            key=f"condition_{idx}"
                        )
                    
                    with col5:
                        st.write(row['uom'])
                    
                    # Store return info
                    if return_qty > 0:
                        st.session_state.return_items[idx] = {
                            'original_issue_detail_id': row['issue_detail_id'],
                            'material_id': row['material_id'],
                            'material_name': row['material_name'],
                            'quantity': return_qty,
                            'uom': row['uom'],
                            'condition': condition,
                            'batch_no': row['batch_no']
                        }
                    elif idx in st.session_state.return_items:
                        del st.session_state.return_items[idx]
                
                st.markdown("---")
            
            # Return reason and notes
            col1, col2 = st.columns(2)
            with col1:
                reason = st.selectbox(
                    "Reason for Return",
                    ["EXCESS", "DEFECT", "WRONG_MATERIAL", "PLAN_CHANGE", "OTHER"]
                )
            with col2:
                notes = st.text_area("Notes", placeholder="Additional information...")
            
            # Submit button
            if st.session_state.return_items:
                st.markdown("### Return Summary")
                for item in st.session_state.return_items.values():
                    st.write(f"- {item['material_name']}: {item['quantity']} {item['uom']} ({item['condition']})")
                
                col1, col2, col3 = st.columns([2, 1, 2])
                with col2:
                    if st.button("Create Return", type="primary", use_container_width=True):
                        try:
                            # Get material issue ID (simplified - assuming single issue)
                            material_issue_id = issued_materials['issue_detail_id'].iloc[0]
                            
                            return_data = {
                                'material_issue_id': material_issue_id,
                                'manufacturing_order_id': selected_order_id,
                                'warehouse_id': order_info['warehouse_id'],
                                'reason': reason,
                                'notes': notes,
                                'items': list(st.session_state.return_items.values())
                            }
                            
                            result = prod_manager.create_material_return(
                                return_data, 
                                st.session_state.user_id
                            )
                            
                            st.success(f"✅ Material return created successfully! Return No: {result['return_no']}")
                            
                            # Clear return items
                            st.session_state.return_items = {}
                            
                            time.sleep(2)
                            st.rerun()
                            
                        except Exception as e:
                            st.error(f"❌ Error creating return: {str(e)}")
                            logger.error(f"Material return error: {e}")
            else:
                st.info("Please select materials to return")
            
            # Show existing returns
            st.markdown("---")
            st.markdown("### Previous Returns")
            returns = prod_manager.get_material_returns(selected_order_id)
            
            if not returns.empty:
                st.dataframe(
                    returns,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "return_no": "Return No.",
                        "return_date": st.column_config.DatetimeColumn("Date"),
                        "reason": "Reason",
                        "item_count": st.column_config.NumberColumn("Items", format="%d"),
                        "total_quantity": st.column_config.NumberColumn("Total Qty", format="%.2f"),
                        "status": "Status"
                    }
                )
            else:
                st.info("No returns found for this order")
        else:
            st.info("No issued materials available for return")
    else:
        st.info("No in-progress orders available for material return")

elif st.session_state.current_view == 'complete':
    # Complete Production
    st.subheader("✅ Complete Production")
    
    # Get in-progress orders
    in_progress = prod_manager.get_orders(status='IN_PROGRESS')
    
    if not in_progress.empty:
        # Order selection
        order_options = dict(zip(
            in_progress['order_no'] + " - " + in_progress['product_name'],
            in_progress['id']
        ))
        
        selected_order_display = st.selectbox(
            "Select Production Order", 
            options=list(order_options.keys())
        )
        selected_order_id = order_options[selected_order_display]
        
        # Get order details
        order_info = prod_manager.get_order_details(selected_order_id)
        
        # Display order info
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Product", order_info['product_name'])
        with col2:
            st.metric("Planned Qty", f"{order_info['planned_qty']} {order_info['uom']}")
        with col3:
            st.metric("Type", order_info['bom_type'])
        with col4:
            st.metric("Target Warehouse", order_info['target_warehouse_name'])
        
        # Show material usage summary
        st.markdown("### Material Usage Summary")
        materials = prod_manager.get_order_material_summary(selected_order_id)
        
        if not materials.empty:
            # Display materials table...
            materials_display = []
            for _, mat in materials.iterrows():
                efficiency = 0
                if mat['actual_used_qty'] > 0:
                    efficiency = (mat['required_qty'] / mat['actual_used_qty']) * 100
                
                materials_display.append({
                    'Material': mat['material_name'],
                    'Required': f"{mat['required_qty']:.2f}",
                    'Issued': f"{mat['issued_qty']:.2f}",
                    'Returned': f"{mat['returned_qty']:.2f}",
                    'Actual Used': f"{mat['actual_used_qty']:.2f}",
                    'Efficiency': f"{efficiency:.1f}%"
                })
            
            st.dataframe(
                pd.DataFrame(materials_display),
                use_container_width=True,
                hide_index=True
            )
        
        # Production completion form
        st.markdown("### Production Results")
        
        # Calculate expiry date
        calculated_expiry = prod_manager.get_calculated_expiry_date(selected_order_id)
        
        col1, col2 = st.columns(2)
        with col1:
            # Get tolerance from config
            tolerance = 1.1  # 10% over-production allowed
            max_allowed = int(order_info['planned_qty'] * tolerance)
            
            produced_qty = st.number_input(
                "Produced Quantity",
                min_value=0,
                max_value=max_allowed,
                value=int(order_info['planned_qty']),
                step=1,
                help=f"Maximum allowed with 10% tolerance: {max_allowed}"
            )
            
            # Batch number generation
            batch_prefix = order_info['bom_type'][:3].upper()
            default_batch = f"{batch_prefix}-{datetime.now().strftime('%Y%m%d%H%M')}"
            batch_no = st.text_input("Batch Number", value=default_batch)
        
        with col2:
            quality_status = st.selectbox("Quality Status", ["PASSED", "FAILED", "PENDING"])
            
            # Expiry date handling với info theo process type
            st.markdown("#### Expiry Date")
            
            # Show info based on BOM type
            if order_info['bom_type'] == 'KITTING':
                st.info("ℹ️ Kit inherits the shortest expiry date from its components")
            elif order_info['bom_type'] == 'CUTTING':
                st.info("ℹ️ Cut products inherit expiry date from source material")
            elif order_info['bom_type'] == 'REPACKING':
                st.info("ℹ️ Repacked products inherit expiry date from original product")
            
            # Display calculated expiry
            if calculated_expiry:
                days_until_expiry = (calculated_expiry - date.today()).days
                
                if days_until_expiry < 30:
                    st.warning(f"⚠️ Calculated expiry: {calculated_expiry.strftime('%Y-%m-%d')} ({days_until_expiry} days)")
                else:
                    st.success(f"📅 Calculated expiry: {calculated_expiry.strftime('%Y-%m-%d')} ({days_until_expiry} days)")
                
                # Allow manual override
                use_calculated = st.checkbox("Use calculated expiry date", value=True)
                
                if use_calculated:
                    expiry_date = calculated_expiry
                else:
                    expiry_date = st.date_input(
                        "Manual Expiry Date",
                        value=calculated_expiry,
                        min_value=date.today(),
                        help="Override the calculated expiry date if needed"
                    )
            else:
                st.warning("⚠️ No expiry date could be calculated from materials")
                # Manual input required
                expiry_date = st.date_input(
                    "Manual Expiry Date",
                    value=None,
                    min_value=date.today(),
                    help="Please set expiry date manually"
                )
            
            notes = st.text_area("Production Notes", height=100)
        
        # Complete button
        col1, col2, col3 = st.columns([2, 1, 2])
        with col2:
            if st.button("Complete Production", type="primary", use_container_width=True):
                if produced_qty <= 0:
                    st.error("Produced quantity must be greater than 0")
                elif not batch_no:
                    st.error("Batch number is required")
                elif not expiry_date:
                    st.error("Expiry date is required")
                else:
                    try:
                        # Create production receipt với expiry date
                        receipt_result = prod_manager.complete_production(
                            order_id=selected_order_id,
                            produced_qty=produced_qty,
                            batch_no=batch_no,
                            quality_status=quality_status,
                            notes=notes,
                            created_by=st.session_state.user_id,
                            expired_date=expiry_date  # Pass expiry date
                        )
                        
                        st.success(f"✅ Production completed! Receipt No: {receipt_result['receipt_no']}")
                        st.balloons()
                        
                        # Show summary với expiry info
                        with st.container():
                            st.markdown("### Production Summary")
                            summary_col1, summary_col2 = st.columns(2)
                            with summary_col1:
                                st.write(f"**Product:** {order_info['product_name']}")
                                st.write(f"**Quantity:** {produced_qty} {order_info['uom']}")
                                st.write(f"**Batch:** {batch_no}")
                            with summary_col2:
                                st.write(f"**Location:** {order_info['target_warehouse_name']}")
                                st.write(f"**Expiry Date:** {expiry_date.strftime('%Y-%m-%d')}")
                                days_shelf_life = (expiry_date - date.today()).days
                                st.write(f"**Shelf Life:** {days_shelf_life} days")
                        
                        time.sleep(3)
                        st.session_state.current_view = 'list'
                        st.rerun()
                        
                    except Exception as e:
                        st.error(f"❌ Error completing production: {str(e)}")
                        logger.error(f"Production completion error: {e}")
    else:
        st.info("No orders in progress")

elif st.session_state.current_view == 'dashboard':
    # Production Dashboard
    st.subheader("📊 Production Dashboard")
    
    # Date range
    col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        start_date = st.date_input("From", value=date.today().replace(day=1))
    with col2:
        end_date = st.date_input("To", value=date.today())
    with col3:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🔄 Refresh", use_container_width=True):
            st.rerun()
    
    # Get statistics
    stats = prod_manager.get_production_stats(start_date, end_date)
    
    # Display metrics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric(
            "Total Orders", 
            stats.get('total_orders', 0),
            delta=f"{stats.get('vs_previous_period', 0):.1f}% vs prev"
        )
    with col2:
        st.metric(
            "Completed", 
            stats.get('completed_orders', 0),
            delta=f"{stats.get('completion_rate', 0):.1f}% rate"
        )
    with col3:
        st.metric(
            "In Progress", 
            stats.get('in_progress_orders', 0)
        )
    with col4:
        avg_lead_time = stats.get('avg_lead_time', 0) or 0
        st.metric(
            "Avg Lead Time", 
            f"{avg_lead_time:.1f} days"
        )
    
    # Charts
    col1, col2 = st.columns(2)
    
    with col1:
        # Orders by type
        st.markdown("### Orders by Type")
        type_data = prod_manager.get_orders_by_type(start_date, end_date)
        if not type_data.empty:
            st.bar_chart(type_data.set_index('bom_type')['count'])
        else:
            st.info("No data available")
    
    with col2:
        # Orders by status
        st.markdown("### Orders by Status")
        status_data = prod_manager.get_orders_by_status(start_date, end_date)
        if not status_data.empty:
            # Create color mapping
            status_colors = {
                'DRAFT': '#0088FE',
                'CONFIRMED': '#FFB800',
                'IN_PROGRESS': '#FF8042',
                'COMPLETED': '#00CC88',
                'CANCELLED': '#FF4444'
            }
            
            # Display with colors
            chart_data = status_data.set_index('status')['count']
            st.bar_chart(chart_data)
        else:
            st.info("No data available")
    
    # Material consumption
    st.markdown("### Top 10 Material Consumption")
    consumption = prod_manager.get_material_consumption(start_date, end_date)
    
    if not consumption.empty:
        # Get top 10
        top_consumed = consumption.head(10)
        
        # Add return rate
        top_consumed['return_rate'] = (
            top_consumed['total_returned'] / top_consumed['total_issued'] * 100
        ).fillna(0)
        
        # Format for display
        display_cols = {
            "material_name": "Material",
            "total_issued": st.column_config.NumberColumn("Issued", format="%.2f"),
            "total_returned": st.column_config.NumberColumn("Returned", format="%.2f"),
            "total_consumed": st.column_config.NumberColumn("Consumed", format="%.2f"),
            "return_rate": st.column_config.NumberColumn("Return %", format="%.1f")
        }
        
        st.dataframe(
            top_consumed[list(display_cols.keys())],
            use_container_width=True,
            hide_index=True,
            column_config=display_cols
        )
    else:
        st.info("No consumption data available")
    
    # Recent activities
    st.markdown("### Recent Production Activities")
    recent = prod_manager.get_recent_activities(limit=10)
    if not recent.empty:
        # Format timestamps
        recent['timestamp'] = pd.to_datetime(recent['timestamp']).dt.strftime('%Y-%m-%d %H:%M')
        
        st.dataframe(
            recent[['activity', 'reference', 'timestamp']],
            use_container_width=True,
            hide_index=True,
            column_config={
                "activity": "Activity",
                "reference": "Reference",
                "timestamp": "Time"
            }
        )
    else:
        st.info("No recent activities")

# Footer
st.markdown("---")
st.caption("Manufacturing Module v1.0 - Production Management")