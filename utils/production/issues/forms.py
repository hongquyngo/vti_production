# utils/production/issues/forms.py
"""
Form components for Issues domain
Issue materials form with quantity editing and alternatives

Version: 2.3.0
Changes from 2.2.0:
- Wrapped confirmation dialog in st.form() to prevent rerun on dropdown change
- Employee selection and notes now batched - only submit on button click
- Improves UX by eliminating page reload when selecting employees

NOTE: This file was already well-implemented with st.form() to prevent reruns.
      Changes are minimal for consistency with other domains.
"""

import logging
from typing import Dict, Any, Optional, List

import streamlit as st
import pandas as pd

from .queries import IssueQueries
from .manager import IssueManager
from .common import (
    format_number, create_status_indicator, get_vietnam_today,
    IssueValidator, get_user_audit_info, IssueConstants
)

logger = logging.getLogger(__name__)


class IssueForms:
    """Form components for Material Issue"""
    
    def __init__(self):
        self.queries = IssueQueries()
        self.manager = IssueManager()
    
    # ==================== Issue Materials Form ====================
    
    def render_issue_form(self):
        """Render issue materials form"""
        st.subheader("📦 Issue Materials")
        
        # Step 1: Select Order (outside form - needs to reload materials)
        orders = self.queries.get_issuable_orders()
        
        if orders.empty:
            st.info("📭 No orders available for material issue")
            st.caption("Orders must be in DRAFT, CONFIRMED, or IN_PROGRESS status")
            return
        
        # Create order options
        order_options = {
            f"{row['order_no']} | {row['priority']} | {row['pt_code']} - {row['product_name']}": row['id']
            for _, row in orders.iterrows()
        }
        
        selected_label = st.selectbox(
            "Select Production Order",
            options=list(order_options.keys()),
            key="issue_order_select"
        )
        
        order_id = order_options[selected_label]
        order = self.queries.get_order_for_issue(order_id)
        
        if not order:
            st.error("❌ Order not found")
            return
        
        # Order info
        col1, col2, col3 = st.columns(3)
        with col1:
            st.info(f"**Product:** {order['product_name']}")
        with col2:
            st.info(f"**Qty:** {format_number(order['planned_qty'], 2)} {order['uom']}")
        with col3:
            st.info(f"**Warehouse:** {order['warehouse_name']}")
        
        st.markdown("---")
        
        # Check if in confirmation mode
        if st.session_state.get('confirm_issue', False):
            self._render_confirmation_dialog(order)
            return
        
        # Step 2: Material Availability
        st.markdown("### 📋 Material Availability")
        
        availability = self.queries.get_material_availability(order_id)
        
        if availability.empty:
            st.error("❌ No materials found for this order")
            return
        
        # Initialize/reset form data when order changes
        if st.session_state.get('issue_order_id') != order_id:
            st.session_state['issue_order_id'] = order_id
            # Clear saved quantities when order changes
            st.session_state.pop('saved_quantities', None)
            st.session_state.pop('saved_alt_quantities', None)
            
            # Initialize form data structure for consistency
            st.session_state['issue_form_data'] = {
                'order_id': order_id,
                'initialized': True
            }
        
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
        
        st.markdown("---")
        st.markdown("### 📝 Adjust Issue Quantities")
        st.caption("💡 Enter quantities for primary material and/or alternatives. Click **Review & Issue** when ready. **No page reload when changing values!**")
        
        # ========== FORM - No reruns when changing inputs ==========
        with st.form(key="issue_materials_form", clear_on_submit=False):
            
            # Calculate default values
            default_quantities = {}
            default_alt_quantities = {}
            
            for _, row in availability.iterrows():
                material_id = row['material_id']
                pending_qty = float(row['pending_qty'])
                available_qty = float(row['available_qty'])
                
                # Ensure non-negative: pending_qty can be negative if over-issued
                safe_pending = max(0.0, pending_qty)
                
                # Use saved values if available, otherwise auto-suggest
                if 'saved_quantities' in st.session_state:
                    default_quantities[material_id] = max(0.0, st.session_state['saved_quantities'].get(material_id, 0))
                else:
                    default_quantities[material_id] = min(safe_pending, available_qty)
                
                # Alternatives
                alternatives = row.get('alternative_details', [])
                if alternatives:
                    # Use safe_pending for remaining calculation
                    remaining = safe_pending - default_quantities[material_id]
                    for alt in alternatives:
                        # Use alternative_id (unique bom_material_alternatives.id) instead of alternative_material_id
                        alt_key = f"{material_id}_{alt['alternative_id']}"
                        if 'saved_alt_quantities' in st.session_state:
                            default_alt_quantities[alt_key] = max(0.0, st.session_state['saved_alt_quantities'].get(alt_key, 0))
                        else:
                            if remaining > 0:
                                alt_available = float(alt['available'])
                                alt_suggest = min(remaining, alt_available)
                                default_alt_quantities[alt_key] = alt_suggest
                                remaining -= alt_suggest
                            else:
                                default_alt_quantities[alt_key] = 0
            
            # Render material rows
            errors = []
            warnings = []
            form_quantities = {}
            form_alt_quantities = {}
            
            for idx, row in availability.iterrows():
                mat_qty, alt_qtys, mat_errors, mat_warnings = self._render_material_row_form(
                    row, default_quantities, default_alt_quantities
                )
                form_quantities[row['material_id']] = mat_qty
                form_alt_quantities.update(alt_qtys)
                errors.extend(mat_errors)
                warnings.extend(mat_warnings)
            
            st.markdown("---")
            
            # Form submit buttons
            col1, col2 = st.columns(2)
            
            with col1:
                submit_btn = st.form_submit_button(
                    "🚀 Review & Issue", 
                    type="primary",
                    use_container_width=True
                )
            
            with col2:
                reset_btn = st.form_submit_button(
                    "🔄 Reset to Defaults",
                    use_container_width=True
                )
        
        # Handle form submission
        if reset_btn:
            # Clear saved quantities to trigger recalculation
            st.session_state.pop('saved_quantities', None)
            st.session_state.pop('saved_alt_quantities', None)
            st.rerun()
        
        if submit_btn:
            # Save quantities to session state
            st.session_state['saved_quantities'] = form_quantities
            st.session_state['saved_alt_quantities'] = form_alt_quantities
            
            # Validate
            has_any_material = any(q > 0 for q in form_quantities.values()) or \
                              any(q > 0 for q in form_alt_quantities.values())
            
            if not has_any_material:
                st.error("❌ Please enter at least one material quantity")
                return
            
            if errors:
                st.error("❌ Please fix the following errors:")
                for error in errors:
                    st.write(f"• {error}")
                return
            
            if warnings:
                with st.expander("⚠️ Warnings (optional to fix)", expanded=True):
                    for warning in warnings:
                        st.write(f"• {warning}")
            
            # Set confirmation mode
            st.session_state['confirm_issue'] = True
            st.session_state['issue_quantities'] = form_quantities
            st.session_state['alternative_quantities'] = form_alt_quantities
            st.rerun()
    
    def _render_material_row_form(self, row: pd.Series, 
                                  default_quantities: Dict,
                                  default_alt_quantities: Dict):
        """
        Render a single material row inside the form
        
        Returns:
            tuple: (primary_qty, alt_qtys_dict, errors_list, warnings_list)
        """
        material_id = row['material_id']
        material_name = row['material_name']
        pending_qty = float(row['pending_qty'])
        available_qty = float(row['available_qty'])
        uom = row['uom']
        status = row['availability_status']
        
        errors = []
        warnings = []
        alt_qtys = {}
        
        # Handle negative pending (over-issued) - show warning
        safe_pending = max(0.0, pending_qty)
        over_issued = pending_qty < 0
        
        # Material header with status
        status_emoji = "✅" if status == 'SUFFICIENT' else "⚠️" if status == 'PARTIAL' else "❌"
        if over_issued:
            st.markdown(f"**⚠️ {material_name}** — Over-issued by: {format_number(abs(pending_qty), 4)} {uom} | Stock: {format_number(available_qty, 4)} {uom}")
            st.caption("ℹ️ This material has been over-issued. No additional issue needed.")
        else:
            st.markdown(f"**{status_emoji} {material_name}** — Need: {format_number(pending_qty, 4)} {uom} | Stock: {format_number(available_qty, 4)} {uom}")
        
        col1, col2, col3 = st.columns([3, 2, 1])
        
        with col1:
            st.write(f"Primary Material")
        
        with col2:
            max_primary = max(0.0, available_qty)
            # Ensure default is non-negative and within bounds
            default_primary = max(0.0, min(float(default_quantities.get(material_id, 0)), max_primary))
            
            primary_qty = st.number_input(
                f"Qty {material_id}",
                min_value=0.0,
                max_value=float(max_primary) if max_primary > 0 else 9999999.0,
                value=float(default_primary),
                step=0.0001,
                format="%.4f",
                key=f"form_primary_{material_id}",
                label_visibility="collapsed"
            )
        
        with col3:
            if primary_qty > available_qty:
                st.error("❌")
                errors.append(f"{material_name}: qty {format_number(primary_qty, 4)} > stock {format_number(available_qty, 4)}")
            elif primary_qty > 0:
                st.success("✅")
            else:
                st.write("—")
        
        # Alternatives
        alternatives = row.get('alternative_details', [])
        if alternatives and isinstance(alternatives, list) and len(alternatives) > 0:
            with st.container():
                for alt in alternatives:
                    # Use alternative_id (unique bom_material_alternatives.id) to avoid duplicate keys
                    alt_unique_id = alt.get('alternative_id')
                    alt_key = f"{material_id}_{alt_unique_id}"
                    alt_name = alt.get('name', 'Unknown')
                    alt_available = float(alt.get('available', 0))
                    alt_priority = alt.get('priority', 1)
                    
                    acol1, acol2, acol3 = st.columns([3, 2, 1])
                    
                    with acol1:
                        # Hiển thị tên alternative kèm stock info
                        stock_display = f"Stock: {alt_available:,.4f}".rstrip('0').rstrip('.')
                        st.write(f"    ↳ {alt_name[:30]}... (P{alt_priority}) | {stock_display}")
                    
                    with acol2:
                        max_alt = max(0.0, alt_available)
                        # Ensure default is non-negative and within bounds
                        default_alt = max(0.0, min(float(default_alt_quantities.get(alt_key, 0)), max_alt))
                        
                        alt_qty = st.number_input(
                            f"Alt {alt_key}",
                            min_value=0.0,
                            max_value=float(max_alt) if max_alt > 0 else 9999999.0,
                            value=float(default_alt),
                            step=0.0001,
                            format="%.4f",
                            key=f"form_alt_{alt_key}",
                            label_visibility="collapsed"
                        )
                        
                        alt_qtys[alt_key] = alt_qty
                    
                    with acol3:
                        if alt_qty > alt_available:
                            st.error("❌")
                            errors.append(f"Alt {alt_name}: qty {format_number(alt_qty, 4)} > stock {format_number(alt_available, 4)}")
                        elif alt_qty > 0:
                            st.success("✅")
                        else:
                            st.write("—")
        
        # Calculate total and add warnings
        total_qty = primary_qty + sum(alt_qtys.values())
        
        # Summary for this material (use safe_pending for comparison)
        if total_qty > 0:
            if total_qty >= safe_pending:
                st.caption(f"  📊 Total: {format_number(total_qty, 4)} {uom} ✅")
            else:
                st.caption(f"  📊 Total: {format_number(total_qty, 4)} {uom} ⚠️ (< required)")
                warnings.append(f"{material_name}: Total {format_number(total_qty, 4)} < required {format_number(safe_pending, 4)}")
        else:
            if safe_pending > 0:
                warnings.append(f"{material_name}: No quantity entered")
        
        st.markdown("---")
        
        return primary_qty, alt_qtys, errors, warnings
    
    def _render_confirmation_dialog(self, order: Dict):
        """Render confirmation dialog after form submission"""
        st.markdown("---")
        st.warning("⚠️ **Confirm Issue Materials**")
        st.info(f"Order: **{order['order_no']}** - {order['product_name']}")
        
        quantities = st.session_state.get('issue_quantities', {})
        alt_quantities = st.session_state.get('alternative_quantities', {})
        
        # Get material names
        availability = self.queries.get_material_availability(order['id'])
        material_names = {row['material_id']: row['material_name'] for _, row in availability.iterrows()}
        material_uoms = {row['material_id']: row['uom'] for _, row in availability.iterrows()}
        
        # Build alternative names lookup
        alt_names = {}
        for _, row in availability.iterrows():
            alts = row.get('alternative_details', [])
            if alts:
                for alt in alts:
                    # Use alternative_id to match the key format used in form
                    alt_key = f"{row['material_id']}_{alt['alternative_id']}"
                    alt_names[alt_key] = alt.get('name', 'Unknown')
        
        st.markdown("**Materials to issue:**")
        
        has_any = False
        for mat_id, qty in quantities.items():
            if qty > 0:
                mat_name = material_names.get(mat_id, f"Material {mat_id}")
                uom = material_uoms.get(mat_id, '')
                st.write(f"• 📦 {mat_name}: **{format_number(qty, 4)}** {uom}")
                has_any = True
        
        for alt_key, qty in alt_quantities.items():
            if qty > 0:
                alt_name = alt_names.get(alt_key, alt_key)
                st.write(f"  ↳ 🔄 {alt_name}: **{format_number(qty, 4)}**")
                has_any = True
        
        if not has_any:
            st.error("❌ No materials selected")
            if st.button("↩️ Go Back"):
                st.session_state['confirm_issue'] = False
                st.rerun()
            return
        
        # Employee selection - WRAP IN FORM to prevent rerun on dropdown change
        employees = self.queries.get_employees()
        
        if employees.empty:
            st.error("❌ No active employees found")
            return
        
        emp_options = {
            f"{row['full_name']} ({row['position_name'] or 'N/A'})": row['id']
            for _, row in employees.iterrows()
        }
        emp_list = ["-- Select --"] + list(emp_options.keys())
        
        # Use form to batch all inputs - no rerun until submit
        with st.form(key="confirm_issue_form", clear_on_submit=False):
            col1, col2 = st.columns(2)
            with col1:
                issued_by = st.selectbox("Issued By (Warehouse)", emp_list, key="issue_issued_by")
            with col2:
                received_by = st.selectbox("Received By (Production)", emp_list, key="issue_received_by")
            
            notes = st.text_area("Notes (Optional)", height=80, key="issue_notes")
            
            col1, col2 = st.columns(2)
            
            with col1:
                submit_btn = st.form_submit_button(
                    "✅ Yes, Issue Now", 
                    type="primary", 
                    use_container_width=True
                )
            
            with col2:
                cancel_btn = st.form_submit_button(
                    "❌ Cancel", 
                    use_container_width=True
                )
        
        # Handle form submission outside the form block
        if cancel_btn:
            st.session_state['confirm_issue'] = False
            st.rerun()
        
        if submit_btn:
            if issued_by == "-- Select --":
                st.error("❌ Please select warehouse staff")
            elif received_by == "-- Select --":
                st.error("❌ Please select production staff")
            else:
                self._execute_issue(
                    order['id'],
                    emp_options[issued_by],
                    emp_options[received_by],
                    notes
                )
    
    def _execute_issue(self, order_id: int, issued_by: int, 
                      received_by: int, notes: str):
        """Execute the material issue"""
        try:
            audit_info = get_user_audit_info()
            custom_quantities = st.session_state.get('issue_quantities', {})
            alternative_quantities = st.session_state.get('alternative_quantities', {})
            
            # Build use_alternatives based on which alternatives have quantity > 0
            use_alternatives = {}
            for key, qty in alternative_quantities.items():
                if qty > 0:
                    parts = key.split('_')
                    if len(parts) >= 2:
                        material_id = int(parts[0])
                        use_alternatives[material_id] = True
            
            with st.spinner("Issuing materials..."):
                result = self.manager.issue_materials(
                    order_id=order_id,
                    user_id=audit_info['user_id'],
                    keycloak_id=audit_info['keycloak_id'],
                    issued_by=issued_by,
                    received_by=received_by,
                    notes=notes.strip() if notes else None,
                    custom_quantities=custom_quantities,
                    use_alternatives=use_alternatives,
                    alternative_quantities=alternative_quantities
                )
            
            # Clear all session state related to issue form
            keys_to_clear = [
                'confirm_issue', 'issue_quantities', 'alternative_quantities',
                'saved_quantities', 'saved_alt_quantities', 'issue_order_id',
                'issue_form_data'
            ]
            for key in keys_to_clear:
                st.session_state.pop(key, None)
            
            # Show success with PDF option
            from .dialogs import show_success_dialog
            show_success_dialog(result)
            
        except Exception as e:
            st.error(f"❌ Error: {str(e)}")
            st.session_state['confirm_issue'] = False
            logger.error(f"Issue error: {e}", exc_info=True)


# Convenience function

def render_issue_form():
    """Render issue materials form"""
    forms = IssueForms()
    forms.render_issue_form()