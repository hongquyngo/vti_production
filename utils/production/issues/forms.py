# utils/production/issues/forms.py
"""
Form components for Issues domain
Issue materials form with quantity editing and alternatives

Version: 2.0.0
Changes:
- Show all primary + alternatives together, let user choose quantities
- Use st.fragment for performance optimization
- Fixed data integrity for inventory_history_id
"""

import logging
from typing import Dict, Any, Optional, List
import time

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
        
        # Step 1: Select Order
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
        
        # Step 2: Material Availability
        st.markdown("### 📋 Material Availability")
        
        availability = self.queries.get_material_availability(order_id)
        
        if availability.empty:
            st.error("❌ No materials found for this order")
            return
        
        # Initialize session state
        if ('issue_quantities' not in st.session_state or 
            st.session_state.get('issue_order_id') != order_id):
            st.session_state['issue_quantities'] = {}
            st.session_state['issue_order_id'] = order_id
            st.session_state['alternative_quantities'] = {}
            
            for _, row in availability.iterrows():
                material_id = row['material_id']
                pending_qty = float(row['pending_qty'])
                available_qty = float(row['available_qty'])
                
                # Auto-suggest: use primary first, then alternatives
                suggested = min(pending_qty, available_qty)
                st.session_state['issue_quantities'][material_id] = suggested
                
                # If primary is insufficient, auto-suggest alternatives
                remaining = pending_qty - suggested
                alternatives = row.get('alternative_details', [])
                if remaining > 0 and alternatives:
                    for alt in alternatives:
                        alt_key = f"{material_id}_{alt['alternative_material_id']}"
                        alt_available = float(alt['available'])
                        alt_suggest = min(remaining, alt_available)
                        st.session_state['alternative_quantities'][alt_key] = alt_suggest
                        remaining -= alt_suggest
                        if remaining <= 0:
                            break
        
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
        st.caption("💡 Enter quantities for primary material and/or alternatives. Total should meet or exceed required quantity.")
        
        # Material rows
        errors = []
        warnings = []
        
        for idx, row in availability.iterrows():
            self._render_material_row_v2(row, errors, warnings)
        
        # Validation messages
        if errors:
            st.error("❌ **Errors - Cannot proceed:**")
            for err in errors:
                st.write(f"• {err}")
        
        if warnings:
            st.warning("⚠️ **Warnings - Issuing less than required:**")
            for warn in warnings:
                st.write(f"• {warn}")
            st.info("💡 Materials can be issued again later if needed")
        
        # Action buttons
        issue_valid = len(errors) == 0
        
        if issue_valid:
            self._render_action_buttons(order, availability)
        else:
            st.error("❌ Cannot issue materials. Please fix errors above.")
    
    def _render_material_row_v2(self, row: pd.Series, errors: List[str], warnings: List[str]):
        """
        Render material row with NEW logic:
        - Always show primary + all alternatives
        - User can choose any combination
        - No "use alternatives" checkbox needed
        - Shows already issued quantity for partial issues
        """
        material_id = row['material_id']
        material_name = row['material_name']
        pt_code = row.get('pt_code', 'N/A')
        required_qty = float(row['required_qty'])
        issued_qty = float(row.get('issued_qty', 0))
        pending_qty = float(row['pending_qty'])
        available_qty = float(row['available_qty'])
        uom = row['uom']
        status = row['availability_status']
        alternatives = row.get('alternative_details', [])
        
        # Status icon
        status_icons = {'SUFFICIENT': '✅', 'PARTIAL': '⚠️', 'INSUFFICIENT': '❌'}
        status_icon = status_icons.get(status, '⚪')
        
        # Get current quantities
        primary_qty = st.session_state['issue_quantities'].get(material_id, 0)
        alt_quantities = st.session_state.get('alternative_quantities', {})
        
        # Calculate total from alternatives
        total_alt_used = 0
        if alternatives:
            for alt in alternatives:
                alt_key = f"{material_id}_{alt['alternative_material_id']}"
                total_alt_used += alt_quantities.get(alt_key, 0)
        
        # Total issue for this material
        total_issue = primary_qty + total_alt_used
        
        # Container for the material
        with st.container():
            # Header row with required/issued info
            col1, col2, col3 = st.columns([4, 2, 2])
            
            with col1:
                st.markdown(f"**{material_name}**")
                st.caption(f"PT Code: {pt_code}")
            
            with col2:
                # Show required and already issued
                if issued_qty > 0:
                    st.write(f"Required: **{format_number(required_qty, 4)}** {uom}")
                    st.caption(f"📦 Already issued: {format_number(issued_qty, 4)} | Remaining: {format_number(pending_qty, 4)}")
                else:
                    st.write(f"Required: **{format_number(pending_qty, 4)}** {uom}")
            
            with col3:
                # Validation status
                if total_issue >= pending_qty and total_issue <= pending_qty * 1.5:
                    st.success(f"✅ Total: {format_number(total_issue, 4)} {uom}")
                elif total_issue < pending_qty:
                    if total_issue > 0:
                        st.warning(f"⚠️ Total: {format_number(total_issue, 4)} {uom}")
                    else:
                        st.error(f"❌ Total: 0 {uom}")
                else:
                    st.error(f"❌ Over: {format_number(total_issue, 4)} {uom}")
            
            # Primary material row
            pcol1, pcol2, pcol3, pcol4 = st.columns([3, 1.5, 2, 1.5])
            
            with pcol1:
                st.write(f"📦 **Primary:** {material_name[:40]}...")
            
            with pcol2:
                avail_display = format_number(available_qty, 4)
                if available_qty > 0:
                    st.write(f"Stock: **{avail_display}**")
                else:
                    st.write(f"Stock: **{avail_display}** ❌")
            
            with pcol3:
                # Primary quantity input
                max_primary = max(0.0, available_qty)
                default_primary = min(float(primary_qty), max_primary)
                
                new_primary_qty = st.number_input(
                    f"Primary qty for {material_id}",
                    min_value=0.0,
                    max_value=float(max_primary) if max_primary > 0 else 0.0,
                    value=float(default_primary),
                    step=0.0001,
                    format="%.4f",
                    key=f"primary_qty_{material_id}",
                    label_visibility="collapsed"
                )
                
                # Update session state
                if new_primary_qty != primary_qty:
                    st.session_state['issue_quantities'][material_id] = new_primary_qty
            
            with pcol4:
                if new_primary_qty > available_qty:
                    st.error("❌ Over stock")
                    errors.append(f"{material_name}: Primary {format_number(new_primary_qty, 4)} > available {format_number(available_qty, 4)}")
                elif new_primary_qty > 0:
                    st.success("✅")
                else:
                    st.caption("—")
            
            # Alternative materials rows (always show if available)
            if alternatives:
                st.caption(f"🔄 **Alternatives available:** ({len(alternatives)} options)")
                
                for alt in alternatives:
                    alt_id = alt['alternative_material_id']
                    alt_key = f"{material_id}_{alt_id}"
                    alt_name = alt['name']
                    alt_available = float(alt['available'])
                    alt_uom = alt.get('uom', uom)
                    alt_priority = alt.get('priority', 1)
                    
                    acol1, acol2, acol3, acol4 = st.columns([3, 1.5, 2, 1.5])
                    
                    with acol1:
                        st.write(f"  ↳ {alt_name[:35]}... (P{alt_priority})")
                    
                    with acol2:
                        if alt_available > 0:
                            st.write(f"Stock: **{format_number(alt_available, 4)}**")
                        else:
                            st.write(f"Stock: **0** ❌")
                    
                    with acol3:
                        current_alt_qty = alt_quantities.get(alt_key, 0)
                        max_alt = max(0.0, alt_available)
                        default_alt = min(float(current_alt_qty), max_alt)
                        
                        new_alt_qty = st.number_input(
                            f"Alt qty for {alt_key}",
                            min_value=0.0,
                            max_value=float(max_alt) if max_alt > 0 else 0.0,
                            value=float(default_alt),
                            step=0.0001,
                            format="%.4f",
                            key=f"alt_qty_{alt_key}",
                            label_visibility="collapsed"
                        )
                        
                        # Update session state
                        if new_alt_qty != current_alt_qty:
                            st.session_state['alternative_quantities'][alt_key] = new_alt_qty
                    
                    with acol4:
                        if new_alt_qty > alt_available:
                            st.error("❌ Over")
                            errors.append(f"Alt {alt_name}: {format_number(new_alt_qty, 4)} > available {format_number(alt_available, 4)}")
                        elif new_alt_qty > 0:
                            st.success("✅")
                        else:
                            st.caption("—")
            
            # Recalculate total after inputs
            updated_primary = st.session_state['issue_quantities'].get(material_id, 0)
            updated_alt_total = sum(
                st.session_state.get('alternative_quantities', {}).get(f"{material_id}_{alt['alternative_material_id']}", 0)
                for alt in alternatives
            ) if alternatives else 0
            
            updated_total = updated_primary + updated_alt_total
            
            # Add warnings for this material
            if updated_total < pending_qty and updated_total > 0:
                warnings.append(
                    f"{material_name}: issuing {format_number(updated_total, 4)} < required {format_number(pending_qty, 4)}"
                )
            elif updated_total > pending_qty * 1.5:
                errors.append(
                    f"{material_name}: total {format_number(updated_total, 4)} > 150% of required"
                )
            elif updated_total == 0 and pending_qty > 0:
                warnings.append(
                    f"{material_name}: no quantity specified (required: {format_number(pending_qty, 4)})"
                )
        
        st.markdown("---")
    
    def _render_action_buttons(self, order: Dict, availability: pd.DataFrame):
        """Render action buttons and confirmation"""
        col1, col2 = st.columns(2)
        
        with col1:
            if not st.session_state.get('confirm_issue', False):
                if st.button("🚀 Issue Materials", type="primary", 
                           use_container_width=True, key="issue_btn"):
                    st.session_state['confirm_issue'] = True
                    st.rerun()
        
        with col2:
            if st.button("🔄 Reset Quantities", use_container_width=True, 
                        key="reset_btn"):
                st.session_state.pop('issue_quantities', None)
                st.session_state.pop('issue_order_id', None)
                st.session_state.pop('alternative_quantities', None)
                st.rerun()
        
        # Confirmation dialog
        if st.session_state.get('confirm_issue', False):
            st.markdown("---")
            st.warning("⚠️ **Confirm Issue Materials**")
            st.info(f"Order: **{order['order_no']}** - {order['product_name']}")
            
            st.markdown("**Materials to issue:**")
            alt_quantities = st.session_state.get('alternative_quantities', {})
            
            has_any_material = False
            
            for _, row in availability.iterrows():
                material_id = row['material_id']
                issue_qty = st.session_state['issue_quantities'].get(material_id, 0)
                
                if issue_qty > 0:
                    st.write(f"• 📦 {row['material_name']}: **{format_number(issue_qty, 4)}** {row['uom']}")
                    has_any_material = True
                
                # Show alternatives being used
                alternatives = row.get('alternative_details', [])
                if alternatives:
                    for alt in alternatives:
                        alt_key = f"{material_id}_{alt['alternative_material_id']}"
                        alt_qty = alt_quantities.get(alt_key, 0)
                        if alt_qty > 0:
                            st.write(f"  ↳ 🔄 {alt['name']}: **{format_number(alt_qty, 4)}** {alt.get('uom', row['uom'])}")
                            has_any_material = True
            
            if not has_any_material:
                st.error("❌ No materials selected to issue")
                if st.button("↩️ Go Back", key="back_no_materials"):
                    st.session_state['confirm_issue'] = False
                    st.rerun()
                return
            
            # Employee selection
            employees = self.queries.get_employees()
            
            if employees.empty:
                st.error("❌ No active employees found")
                return
            
            emp_options = {
                f"{row['full_name']} ({row['position_name'] or 'N/A'})": row['id']
                for _, row in employees.iterrows()
            }
            emp_list = ["-- Select --"] + list(emp_options.keys())
            
            col1, col2 = st.columns(2)
            with col1:
                issued_by = st.selectbox("Issued By (Warehouse)", emp_list, key="issue_issued_by")
            with col2:
                received_by = st.selectbox("Received By (Production)", emp_list, key="issue_received_by")
            
            notes = st.text_area("Notes (Optional)", height=80, key="issue_notes")
            
            col1, col2 = st.columns(2)
            
            with col1:
                if st.button("✅ Yes, Issue Now", type="primary", 
                           use_container_width=True, key="confirm_yes"):
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
            
            with col2:
                if st.button("❌ Cancel", use_container_width=True, key="confirm_no"):
                    st.session_state['confirm_issue'] = False
                    st.rerun()
    
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
                    # Extract material_id from key (format: "material_id_alt_id")
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
            
            # Clear session state
            st.session_state['confirm_issue'] = False
            st.session_state.pop('issue_quantities', None)
            st.session_state.pop('issue_order_id', None)
            st.session_state.pop('alternative_quantities', None)
            
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
