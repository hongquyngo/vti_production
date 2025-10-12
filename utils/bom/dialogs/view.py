# utils/bom/dialogs/view.py
"""
View BOM Details Dialog - FIXED VERSION
Read-only display of BOM information with action buttons
"""

import logging
import streamlit as st
import pandas as pd

from utils.bom.manager import BOMManager, BOMException
from utils.bom.state import StateManager
from utils.bom.common import (
    create_status_indicator,
    format_number,
    render_bom_summary
)

logger = logging.getLogger(__name__)


@st.dialog("📋 BOM Details", width="large")
def show_view_dialog(bom_id: int):
    """
    View BOM details dialog
    
    Args:
        bom_id: BOM ID to view
    """
    state = StateManager()
    manager = BOMManager()
    
    try:
        # Load BOM data
        bom_info = manager.get_bom_info(bom_id)
        bom_details = manager.get_bom_details(bom_id)
        
        if not bom_info:
            st.error("❌ BOM not found")
            if st.button("Close", key=f"view_notfound_close_{bom_id}"):
                st.rerun()
            return
        
        # Action buttons at top
        _render_action_buttons(bom_id, bom_info, state)
        
        st.markdown("---")
        
        # BOM header information
        st.markdown("### 📋 BOM Information")
        render_bom_summary(bom_info)
        
        if bom_info.get('notes'):
            st.markdown("**Notes:**")
            st.info(bom_info['notes'])
        
        st.markdown("---")
        
        # Materials section
        st.markdown("### 🧱 Materials")
        _render_materials_section(bom_details)
        
        st.markdown("---")
        
        # Usage statistics
        st.markdown("### 📊 Usage Statistics")
        _render_usage_stats(bom_info)
        
        st.markdown("---")
        
        # Close button
        if st.button("✔ Close", use_container_width=True, key=f"view_main_close_{bom_id}"):
            state.close_dialog()
            st.rerun()
    
    except Exception as e:
        logger.error(f"Error in view dialog: {e}")
        st.error(f"❌ Error loading BOM details: {str(e)}")
        
        if st.button("Close", key=f"view_error_close_{bom_id}"):
            st.rerun()


def _render_action_buttons(bom_id: int, bom_info: dict, state: StateManager):
    """
    Render action buttons at top of dialog
    
    Args:
        bom_id: BOM ID
        bom_info: BOM information
        state: State manager
    """
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        if st.button("✏️ Edit", use_container_width=True, key=f"view_edit_{bom_id}"):
            state.close_dialog()
            state.open_dialog(state.DIALOG_EDIT, bom_id)
            st.rerun()
    
    with col2:
        if st.button("🔄 Change Status", use_container_width=True, key=f"view_status_{bom_id}"):
            state.close_dialog()
            state.open_dialog(state.DIALOG_STATUS, bom_id)
            st.rerun()
    
    with col3:
        if st.button("🔍 Where Used", use_container_width=True, key=f"view_whereused_{bom_id}"):
            # Pre-fill product for where used search
            state.set_where_used_product(bom_info['product_id'])
            state.close_dialog()
            state.open_dialog(state.DIALOG_WHERE_USED)
            st.rerun()
    
    with col4:
        if st.button("🗑️ Delete", use_container_width=True, type="secondary", key=f"view_delete_{bom_id}"):
            state.close_dialog()
            state.open_dialog(state.DIALOG_DELETE, bom_id)
            st.rerun()


def _render_materials_section(materials: pd.DataFrame):
    """
    Render materials section
    
    Args:
        materials: DataFrame with material details
    """
    if materials.empty:
        st.info("ℹ️ No materials in this BOM")
        return
    
    # Display summary
    st.write(f"**Total Materials:** {len(materials)}")
    
    # Group by material type
    type_counts = materials['material_type'].value_counts()
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        raw_count = type_counts.get('RAW_MATERIAL', 0)
        st.metric("Raw Materials", raw_count)
    
    with col2:
        pack_count = type_counts.get('PACKAGING', 0)
        st.metric("Packaging", pack_count)
    
    with col3:
        cons_count = type_counts.get('CONSUMABLE', 0)
        st.metric("Consumables", cons_count)
    
    st.markdown("---")
    
    # Display materials table
    display_df = materials[[
        'material_name', 'material_code', 'material_type',
        'quantity', 'uom', 'scrap_rate', 'current_stock'
    ]].copy()
    
    # Format columns
    display_df['quantity'] = display_df['quantity'].apply(
        lambda x: format_number(x, 4)
    )
    display_df['scrap_rate'] = display_df['scrap_rate'].apply(
        lambda x: f"{format_number(x, 2)}%"
    )
    display_df['current_stock'] = display_df['current_stock'].apply(
        lambda x: format_number(x, 2)
    )
    
    # Rename columns for display
    display_df.columns = [
        'Material Name', 'Code', 'Type', 
        'Quantity', 'UOM', 'Scrap %', 'Stock'
    ]
    
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True
    )
    
    # Highlight materials with low/no stock
    low_stock = materials[materials['current_stock'] <= 0]
    if not low_stock.empty:
        st.warning(f"⚠️ {len(low_stock)} material(s) have no stock available")


def _render_usage_stats(bom_info: dict):
    """
    Render usage statistics
    
    Args:
        bom_info: BOM information dictionary
    """
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(
            "Total Usage",
            bom_info.get('total_usage', 0),
            help="Total number of manufacturing orders using this BOM"
        )
    
    with col2:
        st.metric(
            "Active Orders",
            bom_info.get('active_orders', 0),
            help="Number of active manufacturing orders"
        )
    
    with col3:
        version = bom_info.get('version', 1)
        st.metric("Version", version)
    
    with col4:
        material_count = bom_info.get('material_count', 0)
        st.metric("Materials", material_count)
    
    # Additional info
    if bom_info.get('effective_date'):
        st.info(f"ℹ️ Effective from: {bom_info['effective_date']}")
    
    # Show restrictions if has active orders
    if bom_info.get('active_orders', 0) > 0:
        st.warning(
            "⚠️ This BOM has active manufacturing orders. "
            "Editing is restricted to prevent data inconsistency."
        )