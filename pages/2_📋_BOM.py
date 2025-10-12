# pages/2_📋_BOM.py - Complete BOM Management (Refactored)
"""
Bill of Materials (BOM) Management
Clean single-page UI with dialog-driven workflows
"""

import streamlit as st
import pandas as pd
import logging

from utils.auth import AuthManager
from utils.bom.manager import BOMManager
from utils.bom.state import StateManager
from utils.bom.common import (
    create_status_indicator,
    format_number
)

# Import dialogs
from utils.bom.dialogs.create import show_create_dialog
from utils.bom.dialogs.view import show_view_dialog
from utils.bom.dialogs.edit import show_edit_dialog
from utils.bom.dialogs.delete import show_delete_dialog
from utils.bom.dialogs.status import show_status_dialog
from utils.bom.dialogs.where_used import show_where_used_dialog

logger = logging.getLogger(__name__)

# ==================== Page Configuration ====================

st.set_page_config(
    page_title="BOM Management",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ==================== Authentication ====================

auth = AuthManager()
auth.require_auth()

# ==================== Initialize Managers ====================

@st.cache_resource
def get_managers():
    """Initialize and cache managers"""
    return BOMManager(), StateManager()

bom_manager, state = get_managers()

# Initialize state
state.init_state()

# ==================== Main Application ====================

def main():
    """Main application entry point"""
    
    # Header with create button
    render_header()
    
    # Show messages if any
    render_messages()
    
    # Filters and metrics
    render_filters_and_metrics()
    
    # BOM table
    render_bom_table()
    
    # Mount active dialog
    render_active_dialog()
    
    # Footer
    st.markdown("---")
    st.caption("Manufacturing Module v2.0 - BOM Management | Dialog-driven UI")


def render_header():
    """Render page header with create button"""
    col1, col2 = st.columns([3, 1])
    
    with col1:
        st.title("📋 BOM Management")
    
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("➕ Create BOM", type="primary", use_container_width=True):
            state.open_dialog(state.DIALOG_CREATE)
            st.rerun()


def render_messages():
    """Render success/error messages"""
    show_success, show_error, message = state.get_message()
    
    if show_success:
        st.success(message)
        state.clear_messages()
    elif show_error:
        st.error(message)
        state.clear_messages()


def render_filters_and_metrics():
    """Render filters and metrics"""
    st.markdown("### 🔍 Filters")
    
    # Filters
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        filter_type = st.selectbox(
            "BOM Type",
            ["All", "KITTING", "CUTTING", "REPACKING"],
            key="filter_type"
        )
    
    with col2:
        filter_status = st.selectbox(
            "Status",
            ["All", "DRAFT", "ACTIVE", "INACTIVE"],
            key="filter_status"
        )
    
    with col3:
        filter_search = st.text_input(
            "Search",
            placeholder="Code or name...",
            key="filter_search"
        )
    
    with col4:
        st.markdown("<br>", unsafe_allow_html=True)
        search_clicked = st.button("🔍 Search", use_container_width=True)
    
    # Get BOMs with filters
    try:
        boms = bom_manager.get_boms(
            bom_type=filter_type if filter_type != "All" else None,
            status=filter_status if filter_status != "All" else None,
            search=filter_search if filter_search else None
        )
        
        # Store in session for table rendering
        st.session_state['filtered_boms'] = boms
        
        if boms.empty:
            st.info("ℹ️ No BOMs found")
            return
        
        # Metrics
        st.markdown("---")
        st.markdown("### 📊 Summary")
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total", len(boms))
        
        with col2:
            active_count = len(boms[boms['status'] == 'ACTIVE'])
            st.metric("Active", active_count)
        
        with col3:
            draft_count = len(boms[boms['status'] == 'DRAFT'])
            st.metric("Draft", draft_count)
        
        with col4:
            inactive_count = len(boms[boms['status'] == 'INACTIVE'])
            st.metric("Inactive", inactive_count)
    
    except Exception as e:
        logger.error(f"Error loading BOMs: {e}")
        st.error(f"❌ Error loading BOMs: {str(e)}")
        st.session_state['filtered_boms'] = pd.DataFrame()


def render_bom_table():
    """Render BOM table with action buttons"""
    boms = st.session_state.get('filtered_boms', pd.DataFrame())
    
    if boms.empty:
        return
    
    st.markdown("---")
    st.markdown("### 📋 Bill of Materials List")
    
    # Format display
    display_df = boms.copy()
    display_df['status'] = display_df['status'].apply(create_status_indicator)
    display_df['output_qty'] = display_df['output_qty'].apply(
        lambda x: format_number(x, 2)
    )
    
    # Column config
    column_config = {
        "bom_code": st.column_config.TextColumn("BOM Code", width="medium"),
        "bom_name": st.column_config.TextColumn("BOM Name", width="large"),
        "bom_type": st.column_config.TextColumn("Type", width="small"),
        "product_name": st.column_config.TextColumn("Product", width="large"),
        "output_qty": st.column_config.TextColumn("Output Qty", width="small"),
        "uom": st.column_config.TextColumn("UOM", width="small"),
        "status": st.column_config.TextColumn("Status", width="small"),
        "material_count": st.column_config.NumberColumn("Materials", width="small"),
    }
    
    # Selectable dataframe
    event = st.dataframe(
        display_df[[
            'bom_code', 'bom_name', 'bom_type', 'product_name',
            'output_qty', 'uom', 'status', 'material_count'
        ]],
        use_container_width=True,
        hide_index=True,
        column_config=column_config,
        on_select="rerun",
        selection_mode="single-row"
    )
    
    # Handle row selection
    if event.selection.rows:
        selected_idx = event.selection.rows[0]
        selected_bom_id = boms.iloc[selected_idx]['id']
        
        st.markdown("---")
        st.markdown("### 🎯 Actions")
        
        render_action_buttons(selected_bom_id, boms.iloc[selected_idx])


def render_action_buttons(bom_id: int, bom_data: pd.Series):
    """
    Render action buttons for selected BOM
    
    Args:
        bom_id: Selected BOM ID
        bom_data: Selected BOM data
    """
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    
    with col1:
        if st.button("👁️ View", use_container_width=True):
            state.open_dialog(state.DIALOG_VIEW, bom_id)
            st.rerun()
    
    with col2:
        # Edit only for DRAFT
        disabled = bom_data['status'] != 'DRAFT'
        if st.button(
            "✏️ Edit",
            disabled=disabled,
            use_container_width=True,
            help="Only DRAFT BOMs can be edited" if disabled else None
        ):
            state.open_dialog(state.DIALOG_EDIT, bom_id)
            st.rerun()
    
    with col3:
        if st.button("🔄 Status", use_container_width=True):
            state.open_dialog(state.DIALOG_STATUS, bom_id)
            st.rerun()
    
    with col4:
        if st.button("🔍 Where Used", use_container_width=True):
            # Pre-fill product for where used
            state.set_where_used_product(bom_data['product_id'])
            state.open_dialog(state.DIALOG_WHERE_USED)
            st.rerun()
    
    with col5:
        # Delete only non-ACTIVE with no usage
        can_delete = (
            bom_data['status'] != 'ACTIVE' and 
            bom_data.get('usage_count', 0) == 0
        )
        
        if st.button(
            "🗑️ Delete",
            type="secondary",
            disabled=not can_delete,
            use_container_width=True,
            help="Cannot delete ACTIVE BOMs or BOMs in use" if not can_delete else None
        ):
            state.open_dialog(state.DIALOG_DELETE, bom_id)
            st.rerun()
    
    with col6:
        if st.button("📥 Export", use_container_width=True):
            export_bom(bom_id, bom_data)


def export_bom(bom_id: int, bom_data: pd.Series):
    """
    Export BOM to Excel
    
    Args:
        bom_id: BOM ID
        bom_data: BOM data
    """
    try:
        from utils.bom.common import export_to_excel, create_download_button
        
        # Get BOM details
        bom_details = bom_manager.get_bom_details(bom_id)
        
        if bom_details.empty:
            st.warning("⚠️ No materials to export")
            return
        
        # Prepare export data
        export_df = bom_details[[
            'material_name', 'material_code', 'material_type',
            'quantity', 'uom', 'scrap_rate'
        ]].copy()
        
        export_df.columns = [
            'Material Name', 'Code', 'Type',
            'Quantity', 'UOM', 'Scrap Rate (%)'
        ]
        
        # Export
        excel_data = export_to_excel(
            export_df,
            sheet_name=f"BOM_{bom_data['bom_code']}"
        )
        
        # Download button
        create_download_button(
            excel_data,
            filename=f"BOM_{bom_data['bom_code']}.xlsx",
            label=f"📥 Download {bom_data['bom_code']}"
        )
    
    except Exception as e:
        logger.error(f"Error exporting BOM: {e}")
        st.error(f"❌ Export error: {str(e)}")


def render_active_dialog():
    """Mount and render active dialog"""
    dialog_name = state.get_open_dialog()
    
    if not dialog_name:
        return
    
    try:
        if dialog_name == state.DIALOG_CREATE:
            show_create_dialog()
        
        elif dialog_name == state.DIALOG_VIEW:
            bom_id = state.get_current_bom()
            if bom_id:
                show_view_dialog(bom_id)
            else:
                state.close_dialog()
                st.rerun()
        
        elif dialog_name == state.DIALOG_EDIT:
            bom_id = state.get_current_bom()
            if bom_id:
                show_edit_dialog(bom_id)
            else:
                state.close_dialog()
                st.rerun()
        
        elif dialog_name == state.DIALOG_DELETE:
            bom_id = state.get_current_bom()
            if bom_id:
                show_delete_dialog(bom_id)
            else:
                state.close_dialog()
                st.rerun()
        
        elif dialog_name == state.DIALOG_STATUS:
            bom_id = state.get_current_bom()
            if bom_id:
                show_status_dialog(bom_id)
            else:
                state.close_dialog()
                st.rerun()
        
        elif dialog_name == state.DIALOG_WHERE_USED:
            show_where_used_dialog()
    
    except Exception as e:
        logger.error(f"Error rendering dialog {dialog_name}: {e}")
        st.error(f"❌ Dialog error: {str(e)}")
        state.close_dialog()


# ==================== Run Application ====================

if __name__ == "__main__":
    main()