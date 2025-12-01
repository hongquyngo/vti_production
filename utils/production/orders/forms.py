# utils/production/orders/forms.py
"""
Form components for Orders domain
Create and Edit order forms

Version: 1.0.0
"""

import logging
from typing import Dict, Any, Optional
import time

import streamlit as st
import pandas as pd

from .queries import OrderQueries
from .manager import OrderManager
from .common import (
    format_number, create_status_indicator, get_vietnam_today,
    OrderValidator, show_message, format_material_display
)

logger = logging.getLogger(__name__)


class OrderForms:
    """Form components for Order management"""
    
    def __init__(self):
        self.queries = OrderQueries()
        self.manager = OrderManager()
    
    # ==================== Create Order Form ====================
    
    def render_create_form(self):
        """Render create new order form"""
        st.subheader("➕ Create New Production Order")
        
        # Step 1: Select BOM
        st.markdown("### 1️⃣ Select BOM")
        
        bom_list = self.queries.get_active_boms()
        
        if bom_list.empty:
            st.error("❌ No active BOMs available. Please create a BOM first.")
            return
        
        # Create BOM options
        bom_options = {
            f"{row['bom_name']} | {row['pt_code']} - {row['product_name']} ({row['bom_type']})": row['id']
            for _, row in bom_list.iterrows()
        }
        
        selected_bom_label = st.selectbox(
            "Select BOM",
            options=list(bom_options.keys()),
            key="create_order_bom"
        )
        
        selected_bom_id = bom_options[selected_bom_label]
        bom_info = self.queries.get_bom_info(selected_bom_id)
        
        if not bom_info:
            st.error("❌ BOM details not found")
            return
        
        # Show BOM info
        col1, col2, col3 = st.columns(3)
        with col1:
            st.info(f"**Product:** {bom_info['product_name']}")
        with col2:
            st.info(f"**Type:** {bom_info['bom_type']}")
        with col3:
            st.info(f"**Output:** {bom_info['output_qty']} {bom_info['uom']}")
        
        st.markdown("---")
        
        # Step 2: Order Details
        st.markdown("### 2️⃣ Order Details")
        
        col1, col2 = st.columns(2)
        
        with col1:
            planned_qty = st.number_input(
                "Planned Quantity *",
                min_value=0.01,
                value=float(bom_info.get('output_qty', 1)),
                step=1.0,
                format="%.2f",
                key="create_order_qty"
            )
            
            scheduled_date = st.date_input(
                "Scheduled Date *",
                value=get_vietnam_today(),
                key="create_order_date"
            )
            
            priority = st.selectbox(
                "Priority",
                options=["LOW", "NORMAL", "HIGH", "URGENT"],
                index=1,
                key="create_order_priority"
            )
        
        with col2:
            warehouses = self.queries.get_warehouses()
            
            if warehouses.empty:
                st.error("❌ No warehouses available")
                return
            
            warehouse_options = {row['name']: row['id'] for _, row in warehouses.iterrows()}
            
            source_warehouse = st.selectbox(
                "Source Warehouse *",
                options=list(warehouse_options.keys()),
                key="create_order_source_wh"
            )
            source_warehouse_id = warehouse_options[source_warehouse]
            
            target_warehouse = st.selectbox(
                "Target Warehouse *",
                options=list(warehouse_options.keys()),
                index=min(1, len(warehouse_options) - 1),
                key="create_order_target_wh"
            )
            target_warehouse_id = warehouse_options[target_warehouse]
            
            notes = st.text_area(
                "Notes",
                height=100,
                key="create_order_notes"
            )
        
        st.markdown("---")
        
        # Step 3: Material Availability Check
        st.markdown("### 3️⃣ Material Availability Check")
        
        with st.spinner("Checking material availability..."):
            availability = self.queries.check_material_availability(
                selected_bom_id, planned_qty, source_warehouse_id
            )
        
        if not availability.empty:
            # Summary metrics
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
            
            # Material details
            with st.expander("📋 View Material Details", expanded=insufficient > 0):
                display_df = availability.copy()
                display_df['material_info'] = display_df.apply(format_material_display, axis=1)
                display_df['required'] = display_df['required_qty'].apply(lambda x: format_number(x, 4))
                display_df['available'] = display_df['available_qty'].apply(lambda x: format_number(x, 4))
                display_df['status'] = display_df['availability_status'].apply(create_status_indicator)
                
                st.dataframe(
                    display_df[['material_info', 'required', 'available', 'status', 'uom']].rename(columns={
                        'material_info': 'Material',
                        'required': 'Required',
                        'available': 'Available',
                        'status': 'Status',
                        'uom': 'UOM'
                    }),
                    use_container_width=True,
                    hide_index=True
                )
            
            # Warning if insufficient materials
            if insufficient > 0:
                st.warning(
                    f"⚠️ **{insufficient} material(s) have insufficient stock.** "
                    "You can still create the order, but materials need to be procured before production."
                )
        
        st.markdown("---")
        
        # Action buttons
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("✅ Create Order", type="primary", use_container_width=True, 
                        key="btn_create_order"):
                self._handle_create_order(
                    bom_info=bom_info,
                    planned_qty=planned_qty,
                    scheduled_date=scheduled_date,
                    priority=priority,
                    source_warehouse_id=source_warehouse_id,
                    target_warehouse_id=target_warehouse_id,
                    notes=notes
                )
        
        with col2:
            if st.button("❌ Cancel", use_container_width=True, key="btn_cancel_create"):
                st.rerun()
    
    def _handle_create_order(self, bom_info: Dict, planned_qty: float,
                            scheduled_date, priority: str,
                            source_warehouse_id: int, target_warehouse_id: int,
                            notes: str):
        """Handle create order button click"""
        order_data = {
            'bom_header_id': bom_info['id'],
            'product_id': bom_info.get('product_id'),
            'planned_qty': planned_qty,
            'uom': bom_info.get('uom', 'EA'),
            'warehouse_id': source_warehouse_id,
            'target_warehouse_id': target_warehouse_id,
            'scheduled_date': scheduled_date,
            'priority': priority,
            'notes': notes,
            'created_by': st.session_state.get('user_id', 1)
        }
        
        # Validate
        is_valid, error_msg = OrderValidator.validate_create_order(order_data)
        
        if not is_valid:
            st.error(f"❌ Validation Error: {error_msg}")
            return
        
        try:
            with st.spinner("Creating order..."):
                order_no = self.manager.create_order(order_data)
            
            st.success(f"✅ Order **{order_no}** created successfully!")
            st.balloons()
            
            # Show next steps
            st.info("""
            **Next Steps:**
            1. View order details to review materials
            2. Confirm the order when ready
            3. Issue materials to start production
            """)
            
            time.sleep(2)
            st.rerun()
            
        except Exception as e:
            st.error(f"❌ Error creating order: {str(e)}")
            logger.error(f"Order creation failed: {e}", exc_info=True)
    
    # ==================== Edit Order Form ====================
    
    def render_edit_form(self, order: Dict[str, Any]):
        """
        Render edit order form
        
        Args:
            order: Current order data
        """
        st.markdown(f"### ✏️ Edit Order: {order['order_no']}")
        
        # Check if editable
        if not OrderValidator.can_edit(order['status']):
            st.warning(f"⚠️ Cannot edit order with status: {order['status']}")
            return
        
        warehouses = self.queries.get_warehouses()
        if warehouses.empty:
            st.error("❌ No warehouses available")
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
                format="%.2f",
                key="edit_order_qty"
            )
            
            # Parse scheduled date
            current_date = order['scheduled_date']
            if isinstance(current_date, str):
                from datetime import datetime
                current_date = datetime.strptime(current_date, '%Y-%m-%d').date()
            
            new_scheduled_date = st.date_input(
                "Scheduled Date",
                value=current_date,
                key="edit_order_date"
            )
            
            priority_options = ["LOW", "NORMAL", "HIGH", "URGENT"]
            current_priority_idx = priority_options.index(order['priority']) if order['priority'] in priority_options else 1
            new_priority = st.selectbox(
                "Priority",
                options=priority_options,
                index=current_priority_idx,
                key="edit_order_priority"
            )
        
        with col2:
            current_source = warehouse_id_to_name.get(order['warehouse_id'], list(warehouse_options.keys())[0])
            new_source_warehouse = st.selectbox(
                "Source Warehouse",
                options=list(warehouse_options.keys()),
                index=list(warehouse_options.keys()).index(current_source) if current_source in warehouse_options else 0,
                key="edit_order_source_wh"
            )
            new_source_warehouse_id = warehouse_options[new_source_warehouse]
            
            current_target = warehouse_id_to_name.get(order['target_warehouse_id'], list(warehouse_options.keys())[0])
            new_target_warehouse = st.selectbox(
                "Target Warehouse",
                options=list(warehouse_options.keys()),
                index=list(warehouse_options.keys()).index(current_target) if current_target in warehouse_options else 0,
                key="edit_order_target_wh"
            )
            new_target_warehouse_id = warehouse_options[new_target_warehouse]
            
            new_notes = st.text_area(
                "Notes",
                value=order.get('notes', '') or '',
                height=100,
                key="edit_order_notes"
            )
        
        # Warning if quantity changed
        if new_planned_qty != float(order['planned_qty']):
            st.warning("⚠️ Changing planned quantity will recalculate all required materials.")
        
        st.markdown("---")
        
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("💾 Save Changes", type="primary", use_container_width=True,
                        key="btn_save_edit"):
                self._handle_save_edit(
                    order_id=order['id'],
                    order=order,
                    new_planned_qty=new_planned_qty,
                    new_scheduled_date=new_scheduled_date,
                    new_priority=new_priority,
                    new_source_warehouse_id=new_source_warehouse_id,
                    new_target_warehouse_id=new_target_warehouse_id,
                    new_notes=new_notes
                )
        
        with col2:
            if st.button("❌ Cancel", use_container_width=True, key="btn_cancel_edit"):
                st.rerun()
    
    def _handle_save_edit(self, order_id: int, order: Dict,
                         new_planned_qty: float, new_scheduled_date,
                         new_priority: str, new_source_warehouse_id: int,
                         new_target_warehouse_id: int, new_notes: str):
        """Handle save edit button click"""
        from datetime import datetime
        
        # Build update data
        update_data = {}
        
        current_date = order['scheduled_date']
        if isinstance(current_date, str):
            current_date = datetime.strptime(current_date, '%Y-%m-%d').date()
        
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
            st.info("ℹ️ No changes detected")
            return
        
        try:
            user_id = st.session_state.get('user_id', 1)
            success = self.manager.update_order(order_id, update_data, user_id)
            
            if success:
                st.success(f"✅ Order {order['order_no']} updated successfully!")
                time.sleep(1)
                st.rerun()
            else:
                st.error("❌ Failed to update order")
                
        except Exception as e:
            st.error(f"❌ Error: {str(e)}")
            logger.error(f"Order update failed: {e}", exc_info=True)


# Convenience functions

def render_create_form():
    """Render create order form"""
    forms = OrderForms()
    forms.render_create_form()


def render_edit_form(order: Dict[str, Any]):
    """Render edit order form"""
    forms = OrderForms()
    forms.render_edit_form(order)
