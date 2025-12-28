# utils/bom/dialogs/view.py
"""
View BOM Details Dialog with Alternatives Display - VERSION 2.3
Read-only display of BOM information with alternatives

Changes in v2.3:
- Updated product/material display to unified format with legacy_code

Changes in v2.2:
- Added duplicate materials warning section
- Shows detailed info about which materials are duplicated

Changes in v2.1:
- Added Export button in action buttons
"""

import logging
import streamlit as st
import pandas as pd

from utils.bom.manager import BOMManager, BOMException
from utils.bom.state import StateManager
from utils.bom.common import (
    create_status_indicator,
    format_number,
    format_product_display,
    render_bom_summary,
    # Duplicate detection
    detect_duplicate_materials_in_bom,
    render_duplicate_warning_section
)

logger = logging.getLogger(__name__)


@st.dialog("📋 BOM Details", width="large")
def show_view_dialog(bom_id: int):
    """View BOM details dialog"""
    state = StateManager()
    manager = BOMManager()
    
    try:
        bom_info = manager.get_bom_info(bom_id)
        bom_details = manager.get_bom_details(bom_id)
        
        if not bom_info:
            st.error("❌ BOM not found")
            if st.button("Close", key=f"view_notfound_close_{bom_id}"):
                st.rerun()
            return
        
        _render_action_buttons(bom_id, bom_info, state)
        
        st.markdown("---")
        
        # Check for duplicate materials and show warning
        duplicate_info = detect_duplicate_materials_in_bom(bom_id)
        if duplicate_info.get('has_duplicates'):
            render_duplicate_warning_section(duplicate_info)
            st.markdown("---")
        
        st.markdown("### 📋 BOM Information")
        render_bom_summary(bom_info)
        
        if bom_info.get('notes'):
            st.markdown("**Notes:**")
            st.info(bom_info['notes'])
        
        st.markdown("---")
        
        st.markdown("### 🧱 Materials")
        _render_materials_section(bom_details, manager)
        
        st.markdown("---")
        
        st.markdown("### 📊 Usage Statistics")
        _render_usage_stats(bom_info)
        
        st.markdown("---")
        
        if st.button("✔ Close", use_container_width=True, key=f"view_main_close_{bom_id}"):
            state.close_dialog()
            st.rerun()
    
    except Exception as e:
        logger.error(f"Error in view dialog: {e}")
        st.error(f"❌ Error loading BOM details: {str(e)}")
        
        if st.button("Close", key=f"view_error_close_{bom_id}"):
            st.rerun()


def _render_action_buttons(bom_id: int, bom_info: dict, state: StateManager):
    """Render action buttons at top of dialog"""
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        if st.button("✏️ Edit", use_container_width=True, key=f"view_edit_{bom_id}"):
            state.close_dialog()
            state.open_dialog(state.DIALOG_EDIT, bom_id)
            st.rerun()
    
    with col2:
        if st.button("🔄 Clone", use_container_width=True, key=f"view_clone_{bom_id}"):
            state.close_dialog()
            state.open_dialog(state.DIALOG_CLONE, bom_id)
            st.rerun()
    
    with col3:
        if st.button("📥 Export", use_container_width=True, key=f"view_export_{bom_id}"):
            state.close_dialog()
            state.open_dialog(state.DIALOG_EXPORT, bom_id)
            st.rerun()
    
    with col4:
        if st.button("📊 Status", use_container_width=True, key=f"view_status_{bom_id}"):
            state.close_dialog()
            state.open_dialog(state.DIALOG_STATUS, bom_id)
            st.rerun()
    
    with col5:
        if st.button("🔍 Where Used", use_container_width=True, key=f"view_whereused_{bom_id}"):
            state.set_where_used_product(bom_info['product_id'])
            state.close_dialog()
            state.open_dialog(state.DIALOG_WHERE_USED)
            st.rerun()


def _render_materials_section(materials: pd.DataFrame, manager: BOMManager):
    """Render materials section with alternatives"""
    if materials.empty:
        st.info("ℹ️ No materials in this BOM")
        return
    
    st.write(f"**Total Materials:** {len(materials)}")
    
    # Summary by type
    type_counts = materials['material_type'].value_counts()
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        raw_count = type_counts.get('RAW_MATERIAL', 0)
        st.metric("Raw Materials", raw_count)
    
    with col2:
        pack_count = type_counts.get('PACKAGING', 0)
        st.metric("Packaging", pack_count)
    
    with col3:
        cons_count = type_counts.get('CONSUMABLE', 0)
        st.metric("Consumables", cons_count)
    
    with col4:
        total_alts = int(materials['alternatives_count'].sum())
        st.metric("Total Alternatives", total_alts)
    
    st.markdown("---")
    
    # Column headers for materials
    col1, col2, col3, col4, col5, col6 = st.columns([3, 1, 1, 1, 1, 1])
    with col1:
        st.markdown("**Material (Code)**")
    with col2:
        st.markdown("**Type**")
    with col3:
        st.markdown("**Quantity**")
    with col4:
        st.markdown("**UOM**")
    with col5:
        st.markdown("**Scrap %**")
    with col6:
        st.markdown("**Stock**")
    
    st.markdown("---")
    
    # Display materials with alternatives
    for idx, material in materials.iterrows():
        _render_material_with_alternatives(material, manager)


def _render_material_with_alternatives(material: pd.Series, manager: BOMManager):
    """Render single material with its alternatives"""
    alt_count = int(material.get('alternatives_count', 0))
    
    # Primary material
    with st.container():
        col1, col2, col3, col4, col5, col6 = st.columns([3, 1, 1, 1, 1, 1])
        
        with col1:
            alt_badge = f" 🔀 **{alt_count} alt(s)**" if alt_count > 0 else ""
            mat_display = format_product_display(
                code=material.get('material_code', ''),
                name=material.get('material_name', ''),
                package_size=material.get('package_size'),
                brand=material.get('brand'),
                legacy_code=material.get('legacy_code')
            )
            st.markdown(f"**{mat_display}**{alt_badge}")
        
        with col2:
            st.text(material['material_type'])
        
        with col3:
            st.text(f"{format_number(material['quantity'], 4)}")
        
        with col4:
            st.text(material['uom'])
        
        with col5:
            st.text(f"{format_number(material['scrap_rate'], 2)}%")
        
        with col6:
            stock_val = float(material['current_stock'])
            if stock_val > 0:
                st.success(f"✅ {format_number(stock_val, 2)}")
            else:
                st.error("❌ No stock")
    
    # Show alternatives if any
    if alt_count > 0:
        with st.expander(f"   ↳ View {alt_count} Alternative(s)", expanded=False):
            _render_alternatives_list(material['id'], manager)
    
    st.markdown("")


def _render_alternatives_list(detail_id: int, manager: BOMManager):
    """Render alternatives list for a material"""
    try:
        alternatives = manager.get_material_alternatives(detail_id)
        
        if alternatives.empty:
            st.info("ℹ️ No alternatives")
            return
        
        st.markdown("**Alternatives (by priority):**")
        
        # Column headers for alternatives
        col1, col2, col3, col4, col5, col6 = st.columns([3, 1, 1, 1, 1, 1])
        with col1:
            st.markdown("_Status: Material (Code)_")
        with col2:
            st.markdown("_Type_")
        with col3:
            st.markdown("_Quantity_")
        with col4:
            st.markdown("_UOM_")
        with col5:
            st.markdown("_Scrap %_")
        with col6:
            st.markdown("_Priority | Stock_")
        
        st.markdown("")
        
        for idx, alt in alternatives.iterrows():
            col1, col2, col3, col4, col5, col6 = st.columns([3, 1, 1, 1, 1, 1])
            
            with col1:
                status = "✅ Active" if alt['is_active'] else "⭕ Inactive"
                alt_display = format_product_display(
                    code=alt.get('material_code', ''),
                    name=alt.get('material_name', ''),
                    package_size=alt.get('package_size'),
                    brand=alt.get('brand'),
                    legacy_code=alt.get('legacy_code')
                )
                st.text(f"  {status}: {alt_display}")
            
            with col2:
                st.text(alt['material_type'])
            
            with col3:
                st.text(f"{format_number(alt['quantity'], 4)}")
            
            with col4:
                st.text(alt['uom'])
            
            with col5:
                st.text(f"{format_number(alt['scrap_rate'], 2)}%")
            
            with col6:
                priority_color = "🟢" if alt['priority'] == 1 else "🟡" if alt['priority'] == 2 else "⚪"
                stock_val = float(alt['current_stock'])
                st.text(f"{priority_color} P{alt['priority']} | {format_number(stock_val, 0)}")
            
            if alt.get('notes'):
                st.caption(f"      Note: {alt['notes']}")
    
    except Exception as e:
        logger.error(f"Error rendering alternatives: {e}")
        st.error(f"❌ Error loading alternatives: {str(e)}")


def _render_usage_stats(bom_info: dict):
    """Render usage statistics"""
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
    
    if bom_info.get('effective_date'):
        st.info(f"ℹ️ Effective from: {bom_info['effective_date']}")
    
    if bom_info.get('active_orders', 0) > 0:
        st.warning(
            "⚠️ This BOM has active manufacturing orders. "
            "Editing is restricted to prevent data inconsistency."
        )