# utils/bom/dialogs/create.py
"""
Create BOM Dialog with Alternatives Support - ENHANCED VERSION
2-step wizard: Header information → Materials (with alternatives)
Validation: At least 1 RAW_MATERIAL required
"""

import logging
import streamlit as st
import pandas as pd
from datetime import date

from utils.bom.manager import BOMManager, BOMException, BOMValidationError
from utils.bom.state import StateManager
from utils.bom.common import (
    get_products,
    get_product_by_id,
    format_product_display,
    render_step_indicator,
    validate_quantity,
    validate_percentage,
    render_material_type_counter,
    validate_materials_for_bom
)

logger = logging.getLogger(__name__)


@st.dialog("➕ Create New BOM", width="large")
def show_create_dialog():
    """Create BOM wizard dialog (2 steps)"""
    state = StateManager()
    manager = BOMManager()
    
    current_step = state.get_create_step()
    
    render_step_indicator(current_step, 2)
    st.markdown("---")
    
    if current_step == 1:
        _render_step1_header(state)
    elif current_step == 2:
        _render_step2_materials(state, manager)


def _render_step1_header(state: StateManager):
    """Render Step 1: BOM Header Information"""
    st.markdown("### Step 1: BOM Information")
    
    saved_data = state.get_create_header_data()
    
    col1, col2 = st.columns(2)
    
    with col1:
        bom_name = st.text_input(
            "BOM Name *",
            value=saved_data.get('bom_name', ''),
            placeholder="Enter BOM name",
            key="create_bom_name"
        )
        
        bom_type = st.selectbox(
            "BOM Type *",
            options=["KITTING", "CUTTING", "REPACKING"],
            index=["KITTING", "CUTTING", "REPACKING"].index(
                saved_data.get('bom_type', 'KITTING')
            ),
            key="create_bom_type"
        )
        
        effective_date = st.date_input(
            "Effective Date",
            value=saved_data.get('effective_date', date.today()),
            key="create_effective_date"
        )
    
    with col2:
        products = get_products()
        
        if products.empty:
            st.error("❌ No products found")
            product_id = None
            uom = 'PCS'
        else:
            # Build product options with new format
            product_options = {}
            for _, row in products.iterrows():
                display_text = format_product_display(
                    code=row['code'],
                    name=row['name'],
                    package_size=row.get('package_size'),
                    brand=row.get('brand')
                )
                product_options[display_text] = row['id']
            
            default_idx = 0
            saved_product_id = saved_data.get('product_id')
            if saved_product_id:
                for idx, pid in enumerate(product_options.values()):
                    if pid == saved_product_id:
                        default_idx = idx
                        break
            
            selected_product = st.selectbox(
                "Output Product *",
                options=list(product_options.keys()),
                index=default_idx,
                key="create_product"
            )
            
            product_id = product_options.get(selected_product)
            
            if product_id:
                product_info = products[products['id'] == product_id].iloc[0]
                uom = product_info.get('uom', 'PCS')
            else:
                uom = 'PCS'
        
        output_qty = st.number_input(
            "Output Quantity *",
            min_value=0.01,
            value=saved_data.get('output_qty', 1.0),
            step=1.0,
            format="%.2f",
            key="create_output_qty"
        )
        
        st.text_input("UOM", value=uom, disabled=True, key="create_uom")
    
    notes = st.text_area(
        "Notes",
        value=saved_data.get('notes', ''),
        placeholder="Optional notes...",
        height=80,
        key="create_notes"
    )
    
    st.markdown("---")
    
    col1, col2 = st.columns([3, 1])
    
    with col2:
        if st.button("Next: Add Materials →", type="primary", use_container_width=True, key="create_step1_next"):
            errors = _validate_step1(bom_name, product_id, output_qty)
            
            if errors:
                for error in errors:
                    st.error(f"❌ {error}")
            else:
                header_data = {
                    'bom_name': bom_name,
                    'bom_type': bom_type,
                    'product_id': product_id,
                    'output_qty': output_qty,
                    'uom': uom,
                    'effective_date': effective_date,
                    'notes': notes
                }
                
                state.set_create_header_data(header_data)
                state.set_create_step(2)
                st.rerun()
    
    with col1:
        if st.button("❌ Cancel", use_container_width=True, key="create_step1_cancel"):
            state.close_dialog()
            st.rerun()


def _render_step2_materials(state: StateManager, manager: BOMManager):
    """Render Step 2: Materials with Alternatives"""
    st.markdown("### Step 2: Add Materials & Alternatives")
    
    header_data = state.get_create_header_data()
    
    with st.expander("📋 BOM Information Summary", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            st.write(f"**Name:** {header_data.get('bom_name', 'N/A')}")
            st.write(f"**Type:** {header_data.get('bom_type', 'N/A')}")
        with col2:
            st.write(f"**Output:** {header_data.get('output_qty', 0)} {header_data.get('uom', 'PCS')}")
            st.write(f"**Effective:** {header_data.get('effective_date', 'N/A')}")
    
    st.markdown("---")
    
    materials = state.get_create_materials()
    
    # Material type counter with validation
    st.markdown("### 📊 Material Summary")
    render_material_type_counter(materials, show_warning=True)
    
    st.markdown("---")
    
    if materials:
        st.markdown(f"**Materials Added ({len(materials)}):**")
        _render_material_list_with_alternatives(materials, state)
    else:
        st.info("ℹ️ No materials added yet. Add at least one RAW_MATERIAL below.")
    
    st.markdown("---")
    
    _render_add_material_form(state)
    
    st.markdown("---")
    
    # Validate before showing Create button
    can_create, validation_error = validate_materials_for_bom(materials)
    
    col1, col2, col3 = st.columns([2, 1, 1])
    
    with col1:
        if st.button("← Back to Information", use_container_width=True, key="create_step2_back"):
            state.set_create_step(1)
            st.rerun()
    
    with col2:
        if st.button(
            "✅ Create BOM",
            type="primary",
            use_container_width=True,
            disabled=not can_create,
            key="create_step2_create"
        ):
            if can_create:
                _handle_create_bom(state, manager)
            else:
                st.error(f"❌ {validation_error}")
    
    with col3:
        if st.button("❌ Cancel", use_container_width=True, key="create_step2_cancel"):
            state.close_dialog()
            st.rerun()
    
    # Show validation message below buttons if not valid
    if not can_create:
        st.error(f"❌ {validation_error}")


def _render_material_list_with_alternatives(materials: list, state: StateManager):
    """Render materials list with alternatives"""
    products = get_products()
    
    for idx, material in enumerate(materials):
        mat_product = products[products['id'] == material['material_id']]
        
        if mat_product.empty:
            continue
        
        mat_info = mat_product.iloc[0]
        alternatives = material.get('alternatives', [])
        
        # Material row
        col1, col2, col3, col4, col5, col6 = st.columns([3, 2, 1, 1, 1, 1])
        
        with col1:
            alt_badge = f" 🔀 **{len(alternatives)} alt(s)**" if alternatives else ""
            display_text = format_product_display(
                code=mat_info['code'],
                name=mat_info['name'],
                package_size=mat_info.get('package_size'),
                brand=mat_info.get('brand'),
                max_name_length=30
            )
            st.markdown(f"**{display_text}**{alt_badge}")
        
        with col2:
            st.text(material['material_type'])
        
        with col3:
            st.text(f"{material['quantity']:.4f}")
        
        with col4:
            st.text(material['uom'])
        
        with col5:
            st.text(f"{material['scrap_rate']:.2f}%")
        
        with col6:
            if st.button("🗑️", key=f"create_remove_mat_{idx}", help="Remove material"):
                state.remove_create_material(idx)
                st.rerun()
        
        # Inline alternatives management
        with st.expander(f"🔀 Manage Alternatives ({len(alternatives)})", expanded=False):
            if alternatives:
                st.markdown("**Current Alternatives:**")
                _render_alternatives_list(idx, alternatives, material, state)
                st.markdown("---")
            
            st.markdown("**Add Alternative:**")
            _render_add_alternative_form(idx, material, alternatives, state)
        
        st.markdown("")


def _render_alternatives_list(material_idx: int, alternatives: list, 
                               material: dict, state: StateManager):
    """Render alternatives list for a material in create mode"""
    products = get_products()
    
    for alt_idx, alt in enumerate(alternatives):
        alt_product = products[products['id'] == alt['alternative_material_id']]
        
        if alt_product.empty:
            continue
        
        alt_info = alt_product.iloc[0]
        
        col1, col2, col3, col4, col5, col6 = st.columns([3, 1, 1, 1, 1, 1])
        
        with col1:
            display_text = format_product_display(
                code=alt_info['code'],
                name=alt_info['name'],
                package_size=alt_info.get('package_size'),
                brand=alt_info.get('brand'),
                max_name_length=25
            )
            st.text(f"  {display_text}")
        
        with col2:
            st.text(f"{alt['quantity']:.4f}")
        
        with col3:
            st.text(alt['uom'])
        
        with col4:
            st.text(f"{alt['scrap_rate']:.2f}%")
        
        with col5:
            priority_color = "🟢" if alt['priority'] == 1 else "🟡" if alt['priority'] == 2 else "⚪"
            st.text(f"{priority_color} P{alt['priority']}")
        
        with col6:
            if st.button("🗑️", key=f"create_remove_alt_{material_idx}_{alt_idx}", help="Remove alternative"):
                materials = state.get_create_materials()
                materials[material_idx]['alternatives'].pop(alt_idx)
                
                state.set_dialog_state(state.DIALOG_CREATE, {
                    'step': state.get_create_step(),
                    'header_data': state.get_create_header_data(),
                    'materials': materials
                })
                
                st.success("✅ Alternative removed!")
                st.rerun()


def _render_add_alternative_form(material_idx: int, material: dict, 
                                  alternatives: list, state: StateManager):
    """Render add alternative form"""
    products = get_products()
    
    if products.empty:
        st.warning("⚠️ No products available to add as alternatives")
        return
    
    # Build product options with new format
    product_options = {}
    for _, row in products.iterrows():
        # Exclude primary material
        if row['id'] == material['material_id']:
            continue
        
        # Exclude already added alternatives
        if any(alt['alternative_material_id'] == row['id'] for alt in alternatives):
            continue
        
        display_text = format_product_display(
            code=row['code'],
            name=row['name'],
            package_size=row.get('package_size'),
            brand=row.get('brand')
        )
        product_options[display_text] = row['id']
    
    if not product_options:
        st.info("ℹ️ No more products available as alternatives")
        return
    
    col1, col2, col3, col4, col5 = st.columns([3, 1, 1, 1, 1])
    
    with col1:
        selected_alt = st.selectbox(
            "Alternative Material",
            options=list(product_options.keys()),
            key=f"create_add_alt_select_{material_idx}",
            label_visibility="collapsed"
        )
        alt_material_id = product_options.get(selected_alt)
    
    with col2:
        quantity = st.number_input(
            "Quantity",
            min_value=0.0001,
            value=material['quantity'],
            step=0.1,
            format="%.4f",
            key=f"create_add_alt_qty_{material_idx}",
            label_visibility="collapsed"
        )
    
    with col3:
        if alt_material_id:
            alt_product = products[products['id'] == alt_material_id].iloc[0]
            alt_uom = alt_product.get('uom', 'PCS')
        else:
            alt_uom = 'PCS'
        st.text_input("UOM", value=alt_uom, disabled=True, 
                     key=f"create_add_alt_uom_{material_idx}", label_visibility="collapsed")
    
    with col4:
        scrap = st.number_input(
            "Scrap %",
            min_value=0.0,
            max_value=100.0,
            value=material['scrap_rate'],
            step=0.5,
            key=f"create_add_alt_scrap_{material_idx}",
            label_visibility="collapsed"
        )
    
    with col5:
        # Auto-calculate next priority
        next_priority = len(alternatives) + 1
        priority = st.number_input(
            "Priority",
            min_value=1,
            max_value=99,
            value=next_priority,
            key=f"create_add_alt_priority_{material_idx}",
            label_visibility="collapsed"
        )
    
    if st.button("➕ Add Alternative", key=f"create_add_alt_btn_{material_idx}", use_container_width=True):
        if not validate_quantity(quantity):
            st.error("❌ Invalid quantity")
            return
        
        if not validate_percentage(scrap):
            st.error("❌ Invalid scrap rate")
            return
        
        # Add alternative to material
        alternative_data = {
            'alternative_material_id': alt_material_id,
            'quantity': quantity,
            'uom': alt_uom,
            'scrap_rate': scrap,
            'priority': priority
        }
        
        materials = state.get_create_materials()
        materials[material_idx]['alternatives'].append(alternative_data)
        
        state.set_dialog_state(state.DIALOG_CREATE, {
            'step': state.get_create_step(),
            'header_data': state.get_create_header_data(),
            'materials': materials
        })
        
        st.success("✅ Alternative added!")
        st.rerun()


def _render_add_material_form(state: StateManager):
    """Render add material form"""
    st.markdown("**Add Material:**")
    
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
        
        # Build product options with new format
        product_options = {}
        for _, row in products.iterrows():
            display_text = format_product_display(
                code=row['code'],
                name=row['name'],
                package_size=row.get('package_size'),
                brand=row.get('brand')
            )
            product_options[display_text] = row['id']
        
        selected_material = st.selectbox(
            "Material",
            options=list(product_options.keys()),
            key="create_add_material_select",
            label_visibility="collapsed"
        )
        
        material_id = product_options.get(selected_material)
    
    with col2:
        material_type = st.selectbox(
            "Type",
            options=["RAW_MATERIAL", "PACKAGING", "CONSUMABLE"],
            key="create_add_material_type",
            label_visibility="collapsed"
        )
    
    with col3:
        quantity = st.number_input(
            "Quantity",
            min_value=0.0001,
            value=1.0,
            step=0.1,
            format="%.4f",
            key="create_add_material_qty",
            label_visibility="collapsed"
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
            key="create_add_material_uom",
            label_visibility="collapsed"
        )
    
    with col5:
        scrap_rate = st.number_input(
            "Scrap Rate (%)",
            min_value=0.0,
            max_value=100.0,
            value=0.0,
            step=0.5,
            key="create_add_material_scrap",
            label_visibility="collapsed"
        )
    
    if st.button("➕ Add Material", key="create_add_material_btn", use_container_width=True):
        if not material_id:
            st.error("❌ Please select a material")
            return
        
        current_materials = state.get_create_materials()
        if any(m['material_id'] == material_id for m in current_materials):
            st.error("❌ Material already added")
            return
        
        if not validate_quantity(quantity):
            st.error("❌ Invalid quantity")
            return
        
        if not validate_percentage(scrap_rate):
            st.error("❌ Invalid scrap rate (must be 0-100%)")
            return
        
        material_data = {
            'material_id': material_id,
            'material_type': material_type,
            'quantity': quantity,
            'uom': mat_uom,
            'scrap_rate': scrap_rate,
            'alternatives': []
        }
        
        state.add_create_material(material_data)
        st.success("✅ Material added! You can add alternatives using 🔀 button.")
        st.rerun()


def _validate_step1(bom_name: str, product_id: int, output_qty: float) -> list:
    """Validate step 1 data"""
    errors = []
    
    if not bom_name or len(bom_name.strip()) == 0:
        errors.append("BOM name is required")
    
    if not product_id:
        errors.append("Output product is required")
    
    if not validate_quantity(output_qty):
        errors.append("Output quantity must be greater than 0")
    
    return errors


def _handle_create_bom(state: StateManager, manager: BOMManager):
    """Handle BOM creation with alternatives and validation"""
    try:
        header_data = state.get_create_header_data()
        materials = state.get_create_materials()
        
        # Final validation
        can_create, validation_error = validate_materials_for_bom(materials)
        
        if not can_create:
            st.error(f"❌ {validation_error}")
            return
        
        user_id = st.session_state.get('user_id', 1)
        
        bom_data = {
            'bom_name': header_data['bom_name'],
            'bom_type': header_data['bom_type'],
            'product_id': header_data['product_id'],
            'output_qty': header_data['output_qty'],
            'uom': header_data['uom'],
            'effective_date': header_data['effective_date'],
            'notes': header_data.get('notes', ''),
            'materials': materials,
            'created_by': user_id
        }
        
        state.set_loading(True)
        bom_code = manager.create_bom(bom_data)
        state.set_loading(False)
        
        state.record_action('create', bom_code=bom_code)
        
        state.show_success(f"✅ BOM {bom_code} created successfully!")
        
        state.close_dialog()
        
        st.rerun()
    
    except BOMValidationError as e:
        state.set_loading(False)
        st.error(f"❌ Validation Error: {str(e)}")
    except BOMException as e:
        state.set_loading(False)
        st.error(f"❌ Error: {str(e)}")
    except Exception as e:
        state.set_loading(False)
        logger.error(f"Unexpected error creating BOM: {e}")
        st.error(f"❌ Unexpected error: {str(e)}")