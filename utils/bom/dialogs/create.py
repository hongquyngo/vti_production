# utils/bom/dialogs/create.py
"""
Create BOM Dialog - FIXED BUTTON KEYS
2-step wizard: Header information → Materials
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
    render_step_indicator,
    validate_quantity,
    validate_percentage
)

logger = logging.getLogger(__name__)


@st.dialog("➕ Create New BOM", width="large")
def show_create_dialog():
    """
    Create BOM wizard dialog (2 steps)
    Step 1: BOM header information
    Step 2: Materials
    """
    state = StateManager()
    manager = BOMManager()
    
    # Get current step
    current_step = state.get_create_step()
    
    # Render step indicator
    render_step_indicator(current_step, 2)
    st.markdown("---")
    
    # Render appropriate step
    if current_step == 1:
        _render_step1_header(state)
    elif current_step == 2:
        _render_step2_materials(state, manager)


def _render_step1_header(state: StateManager):
    """
    Render Step 1: BOM Header Information
    
    Args:
        state: State manager
    """
    st.markdown("### Step 1: BOM Information")
    
    # Get saved data if any
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
        # Product selection
        products = get_products()
        
        if products.empty:
            st.error("❌ No products found")
            product_id = None
            uom = 'PCS'
        else:
            product_options = {
                f"{row['name']} ({row['code']})": row['id']
                for _, row in products.iterrows()
            }
            
            # Find default index
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
            
            # Get product UOM
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
    
    # Notes
    notes = st.text_area(
        "Notes",
        value=saved_data.get('notes', ''),
        placeholder="Optional notes...",
        height=80,
        key="create_notes"
    )
    
    st.markdown("---")
    
    # Navigation buttons
    col1, col2 = st.columns([3, 1])
    
    with col2:
        if st.button("Next: Add Materials →", type="primary", use_container_width=True, key="create_step1_next"):
            # Validate step 1
            errors = _validate_step1(bom_name, product_id, output_qty)
            
            if errors:
                for error in errors:
                    st.error(f"❌ {error}")
            else:
                # Save header data
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
    """
    Render Step 2: Materials
    
    Args:
        state: State manager
        manager: BOM manager
    """
    st.markdown("### Step 2: Add Materials")
    
    # Show header summary
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
    
    # Current materials list
    materials = state.get_create_materials()
    
    if materials:
        st.markdown(f"**Materials Added ({len(materials)}):**")
        _render_material_list(materials, state)
    else:
        st.info("ℹ️ No materials added yet. Add at least one material below.")
    
    st.markdown("---")
    
    # Add material form
    _render_add_material_form(state)
    
    st.markdown("---")
    
    # Navigation buttons
    col1, col2, col3 = st.columns([2, 1, 1])
    
    with col1:
        if st.button("← Back to Information", use_container_width=True, key="create_step2_back"):
            state.set_create_step(1)
            st.rerun()
    
    with col2:
        if st.button("✅ Create BOM", type="primary", use_container_width=True, key="create_step2_create"):
            _handle_create_bom(state, manager)
    
    with col3:
        if st.button("❌ Cancel", use_container_width=True, key="create_step2_cancel"):
            state.close_dialog()
            st.rerun()


def _render_material_list(materials: list, state: StateManager):
    """
    Render current materials list
    
    Args:
        materials: List of material dicts
        state: State manager
    """
    # Convert to DataFrame for display
    materials_df = pd.DataFrame(materials)
    
    # Get product info
    products = get_products()
    mat_ids = materials_df['material_id'].tolist()
    mat_info = products[products['id'].isin(mat_ids)][['id', 'name', 'code']]
    
    materials_df = materials_df.merge(
        mat_info, 
        left_on='material_id', 
        right_on='id', 
        how='left'
    )
    
    # Display table
    for idx, material in materials_df.iterrows():
        col1, col2, col3, col4, col5, col6 = st.columns([3, 2, 1, 1, 1, 1])
        
        with col1:
            st.text(f"{material['name']} ({material['code']})")
        
        with col2:
            st.text(material['material_type'])
        
        with col3:
            st.text(f"{material['quantity']:.4f}")
        
        with col4:
            st.text(material['uom'])
        
        with col5:
            st.text(f"{material['scrap_rate']:.2f}%")
        
        with col6:
            if st.button("🗑️", key=f"create_remove_mat_{idx}", help="Remove"):
                state.remove_create_material(idx)
                st.rerun()


def _render_add_material_form(state: StateManager):
    """
    Render add material form with clear labels
    
    Args:
        state: State manager
    """
    st.markdown("**Add Material:**")
    
    # ✅ ADD HEADER ROW FOR CLARITY
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
        
        selected_material = st.selectbox(
            "Material",
            options=list(product_options.keys()),
            key="create_add_material_select",
            label_visibility="collapsed",  # Hide redundant label since we have header
            help="Select the material/component to add"
        )
        
        material_id = product_options.get(selected_material)
    
    with col2:
        material_type = st.selectbox(
            "Type",
            options=["RAW_MATERIAL", "PACKAGING", "CONSUMABLE"],
            key="create_add_material_type",
            label_visibility="collapsed",
            help="Material classification type"
        )
    
    with col3:
        quantity = st.number_input(
            "Quantity",
            min_value=0.0001,
            value=1.0,
            step=0.1,
            format="%.4f",
            key="create_add_material_qty",
            label_visibility="collapsed",
            help="Required quantity per output unit"
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
            label_visibility="collapsed",
            help="Expected waste/scrap percentage (0-100%)"  # ✅ Clear explanation
        )
    
    # Add button
    if st.button("➕ Add Material", key="create_add_material_btn", use_container_width=True):
        if not material_id:
            st.error("❌ Please select a material")
            return
        
        # Check duplicate
        current_materials = state.get_create_materials()
        if any(m['material_id'] == material_id for m in current_materials):
            st.error("❌ Material already added")
            return
        
        # Validate
        if not validate_quantity(quantity):
            st.error("❌ Invalid quantity")
            return
        
        if not validate_percentage(scrap_rate):
            st.error("❌ Invalid scrap rate (must be 0-100%)")
            return
        
        # Add material
        material_data = {
            'material_id': material_id,
            'material_type': material_type,
            'quantity': quantity,
            'uom': mat_uom,
            'scrap_rate': scrap_rate
        }
        
        state.add_create_material(material_data)
        st.success("✅ Material added!")
        st.rerun()

def _validate_step1(bom_name: str, product_id: int, output_qty: float) -> list:
    """
    Validate step 1 data
    
    Args:
        bom_name: BOM name
        product_id: Product ID
        output_qty: Output quantity
    
    Returns:
        List of error messages
    """
    errors = []
    
    if not bom_name or len(bom_name.strip()) == 0:
        errors.append("BOM name is required")
    
    if not product_id:
        errors.append("Output product is required")
    
    if not validate_quantity(output_qty):
        errors.append("Output quantity must be greater than 0")
    
    return errors


def _handle_create_bom(state: StateManager, manager: BOMManager):
    """
    Handle BOM creation
    
    Args:
        state: State manager
        manager: BOM manager
    """
    try:
        # Get data
        header_data = state.get_create_header_data()
        materials = state.get_create_materials()
        
        # Validate materials
        if not materials:
            st.error("❌ At least one material is required")
            return
        
        # Prepare BOM data
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
        
        # Create BOM
        state.set_loading(True)
        bom_code = manager.create_bom(bom_data)
        state.set_loading(False)
        
        # Record action
        state.record_action('create', bom_code=bom_code)
        
        # Show success
        state.show_success(f"✅ BOM {bom_code} created successfully!")
        
        # Close dialog
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