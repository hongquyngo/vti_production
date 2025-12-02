# utils/production/issues/forms.py
"""
Form components for Issues domain
Issue materials form with quantity editing and alternatives

Version: 1.0.0
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
            st.caption("Orders must be in DRAFT or CONFIRMED status")
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
            st.session_state['use_alternatives'] = {}
            
            for _, row in availability.iterrows():
                material_id = row['material_id']
                suggested = min(float(row['pending_qty']), float(row['available_qty']))
                st.session_state['issue_quantities'][material_id] = suggested
        
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
        
        # Material rows
        errors = []
        warnings = []
        
        for idx, row in availability.iterrows():
            self._render_material_row(row, errors, warnings)
        
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
    
    def _render_material_row(self, row: pd.Series, errors: List[str], warnings: List[str]):
        """Render a single material row with enhanced alternative support"""
        material_id = row['material_id']
        material_name = row['material_name']
        pt_code = row.get('pt_code', 'N/A')
        pending_qty = float(row['pending_qty'])
        available_qty = float(row['available_qty'])
        uom = row['uom']
        status = row['availability_status']
        alt_total = float(row.get('alternative_total_qty', 0))
        alternatives = row.get('alternative_details', [])
        
        # Status icon
        status_icons = {'SUFFICIENT': '✅', 'PARTIAL': '⚠️', 'INSUFFICIENT': '❌'}
        status_icon = status_icons.get(status, '⚪')
        
        # Get alternative usage settings
        use_alternative = st.session_state['use_alternatives'].get(material_id, False)
        alt_quantities = st.session_state.get('alternative_quantities', {})
        
        # Calculate total alternative being used
        total_alt_used = 0
        if use_alternative and alternatives:
            for alt in alternatives:
                alt_key = f"{material_id}_{alt['alternative_material_id']}"
                total_alt_used += alt_quantities.get(alt_key, 0)
        
        # Determine max issue from primary
        max_primary = available_qty
        
        col1, col2, col3, col4, col5 = st.columns([3, 1.5, 1.5, 2, 1])
        
        with col1:
            st.write(f"**{material_name}**")
            st.caption(f"PT Code: {pt_code}")
        
        with col2:
            st.write(f"Required: **{format_number(pending_qty, 4)}**")
            st.caption(uom)
        
        with col3:
            st.write(f"Available: **{format_number(available_qty, 4)}**")
            if use_alternative and total_alt_used > 0:
                st.caption(f"🔄 +{format_number(total_alt_used, 4)} alt")
            else:
                st.caption(f"{status_icon} {status}")
        
        with col4:
            # Primary material quantity
            default_qty = st.session_state['issue_quantities'].get(
                material_id, min(pending_qty, max_primary)
            )
            issue_qty = st.number_input(
                "Issue Qty",
                min_value=0.0,
                max_value=float(max_primary) if max_primary > 0 else 0.0001,
                value=float(min(default_qty, max_primary)),
                step=0.0001,
                format="%.4f",
                key=f"issue_qty_{material_id}",
                label_visibility="collapsed"
            )
            st.session_state['issue_quantities'][material_id] = issue_qty
        
        with col5:
            # Validation - total = primary + alternatives
            total_issue = issue_qty + total_alt_used
            
            if issue_qty > available_qty:
                st.error("❌ Over")
                errors.append(
                    f"{material_name}: cannot issue {format_number(issue_qty, 4)} > "
                    f"available {format_number(available_qty, 4)}"
                )
            elif total_issue < pending_qty:
                st.warning("⚠️ Less")
                warnings.append(
                    f"{material_name}: issuing {format_number(total_issue, 4)} < "
                    f"required {format_number(pending_qty, 4)}"
                )
            elif total_issue > pending_qty * 1.5:
                st.error("❌ Over")
                errors.append(
                    f"{material_name}: total issue {format_number(total_issue, 4)} > 150% of required"
                )
            else:
                st.success("✅ OK")
        
        # Alternatives expander with quantity adjustment
        if status != 'SUFFICIENT' and row.get('has_alternatives', False) and alternatives:
            with st.expander(f"🔄 Alternatives for {material_name}", 
                           expanded=(available_qty == 0)):
                
                use_alt = st.checkbox(
                    f"✅ Use alternative materials (Total available: {format_number(alt_total, 4)} {uom})",
                    value=use_alternative,
                    key=f"use_alt_{material_id}"
                )
                st.session_state['use_alternatives'][material_id] = use_alt
                
                if use_alt != use_alternative:
                    # Initialize alternative quantities when enabling
                    if use_alt and 'alternative_quantities' not in st.session_state:
                        st.session_state['alternative_quantities'] = {}
                    st.rerun()
                
                if use_alt:
                    st.markdown("**Available alternatives:**")
                    
                    # Calculate remaining need
                    remaining_need = max(0, pending_qty - issue_qty)
                    
                    for alt in alternatives:
                        alt_id = alt['alternative_material_id']
                        alt_key = f"{material_id}_{alt_id}"
                        alt_available = float(alt['available'])
                        
                        # Initialize if not exists
                        if alt_key not in alt_quantities:
                            # Auto-suggest based on remaining need
                            suggested = min(remaining_need, alt_available)
                            st.session_state.setdefault('alternative_quantities', {})[alt_key] = suggested
                            remaining_need -= suggested
                        
                        acol1, acol2, acol3 = st.columns([3, 2, 1])
                        
                        with acol1:
                            st.write(f"• **{alt['name']}** (Priority {alt['priority']})")
                            st.caption(f"Available: {format_number(alt_available, 4)} {alt['uom']}")
                        
                        with acol2:
                            alt_qty = st.number_input(
                                f"Use from {alt['name'][:20]}",
                                min_value=0.0,
                                max_value=float(alt_available),
                                value=float(st.session_state.get('alternative_quantities', {}).get(alt_key, 0)),
                                step=0.0001,
                                format="%.4f",
                                key=f"alt_qty_{alt_key}",
                                label_visibility="collapsed"
                            )
                            st.session_state.setdefault('alternative_quantities', {})[alt_key] = alt_qty
                        
                        with acol3:
                            if alt_qty > alt_available:
                                st.error("❌")
                                errors.append(
                                    f"Alternative {alt['name']}: cannot use {format_number(alt_qty, 4)} > "
                                    f"available {format_number(alt_available, 4)}"
                                )
                            elif alt_qty > 0:
                                st.success("✅")
                            else:
                                st.write("")
                    
                    # Summary of alternative usage
                    total_alt_used_now = sum(
                        st.session_state.get('alternative_quantities', {}).get(f"{material_id}_{alt['alternative_material_id']}", 0)
                        for alt in alternatives
                    )
                    
                    st.markdown("---")
                    st.info(f"📊 **Primary:** {format_number(issue_qty, 4)} + **Alternatives:** {format_number(total_alt_used_now, 4)} = **Total:** {format_number(issue_qty + total_alt_used_now, 4)} {uom}")
        
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
                st.session_state.pop('use_alternatives', None)
                st.session_state.pop('alternative_quantities', None)
                st.rerun()
        
        # Confirmation dialog
        if st.session_state.get('confirm_issue', False):
            st.markdown("---")
            st.warning("⚠️ **Confirm Issue Materials**")
            st.info(f"Order: **{order['order_no']}** - {order['product_name']}")
            
            st.markdown("**Materials to issue:**")
            alt_quantities = st.session_state.get('alternative_quantities', {})
            
            for _, row in availability.iterrows():
                material_id = row['material_id']
                issue_qty = st.session_state['issue_quantities'].get(material_id, 0)
                
                if issue_qty > 0:
                    st.write(f"• {row['material_name']}: **{format_number(issue_qty, 4)}** {row['uom']}")
                
                # Show alternatives being used
                alternatives = row.get('alternative_details', [])
                if alternatives:
                    for alt in alternatives:
                        alt_key = f"{material_id}_{alt['alternative_material_id']}"
                        alt_qty = alt_quantities.get(alt_key, 0)
                        if alt_qty > 0:
                            st.write(f"  ↳ 🔄 {alt['name']}: **{format_number(alt_qty, 4)}** {alt['uom']}")
            
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
            use_alternatives = st.session_state.get('use_alternatives', {})
            alternative_quantities = st.session_state.get('alternative_quantities', {})
            
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
            st.session_state.pop('use_alternatives', None)
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
