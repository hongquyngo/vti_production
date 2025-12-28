# utils/production/returns/forms.py
"""
Form components for Returns domain
Return materials form with quantity and condition editing

Version: 2.0.0
Changes:
- Added st.form() to prevent unnecessary reruns when changing quantities/conditions
- Session state for form data preserved across interactions
- Order selection remains outside form (needs to reload materials)
"""

import logging
from typing import Dict, Any, Optional, List

import streamlit as st
import pandas as pd

from .queries import ReturnQueries
from .manager import ReturnManager
from .common import (
    format_number, create_status_indicator, format_date,
    ReturnConstants, ReturnValidator, get_user_audit_info,
    format_order_display, format_material_display
)

logger = logging.getLogger(__name__)


class ReturnForms:
    """Form components for Material Return"""
    
    def __init__(self):
        self.queries = ReturnQueries()
        self.manager = ReturnManager()
    
    # ==================== Return Materials Form ====================
    
    def render_return_form(self):
        """Render return materials form"""
        st.subheader("↩️ Return Unused Materials")
        
        # Check for success message
        if st.session_state.get('return_success'):
            return_info = st.session_state.get('return_info', {})
            st.success(f"""
            ✅ **Materials Returned Successfully!**
            • Return No: **{return_info.get('return_no', 'N/A')}**
            • Items Returned: **{return_info.get('item_count', 0)}**
            • Total Quantity: **{format_number(return_info.get('total_qty', 0), 4)}**
            """)
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button("✅ Create Another Return", type="primary", 
                           use_container_width=True, key="btn_another_return"):
                    st.session_state.pop('return_success', None)
                    st.session_state.pop('return_info', None)
                    st.rerun()
            with col2:
                if st.button("📄 Export PDF", use_container_width=True, key="btn_return_pdf"):
                    from .dialogs import show_pdf_dialog
                    show_pdf_dialog(return_info.get('return_id'), return_info.get('return_no'))
            return
        
        # Step 1: Select Order (outside form - needs to reload materials)
        orders = self.queries.get_returnable_orders()
        
        if orders.empty:
            st.info("📭 No orders with issued materials found")
            st.caption("Only IN_PROGRESS orders can have materials returned")
            return
        
        # Create order options with standardized format
        order_options = {
            format_order_display(
                order_no=row['order_no'],
                pt_code=row['pt_code'],
                product_name=row['product_name'],
                legacy_pt_code=row.get('legacy_pt_code')
            ): row['id']
            for _, row in orders.iterrows()
        }
        
        selected_label = st.selectbox(
            "Select Production Order",
            options=list(order_options.keys()),
            key="return_order_select"
        )
        
        order_id = order_options[selected_label]
        
        # Get returnable materials
        returnable = self.queries.get_returnable_materials(order_id)
        
        if returnable.empty:
            st.info("📭 No materials available for return")
            st.caption("All issued materials may have been returned or consumed")
            return
        
        # Display issued materials summary
        st.markdown("### 📦 Issued Materials")
        
        display_df = returnable.copy()
        
        # Create material display using standardized format
        display_df['material_display'] = display_df.apply(
            lambda x: format_material_display(
                pt_code=x['pt_code'],
                name=x['material_name'],
                legacy_pt_code=x.get('legacy_pt_code'),
                package_size=x.get('package_size'),
                brand_name=x.get('brand_name'),
                is_alternative=bool(x.get('is_alternative')),
                original_name=x.get('original_material_name'),
                include_all=True
            ),
            axis=1
        )
        
        display_df['issued'] = display_df.apply(
            lambda x: f"{format_number(x['issued_qty'], 4)} {x['uom']}", axis=1
        )
        display_df['returnable'] = display_df.apply(
            lambda x: f"{format_number(x['returnable_qty'], 4)} {x['uom']}", axis=1
        )
        display_df['issue_date_display'] = pd.to_datetime(display_df['issue_date']).dt.strftime('%d/%m/%Y')
        
        st.dataframe(
            display_df[['material_display', 'batch_no', 'issued', 'returnable', 'issue_no', 'issue_date_display']].rename(columns={
                'material_display': 'Material',
                'batch_no': 'Batch',
                'issued': 'Issued Qty',
                'returnable': 'Returnable',
                'issue_no': 'Issue No',
                'issue_date_display': 'Issue Date'
            }),
            use_container_width=True,
            hide_index=True
        )
        
        st.markdown("---")
        
        # Initialize/reset form data when order changes
        if st.session_state.get('return_order_id') != order_id:
            st.session_state['return_order_id'] = order_id
            # Initialize with zeros
            st.session_state['return_form_data'] = {
                'quantities': {row['issue_detail_id']: 0.0 for _, row in returnable.iterrows()},
                'conditions': {row['issue_detail_id']: 'GOOD' for _, row in returnable.iterrows()},
                'reason': 'EXCESS',
                'returned_by': None,
                'received_by': None
            }
        
        form_data = st.session_state['return_form_data']
        
        # Get employees for dropdowns
        employees = self.queries.get_employees()
        
        if employees.empty:
            st.error("❌ No active employees found")
            return
        
        emp_options = {
            f"{row['full_name']} ({row['position_name'] or 'N/A'})": row['id']
            for _, row in employees.iterrows()
        }
        emp_list = ["-- Select --"] + list(emp_options.keys())
        
        # ========== FORM - Prevents reruns when changing inputs ==========
        st.markdown("### ↩️ Return Details")
        st.caption("💡 Enter return quantities and conditions. **No page reload when changing values!**")
        
        with st.form(key="return_materials_form", clear_on_submit=False):
            
            # Material rows
            form_quantities = {}
            form_conditions = {}
            
            for idx, row in returnable.iterrows():
                issue_detail_id = row['issue_detail_id']
                # Use standardized format for material display
                material_display = format_material_display(
                    pt_code=row['pt_code'],
                    name=row['material_name'],
                    legacy_pt_code=row.get('legacy_pt_code'),
                    package_size=row.get('package_size'),
                    brand_name=row.get('brand_name'),
                    is_alternative=bool(row.get('is_alternative')),
                    original_name=row.get('original_material_name'),
                    include_all=True
                )
                batch_no = row['batch_no']
                returnable_qty = float(row['returnable_qty'])
                uom = row['uom']
                
                st.markdown(f"**{material_display}** (Batch: {batch_no})")
                
                col1, col2 = st.columns([2, 1])
                
                with col1:
                    # Get saved value or default
                    saved_qty = form_data['quantities'].get(issue_detail_id, 0.0)
                    return_qty = st.number_input(
                        f"Return Qty (max: {format_number(returnable_qty, 4)} {uom})",
                        min_value=0.0,
                        max_value=float(returnable_qty),
                        value=float(min(saved_qty, returnable_qty)),
                        step=0.0001,
                        format="%.4f",
                        key=f"form_return_qty_{issue_detail_id}"
                    )
                    form_quantities[issue_detail_id] = return_qty
                
                with col2:
                    condition_options = [c[0] for c in ReturnConstants.CONDITIONS]
                    condition_labels = {c[0]: c[1] for c in ReturnConstants.CONDITIONS}
                    
                    saved_condition = form_data['conditions'].get(issue_detail_id, 'GOOD')
                    condition_idx = condition_options.index(saved_condition) if saved_condition in condition_options else 0
                    
                    condition = st.selectbox(
                        "Condition",
                        options=condition_options,
                        format_func=lambda x: condition_labels.get(x, x),
                        index=condition_idx,
                        key=f"form_condition_{issue_detail_id}"
                    )
                    form_conditions[issue_detail_id] = condition
                
                st.markdown("---")
            
            # Return reason
            st.markdown("### 📋 Return Information")
            
            col1, col2 = st.columns(2)
            with col1:
                reason_options = [r[0] for r in ReturnConstants.REASONS]
                reason_labels = {r[0]: r[1] for r in ReturnConstants.REASONS}
                
                saved_reason = form_data.get('reason', 'EXCESS')
                reason_idx = reason_options.index(saved_reason) if saved_reason in reason_options else 0
                
                reason = st.selectbox(
                    "Return Reason",
                    options=reason_options,
                    format_func=lambda x: reason_labels.get(x, x),
                    index=reason_idx,
                    key="form_return_reason"
                )
            
            # Employee selection
            col1, col2 = st.columns(2)
            with col1:
                # Find saved index
                saved_returned_by = form_data.get('returned_by')
                returned_by_idx = 0
                if saved_returned_by and saved_returned_by in emp_list:
                    returned_by_idx = emp_list.index(saved_returned_by)
                
                returned_by = st.selectbox(
                    "Returned By (Production Staff)",
                    options=emp_list,
                    index=returned_by_idx,
                    key="form_return_returned_by"
                )
            with col2:
                saved_received_by = form_data.get('received_by')
                received_by_idx = 0
                if saved_received_by and saved_received_by in emp_list:
                    received_by_idx = emp_list.index(saved_received_by)
                
                received_by = st.selectbox(
                    "Received By (Warehouse Staff)",
                    options=emp_list,
                    index=received_by_idx,
                    key="form_return_received_by"
                )
            
            st.markdown("---")
            
            # Summary
            total_return = sum(form_quantities.values())
            good_count = sum(1 for k, v in form_quantities.items() if v > 0 and form_conditions.get(k) == 'GOOD')
            damaged_count = sum(1 for k, v in form_quantities.items() if v > 0 and form_conditions.get(k) == 'DAMAGED')
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.info(f"**Total Return:** {format_number(total_return, 4)}")
            with col2:
                st.info(f"**✅ Good:** {good_count} items")
            with col3:
                st.info(f"**⚠️ Damaged:** {damaged_count} items")
            
            st.markdown("---")
            
            # Form submit buttons
            col1, col2 = st.columns(2)
            
            with col1:
                submit_btn = st.form_submit_button(
                    "✅ Return Materials",
                    type="primary",
                    use_container_width=True
                )
            
            with col2:
                reset_btn = st.form_submit_button(
                    "🔄 Reset",
                    use_container_width=True
                )
        
        # Handle form submission
        if reset_btn:
            st.session_state['return_form_data'] = {
                'quantities': {row['issue_detail_id']: 0.0 for _, row in returnable.iterrows()},
                'conditions': {row['issue_detail_id']: 'GOOD' for _, row in returnable.iterrows()},
                'reason': 'EXCESS',
                'returned_by': None,
                'received_by': None
            }
            st.rerun()
        
        if submit_btn:
            # Save form data
            st.session_state['return_form_data'] = {
                'quantities': form_quantities,
                'conditions': form_conditions,
                'reason': reason,
                'returned_by': returned_by,
                'received_by': received_by
            }
            
            self._execute_return(
                order_id, returnable, reason,
                returned_by if returned_by != "-- Select --" else None,
                received_by if received_by != "-- Select --" else None,
                emp_options, form_quantities, form_conditions
            )
    
    def _execute_return(self, order_id: int, returnable: pd.DataFrame,
                       reason: str, returned_by_label: Optional[str],
                       received_by_label: Optional[str], emp_options: Dict,
                       form_quantities: Dict, form_conditions: Dict):
        """Execute the material return"""
        # Build returns list
        returns = []
        for _, row in returnable.iterrows():
            issue_detail_id = row['issue_detail_id']
            return_qty = form_quantities.get(issue_detail_id, 0)
            condition = form_conditions.get(issue_detail_id, 'GOOD')
            
            if return_qty > 0:
                returns.append({
                    'issue_detail_id': issue_detail_id,
                    'material_id': row['material_id'],
                    'batch_no': row['batch_no'],
                    'quantity': return_qty,
                    'uom': row['uom'],
                    'condition': condition,
                    'expired_date': row['expired_date']
                })
        
        # Validation
        if not returns:
            st.warning("⚠️ No materials selected for return")
            return
        
        if returned_by_label is None:
            st.warning("⚠️ Please select production staff (Returned By)")
            return
        
        if received_by_label is None:
            st.warning("⚠️ Please select warehouse staff (Received By)")
            return
        
        try:
            audit_info = get_user_audit_info()
            returned_by_id = emp_options[returned_by_label]
            received_by_id = emp_options[received_by_label]
            
            with st.spinner("Processing return..."):
                result = self.manager.return_materials(
                    order_id=order_id,
                    returns=returns,
                    reason=reason,
                    user_id=audit_info['user_id'],
                    keycloak_id=audit_info['keycloak_id'],
                    returned_by=returned_by_id,
                    received_by=received_by_id
                )
            
            # Set success state
            st.session_state['return_success'] = True
            st.session_state['return_info'] = {
                'return_no': result['return_no'],
                'return_id': result['return_id'],
                'item_count': len(returns),
                'total_qty': sum(r['quantity'] for r in returns)
            }
            
            # Clear form data
            st.session_state.pop('return_form_data', None)
            st.session_state.pop('return_order_id', None)
            
            st.rerun()
            
        except Exception as e:
            st.error(f"❌ Error: {str(e)}")
            logger.error(f"Return error: {e}", exc_info=True)


# Convenience function

def render_return_form():
    """Render return materials form"""
    forms = ReturnForms()
    forms.render_return_form()