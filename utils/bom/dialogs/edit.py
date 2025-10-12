# utils/bom/dialogs/edit.py
"""
Edit BOM Dialog - FIXED BUTTON KEYS
Tabbed editor: BOM Info / Materials
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
    """
    Edit BOM dialog (DRAFT only)
    
    Args:
        bom_id: BOM ID to edit
    """
    state = StateManager()
    manager = BOMManager()
    
    try:
        # Load BOM data
        bom_info = manager.get_bom_info(bom_id)
        bom_details = manager.get_bom_details(bom_id)
        
        if not bom_info:
            st.error("❌ BOM not found")
            if st.button("Close", key=f"edit_notfound_close_{bom_id}"):
                state.close_dialog()
                st.rerun()
            return
        
        # Check if editable
        if bom_info['status'] != 'DRAFT':
            st.error(f"❌ Only DRAFT BOMs can be edited. Current status: {bom_info['status']}")
            st.info("💡 Change status to DRAFT first if you need to edit.")
            
            if st.button("Close", use_container_width=True, key=f"edit_nondraft_close_{bom_id}"):
                state.close_dialog()
                st.rerun()
            return
        
        # Show BOM info
        st.markdown(f"### Editing: {bom_info['bom_code']} - {bom_info['bom_name']}")
        
        # Tabs
        current_tab = state.get_edit_tab()
        
        tab1, tab2 = st.tabs(["📄 BOM Information", "🧱 Materials"])
        
        with tab1:
            if current_tab != 'info':
                state.set_edit_tab('info')
            _render_info_tab(bom_id, bom_info, state, manager)
        
        with tab2:
            if current_tab != 'materials':
                state.set_edit_tab('materials')
            _render_materials_tab(bom_id, bom_details, state, manager)
    
    except Exception as e:
        logger.error(f"Error in edit dialog: {e}")
        st.error(f"❌ Error: {str(e)}")
        
        if st.button("Close", key=f"edit_exception_close_{bom_id}"):
            state.close_dialog()
            st.rerun()


def _render_info_tab(bom_id: int, bom_info: dict, state: StateManager, manager: BOMManager):
    """
    Render BOM information tab
    
    Args:
        bom_id: BOM ID
        bom_info: BOM information
        state: State manager
        manager: BOM manager
    """
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
    
    # Save button
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
    """
    Render materials tab with inline editing
    
    Args:
        bom_id: BOM ID
        materials: Materials DataFrame
        state: State manager
        manager: BOM manager
    """
    st.markdown("### Edit Materials")
    
    # Current materials
    if not materials.empty:
        st.markdown(f"**Current Materials ({len(materials)}):**")
        
        for idx, material in materials.iterrows():
            _render_material_row(bom_id, idx, material, state, manager)
        
        st.markdown("---")
    else:
        st.info("ℹ️ No materials in this BOM")
    
    # Add new material
    _render_add_material_section(bom_id, materials, state, manager)
    
    st.markdown("---")
    
    # Close button
    if st.button("✔ Close", use_container_width=True, key=f"edit_materials_close_{bom_id}"):
        state.close_dialog()
        st.rerun()


def _render_material_row(bom_id: int, idx: int, material: pd.Series, 
                         state: StateManager, manager: BOMManager):
    """
    Render single material row with inline edit
    
    Args:
        bom_id: BOM ID
        idx: Row index
        material: Material data
        state: State manager
        manager: BOM manager
    """
    mat_id = material['material_id']
    
    # ✅ Show header for first row only
    if idx == 0:
        col1, col2, col3, col4, col5, col6 = st.columns([3, 1, 1, 1, 1, 1])
        
        with col1:
            st.markdown("**Material Name**")
        with col2:
            st.markdown("**Type**")
        with col3:
            st.markdown("**Quantity**")
        with col4:
            st.markdown("**UOM**")
        with col5:
            st.markdown("**Scrap %**")
        with col6:
            st.markdown("**Actions**")
    
    # Data row
    with st.container():
        col1, col2, col3, col4, col5, col6 = st.columns([3, 1, 1, 1, 1, 1])
        
        with col1:
            st.text(f"{material['material_name']} ({material['material_code']})")
        
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
                label_visibility="collapsed",
                help="Quantity per output unit"
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
                label_visibility="collapsed",
                help="Expected waste percentage"
            )
        
        with col6:
            col_save, col_delete = st.columns(2)
            
            with col_save:
                # Only show save if changed
                qty_changed = abs(new_qty - float(material['quantity'])) > 0.0001
                scrap_changed = abs(new_scrap - float(material['scrap_rate'])) > 0.01
                
                if qty_changed or scrap_changed:
                    if st.button("💾", key=f"save_{bom_id}_{mat_id}_{idx}", help="Save changes"):
                        _handle_update_material(
                            bom_id, mat_id, new_qty, new_scrap,
                            state, manager
                        )
            
            with col_delete:
                if st.button("🗑️", key=f"del_{bom_id}_{mat_id}_{idx}", help="Delete material"):
                    _handle_delete_material(bom_id, mat_id, state, manager)
        
        st.markdown("---")

def _render_add_material_section(bom_id: int, current_materials: pd.DataFrame,
                                 state: StateManager, manager: BOMManager):
    """
    Render add material section with clear labels
    
    Args:
        bom_id: BOM ID
        current_materials: Current materials DataFrame
        state: State manager
        manager: BOM manager
    """
    st.markdown("**Add New Material:**")
    
    # ✅ ADD HEADER ROW
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
    
    # Input row
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
            label_visibility="collapsed",
            help="Select material to add to BOM"
        )
        
        material_id = product_options.get(selected)
    
    with col2:
        material_type = st.selectbox(
            "Type",
            options=["RAW_MATERIAL", "PACKAGING", "CONSUMABLE"],
            key=f"edit_add_type_{bom_id}",
            label_visibility="collapsed",
            help="Material type classification"
        )
    
    with col3:
        quantity = st.number_input(
            "Quantity",
            min_value=0.0001,
            value=1.0,
            step=0.1,
            format="%.4f",
            key=f"edit_add_qty_{bom_id}",
            label_visibility="collapsed",
            help="Quantity required"
        )
    
    with col4:
        if material_id:
            product = get_product_by_id(material_id)
            mat_uom = product['uom'] if product else 'PCS'
        else:
            mat_uom = 'PCS'
        st.text_input(
            "UOM", 
            value=mat_uom, 
            disabled=True, 
            key=f"edit_add_uom_{bom_id}",
            label_visibility="collapsed"
        )
    
    with col5:
        scrap = st.number_input(
            "Scrap Rate (%)",
            min_value=0.0,
            max_value=100.0,
            value=0.0,
            step=0.5,
            key=f"edit_add_scrap_{bom_id}",
            label_visibility="collapsed",
            help="Expected waste percentage (0-100%)"  # ✅ Clear help text
        )
    
    if st.button("➕ Add Material", key=f"edit_add_btn_{bom_id}", use_container_width=True):
        # Check duplicate
        if not current_materials.empty:
            if material_id in current_materials['material_id'].values:
                st.error("❌ Material already exists in BOM")
                return
        
        # Validate
        if not validate_quantity(quantity):
            st.error("❌ Invalid quantity (must be > 0)")
            return
        
        if not validate_percentage(scrap):
            st.error("❌ Invalid scrap rate (must be 0-100%)")
            return
        
        # Add material
        _handle_add_material(
            bom_id, material_id, material_type, 
            quantity, mat_uom, scrap,
            state, manager
        )

def _handle_update_header(bom_id: int, name: str, qty: float, 
                          eff_date: date, notes: str,
                          state: StateManager, manager: BOMManager):
    """
    Handle header update
    
    Args:
        bom_id: BOM ID
        name: New name
        qty: New output quantity
        eff_date: New effective date
        notes: New notes
        state: State manager
        manager: BOM manager
    """
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
    """
    Handle material update
    
    Args:
        bom_id: BOM ID
        material_id: Material ID
        qty: New quantity
        scrap: New scrap rate
        state: State manager
        manager: BOM manager
    """
    try:
        updates = {
            'quantity': qty,
            'scrap_rate': scrap
        }
        
        manager.update_material(bom_id, material_id, updates)
        
        st.success("✅ Material updated!")
        st.rerun()
    
    except BOMException as e:
        st.error(f"❌ Error: {str(e)}")


def _handle_delete_material(bom_id: int, material_id: int,
                           state: StateManager, manager: BOMManager):
    """
    Handle material deletion
    
    Args:
        bom_id: BOM ID
        material_id: Material ID
        state: State manager
        manager: BOM manager
    """
    try:
        manager.remove_material(bom_id, material_id)
        
        st.success("✅ Material removed!")
        st.rerun()
    
    except BOMException as e:
        st.error(f"❌ Error: {str(e)}")


def _handle_add_material(bom_id: int, material_id: int, material_type: str,
                        qty: float, uom: str, scrap: float,
                        state: StateManager, manager: BOMManager):
    """
    Handle add material
    
    Args:
        bom_id: BOM ID
        material_id: Material ID
        material_type: Material type
        qty: Quantity
        uom: UOM
        scrap: Scrap rate
        state: State manager
        manager: BOM manager
    """
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