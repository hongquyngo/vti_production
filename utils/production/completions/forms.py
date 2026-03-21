# utils/production/completions/forms.py
"""
Form components for Production Receipts domain
Record production output with QC breakdown (passed/pending/failed)

Version: 4.2.0
Changes:
- v4.2.0: Dialog-based UI flow
  - Converted to @st.dialog — no more view switching / full page rerun
  - show_record_output_dialog() opens as overlay on receipts page
  - Success: "Record Another" reopens dialog, "Done" closes to receipts
  - Removed render_completion_form() convenience function
- v4.1.0: Fix form not refreshing when switching MO
  - Clear cached widget keys on order change and reset
  - Trigger st.rerun() after clearing to force fresh render
- v4.0.0: Production Receipts refactoring
  - Replaced single quality_status selectbox with 3 QC quantity inputs
  - produced_qty derived from sum of passed + pending + failed
  - Removed overproduction limit (no max_qty cap)
  - Removed auto-complete logic — MO stays IN_PROGRESS
  - Added defect_type inline (moved from QC dialog)
  - Updated _execute_completion to call new manager API
- v3.0.0: Added pre & post validation for completion form
- v2.0.0: Added st.form() to prevent unnecessary reruns
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


# Defect types (moved from dialogs.py for inline use)
DEFECT_TYPES = [
    ('VISUAL', '🔍 Visual Defect - Lỗi ngoại quan'),
    ('DIMENSIONAL', '📏 Dimensional - Sai kích thước'),
    ('FUNCTIONAL', '⚙️ Functional - Lỗi chức năng'),
    ('CONTAMINATION', '🧪 Contamination - Nhiễm bẩn'),
    ('PACKAGING', '📦 Packaging - Lỗi đóng gói'),
    ('OTHER', '❓ Other - Khác'),
]

# Base widget key names used inside the completion form
_FORM_WIDGET_BASES = [
    'form_passed_qty', 'form_pending_qty', 'form_failed_qty',
    'form_batch_no', 'form_expiry_date', 'form_defect_type',
    'form_completion_notes'
]


def _clear_form_widget_keys(order_id=None):
    """Clear cached form widget keys from session state.
    With dynamic keys (scoped to order_id), clears the specific suffixed keys.
    Also clears any legacy static keys for safety.
    """
    for base in _FORM_WIDGET_BASES:
        st.session_state.pop(base, None)  # legacy static key
        if order_id is not None:
            st.session_state.pop(f"{base}_{order_id}", None)


class CompletionForms:
    """Form components for Production Output Recording"""
    
    def __init__(self):
        self.queries = CompletionQueries()
        self.manager = CompletionManager()
    
    # ==================== Production Output Form ====================
    
    def render_completion_form(self):
        """Render production output recording form (called inside dialog)"""
        
        # Check for success message
        if st.session_state.get('completion_success'):
            self._render_success_message()
            return
        
        # Step 1: Select Order (outside form)
        orders = self.queries.get_completable_orders()
        
        if orders.empty:
            st.info("🏭 No orders in progress")
            st.caption("Only IN_PROGRESS orders can have production recorded")
            return
        
        # Create order options
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
        self._render_order_info(order, order_id)
        
        st.markdown("---")
        
        # Initialize form data when order changes
        if st.session_state.get('completion_order_id') != order_id:
            st.session_state['completion_order_id'] = order_id
            remaining = float(order['remaining_qty'])
            
            st.session_state['completion_form_data'] = {
                'passed_qty': remaining if remaining > 0 else 0.0,
                'pending_qty': 0.0,
                'failed_qty': 0.0,
                'batch_no': generate_batch_no(),
                'expired_date': get_vietnam_today() + timedelta(days=365),
                'defect_type_idx': 0,
                'notes': ''
            }
            
            # Clear cached widget keys for this order_id in case user is revisiting.
            # NO st.rerun() — keys are popped BEFORE form widgets are created
            # in this render cycle, so value= parameter will be used correctly.
            # (st.rerun() inside @st.dialog closes the dialog!)
            _clear_form_widget_keys(order_id)
        
        form_data = st.session_state['completion_form_data']
        
        # ========== FORM ==========
        # Dynamic keys scoped to order_id: when MO switches, all widgets
        # are brand new with no cached state — value= params always apply.
        st.markdown("### 🏭 Production Receipt")
        st.caption("💡 Enter quality classification. Total = Passed + Pending + Failed.")
        
        k = f"_{order_id}"  # key suffix for all widgets in this form
        
        with st.form(key=f"completion_form{k}", clear_on_submit=False):
            # Quality Classification — 3 columns
            st.markdown("#### 📊 Quality Classification")
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.markdown("##### ✅ Passed")
                passed_qty = st.number_input(
                    "Passed Quantity",
                    min_value=0.0,
                    value=float(form_data['passed_qty']),
                    step=1.0,
                    format="%.2f",
                    key=f"form_passed_qty{k}",
                    label_visibility="collapsed",
                    help="Quantity that passed QC — will be added to inventory"
                )
            
            with col2:
                st.markdown("##### ⏳ Pending")
                pending_qty = st.number_input(
                    "Pending Quantity",
                    min_value=0.0,
                    value=float(form_data['pending_qty']),
                    step=1.0,
                    format="%.2f",
                    key=f"form_pending_qty{k}",
                    label_visibility="collapsed",
                    help="Quantity awaiting QC — NOT in inventory until resolved"
                )
            
            with col3:
                st.markdown("##### ❌ Failed")
                failed_qty = st.number_input(
                    "Failed Quantity",
                    min_value=0.0,
                    value=float(form_data['failed_qty']),
                    step=1.0,
                    format="%.2f",
                    key=f"form_failed_qty{k}",
                    label_visibility="collapsed",
                    help="Quantity that failed QC — will NOT be added to inventory"
                )
            
            total_produced = passed_qty + pending_qty + failed_qty
            
            # Total display
            if total_produced > 0:
                st.info(f"**Total Produced:** {format_number(total_produced, 2)} {order['uom']}")
            else:
                st.warning("⚠️ Total produced quantity must be greater than 0")
            
            st.markdown("---")
            
            # Other fields
            col1, col2 = st.columns(2)
            
            with col1:
                batch_no = st.text_input(
                    "Batch Number",
                    value=form_data['batch_no'],
                    key=f"form_batch_no{k}"
                )
                
                expired_date = st.date_input(
                    "Expiry Date",
                    value=form_data['expired_date'],
                    key=f"form_expiry_date{k}"
                )
            
            with col2:
                # Defect type — only relevant when failed_qty > 0
                defect_type = None
                if failed_qty > 0:
                    defect_options = [d[0] for d in DEFECT_TYPES]
                    defect_labels = {d[0]: d[1] for d in DEFECT_TYPES}
                    
                    defect_type = st.selectbox(
                        "Defect Type *",
                        options=defect_options,
                        format_func=lambda x: defect_labels.get(x, x),
                        index=form_data.get('defect_type_idx', 0),
                        key=f"form_defect_type{k}",
                        help="Required when there are failed items"
                    )
                else:
                    st.info("💡 Defect type shown when Failed qty > 0")
                
                notes = st.text_area(
                    "Production Notes",
                    value=form_data['notes'],
                    height=100,
                    placeholder="Optional notes about this production batch...",
                    key=f"form_completion_notes{k}"
                )
            
            st.markdown("---")
            
            # Receipt Preview
            st.markdown("### 📊 Receipt Preview")
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                new_total = float(order['produced_qty']) + total_produced
                st.info(f"**New Total:** {format_number(new_total, 2)} {order['uom']}")
            
            with col2:
                new_yield = calculate_percentage(new_total, order['planned_qty'])
                st.info(f"**New Yield:** {new_yield}%")
            
            with col3:
                st.info("**Status:** MO remains open")
            
            # Inventory impact preview
            col1, col2, col3 = st.columns(3)
            with col1:
                if passed_qty > 0:
                    st.success(f"📗 **{format_number(passed_qty, 2)} {order['uom']}** → FG Warehouse")
            with col2:
                if pending_qty > 0:
                    st.warning(f"📙 **{format_number(pending_qty, 2)} {order['uom']}** → Awaiting QC")
            with col3:
                if failed_qty > 0:
                    st.error(f"📕 **{format_number(failed_qty, 2)} {order['uom']}** → Rejected")
            
            # Warnings
            remaining_qty = float(order['remaining_qty'])
            over_warn = CompletionValidator.check_overproduction_warning(
                total_produced, remaining_qty, order['uom']
            )
            if over_warn:
                st.warning(f"⚠️ {over_warn}")
            
            expiry_warn = CompletionValidator.check_expiry_warning(
                expired_date, get_vietnam_today()
            )
            if expiry_warn:
                st.warning(f"⚠️ {expiry_warn}")
            
            st.markdown("---")
            
            # Submit buttons
            col1, col2 = st.columns(2)
            
            with col1:
                submit_btn = st.form_submit_button(
                    "📦 Confirm Receipt",
                    type="primary",
                    width='stretch'
                )
            
            with col2:
                reset_btn = st.form_submit_button(
                    "🔄 Reset",
                    width='stretch'
                )
        
        # Handle form submission
        if reset_btn:
            remaining = float(order['remaining_qty'])
            st.session_state['completion_form_data'] = {
                'passed_qty': remaining if remaining > 0 else 0.0,
                'pending_qty': 0.0,
                'failed_qty': 0.0,
                'batch_no': generate_batch_no(),
                'expired_date': get_vietnam_today() + timedelta(days=365),
                'defect_type_idx': 0,
                'notes': ''
            }
            _clear_form_widget_keys(order_id)
            # st.rerun() inside @st.dialog closes the dialog,
            # so set reopen flag first to immediately reopen with fresh values
            st.session_state['open_record_output_dialog'] = True
            st.rerun()
        
        if submit_btn:
            # Save form data to session state
            st.session_state['completion_form_data'] = {
                'passed_qty': passed_qty,
                'pending_qty': pending_qty,
                'failed_qty': failed_qty,
                'batch_no': batch_no,
                'expired_date': expired_date,
                'defect_type_idx': form_data.get('defect_type_idx', 0),
                'notes': notes
            }
            
            self._execute_completion(
                order_id, order, passed_qty, pending_qty, failed_qty,
                batch_no, defect_type, expired_date, notes
            )
    
    # ==================== Private Helpers ====================
    
    def _render_success_message(self):
        """Render success message after recording output"""
        completion_info = st.session_state.get('completion_info', {})
        
        receipts = completion_info.get('receipts', [])
        receipt_lines = []
        for r in receipts:
            receipt_lines.append(
                f"• **{r['receipt_no']}** — {format_number(r['qty'], 2)} {r['status']}"
            )
        receipts_text = "\n".join(receipt_lines) if receipt_lines else f"• {completion_info.get('receipt_no', 'N/A')}"
        
        st.success(f"""
        📦 **Production Receipt Created!**
        
        **Receipts:**
        {receipts_text}
        
        • Batch: **{completion_info.get('batch_no', 'N/A')}**
        • Total: **{format_number(completion_info.get('quantity', 0), 2)}**
        • MO Status: **Open** (receipt more or complete)
        """)
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("📦 New Receipt", type="primary",
                       width='stretch', key="btn_another_completion"):
                st.session_state.pop('completion_success', None)
                st.session_state.pop('completion_info', None)
                old_order_id = st.session_state.pop('completion_order_id', None)
                _clear_form_widget_keys(old_order_id)
                # Reopen dialog with fresh form
                st.session_state['open_record_output_dialog'] = True
                st.rerun()
        with col2:
            if st.button("✅ Done", width='stretch', 
                       key="btn_view_receipts"):
                st.session_state.pop('completion_success', None)
                st.session_state.pop('completion_info', None)
                st.rerun()
    
    def _render_order_info(self, order: Dict, order_id: int):
        """Render order information section"""
        st.markdown("### 📋 Order Information")
        
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
            st.progress(min(progress / 100, 1.0))
        
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
                        width='stretch',
                        hide_index=True
                    )
    
    def _execute_completion(self, order_id: int, order: Dict,
                           passed_qty: float, pending_qty: float, failed_qty: float,
                           batch_no: str, defect_type: Optional[str],
                           expired_date, notes: str):
        """Execute the production output recording"""
        total = passed_qty + pending_qty + failed_qty
        
        # Validation: total > 0
        if total <= 0:
            st.warning("⚠️ Total produced quantity must be greater than 0")
            return
        
        # Validation: batch_no required
        is_valid, error = CompletionValidator.validate_batch_no(batch_no)
        if not is_valid:
            st.warning(f"⚠️ {error}")
            return
        
        # Validation: defect_type required if failed
        if failed_qty > 0 and not defect_type:
            st.warning("⚠️ Please select a defect type for failed items")
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
        
        try:
            audit_info = get_user_audit_info()
            
            with st.spinner("Recording production output..."):
                result = self.manager.complete_production(
                    order_id=order_id,
                    passed_qty=passed_qty,
                    pending_qty=pending_qty,
                    failed_qty=failed_qty,
                    batch_no=batch_no,
                    warehouse_id=order['target_warehouse_id'],
                    user_id=audit_info['user_id'],
                    keycloak_id=audit_info['keycloak_id'],
                    expiry_date=expired_date,
                    defect_type=defect_type,
                    notes=notes
                )
            
            # Set success state
            st.session_state['completion_success'] = True
            st.session_state['completion_info'] = result
            
            # Clear form data
            st.session_state.pop('completion_form_data', None)
            old_order_id = st.session_state.pop('completion_order_id', None)
            _clear_form_widget_keys(old_order_id)
            
            # Reopen dialog to show success message
            # (st.rerun() closes the dialog, flag reopens it)
            st.session_state['open_record_output_dialog'] = True
            st.rerun()
            
        except Exception as e:
            st.error(f"❌ Error: {str(e)}")
            logger.error(f"Production output error: {e}", exc_info=True)


# ==================== Dialog Entry Point ====================

@st.dialog("📦 Production Receipt", width="large")
def show_record_output_dialog():
    """
    Dialog wrapper for Production Receipt form.
    Opens as overlay — no page navigation needed.
    Receipts list stays rendered behind the dialog.
    """
    forms = CompletionForms()
    forms.render_completion_form()