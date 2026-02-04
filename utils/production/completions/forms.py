# utils/production/completions/forms.py
"""
Form components for Completions domain
Production completion form with quantity and quality inputs

Version: 3.0.0
Changes:
- v3.0.0: Added pre & post validation for completion form
  - Duplicate batch_no check (warning, non-blocking)
  - Expiry date in past (warning, non-blocking)
  - Overproduction above remaining (warning, non-blocking)
  - Pending QC blocks order auto-completion (blocking)
  - In-form preview shows warnings before submit
  - _execute_completion checks again with fresh DB data
- v2.1.0: Cleaned up unused imports (format_date)
- v2.0.0: Added st.form() to prevent unnecessary reruns when changing inputs
- Fixed batch_no generation - now generates ONCE and persists in session state
- Added session state to preserve all form values
- Order selection remains outside form (needs to reload order info)
"""

import logging
from datetime import timedelta
from typing import Dict, Any, Optional

import streamlit as st
import pandas as pd

from .queries import CompletionQueries
from .manager import CompletionManager
from .common import (
    format_number, calculate_percentage, create_status_indicator,
    CompletionConstants, CompletionValidator, get_user_audit_info,
    get_vietnam_today, generate_batch_no, format_product_display
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
            st.info("🏭 No orders in progress")
            st.caption("Only IN_PROGRESS orders can have production completed")
            return
        
        # Create order options with new product format
        order_options = {
            f"{row['order_no']} | {format_product_display(row.to_dict())}": row['id']
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
        
        # Product display with new format
        product_display = format_product_display(order)
        st.info(f"**Product:** {product_display}")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
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
        
        # Pre-check: Pending QC status for this order
        pending_qc_count = self.queries.get_pending_receipts_count(order_id)
        if pending_qc_count > 0:
            st.warning(
                f"⚠️ **{pending_qc_count} receipt(s) with PENDING quality status.** "
                f"Order cannot auto-complete until all QC is resolved."
            )
        
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
            
            # ===== Pre-validation Warnings =====
            
            # Warning: overproduction
            remaining_qty = float(order['remaining_qty'])
            over_warn = CompletionValidator.check_overproduction_warning(
                produced_qty, remaining_qty, order['uom']
            )
            if over_warn:
                st.warning(f"⚠️ {over_warn}")
            
            # Warning: expiry date in past
            expiry_warn = CompletionValidator.check_expiry_warning(
                expired_date, get_vietnam_today()
            )
            if expiry_warn:
                st.warning(f"⚠️ {expiry_warn}")
            
            # Block: would auto-complete but has pending QC
            has_pending_block = False
            if will_complete:
                total_pending = pending_qc_count + (1 if quality_status == 'PENDING' else 0)
                if total_pending > 0:
                    has_pending_block = True
                    st.error(
                        f"🚫 **Cannot complete order:** {total_pending} receipt(s) will have PENDING QC.\n\n"
                        f"**Options:** Update QC of existing receipts, "
                        f"change quality status to PASSED/FAILED, "
                        f"or reduce quantity to keep order IN_PROGRESS."
                    )
            
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
        """Execute the production completion with pre-validation"""
        # Validation: batch_no required
        is_valid, error = CompletionValidator.validate_batch_no(batch_no)
        if not is_valid:
            st.warning(f"⚠️ {error}")
            return
        
        # Warning: duplicate batch_no (non-blocking)
        dup_check = self.queries.check_duplicate_batch_no(batch_no, order_id)
        if dup_check['is_duplicate']:
            orders_list = ", ".join(
                r['order_no'] for r in dup_check['existing'][:3]
            )
            st.warning(
                f"⚠️ Batch number **{batch_no}** already exists in "
                f"{dup_check['count']} other receipt(s) ({orders_list}). "
                f"Proceeding anyway."
            )
        
        # Warning: expiry date in past (non-blocking)
        expiry_warn = CompletionValidator.check_expiry_warning(
            expired_date, get_vietnam_today()
        )
        if expiry_warn:
            st.warning(f"⚠️ {expiry_warn} — proceeding anyway.")
        
        # Warning: overproduction (non-blocking)
        remaining = float(order['remaining_qty'])
        over_warn = CompletionValidator.check_overproduction_warning(
            produced_qty, remaining, order['uom']
        )
        if over_warn:
            st.warning(f"⚠️ {over_warn} — proceeding anyway.")
        
        # Block: pending QC prevents order auto-completion
        new_total = float(order.get('produced_qty') or 0) + produced_qty
        would_complete = new_total >= float(order['planned_qty'])
        
        if would_complete:
            pending_count = self.queries.get_pending_receipts_count(order_id)
            total_pending = pending_count + (1 if quality_status == 'PENDING' else 0)
            if total_pending > 0:
                st.error(
                    f"🚫 **Cannot complete order:** {total_pending} receipt(s) "
                    f"will have PENDING quality status.\n\n"
                    f"Resolve QC for pending receipts or change quality status to PASSED/FAILED."
                )
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