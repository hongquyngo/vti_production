# utils/production/completions/dialogs.py
"""
Dialog components for Production Receipts domain
Receipt detail, quality update (with guards), PDF export, close order dialogs

Version: 4.3.0
Changes:
- v4.3.0: Allow under-production MO completion
  - show_close_order_select_dialog: show under-target indicator (⚠️ icon + shortfall)
  - show_close_order_dialog: add under-production warning (non-blocking)
  - Permanent warning includes under-production note when applicable
- v4.2.1: Fix check_pending_dialogs() — use elif chain instead of sequential if
  - Streamlit allows only 1 dialog per render cycle
  - Sequential if could attempt to open multiple dialogs, losing flags silently
- v4.2.0: Dialog-based UI flow
  - NEW: show_close_order_select_dialog() — replaces close order page view
  - Updated check_pending_dialogs() for close order select → confirm flow
- v4.0.0: Production Receipts refactoring
  - QC dialog: ONLY PENDING receipts can be updated (PASSED/FAILED locked)
  - QC dialog: Blocked when MO = COMPLETED
  - QC dialog: Removed ability to assign back to PENDING (one-way)
  - Added aging warning display in QC dialog
  - NEW: show_close_order_dialog() for manual order closure
  - Updated check_pending_dialogs() for close order dialog
- v3.0.0: Full partial QC support with 3 inputs
"""

import logging
import time
from typing import Dict, Any, Optional

import streamlit as st
import pandas as pd

from .queries import CompletionQueries
from .manager import CompletionManager
from .pdf_generator import ReceiptPDFGenerator
from .common import (
    format_number, calculate_percentage, create_status_indicator,
    format_datetime, get_vietnam_now, get_user_audit_info,
    CompletionConstants, format_product_display, format_material_display,
    get_aging_indicator, get_aging_message
)

logger = logging.getLogger(__name__)


# ==================== Receipt Detail Dialog ====================

@st.dialog("📦 Receipt Details", width="large")
def show_receipt_details_dialog(receipt_id: int):
    """
    Show receipt details dialog
    
    Args:
        receipt_id: Receipt ID to display
    """
    queries = CompletionQueries()
    receipt = queries.get_receipt_details(receipt_id)
    
    if not receipt:
        st.error("❌ Receipt not found")
        return
    
    # Header
    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown(f"### 📦 {receipt['receipt_no']}")
    with col2:
        st.markdown(f"**{create_status_indicator(receipt['quality_status'])}**")
    
    st.markdown("---")
    
    # Output info
    st.markdown("### 📦 Receipt Information")
    
    # Product display with new format
    product_display = format_product_display(receipt)
    st.info(f"**Product:** {product_display}")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.write(f"• **Receipt No:** {receipt['receipt_no']}")
        st.write(f"• **Receipt Date:** {format_datetime(receipt['receipt_date'])}")
        st.write(f"• **Batch No:** {receipt['batch_no']}")
    
    with col2:
        st.write(f"• **Quantity:** {format_number(receipt['quantity'], 2)} {receipt['uom']}")
        st.write(f"• **Warehouse:** {receipt['warehouse_name']}")
        st.write(f"• **Quality Status:** {create_status_indicator(receipt['quality_status'])}")
        if receipt.get('expired_date'):
            from .common import format_date
            st.write(f"• **Expiry Date:** {format_date(receipt['expired_date'])}")
    
    st.markdown("---")
    
    # Order info
    st.markdown("### 📋 Order Information")
    col1, col2 = st.columns(2)
    
    with col1:
        st.write(f"• **Order No:** {receipt['order_no']}")
        st.write(f"• **BOM:** {receipt.get('bom_name', 'N/A')}")
    
    with col2:
        st.write(f"• **Planned Qty:** {format_number(receipt['planned_qty'], 2)} {receipt['uom']}")
        st.write(f"• **Produced Qty:** {format_number(receipt['produced_qty'], 2)} {receipt['uom']}")
    
    # Progress
    if receipt['planned_qty'] > 0:
        efficiency = calculate_percentage(receipt['produced_qty'], receipt['planned_qty'])
        st.progress(min(efficiency / 100, 1.0))
        st.caption(f"Completion rate: {efficiency}%")
    
    # Notes
    if receipt.get('notes'):
        st.markdown("---")
        st.markdown("### 📝 Notes")
        st.text(receipt['notes'])
    
    st.markdown("---")
    
    # Material usage
    with st.expander("📦 Material Usage", expanded=False):
        materials = queries.get_receipt_materials(receipt['manufacturing_order_id'])
        if not materials.empty:
            display_df = materials.copy()
            
            # Format material display with new format
            display_df['material_display'] = display_df.apply(
                lambda row: format_material_display(row.to_dict(), show_type=True), axis=1
            )
            display_df['required_qty'] = display_df['required_qty'].apply(lambda x: format_number(x, 4))
            display_df['issued_qty'] = display_df['issued_qty'].apply(lambda x: format_number(x, 4))
            display_df['status'] = display_df['status'].apply(create_status_indicator)
            
            st.dataframe(
                display_df[['material_display', 'required_qty', 'issued_qty', 'uom', 'status']].rename(columns={
                    'material_display': 'Material',
                    'required_qty': 'Required',
                    'issued_qty': 'Issued',
                    'uom': 'UOM',
                    'status': 'Status'
                }),
                width='stretch',
                hide_index=True
            )
        else:
            st.info("No material usage data available")
    
    st.markdown("---")
    
    # Action buttons
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("📄 Export PDF", type="primary", width='stretch',
                    key="detail_export_pdf_btn"):
            # Set session state to open PDF dialog after rerun (avoid nested dialog)
            st.session_state['open_receipt_pdf_dialog'] = True
            st.session_state['receipt_pdf_id'] = receipt_id
            st.session_state['receipt_pdf_no'] = receipt['receipt_no']
            st.rerun()
    
    with col2:
        if st.button("🔬 QC Decision", width='stretch',
                    key="detail_update_quality_btn"):
            # Set session state to open quality dialog after rerun
            st.session_state['open_quality_dialog'] = True
            st.session_state['quality_receipt_id'] = receipt_id
            st.rerun()
    
    with col3:
        if st.button("✖️ Close", width='stretch', key="detail_close_btn"):
            st.rerun()


# ==================== Update Quality Dialog (Full Partial QC Support) ====================

# Defect types for failed items
DEFECT_TYPES = [
    ('VISUAL', '🔍 Visual Defect - Lỗi ngoại quan'),
    ('DIMENSIONAL', '📏 Dimensional - Sai kích thước'),
    ('FUNCTIONAL', '⚙️ Functional - Lỗi chức năng'),
    ('CONTAMINATION', '🧪 Contamination - Nhiễm bẩn'),
    ('PACKAGING', '📦 Packaging - Lỗi đóng gói'),
    ('OTHER', '❓ Other - Khác'),
]

@st.dialog("🔬 QC Decision", width="large")
def show_update_quality_dialog(receipt_id: int):
    """
    Show quality decision dialog — ONLY for PENDING receipts on IN_PROGRESS MOs.
    
    Guards:
    - PASSED/FAILED receipts → locked, show message
    - MO = COMPLETED → locked, show message
    - One-way only: PENDING → PASSED and/or FAILED (no back to PENDING)
    
    Args:
        receipt_id: Receipt ID to update
    """
    queries = CompletionQueries()
    receipt = queries.get_receipt_details(receipt_id)
    
    if not receipt:
        st.error("❌ Receipt not found")
        return
    
    total_qty = float(receipt['quantity'])
    current_status = receipt['quality_status']
    order_status = receipt.get('order_status', '')
    
    # ===== GUARD: Check MO status =====
    if order_status == 'COMPLETED':
        st.error("🔒 **MO is completed** — all QC decisions are locked.")
        st.info(f"Receipt: {receipt['receipt_no']} | Status: {create_status_indicator(current_status)}")
        if st.button("Close", width='stretch', key="qc_close_locked"):
            st.rerun()
        return
    
    # ===== GUARD: Check receipt status =====
    if current_status in ('PASSED', 'FAILED'):
        st.error(
            f"🔒 **Receipt is {current_status}** — QC decision is final.\n\n"
            f"Only PENDING receipts can be updated."
        )
        st.info(f"Receipt: {receipt['receipt_no']} | Status: {create_status_indicator(current_status)}")
        if st.button("Close", width='stretch', key="qc_close_final"):
            st.rerun()
        return
    
    # ===== PENDING receipt — allow update =====
    
    # Header
    st.markdown(f"### Receipt: {receipt['receipt_no']}")
    
    product_display = format_product_display(receipt)
    st.info(f"**Product:** {product_display}")
    
    col1, col2 = st.columns(2)
    with col1:
        st.info(f"**Total Qty:** {format_number(total_qty, 2)} {receipt['uom']}")
    with col2:
        st.info(f"**Batch:** {receipt['batch_no']}")
    
    # Aging warning
    age_days = None
    if receipt.get('created_date'):
        from datetime import datetime
        try:
            created = receipt['created_date']
            if isinstance(created, str):
                created = datetime.strptime(created, '%Y-%m-%d %H:%M:%S')
            age_days = (datetime.now() - created).days
        except Exception:
            pass
    
    aging_msg = get_aging_message(age_days) if age_days else None
    if aging_msg:
        aging_icon = get_aging_indicator(age_days)
        st.warning(f"{aging_icon} **{aging_msg}**")
    
    st.info(f"**Current Status:** {create_status_indicator(current_status)}")
    
    st.markdown("---")
    
    # QC Decision — PENDING can only go to PASSED or FAILED
    st.markdown("### 📊 QC Decision")
    st.caption("Classify this PENDING quantity as PASSED and/or FAILED. No quantity can remain PENDING.")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("##### ✅ Passed")
        passed_qty = st.number_input(
            "Passed Quantity",
            min_value=0.0,
            max_value=total_qty,
            value=total_qty,  # Default: all passed
            step=1.0,
            format="%.2f",
            key="input_passed_qty",
            label_visibility="collapsed",
            help="Quantity that passed QC — will be added to FG warehouse"
        )
    
    with col2:
        st.markdown("##### ❌ Failed")
        failed_qty = st.number_input(
            "Failed Quantity",
            min_value=0.0,
            max_value=total_qty,
            value=0.0,
            step=1.0,
            format="%.2f",
            key="input_failed_qty",
            label_visibility="collapsed",
            help="Quantity that failed QC — rejected, not added to inventory"
        )
    
    # Validation — must equal total, NO pending allowed
    sum_qty = passed_qty + failed_qty
    remaining = total_qty - sum_qty
    is_valid = False
    
    if abs(remaining) < 0.001:
        st.success(f"✅ **Total matches:** {format_number(sum_qty, 2)} = {format_number(total_qty, 2)} {receipt['uom']}")
        is_valid = True
    elif remaining > 0:
        st.warning(f"⚠️ **Remaining:** {format_number(remaining, 2)} {receipt['uom']} — all quantity must be assigned to PASSED or FAILED")
    else:
        st.error(f"❌ **Over-assigned:** {format_number(abs(remaining), 2)} {receipt['uom']} exceeds total")
    
    st.markdown("---")
    
    # Defect Type (only if failed_qty > 0)
    defect_type = None
    if failed_qty > 0:
        st.markdown("### ⚠️ Defect Information")
        
        defect_options = [d[0] for d in DEFECT_TYPES]
        defect_labels = {d[0]: d[1] for d in DEFECT_TYPES}
        
        defect_type = st.selectbox(
            "Defect Type *",
            options=defect_options,
            format_func=lambda x: defect_labels.get(x, x),
            key="select_defect_type",
            help="Required when there are failed items"
        )
    
    # QC Notes
    st.markdown("### 📝 QC Notes")
    notes = st.text_area(
        "Notes",
        value=receipt.get('notes') or "",
        height=100,
        placeholder="Enter QC findings, observations, or reasons for failure...",
        key="qc_notes",
        label_visibility="collapsed"
    )
    
    st.markdown("---")
    
    # Preview — Inventory Impact
    st.markdown("### 📋 Preview — Inventory Impact")
    
    col1, col2 = st.columns(2)
    
    with col1:
        if passed_qty > 0:
            st.success(f"📗 **{format_number(passed_qty, 2)} {receipt['uom']}**\n\n→ FG Warehouse")
        else:
            st.info("📗 No items to FG warehouse")
    
    with col2:
        if failed_qty > 0:
            st.error(f"📕 **{format_number(failed_qty, 2)} {receipt['uom']}**\n\n→ Rejected")
        else:
            st.info("📕 No rejected items")
    
    # Split preview
    has_passed = passed_qty > 0
    has_failed = failed_qty > 0
    
    if has_passed and has_failed:
        st.markdown("---")
        st.markdown("### 📑 Receipt Split Preview")
        st.write(f"✅ Original receipt → **PASSED** ({format_number(passed_qty, 2)})")
        st.write(f"❌ New receipt → **FAILED** ({format_number(failed_qty, 2)})")
        st.caption("💡 Original receipt keeps PASSED status (higher priority).")
    
    st.markdown("---")
    
    # Action Buttons
    col1, col2 = st.columns(2)
    
    with col1:
        update_disabled = not is_valid or (failed_qty > 0 and not defect_type)
        
        if not is_valid:
            st.caption("⚠️ Total quantity must match")
        elif failed_qty > 0 and not defect_type:
            st.caption("⚠️ Please select defect type")
        
        if st.button("✅ Confirm QC Decision", type="primary", width='stretch',
                    disabled=update_disabled, key="qc_update_btn"):
            try:
                audit_info = get_user_audit_info()
                manager = CompletionManager()
                
                with st.spinner("Recording QC decision..."):
                    # Use partial update — pending_qty = 0 (one-way, no back to PENDING)
                    result = manager.update_quality_status_partial(
                        receipt_id=receipt_id,
                        passed_qty=passed_qty,
                        pending_qty=0.0,  # Never assign back to PENDING
                        failed_qty=failed_qty,
                        defect_type=defect_type,
                        notes=notes,
                        user_id=audit_info['user_id'],
                        keycloak_id=audit_info['keycloak_id']
                    )
                
                if result.get('success'):
                    msg_parts = []
                    if passed_qty > 0:
                        msg_parts.append(f"✅ {format_number(passed_qty, 2)} PASSED")
                    if failed_qty > 0:
                        msg_parts.append(f"❌ {format_number(failed_qty, 2)} FAILED")
                    
                    st.success(f"QC Decision recorded: {' | '.join(msg_parts)}")
                    
                    new_receipts = result.get('new_receipts', [])
                    if new_receipts:
                        for nr in new_receipts:
                            st.info(f"📝 New {nr['status']} receipt: **{nr['receipt_no']}** ({format_number(nr['qty'], 2)})")
                    
                    time.sleep(1.5)
                    st.rerun()
                else:
                    st.error(f"❌ Failed to update: {result.get('error', 'Unknown error')}")
                    
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")
                logger.error(f"Quality update failed: {e}", exc_info=True)
    
    with col2:
        if st.button("❌ Cancel", width='stretch', key="qc_cancel_btn"):
            st.rerun()


# ==================== PDF Export Dialog ====================

@st.dialog("📄 Export Receipt PDF", width="medium")
def show_pdf_dialog(receipt_id: int, receipt_no: str):
    """
    Show PDF export options dialog
    
    Args:
        receipt_id: Receipt ID
        receipt_no: Receipt number for display
    """
    st.markdown(f"### 📄 Export: {receipt_no}")
    
    col1, col2 = st.columns(2)
    
    with col1:
        language = st.selectbox(
            "🌐 Language / Ngôn ngữ",
            options=['vi', 'en'],
            format_func=lambda x: "🇻🇳 Tiếng Việt" if x == 'vi' else "🇬🇧 English",
            index=0,
            key="pdf_language"
        )
    
    with col2:
        layout = st.selectbox(
            "📐 Layout",
            options=['landscape', 'portrait'],
            format_func=lambda x: "🖼️ Landscape (Ngang)" if x == 'landscape' else "📄 Portrait (Dọc)",
            index=0,  # Default landscape
            key="pdf_layout"
        )
    
    st.markdown("---")
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("📥 Generate PDF", type="primary", width='stretch',
                    key="generate_pdf_btn"):
            with st.spinner("Generating PDF..."):
                try:
                    pdf_gen = ReceiptPDFGenerator()
                    pdf_bytes = pdf_gen.generate_pdf(
                        receipt_id=receipt_id,
                        language=language,
                        layout=layout
                    )
                    
                    if pdf_bytes:
                        filename = f"{receipt_no}_{language}.pdf"
                        st.download_button(
                            label="💾 Download PDF",
                            data=pdf_bytes,
                            file_name=filename,
                            mime="application/pdf",
                            key="download_receipt_pdf"
                        )
                        st.success("✅ PDF generated successfully!")
                    else:
                        st.error("❌ Failed to generate PDF")
                        
                except Exception as e:
                    st.error(f"❌ Error: {str(e)}")
                    logger.error(f"PDF generation failed: {e}", exc_info=True)
    
    with col2:
        if st.button("✖️ Cancel", width='stretch', key="pdf_cancel_btn"):
            st.rerun()


# ==================== Close Order Dialog ====================

@st.dialog("🔒 Complete Manufacturing Order", width="medium")
def show_close_order_dialog(order_id: int):
    """
    Confirmation dialog for completing (closing) an MO.
    Shows validation results and requires explicit confirmation.
    """
    queries = CompletionQueries()
    validation = queries.get_close_order_validation(order_id)
    
    if not validation:
        st.error("❌ Could not validate order")
        return
    
    st.markdown(f"### 🔒 Complete MO: {validation.get('order_no', 'N/A')}")
    
    # Order summary
    produced = validation.get('produced_qty', 0)
    planned = validation.get('planned_qty', 0)
    uom = validation.get('uom', '')
    yield_pct = calculate_percentage(produced, planned)
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Planned", f"{format_number(planned, 2)} {uom}")
    with col2:
        st.metric("Produced", f"{format_number(produced, 2)} {uom}")
    with col3:
        st.metric("Yield", f"{yield_pct}%")
    
    # Under-production warning (non-blocking)
    if produced < planned:
        shortfall = planned - produced
        st.warning(
            f"📉 **Under target:** produced {format_number(produced, 2)} / "
            f"planned {format_number(planned, 2)} {uom} "
            f"(shortfall: {format_number(shortfall, 2)} {uom}, yield: {yield_pct}%)"
        )
    
    st.markdown("---")
    
    # Validation checklist
    st.markdown("### ✅ Pre-conditions")
    
    can_close = validation.get('can_close', False)
    reasons = validation.get('reasons', [])
    
    checks = [
        ("Status = IN_PROGRESS", validation.get('status') == 'IN_PROGRESS'),
        ("At least 1 receipt exists", validation.get('receipt_count', 0) > 0),
        ("No PENDING QC receipts", validation.get('pending_count', 0) == 0),
    ]
    
    for label, passed in checks:
        icon = "✅" if passed else "❌"
        st.write(f"{icon} {label}")
    
    if reasons:
        st.markdown("---")
        st.error("**Cannot close order:**")
        for reason in reasons:
            st.write(f"• {reason}")
    
    # Receipt summary
    st.markdown("---")
    st.markdown("### 📊 Receipt Summary")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("✅ Passed", validation.get('passed_count', 0))
    with col2:
        st.metric("⏳ Pending", validation.get('pending_count', 0))
    with col3:
        st.metric("❌ Failed", validation.get('failed_count', 0))
    
    if can_close:
        st.markdown("---")
        under_target = produced < planned
        under_note = "\n- ⚠️ **Under-production will be recorded as final**" if under_target else ""
        st.warning(
            "⚠️ **This action is permanent.** After completion:\n"
            "- No more production receipts can be created\n"
            "- QC decisions cannot be changed\n"
            "- Material issues/returns are blocked"
            f"{under_note}"
        )
    
    st.markdown("---")
    
    # Action buttons
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("🔒 Confirm Completion", type="primary", width='stretch',
                     disabled=not can_close, key="close_order_confirm_btn"):
            try:
                audit_info = get_user_audit_info()
                manager = CompletionManager()
                
                with st.spinner("Completing MO..."):
                    result = manager.close_order(
                        order_id=order_id,
                        user_id=audit_info['user_id']
                    )
                
                if result.get('success'):
                    st.success(f"🔒 MO **{result['order_no']}** has been completed.")
                    time.sleep(1.5)
                    st.rerun()
                else:
                    st.error(f"❌ Failed: {result.get('error', 'Unknown error')}")
                    
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")
                logger.error(f"Complete MO failed: {e}", exc_info=True)
    
    with col2:
        if st.button("Cancel", width='stretch', key="close_order_cancel_btn"):
            st.rerun()


# ==================== Complete MO Select Dialog ====================

@st.dialog("🔒 Complete Manufacturing Order", width="large")
def show_close_order_select_dialog():
    """
    Dialog for selecting and completing MOs.
    Shows ready-to-complete and blocked orders.
    """
    queries = CompletionQueries()
    
    st.caption("Select an MO to complete. All QC must be resolved before completion.")
    
    ready_info = queries.get_ready_to_close_orders()
    
    if ready_info['ready_count'] == 0 and ready_info['blocked_count'] == 0:
        st.info("📭 No MOs are ready to complete. Orders need to meet their production target first.")
        return
    
    # Show ready orders
    if ready_info['ready_count'] > 0:
        st.success(f"✅ **{ready_info['ready_count']} MO(s) ready to complete**")
        
        for order in ready_info['ready_orders']:
            with st.container(border=True):
                col1, col2, col3 = st.columns([3, 2, 1])
                with col1:
                    yield_pct = calculate_percentage(order['produced_qty'], order['planned_qty'])
                    under_target = float(order['produced_qty']) < float(order['planned_qty'])
                    target_icon = "⚠️" if under_target else "✅"
                    st.markdown(
                        f"**{order['order_no']}** | {order['product_name']}"
                    )
                    st.caption(
                        f"{target_icon} Produced: {format_number(order['produced_qty'], 2)}"
                        f" / {format_number(order['planned_qty'], 2)} {order['uom']}"
                        f" ({yield_pct}%)"
                    )
                    if under_target:
                        shortfall = float(order['planned_qty']) - float(order['produced_qty'])
                        st.caption(f"📉 Under target by {format_number(shortfall, 2)} {order['uom']}")
                with col2:
                    st.caption(f"Receipts: {order['receipt_count']}")
                with col3:
                    if st.button("🔒 Complete", key=f"close_order_{order['id']}",
                                width='stretch'):
                        # Use pending dialog pattern to avoid nested dialog
                        st.session_state['open_close_order_dialog'] = True
                        st.session_state['close_order_id'] = int(order['id'])
                        st.rerun()
    
    # Show blocked orders
    if ready_info['blocked_count'] > 0:
        st.warning(f"⏳ **{ready_info['blocked_count']} MO(s) blocked by pending QC**")
        
        for order in ready_info['blocked_orders']:
            st.caption(
                f"• **{order['order_no']}** — {order['product_name']} "
                f"({int(order['pending_count'])} pending receipts)"
            )


# ==================== Check for pending dialogs ====================

def check_pending_dialogs():
    """
    Check if there's a pending dialog to open.
    Call this at the start of the page render.
    This prevents nested dialog errors.
    
    Uses elif chain: Streamlit allows only ONE dialog per render cycle.
    If multiple flags are set (edge case), only the first is opened;
    the rest are consumed to prevent stale flags persisting forever.
    """
    # Check for PDF dialog
    if st.session_state.get('open_receipt_pdf_dialog'):
        receipt_id = st.session_state.pop('receipt_pdf_id', None)
        receipt_no = st.session_state.pop('receipt_pdf_no', '')
        st.session_state.pop('open_receipt_pdf_dialog', None)
        if receipt_id:
            show_pdf_dialog(receipt_id, receipt_no)
    
    # Check for quality dialog
    elif st.session_state.get('open_quality_dialog'):
        receipt_id = st.session_state.pop('quality_receipt_id', None)
        st.session_state.pop('open_quality_dialog', None)
        if receipt_id:
            show_update_quality_dialog(receipt_id)
    
    # Check for close order confirm dialog (from close order select dialog)
    elif st.session_state.get('open_close_order_dialog'):
        order_id = st.session_state.pop('close_order_id', None)
        st.session_state.pop('open_close_order_dialog', None)
        if order_id:
            show_close_order_dialog(order_id)
    
    # Check for close order select dialog
    elif st.session_state.get('open_close_order_select_dialog'):
        st.session_state.pop('open_close_order_select_dialog', None)
        show_close_order_select_dialog()
    
    # Check for record output dialog
    elif st.session_state.get('open_record_output_dialog'):
        st.session_state.pop('open_record_output_dialog', None)
        from .forms import show_record_output_dialog  # lazy import to avoid circular
        show_record_output_dialog()


# ==================== Quick Action Functions ====================

def handle_row_action(action: str, receipt_id: int):
    """
    Handle row action button clicks
    
    Args:
        action: Action type (view, update_quality)
        receipt_id: Receipt ID
    """
    if action == 'view':
        show_receipt_details_dialog(receipt_id)
    elif action == 'update_quality':
        show_update_quality_dialog(receipt_id)