# utils/production/issues/dialogs.py
"""
Dialog components for Issues domain
Success, Detail, PDF dialogs

Version: 1.0.0
"""

import logging
from typing import Dict, Any, Optional
import time

import streamlit as st
import pandas as pd

from .queries import IssueQueries
from .common import (
    format_number, create_status_indicator, format_datetime,
    get_vietnam_now, format_product_display
)

logger = logging.getLogger(__name__)


# ==================== Success Dialog ====================

@st.dialog("✅ Material Issue Successful", width="medium")
def show_success_dialog(result: Dict[str, Any]):
    """
    Show success dialog after issue with PDF option
    
    Args:
        result: Issue result containing issue_no, issue_id, details, substitutions
    """
    issue_no = result['issue_no']
    issue_id = result['issue_id']
    details = result.get('details', [])
    substitutions = result.get('substitutions', [])
    
    st.success(f"✅ Materials issued successfully!")
    st.markdown(f"**Issue No:** `{issue_no}`")
    
    # Summary
    total_items = len(details)
    total_qty = sum(d['quantity'] for d in details)
    
    st.markdown(f"**Items:** {total_items} | **Total Qty:** {format_number(total_qty, 4)}")
    
    # Show substitutions if any
    if substitutions:
        st.markdown("---")
        st.markdown("🔄 **Material Substitutions:**")
        for sub in substitutions:
            st.write(
                f"• {sub['original_material']} → {sub['substitute_material']}: "
                f"{format_number(sub['actual_quantity'], 4)} {sub['uom']}"
            )
    
    st.markdown("---")
    
    # Actions
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("📄 Export PDF", type="primary", use_container_width=True,
                    key="success_pdf_btn"):
            # Set session state to open PDF dialog after rerun
            st.session_state['open_issue_pdf_dialog'] = True
            st.session_state['issue_pdf_id'] = issue_id
            st.session_state['issue_pdf_no'] = issue_no
            st.rerun()
    
    with col2:
        if st.button("✅ Done", use_container_width=True, key="success_done_btn"):
            st.rerun()


# ==================== Issue Detail Dialog ====================

@st.dialog("📋 Issue Details", width="large")
def show_detail_dialog(issue_id: int):
    """
    Show issue details dialog
    
    Args:
        issue_id: Issue ID to display
    """
    queries = IssueQueries()
    issue = queries.get_issue_details(issue_id)
    
    if not issue:
        st.error("❌ Issue not found")
        return
    
    # Header
    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown(f"### 📋 {issue['issue_no']}")
    with col2:
        st.markdown(f"**{create_status_indicator(issue['status'])}**")
    
    st.markdown("---")
    
    # Issue info
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**📅 Issue Information**")
        st.write(f"• **Date:** {format_datetime(issue['issue_date'])}")
        st.write(f"• **Order:** {issue['order_no']}")
        # Product với format: code (legacy|NEW) | name | size (brand)
        product_display = format_product_display(
            pt_code=issue.get('pt_code'),
            legacy_pt_code=issue.get('legacy_pt_code'),
            product_name=issue.get('product_name'),
            package_size=issue.get('package_size'),
            brand_name=issue.get('brand_name')
        )
        st.write(f"• **Product:** {product_display}")
        st.write(f"• **Warehouse:** {issue['warehouse_name']}")
    
    with col2:
        st.markdown("**👤 Personnel**")
        st.write(f"• **Issued By:** {issue['issued_by_name'] or 'N/A'}")
        st.write(f"• **Received By:** {issue['received_by_name'] or 'N/A'}")
        st.write(f"• **Created By:** {issue['created_by_name'] or 'N/A'}")
    
    # Notes
    if issue.get('notes'):
        st.markdown("---")
        st.markdown("**📝 Notes**")
        st.text(issue['notes'])
    
    # Materials
    st.markdown("---")
    st.markdown("### 📦 Issued Materials")
    
    materials = queries.get_issue_materials(issue_id)
    
    if not materials.empty:
        display_df = materials.copy()
        display_df['material_info'] = display_df.apply(
            lambda x: f"{x['material_name']}" + 
                     (f" (Alt: {x['original_material_name']})" if x.get('is_alternative') else ""),
            axis=1
        )
        # Format: code (legacy|NEW)
        display_df['code_display'] = display_df.apply(
            lambda x: f"{x['pt_code']} ({x['legacy_pt_code'] if x.get('legacy_pt_code') else 'NEW'})",
            axis=1
        )
        # Format: size (brand)
        display_df['size_brand'] = display_df.apply(
            lambda x: f"{x['package_size'] or ''}" + (f" ({x['brand_name']})" if x.get('brand_name') else ""),
            axis=1
        )
        display_df['qty'] = display_df['quantity'].apply(lambda x: format_number(x, 4))
        display_df['expiry'] = pd.to_datetime(display_df['expired_date']).dt.strftime('%d/%m/%Y')
        
        st.dataframe(
            display_df[['material_info', 'code_display', 'size_brand', 'batch_no', 'qty', 'uom', 'expiry']].rename(columns={
                'material_info': 'Material',
                'code_display': 'Code (Legacy)',
                'size_brand': 'Size (Brand)',
                'batch_no': 'Batch',
                'qty': 'Quantity',
                'uom': 'UOM',
                'expiry': 'Expiry'
            }),
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("No materials in this issue")
    
    st.markdown("---")
    
    # Action buttons - Use session state to trigger PDF dialog after closing this one
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("📄 Export PDF", type="primary", use_container_width=True,
                    key="detail_pdf_btn"):
            # Set session state to open PDF dialog after rerun
            st.session_state['open_issue_pdf_dialog'] = True
            st.session_state['issue_pdf_id'] = issue_id
            st.session_state['issue_pdf_no'] = issue['issue_no']
            st.rerun()
    
    with col2:
        if st.button("✖️ Close", use_container_width=True, key="detail_close_btn"):
            st.rerun()


# ==================== PDF Export Dialog ====================

@st.dialog("📄 Export Issue PDF", width="medium")
def show_pdf_dialog(issue_id: int, issue_no: str):
    """
    Show PDF export dialog
    
    Args:
        issue_id: Issue ID
        issue_no: Issue number for filename
    """
    st.markdown(f"### 📄 Export: {issue_no}")
    
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
                    key="pdf_gen_btn"):
            try:
                from .pdf_generator import IssuePDFGenerator
                
                with st.spinner("Generating PDF..."):
                    generator = IssuePDFGenerator()
                    pdf_content = generator.generate_pdf(
                        issue_id,
                        language=language,
                        layout=layout
                    )
                
                if pdf_content:
                    timestamp = get_vietnam_now().strftime('%Y%m%d_%H%M%S')
                    filename = f"Issue_{issue_no}_{timestamp}.pdf"
                    
                    st.success("✅ PDF Generated!")
                    st.download_button(
                        label="💾 Download PDF",
                        data=pdf_content,
                        file_name=filename,
                        mime="application/pdf",
                        use_container_width=True,
                        key="pdf_download_btn"
                    )
                else:
                    st.error("❌ Failed to generate PDF")
                    
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")
                logger.error(f"PDF generation failed: {e}", exc_info=True)
    
    with col2:
        if st.button("❌ Cancel", use_container_width=True, key="pdf_cancel_btn"):
            st.rerun()


# ==================== Check for pending dialog ====================

def check_pending_dialogs():
    """
    Check if there's a pending dialog to open.
    Call this at the start of the page render.
    """
    if st.session_state.get('open_issue_pdf_dialog'):
        issue_id = st.session_state.pop('issue_pdf_id', None)
        issue_no = st.session_state.pop('issue_pdf_no', '')
        st.session_state.pop('open_issue_pdf_dialog', None)
        if issue_id:
            show_pdf_dialog(issue_id, issue_no)


# ==================== Quick Action Functions ====================

def handle_row_action(action: str, issue_id: int, issue_no: str):
    """
    Handle row action button clicks
    
    Args:
        action: Action type (view, pdf)
        issue_id: Issue ID
        issue_no: Issue number
    """
    if action == 'view':
        show_detail_dialog(issue_id)
    elif action == 'pdf':
        show_pdf_dialog(issue_id, issue_no)