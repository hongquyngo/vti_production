# utils/bom/dialogs/create.py
"""
Create BOM Dialog with Alternatives Support - OPTIMIZED VERSION v2.3
2-step wizard with form containers to prevent unnecessary reruns
Validation: At least 1 RAW_MATERIAL required

Changes in v2.3:
- Added circular dependency validation: output product cannot be used as input material
- Filter output product from material/alternative selection lists
- Final validation before BOM creation

Changes in v2.2:
- Added info banner when selecting product that already has Active BOM
- Non-blocking informational warning for conflict awareness

Changes in v2.1:
- Updated format_product_display calls with legacy_code parameter
"""

import logging
import streamlit as st
import pandas as pd
from datetime import date
from typing import Dict, List, Any, Optional

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
    validate_materials_for_bom,
    format_number,
    # Duplicate validation helpers
    get_all_material_ids_in_bom_list,
    validate_material_not_duplicate,
    filter_available_materials,
    # Active BOM conflict detection
    get_active_boms_for_product,
    # Output product vs materials validation (circular dependency prevention)
    validate_output_not_in_materials,
    validate_material_not_output_product,
    filter_available_materials_excluding_output
)

logger = logging.getLogger(__name__)

# Cache product list to avoid repeated queries
@st.cache_data(ttl=300)  # Cache for 5 minutes
def get_cached_products():
    """Get cached product list"""
    return get_products()


def _render_active_bom_info_banner(active_boms: list):
    """
    Render info banner when product already has active BOM(s)
    Non-blocking informational warning
    """
    count = len(active_boms)
    bom_codes = [bom['bom_code'] for bom in active_boms]
    bom_codes_str = ", ".join(bom_codes[:3])  # Show max 3 codes
    if count > 3:
        bom_codes_str += f" (+{count - 3} more)"
    
    st.info(
        f"ℹ️ **This product already has {count} active BOM(s):** {bom_codes_str}\n\n"
        f"New BOM will be created as **DRAFT**. You can activate it later."
    )


@st.dialog("➕ Create New BOM", width="large")
def show_create_dialog():
    """Create BOM wizard dialog (2 steps) - Optimized version"""
    state = StateManager()
    manager = BOMManager()
    
    current_step = state.get_create_step()
    
    render_step_indicator(current_step, 2)
    st.markdown("---")
    
    if current_step == 1:
        _render_step1_header_optimized(state)
    elif current_step == 2:
        _render_step2_materials_optimized(state, manager)


def _render_step1_header_optimized(state: StateManager):
    """Render Step 1: BOM Header Information - Using Form Container"""
    st.markdown("### Step 1: BOM Information")
    
    saved_data = state.get_create_header_data()
    products = get_cached_products()
    
    # =====================================================
    # INFO BANNER: Check if saved product has active BOM
    # =====================================================
    saved_product_id = saved_data.get('product_id')
    if saved_product_id:
        active_boms = get_active_boms_for_product(saved_product_id)
        if active_boms:
            _render_active_bom_info_banner(active_boms)
    
    # Use form container to prevent reruns on every input
    with st.form("create_bom_header_form", clear_on_submit=False):
        col1, col2 = st.columns(2)
        
        with col1:
            bom_name = st.text_input(
                "BOM Name *",
                value=saved_data.get('bom_name', ''),
                placeholder="Enter BOM name"
            )
            
            bom_type = st.selectbox(
                "BOM Type *",
                options=["KITTING", "CUTTING", "REPACKING"],
                index=["KITTING", "CUTTING", "REPACKING"].index(
                    saved_data.get('bom_type', 'KITTING')
                )
            )
            
            effective_date = st.date_input(
                "Effective Date",
                value=saved_data.get('effective_date', date.today())
            )
        
        with col2:
            if products.empty:
                st.error("❌ No products found")
                product_id = None
                uom = 'PCS'
            else:
                # Build product options
                product_options = {}
                product_displays = []
                
                for _, row in products.iterrows():
                    display_text = format_product_display(
                        code=row['code'],
                        name=row['name'],
                        package_size=row.get('package_size'),
                        brand=row.get('brand'),
                        legacy_code=row.get('legacy_code')
                    )
                    product_options[display_text] = {
                        'id': row['id'],
                        'uom': row['uom']
                    }
                    product_displays.append(display_text)
                
                # Find default index
                default_idx = 0
                saved_product_id = saved_data.get('product_id')
                if saved_product_id:
                    for idx, (display, info) in enumerate(product_options.items()):
                        if info['id'] == saved_product_id:
                            default_idx = idx
                            break
                
                selected_product = st.selectbox(
                    "Output Product *",
                    options=product_displays,
                    index=default_idx
                )
                
                product_info = product_options.get(selected_product)
                product_id = product_info['id'] if product_info else None
                uom = product_info['uom'] if product_info else 'PCS'
            
            output_qty = st.number_input(
                "Output Quantity *",
                min_value=0.01,
                value=saved_data.get('output_qty', 1.0),
                step=1.0,
                format="%.2f"
            )
            
            st.text_input("UOM", value=uom, disabled=True)
        
        notes = st.text_area(
            "Notes",
            value=saved_data.get('notes', ''),
            placeholder="Optional notes...",
            height=80
        )
        
        st.markdown("---")
        
        col1, col2 = st.columns([3, 1])
        
        with col1:
            cancel_button = st.form_submit_button("❌ Cancel", use_container_width=True)
        
        with col2:
            next_button = st.form_submit_button(
                "Next: Add Materials →",
                type="primary",
                use_container_width=True
            )
    
    # Handle form submission outside the form
    if next_button:
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
    
    if cancel_button:
        state.close_dialog()
        st.rerun()


def _render_step2_materials_optimized(state: StateManager, manager: BOMManager):
    """Render Step 2: Materials with Alternatives - Optimized"""
    st.markdown("### Step 2: Add Materials & Alternatives")
    
    header_data = state.get_create_header_data()
    
    # =====================================================
    # INFO BANNER: Check if selected product has active BOM
    # =====================================================
    product_id = header_data.get('product_id')
    if product_id:
        active_boms = get_active_boms_for_product(product_id)
        if active_boms:
            _render_active_bom_info_banner(active_boms)
    
    # Summary section
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
    
    # Material type counter
    st.markdown("### 📊 Material Summary")
    render_material_type_counter(materials, show_warning=True)
    
    st.markdown("---")
    
    # Display materials list
    if materials:
        st.markdown(f"**Materials Added ({len(materials)}):**")
        _render_material_list_optimized(materials, state)
    else:
        st.info("ℹ️ No materials added yet. Add at least one RAW_MATERIAL below.")
    
    st.markdown("---")
    
    # Add material form - using form container
    _render_add_material_form_optimized(state)
    
    st.markdown("---")
    
    # Bottom action buttons
    can_create, validation_error = validate_materials_for_bom(materials)
    
    col1, col2, col3 = st.columns([2, 1, 1])
    
    with col1:
        if st.button("← Back to Information", use_container_width=True):
            state.set_create_step(1)
            st.rerun()
    
    with col2:
        if st.button(
            "✅ Create BOM",
            type="primary",
            use_container_width=True,
            disabled=not can_create
        ):
            if can_create:
                _handle_create_bom(state, manager)
            else:
                st.error(f"❌ {validation_error}")
    
    with col3:
        if st.button("❌ Cancel", use_container_width=True):
            state.close_dialog()
            st.rerun()
    
    if not can_create:
        st.error(f"❌ {validation_error}")


def _render_material_list_optimized(materials: list, state: StateManager):
    """Render materials list with alternatives - Optimized"""
    products = get_cached_products()
    
    for idx, material in enumerate(materials):
        mat_product = products[products['id'] == material['material_id']]
        
        if mat_product.empty:
            continue
        
        mat_info = mat_product.iloc[0]
        alternatives = material.get('alternatives', [])
        
        # Material card
        with st.container():
            col1, col2, col3, col4, col5, col6, col7 = st.columns([3, 1.5, 1, 0.8, 0.8, 0.8, 0.8])
            
            with col1:
                alt_badge = f" 🔀 **{len(alternatives)} alt(s)**" if alternatives else ""
                mat_display = format_product_display(
                    code=mat_info['code'],
                    name=mat_info['name'],
                    package_size=mat_info.get('package_size'),
                    brand=mat_info.get('brand'),
                    legacy_code=mat_info.get('legacy_code')
                )
                st.markdown(f"**{mat_display}**{alt_badge}")
            
            with col2:
                st.text(material['material_type'])
            
            with col3:
                st.text(f"{format_number(material['quantity'], 4)}")
            
            with col4:
                st.text(material['uom'])
            
            with col5:
                st.text(f"{material['scrap_rate']}%")
            
            with col6:
                # Alternative button
                if st.button("🔀", key=f"alt_btn_{idx}", help="Manage alternatives"):
                    # Toggle alternative section visibility
                    alt_key = f"show_alt_{idx}"
                    if alt_key not in st.session_state:
                        st.session_state[alt_key] = False
                    st.session_state[alt_key] = not st.session_state[alt_key]
                    st.rerun()
            
            with col7:
                if st.button("🗑️", key=f"del_btn_{idx}", help="Remove material"):
                    state.remove_create_material(idx)
                    st.rerun()
        
        # Show alternatives section if toggled
        alt_key = f"show_alt_{idx}"
        if st.session_state.get(alt_key, False):
            with st.expander(f"   ↳ Alternatives for Material #{idx+1}", expanded=True):
                _render_alternatives_section_optimized(idx, material, alternatives, state)
        
        st.markdown("")


def _render_alternatives_section_optimized(material_idx: int, material: dict, 
                                          alternatives: list, state: StateManager):
    """Render alternatives section for a material - Using Form"""
    
    # Display existing alternatives
    if alternatives:
        st.markdown("**Current Alternatives:**")
        
        for alt_idx, alt in enumerate(alternatives):
            alt_product = get_product_by_id(alt['alternative_material_id'])
            if alt_product:
                col1, col2, col3, col4, col5 = st.columns([3, 1, 1, 1, 1])
                
                with col1:
                    alt_display = format_product_display(
                        code=alt_product['code'],
                        name=alt_product['name'],
                        package_size=alt_product.get('package_size'),
                        brand=alt_product.get('brand'),
                        legacy_code=alt_product.get('legacy_code')
                    )
                    st.text(f"P{alt['priority']}: {alt_display}")
                
                with col2:
                    st.text(f"{format_number(alt['quantity'], 4)}")
                
                with col3:
                    st.text(alt['uom'])
                
                with col4:
                    st.text(f"{alt['scrap_rate']}%")
                
                with col5:
                    if st.button("❌", key=f"del_alt_{material_idx}_{alt_idx}"):
                        materials = state.get_create_materials()
                        materials[material_idx]['alternatives'].pop(alt_idx)
                        state.set_dialog_state(state.DIALOG_CREATE, {
                            'step': state.get_create_step(),
                            'header_data': state.get_create_header_data(),
                            'materials': materials
                        })
                        st.rerun()
        
        st.markdown("---")
    
    # Add alternative form
    st.markdown("**Add Alternative:**")
    
    # Get all material IDs already used in this BOM (primary + alternatives)
    all_materials = state.get_create_materials()
    used_material_ids = get_all_material_ids_in_bom_list(all_materials)
    
    # Get output product ID to exclude (prevent circular dependency)
    header_data = state.get_create_header_data()
    output_product_id = header_data.get('product_id')
    
    with st.form(f"add_alternative_form_{material_idx}", clear_on_submit=True):
        products = get_cached_products()
        
        col1, col2, col3, col4, col5 = st.columns([3, 1, 1, 1, 1])
        
        with col1:
            # Filter products to exclude ALL materials already in BOM AND output product
            product_options = filter_available_materials_excluding_output(
                products, used_material_ids, output_product_id
            )
            
            if not product_options:
                st.warning("⚠️ No available materials (all products already used in this BOM)")
                selected_alt = None
                alt_material_id = None
                alt_uom = 'PCS'
            else:
                selected_alt = st.selectbox(
                    "Alternative Material",
                    options=list(product_options.keys()),
                    key=f"alt_select_{material_idx}"
                )
                
                alt_info = product_options.get(selected_alt)
                alt_material_id = alt_info['id'] if alt_info else None
                alt_uom = alt_info['uom'] if alt_info else 'PCS'
        
        with col2:
            quantity = st.number_input(
                "Qty",
                min_value=0.0001,
                value=material['quantity'],
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
                value=material['scrap_rate'],
                step=0.5
            )
        
        with col5:
            next_priority = len(alternatives) + 1
            priority = st.number_input(
                "Priority",
                min_value=1,
                max_value=99,
                value=next_priority
            )
        
        add_alt_button = st.form_submit_button("➕ Add", use_container_width=True, disabled=not product_options)
    
    # Handle add alternative
    if add_alt_button and alt_material_id:
        # Validate not duplicate
        is_valid, error_msg = validate_material_not_duplicate(alt_material_id, used_material_ids)
        
        if not is_valid:
            st.error(f"❌ {error_msg}")
            return
        
        # Validate not output product (circular dependency check)
        is_valid_output, error_msg_output = validate_material_not_output_product(alt_material_id, output_product_id)
        if not is_valid_output:
            st.error(f"❌ {error_msg_output}")
            return
        
        if not validate_quantity(quantity) or not validate_percentage(scrap):
            st.error("❌ Invalid quantity or scrap rate")
            return
        
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


def _render_add_material_form_optimized(state: StateManager):
    """Render add material form - Using Form Container"""
    st.markdown("**Add Material:**")
    
    # Get all material IDs already used in this BOM (primary + alternatives)
    current_materials = state.get_create_materials()
    used_material_ids = get_all_material_ids_in_bom_list(current_materials)
    
    # Get output product ID to exclude (prevent circular dependency)
    header_data = state.get_create_header_data()
    output_product_id = header_data.get('product_id')
    
    with st.form("add_material_form", clear_on_submit=True):
        products = get_cached_products()
        
        if products.empty:
            st.error("❌ No products available")
            return
        
        col1, col2, col3, col4, col5 = st.columns([3, 2, 1, 1, 1])
        
        with col1:
            # Filter products to exclude materials already in BOM AND output product
            product_options = filter_available_materials_excluding_output(
                products, used_material_ids, output_product_id
            )
            
            if not product_options:
                st.warning("⚠️ No available materials (all products already used in this BOM)")
                selected_material = None
                material_id = None
                mat_uom = 'PCS'
            else:
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
        
        add_button = st.form_submit_button("➕ Add Material", use_container_width=True, disabled=not product_options)
    
    # Handle form submission
    if add_button and material_id:
        # Validate not duplicate
        is_valid, error_msg = validate_material_not_duplicate(material_id, used_material_ids)
        
        if not is_valid:
            st.error(f"❌ {error_msg}")
            return
        
        # Validate not output product (circular dependency check)
        is_valid_output, error_msg_output = validate_material_not_output_product(material_id, output_product_id)
        if not is_valid_output:
            st.error(f"❌ {error_msg_output}")
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
        
        # Final validation: materials structure
        can_create, validation_error = validate_materials_for_bom(materials)
        
        if not can_create:
            st.error(f"❌ {validation_error}")
            return
        
        # Final validation: output product not in materials (circular dependency)
        output_product_id = header_data.get('product_id')
        is_valid, error_msg, _ = validate_output_not_in_materials(output_product_id, materials)
        
        if not is_valid:
            st.error(f"❌ {error_msg}")
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