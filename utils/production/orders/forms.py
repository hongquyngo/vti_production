# utils/production/orders/forms.py
"""
Form components for Orders domain
Create and Edit order forms with comprehensive validation

Version: 5.1.0
Changes:
- v5.1.0: Fixed validation results not showing after clicking Validate button
          + Merged validation results rendering INTO _fragment_order_details
          + Removed separate _render_validation_results fragment
          + Now only fragment reruns when validating (not full page)
- v5.0.0: Integrated comprehensive validation module
          + Create form now shows all validation warnings before submission
          + Edit form validates and shows warnings
          + Warning acknowledgment required before proceeding
- v4.0.0: Applied Fragment pattern to minimize reruns
- v3.0.0: Refactored Create Order flow to Product-first selection
"""

import logging
from typing import Dict, Any, Optional
import time

import streamlit as st
import pandas as pd

from .queries import OrderQueries
from .manager import OrderManager
from .validators import ValidationResults
from .validation_ui import (
    render_validation_blocks, render_validation_warnings,
    render_warning_acknowledgment
)
from .common import (
    format_number, create_status_indicator, get_vietnam_today,
    format_material_display, format_product_display,
    calculate_percentage
)

logger = logging.getLogger(__name__)


class OrderForms:
    """Form components for Order management"""
    
    def __init__(self):
        self.queries = OrderQueries()
        self.manager = OrderManager()
    
    # ==================== Create Order Form - FRAGMENTED ====================
    
    def render_create_form(self):
        """
        Render create new order form with Product-first selection
        Uses fragments to minimize reruns and improve UX
        """
        st.subheader("➕ Create New Production Order")
        
        # Initialize session state for create form
        if 'create_form_product_id' not in st.session_state:
            st.session_state.create_form_product_id = None
        if 'create_form_bom_id' not in st.session_state:
            st.session_state.create_form_bom_id = None
        if 'create_validation_results' not in st.session_state:
            st.session_state.create_validation_results = None
        if 'create_warnings_acknowledged' not in st.session_state:
            st.session_state.create_warnings_acknowledged = False
        
        # Fragment 1: Product Selection
        self._fragment_product_selection()
        
        # Only show next steps if product is selected
        if st.session_state.create_form_product_id:
            st.markdown("---")
            
            # Fragment 2: BOM Selection
            self._fragment_bom_selection()
            
            # Only show order details if BOM is selected
            if st.session_state.create_form_bom_id:
                st.markdown("---")
                
                # Fragment 3: Order Details Form + Validation Results (all in one fragment)
                self._fragment_order_details()
    
    @st.fragment
    def _fragment_product_selection(self):
        """
        Fragment 1: Product Selection
        Isolated rerun when searching/selecting product
        """
        st.markdown("### 1️⃣ Select Product")
        
        # Get products with active BOMs
        products_df = self.queries.get_products_with_active_boms()
        
        if products_df.empty:
            st.error("❌ No products with active BOMs available. Please create a BOM first.")
            return
        
        # Format product options
        def format_product_option(row) -> str:
            """Format: PT_CODE (LEGACY) | PRODUCT_NAME | PKG_SIZE (BRAND)"""
            pt_code = row.get('pt_code', '') or ''
            legacy = row.get('legacy_pt_code', '') or ''
            legacy_display = legacy if legacy else 'NEW'
            name = row.get('product_name', '')
            pkg = row.get('package_size', '') or ''
            brand = row.get('brand_name', '') or ''
            active_count = row.get('active_bom_count', 0)
            
            parts = []
            if pt_code:
                parts.append(f"{pt_code} ({legacy_display})")
            parts.append(name)
            if pkg or brand:
                size_brand = pkg
                if brand:
                    size_brand = f"{pkg} ({brand})" if pkg else f"({brand})"
                if size_brand:
                    parts.append(size_brand)
            
            # Add BOM count indicator if multiple
            result = " | ".join(parts)
            if active_count > 1:
                result += f" ⚠️ [{active_count} BOMs]"
            
            return result
        
        product_options = {
            format_product_option(row): row['product_id']
            for _, row in products_df.iterrows()
        }
        
        # Get current selection index
        current_product_id = st.session_state.create_form_product_id
        current_index = 0
        if current_product_id:
            # Find index of current selection
            for idx, (label, pid) in enumerate(product_options.items()):
                if pid == current_product_id:
                    current_index = idx
                    break
        
        # Selectbox has built-in search - just type to filter
        selected_product_label = st.selectbox(
            "Select Product",
            options=list(product_options.keys()),
            index=current_index,
            key="fragment_product_select",
            help="Type to search by code, name, or brand"
        )
        
        selected_product_id = product_options[selected_product_label]
        
        # Update session state only if changed
        if st.session_state.create_form_product_id != selected_product_id:
            st.session_state.create_form_product_id = selected_product_id
            st.session_state.create_form_bom_id = None  # Reset BOM selection
            st.session_state.create_validation_results = None  # Reset validation
            st.session_state.create_warnings_acknowledged = False
            st.rerun()
        
        # Get product info and check for conflicts
        product_row = products_df[products_df['product_id'] == selected_product_id].iloc[0]
        active_bom_count = product_row['active_bom_count']
        total_bom_count = product_row['total_bom_count']
        
        # Show product info
        col1, col2, col3 = st.columns(3)
        with col1:
            st.info(f"**PT Code:** {product_row['pt_code'] or 'N/A'}")
        with col2:
            st.info(f"**Brand:** {product_row['brand_name'] or 'N/A'}")
        with col3:
            st.info(f"**Package:** {product_row['package_size'] or 'N/A'}")
        
        # BOM CONFLICT CHECK (BLOCKING) - C4
        if active_bom_count > 1:
            st.error(f"""
            🚫 **Cannot Create Order - BOM Conflict Detected! [C4]**
            
            This product has **{active_bom_count} active BOMs** (total: {total_bom_count}).
            
            **Action Required:**
            1. Go to BOM Management
            2. Review the BOMs for this product
            3. Set only ONE BOM as ACTIVE
            4. Return here to create the order
            
            ⚠️ Orders cannot be created for products with multiple active BOMs to ensure production consistency.
            """)
            
            # Show list of active BOMs for this product
            with st.expander("📋 View Active BOMs for this Product"):
                boms_for_product = self.queries.get_boms_by_product(selected_product_id, active_only=True)
                if not boms_for_product.empty:
                    st.dataframe(
                        boms_for_product[['bom_code', 'bom_name', 'bom_type', 'output_qty', 'uom', 'status']].rename(columns={
                            'bom_code': 'BOM Code',
                            'bom_name': 'BOM Name',
                            'bom_type': 'Type',
                            'output_qty': 'Output Qty',
                            'uom': 'UOM',
                            'status': 'Status'
                        }),
                        use_container_width=True,
                        hide_index=True
                    )
            
            # Clear BOM selection if conflict exists
            st.session_state.create_form_bom_id = None
    
    @st.fragment
    def _fragment_bom_selection(self):
        """
        Fragment 2: BOM Selection
        Isolated rerun when selecting BOM
        """
        st.markdown("### 2️⃣ Select BOM")
        
        product_id = st.session_state.create_form_product_id
        
        if not product_id:
            st.warning("⚠️ Please select a product first")
            return
        
        # Check for conflicts first
        product_df = self.queries.get_products_with_active_boms()
        product_row = product_df[product_df['product_id'] == product_id].iloc[0]
        if product_row['active_bom_count'] > 1:
            return  # Don't show BOM selection if conflict exists
        
        # Get BOMs for selected product (active only)
        boms_for_product = self.queries.get_boms_by_product(product_id, active_only=True)
        
        if boms_for_product.empty:
            st.error("❌ No active BOMs found for this product")
            return
        
        # Since we blocked multiple active BOMs, there should be exactly 1
        def format_bom_option(row) -> str:
            """Format: BOM_CODE | BOM_NAME | TYPE | OUTPUT"""
            return f"{row['bom_code']} | {row['bom_name']} | {row['bom_type']} | {row['output_qty']} {row['uom']}"
        
        bom_options = {
            format_bom_option(row): row['id']
            for _, row in boms_for_product.iterrows()
        }
        
        # Get current selection index
        current_bom_id = st.session_state.create_form_bom_id
        current_index = 0
        if current_bom_id:
            for idx, (label, bid) in enumerate(bom_options.items()):
                if bid == current_bom_id:
                    current_index = idx
                    break
        
        selected_bom_label = st.selectbox(
            "Select BOM",
            options=list(bom_options.keys()),
            index=current_index,
            key="fragment_bom_select"
        )
        
        selected_bom_id = bom_options[selected_bom_label]
        
        # Update session state only if changed
        if st.session_state.create_form_bom_id != selected_bom_id:
            st.session_state.create_form_bom_id = selected_bom_id
            st.session_state.create_validation_results = None  # Reset validation
            st.session_state.create_warnings_acknowledged = False
            st.rerun()
        
        # Show BOM details
        bom_row = boms_for_product[boms_for_product['id'] == selected_bom_id].iloc[0]
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.info(f"**Type:** {bom_row['bom_type']}")
        with col2:
            st.info(f"**Output:** {bom_row['output_qty']} {bom_row['uom']}")
        with col3:
            st.info(f"**Status:** {bom_row['status']}")
    
    @st.fragment
    def _fragment_order_details(self):
        """
        Fragment 3: Order Details Form + Validation Results
        
        This fragment includes:
        - Order details form (qty, date, priority, warehouses)
        - Validate button
        - Validation results (blocks, warnings, material check)
        - Create/Cancel buttons
        
        All in one fragment so only this section reruns when validating,
        not the entire page (dashboard, filters, product/BOM selection stay stable)
        """
        st.markdown("### 3️⃣ Order Details")
        
        bom_id = st.session_state.create_form_bom_id
        product_id = st.session_state.create_form_product_id
        
        if not bom_id or not product_id:
            st.warning("⚠️ Please select product and BOM first")
            return
        
        # Get BOM info
        bom_info = self.queries.get_bom_info(bom_id)
        if not bom_info:
            st.error("❌ BOM not found")
            return
        
        # Get warehouses
        warehouses = self.queries.get_warehouses()
        if warehouses.empty:
            st.error("❌ No warehouses available")
            return
        
        warehouse_options = {row['name']: row['id'] for _, row in warehouses.iterrows()}
        warehouse_list = list(warehouse_options.keys())
        
        # Find default warehouses
        raw_wh_idx = 0
        fg_wh_idx = 0
        for idx, name in enumerate(warehouse_list):
            if 'RAW' in name.upper() or 'NGUYÊN' in name.upper():
                raw_wh_idx = idx
            if 'FG' in name.upper() or 'THÀNH' in name.upper():
                fg_wh_idx = idx
        
        # Initialize form data if needed
        if 'create_order_form_data' not in st.session_state:
            st.session_state.create_order_form_data = {
                'planned_qty': float(bom_info['output_qty']),
                'scheduled_date': get_vietnam_today(),
                'priority': 'NORMAL',
                'source_warehouse': warehouse_list[raw_wh_idx],
                'target_warehouse': warehouse_list[fg_wh_idx],
                'notes': ''
            }
        
        form_data = st.session_state.create_order_form_data
        
        st.caption("💡 Fill in order details. Click 'Validate & Check' to see material availability and validation results.")
        
        # ========== FORM - Prevents reruns when changing inputs ==========
        with st.form(key="create_order_details_form", clear_on_submit=False):
            col1, col2 = st.columns(2)
            
            with col1:
                planned_qty = st.number_input(
                    "Planned Quantity",
                    min_value=0.01,
                    value=float(form_data['planned_qty']),
                    step=float(bom_info['output_qty']),
                    format="%.2f",
                    key="form_create_qty",
                    help=f"BOM output: {bom_info['output_qty']} {bom_info['uom']}"
                )
                
                scheduled_date = st.date_input(
                    "Scheduled Date",
                    value=form_data['scheduled_date'],
                    key="form_create_date"
                )
                
                priority_options = ["LOW", "NORMAL", "HIGH", "URGENT"]
                priority_idx = priority_options.index(form_data['priority']) if form_data['priority'] in priority_options else 1
                priority = st.selectbox(
                    "Priority",
                    options=priority_options,
                    index=priority_idx,
                    key="form_create_priority"
                )
            
            with col2:
                source_idx = warehouse_list.index(form_data['source_warehouse']) if form_data['source_warehouse'] in warehouse_list else raw_wh_idx
                source_warehouse = st.selectbox(
                    "Source Warehouse (Materials)",
                    options=warehouse_list,
                    index=source_idx,
                    key="form_create_source_wh",
                    help="Warehouse to issue materials from"
                )
                
                target_idx = warehouse_list.index(form_data['target_warehouse']) if form_data['target_warehouse'] in warehouse_list else fg_wh_idx
                target_warehouse = st.selectbox(
                    "Target Warehouse (Finished Goods)",
                    options=warehouse_list,
                    index=target_idx,
                    key="form_create_target_wh",
                    help="Warehouse to receive finished products"
                )
                
                notes = st.text_area(
                    "Notes (Optional)",
                    value=form_data['notes'],
                    height=100,
                    key="form_create_notes"
                )
            
            st.markdown("---")
            
            # Validate button
            validate_btn = st.form_submit_button(
                "🔍 Validate & Check Materials",
                use_container_width=True,
                help="Validate order data and check material availability"
            )
        
        # Handle validate button
        if validate_btn:
            # Update form data
            st.session_state.create_order_form_data = {
                'planned_qty': planned_qty,
                'scheduled_date': scheduled_date,
                'priority': priority,
                'source_warehouse': source_warehouse,
                'target_warehouse': target_warehouse,
                'notes': notes
            }
            st.session_state.create_warnings_acknowledged = False
            
            # Build order data for validation
            order_data = {
                'bom_header_id': bom_id,
                'product_id': product_id,
                'planned_qty': planned_qty,
                'uom': bom_info['uom'],
                'warehouse_id': warehouse_options[source_warehouse],
                'target_warehouse_id': warehouse_options[target_warehouse],
                'scheduled_date': scheduled_date,
                'priority': priority,
                'notes': notes
            }
            
            # Run validation
            results = self.manager.validate_create(order_data)
            st.session_state.create_validation_results = results
            st.session_state.create_order_data = order_data
            # Fragment will rerun itself - no need for st.rerun()
        
        # === VALIDATION RESULTS - RENDERED INSIDE FRAGMENT ===
        if st.session_state.get('create_validation_results'):
            st.markdown("---")
            self._render_validation_results_inline()
        
    def _render_validation_results_inline(self):
        """
        Render validation results inline (called from within _fragment_order_details)
        NOT a separate fragment - rendered inside the order details fragment
        """
        results = st.session_state.create_validation_results
        order_data = st.session_state.get('create_order_data', {})
        
        st.markdown("### 4️⃣ Validation Results")
        
        # Show blocking errors
        if results.has_blocks:
            render_validation_blocks(results, language='en')
            st.error("❌ Cannot create order due to blocking errors above.")
            return
        
        # Show material availability
        bom_id = order_data.get('bom_header_id')
        quantity = order_data.get('planned_qty', 0)
        warehouse_id = order_data.get('warehouse_id')
        
        if all([bom_id, quantity, warehouse_id]):
            self._render_material_check(bom_id, quantity, warehouse_id)
        
        # Show warnings if any
        if results.has_warnings:
            st.markdown("---")
            st.markdown("### ⚠️ Validation Warnings")
            render_validation_warnings(results, language='en')
            
            # Acknowledgment checkbox
            st.markdown("---")
            acknowledged = st.checkbox(
                "☑️ I understand the warnings and want to proceed with order creation",
                value=st.session_state.get('create_warnings_acknowledged', False),
                key="create_warnings_ack_checkbox"
            )
            st.session_state.create_warnings_acknowledged = acknowledged
        else:
            acknowledged = True
            st.success("✅ All validations passed!")
        
        # Create Order button
        st.markdown("---")
        
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("✅ Create Order", type="primary", use_container_width=True,
                        disabled=not acknowledged, key="btn_create_order_final"):
                self._handle_create_order()
        
        with col2:
            if st.button("❌ Cancel", use_container_width=True, key="btn_cancel_create"):
                # Clear session state
                st.session_state.create_form_product_id = None
                st.session_state.create_form_bom_id = None
                st.session_state.pop('create_order_form_data', None)
                st.session_state.pop('create_validation_results', None)
                st.session_state.pop('create_order_data', None)
                st.session_state.create_warnings_acknowledged = False
                st.session_state.orders_view = 'list'
                st.rerun()
    
    def _render_material_check(self, bom_id: int, quantity: float, warehouse_id: int):
        """Render material availability check"""
        st.markdown("### 📦 Material Availability")
        
        with st.spinner("Checking material availability..."):
            result = self.queries.check_material_availability_with_alternatives(
                bom_id, quantity, warehouse_id
            )
        
        primary_df = result['primary']
        alternatives_df = result['alternatives']
        summary = result['summary']
        
        if primary_df.empty:
            st.warning("⚠️ No materials found for this BOM")
            return
        
        # Summary metrics
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Materials", summary['total'])
        
        with col2:
            delta_color = "normal" if summary['sufficient'] == summary['total'] else "inverse"
            st.metric(
                "✅ Sufficient",
                summary['sufficient'],
                delta=f"{calculate_percentage(summary['sufficient'], summary['total'])}%",
                delta_color=delta_color
            )
        
        with col3:
            if summary['partial'] > 0:
                st.metric("⚠️ Partial", summary['partial'], delta_color="off")
            else:
                st.metric("⚠️ Partial", summary['partial'])
        
        with col4:
            if summary['insufficient'] > 0:
                st.metric("❌ Insufficient", summary['insufficient'], delta_color="inverse")
            else:
                st.metric("❌ Insufficient", summary['insufficient'])
        
        # Primary materials table
        st.markdown("**Primary Materials:**")
        
        display_df = primary_df.copy()
        display_df['material_info'] = display_df.apply(format_material_display, axis=1)
        display_df['required'] = display_df['required_qty'].apply(lambda x: format_number(x, 4))
        display_df['available'] = display_df['available_qty'].apply(lambda x: format_number(x, 4))
        display_df['status_display'] = display_df['availability_status'].apply(create_status_indicator)
        
        st.dataframe(
            display_df[['material_info', 'required', 'available', 'status_display', 'uom']].rename(columns={
                'material_info': 'Material',
                'required': 'Required',
                'available': 'Available',
                'status_display': 'Status',
                'uom': 'UOM'
            }),
            use_container_width=True,
            hide_index=True
        )
        
        # Show alternatives if any
        if not alternatives_df.empty and summary['has_alternatives'] > 0:
            st.markdown("---")
            st.markdown("**Alternative Materials Available:**")
            st.info(f"ℹ️ Found alternatives for **{summary['has_alternatives']}** material(s) with partial/insufficient stock")
            
            with st.expander("📦 View Alternative Materials", expanded=False):
                for bom_detail_id in alternatives_df['bom_detail_id'].unique():
                    alt_for_material = alternatives_df[alternatives_df['bom_detail_id'] == bom_detail_id]
                    
                    primary_material = primary_df[primary_df['bom_detail_id'] == bom_detail_id].iloc[0]
                    st.markdown(f"**For:** {format_material_display(primary_material)}")
                    
                    alt_display = alt_for_material.copy()
                    alt_display['alt_info'] = alt_display.apply(format_material_display, axis=1)
                    alt_display['required'] = alt_display['required_qty'].apply(lambda x: format_number(x, 4))
                    alt_display['available'] = alt_display['available_qty'].apply(lambda x: format_number(x, 4))
                    alt_display['status_display'] = alt_display['availability_status'].apply(create_status_indicator)
                    
                    st.dataframe(
                        alt_display[['alt_priority', 'alt_info', 'required', 'available', 'status_display', 'uom']].rename(columns={
                            'alt_priority': 'Priority',
                            'alt_info': 'Alternative Material',
                            'required': 'Required',
                            'available': 'Available',
                            'status_display': 'Status',
                            'uom': 'UOM'
                        }),
                        use_container_width=True,
                        hide_index=True
                    )
                    st.markdown("---")
    
    def _handle_create_order(self):
        """Handle create order button click"""
        try:
            order_data = st.session_state.get('create_order_data', {})
            
            if not order_data:
                st.error("❌ No order data available. Please fill the form again.")
                return
            
            # Add user_id
            order_data['created_by'] = st.session_state.get('user_id', 1)
            
            # Create order (skip_warnings=True since user already acknowledged)
            order_no, results = self.manager.create_order(order_data, skip_warnings=True)
            
            if order_no:
                # Clear session state
                st.session_state.create_form_product_id = None
                st.session_state.create_form_bom_id = None
                st.session_state.pop('create_order_form_data', None)
                st.session_state.pop('create_validation_results', None)
                st.session_state.pop('create_order_data', None)
                st.session_state.create_warnings_acknowledged = False
                
                # Set success flag
                st.session_state.order_created_success = order_no
                st.session_state.orders_view = 'list'
                
                time.sleep(0.5)
                st.rerun()
            else:
                st.error("❌ Failed to create order")
            
        except ValueError as e:
            st.error(f"❌ Validation Error: {str(e)}")
            logger.error(f"Order creation validation failed: {e}")
        except Exception as e:
            st.error(f"❌ Error creating order: {str(e)}")
            logger.error(f"Order creation failed: {e}", exc_info=True)
    
    # ==================== Edit Order Form ====================
    
    def render_edit_form(self, order: Dict[str, Any]):
        """
        Render edit order form with validation
        
        Args:
            order: Current order data
        """
        st.markdown(f"### ✏️ Edit Order: {order['order_no']}")
        
        # E1: Check if editable (status check)
        if order['status'] not in ['DRAFT', 'CONFIRMED']:
            st.error(f"🚫 **[E1]** Cannot edit order with status: {order['status']}")
            st.info("Only DRAFT or CONFIRMED orders can be edited.")
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
            st.session_state['edit_validation_results'] = None
            st.session_state['edit_warnings_acknowledged'] = False
        
        form_data = st.session_state['edit_order_form_data']
        
        st.caption("💡 Edit order details. Click 'Validate Changes' to check before saving.")
        
        # ========== FORM ==========
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
            
            st.markdown("---")
            
            col1, col2 = st.columns(2)
            
            with col1:
                validate_btn = st.form_submit_button(
                    "🔍 Validate Changes",
                    use_container_width=True
                )
            
            with col2:
                cancel_btn = st.form_submit_button(
                    "❌ Cancel",
                    use_container_width=True
                )
        
        # Handle cancel
        if cancel_btn:
            st.session_state.pop('edit_order_form_data', None)
            st.session_state.pop('edit_order_id', None)
            st.session_state.pop('edit_validation_results', None)
            st.session_state.pop('edit_update_data', None)
            st.rerun()
        
        # Handle validate
        if validate_btn:
            # Build update data
            update_data = {}
            
            from datetime import datetime
            current_date = order['scheduled_date']
            if isinstance(current_date, str):
                current_date = datetime.strptime(current_date, '%Y-%m-%d').date()
            
            if new_planned_qty != float(order['planned_qty']):
                update_data['planned_qty'] = new_planned_qty
            if new_scheduled_date != current_date:
                update_data['scheduled_date'] = new_scheduled_date
            if new_priority != order['priority']:
                update_data['priority'] = new_priority
            if warehouse_options[new_source_warehouse] != order['warehouse_id']:
                update_data['warehouse_id'] = warehouse_options[new_source_warehouse]
            if warehouse_options[new_target_warehouse] != order['target_warehouse_id']:
                update_data['target_warehouse_id'] = warehouse_options[new_target_warehouse]
            if new_notes != (order.get('notes', '') or ''):
                update_data['notes'] = new_notes
            
            if not update_data:
                st.info("ℹ️ No changes detected")
                return
            
            # Run validation
            results = self.manager.validate_update(order['id'], update_data)
            st.session_state['edit_validation_results'] = results
            st.session_state['edit_update_data'] = update_data
            st.session_state['edit_warnings_acknowledged'] = False
            
            # Update form data
            st.session_state['edit_order_form_data'] = {
                'planned_qty': new_planned_qty,
                'scheduled_date': new_scheduled_date,
                'priority': new_priority,
                'source_warehouse': new_source_warehouse,
                'target_warehouse': new_target_warehouse,
                'notes': new_notes
            }
        
        # Show validation results
        if st.session_state.get('edit_validation_results'):
            self._render_edit_validation_results(order)
    
    @st.fragment
    def _render_edit_validation_results(self, order: Dict[str, Any]):
        """
        Fragment: Edit Validation Results
        Isolated rerun when acknowledging warnings
        """
        results = st.session_state['edit_validation_results']
        update_data = st.session_state.get('edit_update_data', {})
        
        st.markdown("---")
        st.markdown("### Validation Results")
        
        # Show blocking errors
        if results.has_blocks:
            render_validation_blocks(results, language='en')
            return
        
        # Show warnings
        if results.has_warnings:
            render_validation_warnings(results, language='en')
            
            acknowledged = st.checkbox(
                "☑️ I understand the warnings and want to proceed",
                value=st.session_state.get('edit_warnings_acknowledged', False),
                key="edit_warnings_ack"
            )
            st.session_state['edit_warnings_acknowledged'] = acknowledged
        else:
            acknowledged = True
            st.success("✅ All validations passed!")
        
        # Save button
        st.markdown("---")
        
        if st.button("💾 Save Changes", type="primary", use_container_width=True,
                    disabled=not acknowledged, key="btn_save_edit"):
            try:
                user_id = st.session_state.get('user_id', 1)
                success, _ = self.manager.update_order(
                    order['id'], update_data, user_id, skip_warnings=True
                )
                
                if success:
                    # Clear form data
                    st.session_state.pop('edit_order_form_data', None)
                    st.session_state.pop('edit_order_id', None)
                    st.session_state.pop('edit_validation_results', None)
                    st.session_state.pop('edit_update_data', None)
                    
                    st.success(f"✅ Order {order['order_no']} updated successfully!")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("❌ Failed to update order")
                    
            except ValueError as e:
                st.error(f"❌ Validation Error: {str(e)}")
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