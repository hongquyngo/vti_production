# utils/bom/dialogs/edit.py
"""
Edit BOM Dialog with Material Alternatives Support
Tabbed editor: BOM Info / Materials (with alternatives)
Only DRAFT BOMs can be edited
"""

import logging
import streamlit as st
import pandas as pd
from datetime import date

from utils.bom.manager import BOMManager, BOMException, BOMValidationError, BOMNotFoundError
from utils.bom.state import StateManager
from utils.bom.common import (
    get_products,
    get_product_by_id,
    validate_quantity,
    validate_percentage
)

logger = logging.getLogger(__name__)


@st.dialog("✏️ Edit BOM", width="large")
def show_edit_dialog(bom_id: int):
    """Edit BOM dialog (DRAFT only)"""
    state = StateManager()
    manager = BOMManager()
    
    try:
        bom_info = manager.get_bom_info(bom_id)
        bom_details = manager.get_bom_details(bom_id)
        
        if not bom_info:
            st.error("❌ BOM not found")
            if st.button("Close", key=f"edit_notfound_close_{bom_id}"):
                state.close_dialog()
                st.rerun()
            return
        
        if bom_info['status'] != 'DRAFT':
            st.error(f"❌ Only DRAFT BOMs can be edited. Current status: {bom_info['status']}")
            st.info("💡 Change status to DRAFT first if you need to edit.")
            
            if st.button("Close", use_container_width=True, key=f"edit_nondraft_close_{bom_id}"):
                state.close_dialog()
                st.rerun()
            return
        
        st.markdown(f"### Editing: {bom_info['bom_code']} - {bom_info['bom_name']}")
        
        tab1, tab2 = st.tabs(["📄 BOM Information", "🧱 Materials"])
        
        with tab1:
            _render_info_tab(bom_id, bom_info, state, manager)
        
        with tab2:
            _render_materials_tab(bom_id, bom_details, state, manager)
    
    except Exception as e:
        logger.error(f"Error in edit dialog: {e}")
        st.error(f"❌ Error: {str(e)}")
        
        if st.button("Close", key=f"edit_exception_close_{bom_id}"):
            state.close_dialog()
            st.rerun()


def _render_info_tab(bom_id: int, bom_info: dict, state: StateManager, manager: BOMManager):
    """Render BOM information tab"""
    st.markdown("### Edit BOM Information")
    
    col1, col2 = st.columns(2)
    
    with col1:
        new_name = st.text_input(
            "BOM Name *",
            value=bom_info['bom_name'],
            key=f"edit_name_{bom_id}"
        )
        
        new_output_qty = st.number_input(
            "Output Quantity *",
            min_value=0.01,
            value=float(bom_info['output_qty']),
            step=1.0,
            format="%.2f",
            key=f"edit_qty_{bom_id}"
        )
    
    with col2:
        new_effective_date = st.date_input(
            "Effective Date",
            value=bom_info.get('effective_date', date.today()),
            key=f"edit_date_{bom_id}"
        )
        
        st.text_input(
            "UOM",
            value=bom_info['uom'],
            disabled=True,
            key=f"edit_uom_{bom_id}"
        )
    
    new_notes = st.text_area(
        "Notes",
        value=bom_info.get('notes', ''),
        height=100,
        key=f"edit_notes_{bom_id}"
    )
    
    st.markdown("---")
    
    col1, col2 = st.columns([3, 1])
    
    with col2:
        if st.button("💾 Save Changes", type="primary", use_container_width=True, key=f"edit_info_save_{bom_id}"):
            _handle_update_header(
                bom_id, new_name, new_output_qty, 
                new_effective_date, new_notes,
                state, manager
            )
    
    with col1:
        if st.button("✔ Close", use_container_width=True, key=f"edit_info_close_{bom_id}"):
            state.close_dialog()
            st.rerun()


def _render_materials_tab(bom_id: int, materials: pd.DataFrame, 
                         state: StateManager, manager: BOMManager):
    """Render materials tab with alternatives management"""
    st.markdown("### Edit Materials")
    
    if not materials.empty:
        st.markdown(f"**Current Materials ({len(materials)}):**")
        
        for idx, material in materials.iterrows():
            _render_material_section(bom_id, idx, material, state, manager)
        
        st.markdown("---")
    else:
        st.info("ℹ️ No materials in this BOM")
    
    _render_add_material_section(bom_id, materials, state, manager)
    
    st.markdown("---")
    
    if st.button("✔ Close", use_container_width=True, key=f"edit_materials_close_{bom_id}"):
        state.close_dialog()
        st.rerun()


def _render_material_section(bom_id: int, idx: int, material: pd.Series, 
                             state: StateManager, manager: BOMManager):
    """Render material with alternatives in expandable section"""
    mat_id = material['material_id']
    detail_id = material['id']
    alt_count = int(material.get('alternatives_count', 0))
    
    # Material header
    with st.container():
        col1, col2, col3, col4, col5, col6 = st.columns([3, 1, 1, 1, 1, 1])
        
        with col1:
            st.markdown(f"**{material['material_name']}** ({material['material_code']})")
        
        with col2:
            st.text(material['material_type'])
        
        with col3:
            new_qty = st.number_input(
                "Qty",
                min_value=0.0001,
                value=float(material['quantity']),
                step=0.1,
                format="%.4f",
                key=f"mat_qty_{bom_id}_{mat_id}_{idx}",
                label_visibility="collapsed"
            )
        
        with col4:
            st.text(material['uom'])
        
        with col5:
            new_scrap = st.number_input(
                "Scrap %",
                min_value=0.0,
                max_value=100.0,
                value=float(material['scrap_rate']),
                step=0.5,
                key=f"mat_scrap_{bom_id}_{mat_id}_{idx}",
                label_visibility="collapsed"
            )
        
        with col6:
            col_save, col_delete = st.columns(2)
            
            with col_save:
                qty_changed = abs(new_qty - float(material['quantity'])) > 0.0001
                scrap_changed = abs(new_scrap - float(material['scrap_rate'])) > 0.01
                
                if qty_changed or scrap_changed:
                    if st.button("💾", key=f"save_{bom_id}_{mat_id}_{idx}", help="Save changes"):
                        _handle_update_material(bom_id, mat_id, new_qty, new_scrap, state, manager)
            
            with col_delete:
                if st.button("🗑️", key=f"del_{bom_id}_{mat_id}_{idx}", help="Delete material"):
                    _handle_delete_material(bom_id, mat_id, state, manager)
    
    # Alternatives section
    with st.expander(f"🔀 Alternatives ({alt_count})", expanded=False):
        _render_alternatives_section(bom_id, detail_id, mat_id, manager)
    
    st.markdown("---")


def _render_alternatives_section(bom_id: int, detail_id: int, primary_mat_id: int, manager: BOMManager):
    """Render alternatives for a material"""
    try:
        alternatives = manager.get_material_alternatives(detail_id)
        
        if not alternatives.empty:
            st.markdown("**Current Alternatives (by priority):**")
            
            for idx, alt in alternatives.iterrows():
                _render_alternative_row(bom_id, detail_id, idx, alt, manager)
        else:
            st.info("ℹ️ No alternatives defined")
        
        st.markdown("---")
        _render_add_alternative_form(bom_id, detail_id, primary_mat_id, alternatives, manager)
    
    except Exception as e:
        logger.error(f"Error rendering alternatives: {e}")
        st.error(f"❌ Error loading alternatives: {str(e)}")


def _render_alternative_row(bom_id: int, detail_id: int, idx: int, alt: pd.Series, manager: BOMManager):
    """Render single alternative row"""
    alt_id = alt['id']
    
    with st.container():
        col1, col2, col3, col4, col5, col6, col7 = st.columns([2, 1, 1, 1, 1, 1, 1])
        
        with col1:
            status_icon = "✅" if alt['is_active'] else "⭕"
            st.text(f"{status_icon} {alt['material_name']} ({alt['material_code']})")
        
        with col2:
            new_qty = st.number_input(
                "Alt Qty",
                min_value=0.0001,
                value=float(alt['quantity']),
                step=0.1,
                format="%.4f",
                key=f"alt_qty_{bom_id}_{alt_id}_{idx}",
                label_visibility="collapsed"
            )
        
        with col3:
            st.text(alt['uom'])
        
        with col4:
            new_scrap = st.number_input(
                "Scrap",
                min_value=0.0,
                max_value=100.0,
                value=float(alt['scrap_rate']),
                step=0.5,
                key=f"alt_scrap_{bom_id}_{alt_id}_{idx}",
                label_visibility="collapsed"
            )
        
        with col5:
            new_priority = st.number_input(
                "Priority",
                min_value=1,
                max_value=99,
                value=int(alt['priority']),
                key=f"alt_priority_{bom_id}_{alt_id}_{idx}",
                label_visibility="collapsed"
            )
        
        with col6:
            new_active = st.checkbox(
                "Active",
                value=bool(alt['is_active']),
                key=f"alt_active_{bom_id}_{alt_id}_{idx}",
                label_visibility="collapsed"
            )
        
        with col7:
            col_save, col_del = st.columns(2)
            
            with col_save:
                qty_changed = abs(new_qty - float(alt['quantity'])) > 0.0001
                scrap_changed = abs(new_scrap - float(alt['scrap_rate'])) > 0.01
                priority_changed = new_priority != int(alt['priority'])
                active_changed = new_active != bool(alt['is_active'])
                
                if qty_changed or scrap_changed or priority_changed or active_changed:
                    if st.button("💾", key=f"save_alt_{bom_id}_{alt_id}_{idx}", help="Save"):
                        _handle_update_alternative(
                            alt_id, new_qty, new_scrap, new_priority, new_active, manager
                        )
            
            with col_del:
                if st.button("🗑️", key=f"del_alt_{bom_id}_{alt_id}_{idx}", help="Delete"):
                    _handle_delete_alternative(alt_id, manager)


def _render_add_alternative_form(bom_id: int, detail_id: int, primary_mat_id: int, 
                                 current_alts: pd.DataFrame, manager: BOMManager):
    """Render add alternative form"""
    st.markdown("**Add Alternative Material:**")
    
    col1, col2, col3, col4, col5 = st.columns([2, 1, 1, 1, 1])
    
    with col1:
        products = get_products()
        
        # Exclude primary material and existing alternatives
        exclude_ids = [primary_mat_id]
        if not current_alts.empty:
            exclude_ids.extend(current_alts['alternative_material_id'].tolist())
        
        available = products[~products['id'].isin(exclude_ids)]
        
        if available.empty:
            st.warning("⚠️ No materials available as alternatives")
            return
        
        product_options = {
            f"{row['name']} ({row['code']})": row['id']
            for _, row in available.iterrows()
        }
        
        selected = st.selectbox(
            "Material",
            options=list(product_options.keys()),
            key=f"add_alt_mat_{bom_id}_{detail_id}",
            label_visibility="collapsed"
        )
        
        alt_material_id = product_options.get(selected)
    
    with col2:
        quantity = st.number_input(
            "Quantity",
            min_value=0.0001,
            value=1.0,
            step=0.1,
            format="%.4f",
            key=f"add_alt_qty_{bom_id}_{detail_id}",
            label_visibility="collapsed"
        )
    
    with col3:
        if alt_material_id:
            product = get_product_by_id(alt_material_id)
            alt_uom = product['uom'] if product else 'PCS'
        else:
            alt_uom = 'PCS'
        st.text_input("UOM", value=alt_uom, disabled=True, 
                     key=f"add_alt_uom_{bom_id}_{detail_id}", label_visibility="collapsed")
    
    with col4:
        scrap = st.number_input(
            "Scrap %",
            min_value=0.0,
            max_value=100.0,
            value=0.0,
            step=0.5,
            key=f"add_alt_scrap_{bom_id}_{detail_id}",
            label_visibility="collapsed"
        )
    
    with col5:
        # Auto-calculate next priority
        next_priority = 1
        if not current_alts.empty:
            next_priority = int(current_alts['priority'].max()) + 1
        
        priority = st.number_input(
            "Priority",
            min_value=1,
            max_value=99,
            value=next_priority,
            key=f"add_alt_priority_{bom_id}_{detail_id}",
            label_visibility="collapsed"
        )
    
    if st.button("➕ Add Alternative", key=f"add_alt_btn_{bom_id}_{detail_id}", use_container_width=True):
        if not validate_quantity(quantity):
            st.error("❌ Invalid quantity")
            return
        
        if not validate_percentage(scrap):
            st.error("❌ Invalid scrap rate (0-100%)")
            return
        
        _handle_add_alternative(
            detail_id, alt_material_id, quantity, alt_uom, scrap, priority, manager
        )


def _render_add_material_section(bom_id: int, current_materials: pd.DataFrame,
                                 state: StateManager, manager: BOMManager):
    """Render add material section"""
    st.markdown("**Add New Material:**")
    
    col1, col2, col3, col4, col5 = st.columns([3, 2, 1, 1, 1])
    
    with col1:
        st.markdown("**Material**")
    with col2:
        st.markdown("**Type**")
    with col3:
        st.markdown("**Quantity**")
    with col4:
        st.markdown("**UOM**")
    with col5:
        st.markdown("**Scrap %**")
    
    col1, col2, col3, col4, col5 = st.columns([3, 2, 1, 1, 1])
    
    with col1:
        products = get_products()
        
        if products.empty:
            st.error("❌ No products available")
            return
        
        product_options = {
            f"{row['name']} ({row['code']})": row['id']
            for _, row in products.iterrows()
        }
        
        selected = st.selectbox(
            "Material",
            options=list(product_options.keys()),
            key=f"edit_add_mat_{bom_id}",
            label_visibility="collapsed"
        )
        
        material_id = product_options.get(selected)
    
    with col2:
        material_type = st.selectbox(
            "Type",
            options=["RAW_MATERIAL", "PACKAGING", "CONSUMABLE"],
            key=f"edit_add_type_{bom_id}",
            label_visibility="collapsed"
        )
    
    with col3:
        quantity = st.number_input(
            "Quantity",
            min_value=0.0001,
            value=1.0,
            step=0.1,
            format="%.4f",
            key=f"edit_add_qty_{bom_id}",
            label_visibility="collapsed"
        )
    
    with col4:
        if material_id:
            product = get_product_by_id(material_id)
            mat_uom = product['uom'] if product else 'PCS'
        else:
            mat_uom = 'PCS'
        st.text_input("UOM", value=mat_uom, disabled=True, 
                     key=f"edit_add_uom_{bom_id}", label_visibility="collapsed")
    
    with col5:
        scrap = st.number_input(
            "Scrap Rate (%)",
            min_value=0.0,
            max_value=100.0,
            value=0.0,
            step=0.5,
            key=f"edit_add_scrap_{bom_id}",
            label_visibility="collapsed"
        )
    
    if st.button("➕ Add Material", key=f"edit_add_btn_{bom_id}", use_container_width=True):
        if not current_materials.empty:
            if material_id in current_materials['material_id'].values:
                st.error("❌ Material already exists in BOM")
                return
        
        if not validate_quantity(quantity):
            st.error("❌ Invalid quantity (must be > 0)")
            return
        
        if not validate_percentage(scrap):
            st.error("❌ Invalid scrap rate (must be 0-100%)")
            return
        
        _handle_add_material(bom_id, material_id, material_type, quantity, mat_uom, scrap, state, manager)


# ==================== Event Handlers ====================

def _handle_update_header(bom_id: int, name: str, qty: float, 
                          eff_date: date, notes: str,
                          state: StateManager, manager: BOMManager):
    """Handle header update"""
    try:
        user_id = st.session_state.get('user_id', 1)
        
        updates = {
            'bom_name': name,
            'output_qty': qty,
            'effective_date': eff_date,
            'notes': notes,
            'updated_by': user_id
        }
        
        manager.update_bom_header(bom_id, updates)
        
        st.success("✅ BOM information updated!")
        state.mark_unsaved_changes(False)
        st.rerun()
    
    except BOMException as e:
        st.error(f"❌ Error: {str(e)}")


def _handle_update_material(bom_id: int, material_id: int, 
                           qty: float, scrap: float,
                           state: StateManager, manager: BOMManager):
    """Handle material update"""
    try:
        updates = {'quantity': qty, 'scrap_rate': scrap}
        manager.update_material(bom_id, material_id, updates)
        
        st.success("✅ Material updated!")
        st.rerun()
    
    except BOMException as e:
        st.error(f"❌ Error: {str(e)}")


def _handle_delete_material(bom_id: int, material_id: int,
                           state: StateManager, manager: BOMManager):
    """Handle material deletion"""
    try:
        manager.remove_material(bom_id, material_id)
        
        st.success("✅ Material removed!")
        st.rerun()
    
    except BOMException as e:
        st.error(f"❌ Error: {str(e)}")


def _handle_add_material(bom_id: int, material_id: int, material_type: str,
                        qty: float, uom: str, scrap: float,
                        state: StateManager, manager: BOMManager):
    """Handle add material"""
    try:
        materials = [{
            'material_id': material_id,
            'material_type': material_type,
            'quantity': qty,
            'uom': uom,
            'scrap_rate': scrap
        }]
        
        manager.add_materials(bom_id, materials)
        
        st.success("✅ Material added!")
        st.rerun()
    
    except BOMException as e:
        st.error(f"❌ Error: {str(e)}")


def _handle_add_alternative(detail_id: int, alt_material_id: int, 
                           qty: float, uom: str, scrap: float, priority: int,
                           manager: BOMManager):
    """Handle add alternative"""
    try:
        alternative_data = {
            'alternative_material_id': alt_material_id,
            'quantity': qty,
            'uom': uom,
            'scrap_rate': scrap,
            'priority': priority,
            'is_active': 1
        }
        
        manager.add_alternative(detail_id, alternative_data)
        
        st.success("✅ Alternative added!")
        st.rerun()
    
    except BOMException as e:
        st.error(f"❌ Error: {str(e)}")


def _handle_update_alternative(alt_id: int, qty: float, scrap: float, 
                               priority: int, is_active: bool, manager: BOMManager):
    """Handle update alternative"""
    try:
        updates = {
            'quantity': qty,
            'scrap_rate': scrap,
            'priority': priority,
            'is_active': 1 if is_active else 0
        }
        
        manager.update_alternative(alt_id, updates)
        
        st.success("✅ Alternative updated!")
        st.rerun()
    
    except BOMException as e:
        st.error(f"❌ Error: {str(e)}")


def _handle_delete_alternative(alt_id: int, manager: BOMManager):
    """Handle delete alternative"""
    try:
        manager.remove_alternative(alt_id)
        
        st.success("✅ Alternative removed!")
        st.rerun()
    
    except BOMException as e:
        st.error(f"❌ Error: {str(e)}")