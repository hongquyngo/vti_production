# utils/production/completions/dialogs.py
"""
Dialog components for Completions domain
Receipt detail, quality update, PDF export dialogs

Version: 1.1.0
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
    CompletionConstants
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
    col1, col2 = st.columns(2)
    
    with col1:
        st.write(f"• **Receipt No:** {receipt['receipt_no']}")
        st.write(f"• **Receipt Date:** {format_datetime(receipt['receipt_date'])}")
        st.write(f"• **Batch No:** {receipt['batch_no']}")
        st.write(f"• **Product:** {receipt['product_name']}")
        if receipt.get('pt_code'):
            st.write(f"• **PT Code:** {receipt['pt_code']}")
    
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
            display_df['required_qty'] = display_df['required_qty'].apply(lambda x: format_number(x, 4))
            display_df['issued_qty'] = display_df['issued_qty'].apply(lambda x: format_number(x, 4))
            display_df['status'] = display_df['status'].apply(create_status_indicator)
            
            st.dataframe(
                display_df[['material_name', 'pt_code', 'required_qty', 'issued_qty', 'uom', 'status']].rename(columns={
                    'material_name': 'Material',
                    'pt_code': 'PT Code',
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


# ==================== Update Quality Dialog ====================

@st.dialog("✏️ Update Quality Status", width="medium")
def show_update_quality_dialog(receipt_id: int):
    """
    Show quality update dialog
    
    Args:
        receipt_id: Receipt ID to update
    """
    queries = CompletionQueries()
    receipt = queries.get_receipt_details(receipt_id)
    
    if not receipt:
        st.error("❌ Receipt not found")
        return
    
    st.markdown(f"### Receipt: {receipt['receipt_no']}")
    
    col1, col2 = st.columns(2)
    with col1:
        st.info(f"**Product:** {receipt['product_name']}")
        st.info(f"**Quantity:** {format_number(receipt['quantity'], 2)} {receipt['uom']}")
    with col2:
        st.info(f"**Batch:** {receipt['batch_no']}")
        st.info(f"**Current Status:** {create_status_indicator(receipt['quality_status'])}")
    
    st.markdown("---")
    
    # Quality status selection
    quality_options = [q[0] for q in CompletionConstants.QUALITY_STATUSES]
    quality_labels = {q[0]: q[1] for q in CompletionConstants.QUALITY_STATUSES}
    
    current_index = quality_options.index(receipt['quality_status']) if receipt['quality_status'] in quality_options else 0
    
    new_status = st.selectbox(
        "New Quality Status",
        options=quality_options,
        format_func=lambda x: quality_labels.get(x, x),
        index=current_index,
        key="new_quality_status"
    )
    
    notes = st.text_area(
        "Quality Notes",
        value=receipt.get('notes') or "",
        height=150,
        key="quality_notes"
    )
    
    # Warning for status changes
    if receipt['quality_status'] == 'PASSED' and new_status != 'PASSED':
        st.warning("⚠️ Changing from PASSED to another status will remove inventory")
    elif receipt['quality_status'] != 'PASSED' and new_status == 'PASSED':
        st.info("ℹ️ Changing to PASSED will add inventory")
    
    st.markdown("---")
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("✅ Update", type="primary", use_container_width=True,
                    key="quality_update_btn"):
            try:
                audit_info = get_user_audit_info()
                manager = CompletionManager()
                
                with st.spinner("Updating quality status..."):
                    success = manager.update_quality_status(
                        receipt_id=receipt_id,
                        new_status=new_status,
                        notes=notes,
                        user_id=audit_info['user_id'],
                        keycloak_id=audit_info['keycloak_id']
                    )
                
                if success:
                    st.success(f"✅ Quality status updated to {new_status}")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("❌ Failed to update quality status")
                    
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")
                logger.error(f"Quality update failed: {e}", exc_info=True)
    
    with col2:
        if st.button("❌ Cancel", use_container_width=True, key="quality_cancel_btn"):
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
