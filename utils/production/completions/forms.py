# utils/production/completions/forms.py
"""
Form components for Completions domain
Production completion form with quantity and quality inputs

Version: 2.0.0
Changes:
- Added st.form() to prevent unnecessary reruns when changing inputs
- Fixed batch_no generation - now generates ONCE and persists in session state
- Added session state to preserve all form values
- Order selection remains outside form (needs to reload order info)
"""

import logging
from datetime import timedelta
from typing import Dict, Any, Optional, List

import streamlit as st
import pandas as pd

from .queries import CompletionQueries
from .manager import CompletionManager
from .common import (
    format_number, calculate_percentage, create_status_indicator, format_date,
    CompletionConstants, CompletionValidator, get_user_audit_info,
    get_vietnam_today, get_vietnam_now, generate_batch_no
)

logger = logging.getLogger(__name__)


class CompletionForms:
    """Form components for Production Completion"""
    
    def __init__(self):
        self.queries = CompletionQueries()
        self.manager = CompletionManager()
    
    # ==================== Production Completion Form ====================
    
    def render_completion_form(self):
        """Render production completion form"""
        st.subheader("✅ Complete Production Order")
        
        # Check for success message
        if st.session_state.get('completion_success'):
            completion_info = st.session_state.get('completion_info', {})
            
            status_text = "Order Completed" if completion_info.get('order_completed') else "Partial - In Progress"
            
            st.success(f"""
            ✅ **Production Output Recorded!**
            • Receipt No: **{completion_info.get('receipt_no', 'N/A')}**
            • Quantity: **{format_number(completion_info.get('quantity', 0), 2)}**
            • Batch: **{completion_info.get('batch_no', 'N/A')}**
            • Quality: **{completion_info.get('quality_status', 'N/A')}**
            • Status: **{status_text}**
            """)
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button("✅ Record Another Output", type="primary",
                           use_container_width=True, key="btn_another_completion"):
                    st.session_state.pop('completion_success', None)
                    st.session_state.pop('completion_info', None)
                    st.rerun()
            with col2:
                if st.button("📋 View Receipts", use_container_width=True, 
                           key="btn_view_receipts"):
                    st.session_state.completions_view = 'receipts'
                    st.session_state.pop('completion_success', None)
                    st.session_state.pop('completion_info', None)
                    st.rerun()
            return
        
        # Step 1: Select Order (outside form - needs to reload order info)
        orders = self.queries.get_completable_orders()
        
        if orders.empty:
            st.info("📭 No orders in progress")
            st.caption("Only IN_PROGRESS orders can have production completed")
            return
        
        # Create order options
        order_options = {
            f"{row['order_no']} | {row['pt_code']} - {row['product_name']}": row['id']
            for _, row in orders.iterrows()
        }
        
        selected_label = st.selectbox(
            "Select Production Order",
            options=list(order_options.keys()),
            key="completion_order_select"
        )
        
        order_id = order_options[selected_label]
        order = orders[orders['id'] == order_id].iloc[0].to_dict()
        
        # Order Information
        st.markdown("### 📋 Order Information")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.info(f"**Product:** {order['product_name']}")
            st.info(f"**Planned:** {format_number(order['planned_qty'], 2)} {order['uom']}")
        
        with col2:
            st.info(f"**Produced:** {format_number(order['produced_qty'], 2)} {order['uom']}")
            st.info(f"**Remaining:** {format_number(order['remaining_qty'], 2)} {order['uom']}")
        
        with col3:
            progress = calculate_percentage(order['produced_qty'], order['planned_qty'])
            st.info(f"**Progress:** {progress}%")
            st.progress(progress / 100)
        
        # Existing receipts summary
        output_summary = self.queries.get_order_output_summary(order_id)
        
        if output_summary and output_summary['receipt_count'] > 0:
            st.markdown("### 📦 Existing Production Receipts")
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric("Total Receipts", 
                         f"{format_number(output_summary['total_receipts'], 2)} {order['uom']}")
            with col2:
                st.metric("Receipt Count", output_summary['receipt_count'])
            with col3:
                st.metric("Current Yield", f"{output_summary['yield_rate']}%")
            
            with st.expander("View Receipt Details", expanded=False):
                receipts = self.queries.get_order_receipts(order_id)
                if not receipts.empty:
                    display_df = receipts.copy()
                    display_df['receipt_date'] = pd.to_datetime(display_df['receipt_date']).dt.strftime('%d/%m/%Y %H:%M')
                    display_df['quantity'] = display_df.apply(
                        lambda x: f"{format_number(x['quantity'], 2)} {x['uom']}", axis=1
                    )
                    display_df['quality_status'] = display_df['quality_status'].apply(create_status_indicator)
                    
                    st.dataframe(
                        display_df[['receipt_no', 'receipt_date', 'quantity', 'batch_no', 'quality_status']].rename(columns={
                            'receipt_no': 'Receipt No',
                            'receipt_date': 'Date',
                            'quantity': 'Quantity',
                            'batch_no': 'Batch',
                            'quality_status': 'Quality'
                        }),
                        use_container_width=True,
                        hide_index=True
                    )
        
        st.markdown("---")
        
        # Initialize/reset form data when order changes
        # CRITICAL: This prevents batch_no from regenerating on every rerun
        if st.session_state.get('completion_order_id') != order_id:
            st.session_state['completion_order_id'] = order_id
            remaining = float(order['remaining_qty'])
            
            st.session_state['completion_form_data'] = {
                'produced_qty': remaining if remaining > 0 else 1.0,
                'batch_no': generate_batch_no(),  # Generate ONCE when order changes
                'quality_status': 'PENDING',
                'expired_date': get_vietnam_today() + timedelta(days=365),
                'notes': ''
            }
        
        form_data = st.session_state['completion_form_data']
        
        # ========== FORM - Prevents reruns when changing inputs ==========
        st.markdown("### 🏭 Record Production Output")
        st.caption("💡 Enter production details. **No page reload when changing values!**")
        
        remaining = float(order['remaining_qty'])
        max_qty = remaining * 1.5  # Allow 50% overproduction
        
        with st.form(key="completion_form", clear_on_submit=False):
            col1, col2 = st.columns(2)
            
            with col1:
                produced_qty = st.number_input(
                    "Produced Quantity",
                    min_value=0.01,
                    max_value=max(max_qty, 1.0),
                    value=float(min(form_data['produced_qty'], max(max_qty, 1.0))),
                    step=0.1,
                    format="%.2f",
                    key="form_produced_qty"
                )
                
                batch_no = st.text_input(
                    "Batch Number",
                    value=form_data['batch_no'],
                    key="form_batch_no"
                )
                
                quality_options = [q[0] for q in CompletionConstants.QUALITY_STATUSES]
                quality_labels = {q[0]: q[1] for q in CompletionConstants.QUALITY_STATUSES}
                
                quality_idx = quality_options.index(form_data['quality_status']) if form_data['quality_status'] in quality_options else 0
                quality_status = st.selectbox(
                    "Quality Status",
                    options=quality_options,
                    format_func=lambda x: quality_labels.get(x, x),
                    index=quality_idx,
                    key="form_quality_status"
                )
            
            with col2:
                expired_date = st.date_input(
                    "Expiry Date",
                    value=form_data['expired_date'],
                    key="form_expiry_date"
                )
                
                notes = st.text_area(
                    "Production Notes",
                    value=form_data['notes'],
                    height=100,
                    placeholder="Optional notes about this production batch...",
                    key="form_completion_notes"
                )
            
            st.markdown("---")
            
            # Output Preview (calculated from current form values)
            st.markdown("### 📊 Output Preview")
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                new_total = order['produced_qty'] + produced_qty
                st.info(f"**New Total:** {format_number(new_total, 2)} {order['uom']}")
            
            with col2:
                new_yield = calculate_percentage(new_total, order['planned_qty'])
                st.info(f"**New Yield:** {new_yield}%")
            
            with col3:
                will_complete = new_total >= order['planned_qty']
                status_text = "✅ Will Complete" if will_complete else "🔄 Partial"
                st.info(f"**Status:** {status_text}")
            
            st.markdown("---")
            
            # Form submit buttons
            col1, col2 = st.columns(2)
            
            with col1:
                submit_btn = st.form_submit_button(
                    "✅ Record Output",
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
            remaining = float(order['remaining_qty'])
            st.session_state['completion_form_data'] = {
                'produced_qty': remaining if remaining > 0 else 1.0,
                'batch_no': generate_batch_no(),  # Generate new batch_no on reset
                'quality_status': 'PENDING',
                'expired_date': get_vietnam_today() + timedelta(days=365),
                'notes': ''
            }
            st.rerun()
        
        if submit_btn:
            # Save form data to session state
            st.session_state['completion_form_data'] = {
                'produced_qty': produced_qty,
                'batch_no': batch_no,
                'quality_status': quality_status,
                'expired_date': expired_date,
                'notes': notes
            }
            
            self._execute_completion(
                order_id, order, produced_qty, batch_no,
                quality_status, expired_date, notes
            )
    
    def _execute_completion(self, order_id: int, order: Dict,
                           produced_qty: float, batch_no: str,
                           quality_status: str, expired_date,
                           notes: str):
        """Execute the production completion"""
        # Validation
        is_valid, error = CompletionValidator.validate_batch_no(batch_no)
        if not is_valid:
            st.warning(f"⚠️ {error}")
            return
        
        try:
            audit_info = get_user_audit_info()
            
            with st.spinner("Recording production output..."):
                result = self.manager.complete_production(
                    order_id=order_id,
                    produced_qty=produced_qty,
                    batch_no=batch_no,
                    warehouse_id=order['target_warehouse_id'],
                    quality_status=quality_status,
                    user_id=audit_info['user_id'],
                    keycloak_id=audit_info['keycloak_id'],
                    expiry_date=expired_date,
                    notes=notes
                )
            
            # Set success state
            st.session_state['completion_success'] = True
            st.session_state['completion_info'] = result
            
            # Clear form data
            st.session_state.pop('completion_form_data', None)
            st.session_state.pop('completion_order_id', None)
            
            st.rerun()
            
        except Exception as e:
            st.error(f"❌ Error: {str(e)}")
            logger.error(f"Completion error: {e}", exc_info=True)


# Convenience function

def render_completion_form():
    """Render production completion form"""
    forms = CompletionForms()
    forms.render_completion_form()