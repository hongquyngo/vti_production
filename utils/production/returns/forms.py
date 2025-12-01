# utils/production/returns/forms.py
"""
Form components for Returns domain
Return materials form with quantity and condition editing

Version: 1.0.0
"""

import logging
from typing import Dict, Any, Optional, List

import streamlit as st
import pandas as pd

from .queries import ReturnQueries
from .manager import ReturnManager
from .common import (
    format_number, create_status_indicator, format_date,
    ReturnConstants, ReturnValidator, get_user_audit_info
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
        
        # Step 1: Select Order
        orders = self.queries.get_returnable_orders()
        
        if orders.empty:
            st.info("📭 No orders with issued materials found")
            st.caption("Only IN_PROGRESS orders can have materials returned")
            return
        
        # Create order options
        order_options = {
            f"{row['order_no']} | {row['pt_code']} - {row['product_name']}": row['id']
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
        display_df['issued'] = display_df.apply(
            lambda x: f"{format_number(x['issued_qty'], 4)} {x['uom']}", axis=1
        )
        display_df['returnable'] = display_df.apply(
            lambda x: f"{format_number(x['returnable_qty'], 4)} {x['uom']}", axis=1
        )
        display_df['issue_date_display'] = pd.to_datetime(display_df['issue_date']).dt.strftime('%d/%m/%Y')
        
        st.dataframe(
            display_df[['display_name', 'batch_no', 'issued', 'returnable', 'issue_no', 'issue_date_display']].rename(columns={
                'display_name': 'Material',
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
        st.markdown("### ↩️ Return Details")
        
        # Initialize session state for return quantities
        if 'return_quantities' not in st.session_state or st.session_state.get('return_order_id') != order_id:
            st.session_state['return_quantities'] = {}
            st.session_state['return_conditions'] = {}
            st.session_state['return_order_id'] = order_id
        
        # Material rows for return
        for idx, row in returnable.iterrows():
            self._render_return_row(row)
        
        st.markdown("---")
        
        # Return reason
        col1, col2 = st.columns(2)
        with col1:
            reason_options = [r[0] for r in ReturnConstants.REASONS]
            reason_labels = {r[0]: r[1] for r in ReturnConstants.REASONS}
            reason = st.selectbox(
                "Return Reason",
                options=reason_options,
                format_func=lambda x: reason_labels.get(x, x),
                key="return_reason"
            )
        
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
            returned_by = st.selectbox(
                "Returned By (Production Staff)",
                options=emp_list,
                key="return_returned_by"
            )
        with col2:
            received_by = st.selectbox(
                "Received By (Warehouse Staff)",
                options=emp_list,
                key="return_received_by"
            )
        
        st.markdown("---")
        
        # Action buttons
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("✅ Return Materials", type="primary", 
                        use_container_width=True, key="btn_return"):
                self._execute_return(
                    order_id, returnable, reason,
                    returned_by if returned_by != "-- Select --" else None,
                    received_by if received_by != "-- Select --" else None,
                    emp_options
                )
        
        with col2:
            if st.button("🔄 Reset", use_container_width=True, key="btn_reset_return"):
                st.session_state.pop('return_quantities', None)
                st.session_state.pop('return_conditions', None)
                st.session_state.pop('return_order_id', None)
                st.rerun()
    
    def _render_return_row(self, row: pd.Series):
        """Render a single return row"""
        issue_detail_id = row['issue_detail_id']
        material_name = row['display_name']
        batch_no = row['batch_no']
        returnable_qty = float(row['returnable_qty'])
        uom = row['uom']
        
        st.markdown(f"**{material_name}** (Batch: {batch_no})")
        
        col1, col2 = st.columns([2, 1])
        
        with col1:
            return_qty = st.number_input(
                f"Return Qty (max: {format_number(returnable_qty, 4)} {uom})",
                min_value=0.0,
                max_value=float(returnable_qty),
                value=st.session_state['return_quantities'].get(issue_detail_id, 0.0),
                step=0.0001,
                format="%.4f",
                key=f"return_qty_{issue_detail_id}"
            )
            st.session_state['return_quantities'][issue_detail_id] = return_qty
        
        with col2:
            condition_options = [c[0] for c in ReturnConstants.CONDITIONS]
            condition_labels = {c[0]: c[1] for c in ReturnConstants.CONDITIONS}
            condition = st.selectbox(
                "Condition",
                options=condition_options,
                format_func=lambda x: condition_labels.get(x, x),
                index=0,
                key=f"condition_{issue_detail_id}"
            )
            st.session_state['return_conditions'][issue_detail_id] = condition
        
        st.markdown("---")
    
    def _execute_return(self, order_id: int, returnable: pd.DataFrame,
                       reason: str, returned_by_label: Optional[str],
                       received_by_label: Optional[str], emp_options: Dict):
        """Execute the material return"""
        # Build returns list
        returns = []
        for _, row in returnable.iterrows():
            issue_detail_id = row['issue_detail_id']
            return_qty = st.session_state['return_quantities'].get(issue_detail_id, 0)
            condition = st.session_state['return_conditions'].get(issue_detail_id, 'GOOD')
            
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
            
            # Clear quantities
            st.session_state.pop('return_quantities', None)
            st.session_state.pop('return_conditions', None)
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
