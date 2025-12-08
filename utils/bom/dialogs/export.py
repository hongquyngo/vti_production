# utils/bom/dialogs/export.py
"""
BOM Export Dialog - Export to PDF or Excel
Supports exporting single BOM with materials and alternatives
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
    export_to_excel
)
from utils.bom.pdf_generator import generate_bom_pdf

logger = logging.getLogger(__name__)


@st.dialog("📥 Export BOM", width="large")
def show_export_dialog(bom_id: int):
    """Export BOM dialog - Choose PDF or Excel format"""
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
        
        # Export format selection
        st.markdown("### 📤 Select Export Format")
        
        col1, col2 = st.columns(2)
        
        with col1:
            pdf_selected = st.button(
                "📄 Export as PDF",
                use_container_width=True,
                type="primary",
                key="export_pdf_btn"
            )
            st.caption("Professional document format with materials and alternatives")
        
        with col2:
            excel_selected = st.button(
                "📊 Export as Excel",
                use_container_width=True,
                type="secondary",
                key="export_excel_btn"
            )
            st.caption("Spreadsheet format for data analysis")
        
        st.markdown("---")
        
        # Handle export actions
        if pdf_selected:
            _export_as_pdf(bom_id, bom_info, bom_details, manager)
        
        if excel_selected:
            _export_as_excel(bom_info, bom_details, manager)
        
        # Preview section
        st.markdown("### 👁️ BOM Preview")
        
        with st.expander("📋 BOM Information", expanded=True):
            col1, col2 = st.columns(2)
            
            with col1:
                st.write(f"**Code:** {bom_info['bom_code']}")
                st.write(f"**Name:** {bom_info['bom_name']}")
                st.write(f"**Type:** {bom_info['bom_type']}")
                st.write(f"**Status:** {bom_info['status']}")
            
            with col2:
                st.write(f"**Product:** {bom_info['product_code']} - {bom_info['product_name']}")
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


def _export_as_pdf(bom_id: int, bom_info: Dict, bom_details: pd.DataFrame, manager: BOMManager):
    """Generate and provide PDF download"""
    try:
        with st.spinner("Generating PDF..."):
            # Load alternatives for each material
            alternatives_data = {}
            for _, mat in bom_details.iterrows():
                detail_id = int(mat['id'])
                alternatives = manager.get_material_alternatives(detail_id)
                alternatives_data[detail_id] = alternatives
            
            # Get company name from session or use default
            company_name = st.session_state.get('company_name', 'Prostech Asia')
            
            # Generate PDF
            pdf_bytes = generate_bom_pdf(
                bom_info=bom_info,
                materials=bom_details,
                alternatives_data=alternatives_data,
                company_name=company_name
            )
            
            # Create filename
            filename = f"BOM_{bom_info['bom_code']}_{datetime.now().strftime('%Y%m%d')}.pdf"
            
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


def _export_as_excel(bom_info: Dict, bom_details: pd.DataFrame, manager: BOMManager):
    """Generate and provide Excel download"""
    try:
        with st.spinner("Generating Excel..."):
            # Prepare BOM info sheet
            info_data = {
                'Field': ['BOM Code', 'BOM Name', 'BOM Type', 'Status', 
                          'Product Code', 'Product Name', 'Output Qty', 'UOM',
                          'Effective Date', 'Version', 'Notes'],
                'Value': [
                    bom_info.get('bom_code', ''),
                    bom_info.get('bom_name', ''),
                    bom_info.get('bom_type', ''),
                    bom_info.get('status', ''),
                    bom_info.get('product_code', ''),
                    bom_info.get('product_name', ''),
                    bom_info.get('output_qty', 0),
                    bom_info.get('uom', ''),
                    str(bom_info.get('effective_date', '')),
                    bom_info.get('version', 1),
                    bom_info.get('notes', '')
                ]
            }
            info_df = pd.DataFrame(info_data)
            
            # Prepare materials sheet
            if not bom_details.empty:
                materials_df = bom_details[[
                    'material_code', 'material_name', 'material_type',
                    'quantity', 'uom', 'scrap_rate', 'current_stock', 'alternatives_count'
                ]].copy()
                materials_df.columns = [
                    'Material Code', 'Material Name', 'Type',
                    'Quantity', 'UOM', 'Scrap %', 'Current Stock', 'Alternatives'
                ]
            else:
                materials_df = pd.DataFrame(columns=[
                    'Material Code', 'Material Name', 'Type',
                    'Quantity', 'UOM', 'Scrap %', 'Current Stock', 'Alternatives'
                ])
            
            # Prepare alternatives sheet
            all_alternatives = []
            for _, mat in bom_details.iterrows():
                detail_id = int(mat['id'])
                alternatives = manager.get_material_alternatives(detail_id)
                
                if not alternatives.empty:
                    for _, alt in alternatives.iterrows():
                        all_alternatives.append({
                            'Primary Material': mat['material_code'],
                            'Primary Name': mat['material_name'],
                            'Alt Priority': alt['priority'],
                            'Alt Material Code': alt['material_code'],
                            'Alt Material Name': alt['material_name'],
                            'Alt Quantity': alt['quantity'],
                            'Alt UOM': alt['uom'],
                            'Alt Scrap %': alt['scrap_rate'],
                            'Status': 'Active' if alt['is_active'] else 'Inactive',
                            'Notes': alt.get('notes', '')
                        })
            
            if all_alternatives:
                alternatives_df = pd.DataFrame(all_alternatives)
            else:
                alternatives_df = pd.DataFrame(columns=[
                    'Primary Material', 'Primary Name', 'Alt Priority',
                    'Alt Material Code', 'Alt Material Name', 'Alt Quantity',
                    'Alt UOM', 'Alt Scrap %', 'Status', 'Notes'
                ])
            
            # Create Excel with multiple sheets
            excel_bytes = export_to_excel({
                'BOM Info': info_df,
                'Materials': materials_df,
                'Alternatives': alternatives_df
            })
            
            # Create filename
            filename = f"BOM_{bom_info['bom_code']}_{datetime.now().strftime('%Y%m%d')}.xlsx"
            
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

def quick_export_pdf(bom_id: int, manager: BOMManager) -> Optional[bytes]:
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
        
        company_name = st.session_state.get('company_name', 'Prostech Asia')
        
        return generate_bom_pdf(
            bom_info=bom_info,
            materials=bom_details,
            alternatives_data=alternatives_data,
            company_name=company_name
        )
    
    except Exception as e:
        logger.error(f"Error in quick PDF export: {e}")
        return None


def quick_export_excel(bom_id: int, manager: BOMManager) -> Optional[bytes]:
    """
    Quick export BOM to Excel without dialog
    Returns Excel bytes or None on error
    """
    try:
        bom_info = manager.get_bom_info(bom_id)
        bom_details = manager.get_bom_details(bom_id)
        
        if not bom_info:
            return None
        
        # Similar logic to _export_as_excel but returns bytes
        info_data = {
            'Field': ['BOM Code', 'BOM Name', 'BOM Type', 'Status', 
                      'Product Code', 'Product Name', 'Output Qty', 'UOM',
                      'Effective Date', 'Version'],
            'Value': [
                bom_info.get('bom_code', ''),
                bom_info.get('bom_name', ''),
                bom_info.get('bom_type', ''),
                bom_info.get('status', ''),
                bom_info.get('product_code', ''),
                bom_info.get('product_name', ''),
                bom_info.get('output_qty', 0),
                bom_info.get('uom', ''),
                str(bom_info.get('effective_date', '')),
                bom_info.get('version', 1)
            ]
        }
        info_df = pd.DataFrame(info_data)
        
        if not bom_details.empty:
            materials_df = bom_details[[
                'material_code', 'material_name', 'material_type',
                'quantity', 'uom', 'scrap_rate', 'current_stock', 'alternatives_count'
            ]].copy()
            materials_df.columns = [
                'Material Code', 'Material Name', 'Type',
                'Quantity', 'UOM', 'Scrap %', 'Current Stock', 'Alternatives'
            ]
        else:
            materials_df = pd.DataFrame()
        
        return export_to_excel({
            'BOM Info': info_df,
            'Materials': materials_df
        })
    
    except Exception as e:
        logger.error(f"Error in quick Excel export: {e}")
        return None
