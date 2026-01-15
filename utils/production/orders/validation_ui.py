# utils/production/orders/validation_ui.py
"""
UI helpers for displaying validation results in Streamlit
Provides consistent UI components for showing blocks and warnings

Version: 1.0.0
"""

import logging
from typing import Callable, Optional

import streamlit as st

from .validators import ValidationResults, ValidationLevel, ValidationResult

logger = logging.getLogger(__name__)


def render_validation_blocks(results: ValidationResults, language: str = 'en') -> bool:
    """
    Render blocking validation errors
    
    Args:
        results: ValidationResults object
        language: 'en' for English, 'vi' for Vietnamese
        
    Returns:
        True if there are blocking errors
    """
    if not results.has_blocks:
        return False
    
    st.error("🚫 **Cannot proceed - validation errors found:**")
    
    for block in results.blocks:
        msg = block.message_vi if language == 'vi' else block.message
        st.markdown(f"- **[{block.rule_id}]** {msg}")
        
        # Show details if available
        if block.details:
            with st.expander(f"Details for {block.rule_id}", expanded=False):
                for key, value in block.details.items():
                    st.write(f"• {key}: {value}")
    
    return True


def render_validation_warnings(results: ValidationResults, 
                               language: str = 'en',
                               show_details: bool = True) -> bool:
    """
    Render validation warnings
    
    Args:
        results: ValidationResults object
        language: 'en' for English, 'vi' for Vietnamese
        show_details: If True, show expandable details
        
    Returns:
        True if there are warnings
    """
    if not results.has_warnings:
        return False
    
    st.warning(f"⚠️ **{len(results.warnings)} warning(s) found:**")
    
    for warning in results.warnings:
        msg = warning.message_vi if language == 'vi' else warning.message
        st.markdown(f"- **[{warning.rule_id}]** {msg}")
        
        # Show details if available and requested
        if show_details and warning.details:
            with st.expander(f"Details for {warning.rule_id}", expanded=False):
                for key, value in warning.details.items():
                    st.write(f"• {key}: {value}")
    
    return True


def render_validation_summary(results: ValidationResults, language: str = 'en'):
    """
    Render a summary of validation results
    
    Args:
        results: ValidationResults object
        language: 'en' for English, 'vi' for Vietnamese
    """
    if not results.results:
        st.success("✅ All validations passed")
        return
    
    col1, col2 = st.columns(2)
    
    with col1:
        if results.has_blocks:
            st.error(f"🚫 {len(results.blocks)} blocking error(s)")
        else:
            st.success("✅ No blocking errors")
    
    with col2:
        if results.has_warnings:
            st.warning(f"⚠️ {len(results.warnings)} warning(s)")
        else:
            st.info("ℹ️ No warnings")


def render_warning_acknowledgment(results: ValidationResults,
                                  key_prefix: str,
                                  language: str = 'en') -> bool:
    """
    Render warnings with acknowledgment checkbox
    
    Args:
        results: ValidationResults object
        key_prefix: Unique prefix for session state keys
        language: 'en' for English, 'vi' for Vietnamese
        
    Returns:
        True if user has acknowledged all warnings
    """
    if not results.has_warnings:
        return True
    
    # Initialize acknowledgment state
    ack_key = f"{key_prefix}_warnings_acknowledged"
    if ack_key not in st.session_state:
        st.session_state[ack_key] = False
    
    # Render warnings
    render_validation_warnings(results, language)
    
    st.markdown("---")
    
    # Acknowledgment checkbox
    ack_label = "I understand and want to proceed anyway" if language == 'en' else "Tôi hiểu và muốn tiếp tục"
    acknowledged = st.checkbox(
        f"☑️ {ack_label}",
        value=st.session_state[ack_key],
        key=f"{key_prefix}_ack_checkbox"
    )
    
    st.session_state[ack_key] = acknowledged
    
    return acknowledged


def render_validation_dialog(results: ValidationResults,
                            action_name: str,
                            on_proceed: Callable,
                            on_cancel: Callable,
                            key_prefix: str,
                            language: str = 'en'):
    """
    Render a complete validation dialog with warnings and action buttons
    
    Args:
        results: ValidationResults object
        action_name: Name of the action (e.g., "Create Order", "Confirm")
        on_proceed: Callback when user proceeds
        on_cancel: Callback when user cancels
        key_prefix: Unique prefix for session state keys
        language: 'en' for English, 'vi' for Vietnamese
    """
    # Check for blocks first
    if results.has_blocks:
        render_validation_blocks(results, language)
        
        if st.button("❌ Close", key=f"{key_prefix}_close_btn"):
            on_cancel()
        return
    
    # Show warnings if any
    if results.has_warnings:
        acknowledged = render_warning_acknowledgment(results, key_prefix, language)
        
        st.markdown("---")
        
        col1, col2 = st.columns(2)
        
        with col1:
            proceed_label = f"✅ {action_name}" if language == 'en' else f"✅ {action_name}"
            if st.button(proceed_label, 
                        type="primary", 
                        use_container_width=True,
                        disabled=not acknowledged,
                        key=f"{key_prefix}_proceed_btn"):
                on_proceed()
        
        with col2:
            cancel_label = "❌ Cancel" if language == 'en' else "❌ Hủy"
            if st.button(cancel_label, 
                        use_container_width=True,
                        key=f"{key_prefix}_cancel_btn"):
                on_cancel()
    else:
        # No warnings, just proceed
        on_proceed()


def show_validation_toast(results: ValidationResults, language: str = 'en'):
    """
    Show validation results as toast notifications
    
    Args:
        results: ValidationResults object
        language: 'en' for English, 'vi' for Vietnamese
    """
    for block in results.blocks:
        msg = block.message_vi if language == 'vi' else block.message
        st.toast(f"🚫 [{block.rule_id}] {msg}", icon="🚫")
    
    for warning in results.warnings:
        msg = warning.message_vi if language == 'vi' else warning.message
        st.toast(f"⚠️ [{warning.rule_id}] {msg}", icon="⚠️")


def format_validation_for_notes(results: ValidationResults, language: str = 'en') -> str:
    """
    Format validation results as text for order notes
    
    Args:
        results: ValidationResults object
        language: 'en' for English, 'vi' for Vietnamese
        
    Returns:
        Formatted string suitable for notes field
    """
    if not results.has_warnings:
        return ""
    
    lines = ["[WARNINGS ACKNOWLEDGED]"]
    
    for warning in results.warnings:
        msg = warning.message_vi if language == 'vi' else warning.message
        lines.append(f"- [{warning.rule_id}] {msg}")
    
    return "\n".join(lines)


class ValidationUI:
    """
    Class-based UI helper for validation display
    Maintains state across renders
    """
    
    def __init__(self, key_prefix: str, language: str = 'en'):
        self.key_prefix = key_prefix
        self.language = language
        self._results: Optional[ValidationResults] = None
    
    def set_results(self, results: ValidationResults):
        """Set validation results to display"""
        self._results = results
    
    @property
    def has_blocks(self) -> bool:
        return self._results.has_blocks if self._results else False
    
    @property
    def has_warnings(self) -> bool:
        return self._results.has_warnings if self._results else False
    
    @property
    def is_acknowledged(self) -> bool:
        """Check if warnings have been acknowledged"""
        if not self._results or not self._results.has_warnings:
            return True
        
        ack_key = f"{self.key_prefix}_warnings_acknowledged"
        return st.session_state.get(ack_key, False)
    
    def render_blocks(self) -> bool:
        """Render blocking errors, returns True if there are blocks"""
        if not self._results:
            return False
        return render_validation_blocks(self._results, self.language)
    
    def render_warnings(self) -> bool:
        """Render warnings, returns True if there are warnings"""
        if not self._results:
            return False
        return render_validation_warnings(self._results, self.language)
    
    def render_acknowledgment(self) -> bool:
        """Render warnings with acknowledgment, returns True if acknowledged"""
        if not self._results:
            return True
        return render_warning_acknowledgment(self._results, self.key_prefix, self.language)
    
    def render_summary(self):
        """Render validation summary"""
        if self._results:
            render_validation_summary(self._results, self.language)
    
    def can_proceed(self) -> bool:
        """Check if action can proceed (no blocks, warnings acknowledged)"""
        if not self._results:
            return True
        
        if self._results.has_blocks:
            return False
        
        if self._results.has_warnings and not self.is_acknowledged:
            return False
        
        return True
    
    def reset_acknowledgment(self):
        """Reset warning acknowledgment state"""
        ack_key = f"{self.key_prefix}_warnings_acknowledged"
        if ack_key in st.session_state:
            del st.session_state[ack_key]
