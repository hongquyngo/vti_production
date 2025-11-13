# utils/production/pdf_ui.py
"""
PDF Export UI Components for Production Module
Handles user interface for PDF generation after material issue
"""

import streamlit as st
from datetime import datetime
from typing import Dict, Any, Optional
import logging

from .pdf_generator import pdf_generator
from ..production.common import UIHelpers

logger = logging.getLogger(__name__)


class PDFExportDialog:
    """Handle PDF export dialog after material issue"""
    
    @staticmethod
    def show_pdf_export_dialog(issue_result: Dict[str, Any]):
        """
        Show PDF export dialog after successful material issue
        
        Args:
            issue_result: Result from issue_materials function containing:
                - issue_no: Issue number
                - issue_id: Issue ID
                - details: Issue details
                - substitutions: Any substitutions made
        """
        # Store issue info in session state
        st.session_state['last_issue_result'] = issue_result
        st.session_state['show_pdf_options'] = False
        
        # Success message with issue details
        st.success(f"""
        ✅ **Materials Issued Successfully!**
        
        - Issue No: **{issue_result['issue_no']}**
        - Total Items: **{len(issue_result['details'])}**
        """)
        
        # Show substitutions if any
        if issue_result.get('substitutions'):
            st.warning(f"⚠️ **Note:** {len(issue_result['substitutions'])} material substitutions were made")
        
        # PDF Export section
        st.markdown("---")
        st.markdown("### 📄 Generate Document")
        
        col1, col2, col3 = st.columns([2, 2, 1])
        
        with col1:
            if st.button("📥 Generate PDF Issue Slip", type="primary", use_container_width=True):
                st.session_state['show_pdf_options'] = True
                st.rerun()
        
        with col2:
            if st.button("⏭️ Skip", use_container_width=True):
                st.info("You can generate the PDF later from the Issue History")
                st.session_state['show_pdf_dialog'] = False
                st.session_state['last_issue_result'] = None
                return
        
        # Show PDF options if requested
        if st.session_state.get('show_pdf_options'):
            PDFExportDialog.show_pdf_options()
    
    @staticmethod
    def show_pdf_options():
        """Show PDF generation options"""
        st.markdown("### 📋 PDF Options")
        
        with st.form("pdf_options_form"):
            col1, col2 = st.columns(2)
            
            with col1:
                language = st.selectbox(
                    "Language / Ngôn ngữ",
                    options=['vi', 'en'],
                    format_func=lambda x: "Tiếng Việt" if x == 'vi' else "English",
                    index=0
                )
                
                include_signatures = st.checkbox(
                    "Include signature section",
                    value=True
                )
            
            with col2:
                doc_type = st.selectbox(
                    "Document Type",
                    options=['issue_slip', 'detailed_report'],
                    format_func=lambda x: "Phiếu xuất kho" if x == 'issue_slip' else "Báo cáo chi tiết",
                    index=0
                )
                
                add_notes = st.checkbox(
                    "Add custom notes",
                    value=False
                )
            
            if add_notes:
                custom_notes = st.text_area(
                    "Notes / Ghi chú",
                    placeholder="Enter any additional notes for the document..."
                )
            else:
                custom_notes = ""
            
            st.markdown("---")
            
            col1, col2 = st.columns(2)
            
            with col1:
                generate = st.form_submit_button(
                    "🖨️ Generate PDF",
                    type="primary",
                    use_container_width=True
                )
            
            with col2:
                cancel = st.form_submit_button(
                    "❌ Cancel",
                    use_container_width=True
                )
            
            if generate:
                PDFExportDialog.generate_pdf(
                    language=language,
                    doc_type=doc_type,
                    include_signatures=include_signatures,
                    notes=custom_notes
                )
            
            if cancel:
                st.session_state['show_pdf_options'] = False
                st.session_state['show_pdf_dialog'] = False
                st.rerun()
    
    @staticmethod
    def generate_pdf(language: str = 'vi', doc_type: str = 'issue_slip', 
                    include_signatures: bool = True, notes: str = ""):
        """Generate and download PDF"""
        
        issue_result = st.session_state.get('last_issue_result')
        if not issue_result:
            st.error("No issue data available")
            return
        
        try:
            with st.spinner("Generating PDF..."):
                # Generate PDF
                pdf_options = {
                    'language': language,
                    'doc_type': doc_type,
                    'include_signatures': include_signatures,
                    'notes': notes
                }
                
                pdf_content = pdf_generator.generate_pdf_with_options(
                    issue_result['issue_id'],
                    pdf_options
                )
                
                # Generate filename
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f"MaterialIssue_{issue_result['issue_no']}_{timestamp}.pdf"
                
                # Show success and download button
                st.success("✅ PDF Generated Successfully!")
                
                col1, col2, col3 = st.columns([2, 2, 1])
                
                with col1:
                    st.download_button(
                        label="💾 Download PDF",
                        data=pdf_content,
                        file_name=filename,
                        mime="application/pdf",
                        use_container_width=True,
                        type="primary"
                    )
                
                with col2:
                    if st.button("✅ Done", use_container_width=True):
                        # Clear session state
                        st.session_state['show_pdf_dialog'] = False
                        st.session_state['show_pdf_options'] = False
                        st.session_state['last_issue_result'] = None
                        st.rerun()
                
                # Log the generation
                logger.info(f"PDF generated for issue {issue_result['issue_no']} by user {st.session_state.get('username')}")
                
        except Exception as e:
            st.error(f"❌ Error generating PDF: {str(e)}")
            logger.error(f"PDF generation error: {e}", exc_info=True)


def render_material_issue_with_pdf():
    """
    Enhanced material issue function with PDF export
    This wraps the existing material issue process
    """
    import streamlit as st
    from ..production.materials import issue_materials
    
    # Get the selected order
    order_id = st.session_state.get('selected_order')
    if not order_id:
        st.warning("Please select a production order first")
        return
    
    # Material issue button
    if st.button("📤 Issue Materials", type="primary", use_container_width=True):
        try:
            # Issue materials
            with st.spinner("Issuing materials..."):
                result = issue_materials(
                    order_id=order_id,
                    user_id=st.session_state.get('user_id', 1)
                )
            
            # Show PDF dialog
            if result and result.get('issue_id'):
                PDFExportDialog.show_pdf_export_dialog(result)
            else:
                st.error("Material issue failed")
                
        except ValueError as e:
            st.error(f"❌ {str(e)}")
            logger.error(f"Material issue error: {e}")
        except Exception as e:
            st.error(f"❌ An error occurred: {str(e)}")
            logger.error(f"Unexpected error: {e}", exc_info=True)


class QuickPDFButton:
    """Quick PDF generation button for existing issues"""
    
    @staticmethod
    def render(issue_id: int, issue_no: str):
        """
        Render a quick PDF download button for an existing issue
        
        Args:
            issue_id: Material issue ID
            issue_no: Material issue number
        """
        if st.button(f"📄 PDF", key=f"pdf_{issue_id}", help=f"Generate PDF for {issue_no}"):
            try:
                with st.spinner("Generating PDF..."):
                    pdf_content = pdf_generator.generate_pdf(issue_id)
                    
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    filename = f"MaterialIssue_{issue_no}_{timestamp}.pdf"
                    
                    st.download_button(
                        label="💾 Download",
                        data=pdf_content,
                        file_name=filename,
                        mime="application/pdf",
                        key=f"download_{issue_id}"
                    )
            except Exception as e:
                st.error(f"Error: {str(e)}")
                logger.error(f"Quick PDF generation error: {e}")