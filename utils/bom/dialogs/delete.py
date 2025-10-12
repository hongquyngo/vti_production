# utils/bom/dialogs/delete.py
"""
Delete BOM Confirmation Dialog - FIXED IMPORT
Simple confirmation dialog with safety checks
"""

import logging
import streamlit as st

from utils.bom.manager import BOMManager, BOMException, BOMValidationError, BOMNotFoundError
from utils.bom.state import StateManager
from utils.bom.common import render_confirmation_checkbox

logger = logging.getLogger(__name__)


@st.dialog("🗑️ Delete BOM", width="large")
def show_delete_dialog(bom_id: int):
    """
    Delete BOM confirmation dialog
    
    Args:
        bom_id: BOM ID to delete
    """
    state = StateManager()
    manager = BOMManager()
    
    try:
        # Load BOM info
        bom_info = manager.get_bom_info(bom_id)
        
        if not bom_info:
            st.error("❌ BOM not found")
            if st.button("Close", key=f"delete_notfound_close_{bom_id}"):
                st.rerun()
            return
        
        # Check if deletable
        can_delete, error_msg = _check_deletable(bom_info)
        
        # Display warning
        st.warning("⚠️ **Warning: This action cannot be undone!**")
        
        # BOM details
        st.markdown("### BOM to be deleted:")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.write(f"**Code:** {bom_info['bom_code']}")
            st.write(f"**Name:** {bom_info['bom_name']}")
            st.write(f"**Type:** {bom_info['bom_type']}")
        
        with col2:
            st.write(f"**Product:** {bom_info['product_name']}")
            st.write(f"**Status:** {bom_info['status']}")
            st.write(f"**Materials:** {bom_info.get('material_count', 0)}")
        
        st.markdown("---")
        
        # Show error if not deletable
        if not can_delete:
            st.error(f"❌ {error_msg}")
            
            if st.button("Close", use_container_width=True, key=f"delete_error_close_{bom_id}"):
                state.close_dialog()
                st.rerun()
            return
        
        # Confirmation checkbox
        confirmed = render_confirmation_checkbox(
            f"delete_confirm_{bom_id}",
            "✓ I understand this will permanently delete the BOM"
        )
        
        st.markdown("---")
        
        # Action buttons
        col1, col2 = st.columns([1, 1])
        
        with col1:
            if st.button(
                "🗑️ Confirm Delete",
                type="primary",
                disabled=not confirmed,
                use_container_width=True,
                key=f"delete_confirm_btn_{bom_id}"
            ):
                _handle_delete(bom_id, bom_info, state, manager)
        
        with col2:
            if st.button("❌ Cancel", use_container_width=True, key=f"delete_cancel_{bom_id}"):
                state.close_dialog()
                st.rerun()
    
    except Exception as e:
        logger.error(f"Error in delete dialog: {e}")
        st.error(f"❌ Error: {str(e)}")
        
        if st.button("Close", key=f"delete_exception_close_{bom_id}"):
            state.close_dialog()
            st.rerun()


def _check_deletable(bom_info: dict) -> tuple[bool, str]:
    """
    Check if BOM can be deleted
    
    Args:
        bom_info: BOM information dictionary
    
    Returns:
        Tuple of (can_delete, error_message)
    """
    # Check if BOM has usage
    total_usage = bom_info.get('total_usage', 0)
    
    if total_usage > 0:
        return False, f"Cannot delete BOM - used in {total_usage} manufacturing orders"
    
    # Check if BOM is active
    if bom_info['status'] == 'ACTIVE':
        return False, "Cannot delete ACTIVE BOM. Please set to INACTIVE first."
    
    return True, ""


def _handle_delete(bom_id: int, bom_info: dict, state: StateManager, manager: BOMManager):
    """
    Handle BOM deletion
    
    Args:
        bom_id: BOM ID
        bom_info: BOM information
        state: State manager
        manager: BOM manager
    """
    try:
        # Get user ID from session
        user_id = st.session_state.get('user_id', 1)
        
        # Delete BOM
        manager.delete_bom(bom_id, user_id)
        
        # Record action
        state.record_action(
            'delete',
            bom_id=bom_id,
            bom_code=bom_info['bom_code']
        )
        
        # Show success
        state.show_success(f"✅ BOM {bom_info['bom_code']} deleted successfully!")
        
        # Close dialog
        state.close_dialog()
        
        st.rerun()
    
    except BOMValidationError as e:
        st.error(f"❌ Validation Error: {str(e)}")
    except BOMException as e:
        st.error(f"❌ Error: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error deleting BOM: {e}")
        st.error(f"❌ Unexpected error: {str(e)}")