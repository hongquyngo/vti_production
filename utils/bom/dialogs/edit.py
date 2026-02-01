# utils/bom/dialogs/edit.py
"""
Edit BOM Dialog with Usage-based Edit Levels - VERSION 2.2

Edit permission based on ACTUAL IMPACT, not just STATUS:
- Level 4 (FULL_EDIT): DRAFT always, or ACTIVE/INACTIVE with no usage
- Level 2 (ALTERNATIVES_PLUS): ACTIVE with IN_PROGRESS orders
- Level 0 (READ_ONLY): Has completed orders or inactive with history

Changes in v2.2:
- Added circular dependency validation: output product cannot be used as input material
- Filter output product from material/alternative selection lists

Changes in v2.1:
- Updated all product/material displays to use format_product_display with legacy_code
- Unified display format: code (legacy | N/A) | name | pkg (brand)

Changes in v2.0:
- Replaced status-based logic with usage-based edit levels
- ACTIVE BOMs without usage now have full edit capability
- BOMs with completed orders are read-only (create new BOM instead)
- Added usage context display
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
    validate_materials_for_bom,
    # New imports for edit levels
    EditLevel,
    get_edit_level,
    get_edit_level_description,
    can_edit_field,
    render_edit_level_indicator,
    render_usage_context,
    # Duplicate validation helpers
    get_all_material_ids_in_bom_db,
    validate_material_not_duplicate,
    filter_available_materials,
    # Duplicate detection for warning
    detect_duplicate_materials_in_bom,
    render_duplicate_warning_section,
    # Output product vs materials validation (circular dependency prevention)
    validate_material_not_output_product,
    filter_available_materials_excluding_output
)

logger = logging.getLogger(__name__)

# Cache product list to avoid repeated queries
@st.cache_data(ttl=300)  # Cache for 5 minutes
def get_cached_products():
    """Get cached product list"""
    return get_products()


@st.dialog("✏️ Edit BOM", width="large")
def show_edit_dialog(bom_id: int):
    """
    Edit BOM dialog with usage-based edit levels
    
    Edit levels are determined by actual impact:
    - FULL_EDIT: Can modify everything (DRAFT or never used)
    - ALTERNATIVES_PLUS: Only alternatives (has active orders)
    - READ_ONLY: View only (has completed orders)
    """
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
        
        # Check for duplicate materials and show warning at top
        duplicate_info = detect_duplicate_materials_in_bom(bom_id)
        if duplicate_info.get('has_duplicates'):
            render_duplicate_warning_section(duplicate_info)
            st.markdown("---")
        
        # Determine edit level based on status AND usage
        edit_level = get_edit_level(bom_info)
        
        # Render header with edit level indicator
        _render_edit_header(bom_info, edit_level)
        
        st.markdown("---")
        
        # Render based on edit level
        if edit_level == EditLevel.FULL_EDIT:
            _render_full_edit_mode(bom_id, bom_info, bom_details, state, manager)
        
        elif edit_level == EditLevel.ALTERNATIVES_PLUS:
            _render_alternatives_mode(bom_id, bom_info, bom_details, state, manager)
        
        else:  # READ_ONLY
            _render_read_only_mode(bom_id, bom_info, bom_details, state, manager)
    
    except Exception as e:
        logger.error(f"Error in edit dialog: {e}")
        st.error(f"❌ Error: {str(e)}")
        
        if st.button("Close", key=f"edit_exception_close_{bom_id}"):
            state.close_dialog()
            st.rerun()


def _render_edit_header(bom_info: dict, edit_level: int):
    """Render dialog header with status and edit level info"""
    # Title
    st.markdown(f"### {EditLevel.ICONS.get(edit_level, '📋')} {bom_info['bom_code']} - {bom_info['bom_name']}")
    
    # Status and usage context
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.markdown(f"**Status:** {create_status_indicator(bom_info['status'])}")
    
    with col2:
        total_usage = int(bom_info.get('total_usage', 0))
        active_orders = int(bom_info.get('active_orders', 0))
        if total_usage > 0:
            st.markdown(f"**Usage:** {total_usage} order(s) ({active_orders} active)")
        else:
            st.markdown("**Usage:** Never used")
    
    # Edit level indicator
    render_edit_level_indicator(edit_level, bom_info)


# ==================== FULL EDIT MODE ====================

def _render_full_edit_mode(bom_id: int, bom_info: dict, bom_details: pd.DataFrame,
                           state: StateManager, manager: BOMManager):
    """Render full edit mode - all fields editable"""
    
    # Tabs for different sections
    tab1, tab2 = st.tabs(["📄 BOM Information", "🧱 Materials & Alternatives"])
    
    with tab1:
        _render_info_tab_editable(bom_id, bom_info, state, manager)
    
    with tab2:
        _render_materials_tab_full_edit(bom_id, bom_details, state, manager)


def _render_info_tab_editable(bom_id: int, bom_info: dict, state: StateManager, manager: BOMManager):
    """Render editable BOM information tab"""
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
            
            new_effective = st.date_input(
                "Effective Date",
                value=bom_info['effective_date'] if bom_info['effective_date'] else date.today()
            )
        
        with col2:
            st.text_input("BOM Code", value=bom_info['bom_code'], disabled=True)
            st.text_input("BOM Type", value=bom_info['bom_type'], disabled=True)
            # Format product display with full info
            product_display = format_product_display(
                code=bom_info.get('product_code', ''),
                name=bom_info.get('product_name', ''),
                package_size=bom_info.get('package_size'),
                brand=bom_info.get('brand'),
                legacy_code=bom_info.get('legacy_code')
            )
            st.text_input("Product", value=product_display, disabled=True)
        
        new_notes = st.text_area(
            "Notes",
            value=bom_info.get('notes', ''),
            height=100
        )
        
        col_save, col_cancel = st.columns([1, 1])
        
        with col_save:
            save_button = st.form_submit_button("💾 Save Changes", type="primary", use_container_width=True)
        
        with col_cancel:
            cancel_button = st.form_submit_button("❌ Cancel", use_container_width=True)
    
    # Handle form submission
    if save_button:
        _handle_save_info(bom_id, bom_info, new_name, new_output_qty, new_effective, new_notes, state, manager)
    
    if cancel_button:
        state.close_dialog()
        st.rerun()


def _handle_save_info(bom_id: int, bom_info: dict, new_name: str, new_output_qty: float,
                      new_effective: date, new_notes: str, state: StateManager, manager: BOMManager):
    """Handle saving BOM information changes"""
    if not new_name:
        st.error("❌ BOM Name is required")
        return
    
    if new_output_qty <= 0:
        st.error("❌ Output quantity must be positive")
        return
    
    try:
        user_id = st.session_state.get('user_id', 1)
        
        update_data = {
            'bom_name': new_name,
            'output_qty': new_output_qty,
            'effective_date': new_effective,
            'notes': new_notes,
            'updated_by': user_id
        }
        
        manager.update_bom_header(bom_id, update_data, user_id)
        
        state.record_action('edit', bom_id=bom_id, bom_code=bom_info['bom_code'])
        state.clear_bom_list_cache()
        st.success("✅ BOM information updated successfully!")
        st.rerun()
    
    except BOMValidationError as e:
        st.error(f"❌ Validation Error: {str(e)}")
    except Exception as e:
        logger.error(f"Error saving BOM info: {e}")
        st.error(f"❌ Error: {str(e)}")


def _render_materials_tab_full_edit(bom_id: int, bom_details: pd.DataFrame,
                                     state: StateManager, manager: BOMManager):
    """Render materials tab with full editing capability"""
    st.markdown("### Materials & Alternatives")
    
    if bom_details.empty:
        st.info("ℹ️ No materials in this BOM. Add materials below.")
    else:
        # Material type counter
        materials_list = bom_details.to_dict('records')
        render_material_type_counter(materials_list, show_warning=True)
        
        st.markdown("---")
        
        # Display each material with edit/delete options
        for idx, material in bom_details.iterrows():
            _render_material_card_full_edit(bom_id, material, state, manager)
    
    st.markdown("---")
    
    # Add new material form
    _render_add_material_form(bom_id, state, manager)
    
    st.markdown("---")
    
    # Close button
    if st.button("✔ Close", use_container_width=True, key="full_edit_close"):
        state.close_dialog()
        st.rerun()


def _render_material_card_full_edit(bom_id: int, material: pd.Series, state: StateManager, manager: BOMManager):
    """Render material card with full edit options"""
    detail_id = int(material['id'])
    alt_count = int(material.get('alternatives_count', 0))
    
    with st.container():
        col1, col2, col3, col4, col5, col6 = st.columns([3, 1.5, 1, 0.8, 0.8, 0.8])
        
        with col1:
            alt_badge = f" 🔀 **{alt_count}**" if alt_count > 0 else ""
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
            # Delete button
            if st.button("🗑️", key=f"del_mat_{detail_id}", help="Remove material"):
                try:
                    user_id = st.session_state.get('user_id', 1)
                    manager.delete_bom_material(detail_id, user_id)
                    st.success("✅ Material removed")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Error: {str(e)}")
    
    # Expandable alternatives section
    with st.expander(f"🔀 Manage Alternatives ({alt_count})", expanded=False):
        _render_alternatives_manager(bom_id, detail_id, material, manager)
    
    st.markdown("")


def _render_alternatives_manager(bom_id: int, detail_id: int, material: pd.Series, manager: BOMManager):
    """Render alternatives management section"""
    try:
        alternatives = manager.get_material_alternatives(detail_id)
        
        if not alternatives.empty:
            for _, alt in alternatives.iterrows():
                col1, col2, col3, col4, col5, col6 = st.columns([3, 1, 1, 0.8, 0.8, 0.6])
                
                with col1:
                    status_icon = "✅" if alt['is_active'] else "⭕"
                    alt_display = format_product_display(
                        code=alt.get('material_code', ''),
                        name=alt.get('material_name', ''),
                        package_size=alt.get('package_size'),
                        brand=alt.get('brand'),
                        legacy_code=alt.get('legacy_code')
                    )
                    st.text(f"{status_icon} P{alt['priority']}: {alt_display}")
                
                with col2:
                    st.text(f"{format_number(alt['quantity'], 4)}")
                
                with col3:
                    st.text(alt['uom'])
                
                with col4:
                    st.text(f"{format_number(alt['scrap_rate'], 2)}%")
                
                with col5:
                    stock = float(alt['current_stock'])
                    if stock > 0:
                        st.text(f"📦 {format_number(stock, 0)}")
                    else:
                        st.text("📦 0")
                
                with col6:
                    if st.button("🗑️", key=f"del_alt_{alt['id']}", help="Remove alternative"):
                        try:
                            user_id = st.session_state.get('user_id', 1)
                            manager.delete_material_alternative(alt['id'], user_id)
                            st.success("✅ Alternative removed")
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Error: {str(e)}")
        else:
            st.info("ℹ️ No alternatives defined")
        
        st.markdown("---")
        
        # Add alternative form
        _render_add_alternative_form(bom_id, detail_id, material, manager)
    
    except Exception as e:
        logger.error(f"Error rendering alternatives: {e}")
        st.error(f"❌ Error: {str(e)}")


def _render_add_alternative_form(bom_id: int, detail_id: int, material: pd.Series, manager: BOMManager):
    """Render form to add new alternative with duplicate and circular dependency validation"""
    st.markdown("**➕ Add Alternative:**")
    
    # Get all material IDs already used in this BOM (from database)
    used_material_ids = get_all_material_ids_in_bom_db(bom_id)
    
    # Get output product ID to exclude (prevent circular dependency)
    bom_info = manager.get_bom_info(bom_id)
    output_product_id = bom_info.get('product_id') if bom_info else None
    
    with st.form(f"add_alt_form_{detail_id}", clear_on_submit=True):
        products = get_cached_products()
        
        col1, col2, col3, col4, col5 = st.columns([3, 1, 1, 1, 1])
        
        with col1:
            # Filter products to exclude ALL materials already in BOM AND output product
            product_options = filter_available_materials_excluding_output(
                products, used_material_ids, output_product_id
            )
            
            if not product_options:
                st.warning("⚠️ No available materials (all products already used in this BOM)")
                selected = None
                alt_material_id = None
                alt_uom = 'PCS'
            else:
                selected = st.selectbox("Alternative Material", options=list(product_options.keys()))
                alt_info = product_options.get(selected)
                alt_material_id = alt_info['id'] if alt_info else None
                alt_uom = alt_info['uom'] if alt_info else 'PCS'
        
        with col2:
            quantity = st.number_input("Qty", min_value=0.0001, value=float(material['quantity']), step=0.1, format="%.4f")
        
        with col3:
            scrap = st.number_input("Scrap %", min_value=0.0, max_value=100.0, value=0.0, step=0.5)
        
        with col4:
            priority = st.number_input("Priority", min_value=1, max_value=99, value=1)
        
        with col5:
            is_active = st.checkbox("Active", value=True)
        
        notes = st.text_input("Notes (optional)")
        
        add_btn = st.form_submit_button("➕ Add Alternative", use_container_width=True, disabled=not product_options)
    
    if add_btn and alt_material_id:
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
        
        try:
            alternative_data = {
                'bom_detail_id': detail_id,
                'alternative_material_id': alt_material_id,
                'quantity': quantity,
                'scrap_rate': scrap,
                'priority': priority,
                'is_active': 1 if is_active else 0,
                'notes': notes if notes else None
            }
            
            manager.add_material_alternative(alternative_data)
            st.success("✅ Alternative added!")
            st.rerun()
        except Exception as e:
            st.error(f"❌ Error: {str(e)}")


def _render_add_material_form(bom_id: int, state: StateManager, manager: BOMManager):
    """Render form to add new material to BOM with duplicate and circular dependency validation"""
    st.markdown("### ➕ Add New Material")
    
    # Get all material IDs already used in this BOM (from database)
    used_material_ids = get_all_material_ids_in_bom_db(bom_id)
    
    # Get output product ID to exclude (prevent circular dependency)
    bom_info = manager.get_bom_info(bom_id)
    output_product_id = bom_info.get('product_id') if bom_info else None
    
    with st.form("add_material_form", clear_on_submit=True):
        products = get_cached_products()
        
        if products.empty:
            st.error("❌ No products available")
            st.form_submit_button("Add Material", disabled=True)
            return
        
        col1, col2, col3, col4, col5 = st.columns([3, 1.5, 1, 0.8, 0.8])
        
        with col1:
            # Filter products to exclude materials already in BOM AND output product
            product_options = filter_available_materials_excluding_output(
                products, used_material_ids, output_product_id
            )
            
            if not product_options:
                st.warning("⚠️ No available materials (all products already used in this BOM)")
                selected = None
                material_id = None
                material_uom = 'PCS'
            else:
                selected = st.selectbox("Material", options=list(product_options.keys()))
                mat_info = product_options.get(selected)
                material_id = mat_info['id'] if mat_info else None
                material_uom = mat_info['uom'] if mat_info else 'PCS'
        
        with col2:
            material_type = st.selectbox("Type", options=["RAW_MATERIAL", "PACKAGING", "CONSUMABLE"])
        
        with col3:
            quantity = st.number_input("Quantity", min_value=0.0001, value=1.0, step=0.1, format="%.4f")
        
        with col4:
            st.text_input("UOM", value=material_uom, disabled=True)
        
        with col5:
            scrap_rate = st.number_input("Scrap %", min_value=0.0, max_value=100.0, value=0.0, step=0.5)
        
        add_btn = st.form_submit_button("➕ Add Material", type="primary", use_container_width=True, disabled=not product_options)
    
    if add_btn and material_id:
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
        
        if not validate_quantity(quantity) or not validate_percentage(scrap_rate):
            st.error("❌ Invalid quantity or scrap rate")
            return
        
        try:
            material_data = {
                'bom_header_id': bom_id,
                'material_id': material_id,
                'material_type': material_type,
                'quantity': quantity,
                'scrap_rate': scrap_rate
            }
            
            manager.add_bom_material(material_data)
            st.success("✅ Material added!")
            st.rerun()
        except Exception as e:
            st.error(f"❌ Error: {str(e)}")


# ==================== ALTERNATIVES ONLY MODE ====================

def _render_alternatives_mode(bom_id: int, bom_info: dict, bom_details: pd.DataFrame,
                              state: StateManager, manager: BOMManager):
    """Render alternatives-only edit mode (has active orders)"""
    
    # Show usage context
    st.markdown("### 📊 Usage Context")
    render_usage_context(bom_info)
    
    st.markdown("---")
    
    # Read-only BOM info
    st.markdown("### 📋 BOM Information (Read-Only)")
    _render_info_readonly(bom_info)
    
    st.markdown("---")
    
    # Materials with alternatives editing only
    st.markdown("### 🔀 Alternatives Management")
    st.info("ℹ️ You can add, modify, or remove alternative materials. Primary materials cannot be changed while orders are in progress.")
    
    if bom_details.empty:
        st.warning("⚠️ No materials in this BOM")
    else:
        for idx, material in bom_details.iterrows():
            _render_material_card_alternatives_only(bom_id, material, manager)
    
    st.markdown("---")
    
    # Close button
    if st.button("✔ Close", use_container_width=True, key="alt_mode_close"):
        state.close_dialog()
        st.rerun()


def _render_material_card_alternatives_only(bom_id: int, material: pd.Series, manager: BOMManager):
    """Render material card with alternatives editing only"""
    detail_id = int(material['id'])
    alt_count = int(material.get('alternatives_count', 0))
    
    with st.container():
        col1, col2, col3, col4, col5 = st.columns([3, 1.5, 1, 0.8, 0.8])
        
        with col1:
            alt_badge = f" 🔀 **{alt_count}**" if alt_count > 0 else ""
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
            stock = float(material['current_stock'])
            if stock > 0:
                st.success(f"📦 {format_number(stock, 0)}")
            else:
                st.error("📦 0")
    
    # Expandable alternatives section - editable
    with st.expander(f"🔀 Manage Alternatives ({alt_count})", expanded=False):
        _render_alternatives_manager(bom_id, detail_id, material, manager)
    
    st.markdown("")


def _render_info_readonly(bom_info: dict):
    """Render BOM information in read-only mode"""
    col1, col2 = st.columns(2)
    
    with col1:
        st.text_input("BOM Code", value=bom_info['bom_code'], disabled=True)
        st.text_input("BOM Name", value=bom_info['bom_name'], disabled=True)
        st.text_input("BOM Type", value=bom_info['bom_type'], disabled=True)
    
    with col2:
        product_display = format_product_display(
            code=bom_info.get('product_code', ''),
            name=bom_info.get('product_name', ''),
            package_size=bom_info.get('package_size'),
            brand=bom_info.get('brand'),
            legacy_code=bom_info.get('legacy_code')
        )
        st.text_input("Output Product", value=product_display, disabled=True)
        st.text_input("Output Quantity", value=f"{format_number(bom_info['output_qty'], 2)} {bom_info['uom']}", disabled=True)
        st.text_input("Effective Date", value=str(bom_info.get('effective_date', 'N/A')), disabled=True)
    
    if bom_info.get('notes'):
        st.text_area("Notes", value=bom_info['notes'], disabled=True)


# ==================== READ ONLY MODE ====================

def _render_read_only_mode(bom_id: int, bom_info: dict, bom_details: pd.DataFrame,
                           state: StateManager, manager: BOMManager):
    """Render read-only mode (has completed orders)"""
    
    # Show usage context
    st.markdown("### 📊 Usage Context")
    render_usage_context(bom_info)
    
    st.markdown("---")
    
    # BOM info - read only
    st.markdown("### 📋 BOM Information")
    _render_info_readonly(bom_info)
    
    st.markdown("---")
    
    # Materials - read only
    st.markdown("### 🧱 Materials")
    
    if bom_details.empty:
        st.info("ℹ️ No materials in this BOM")
    else:
        for idx, material in bom_details.iterrows():
            _render_material_card_readonly(material, manager)
    
    st.markdown("---")
    
    # Suggested actions
    st.markdown("### 💡 Available Actions")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("🔄 Clone BOM", use_container_width=True, help="Create a new BOM based on this one"):
            state.close_dialog()
            state.open_dialog(state.DIALOG_CLONE, bom_id)
            st.rerun()
    
    with col2:
        if st.button("👁️ View Details", use_container_width=True, help="View full BOM details"):
            state.close_dialog()
            state.open_dialog(state.DIALOG_VIEW, bom_id)
            st.rerun()
    
    with col3:
        if st.button("✔ Close", use_container_width=True):
            state.close_dialog()
            st.rerun()


def _render_material_card_readonly(material: pd.Series, manager: BOMManager):
    """Render material card in read-only mode"""
    detail_id = int(material['id'])
    alt_count = int(material.get('alternatives_count', 0))
    
    with st.container():
        col1, col2, col3, col4, col5 = st.columns([3, 1.5, 1, 0.8, 0.8])
        
        with col1:
            alt_badge = f" 🔀 {alt_count}" if alt_count > 0 else ""
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
    
    # Show alternatives - read only
    if alt_count > 0:
        with st.expander(f"🔀 View Alternatives ({alt_count})", expanded=False):
            _render_alternatives_readonly(detail_id, manager)
    
    st.markdown("")


def _render_alternatives_readonly(detail_id: int, manager: BOMManager):
    """Render alternatives in read-only mode"""
    try:
        alternatives = manager.get_material_alternatives(detail_id)
        
        if alternatives.empty:
            st.info("ℹ️ No alternatives")
            return
        
        for _, alt in alternatives.iterrows():
            col1, col2, col3, col4, col5 = st.columns([3, 1, 1, 0.8, 0.8])
            
            with col1:
                status_icon = "✅" if alt['is_active'] else "⭕"
                alt_display = format_product_display(
                    code=alt.get('material_code', ''),
                    name=alt.get('material_name', ''),
                    package_size=alt.get('package_size'),
                    brand=alt.get('brand'),
                    legacy_code=alt.get('legacy_code')
                )
                st.text(f"{status_icon} P{alt['priority']}: {alt_display}")
            
            with col2:
                st.text(f"{format_number(alt['quantity'], 4)}")
            
            with col3:
                st.text(alt['uom'])
            
            with col4:
                st.text(f"{format_number(alt['scrap_rate'], 2)}%")
            
            with col5:
                stock = float(alt['current_stock'])
                st.text(f"📦 {format_number(stock, 0)}")
            
            if alt.get('notes'):
                st.caption(f"   Note: {alt['notes']}")
    
    except Exception as e:
        logger.error(f"Error rendering alternatives: {e}")
        st.error(f"❌ Error: {str(e)}")