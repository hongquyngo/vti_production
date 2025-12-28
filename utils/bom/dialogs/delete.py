# utils/bom/dialogs/delete.py
"""
Delete BOM Confirmation Dialog with Alternatives Info - VERSION 2.1
Shows complete deletion impact including alternatives

Changes in v2.1:
- Updated material display to unified format with legacy_code
"""

import logging
import streamlit as st

from utils.bom.manager import BOMManager, BOMException, BOMValidationError, BOMNotFoundError
from utils.bom.state import StateManager
from utils.bom.common import render_confirmation_checkbox, format_product_display

logger = logging.getLogger(__name__)


@st.dialog("🗑️ Delete BOM", width="large")
def show_delete_dialog(bom_id: int):
    """Delete BOM confirmation dialog"""
    state = StateManager()
    manager = BOMManager()
    
    try:
        bom_info = manager.get_bom_info(bom_id)
        
        if not bom_info:
            st.error("❌ BOM not found")
            if st.button("Close", key=f"delete_notfound_close_{bom_id}"):
                st.rerun()
            return
        
        # Get deletion impact details
        deletion_impact = _get_deletion_impact(bom_id, bom_info, manager)
        
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
            st.write(f"**Materials:** {deletion_impact['material_count']}")
        
        st.markdown("---")
        
        # Show deletion impact
        _render_deletion_impact(deletion_impact)
        
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
            "✓ I understand this will permanently delete the BOM and all its materials/alternatives"
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


def _get_deletion_impact(bom_id: int, bom_info: dict, manager: BOMManager) -> dict:
    """
    Get complete deletion impact including alternatives
    
    Returns:
        {
            'material_count': int,
            'total_alternatives_count': int,
            'materials_with_alternatives': int,
            'materials': [
                {
                    'name': str,
                    'code': str,
                    'legacy_code': str,
                    'package_size': str,
                    'brand': str,
                    'alternatives_count': int
                }
            ]
        }
    """
    try:
        bom_details = manager.get_bom_details(bom_id)
        
        material_count = len(bom_details)
        total_alternatives = int(bom_details['alternatives_count'].sum()) if not bom_details.empty else 0
        materials_with_alts = int((bom_details['alternatives_count'] > 0).sum()) if not bom_details.empty else 0
        
        # Get material details with full product info
        materials_info = []
        if not bom_details.empty:
            for _, mat in bom_details.iterrows():
                alt_count = int(mat.get('alternatives_count', 0))
                materials_info.append({
                    'name': mat.get('material_name', ''),
                    'code': mat.get('material_code', ''),
                    'legacy_code': mat.get('legacy_code'),
                    'package_size': mat.get('package_size'),
                    'brand': mat.get('brand'),
                    'alternatives_count': alt_count
                })
        
        return {
            'material_count': material_count,
            'total_alternatives_count': total_alternatives,
            'materials_with_alternatives': materials_with_alts,
            'materials': materials_info
        }
    
    except Exception as e:
        logger.error(f"Error getting deletion impact: {e}")
        return {
            'material_count': 0,
            'total_alternatives_count': 0,
            'materials_with_alternatives': 0,
            'materials': []
        }


def _render_deletion_impact(impact: dict):
    """Render deletion impact summary"""
    st.markdown("### 📊 Deletion Impact")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric(
            "Materials",
            impact['material_count'],
            help="Number of materials that will be deleted"
        )
    
    with col2:
        st.metric(
            "Materials with Alternatives",
            impact['materials_with_alternatives'],
            help="Materials that have alternative materials defined"
        )
    
    with col3:
        st.metric(
            "Total Alternatives",
            impact['total_alternatives_count'],
            help="Total number of alternative materials that will be deleted"
        )
    
    # Show details if there are alternatives
    if impact['total_alternatives_count'] > 0:
        st.markdown("---")
        
        st.warning(
            f"⚠️ **This BOM has {impact['total_alternatives_count']} alternative material(s) "
            f"defined across {impact['materials_with_alternatives']} material(s). "
            f"All alternatives will be permanently deleted.**"
        )
        
        # Show expandable list of materials with alternatives
        with st.expander("📋 View materials with alternatives", expanded=False):
            for mat in impact['materials']:
                if mat['alternatives_count'] > 0:
                    mat_display = format_product_display(
                        code=mat.get('code', ''),
                        name=mat.get('name', ''),
                        package_size=mat.get('package_size'),
                        brand=mat.get('brand'),
                        legacy_code=mat.get('legacy_code')
                    )
                    st.markdown(
                        f"- **{mat_display}** "
                        f"→ 🔀 **{mat['alternatives_count']} alternative(s)**"
                    )
    else:
        st.info("ℹ️ This BOM has no alternative materials defined.")


def _check_deletable(bom_info: dict) -> tuple[bool, str]:
    """
    Check if BOM can be deleted
    
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
    """Handle BOM deletion"""
    try:
        user_id = st.session_state.get('user_id', 1)
        
        # Delete BOM (soft delete on header, materials and alternatives remain but inaccessible)
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