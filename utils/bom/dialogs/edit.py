# utils/bom/dialogs/edit.py
"""
Edit BOM Dialog with Material Alternatives Support - OPTIMIZED VERSION
Tabbed editor with form containers to prevent unnecessary reruns
Only DRAFT BOMs can be edited
"""

import logging
import streamlit as st
import pandas as pd
from datetime import date
from typing import Dict, List, Any, Optional

from utils.bom.manager import BOMManager, BOMException, BOMValidationError, BOMNotFoundError
from utils.bom.state import StateManager
from utils.bom.common import (
    get_products,
    get_product_by_id,
    format_product_display,
    validate_quantity,
    validate_percentage,
    format_number,
    create_status_indicator,
    render_material_type_counter,
    validate_materials_for_bom
)

logger = logging.getLogger(__name__)

# Cache product list to avoid repeated queries
@st.cache_data(ttl=300)  # Cache for 5 minutes
def get_cached_products():
    """Get cached product list"""
    return get_products()


@st.dialog("✏️ Edit BOM", width="large")
def show_edit_dialog(bom_id: int):
    """Edit BOM dialog (DRAFT only) - Optimized version"""
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
        
        # Check if editable
        if bom_info['status'] != 'DRAFT':
            st.error(f"❌ Only DRAFT BOMs can be edited. Current status: {bom_info['status']}")
            st.info("💡 Change status to DRAFT first if you need to edit.")
            
            if st.button("Close", use_container_width=True, key=f"edit_nondraft_close_{bom_id}"):
                state.close_dialog()
                st.rerun()
            return
        
        st.markdown(f"### Editing: {bom_info['bom_code']} - {bom_info['bom_name']}")
        
        # Tabs for different sections
        tab1, tab2 = st.tabs(["📄 BOM Information", "🧱 Materials"])
        
        with tab1:
            _render_info_tab_optimized(bom_id, bom_info, state, manager)
        
        with tab2:
            _render_materials_tab_optimized(bom_id, bom_details, state, manager)
    
    except Exception as e:
        logger.error(f"Error in edit dialog: {e}")
        st.error(f"❌ Error: {str(e)}")
        
        if st.button("Close", key=f"edit_exception_close_{bom_id}"):
            state.close_dialog()
            st.rerun()


def _render_info_tab_optimized(bom_id: int, bom_info: dict, state: StateManager, manager: BOMManager):
    """Render BOM information tab - Using Form Container"""
    st.markdown("### Edit BOM Information")
    
    with st.form("edit_bom_info_form", clear_on_submit=False):
        col1, col2 = st.columns(2)
        
        with col1:
            new_name = st.text_input(
                "BOM Name *",
                value=bom_info['bom_name']
            )
            
            new_output_qty = st.number_input(
                "Output Quantity *",
                min_value=0.01,
                value=float(bom_info['output_qty']),
                step=1.0,
                format="%.2f"
            )
        
        with col2:
            new_effective_date = st.date_input(
                "Effective Date",
                value=bom_info.get('effective_date', date.today())
            )
            
            st.text_input(
                "UOM",
                value=bom_info.get('uom', 'PCS'),
                disabled=True
            )
        
        new_notes = st.text_area(
            "Notes",
            value=bom_info.get('notes', ''),
            height=100
        )
        
        # Read-only fields
        st.markdown("---")
        st.markdown("**Read-only Information:**")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.text_input("BOM Code", value=bom_info['bom_code'], disabled=True)
        
        with col2:
            st.text_input("BOM Type", value=bom_info['bom_type'], disabled=True)
        
        with col3:
            st.text_input("Status", value=bom_info['status'], disabled=True)
        
        st.markdown("---")
        
        col1, col2 = st.columns([3, 1])
        
        with col1:
            cancel_button = st.form_submit_button("❌ Cancel", use_container_width=True)
        
        with col2:
            save_button = st.form_submit_button(
                "💾 Save Changes",
                type="primary",
                use_container_width=True
            )
    
    # Handle form submission
    if save_button:
        # Validate
        if not new_name or len(new_name.strip()) == 0:
            st.error("❌ BOM name is required")
        elif new_output_qty <= 0:
            st.error("❌ Output quantity must be greater than 0")
        else:
            # Update BOM info
            try:
                user_id = st.session_state.get('user_id', 1)
                
                update_data = {
                    'bom_name': new_name,
                    'output_qty': new_output_qty,
                    'effective_date': new_effective_date,
                    'notes': new_notes,
                    'updated_by': user_id
                }
                
                manager.update_bom_header(bom_id, update_data)
                
                state.record_action('update', bom_id=bom_id, bom_code=bom_info['bom_code'])
                
                st.success("✅ BOM information updated successfully!")
                st.rerun()
            
            except BOMValidationError as e:
                st.error(f"❌ Validation Error: {str(e)}")
            except Exception as e:
                logger.error(f"Error updating BOM info: {e}")
                st.error(f"❌ Error: {str(e)}")
    
    if cancel_button:
        state.close_dialog()
        st.rerun()


def _render_materials_tab_optimized(bom_id: int, bom_details: pd.DataFrame, 
                                    state: StateManager, manager: BOMManager):
    """Render materials tab - Optimized version"""
    st.markdown("### Materials Management")
    
    # Convert DataFrame to list for easier manipulation
    materials = []
    if not bom_details.empty:
        for _, row in bom_details.iterrows():
            materials.append({
                'detail_id': row['id'],
                'material_id': row['material_id'],
                'material_name': row['material_name'],
                'material_code': row['material_code'],
                'material_type': row['material_type'],
                'quantity': row['quantity'],
                'uom': row['uom'],
                'scrap_rate': row['scrap_rate'],
                'alternatives_count': row.get('alternatives_count', 0)
            })
    
    # Material counter
    st.markdown("### 📊 Material Summary")
    render_material_type_counter(materials, show_warning=True)
    
    st.markdown("---")
    
    # Display existing materials
    if materials:
        st.markdown(f"**Current Materials ({len(materials)}):**")
        _render_editable_material_list(bom_id, materials, state, manager)
    else:
        st.info("ℹ️ No materials in this BOM. Add at least one RAW_MATERIAL.")
    
    st.markdown("---")
    
    # Add new material form
    _render_add_material_to_bom_form(bom_id, state, manager)
    
    st.markdown("---")
    
    # Action buttons
    col1, col2 = st.columns([3, 1])
    
    with col1:
        if st.button("🔄 Refresh", use_container_width=True, key=f"materials_refresh_{bom_id}"):
            st.rerun()
    
    with col2:
        if st.button("✅ Close", use_container_width=True, type="primary", key=f"materials_close_{bom_id}"):
            state.close_dialog()
            st.rerun()


def _render_editable_material_list(bom_id: int, materials: list, 
                                   state: StateManager, manager: BOMManager):
    """Render editable material list with inline edit capabilities"""
    
    for idx, material in enumerate(materials):
        detail_id = material['detail_id']
        edit_key = f"edit_mat_{detail_id}"
        alt_key = f"show_alt_{detail_id}"
        
        # Material card
        with st.container():
            # Check if in edit mode
            if st.session_state.get(edit_key, False):
                # Edit mode - using form
                _render_material_edit_form(bom_id, detail_id, material, state, manager)
            else:
                # Display mode
                col1, col2, col3, col4, col5, col6, col7, col8 = st.columns([3, 1.5, 1, 0.8, 0.8, 0.7, 0.7, 0.7])
                
                with col1:
                    alt_count = material.get('alternatives_count', 0)
                    alt_badge = f" 🔀 **{alt_count} alt(s)**" if alt_count > 0 else ""
                    st.markdown(f"**{material['material_name']}** ({material['material_code']}){alt_badge}")
                
                with col2:
                    st.text(material['material_type'])
                
                with col3:
                    st.text(f"{format_number(material['quantity'], 4)}")
                
                with col4:
                    st.text(material['uom'])
                
                with col5:
                    st.text(f"{material['scrap_rate']}%")
                
                with col6:
                    if st.button("✏️", key=f"edit_btn_{detail_id}", help="Edit"):
                        st.session_state[edit_key] = True
                        st.rerun()
                
                with col7:
                    show_alts = material.get('alternatives_count', 0) > 0
                    if st.button("🔀", key=f"alt_btn_{detail_id}", help=f"Alternatives ({material.get('alternatives_count', 0)})", disabled=not show_alts and material.get('alternatives_count', 0) == 0):
                        st.session_state[alt_key] = not st.session_state.get(alt_key, False)
                        st.rerun()
                
                with col8:
                    if st.button("🗑️", key=f"del_btn_{detail_id}", help="Remove"):
                        try:
                            user_id = st.session_state.get('user_id', 1)
                            manager.delete_bom_material(detail_id, user_id)
                            st.success(f"✅ Material removed")
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Error: {str(e)}")
        
        # Show alternatives section if toggled
        if st.session_state.get(alt_key, False):
            with st.expander(f"   ↳ Alternatives for {material['material_name']}", expanded=True):
                _render_material_alternatives(bom_id, detail_id, manager)
        
        st.markdown("")


def _render_material_edit_form(bom_id: int, detail_id: int, material: dict, 
                               state: StateManager, manager: BOMManager):
    """Render inline edit form for material"""
    
    with st.form(f"edit_material_form_{detail_id}", clear_on_submit=False):
        col1, col2, col3, col4, col5, col6 = st.columns([3, 1.5, 1, 0.8, 0.8, 1.2])
        
        with col1:
            st.text_input(
                "Material",
                value=f"{material['material_name']} ({material['material_code']})",
                disabled=True
            )
        
        with col2:
            new_type = st.selectbox(
                "Type",
                options=["RAW_MATERIAL", "PACKAGING", "CONSUMABLE"],
                index=["RAW_MATERIAL", "PACKAGING", "CONSUMABLE"].index(material['material_type'])
            )
        
        with col3:
            new_qty = st.number_input(
                "Quantity",
                min_value=0.0001,
                value=float(material['quantity']),
                step=0.1,
                format="%.4f"
            )
        
        with col4:
            st.text_input("UOM", value=material['uom'], disabled=True)
        
        with col5:
            new_scrap = st.number_input(
                "Scrap %",
                min_value=0.0,
                max_value=100.0,
                value=float(material['scrap_rate']),
                step=0.5
            )
        
        with col6:
            col_save, col_cancel = st.columns(2)
            with col_save:
                save_button = st.form_submit_button("💾", help="Save", use_container_width=True)
            with col_cancel:
                cancel_button = st.form_submit_button("❌", help="Cancel", use_container_width=True)
    
    # Handle form submission
    if save_button:
        if validate_quantity(new_qty) and validate_percentage(new_scrap):
            try:
                user_id = st.session_state.get('user_id', 1)
                
                update_data = {
                    'material_type': new_type,
                    'quantity': new_qty,
                    'scrap_rate': new_scrap,
                    'updated_by': user_id
                }
                
                manager.update_bom_material(detail_id, update_data)
                
                st.session_state[f"edit_mat_{detail_id}"] = False
                st.success("✅ Material updated")
                st.rerun()
            
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")
        else:
            st.error("❌ Invalid quantity or scrap rate")
    
    if cancel_button:
        st.session_state[f"edit_mat_{detail_id}"] = False
        st.rerun()


def _render_material_alternatives(bom_id: int, detail_id: int, manager: BOMManager):
    """Render and manage alternatives for a material"""
    try:
        # Get existing alternatives
        alternatives = manager.get_material_alternatives(detail_id)
        
        # Display existing alternatives
        if not alternatives.empty:
            st.markdown("**Current Alternatives:**")
            
            for _, alt in alternatives.iterrows():
                col1, col2, col3, col4, col5, col6 = st.columns([3, 1, 1, 1, 1, 1])
                
                with col1:
                    status_icon = "✅" if alt['is_active'] else "⭕"
                    st.text(f"P{alt['priority']}: {status_icon} {alt['material_name']} ({alt['material_code']})")
                
                with col2:
                    st.text(alt['material_type'])
                
                with col3:
                    st.text(f"{format_number(alt['quantity'], 4)}")
                
                with col4:
                    st.text(alt['uom'])
                
                with col5:
                    st.text(f"{alt['scrap_rate']}%")
                
                with col6:
                    if st.button("🗑️", key=f"del_alt_{alt['id']}", help="Remove alternative"):
                        try:
                            user_id = st.session_state.get('user_id', 1)
                            manager.delete_material_alternative(alt['id'], user_id)
                            st.success("✅ Alternative removed")
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Error: {str(e)}")
            
            st.markdown("---")
        
        # Add new alternative form
        st.markdown("**Add Alternative:**")
        
        with st.form(f"add_alternative_to_material_{detail_id}", clear_on_submit=True):
            products = get_cached_products()
            
            col1, col2, col3, col4, col5 = st.columns([3, 1, 1, 1, 1])
            
            with col1:
                product_options = {}
                for _, row in products.iterrows():
                    display_text = format_product_display(
                        code=row['code'],
                        name=row['name'],
                        package_size=row.get('package_size'),
                        brand=row.get('brand')
                    )
                    product_options[display_text] = {
                        'id': row['id'],
                        'uom': row['uom']
                    }
                
                selected_alt = st.selectbox(
                    "Alternative Material",
                    options=list(product_options.keys())
                )
                
                alt_info = product_options.get(selected_alt)
                alt_material_id = alt_info['id'] if alt_info else None
                alt_uom = alt_info['uom'] if alt_info else 'PCS'
            
            with col2:
                quantity = st.number_input(
                    "Qty",
                    min_value=0.0001,
                    value=1.0,
                    step=0.1,
                    format="%.4f"
                )
            
            with col3:
                st.text_input("UOM", value=alt_uom, disabled=True)
            
            with col4:
                scrap = st.number_input(
                    "Scrap %",
                    min_value=0.0,
                    max_value=100.0,
                    value=0.0,
                    step=0.5
                )
            
            with col5:
                priority = st.number_input(
                    "Priority",
                    min_value=1,
                    max_value=99,
                    value=len(alternatives) + 1 if not alternatives.empty else 1
                )
            
            add_button = st.form_submit_button("➕ Add", use_container_width=True)
        
        # Handle form submission
        if add_button and alt_material_id:
            if validate_quantity(quantity) and validate_percentage(scrap):
                try:
                    user_id = st.session_state.get('user_id', 1)
                    
                    alternative_data = {
                        'bom_detail_id': detail_id,
                        'alternative_material_id': alt_material_id,
                        'quantity': quantity,
                        'scrap_rate': scrap,
                        'priority': priority,
                        'is_active': 1,
                        'created_by': user_id
                    }
                    
                    manager.add_material_alternative(alternative_data)
                    
                    st.success("✅ Alternative added!")
                    st.rerun()
                
                except Exception as e:
                    st.error(f"❌ Error: {str(e)}")
            else:
                st.error("❌ Invalid quantity or scrap rate")
    
    except Exception as e:
        logger.error(f"Error managing alternatives: {e}")
        st.error(f"❌ Error loading alternatives: {str(e)}")


def _render_add_material_to_bom_form(bom_id: int, state: StateManager, manager: BOMManager):
    """Render form to add new material to BOM"""
    st.markdown("**Add New Material:**")
    
    with st.form("add_material_to_bom_form", clear_on_submit=True):
        products = get_cached_products()
        
        if products.empty:
            st.error("❌ No products available")
            return
        
        col1, col2, col3, col4, col5 = st.columns([3, 2, 1, 1, 1])
        
        with col1:
            product_options = {}
            for _, row in products.iterrows():
                display_text = format_product_display(
                    code=row['code'],
                    name=row['name'],
                    package_size=row.get('package_size'),
                    brand=row.get('brand')
                )
                product_options[display_text] = {
                    'id': row['id'],
                    'uom': row['uom']
                }
            
            selected_material = st.selectbox(
                "Material",
                options=list(product_options.keys())
            )
            
            mat_info = product_options.get(selected_material)
            material_id = mat_info['id'] if mat_info else None
            mat_uom = mat_info['uom'] if mat_info else 'PCS'
        
        with col2:
            material_type = st.selectbox(
                "Type",
                options=["RAW_MATERIAL", "PACKAGING", "CONSUMABLE"]
            )
        
        with col3:
            quantity = st.number_input(
                "Quantity",
                min_value=0.0001,
                value=1.0,
                step=0.1,
                format="%.4f"
            )
        
        with col4:
            st.text_input("UOM", value=mat_uom, disabled=True)
        
        with col5:
            scrap_rate = st.number_input(
                "Scrap %",
                min_value=0.0,
                max_value=100.0,
                value=0.0,
                step=0.5
            )
        
        add_button = st.form_submit_button("➕ Add Material", use_container_width=True)
    
    # Handle form submission
    if add_button and material_id:
        if validate_quantity(quantity) and validate_percentage(scrap_rate):
            try:
                user_id = st.session_state.get('user_id', 1)
                
                material_data = {
                    'bom_header_id': bom_id,
                    'material_id': material_id,
                    'material_type': material_type,
                    'quantity': quantity,
                    'scrap_rate': scrap_rate,
                    'created_by': user_id
                }
                
                manager.add_bom_material(material_data)
                
                st.success("✅ Material added to BOM!")
                st.rerun()
            
            except BOMValidationError as e:
                st.error(f"❌ Validation Error: {str(e)}")
            except Exception as e:
                logger.error(f"Error adding material: {e}")
                st.error(f"❌ Error: {str(e)}")
        else:
            st.error("❌ Invalid quantity or scrap rate")