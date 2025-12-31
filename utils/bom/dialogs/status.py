# utils/bom/dialogs/status.py
"""
Change BOM Status Dialog - VERSION 2.2

Updated status transitions:
- DRAFT → ACTIVE, INACTIVE
- ACTIVE → INACTIVE, DRAFT (if no usage)
- INACTIVE → ACTIVE, DRAFT (if no usage)

Changes in v2.2:
- Added pre-validation for Multiple Active BOM Conflict (Phase 1)
- Warning displayed when activating BOM for product that already has active BOM(s)
- Options: Deactivate old + Activate new, Keep both active, Cancel
- Auto-deactivation of existing BOMs when user selects that option

Changes in v2.1:
- Updated product display to unified format with legacy_code

New in v2.0:
- Added ACTIVE/INACTIVE → DRAFT transition (only if total_usage == 0)
- Enhanced validation with usage context
- Clearer requirements display
"""

import logging
import streamlit as st

from utils.bom.manager import BOMManager, BOMException, BOMValidationError, BOMNotFoundError
from utils.bom.state import StateManager
from utils.bom.common import (
    create_status_indicator,
    format_product_display,
    STATUS_WORKFLOW,
    get_allowed_status_transitions,
    validate_status_transition,
    render_usage_context,
    format_number,
    # Phase 1: Active BOM Conflict Detection
    check_active_bom_conflict
)

logger = logging.getLogger(__name__)


@st.dialog("🔄 Change BOM Status", width="large")
def show_status_dialog(bom_id: int):
    """Change BOM status dialog with usage-aware transitions"""
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
        _render_bom_info(bom_info)
        
        st.markdown("---")
        
        # Current status
        current_status = bom_info['status']
        st.markdown("### Current Status")
        st.info(f"**{create_status_indicator(current_status)}**")
        
        # Usage context
        st.markdown("### 📊 Usage Context")
        render_usage_context(bom_info)
        
        st.markdown("---")
        
        # Get allowed transitions with validation
        transitions = get_allowed_status_transitions(bom_info)
        
        if not transitions:
            st.warning(f"⚠️ No status transitions available from {current_status}")
            
            if st.button("Close", use_container_width=True, key=f"status_notransition_close_{bom_id}"):
                state.close_dialog()
                st.rerun()
            return
        
        # New status selection
        st.markdown("### Select New Status")
        
        # Build options with availability info
        status_options = []
        for new_status, (is_allowed, reason) in transitions.items():
            status_options.append({
                'status': new_status,
                'allowed': is_allowed,
                'reason': reason
            })
        
        # Radio for status selection
        selected_status = st.radio(
            "New Status",
            options=[opt['status'] for opt in status_options],
            format_func=lambda x: _format_status_option(x, transitions),
            key=f"status_radio_{bom_id}"
        )
        
        # Show requirements for selected status
        if selected_status:
            _render_status_requirements(selected_status, bom_info, transitions, manager)
        
        st.markdown("---")
        
        # Validate transition
        is_allowed, error_msg = transitions.get(selected_status, (False, "Invalid status"))
        
        # Show validation errors
        if not is_allowed:
            st.error(f"❌ {error_msg}")
        
        # Check if there's a conflict action that blocks proceeding
        conflict_action = st.session_state.get(f"conflict_action_{bom_id}", None)
        conflict_info = st.session_state.get(f"conflict_info_{bom_id}", {})
        
        # Determine if we can proceed based on conflict action
        can_proceed = is_allowed
        button_label = "✅ Update Status"
        
        if selected_status == 'ACTIVE' and conflict_info.get('has_conflict'):
            if conflict_action == 'cancel':
                can_proceed = False
                button_label = "❌ Action Cancelled"
            elif conflict_action == 'deactivate_old':
                count = conflict_info.get('conflict_count', 0)
                button_label = f"🔄 Deactivate {count} BOM(s) & Activate"
            elif conflict_action == 'keep_both':
                button_label = "⚠️ Activate (Keep All Active)"
        
        # Action buttons
        col1, col2 = st.columns([1, 1])
        
        with col1:
            if st.button(
                button_label,
                type="primary",
                disabled=not can_proceed,
                use_container_width=True,
                key=f"status_update_{bom_id}"
            ):
                _handle_status_update(bom_id, selected_status, bom_info, state, manager)
        
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


def _render_bom_info(bom_info: dict):
    """Render BOM information header"""
    st.markdown("### BOM Information")
    col1, col2 = st.columns(2)
    
    with col1:
        st.write(f"**Code:** {bom_info['bom_code']}")
        st.write(f"**Name:** {bom_info['bom_name']}")
    
    with col2:
        st.write(f"**Type:** {bom_info['bom_type']}")
        product_display = format_product_display(
            code=bom_info.get('product_code', ''),
            name=bom_info.get('product_name', ''),
            package_size=bom_info.get('package_size'),
            brand=bom_info.get('brand'),
            legacy_code=bom_info.get('legacy_code')
        )
        st.write(f"**Product:** {product_display}")


def _format_status_option(status: str, transitions: dict) -> str:
    """Format status option with availability indicator"""
    is_allowed, reason = transitions.get(status, (False, ""))
    
    indicator = create_status_indicator(status)
    
    if is_allowed:
        return f"{indicator}"
    else:
        return f"{indicator} (🚫 Blocked)"


def _render_status_requirements(status: str, bom_info: dict, transitions: dict, manager: BOMManager):
    """Render requirements for selected status"""
    st.markdown("#### Requirements & Impact:")
    
    is_allowed, reason = transitions.get(status, (False, "Unknown"))
    
    total_usage = int(bom_info.get('total_usage', 0))
    active_orders = int(bom_info.get('active_orders', 0))
    completed_orders = total_usage - active_orders
    
    if status == 'ACTIVE':
        st.info("**To activate BOM:**")
        
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
        
        # =====================================================
        # PHASE 1: Check for Multiple Active BOM Conflict
        # =====================================================
        conflict_info = check_active_bom_conflict(
            product_id=bom_info['product_id'],
            exclude_bom_id=bom_info['id']
        )
        
        # Store conflict info in session state for use in action handler
        st.session_state[f"conflict_info_{bom_info['id']}"] = conflict_info
        
        if conflict_info['has_conflict']:
            st.markdown("---")
            _render_conflict_warning(conflict_info, bom_info)
    
    elif status == 'INACTIVE':
        st.info("**To deactivate BOM:**")
        
        no_active_orders = active_orders == 0
        orders_icon = "✅" if no_active_orders else "❌"
        st.write(f"{orders_icon} No active manufacturing orders (Current: {active_orders})")
        
        if active_orders > 0:
            st.warning("⚠️ Complete or cancel all active orders before deactivating BOM")
        
        if completed_orders > 0:
            st.caption(f"ℹ️ This BOM has {completed_orders} completed order(s). Deactivating will prevent new orders but preserve history.")
    
    elif status == 'DRAFT':
        st.info("**To return to DRAFT:**")
        
        no_usage = total_usage == 0
        usage_icon = "✅" if no_usage else "❌"
        st.write(f"{usage_icon} No manufacturing orders created (Current: {total_usage})")
        
        if no_usage:
            st.success("✅ BOM can be returned to DRAFT for full editing")
            st.caption("ℹ️ In DRAFT status, you can modify all BOM information including header, materials, and alternatives.")
        else:
            st.error(f"❌ Cannot return to DRAFT - BOM has been used in {total_usage} order(s)")
            st.caption("💡 Use 'Clone' to create a new editable BOM based on this one instead.")


def _render_conflict_warning(conflict_info: dict, bom_info: dict):
    """Render conflict warning section when activating BOM that would cause multiple active BOMs"""
    conflicting_boms = conflict_info.get('conflicting_boms', [])
    count = conflict_info.get('conflict_count', 0)
    
    st.error(f"⚠️ **Warning: Product Already Has {count} Active BOM(s)!**")
    
    st.markdown(f"**Product:** {bom_info.get('product_code', '')} - {bom_info.get('product_name', '')}")
    
    # Show existing active BOMs
    with st.expander("📋 Current Active BOM(s)", expanded=True):
        for bom in conflicting_boms:
            created_str = ""
            if bom.get('created_date'):
                try:
                    created_str = bom['created_date'].strftime('%d/%m/%Y')
                except:
                    created_str = str(bom['created_date'])[:10]
            
            usage_count = bom.get('usage_count', 0)
            usage_badge = f"🏭 {usage_count} orders" if usage_count > 0 else "No usage"
            
            st.info(
                f"**{bom['bom_code']}** | {bom['bom_name']}\n\n"
                f"Type: {bom['bom_type']} | Created: {created_str} | {usage_badge}"
            )
    
    st.markdown("---")
    st.markdown("**Choose an action:**")
    
    # Conflict resolution options
    conflict_action = st.radio(
        "Conflict Resolution",
        options=['deactivate_old', 'keep_both', 'cancel'],
        format_func=lambda x: {
            'deactivate_old': f'🔄 Deactivate all {count} existing BOM(s) and activate this one (Recommended)',
            'keep_both': '⚠️ Keep all BOMs active (Not recommended - may cause confusion)',
            'cancel': '❌ Cancel - keep current state'
        }.get(x, x),
        key=f"conflict_action_{bom_info['id']}",
        index=0,  # Default to recommended option
        horizontal=False
    )
    
    # Store selection in session state
    st.session_state[f"conflict_action_{bom_info['id']}"] = conflict_action
    
    # Show warning for keep_both option
    if conflict_action == 'keep_both':
        st.warning(
            "⚠️ **Warning:** Having multiple active BOMs for the same product may cause:\n"
            "- Confusion when creating Manufacturing Orders\n"
            "- Inconsistent costing calculations\n"
            "- Difficulty tracking production history\n\n"
            "**Recommended:** Deactivate older BOMs or use during transition periods only."
        )
    elif conflict_action == 'cancel':
        st.info("ℹ️ Click 'Cancel' button below to keep the current state.")


def _handle_status_update(bom_id: int, new_status: str, bom_info: dict,
                         state: StateManager, manager: BOMManager):
    """Handle status update with conflict resolution support"""
    try:
        user_id = st.session_state.get('user_id', 1)
        
        # Final validation
        is_valid, error = validate_status_transition(
            bom_info['status'], 
            new_status, 
            bom_info
        )
        
        if not is_valid:
            st.error(f"❌ {error}")
            return
        
        # =====================================================
        # PHASE 1: Handle Multiple Active BOM Conflict Resolution
        # =====================================================
        conflict_info = st.session_state.get(f"conflict_info_{bom_id}", {})
        conflict_action = st.session_state.get(f"conflict_action_{bom_id}", None)
        
        deactivated_count = 0
        
        if new_status == 'ACTIVE' and conflict_info.get('has_conflict'):
            if conflict_action == 'cancel':
                st.info("ℹ️ Operation cancelled. No changes made.")
                return
            
            if conflict_action == 'deactivate_old':
                # Deactivate all existing active BOMs for this product
                try:
                    deactivated_count = manager.deactivate_boms_for_product(
                        product_id=bom_info['product_id'],
                        exclude_bom_id=bom_id,
                        user_id=user_id
                    )
                    logger.info(f"Deactivated {deactivated_count} existing active BOMs for product {bom_info['product_id']}")
                except Exception as e:
                    logger.error(f"Error deactivating existing BOMs: {e}")
                    st.error(f"❌ Failed to deactivate existing BOMs: {str(e)}")
                    return
        
        # Now update the current BOM status
        manager.update_bom_status(bom_id, new_status, user_id)
        
        state.record_action(
            'status_change',
            bom_id=bom_id,
            bom_code=bom_info['bom_code']
        )
        
        # Clear cache to reflect status change
        state.clear_bom_list_cache()
        
        # Clear conflict session state
        if f"conflict_info_{bom_id}" in st.session_state:
            del st.session_state[f"conflict_info_{bom_id}"]
        if f"conflict_action_{bom_id}" in st.session_state:
            del st.session_state[f"conflict_action_{bom_id}"]
        
        # Build success message
        if deactivated_count > 0:
            state.show_success(
                f"✅ BOM {bom_info['bom_code']} status updated to {new_status}. "
                f"Deactivated {deactivated_count} previous active BOM(s)."
            )
        else:
            state.show_success(
                f"✅ BOM {bom_info['bom_code']} status updated to {new_status}"
            )
        
        state.close_dialog()
        
        st.rerun()
    
    except BOMValidationError as e:
        st.error(f"❌ Validation Error: {str(e)}")
    except BOMException as e:
        st.error(f"❌ Error: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error updating status: {e}")
        st.error(f"❌ Unexpected error: {str(e)}")