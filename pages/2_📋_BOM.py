# pages/2_📋_BOM.py - Complete BOM Management
"""
Bill of Materials (BOM) Management UI
Complete CRUD: Create, Read, Update, Delete BOMs
"""

import streamlit as st
import pandas as pd
from datetime import datetime, date
from typing import Dict, Optional, List
import time
import logging

from utils.auth import AuthManager
from utils.bom.manager import BOMManager
from utils.bom.common import (
    format_number,
    create_status_indicator,
    get_products,
    UIHelpers
)

logger = logging.getLogger(__name__)

# ==================== Page Configuration ====================

st.set_page_config(
    page_title="BOM Management",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ==================== Authentication ====================

auth = AuthManager()
auth.require_auth()

# ==================== Initialize Managers ====================

@st.cache_resource
def get_managers():
    """Initialize and cache managers"""
    return BOMManager()

bom_manager = get_managers()

# ==================== Session State ====================

def initialize_session_state():
    """Initialize session state variables"""
    defaults = {
        'current_tab': 0,
        'selected_bom_id': None,
        'editing_bom_id': None,
        'create_materials': [],  # Materials buffer for create form
        'edit_mode': None,  # 'header' or 'materials'
    }
    
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)

initialize_session_state()

# ==================== CREATE TAB ====================

def render_create_bom():
    """Render complete BOM creation with materials"""
    st.markdown("### ➕ Create New BOM")
    
    # Step 1: BOM Header
    st.markdown("#### Step 1: BOM Information")
    
    col1, col2 = st.columns(2)
    
    with col1:
        bom_name = st.text_input(
            "BOM Name *",
            placeholder="Enter BOM name",
            key="create_bom_name"
        )
        
        bom_type = st.selectbox(
            "BOM Type *",
            ["KITTING", "CUTTING", "REPACKING"],
            key="create_bom_type"
        )
        
        effective_date = st.date_input(
            "Effective Date",
            value=date.today(),
            key="create_effective_date"
        )
    
    with col2:
        # Product selection
        products = get_products()
        if not products.empty:
            product_options = {
                f"{row['name']} ({row['code']})": row['id']
                for _, row in products.iterrows()
            }
            
            selected_product = st.selectbox(
                "Output Product *",
                options=list(product_options.keys()),
                key="create_product"
            )
            
            product_id = product_options.get(selected_product)
            
            # Get product UOM
            if product_id:
                product_info = products[products['id'] == product_id].iloc[0]
                uom = product_info.get('uom', 'PCS')
            else:
                uom = 'PCS'
        else:
            st.error("❌ No products found")
            product_id = None
            uom = 'PCS'
        
        output_qty = st.number_input(
            "Output Quantity *",
            min_value=0.01,
            value=1.0,
            step=1.0,
            format="%.2f",
            key="create_output_qty"
        )
        
        st.text_input("UOM", value=uom, disabled=True, key="create_uom")
    
    # Notes
    notes = st.text_area(
        "Notes",
        placeholder="Optional notes...",
        height=80,
        key="create_notes"
    )
    
    st.markdown("---")
    
    # Step 2: Materials
    st.markdown("#### Step 2: Add Materials")
    
    # Display current materials buffer
    if st.session_state.create_materials:
        st.markdown("**Materials to be added:**")
        
        materials_df = pd.DataFrame(st.session_state.create_materials)
        
        # Add product names
        mat_ids = materials_df['material_id'].tolist()
        mat_info = products[products['id'].isin(mat_ids)][['id', 'name', 'code']]
        materials_df = materials_df.merge(mat_info, left_on='material_id', right_on='id', how='left')
        
        # Display table
        display_cols = ['name', 'code', 'material_type', 'quantity', 'uom', 'scrap_rate']
        st.dataframe(
            materials_df[display_cols],
            use_container_width=True,
            hide_index=True
        )
        
        # Remove material button
        col1, col2, col3 = st.columns([2, 1, 3])
        with col1:
            mat_to_remove = st.selectbox(
                "Remove material",
                options=range(len(st.session_state.create_materials)),
                format_func=lambda i: materials_df.iloc[i]['name'],
                key="remove_mat_select"
            )
        with col2:
            if st.button("🗑️ Remove", key="remove_mat_btn"):
                st.session_state.create_materials.pop(mat_to_remove)
                st.rerun()
        
        st.markdown("---")
    else:
        st.info("ℹ️ No materials added yet. Add at least one material below.")
    
    # Add material form
    st.markdown("**Add Material:**")
    
    col1, col2, col3, col4, col5 = st.columns([3, 2, 1, 1, 1])
    
    with col1:
        if not products.empty:
            material_options = {
                f"{row['name']} ({row['code']})": row['id']
                for _, row in products.iterrows()
            }
            
            selected_material = st.selectbox(
                "Material",
                options=list(material_options.keys()),
                key="add_material_select"
            )
            
            material_id = material_options.get(selected_material)
        else:
            material_id = None
    
    with col2:
        material_type = st.selectbox(
            "Type",
            ["RAW_MATERIAL", "PACKAGING", "CONSUMABLE"],
            key="add_material_type"
        )
    
    with col3:
        mat_quantity = st.number_input(
            "Quantity",
            min_value=0.0001,
            value=1.0,
            step=0.1,
            format="%.4f",
            key="add_material_qty"
        )
    
    with col4:
        if material_id:
            mat_info = products[products['id'] == material_id].iloc[0]
            mat_uom = mat_info.get('uom', 'PCS')
        else:
            mat_uom = 'PCS'
        st.text_input("UOM", value=mat_uom, disabled=True, key="add_material_uom")
    
    with col5:
        mat_scrap = st.number_input(
            "Scrap %",
            min_value=0.0,
            max_value=100.0,
            value=0.0,
            step=0.5,
            key="add_material_scrap"
        )
    
    if st.button("➕ Add Material", key="add_material_btn", use_container_width=True):
        if material_id:
            # Check duplicate
            if any(m['material_id'] == material_id for m in st.session_state.create_materials):
                st.error("❌ Material already added")
            else:
                st.session_state.create_materials.append({
                    'material_id': material_id,
                    'material_type': material_type,
                    'quantity': mat_quantity,
                    'uom': mat_uom,
                    'scrap_rate': mat_scrap
                })
                st.success("✅ Material added to list")
                time.sleep(0.5)
                st.rerun()
    
    st.markdown("---")
    
    # Submit buttons
    col1, col2, col3 = st.columns([4, 1, 1])
    
    with col2:
        if st.button("✅ Create BOM", type="primary", use_container_width=True):
            # Validation
            errors = []
            
            if not bom_name:
                errors.append("BOM name is required")
            if not product_id:
                errors.append("Output product is required")
            if not st.session_state.create_materials:
                errors.append("At least one material is required")
            
            if errors:
                for error in errors:
                    st.error(f"❌ {error}")
            else:
                try:
                    # Create BOM
                    bom_data = {
                        'bom_name': bom_name,
                        'bom_type': bom_type,
                        'product_id': product_id,
                        'output_qty': output_qty,
                        'uom': uom,
                        'effective_date': effective_date,
                        'notes': notes,
                        'materials': st.session_state.create_materials,
                        'created_by': st.session_state.get('user_id', 1)
                    }
                    
                    bom_code = bom_manager.create_bom(bom_data)
                    
                    # Clear buffer
                    st.session_state.create_materials = []
                    
                    st.success(f"✅ BOM {bom_code} created successfully!")
                    time.sleep(2)
                    st.rerun()
                    
                except Exception as e:
                    st.error(f"❌ Error creating BOM: {str(e)}")
    
    with col3:
        if st.button("🔄 Reset", use_container_width=True):
            st.session_state.create_materials = []
            st.rerun()

# ==================== LIST TAB ====================

def render_bom_list():
    """Render BOM list with search and actions"""
    st.markdown("### 📋 Bill of Materials List")
    
    # Filters
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        filter_type = st.selectbox(
            "BOM Type",
            ["All", "KITTING", "CUTTING", "REPACKING"],
            key="filter_type"
        )
    
    with col2:
        filter_status = st.selectbox(
            "Status",
            ["All", "DRAFT", "ACTIVE", "INACTIVE"],
            key="filter_status"
        )
    
    with col3:
        filter_search = st.text_input(
            "Search",
            placeholder="Code or name...",
            key="filter_search"
        )
    
    with col4:
        st.markdown("<br>", unsafe_allow_html=True)
        search_clicked = st.button("🔍 Search", use_container_width=True)
    
    # Get BOMs
    try:
        boms = bom_manager.get_boms(
            bom_type=filter_type if filter_type != "All" else None,
            status=filter_status if filter_status != "All" else None,
            search=filter_search if filter_search else None
        )
        
        if boms.empty:
            st.info("ℹ️ No BOMs found")
            return
        
        # Metrics
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total", len(boms))
        with col2:
            st.metric("Active", len(boms[boms['status'] == 'ACTIVE']))
        with col3:
            st.metric("Draft", len(boms[boms['status'] == 'DRAFT']))
        with col4:
            st.metric("Inactive", len(boms[boms['status'] == 'INACTIVE']))
        
        st.markdown("---")
        
        # Display table
        display_df = boms.copy()
        display_df['status'] = display_df['status'].apply(create_status_indicator)
        
        # Configure columns
        column_config = {
            "bom_code": st.column_config.TextColumn("BOM Code", width="medium"),
            "bom_name": st.column_config.TextColumn("BOM Name", width="large"),
            "bom_type": st.column_config.TextColumn("Type", width="small"),
            "product_name": st.column_config.TextColumn("Product", width="large"),
            "output_qty": st.column_config.NumberColumn("Output Qty", format="%.2f"),
            "status": st.column_config.TextColumn("Status", width="small"),
            "material_count": st.column_config.NumberColumn("Materials", width="small"),
        }
        
        # Selectable dataframe
        event = st.dataframe(
            display_df[['bom_code', 'bom_name', 'bom_type', 'product_name', 
                       'output_qty', 'uom', 'status', 'material_count']],
            use_container_width=True,
            hide_index=True,
            column_config=column_config,
            on_select="rerun",
            selection_mode="single-row"
        )
        
        # Get selected BOM
        if event.selection.rows:
            selected_idx = event.selection.rows[0]
            st.session_state.selected_bom_id = boms.iloc[selected_idx]['id']
        
        # Actions for selected BOM
        if st.session_state.selected_bom_id:
            st.markdown("---")
            st.markdown("### 🎯 Actions")
            
            col1, col2, col3, col4, col5 = st.columns(5)
            
            with col1:
                if st.button("👁️ View Details", use_container_width=True):
                    show_bom_details(st.session_state.selected_bom_id)
            
            with col2:
                if st.button("✏️ Edit", use_container_width=True):
                    st.session_state.editing_bom_id = st.session_state.selected_bom_id
                    st.session_state.current_tab = 2
                    st.rerun()
            
            with col3:
                if st.button("🔄 Change Status", use_container_width=True):
                    show_change_status_dialog(st.session_state.selected_bom_id)
            
            with col4:
                if st.button("📍 Where Used", use_container_width=True):
                    st.session_state.current_tab = 3
                    st.rerun()
            
            with col5:
                if st.button("🗑️ Delete", use_container_width=True, type="secondary"):
                    show_delete_confirmation(st.session_state.selected_bom_id)
        
    except Exception as e:
        st.error(f"❌ Error loading BOMs: {str(e)}")

def show_bom_details(bom_id: int):
    """Show BOM details in expander"""
    with st.expander("📋 BOM Details", expanded=True):
        bom_info = bom_manager.get_bom_info(bom_id)
        bom_details = bom_manager.get_bom_details(bom_id)
        
        if bom_info:
            col1, col2, col3 = st.columns(3)
            with col1:
                st.write(f"**Code:** {bom_info['bom_code']}")
                st.write(f"**Name:** {bom_info['bom_name']}")
                st.write(f"**Type:** {bom_info['bom_type']}")
            with col2:
                st.write(f"**Product:** {bom_info['product_name']}")
                st.write(f"**Output:** {bom_info['output_qty']} {bom_info['uom']}")
                st.write(f"**Status:** {bom_info['status']}")
            with col3:
                st.write(f"**Effective Date:** {bom_info.get('effective_date', 'N/A')}")
                st.write(f"**Total Usage:** {bom_info.get('total_usage', 0)} orders")
                st.write(f"**Active Orders:** {bom_info.get('active_orders', 0)}")
            
            if bom_info.get('notes'):
                st.markdown(f"**Notes:** {bom_info['notes']}")
        
        if not bom_details.empty:
            st.markdown("**Materials:**")
            st.dataframe(
                bom_details[['material_name', 'material_code', 'material_type', 
                           'quantity', 'uom', 'scrap_rate', 'current_stock']],
                use_container_width=True,
                hide_index=True
            )

def show_change_status_dialog(bom_id: int):
    """Show status change dialog"""
    with st.expander("🔄 Change BOM Status", expanded=True):
        bom_info = bom_manager.get_bom_info(bom_id)
        current_status = bom_info['status']
        
        st.write(f"**Current Status:** {create_status_indicator(current_status)}")
        
        col1, col2 = st.columns([2, 1])
        
        with col1:
            new_status = st.selectbox(
                "New Status",
                ["DRAFT", "ACTIVE", "INACTIVE"],
                key=f"new_status_{bom_id}"
            )
        
        with col2:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("✅ Update", type="primary", use_container_width=True):
                try:
                    bom_manager.update_bom_status(
                        bom_id,
                        new_status,
                        st.session_state.get('user_id', 1)
                    )
                    st.success(f"✅ Status updated to {new_status}")
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ {str(e)}")

def show_delete_confirmation(bom_id: int):
    """Show delete confirmation dialog"""
    with st.expander("⚠️ Delete BOM", expanded=True):
        bom_info = bom_manager.get_bom_info(bom_id)
        
        st.warning(f"🚨 Are you sure you want to delete **{bom_info['bom_code']} - {bom_info['bom_name']}**?")
        st.write("This action cannot be undone.")
        
        col1, col2, col3 = st.columns([3, 1, 1])
        
        with col2:
            if st.button("✅ Confirm Delete", type="primary", key=f"confirm_del_{bom_id}"):
                try:
                    bom_manager.delete_bom(bom_id, st.session_state.get('user_id', 1))
                    st.success("✅ BOM deleted successfully")
                    st.session_state.selected_bom_id = None
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ {str(e)}")
        
        with col3:
            if st.button("❌ Cancel", key=f"cancel_del_{bom_id}"):
                st.rerun()

# ==================== EDIT TAB ====================

def render_edit_bom():
    """Render BOM editing interface"""
    st.markdown("### ✏️ Edit BOM")
    
    # BOM selection
    boms = bom_manager.get_boms(status='DRAFT')
    
    if boms.empty:
        st.warning("⚠️ Only DRAFT BOMs can be edited. No DRAFT BOMs found.")
        return
    
    bom_options = {
        f"{row['bom_name']} ({row['bom_code']})": row['id']
        for _, row in boms.iterrows()
    }
    
    # Pre-select if coming from list
    default_index = 0
    if st.session_state.editing_bom_id:
        for idx, bom_id in enumerate(bom_options.values()):
            if bom_id == st.session_state.editing_bom_id:
                default_index = idx
                break
    
    selected_bom = st.selectbox(
        "Select BOM to Edit",
        options=list(bom_options.keys()),
        index=default_index,
        key="edit_bom_select"
    )
    
    if not selected_bom:
        return
    
    bom_id = bom_options[selected_bom]
    st.session_state.editing_bom_id = bom_id
    
    # Get BOM data
    bom_info = bom_manager.get_bom_info(bom_id)
    bom_details = bom_manager.get_bom_details(bom_id)
    
    if not bom_info:
        st.error("❌ BOM not found")
        return
    
    # Edit mode selection
    st.markdown("---")
    edit_mode = st.radio(
        "What do you want to edit?",
        ["BOM Information", "Materials"],
        horizontal=True,
        key="edit_mode_radio"
    )
    
    st.markdown("---")
    
    if edit_mode == "BOM Information":
        render_edit_header(bom_id, bom_info)
    else:
        render_edit_materials(bom_id, bom_details)

def render_edit_header(bom_id: int, bom_info: Dict):
    """Render header editing form"""
    st.markdown("#### Edit BOM Information")
    
    col1, col2 = st.columns(2)
    
    with col1:
        new_name = st.text_input(
            "BOM Name",
            value=bom_info['bom_name'],
            key="edit_bom_name"
        )
        
        new_output_qty = st.number_input(
            "Output Quantity",
            min_value=0.01,
            value=float(bom_info['output_qty']),
            step=1.0,
            format="%.2f",
            key="edit_output_qty"
        )
    
    with col2:
        new_effective_date = st.date_input(
            "Effective Date",
            value=bom_info.get('effective_date', date.today()),
            key="edit_effective_date"
        )
        
        st.text_input("UOM", value=bom_info['uom'], disabled=True)
    
    new_notes = st.text_area(
        "Notes",
        value=bom_info.get('notes', ''),
        height=100,
        key="edit_notes"
    )
    
    # Save button
    col1, col2, col3 = st.columns([4, 1, 1])
    
    with col2:
        if st.button("💾 Save Changes", type="primary", use_container_width=True):
            try:
                updates = {
                    'bom_name': new_name,
                    'output_qty': new_output_qty,
                    'effective_date': new_effective_date,
                    'notes': new_notes,
                    'updated_by': st.session_state.get('user_id', 1)
                }
                
                bom_manager.update_bom_header(bom_id, updates)
                st.success("✅ BOM updated successfully!")
                time.sleep(1)
                st.rerun()
                
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")
    
    with col3:
        if st.button("🔙 Cancel", use_container_width=True):
            st.rerun()

def render_edit_materials(bom_id: int, bom_details: pd.DataFrame):
    """Render materials editing"""
    st.markdown("#### Edit Materials")
    
    # Current materials
    if not bom_details.empty:
        st.markdown("**Current Materials:**")
        
        for idx, material in bom_details.iterrows():
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
                        key=f"mat_qty_{material['id']}",
                        label_visibility="collapsed"
                    )
                
                with col4:
                    st.text(material['uom'])
                
                with col5:
                    new_scrap = st.number_input(
                        "Scrap",
                        min_value=0.0,
                        max_value=100.0,
                        value=float(material['scrap_rate']),
                        step=0.5,
                        key=f"mat_scrap_{material['id']}",
                        label_visibility="collapsed"
                    )
                
                with col6:
                    col_update, col_delete = st.columns(2)
                    
                    with col_update:
                        if new_qty != material['quantity'] or new_scrap != material['scrap_rate']:
                            if st.button("💾", key=f"update_{material['id']}", help="Save changes"):
                                try:
                                    bom_manager.update_material(
                                        bom_id,
                                        material['material_id'],
                                        {'quantity': new_qty, 'scrap_rate': new_scrap}
                                    )
                                    st.success("✅ Updated")
                                    time.sleep(0.5)
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"❌ {str(e)}")
                    
                    with col_delete:
                        if st.button("🗑️", key=f"remove_{material['id']}", help="Remove material"):
                            try:
                                bom_manager.remove_material(bom_id, material['material_id'])
                                st.success("✅ Removed")
                                time.sleep(0.5)
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ {str(e)}")
                
                st.markdown("---")
    else:
        st.info("ℹ️ No materials in this BOM")
    
    # Add new material
    st.markdown("**Add New Material:**")
    
    products = get_products()
    
    col1, col2, col3, col4, col5 = st.columns([3, 2, 1, 1, 1])
    
    with col1:
        if not products.empty:
            material_options = {
                f"{row['name']} ({row['code']})": row['id']
                for _, row in products.iterrows()
            }
            
            selected_material = st.selectbox(
                "Material",
                options=list(material_options.keys()),
                key="edit_add_material"
            )
            
            material_id = material_options.get(selected_material)
        else:
            material_id = None
    
    with col2:
        material_type = st.selectbox(
            "Type",
            ["RAW_MATERIAL", "PACKAGING", "CONSUMABLE"],
            key="edit_material_type"
        )
    
    with col3:
        quantity = st.number_input(
            "Quantity",
            min_value=0.0001,
            value=1.0,
            step=0.1,
            format="%.4f",
            key="edit_material_qty"
        )
    
    with col4:
        if material_id:
            mat_info = products[products['id'] == material_id].iloc[0]
            mat_uom = mat_info.get('uom', 'PCS')
        else:
            mat_uom = 'PCS'
        st.text_input("UOM", value=mat_uom, disabled=True, key="edit_material_uom")
    
    with col5:
        scrap_rate = st.number_input(
            "Scrap %",
            min_value=0.0,
            max_value=100.0,
            value=0.0,
            step=0.5,
            key="edit_material_scrap"
        )
    
    if st.button("➕ Add Material", use_container_width=True, key="edit_add_btn"):
        if material_id:
            # Check duplicate
            if not bom_details.empty and material_id in bom_details['material_id'].values:
                st.error("❌ Material already exists in BOM")
            else:
                try:
                    materials = [{
                        'material_id': material_id,
                        'material_type': material_type,
                        'quantity': quantity,
                        'uom': mat_uom,
                        'scrap_rate': scrap_rate
                    }]
                    
                    bom_manager.add_materials(bom_id, materials)
                    st.success("✅ Material added!")
                    time.sleep(0.5)
                    st.rerun()
                    
                except Exception as e:
                    st.error(f"❌ Error: {str(e)}")

# ==================== WHERE USED TAB ====================

def render_where_used():
    """Render where used analysis"""
    st.markdown("### 🔍 Where Used Analysis")
    
    st.info("ℹ️ Find which BOMs use a specific product/material")
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        products = get_products()
        if not products.empty:
            product_options = {
                f"{row['name']} ({row['code']})": row['id']
                for _, row in products.iterrows()
            }
            
            selected_product = st.selectbox(
                "Select Product/Material",
                options=list(product_options.keys()),
                key="where_used_product"
            )
            
            product_id = product_options.get(selected_product)
        else:
            st.error("❌ No products found")
            product_id = None
    
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        search = st.button("🔍 Search", type="primary", use_container_width=True)
    
    if search and product_id:
        try:
            where_used = bom_manager.get_where_used(product_id)
            
            if where_used.empty:
                st.info("ℹ️ This product is not used in any BOM")
            else:
                st.success(f"✅ Found in **{len(where_used)}** BOM(s)")
                
                # Format display
                display_df = where_used.copy()
                display_df['bom_status'] = display_df['bom_status'].apply(create_status_indicator)
                
                st.dataframe(
                    display_df[['bom_code', 'bom_name', 'bom_type', 'bom_status',
                              'output_product_name', 'quantity', 'uom', 'scrap_rate']],
                    use_container_width=True,
                    hide_index=True
                )
                
        except Exception as e:
            st.error(f"❌ Error: {str(e)}")

# ==================== MAIN APPLICATION ====================

def main():
    """Main application entry point"""
    st.title("📋 BOM Management")
    
    # Create tabs
    tab_names = ["📋 List", "➕ Create", "✏️ Edit", "🔍 Where Used"]
    tabs = st.tabs(tab_names)
    
    with tabs[0]:
        render_bom_list()
    
    with tabs[1]:
        render_create_bom()
    
    with tabs[2]:
        render_edit_bom()
    
    with tabs[3]:
        render_where_used()
    
    # Footer
    st.markdown("---")
    st.caption("Manufacturing Module v2.0 - BOM Management | Clean CRUD Implementation")

if __name__ == "__main__":
    main()