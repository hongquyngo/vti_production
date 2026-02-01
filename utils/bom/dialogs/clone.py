# utils/bom/dialogs/clone.py
"""
Clone BOM Dialog - Create new BOM from existing template - VERSION 2.2
2-step wizard: Review/Edit Header → Review/Edit Materials

Changes in v2.2:
- Added circular dependency validation: output product cannot be used as input material
- Validation when changing output product (check conflict with existing materials)
- Final validation before clone creation

Changes in v2.1:
- Added info banner when selecting product that already has Active BOM
- Non-blocking informational warning for conflict awareness
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
    create_status_indicator,
    # Active BOM conflict detection
    get_active_boms_for_product,
    # Output product vs materials validation (circular dependency prevention)
    validate_output_not_in_materials,
    check_materials_conflict_with_new_output
)

logger = logging.getLogger(__name__)

# Cache product list
@st.cache_data(ttl=300)
def get_cached_products():
    """Get cached product list"""
    return get_products()


def _render_active_bom_info_banner(active_boms: list, exclude_bom_code: str = None):
    """
    Render info banner when product already has active BOM(s)
    Non-blocking informational warning
    
    Args:
        active_boms: List of active BOM info dicts
        exclude_bom_code: BOM code to exclude from display (source BOM for clone)
    """
    # Filter out source BOM if specified
    display_boms = active_boms
    if exclude_bom_code:
        display_boms = [b for b in active_boms if b['bom_code'] != exclude_bom_code]
    
    if not display_boms:
        return
    
    count = len(display_boms)
    bom_codes = [bom['bom_code'] for bom in display_boms]
    bom_codes_str = ", ".join(bom_codes[:3])  # Show max 3 codes
    if count > 3:
        bom_codes_str += f" (+{count - 3} more)"
    
    st.info(
        f"ℹ️ **This product already has {count} active BOM(s):** {bom_codes_str}\n\n"
        f"New BOM will be created as **DRAFT**. You can activate it later."
    )


@st.dialog("🔄 Clone BOM", width="large")
def show_clone_dialog(source_bom_id: int):
    """Clone BOM wizard dialog - Create new BOM from existing"""
    state = StateManager()
    manager = BOMManager()
    
    # Initialize clone state if needed
    if 'clone_step' not in st.session_state:
        st.session_state['clone_step'] = 1
    
    if 'clone_data' not in st.session_state:
        try:
            # Load source BOM data
            source_data = manager.get_bom_complete_data(source_bom_id)
            
            # Initialize with source data
            st.session_state['clone_data'] = {
                'source_bom_id': source_bom_id,
                'source_code': source_data['header']['bom_code'],
                'header': {
                    'bom_name': f"{source_data['header']['bom_name']} - Copy",
                    'bom_type': source_data['header']['bom_type'],
                    'product_id': source_data['header']['product_id'],
                    'output_qty': source_data['header']['output_qty'],
                    'uom': source_data['header']['uom'],
                    'effective_date': date.today(),
                    'notes': f"Cloned from {source_data['header']['bom_code']}"
                },
                'materials': source_data['materials']
            }
        except Exception as e:
            st.error(f"❌ Error loading source BOM: {str(e)}")
            if st.button("Close", key="clone_error_close"):
                _cleanup_clone_state()
                state.close_dialog()
                st.rerun()
            return
    
    current_step = st.session_state['clone_step']
    
    # Render step indicator
    render_step_indicator(current_step, 2)
    st.markdown("---")
    
    # Show source BOM info
    st.info(f"📋 Cloning from: **{st.session_state['clone_data']['source_code']}**")
    st.markdown("---")
    
    # Render current step
    if current_step == 1:
        _render_step1_clone_header()
    elif current_step == 2:
        _render_step2_clone_materials(manager)


def _render_step1_clone_header():
    """Step 1: Review and edit BOM header information"""
    st.markdown("### Step 1: BOM Information")
    st.caption("Review and modify the header information for the new BOM")
    
    clone_data = st.session_state['clone_data']
    header_data = clone_data['header']
    materials = clone_data.get('materials', [])
    source_code = clone_data.get('source_code', '')
    products = get_cached_products()
    
    # =====================================================
    # INFO BANNER: Check if selected product has active BOM
    # =====================================================
    product_id = header_data.get('product_id')
    if product_id:
        active_boms = get_active_boms_for_product(product_id)
        if active_boms:
            _render_active_bom_info_banner(active_boms, exclude_bom_code=source_code)
    
    with st.form("clone_bom_header_form", clear_on_submit=False):
        col1, col2 = st.columns(2)
        
        with col1:
            bom_name = st.text_input(
                "BOM Name *",
                value=header_data['bom_name'],
                placeholder="Enter BOM name"
            )
            
            bom_type = st.selectbox(
                "BOM Type *",
                options=["KITTING", "CUTTING", "REPACKING"],
                index=["KITTING", "CUTTING", "REPACKING"].index(header_data['bom_type'])
            )
            
            effective_date = st.date_input(
                "Effective Date",
                value=header_data['effective_date']
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
                for idx, (display, info) in enumerate(product_options.items()):
                    if info['id'] == header_data['product_id']:
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
                value=header_data['output_qty'],
                step=1.0,
                format="%.2f"
            )
            
            st.text_input("UOM", value=uom, disabled=True)
        
        notes = st.text_area(
            "Notes",
            value=header_data['notes'],
            placeholder="Optional notes...",
            height=80
        )
        
        st.markdown("---")
        
        col1, col2, col3 = st.columns([2, 1, 1])
        
        with col1:
            cancel_button = st.form_submit_button("❌ Cancel", use_container_width=True)
        
        with col2:
            # No back button on step 1
            pass
        
        with col3:
            next_button = st.form_submit_button(
                "Next: Review Materials →",
                type="primary",
                use_container_width=True
            )
    
    # Handle form submission
    if next_button:
        # Validate basic fields
        errors = []
        if not bom_name or len(bom_name.strip()) == 0:
            errors.append("BOM name is required")
        if not product_id:
            errors.append("Output product is required")
        if output_qty <= 0:
            errors.append("Output quantity must be greater than 0")
        
        # Validate output product not in materials (circular dependency)
        if product_id and materials:
            has_conflict, conflicts = check_materials_conflict_with_new_output(materials, product_id)
            if has_conflict:
                conflict_details = []
                for c in conflicts:
                    if c['type'] == 'PRIMARY':
                        conflict_details.append(f"Primary material #{c['index'] + 1}")
                    else:
                        conflict_details.append(f"Alternative P{c['priority']} of material #{c['index'] + 1}")
                errors.append(f"Output product cannot be used as input material (circular dependency). Found in: {', '.join(conflict_details)}")
        
        if errors:
            for error in errors:
                st.error(f"❌ {error}")
        else:
            # Save header data
            st.session_state['clone_data']['header'] = {
                'bom_name': bom_name,
                'bom_type': bom_type,
                'product_id': product_id,
                'output_qty': output_qty,
                'uom': uom,
                'effective_date': effective_date,
                'notes': notes
            }
            
            # Move to next step
            st.session_state['clone_step'] = 2
            st.rerun()
    
    if cancel_button:
        _cleanup_clone_state()
        StateManager().close_dialog()
        st.rerun()


def _render_step2_clone_materials(manager: BOMManager):
    """Step 2: Review and edit materials"""
    st.markdown("### Step 2: Review Materials")
    st.caption("Review the materials that will be copied to the new BOM")
    
    clone_data = st.session_state['clone_data']
    header_data = clone_data['header']
    materials = clone_data['materials']
    source_code = clone_data.get('source_code', '')
    
    # =====================================================
    # INFO BANNER: Check if selected product has active BOM
    # =====================================================
    product_id = header_data.get('product_id')
    if product_id:
        active_boms = get_active_boms_for_product(product_id)
        if active_boms:
            _render_active_bom_info_banner(active_boms, exclude_bom_code=source_code)
    
    # Header summary
    with st.expander("📋 New BOM Information", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            st.write(f"**Name:** {header_data['bom_name']}")
            st.write(f"**Type:** {header_data['bom_type']}")
        with col2:
            st.write(f"**Output:** {header_data['output_qty']} {header_data['uom']}")
            st.write(f"**Effective:** {header_data['effective_date']}")
    
    st.markdown("---")
    
    # Material counter
    st.markdown("### 📊 Material Summary")
    render_material_type_counter(materials, show_warning=True)
    
    st.markdown("---")
    
    # Display materials
    if materials:
        st.markdown(f"**Materials to be copied ({len(materials)}):**")
        _render_clone_materials_list(materials)
    else:
        st.warning("⚠️ No materials to copy")
    
    st.markdown("---")
    
    # Options for cloning
    st.markdown("### Clone Options")
    col1, col2 = st.columns(2)
    
    with col1:
        keep_quantities = st.checkbox(
            "Keep original quantities",
            value=True,
            key="clone_keep_quantities",
            help="Use the same quantities as the source BOM"
        )
    
    with col2:
        keep_alternatives = st.checkbox(
            "Copy alternative materials",
            value=True,
            key="clone_keep_alternatives",
            help="Include all alternative materials from source BOM"
        )
    
    st.markdown("---")
    
    # Validate materials
    can_create, validation_error = validate_materials_for_bom(materials)
    
    # Action buttons
    col1, col2, col3, col4 = st.columns([1.5, 1, 1, 1])
    
    with col1:
        if st.button("❌ Cancel", use_container_width=True):
            _cleanup_clone_state()
            StateManager().close_dialog()
            st.rerun()
    
    with col2:
        if st.button("← Back", use_container_width=True):
            st.session_state['clone_step'] = 1
            st.rerun()
    
    with col3:
        pass  # Spacer
    
    with col4:
        if st.button(
            "✅ Create Clone",
            type="primary",
            use_container_width=True,
            disabled=not can_create
        ):
            if can_create:
                _handle_clone_bom(manager)
            else:
                st.error(f"❌ {validation_error}")
    
    if not can_create:
        st.error(f"❌ {validation_error}")


def _render_clone_materials_list(materials: list):
    """Render materials list for review"""
    products = get_cached_products()
    
    for idx, material in enumerate(materials):
        # Get product info
        mat_product = products[products['id'] == material['material_id']]
        
        if mat_product.empty:
            continue
        
        mat_info = mat_product.iloc[0]
        alternatives = material.get('alternatives', [])
        
        # Material card
        with st.container():
            col1, col2, col3, col4, col5, col6 = st.columns([3.5, 1.5, 1, 0.8, 0.8, 0.8])
            
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
                # Remove button
                if st.button("🗑️", key=f"clone_remove_{idx}", help="Remove from clone"):
                    st.session_state['clone_data']['materials'].pop(idx)
                    st.rerun()
        
        # Show alternatives if any
        if alternatives and st.session_state.get('clone_keep_alternatives', True):
            with st.expander(f"   ↳ {len(alternatives)} Alternative(s)", expanded=False):
                for alt in alternatives:
                    # Support both 'alternative_material_id' and 'material_id' keys
                    alt_mat_id = alt.get('alternative_material_id') or alt.get('material_id')
                    alt_product = get_product_by_id(alt_mat_id)
                    if alt_product:
                        alt_display = format_product_display(
                            code=alt_product['code'],
                            name=alt_product['name'],
                            package_size=alt_product.get('package_size'),
                            brand=alt_product.get('brand'),
                            legacy_code=alt_product.get('legacy_code')
                        )
                        st.text(
                            f"   P{alt['priority']}: {alt_display} | "
                            f"Qty: {format_number(alt['quantity'], 4)} | "
                            f"Scrap: {alt['scrap_rate']}%"
                        )
        
        st.markdown("")


def _handle_clone_bom(manager: BOMManager):
    """Handle BOM cloning"""
    state = StateManager()
    
    try:
        clone_data = st.session_state['clone_data']
        header_data = clone_data['header']
        materials = clone_data['materials']
        
        # Remove alternatives if not keeping them
        if not st.session_state.get('clone_keep_alternatives', True):
            for material in materials:
                material['alternatives'] = []
        
        # Final validation: output product not in materials (circular dependency)
        output_product_id = header_data.get('product_id')
        is_valid, error_msg, _ = validate_output_not_in_materials(output_product_id, materials)
        
        if not is_valid:
            st.error(f"❌ {error_msg}")
            return
        
        # Prepare clone data
        user_id = st.session_state.get('user_id', 1)
        
        clone_request = {
            'bom_name': header_data['bom_name'],
            'bom_type': header_data['bom_type'],
            'product_id': header_data['product_id'],
            'output_qty': header_data['output_qty'],
            'uom': header_data['uom'],
            'effective_date': header_data['effective_date'],
            'notes': header_data['notes'],
            'created_by': user_id
        }
        
        # Clone the BOM
        state.set_loading(True)
        new_bom_code = manager.clone_bom(
            clone_data['source_bom_id'],
            clone_request
        )
        state.set_loading(False)
        
        # Record action
        state.record_action('clone', bom_code=new_bom_code)
        
        # Show success
        state.show_success(
            f"✅ BOM cloned successfully! New BOM: {new_bom_code}"
        )
        
        # Cleanup and close
        _cleanup_clone_state()
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
        logger.error(f"Unexpected error cloning BOM: {e}")
        st.error(f"❌ Unexpected error: {str(e)}")


def _cleanup_clone_state():
    """Clean up clone dialog state"""
    if 'clone_step' in st.session_state:
        del st.session_state['clone_step']
    if 'clone_data' in st.session_state:
        del st.session_state['clone_data']
    if 'clone_keep_quantities' in st.session_state:
        del st.session_state['clone_keep_quantities']
    if 'clone_keep_alternatives' in st.session_state:
        del st.session_state['clone_keep_alternatives']