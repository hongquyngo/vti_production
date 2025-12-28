# utils/production/completions/dialogs.py
"""
Dialog components for Completions domain
Receipt detail, quality update, PDF export dialogs

Version: 3.0.0
Changes:
- v3.0.0: Full partial QC support with 3 inputs (passed, pending, failed)
  - Added pending_qty input for partial pending scenarios
  - Preview shows impact for all 3 statuses
  - Supports all 7 QC scenarios including 3-way split
- v2.0.0: Updated QC dialog to support partial results (passed_qty + failed_qty)
- Added defect type selection for failed items
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
    CompletionConstants, format_product_display, format_material_display
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
    st.markdown("### 📦 Output Information")
    
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
        st.progress(efficiency / 100)
        st.caption(f"Production Efficiency: {efficiency}%")
    
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
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("No material usage data available")
    
    st.markdown("---")
    
    # Action buttons
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("📄 Export PDF", type="primary", use_container_width=True,
                    key="detail_export_pdf_btn"):
            # Set session state to open PDF dialog after rerun (avoid nested dialog)
            st.session_state['open_receipt_pdf_dialog'] = True
            st.session_state['receipt_pdf_id'] = receipt_id
            st.session_state['receipt_pdf_no'] = receipt['receipt_no']
            st.rerun()
    
    with col2:
        if st.button("✏️ Update Quality", use_container_width=True,
                    key="detail_update_quality_btn"):
            # Set session state to open quality dialog after rerun
            st.session_state['open_quality_dialog'] = True
            st.session_state['quality_receipt_id'] = receipt_id
            st.rerun()
    
    with col3:
        if st.button("✖️ Close", use_container_width=True, key="detail_close_btn"):
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

@st.dialog("🔬 Update Quality Status", width="large")
def show_update_quality_dialog(receipt_id: int):
    """
    Show quality update dialog with full partial QC support
    Allows specifying passed_qty, pending_qty, and failed_qty separately
    
    Supports all 7 scenarios:
    1. All PASSED
    2. All PENDING
    3. All FAILED
    4. PASSED + FAILED
    5. PASSED + PENDING
    6. PENDING + FAILED
    7. PASSED + PENDING + FAILED
    
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
    
    # Header
    st.markdown(f"### Receipt: {receipt['receipt_no']}")
    
    # Product display with new format
    product_display = format_product_display(receipt)
    st.info(f"**Product:** {product_display}")
    
    # Receipt info cards
    col1, col2 = st.columns(2)
    with col1:
        st.info(f"**Total Qty:** {format_number(total_qty, 2)} {receipt['uom']}")
    with col2:
        st.info(f"**Batch:** {receipt['batch_no']}")
        st.info(f"**Current Status:** {create_status_indicator(current_status)}")
    
    st.markdown("---")
    
    # QC Result Section
    st.markdown("### 📊 QC Result Breakdown")
    st.caption("Enter quantities for each QC result. Total must equal the receipt quantity.")
    
    # Initialize session state for QC values based on current status
    if 'qc_passed_qty' not in st.session_state:
        if current_status == 'PASSED':
            st.session_state.qc_passed_qty = total_qty
            st.session_state.qc_pending_qty = 0.0
            st.session_state.qc_failed_qty = 0.0
        elif current_status == 'FAILED':
            st.session_state.qc_passed_qty = 0.0
            st.session_state.qc_pending_qty = 0.0
            st.session_state.qc_failed_qty = total_qty
        else:  # PENDING
            st.session_state.qc_passed_qty = 0.0
            st.session_state.qc_pending_qty = total_qty
            st.session_state.qc_failed_qty = 0.0
    
    # Three-column layout for QC inputs
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("##### ✅ Passed")
        passed_qty = st.number_input(
            "Passed Quantity",
            min_value=0.0,
            max_value=total_qty,
            value=float(st.session_state.qc_passed_qty),
            step=1.0,
            format="%.2f",
            key="input_passed_qty",
            label_visibility="collapsed",
            help="Quantity that passed quality check - will be added to available inventory"
        )
    
    with col2:
        st.markdown("##### ⏳ Pending")
        pending_qty = st.number_input(
            "Pending Quantity",
            min_value=0.0,
            max_value=total_qty,
            value=float(st.session_state.qc_pending_qty),
            step=1.0,
            format="%.2f",
            key="input_pending_qty",
            label_visibility="collapsed",
            help="Quantity still awaiting QC - not yet in inventory"
        )
    
    with col3:
        st.markdown("##### ❌ Failed")
        failed_qty = st.number_input(
            "Failed Quantity",
            min_value=0.0,
            max_value=total_qty,
            value=float(st.session_state.qc_failed_qty),
            step=1.0,
            format="%.2f",
            key="input_failed_qty",
            label_visibility="collapsed",
            help="Quantity that failed QC - will not be added to inventory"
        )
    
    # Update session state
    st.session_state.qc_passed_qty = passed_qty
    st.session_state.qc_pending_qty = pending_qty
    st.session_state.qc_failed_qty = failed_qty
    
    # Validation
    sum_qty = passed_qty + pending_qty + failed_qty
    remaining = total_qty - sum_qty
    is_valid = False
    
    if abs(remaining) < 0.001:  # Allow small floating point differences
        st.success(f"✅ **Total matches:** {format_number(sum_qty, 2)} = {format_number(total_qty, 2)} {receipt['uom']}")
        is_valid = True
    elif remaining > 0:
        st.warning(f"⚠️ **Remaining:** {format_number(remaining, 2)} {receipt['uom']} not assigned")
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
    
    # Preview Section - Inventory Impact
    st.markdown("### 📋 Preview - Inventory Impact")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if passed_qty > 0:
            st.success(f"📗 **{format_number(passed_qty, 2)} {receipt['uom']}**\n\n→ GOOD Inventory")
        else:
            st.info("📗 No items to GOOD inventory")
    
    with col2:
        if pending_qty > 0:
            st.warning(f"📙 **{format_number(pending_qty, 2)} {receipt['uom']}**\n\n→ Awaiting QC")
        else:
            st.info("📙 No items pending")
    
    with col3:
        if failed_qty > 0:
            st.error(f"📕 **{format_number(failed_qty, 2)} {receipt['uom']}**\n\n→ DEFECTIVE")
        else:
            st.info("📕 No failed items")
    
    # Determine scenario and show split info
    has_passed = passed_qty > 0
    has_pending = pending_qty > 0
    has_failed = failed_qty > 0
    portions = sum([has_passed, has_pending, has_failed])
    
    if portions > 1:
        st.markdown("---")
        st.markdown("### 📑 Receipt Split Preview")
        
        split_info = []
        if has_passed:
            split_info.append(f"✅ Original receipt → **PASSED** ({format_number(passed_qty, 2)})")
        if has_pending:
            if has_passed:
                split_info.append(f"⏳ New receipt → **PENDING** ({format_number(pending_qty, 2)})")
            else:
                split_info.append(f"⏳ Original receipt → **PENDING** ({format_number(pending_qty, 2)})")
        if has_failed:
            split_info.append(f"❌ New receipt → **FAILED** ({format_number(failed_qty, 2)})")
        
        for info in split_info:
            st.write(info)
        
        st.caption("💡 Split priority: PASSED > PENDING > FAILED. Original receipt keeps highest priority status.")
    
    # Special case warnings
    if current_status == 'PASSED':
        if pending_qty > 0 or failed_qty > 0:
            removed_qty = pending_qty + failed_qty
            st.warning(
                f"⚠️ **Attention:** This receipt was previously PASSED. "
                f"{format_number(removed_qty, 2)} {receipt['uom']} will be removed from GOOD inventory."
            )
    
    st.markdown("---")
    
    # Action Buttons
    col1, col2 = st.columns(2)
    
    with col1:
        update_disabled = not is_valid or (failed_qty > 0 and not defect_type)
        
        if not is_valid:
            st.caption("⚠️ Total quantity must match")
        elif failed_qty > 0 and not defect_type:
            st.caption("⚠️ Please select defect type")
        
        if st.button("✅ Update QC Result", type="primary", use_container_width=True,
                    disabled=update_disabled, key="qc_update_btn"):
            try:
                audit_info = get_user_audit_info()
                manager = CompletionManager()
                
                with st.spinner("Updating quality status..."):
                    result = manager.update_quality_status_partial(
                        receipt_id=receipt_id,
                        passed_qty=passed_qty,
                        pending_qty=pending_qty,
                        failed_qty=failed_qty,
                        defect_type=defect_type,
                        notes=notes,
                        user_id=audit_info['user_id'],
                        keycloak_id=audit_info['keycloak_id']
                    )
                
                if result.get('success'):
                    # Clear session state
                    st.session_state.pop('qc_passed_qty', None)
                    st.session_state.pop('qc_pending_qty', None)
                    st.session_state.pop('qc_failed_qty', None)
                    
                    # Show success message
                    msg_parts = []
                    if passed_qty > 0:
                        msg_parts.append(f"✅ {format_number(passed_qty, 2)} PASSED")
                    if pending_qty > 0:
                        msg_parts.append(f"⏳ {format_number(pending_qty, 2)} PENDING")
                    if failed_qty > 0:
                        msg_parts.append(f"❌ {format_number(failed_qty, 2)} FAILED")
                    
                    st.success(f"QC Updated: {' | '.join(msg_parts)}")
                    
                    # Show new receipts created
                    new_receipts = result.get('new_receipts', [])
                    if new_receipts:
                        for nr in new_receipts:
                            st.info(f"📝 New {nr['status']} receipt: **{nr['receipt_no']}** ({format_number(nr['qty'], 2)})")
                    elif result.get('new_receipt_no'):
                        # Backward compatibility
                        st.info(f"📝 New receipt created: {result['new_receipt_no']}")
                    
                    time.sleep(1.5)
                    st.rerun()
                else:
                    st.error(f"❌ Failed to update: {result.get('error', 'Unknown error')}")
                    
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")
                logger.error(f"Quality update failed: {e}", exc_info=True)
    
    with col2:
        if st.button("❌ Cancel", use_container_width=True, key="qc_cancel_btn"):
            # Clear session state
            st.session_state.pop('qc_passed_qty', None)
            st.session_state.pop('qc_pending_qty', None)
            st.session_state.pop('qc_failed_qty', None)
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
        if st.button("📥 Generate PDF", type="primary", use_container_width=True,
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
        if st.button("✖️ Cancel", use_container_width=True, key="pdf_cancel_btn"):
            st.rerun()


# ==================== Check for pending dialogs ====================

def check_pending_dialogs():
    """
    Check if there's a pending dialog to open.
    Call this at the start of the page render.
    This prevents nested dialog errors.
    """
    # Check for PDF dialog
    if st.session_state.get('open_receipt_pdf_dialog'):
        receipt_id = st.session_state.pop('receipt_pdf_id', None)
        receipt_no = st.session_state.pop('receipt_pdf_no', '')
        st.session_state.pop('open_receipt_pdf_dialog', None)
        if receipt_id:
            show_pdf_dialog(receipt_id, receipt_no)
    
    # Check for quality dialog
    if st.session_state.get('open_quality_dialog'):
        receipt_id = st.session_state.pop('quality_receipt_id', None)
        st.session_state.pop('open_quality_dialog', None)
        if receipt_id:
            show_update_quality_dialog(receipt_id)


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