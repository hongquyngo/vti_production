# utils/bom/dialogs/status.py
"""
Change BOM Status Dialog with Alternatives Awareness
Status transition with validation considering alternatives
"""

import logging
import streamlit as st

from utils.bom.manager import BOMManager, BOMException, BOMValidationError, BOMNotFoundError
from utils.bom.state import StateManager
from utils.bom.common import create_status_indicator, STATUS_WORKFLOW

logger = logging.getLogger(__name__)


@st.dialog("🔄 Change BOM Status", width="large")
def show_status_dialog(bom_id: int):
    """Change BOM status dialog"""
    state = StateManager()
    manager = BOMManager()
    
    try:
        bom_info = manager.get_bom_info(bom_id)
        
        if not bom_info:
            st.error("❌ BOM not found")
            if st.button("Close", key=f"status_notfound_close_{bom_id}"):
                state.close_dialog()
                st.rerun()
            return
        
        # Display BOM info
        st.markdown("### BOM Information")
        col1, col2 = st.columns(2)
        
        with col1:
            st.write(f"**Code:** {bom_info['bom_code']}")
            st.write(f"**Name:** {bom_info['bom_name']}")
        
        with col2:
            st.write(f"**Type:** {bom_info['bom_type']}")
            st.write(f"**Product:** {bom_info['product_name']}")
        
        st.markdown("---")
        
        # Current status
        current_status = bom_info['status']
        st.markdown("### Current Status")
        st.info(f"**{create_status_indicator(current_status)}**")
        
        st.markdown("---")
        
        # New status selection
        st.markdown("### Select New Status")
        
        allowed_statuses = STATUS_WORKFLOW.get(current_status, [])
        
        if not allowed_statuses:
            st.warning(f"⚠️ No status transitions available from {current_status}")
            
            if st.button("Close", use_container_width=True, key=f"status_notransition_close_{bom_id}"):
                state.close_dialog()
                st.rerun()
            return
        
        new_status = st.radio(
            "New Status",
            options=allowed_statuses,
            format_func=lambda x: create_status_indicator(x),
            key=f"status_radio_{bom_id}"
        )
        
        # Show requirements for selected status
        if new_status:
            _render_status_requirements(new_status, bom_info, manager)
        
        st.markdown("---")
        
        # Validate transition
        can_transition, error_msg = _validate_status_transition(
            current_status, new_status, bom_info, manager
        )
        
        # Show validation errors
        if not can_transition:
            st.error(f"❌ {error_msg}")
        
        # Action buttons
        col1, col2 = st.columns([1, 1])
        
        with col1:
            if st.button(
                "✅ Update Status",
                type="primary",
                disabled=not can_transition,
                use_container_width=True,
                key=f"status_update_{bom_id}"
            ):
                _handle_status_update(bom_id, new_status, bom_info, state, manager)
        
        with col2:
            if st.button("❌ Cancel", use_container_width=True, key=f"status_cancel_{bom_id}"):
                state.close_dialog()
                st.rerun()
    
    except Exception as e:
        logger.error(f"Error in status dialog: {e}")
        st.error(f"❌ Error: {str(e)}")
        
        if st.button("Close", key=f"status_exception_close_{bom_id}"):
            state.close_dialog()
            st.rerun()


def _render_status_requirements(status: str, bom_info: dict, manager: BOMManager):
    """Render requirements for selected status """
    st.markdown("#### Requirements:")
    
    if status == 'ACTIVE':
        st.info("**To activate BOM, the following is required:**")
        
        # Check materials
        bom_details = manager.get_bom_details(bom_info['id'])
        has_materials = not bom_details.empty
        
        material_icon = "✅" if has_materials else "❌"
        st.write(f"{material_icon} At least 1 material")
        
        # Check product mapping
        has_product = bom_info.get('product_id') is not None
        product_icon = "✅" if has_product else "❌"
        st.write(f"{product_icon} Valid product mapping")
        
        # Check output quantity
        has_output = bom_info.get('output_qty', 0) > 0
        output_icon = "✅" if has_output else "❌"
        st.write(f"{output_icon} Output quantity > 0")

        st.caption("ℹ️ Stock availability will be validated at Manufacturing Order level")
        
    
    elif status == 'INACTIVE':
        st.info("**To deactivate BOM:**")
        
        active_orders = bom_info.get('active_orders', 0)
        no_active_orders = active_orders == 0
        
        orders_icon = "✅" if no_active_orders else "❌"
        st.write(f"{orders_icon} No active manufacturing orders (Current: {active_orders})")
        
        if active_orders > 0:
            st.warning(
                "⚠️ Complete or cancel all active orders before deactivating BOM"
            )
    
    elif status == 'DRAFT':
        st.info("**Reverting to DRAFT:**")
        st.write("✅ Can edit BOM information")
        st.write("✅ Can modify materials and alternatives")
        st.write("⚠️ Cannot be used in manufacturing orders")

def _validate_status_transition(current: str, new: str, 
                                bom_info: dict, manager: BOMManager) -> tuple[bool, str]:
    """Validate if status transition is allowed"""
    # Check if same status
    if current == new:
        return False, "New status must be different from current status"
    
    # Check if transition is allowed
    allowed = STATUS_WORKFLOW.get(current, [])
    if new not in allowed:
        return False, f"Cannot transition from {current} to {new}"
    
    # Validate ACTIVE requirements
    if new == 'ACTIVE':
        # Check has materials
        bom_details = manager.get_bom_details(bom_info['id'])
        if bom_details.empty:
            return False, "Cannot activate BOM without materials"
        
        # Check output quantity
        if bom_info.get('output_qty', 0) <= 0:
            return False, "Output quantity must be greater than 0"
        
    # Validate INACTIVE requirements
    if new == 'INACTIVE':
        # Check no active orders
        active_orders = bom_info.get('active_orders', 0)
        if active_orders > 0:
            return False, f"Cannot deactivate BOM with {active_orders} active manufacturing orders"
    
    return True, ""


def _handle_status_update(bom_id: int, new_status: str, bom_info: dict,
                         state: StateManager, manager: BOMManager):
    """Handle status update"""
    try:
        user_id = st.session_state.get('user_id', 1)
        
        manager.update_bom_status(bom_id, new_status, user_id)
        
        state.record_action(
            'status_change',
            bom_id=bom_id,
            bom_code=bom_info['bom_code']
        )
        
        state.show_success(
            f"✅ BOM {bom_info['bom_code']} status updated to {new_status}"
        )
        
        state.clear_bom_list_cache() # Clear cache to reflect status change

        state.close_dialog()
        
        st.rerun()
    
    except BOMValidationError as e:
        st.error(f"❌ Validation Error: {str(e)}")
    except BOMException as e:
        st.error(f"❌ Error: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error updating status: {e}")
        st.error(f"❌ Unexpected error: {str(e)}")