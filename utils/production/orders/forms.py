# utils/production/orders/forms.py
"""
Form components for Orders domain
Create and Edit order forms

Version: 2.1.0
Changes:
- v2.1.0: Added alternative materials display in Material Availability Check (Step 3)
          Shows alternatives for PARTIAL/INSUFFICIENT primary materials
- v2.0.1: Added st.form() to prevent unnecessary reruns in Create form (Step 2)
- Added st.form() to prevent unnecessary reruns in Edit form
- Added session state to preserve form values across interactions
- BOM selection remains outside form (needs to reload materials)
- Fixed: Swapped default Source/Target warehouse (Source=RAW, Target=FG)
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
    OrderValidator, show_message, format_material_display, format_product_display
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
        
        # Step 1: Select BOM (outside form - needs to reload materials)
        st.markdown("### 1️⃣ Select BOM")
        
        bom_list = self.queries.get_active_boms()
        
        if bom_list.empty:
            st.error("❌ No active BOMs available. Please create a BOM first.")
            return
        
        # Create BOM options with unified format
        def format_bom_option(row) -> str:
            """Format: BOM_NAME | PT_CODE (LEGACY) | PRODUCT_NAME | PKG_SIZE (BRAND) (TYPE)"""
            pt_code = row.get('pt_code', '') or ''
            legacy = row.get('legacy_pt_code', '') or ''
            legacy_display = legacy if legacy else 'NEW'
            name = row.get('product_name', '')
            pkg = row.get('package_size', '') or ''
            brand = row.get('brand_name', '') or ''
            
            parts = [row['bom_name']]
            if pt_code:
                parts.append(f"{pt_code} ({legacy_display})")
            parts.append(name)
            if pkg or brand:
                size_brand = pkg
                if brand:
                    size_brand = f"{pkg} ({brand})" if pkg else f"({brand})"
                if size_brand:
                    parts.append(size_brand)
            
            return f"{' | '.join(parts)} [{row['bom_type']}]"
        
        bom_options = {
            format_bom_option(row): row['id']
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
        
        # Initialize/reset form data when BOM changes
        if st.session_state.get('create_order_bom_id') != selected_bom_id:
            st.session_state['create_order_bom_id'] = selected_bom_id
            st.session_state['create_order_form_data'] = {
                'planned_qty': float(bom_info.get('output_qty', 1)),
                'scheduled_date': get_vietnam_today(),
                'priority': 'NORMAL',
                'source_warehouse': None,
                'target_warehouse': None,
                'notes': ''
            }
            # Clear material check state when BOM changes
            st.session_state.pop('create_order_materials_checked', None)
            st.session_state.pop('create_order_availability', None)
            st.session_state.pop('create_order_alternatives', None)
            st.session_state.pop('create_order_availability_summary', None)
            st.session_state.pop('create_order_warehouse_ids', None)
        
        # Get warehouses
        warehouses = self.queries.get_warehouses()
        if warehouses.empty:
            st.error("❌ No warehouses available")
            return
        
        warehouse_options = {row['name']: row['id'] for _, row in warehouses.iterrows()}
        warehouse_list = list(warehouse_options.keys())
        
        # Set default warehouses if not set
        # FIXED: Source = RAW (index 1), Target = FG (index 0)
        form_data = st.session_state['create_order_form_data']
        if form_data['source_warehouse'] is None:
            form_data['source_warehouse'] = warehouse_list[min(1, len(warehouse_list) - 1)]
        if form_data['target_warehouse'] is None:
            form_data['target_warehouse'] = warehouse_list[0]
        
        # ========== FORM - Prevents reruns when changing inputs ==========
        st.markdown("### 2️⃣ Order Details")
        st.caption("💡 Fill in order details. **No page reload when changing values!**")
        
        with st.form(key="create_order_form", clear_on_submit=False):
            col1, col2 = st.columns(2)
            
            with col1:
                planned_qty = st.number_input(
                    "Planned Quantity *",
                    min_value=0.01,
                    value=float(form_data['planned_qty']),
                    step=1.0,
                    format="%.2f",
                    key="form_create_order_qty"
                )
                
                scheduled_date = st.date_input(
                    "Scheduled Date *",
                    value=form_data['scheduled_date'],
                    key="form_create_order_date"
                )
                
                priority_options = ["LOW", "NORMAL", "HIGH", "URGENT"]
                priority_idx = priority_options.index(form_data['priority']) if form_data['priority'] in priority_options else 1
                priority = st.selectbox(
                    "Priority",
                    options=priority_options,
                    index=priority_idx,
                    key="form_create_order_priority"
                )
            
            with col2:
                source_idx = warehouse_list.index(form_data['source_warehouse']) if form_data['source_warehouse'] in warehouse_list else 0
                source_warehouse = st.selectbox(
                    "Source Warehouse *",
                    options=warehouse_list,
                    index=source_idx,
                    key="form_create_order_source_wh"
                )
                
                target_idx = warehouse_list.index(form_data['target_warehouse']) if form_data['target_warehouse'] in warehouse_list else 0
                target_warehouse = st.selectbox(
                    "Target Warehouse *",
                    options=warehouse_list,
                    index=target_idx,
                    key="form_create_order_target_wh"
                )
                
                notes = st.text_area(
                    "Notes",
                    value=form_data['notes'],
                    height=100,
                    key="form_create_order_notes"
                )
            
            st.markdown("---")
            
            # Form submit buttons
            col1, col2 = st.columns(2)
            
            with col1:
                check_materials_btn = st.form_submit_button(
                    "📋 Check Materials & Create",
                    type="primary",
                    use_container_width=True
                )
            
            with col2:
                reset_btn = st.form_submit_button(
                    "🔄 Reset Form",
                    use_container_width=True
                )
        
        # Handle form submission
        if reset_btn:
            # FIXED: Source = RAW (index 1), Target = FG (index 0)
            st.session_state['create_order_form_data'] = {
                'planned_qty': float(bom_info.get('output_qty', 1)),
                'scheduled_date': get_vietnam_today(),
                'priority': 'NORMAL',
                'source_warehouse': warehouse_list[min(1, len(warehouse_list) - 1)],
                'target_warehouse': warehouse_list[0],
                'notes': ''
            }
            # Clear material check state
            st.session_state.pop('create_order_materials_checked', None)
            st.session_state.pop('create_order_availability', None)
            st.session_state.pop('create_order_alternatives', None)
            st.session_state.pop('create_order_availability_summary', None)
            st.session_state.pop('create_order_warehouse_ids', None)
            st.rerun()
        
        if check_materials_btn:
            # Save form data to session state
            st.session_state['create_order_form_data'] = {
                'planned_qty': planned_qty,
                'scheduled_date': scheduled_date,
                'priority': priority,
                'source_warehouse': source_warehouse,
                'target_warehouse': target_warehouse,
                'notes': notes
            }
            
            source_warehouse_id = warehouse_options[source_warehouse]
            target_warehouse_id = warehouse_options[target_warehouse]
            
            # Check material availability WITH ALTERNATIVES
            with st.spinner("Checking material availability..."):
                result = self.queries.check_material_availability_with_alternatives(
                    selected_bom_id, planned_qty, source_warehouse_id
                )
            
            # Store results in session state
            st.session_state['create_order_materials_checked'] = True
            st.session_state['create_order_availability'] = result['primary']
            st.session_state['create_order_alternatives'] = result['alternatives']
            st.session_state['create_order_availability_summary'] = result['summary']
            st.session_state['create_order_warehouse_ids'] = {
                'source': source_warehouse_id,
                'target': target_warehouse_id
            }
            st.rerun()  # Rerun to show Step 3
        
        # Step 3: Show Material Check Results (based on session state, not button click)
        if st.session_state.get('create_order_materials_checked'):
            availability = st.session_state.get('create_order_availability', pd.DataFrame())
            alternatives = st.session_state.get('create_order_alternatives', pd.DataFrame())
            summary = st.session_state.get('create_order_availability_summary', {})
            warehouse_ids = st.session_state.get('create_order_warehouse_ids', {})
            
            st.markdown("---")
            st.markdown("### 3️⃣ Material Availability Check")
            
            if not availability.empty:
                # Summary metrics - Enhanced with alternatives info
                total = summary.get('total', len(availability))
                sufficient = summary.get('sufficient', 0)
                partial = summary.get('partial', 0)
                insufficient = summary.get('insufficient', 0)
                has_sufficient_alt = summary.get('has_sufficient_alternatives', 0)
                
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Total Materials", total)
                with col2:
                    st.metric("✅ Sufficient", sufficient)
                with col3:
                    # Show partial/insufficient with alternatives info
                    needs_attention = partial + insufficient
                    if needs_attention > 0 and has_sufficient_alt > 0:
                        st.metric("⚠️ Partial", partial, 
                                 delta=f"{has_sufficient_alt} có alt ✓", 
                                 delta_color="off")
                    else:
                        st.metric("⚠️ Partial", partial)
                with col4:
                    st.metric("❌ Insufficient", insufficient)
                
                # ==================== PRIMARY MATERIALS ====================
                with st.expander("📋 View Material Details (Primary)", expanded=insufficient > 0 or partial > 0):
                    display_df = availability.copy()
                    display_df['material_info'] = display_df.apply(format_material_display, axis=1)
                    display_df['required'] = display_df['required_qty'].apply(lambda x: format_number(x, 4))
                    display_df['available'] = display_df['available_qty'].apply(lambda x: format_number(x, 4))
                    display_df['status'] = display_df['availability_status'].apply(create_status_indicator)
                    display_df['type'] = '🔵 Primary'
                    
                    st.dataframe(
                        display_df[['type', 'material_info', 'required', 'available', 'status', 'uom']].rename(columns={
                            'type': 'Type',
                            'material_info': 'Material',
                            'required': 'Required',
                            'available': 'Available',
                            'status': 'Status',
                            'uom': 'UOM'
                        }),
                        use_container_width=True,
                        hide_index=True
                    )
                
                # ==================== ALTERNATIVE MATERIALS ====================
                if not alternatives.empty:
                    with st.expander("🔄 Alternative Materials", expanded=True):
                        num_alts = len(alternatives)
                        num_primary_with_alts = alternatives['bom_detail_id'].nunique()
                        st.info(f"💡 **{num_alts}** alternative material(s) found for **{num_primary_with_alts}** item(s) with insufficient/partial stock")
                        
                        # Group alternatives by primary material
                        for bom_detail_id in alternatives['bom_detail_id'].unique():
                            # Get primary material info
                            primary_row = availability[availability['bom_detail_id'] == bom_detail_id]
                            if not primary_row.empty:
                                primary_info = primary_row.iloc[0]
                                primary_name = format_material_display(primary_info)
                                primary_status = primary_info['availability_status']
                                
                                st.markdown(f"**Primary:** {primary_name} — {create_status_indicator(primary_status)}")
                                
                                # Get alternatives for this primary
                                alt_rows = alternatives[alternatives['bom_detail_id'] == bom_detail_id].copy()
                                
                                if not alt_rows.empty:
                                    alt_rows['material_info'] = alt_rows.apply(format_material_display, axis=1)
                                    alt_rows['required'] = alt_rows['required_qty'].apply(lambda x: format_number(x, 4))
                                    alt_rows['available'] = alt_rows['available_qty'].apply(lambda x: format_number(x, 4))
                                    alt_rows['status'] = alt_rows['availability_status'].apply(create_status_indicator)
                                    alt_rows['priority_display'] = alt_rows['alt_priority'].apply(lambda x: f"Alt #{x}")
                                    # Show scrap rate instead of conversion rate
                                    alt_rows['scrap'] = alt_rows['alt_scrap_rate'].apply(
                                        lambda x: f"+{x:.1f}%" if x and x > 0 else "0%"
                                    )
                                    
                                    st.dataframe(
                                        alt_rows[['priority_display', 'material_info', 'required', 'available', 'status', 'scrap', 'uom']].rename(columns={
                                            'priority_display': 'Priority',
                                            'material_info': 'Alternative Material',
                                            'required': 'Required',
                                            'available': 'Available',
                                            'status': 'Status',
                                            'scrap': 'Scrap%',
                                            'uom': 'UOM'
                                        }),
                                        use_container_width=True,
                                        hide_index=True
                                    )
                                
                                st.markdown("---")
                
                # Warning messages with alternatives context
                if insufficient > 0:
                    if has_sufficient_alt > 0:
                        st.warning(
                            f"⚠️ **{insufficient} material(s)** have insufficient stock, "
                            f"but **{has_sufficient_alt}** have sufficient alternatives available. "
                            "You can proceed with alternatives or wait for procurement."
                        )
                    else:
                        st.warning(
                            f"⚠️ **{insufficient} material(s)** have insufficient stock. "
                            "You can still create the order, but materials need to be procured before production."
                        )
                elif partial > 0:
                    if has_sufficient_alt > 0:
                        st.info(
                            f"ℹ️ **{partial} material(s)** have partial stock. "
                            f"**{has_sufficient_alt}** have sufficient alternatives available."
                        )
                    else:
                        st.info(
                            f"ℹ️ **{partial} material(s)** have partial stock. "
                            "Consider checking alternative materials or procurement."
                        )
            
            st.markdown("---")
            
            # Confirm creation buttons (NOW they persist across reruns!)
            col1, col2 = st.columns(2)
            
            with col1:
                if st.button("✅ Create Order", type="primary", use_container_width=True, 
                            key="btn_confirm_create_order"):
                    # Get form data from session state
                    form_data = st.session_state.get('create_order_form_data', {})
                    self._handle_create_order(
                        bom_info=bom_info,
                        planned_qty=form_data.get('planned_qty', 1.0),
                        scheduled_date=form_data.get('scheduled_date', get_vietnam_today()),
                        priority=form_data.get('priority', 'NORMAL'),
                        source_warehouse_id=warehouse_ids.get('source'),
                        target_warehouse_id=warehouse_ids.get('target'),
                        notes=form_data.get('notes', '')
                    )
            
            with col2:
                if st.button("❌ Cancel", use_container_width=True, key="btn_cancel_create"):
                    st.session_state.pop('create_order_form_data', None)
                    st.session_state.pop('create_order_bom_id', None)
                    st.session_state.pop('create_order_materials_checked', None)
                    st.session_state.pop('create_order_availability', None)
                    st.session_state.pop('create_order_alternatives', None)
                    st.session_state.pop('create_order_availability_summary', None)
                    st.session_state.pop('create_order_warehouse_ids', None)
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
            
            # Clear all form data
            st.session_state.pop('create_order_form_data', None)
            st.session_state.pop('create_order_bom_id', None)
            st.session_state.pop('create_order_materials_checked', None)
            st.session_state.pop('create_order_availability', None)
            st.session_state.pop('create_order_alternatives', None)
            st.session_state.pop('create_order_availability_summary', None)
            st.session_state.pop('create_order_warehouse_ids', None)
            
            # Set success state and go back to list
            st.session_state['order_created_success'] = order_no
            st.session_state['orders_view'] = 'list'
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
        warehouse_list = list(warehouse_options.keys())
        
        # Initialize form data for this order
        if st.session_state.get('edit_order_id') != order['id']:
            st.session_state['edit_order_id'] = order['id']
            
            # Parse scheduled date
            current_date = order['scheduled_date']
            if isinstance(current_date, str):
                from datetime import datetime
                current_date = datetime.strptime(current_date, '%Y-%m-%d').date()
            
            st.session_state['edit_order_form_data'] = {
                'planned_qty': float(order['planned_qty']),
                'scheduled_date': current_date,
                'priority': order['priority'],
                'source_warehouse': warehouse_id_to_name.get(order['warehouse_id'], warehouse_list[0]),
                'target_warehouse': warehouse_id_to_name.get(order['target_warehouse_id'], warehouse_list[0]),
                'notes': order.get('notes', '') or ''
            }
        
        form_data = st.session_state['edit_order_form_data']
        
        st.caption("💡 Edit order details. **No page reload when changing values!**")
        
        # ========== FORM - Prevents reruns when changing inputs ==========
        with st.form(key="edit_order_form", clear_on_submit=False):
            col1, col2 = st.columns(2)
            
            with col1:
                new_planned_qty = st.number_input(
                    "Planned Quantity",
                    min_value=0.01,
                    value=float(form_data['planned_qty']),
                    step=1.0,
                    format="%.2f",
                    key="form_edit_order_qty"
                )
                
                new_scheduled_date = st.date_input(
                    "Scheduled Date",
                    value=form_data['scheduled_date'],
                    key="form_edit_order_date"
                )
                
                priority_options = ["LOW", "NORMAL", "HIGH", "URGENT"]
                current_priority_idx = priority_options.index(form_data['priority']) if form_data['priority'] in priority_options else 1
                new_priority = st.selectbox(
                    "Priority",
                    options=priority_options,
                    index=current_priority_idx,
                    key="form_edit_order_priority"
                )
            
            with col2:
                source_idx = warehouse_list.index(form_data['source_warehouse']) if form_data['source_warehouse'] in warehouse_list else 0
                new_source_warehouse = st.selectbox(
                    "Source Warehouse",
                    options=warehouse_list,
                    index=source_idx,
                    key="form_edit_order_source_wh"
                )
                
                target_idx = warehouse_list.index(form_data['target_warehouse']) if form_data['target_warehouse'] in warehouse_list else 0
                new_target_warehouse = st.selectbox(
                    "Target Warehouse",
                    options=warehouse_list,
                    index=target_idx,
                    key="form_edit_order_target_wh"
                )
                
                new_notes = st.text_area(
                    "Notes",
                    value=form_data['notes'],
                    height=100,
                    key="form_edit_order_notes"
                )
            
            # Warning about quantity change (shown inside form)
            if new_planned_qty != float(order['planned_qty']):
                st.warning("⚠️ Changing planned quantity will recalculate all required materials.")
            
            st.markdown("---")
            
            # Form submit buttons
            col1, col2 = st.columns(2)
            
            with col1:
                save_btn = st.form_submit_button(
                    "💾 Save Changes",
                    type="primary",
                    use_container_width=True
                )
            
            with col2:
                cancel_btn = st.form_submit_button(
                    "❌ Cancel",
                    use_container_width=True
                )
        
        # Handle form submission
        if cancel_btn:
            st.session_state.pop('edit_order_form_data', None)
            st.session_state.pop('edit_order_id', None)
            st.rerun()
        
        if save_btn:
            # Update form data in session state
            st.session_state['edit_order_form_data'] = {
                'planned_qty': new_planned_qty,
                'scheduled_date': new_scheduled_date,
                'priority': new_priority,
                'source_warehouse': new_source_warehouse,
                'target_warehouse': new_target_warehouse,
                'notes': new_notes
            }
            
            self._handle_save_edit(
                order_id=order['id'],
                order=order,
                new_planned_qty=new_planned_qty,
                new_scheduled_date=new_scheduled_date,
                new_priority=new_priority,
                new_source_warehouse_id=warehouse_options[new_source_warehouse],
                new_target_warehouse_id=warehouse_options[new_target_warehouse],
                new_notes=new_notes
            )
    
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
                # Clear form data
                st.session_state.pop('edit_order_form_data', None)
                st.session_state.pop('edit_order_id', None)
                
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