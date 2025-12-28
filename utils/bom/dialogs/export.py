# utils/bom/dialogs/export.py
"""
BOM Export Dialog - Export to PDF or Excel
Supports exporting single BOM with materials and alternatives

VERSION 2.2 - Updated Product Display
- User can select which internal company to display on exported documents
- Company logo and name will be shown on PDF header
- Company info added to Excel metadata
- Updated product display to unified format with legacy_code
"""

import logging
from datetime import datetime
from io import BytesIO
from typing import Dict, Any, Optional
import pandas as pd

import streamlit as st

from utils.bom.manager import BOMManager, BOMException
from utils.bom.state import StateManager
from utils.bom.common import (
    create_status_indicator,
    format_number,
    format_product_display,
    get_internal_companies_cached,
    format_company_display
)
from utils.bom.pdf_generator import generate_bom_pdf
from utils.bom.excel_generator import generate_bom_excel

logger = logging.getLogger(__name__)


@st.dialog("📥 Export BOM", width="large")
def show_export_dialog(bom_id: int):
    """Export BOM dialog - Choose company, format (PDF/Excel), and options"""
    state = StateManager()
    manager = BOMManager()
    
    try:
        # Load BOM data
        bom_info = manager.get_bom_info(bom_id)
        bom_details = manager.get_bom_details(bom_id)
        
        if not bom_info:
            st.error("❌ BOM not found")
            if st.button("Close", key="export_notfound_close"):
                state.close_dialog()
                st.rerun()
            return
        
        # Header
        st.markdown(f"### 📋 {bom_info['bom_code']} - {bom_info['bom_name']}")
        st.markdown(f"**Status:** {create_status_indicator(bom_info['status'])} | **Materials:** {len(bom_details)}")
        
        st.markdown("---")
        
        # ==================== Company Selection ====================
        st.markdown("### 🏢 Select Company")
        st.caption("Choose the internal company to display on the exported document")
        
        # Load internal companies
        internal_companies = get_internal_companies_cached()
        
        if internal_companies.empty:
            st.warning("⚠️ No internal companies found. Using default company info.")
            selected_company_id = None
            selected_company_info = None
        else:
            # Build company options
            company_options = {}
            for _, row in internal_companies.iterrows():
                display_text = format_company_display(
                    english_name=row['english_name'],
                    local_name=row.get('local_name'),
                    company_code=row.get('company_code')
                )
                company_options[display_text] = {
                    'id': row['id'],
                    'english_name': row['english_name'],
                    'local_name': row.get('local_name'),
                    'address': row.get('address'),
                    'registration_code': row.get('registration_code'),
                    'logo_path': row.get('logo_path')
                }
            
            # Default selection - try to get from session state or first company
            default_company_display = list(company_options.keys())[0]
            
            # Check if user has a preferred company from session
            session_company_id = st.session_state.get('company_id')
            if session_company_id:
                for display, info in company_options.items():
                    if info['id'] == session_company_id:
                        default_company_display = display
                        break
            
            selected_company = st.selectbox(
                "Company / Công ty",
                options=list(company_options.keys()),
                index=list(company_options.keys()).index(default_company_display),
                key="export_company_select"
            )
            
            selected_company_info = company_options.get(selected_company)
            selected_company_id = selected_company_info['id'] if selected_company_info else None
            
            # Show selected company preview
            if selected_company_info:
                with st.expander("👁️ Company Preview", expanded=False):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.write(f"**English Name:** {selected_company_info['english_name']}")
                        st.write(f"**Local Name:** {selected_company_info.get('local_name') or 'N/A'}")
                        st.write(f"**MST:** {selected_company_info.get('registration_code') or 'N/A'}")
                    with col2:
                        st.write(f"**Address:** {selected_company_info.get('address') or 'N/A'}")
                        has_logo = "✅ Yes" if selected_company_info.get('logo_path') else "❌ No"
                        st.write(f"**Has Logo:** {has_logo}")
        
        st.markdown("---")
        
        # ==================== Export Options ====================
        st.markdown("### ⚙️ Export Options")
        
        col1, col2 = st.columns(2)
        
        with col1:
            language = st.selectbox(
                "Language / Ngôn ngữ",
                options=['vi', 'en'],
                format_func=lambda x: '🇻🇳 Tiếng Việt' if x == 'vi' else '🇬🇧 English',
                key="export_language"
            )
        
        with col2:
            layout = st.selectbox(
                "Layout / Bố cục",
                options=['landscape', 'portrait'],
                format_func=lambda x: '📄 Landscape (Ngang)' if x == 'landscape' else '📄 Portrait (Dọc)',
                key="export_layout"
            )
        
        st.markdown("---")
        
        # ==================== Export Format Selection ====================
        st.markdown("### 📤 Select Export Format")
        
        col1, col2 = st.columns(2)
        
        with col1:
            pdf_selected = st.button(
                "📄 Export as PDF",
                use_container_width=True,
                type="primary",
                key="export_pdf_btn"
            )
            st.caption("Professional document format with company header, materials and alternatives")
        
        with col2:
            excel_selected = st.button(
                "📊 Export as Excel",
                use_container_width=True,
                type="secondary",
                key="export_excel_btn"
            )
            st.caption("Spreadsheet format with company info for data analysis")
        
        st.markdown("---")
        
        # Handle export actions
        if pdf_selected:
            _export_as_pdf(bom_id, bom_info, bom_details, manager, 
                          selected_company_id, selected_company_info,
                          language, layout)
        
        if excel_selected:
            _export_as_excel(bom_info, bom_details, manager, 
                           selected_company_id, selected_company_info,
                           language)
        
        # ==================== Preview Section ====================
        st.markdown("### 👁️ BOM Preview")
        
        with st.expander("📋 BOM Information", expanded=True):
            col1, col2 = st.columns(2)
            
            with col1:
                st.write(f"**Code:** {bom_info['bom_code']}")
                st.write(f"**Name:** {bom_info['bom_name']}")
                st.write(f"**Type:** {bom_info['bom_type']}")
                st.write(f"**Status:** {bom_info['status']}")
            
            with col2:
                product_display = format_product_display(
                    code=bom_info.get('product_code', ''),
                    name=bom_info.get('product_name', ''),
                    package_size=bom_info.get('package_size'),
                    brand=bom_info.get('brand'),
                    legacy_code=bom_info.get('legacy_code')
                )
                st.write(f"**Product:** {product_display}")
                st.write(f"**Output:** {format_number(bom_info['output_qty'], 2)} {bom_info['uom']}")
                st.write(f"**Effective:** {bom_info.get('effective_date', 'N/A')}")
                st.write(f"**Version:** {bom_info.get('version', 1)}")
        
        with st.expander(f"🧱 Materials ({len(bom_details)} items)", expanded=False):
            if not bom_details.empty:
                display_df = bom_details[['material_code', 'material_name', 'material_type', 
                                          'quantity', 'uom', 'scrap_rate', 'alternatives_count']].copy()
                display_df.columns = ['Code', 'Name', 'Type', 'Qty', 'UOM', 'Scrap %', 'Alternatives']
                st.dataframe(display_df, use_container_width=True, hide_index=True)
            else:
                st.info("No materials in this BOM")
        
        st.markdown("---")
        
        # Close button
        if st.button("✔ Close", use_container_width=True, key="export_close"):
            state.close_dialog()
            st.rerun()
    
    except Exception as e:
        logger.error(f"Error in export dialog: {e}")
        st.error(f"❌ Error: {str(e)}")
        
        if st.button("Close", key="export_error_close"):
            state.close_dialog()
            st.rerun()


def _export_as_pdf(bom_id: int, bom_info: Dict, bom_details: pd.DataFrame, 
                   manager: BOMManager, 
                   company_id: Optional[int], company_info: Optional[Dict],
                   language: str = 'vi', layout: str = 'portrait'):
    """Generate and provide PDF download with selected company"""
    try:
        with st.spinner("Generating PDF..."):
            # Load alternatives for each material
            alternatives_data = {}
            for _, mat in bom_details.iterrows():
                detail_id = int(mat['id'])
                alternatives = manager.get_material_alternatives(detail_id)
                alternatives_data[detail_id] = alternatives
            
            # Get current user name for exported_by
            exported_by = st.session_state.get('user_name') or st.session_state.get('username') or 'Unknown'
            
            # Generate PDF with company_id and other options
            pdf_bytes = generate_bom_pdf(
                bom_info=bom_info,
                materials=bom_details,
                alternatives_data=alternatives_data,
                company_id=company_id,
                company_info=company_info,
                language=language,
                layout=layout,
                exported_by=exported_by
            )
            
            if pdf_bytes is None:
                st.error("❌ Failed to generate PDF. Check logs for details.")
                return
            
            # Create filename with company code and language suffix
            company_suffix = ""
            if company_info and company_info.get('english_name'):
                # Use first word or abbreviation
                company_suffix = f"_{company_info['english_name'].split()[0]}"
            
            # Language suffix
            lang_suffix = "_VN" if language == 'vi' else "_EN"
            
            filename = f"BOM_{bom_info['bom_code']}{company_suffix}{lang_suffix}_{datetime.now().strftime('%Y%m%d')}.pdf"
            
            # Download button
            st.success("✅ PDF generated successfully!")
            
            st.download_button(
                label="📥 Download PDF",
                data=pdf_bytes,
                file_name=filename,
                mime="application/pdf",
                use_container_width=True,
                key="download_pdf_btn"
            )
    
    except Exception as e:
        logger.error(f"Error generating PDF: {e}")
        st.error(f"❌ Error generating PDF: {str(e)}")


def _export_as_excel(bom_info: Dict, bom_details: pd.DataFrame, manager: BOMManager,
                     company_id: Optional[int], company_info: Optional[Dict],
                     language: str = 'vi'):
    """Generate and provide Excel download with company info"""
    try:
        with st.spinner("Generating Excel..."):
            # Load alternatives for each material
            alternatives_data = {}
            for _, mat in bom_details.iterrows():
                detail_id = int(mat['id'])
                alternatives = manager.get_material_alternatives(detail_id)
                alternatives_data[detail_id] = alternatives
            
            # Get current user name for exported_by
            exported_by = st.session_state.get('user_name') or st.session_state.get('username') or 'Unknown'
            
            # Generate professional Excel with company info
            excel_bytes = generate_bom_excel(
                bom_info=bom_info,
                materials=bom_details,
                alternatives_data=alternatives_data,
                company_id=company_id,
                company_info=company_info,
                language=language,
                exported_by=exported_by
            )
            
            # Create filename with company code and language suffix
            company_suffix = ""
            if company_info and company_info.get('english_name'):
                company_suffix = f"_{company_info['english_name'].split()[0]}"
            
            # Language suffix
            lang_suffix = "_VN" if language == 'vi' else "_EN"
            
            filename = f"BOM_{bom_info['bom_code']}{company_suffix}{lang_suffix}_{datetime.now().strftime('%Y%m%d')}.xlsx"
            
            # Download button
            st.success("✅ Excel generated successfully!")
            
            st.download_button(
                label="📥 Download Excel",
                data=excel_bytes,
                file_name=filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key="download_excel_btn"
            )
    
    except Exception as e:
        logger.error(f"Error generating Excel: {e}")
        st.error(f"❌ Error generating Excel: {str(e)}")


# ==================== Quick Export Functions ====================

def quick_export_pdf(bom_id: int, manager: BOMManager, 
                     company_id: Optional[int] = None,
                     language: str = 'vi', layout: str = 'landscape',
                     exported_by: Optional[str] = None) -> Optional[bytes]:
    """
    Quick export BOM to PDF without dialog
    Returns PDF bytes or None on error
    """
    try:
        bom_info = manager.get_bom_info(bom_id)
        bom_details = manager.get_bom_details(bom_id)
        
        if not bom_info:
            return None
        
        # Load alternatives
        alternatives_data = {}
        for _, mat in bom_details.iterrows():
            detail_id = int(mat['id'])
            alternatives = manager.get_material_alternatives(detail_id)
            alternatives_data[detail_id] = alternatives
        
        # Get exported_by from session if not provided
        if not exported_by:
            exported_by = st.session_state.get('user_name') or st.session_state.get('username')
        
        return generate_bom_pdf(
            bom_info=bom_info,
            materials=bom_details,
            alternatives_data=alternatives_data,
            company_id=company_id,
            language=language,
            layout=layout,
            exported_by=exported_by
        )
    
    except Exception as e:
        logger.error(f"Error in quick PDF export: {e}")
        return None


def quick_export_excel(bom_id: int, manager: BOMManager,
                       company_id: Optional[int] = None,
                       language: str = 'vi',
                       exported_by: Optional[str] = None) -> Optional[bytes]:
    """
    Quick export BOM to Excel without dialog
    Returns Excel bytes or None on error
    """
    try:
        bom_info = manager.get_bom_info(bom_id)
        bom_details = manager.get_bom_details(bom_id)
        
        if not bom_info:
            return None
        
        # Load alternatives
        alternatives_data = {}
        for _, mat in bom_details.iterrows():
            detail_id = int(mat['id'])
            alternatives = manager.get_material_alternatives(detail_id)
            alternatives_data[detail_id] = alternatives
        
        # Get exported_by from session if not provided
        if not exported_by:
            exported_by = st.session_state.get('user_name') or st.session_state.get('username')
        
        return generate_bom_excel(
            bom_info=bom_info,
            materials=bom_details,
            alternatives_data=alternatives_data,
            company_id=company_id,
            language=language,
            exported_by=exported_by
        )
    
    except Exception as e:
        logger.error(f"Error in quick Excel export: {e}")
        return None