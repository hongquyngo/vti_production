# utils/production/pdf_ui.py
"""
PDF Export UI Components for Production Module - REFACTORED v2.4
SIMPLIFIED: Removed Document Type option, streamlined UI

CHANGES v2.4:
- ✅ REMOVED: Document Type selector (không cần thiết)
- ✅ REMOVED: Add custom notes option (giữ giao diện đơn giản)
- ✅ SIMPLIFIED: Chỉ giữ Language và Include signatures
- ✅ Maintained all v2.3.1 fixes (dialog persistence, button behavior)
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
    @st.dialog("📄 Material Issue - PDF Export", width="large")
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
        # Success message with issue details
        st.success(f"""
        ✅ **Materials Issued Successfully!**
        
        - Issue No: **{issue_result['issue_no']}**
        - Total Items: **{len(issue_result['details'])}**
        """)
        
        # Show substitutions if any
        if issue_result.get('substitutions'):
            st.warning(f"⚠️ **Note:** {len(issue_result['substitutions'])} material substitutions were made:")
            for sub in issue_result['substitutions']:
                st.write(f"• {sub['original_material']} → **{sub['substitute_material']}** ({sub['quantity']} {sub['uom']})")
        
        st.markdown("---")
        
        # PDF Generation Section
        st.markdown("### 📄 Generate PDF Document")
        
        # Check if PDF already generated in this session
        pdf_key = f"pdf_generated_{issue_result['issue_id']}"
        
        if not st.session_state.get(pdf_key):
            # Show generation form
            PDFExportDialog._show_generation_form(issue_result, pdf_key)
        else:
            # Show download section
            PDFExportDialog._show_download_section(issue_result, pdf_key)
    
    @staticmethod
    def _show_generation_form(issue_result: Dict[str, Any], pdf_key: str):
        """Show simplified PDF generation form"""
        with st.form("pdf_generation_form", clear_on_submit=False):
            col1, col2 = st.columns(2)
            
            with col1:
                language = st.selectbox(
                    "Language / Ngôn ngữ",
                    options=['vi', 'en'],
                    format_func=lambda x: "🇻🇳 Tiếng Việt" if x == 'vi' else "🇬🇧 English",
                    index=0,
                    key="pdf_language"
                )
            
            with col2:
                include_signatures = st.checkbox(
                    "Include signature section",
                    value=True,
                    key="pdf_signatures"
                )
            
            st.markdown("---")
            
            # Action buttons
            col1, col2 = st.columns([2, 2])
            
            with col1:
                generate_btn = st.form_submit_button(
                    "🖨️ Generate PDF",
                    type="primary",
                    use_container_width=True
                )
            
            with col2:
                skip_btn = st.form_submit_button(
                    "⏭️ Skip for Now",
                    use_container_width=True
                )
            
            if generate_btn:
                issue_id = issue_result.get('issue_id')
                issue_no = issue_result.get('issue_no', f'ISSUE_{issue_id}')
                
                if not issue_id:
                    st.error("❌ Invalid issue data. Missing issue ID.")
                    return
                
                try:
                    # Validate issue data
                    if not pdf_generator.validate_issue_data(issue_id):
                        st.error("❌ Issue data not found in database.")
                        return
                    
                    with st.spinner("Generating PDF... Please wait..."):
                        # Generate PDF with simplified options
                        pdf_options = {
                            'language': language,
                            'include_signatures': include_signatures,
                        }
                        
                        pdf_content = pdf_generator.generate_pdf_with_options(
                            issue_id,
                            pdf_options
                        )
                        
                        if not pdf_content:
                            st.error("❌ PDF generation failed - empty content returned")
                            return
                        
                        # Generate filename with language indicator
                        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                        lang_suffix = 'EN' if language == 'en' else 'VI'
                        filename = f"MaterialIssue_{issue_no}_{lang_suffix}_{timestamp}.pdf"
                        
                        # Store in session state with unique key
                        st.session_state[pdf_key] = True
                        st.session_state[f'{pdf_key}_content'] = pdf_content
                        st.session_state[f'{pdf_key}_filename'] = filename
                        
                        logger.info(f"✅ PDF generated for issue {issue_no}")
                        
                        # Rerun to show download section
                        st.rerun()
                        
                except Exception as e:
                    st.error(f"❌ Error generating PDF: {str(e)}")
                    logger.error(f"PDF generation error for issue {issue_id}: {e}", exc_info=True)
            
            if skip_btn:
                st.info("✅ You can generate the PDF later from the Issue History tab")
                st.rerun()  # Close dialog after skip
    
    @staticmethod
    def _show_download_section(issue_result: Dict[str, Any], pdf_key: str):
        """Show download section after PDF generation"""
        st.success("✅ PDF Generated Successfully!")
        
        pdf_content = st.session_state.get(f'{pdf_key}_content')
        filename = st.session_state.get(f'{pdf_key}_filename')
        issue_id = issue_result.get('issue_id')
        
        if pdf_content and filename:
            col1, col2 = st.columns([3, 1])
            
            with col1:
                st.download_button(
                    label="💾 Download PDF",
                    data=pdf_content,
                    file_name=filename,
                    mime="application/pdf",
                    use_container_width=True,
                    type="primary",
                    key=f"download_{issue_id}_final"
                )
            
            with col2:
                if st.button("✅ Done", use_container_width=True, key=f"done_{issue_id}"):
                    # Clear state and close
                    st.session_state.pop(pdf_key, None)
                    st.session_state.pop(f'{pdf_key}_content', None)
                    st.session_state.pop(f'{pdf_key}_filename', None)
                    st.rerun()
            
            st.markdown("---")
            if st.button("🔄 Regenerate with Different Settings", key=f"regenerate_{issue_id}"):
                st.session_state.pop(pdf_key, None)
                st.session_state.pop(f'{pdf_key}_content', None)
                st.session_state.pop(f'{pdf_key}_filename', None)
                st.rerun()


class QuickPDFButton:
    """Quick PDF generation button for Issue History list"""
    
    @staticmethod
    @st.dialog("📄 Generate PDF", width="large")
    def show_quick_pdf_dialog(issue_id: int, issue_no: str):
        """
        Show quick PDF generation dialog from Issue History
        
        Args:
            issue_id: Material issue ID
            issue_no: Material issue number
        """
        st.markdown(f"### Generate PDF for Issue: **{issue_no}**")
        
        quick_key = f"quick_pdf_{issue_id}"
        
        if not st.session_state.get(quick_key):
            QuickPDFButton._show_quick_generation_form(issue_id, issue_no, quick_key)
        else:
            QuickPDFButton._show_quick_download_section(issue_id, issue_no, quick_key)
    
    @staticmethod
    def _show_quick_generation_form(issue_id: int, issue_no: str, quick_key: str):
        """Show quick generation form"""
        col1, col2 = st.columns(2)
        
        with col1:
            language = st.selectbox(
                "Language / Ngôn ngữ",
                options=['vi', 'en'],
                format_func=lambda x: "🇻🇳 Tiếng Việt" if x == 'vi' else "🇬🇧 English",
                key=f"quick_lang_{issue_id}"
            )
        
        with col2:
            include_signatures = st.checkbox(
                "Include signatures",
                value=True,
                key=f"quick_sig_{issue_id}"
            )
        
        st.markdown("---")
        
        col1, col2 = st.columns(2)
        
        with col1:
            generate = st.button(
                "🖨️ Generate PDF",
                type="primary",
                use_container_width=True,
                key=f"quick_gen_{issue_id}"
            )
        
        with col2:
            cancel = st.button(
                "❌ Cancel",
                use_container_width=True,
                key=f"quick_cancel_{issue_id}"
            )
        
        if generate:
            try:
                if not pdf_generator.validate_issue_data(issue_id):
                    st.error("❌ Issue data not found")
                    return
                
                with st.spinner("Generating PDF..."):
                    pdf_options = {
                        'language': language,
                        'include_signatures': include_signatures,
                    }
                    
                    pdf_content = pdf_generator.generate_pdf_with_options(
                        issue_id,
                        pdf_options
                    )
                    
                    if not pdf_content:
                        st.error("❌ PDF generation failed - empty content")
                        return
                    
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    lang_suffix = 'EN' if language == 'en' else 'VI'
                    filename = f"MaterialIssue_{issue_no}_{lang_suffix}_{timestamp}.pdf"
                    
                    # Store in session state
                    st.session_state[quick_key] = True
                    st.session_state[f'{quick_key}_content'] = pdf_content
                    st.session_state[f'{quick_key}_filename'] = filename
                    
                    logger.info(f"Quick PDF generated for issue {issue_no}")
                    
                    # Show download immediately
                    st.success("✅ PDF Generated Successfully!")
                    
                    st.download_button(
                        label="💾 Download PDF",
                        data=pdf_content,
                        file_name=filename,
                        mime="application/pdf",
                        use_container_width=True,
                        type="primary",
                        key=f"quick_download_inline_{issue_id}"
                    )
                    
                    st.info("💡 Close this dialog when done, or generate another PDF from the history list")
                    
            except Exception as e:
                st.error(f"❌ Unable to generate PDF: {str(e)}")
                logger.error(f"Quick PDF error for issue {issue_id}: {e}", exc_info=True)
        
        if cancel:
            # Clear any stored state for this issue
            st.session_state.pop(quick_key, None)
            st.session_state.pop(f'{quick_key}_content', None)
            st.session_state.pop(f'{quick_key}_filename', None)
            st.rerun()
    
    @staticmethod
    def _show_quick_download_section(issue_id: int, issue_no: str, quick_key: str):
        """Show quick download section"""
        st.success("✅ PDF Generated Successfully!")
        
        pdf_content = st.session_state.get(f'{quick_key}_content')
        filename = st.session_state.get(f'{quick_key}_filename')
        
        if pdf_content and filename:
            col1, col2 = st.columns([3, 1])
            
            with col1:
                st.download_button(
                    label="💾 Download PDF",
                    data=pdf_content,
                    file_name=filename,
                    mime="application/pdf",
                    use_container_width=True,
                    type="primary",
                    key=f"quick_download_{issue_id}_final"
                )
            
            with col2:
                if st.button("✅ Done", use_container_width=True, key=f"quick_done_{issue_id}"):
                    # Clear state
                    st.session_state.pop(quick_key, None)
                    st.session_state.pop(f'{quick_key}_content', None)
                    st.session_state.pop(f'{quick_key}_filename', None)
                    st.rerun()
            
            st.markdown("---")
            if st.button("🔄 Generate with Different Settings", key=f"regenerate_quick_{issue_id}"):
                st.session_state.pop(quick_key, None)
                st.session_state.pop(f'{quick_key}_content', None)
                st.session_state.pop(f'{quick_key}_filename', None)
                st.rerun()
    
    @staticmethod
    def render(issue_id: int, issue_no: str):
        """
        Render a quick PDF button that opens dialog
        
        Args:
            issue_id: Material issue ID
            issue_no: Material issue number
        """
        if st.button(f"📄 PDF", key=f"pdf_{issue_id}", help=f"Generate PDF for {issue_no}"):
            QuickPDFButton.show_quick_pdf_dialog(issue_id, issue_no)


class PDFBulkExport:
    """Handle bulk PDF export for multiple issues"""
    
    @staticmethod
    @st.dialog("📦 Bulk PDF Export", width="large")
    def show_bulk_export_dialog(issue_ids: list, issue_data: list):
        """
        Show bulk export dialog
        
        Args:
            issue_ids: List of issue IDs to export
            issue_data: List of dicts with issue info (id, issue_no, etc.)
        """
        if not issue_ids:
            st.warning("No issues selected for export")
            return
        
        st.markdown(f"### 📦 Bulk PDF Export ({len(issue_ids)} issues)")
        
        # Show selected issues
        with st.expander("📋 Selected Issues", expanded=True):
            for issue in issue_data:
                st.write(f"• {issue['issue_no']} - {issue.get('order_no', 'N/A')}")
        
        st.markdown("---")
        
        # Bulk export options
        with st.form("bulk_export_form"):
            language = st.selectbox(
                "Language for all PDFs",
                options=['vi', 'en'],
                format_func=lambda x: "🇻🇳 Tiếng Việt" if x == 'vi' else "🇬🇧 English",
                key="bulk_language"
            )
            
            st.markdown("---")
            
            col1, col2 = st.columns(2)
            
            with col1:
                start_export = st.form_submit_button(
                    "🚀 Start Bulk Export",
                    type="primary",
                    use_container_width=True
                )
            
            with col2:
                cancel = st.form_submit_button(
                    "❌ Cancel",
                    use_container_width=True
                )
            
            if start_export:
                PDFBulkExport._process_bulk_export(issue_ids, language)
            
            if cancel:
                st.rerun()
    
    @staticmethod
    def _process_bulk_export(issue_ids: list, language: str):
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
        
        st.info("💡 Note: PDFs are generated but not automatically downloaded in bulk mode. Use individual download for each issue.")
    
    @staticmethod
    def render_bulk_export_button(issue_ids: list, issue_data: list):
        """
        Render bulk export button
        
        Args:
            issue_ids: List of issue IDs
            issue_data: List of issue info dicts
        """
        if st.button("📦 Bulk Export PDFs", type="primary"):
            PDFBulkExport.show_bulk_export_dialog(issue_ids, issue_data)