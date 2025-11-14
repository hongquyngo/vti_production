# utils/production/pdf_ui.py
"""
PDF Export UI Components for Production Module - REFACTORED
Fixed: Error handling, validation, user feedback
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
            with st.warning(""):
                st.write(f"⚠️ **Note:** {len(issue_result['substitutions'])} material substitutions were made:")
                for sub in issue_result['substitutions']:
                    st.write(f"• {sub['original_material']} → **{sub['substitute_material']}** ({sub['quantity']} {sub['uom']})")
        
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
        """Show PDF generation options with better error handling"""
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
                    placeholder="Enter any additional notes for the document...",
                    max_chars=500
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
        """Generate and download PDF with enhanced error handling"""
        
        issue_result = st.session_state.get('last_issue_result')
        if not issue_result:
            st.error("❌ No issue data available. Please refresh and try again.")
            logger.error("Attempted to generate PDF without issue data")
            return
        
        issue_id = issue_result.get('issue_id')
        if not issue_id:
            st.error("❌ Invalid issue data. Missing issue ID.")
            logger.error(f"Issue result missing issue_id: {issue_result}")
            return
        
        try:
            # Validate issue data exists in database
            if not pdf_generator.validate_issue_data(issue_id):
                st.error("❌ Issue data not found in database. Please contact IT support.")
                logger.error(f"Issue {issue_id} validation failed")
                return
            
            with st.spinner("Generating PDF... Please wait..."):
                # Generate PDF
                pdf_options = {
                    'language': language,
                    'doc_type': doc_type,
                    'include_signatures': include_signatures,
                    'notes': notes
                }
                
                pdf_content = pdf_generator.generate_pdf_with_options(
                    issue_id,
                    pdf_options
                )
                
                if not pdf_content:
                    st.error("❌ PDF generation failed - empty content returned")
                    st.info("💡 Please try again or contact IT support if the problem persists")
                    logger.error(f"Empty PDF content for issue {issue_id}")
                    return
                
                # Generate filename
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                issue_no = issue_result.get('issue_no', f'ISSUE_{issue_id}')
                filename = f"MaterialIssue_{issue_no}_{timestamp}.pdf"
                
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
                logger.info(f"PDF generated successfully for issue {issue_no} (ID: {issue_id})")
                
        except ValueError as ve:
            st.error(f"❌ Data Error: {str(ve)}")
            st.info("Please ensure all required fields are filled in the database")
            logger.error(f"ValueError in PDF generation for issue {issue_id}: {ve}")
            
        except ConnectionError as ce:
            st.error("❌ Database connection error")
            st.info("Please check your network connection and try again")
            logger.error(f"Connection error for issue {issue_id}: {ce}")
            
        except Exception as e:
            st.error("❌ Unexpected error occurred while generating PDF")
            
            # Show user-friendly error message
            error_messages = {
                "font": "Font rendering issue - Vietnamese text may not display correctly",
                "logo": "Company logo could not be loaded",
                "memory": "Out of memory - try generating a smaller document",
                "timeout": "Operation timed out - please try again"
            }
            
            error_str = str(e).lower()
            for key, message in error_messages.items():
                if key in error_str:
                    st.warning(f"⚠️ {message}")
                    break
            else:
                st.info("Please try again or contact IT support if the problem persists")
            
            # Show debug info if in dev mode
            if st.session_state.get('debug_mode', False):
                with st.expander("🔍 Debug Information"):
                    st.code(f"Error Type: {type(e).__name__}")
                    st.code(f"Error Message: {str(e)}")
                    st.code(f"Issue ID: {issue_id}")
                    st.code(f"Options: {pdf_options if 'pdf_options' in locals() else 'N/A'}")
            
            logger.error(f"PDF generation error for issue {issue_id}: {e}", exc_info=True)


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
        st.warning("⚠️ Please select a production order first")
        return
    
    # Material issue button
    if st.button("📤 Issue Materials", type="primary", use_container_width=True):
        try:
            # Validate order status first
            from ..db import get_db_engine
            import pandas as pd
            
            engine = get_db_engine()
            order_check = pd.read_sql(
                "SELECT status FROM manufacturing_orders WHERE id = %s",
                engine, params=(order_id,)
            )
            
            if order_check.empty:
                st.error("❌ Order not found")
                return
            
            if order_check.iloc[0]['status'] not in ['DRAFT', 'CONFIRMED']:
                st.error(f"❌ Cannot issue materials for {order_check.iloc[0]['status']} order")
                return
            
            # Issue materials
            with st.spinner("Issuing materials... Please wait..."):
                result = issue_materials(
                    order_id=order_id,
                    user_id=st.session_state.get('user_id', 1)
                )
            
            # Show PDF dialog
            if result and result.get('issue_id'):
                PDFExportDialog.show_pdf_export_dialog(result)
            else:
                st.error("❌ Material issue failed - no result returned")
                
        except ValueError as e:
            st.error(f"❌ {str(e)}")
            logger.error(f"Material issue error: {e}")
            
        except ConnectionError:
            st.error("❌ Database connection lost. Please check your network.")
            
        except Exception as e:
            st.error(f"❌ An unexpected error occurred")
            if st.session_state.get('debug_mode'):
                st.code(str(e))
            logger.error(f"Unexpected error: {e}", exc_info=True)


class QuickPDFButton:
    """Quick PDF generation button for existing issues"""
    
    @staticmethod
    def validate_issue_data(issue_id: int) -> bool:
        """Validate that issue has required data before attempting PDF generation"""
        try:
            return pdf_generator.validate_issue_data(issue_id)
        except Exception as e:
            logger.error(f"Failed to validate issue {issue_id}: {e}")
            return False
    
    @staticmethod
    def render(issue_id: int, issue_no: str):
        """
        Render a quick PDF download button for an existing issue with enhanced error handling
        
        Args:
            issue_id: Material issue ID
            issue_no: Material issue number
        """
        if st.button(f"📄 PDF", key=f"pdf_{issue_id}", help=f"Generate PDF for {issue_no}"):
            try:
                # Validate first
                if not QuickPDFButton.validate_issue_data(issue_id):
                    st.error("⚠️ Issue data incomplete or missing")
                    st.info("Please verify all material details are present")
                    return
                
                with st.spinner("Generating PDF..."):
                    pdf_content = pdf_generator.generate_pdf(issue_id)
                    
                    if not pdf_content:
                        st.error("❌ PDF generation failed - empty content")
                        st.info("💡 Please check if all required data is available:")
                        st.info("• Issue has material details")
                        st.info("• Production order is linked")
                        st.info("• Warehouse information is complete")
                        return
                    
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    filename = f"MaterialIssue_{issue_no}_{timestamp}.pdf"
                    
                    # Success feedback
                    col1, col2 = st.columns([3, 1])
                    
                    with col1:
                        st.download_button(
                            label="💾 Download PDF",
                            data=pdf_content,
                            file_name=filename,
                            mime="application/pdf",
                            key=f"download_{issue_id}",
                            use_container_width=True
                        )
                    
                    with col2:
                        st.success("✅ Ready")
                    
                    logger.info(f"Quick PDF generated for issue {issue_no}")
                    
            except ValueError as ve:
                st.error(f"❌ Data Error: {str(ve)}")
                st.info("Please ensure all required fields are filled")
                logger.error(f"Quick PDF value error for issue {issue_id}: {ve}")
                
            except ConnectionError:
                st.error("❌ Database connection error")
                st.info("Please check your network and try again")
                
            except Exception as e:
                st.error("❌ Unable to generate PDF")
                
                # Provide helpful error messages
                if "NoneType" in str(e):
                    st.info("Some required data is missing. Please check the issue details.")
                elif "permission" in str(e).lower():
                    st.info("Permission denied. Please contact IT support.")
                else:
                    st.info("Please try again or contact IT support")
                
                if st.session_state.get('debug_mode'):
                    with st.expander("Debug Info"):
                        st.code(f"Error: {str(e)}")
                        st.code(f"Issue ID: {issue_id}")
                
                logger.error(f"Quick PDF generation error for issue {issue_id}: {e}", exc_info=True)


class PDFBulkExport:
    """Handle bulk PDF export for multiple issues"""
    
    @staticmethod
    def render_bulk_export(issue_ids: list):
        """
        Render bulk export controls for multiple issues
        
        Args:
            issue_ids: List of issue IDs to export
        """
        if not issue_ids:
            st.warning("No issues selected for export")
            return
        
        st.markdown(f"### 📦 Bulk PDF Export ({len(issue_ids)} issues)")
        
        col1, col2, col3 = st.columns([2, 2, 1])
        
        with col1:
            language = st.selectbox(
                "Language for all PDFs",
                options=['vi', 'en'],
                format_func=lambda x: "Tiếng Việt" if x == 'vi' else "English",
                key="bulk_language"
            )
        
        with col2:
            if st.button("🚀 Generate All PDFs", type="primary", key="bulk_generate"):
                PDFBulkExport.process_bulk_export(issue_ids, language)
        
        with col3:
            if st.button("❌ Cancel", key="bulk_cancel"):
                st.session_state['show_bulk_export'] = False
                st.rerun()
    
    @staticmethod
    def process_bulk_export(issue_ids: list, language: str):
        """Process bulk PDF generation with progress tracking"""
        progress_bar = st.progress(0)
        status_text = st.empty()
        success_count = 0
        failed_ids = []
        
        for idx, issue_id in enumerate(issue_ids):
            progress = (idx + 1) / len(issue_ids)
            progress_bar.progress(progress)
            status_text.text(f"Processing {idx + 1} of {len(issue_ids)}...")
            
            try:
                pdf_content = pdf_generator.generate_pdf(issue_id, language)
                if pdf_content:
                    success_count += 1
                else:
                    failed_ids.append(issue_id)
            except Exception as e:
                logger.error(f"Bulk export failed for issue {issue_id}: {e}")
                failed_ids.append(issue_id)
        
        progress_bar.empty()
        status_text.empty()
        
        # Show results
        if success_count == len(issue_ids):
            st.success(f"✅ Successfully generated {success_count} PDFs")
        else:
            st.warning(f"⚠️ Generated {success_count} of {len(issue_ids)} PDFs")
            if failed_ids:
                st.error(f"Failed IDs: {', '.join(map(str, failed_ids))}")