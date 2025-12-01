# utils/production/returns/dialogs.py
"""
Dialog components for Returns domain
Detail, PDF dialogs

Version: 1.0.0
"""

import logging
from typing import Dict, Any, Optional

import streamlit as st
import pandas as pd

from .queries import ReturnQueries
from .common import (
    format_number, create_status_indicator, create_reason_display,
    format_datetime, get_vietnam_now
)

logger = logging.getLogger(__name__)


# ==================== Return Detail Dialog ====================

@st.dialog("📋 Return Details", width="large")
def show_detail_dialog(return_id: int):
    """
    Show return details dialog
    
    Args:
        return_id: Return ID to display
    """
    queries = ReturnQueries()
    return_data = queries.get_return_details(return_id)
    
    if not return_data:
        st.error("❌ Return not found")
        return
    
    # Header
    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown(f"### ↩️ {return_data['return_no']}")
    with col2:
        st.markdown(f"**{create_status_indicator(return_data['status'])}**")
    
    st.markdown("---")
    
    # Return info
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**📅 Return Information**")
        st.write(f"• **Date:** {format_datetime(return_data['return_date'])}")
        st.write(f"• **Order:** {return_data['order_no']}")
        st.write(f"• **Product:** {return_data['product_name']}")
        st.write(f"• **Warehouse:** {return_data['warehouse_name']}")
        st.write(f"• **Reason:** {create_reason_display(return_data['reason'])}")
    
    with col2:
        st.markdown("**👤 Personnel**")
        st.write(f"• **Returned By:** {return_data['returned_by_name'] or 'N/A'}")
        st.write(f"• **Received By:** {return_data['received_by_name'] or 'N/A'}")
        st.write(f"• **Created By:** {return_data['created_by_name'] or 'N/A'}")
        if return_data.get('issue_no'):
            st.write(f"• **Original Issue:** {return_data['issue_no']}")
    
    # Materials
    st.markdown("---")
    st.markdown("### 📦 Returned Materials")
    
    materials = queries.get_return_materials(return_id)
    
    if not materials.empty:
        display_df = materials.copy()
        display_df['material_info'] = display_df.apply(
            lambda x: f"{x['material_name']}" + 
                     (f" (Alt: {x['original_material_name']})" if x.get('is_alternative') else ""),
            axis=1
        )
        display_df['qty'] = display_df['quantity'].apply(lambda x: format_number(x, 4))
        display_df['condition_display'] = display_df['condition'].apply(create_status_indicator)
        display_df['expiry'] = pd.to_datetime(display_df['expired_date']).dt.strftime('%d/%m/%Y')
        
        st.dataframe(
            display_df[['material_info', 'pt_code', 'batch_no', 'qty', 'uom', 'condition_display', 'expiry']].rename(columns={
                'material_info': 'Material',
                'pt_code': 'PT Code',
                'batch_no': 'Batch',
                'qty': 'Quantity',
                'uom': 'UOM',
                'condition_display': 'Condition',
                'expiry': 'Expiry'
            }),
            use_container_width=True,
            hide_index=True
        )
        
        # Summary
        total_qty = materials['quantity'].sum()
        good_qty = materials[materials['condition'] == 'GOOD']['quantity'].sum()
        damaged_qty = materials[materials['condition'] == 'DAMAGED']['quantity'].sum()
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Returned", format_number(total_qty, 4))
        with col2:
            st.metric("✅ Good", format_number(good_qty, 4))
        with col3:
            st.metric("⚠️ Damaged", format_number(damaged_qty, 4))
    else:
        st.info("No materials in this return")
    
    st.markdown("---")
    
    # Action buttons - Use session state to trigger PDF dialog after closing this one
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("📄 Export PDF", type="primary", use_container_width=True,
                    key="detail_pdf_btn"):
            # Set session state to open PDF dialog after rerun
            st.session_state['open_return_pdf_dialog'] = True
            st.session_state['return_pdf_id'] = return_id
            st.session_state['return_pdf_no'] = return_data['return_no']
            st.rerun()
    
    with col2:
        if st.button("✖️ Close", use_container_width=True, key="detail_close_btn"):
            st.rerun()


# ==================== PDF Export Dialog ====================

@st.dialog("📄 Export Return PDF", width="medium")
def show_pdf_dialog(return_id: int, return_no: str):
    """
    Show PDF export dialog
    
    Args:
        return_id: Return ID
        return_no: Return number for filename
    """
    st.markdown(f"### 📄 Export: {return_no}")
    
    col1, col2 = st.columns(2)
    
    with col1:
        language = st.selectbox(
            "Language",
            options=['vi', 'en'],
            format_func=lambda x: "🇻🇳 Tiếng Việt" if x == 'vi' else "🇬🇧 English",
            key="pdf_language"
        )
    
    with col2:
        layout = st.selectbox(
            "Layout",
            options=['landscape', 'portrait'],
            format_func=lambda x: "📐 Landscape" if x == 'landscape' else "📄 Portrait",
            key="pdf_layout"
        )
    
    st.markdown("---")
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("📄 Generate PDF", type="primary", use_container_width=True,
                    key="pdf_gen_btn"):
            try:
                from .pdf_generator import ReturnPDFGenerator
                
                with st.spinner("Generating PDF..."):
                    generator = ReturnPDFGenerator()
                    pdf_content = generator.generate_pdf(
                        return_id,
                        language=language,
                        layout=layout
                    )
                
                if pdf_content:
                    timestamp = get_vietnam_now().strftime('%Y%m%d_%H%M%S')
                    filename = f"Return_{return_no}_{timestamp}.pdf"
                    
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
    if st.session_state.get('open_return_pdf_dialog'):
        return_id = st.session_state.pop('return_pdf_id', None)
        return_no = st.session_state.pop('return_pdf_no', '')
        st.session_state.pop('open_return_pdf_dialog', None)
        if return_id:
            show_pdf_dialog(return_id, return_no)


# ==================== Quick Action Functions ====================

def handle_row_action(action: str, return_id: int, return_no: str):
    """
    Handle row action button clicks
    
    Args:
        action: Action type (view, pdf)
        return_id: Return ID
        return_no: Return number
    """
    if action == 'view':
        show_detail_dialog(return_id)
    elif action == 'pdf':
        show_pdf_dialog(return_id, return_no)
