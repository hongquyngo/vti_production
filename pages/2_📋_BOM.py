# pages/2_📋_BOM.py - Complete BOM Management UI
"""
Bill of Materials (BOM) Management UI
Complete BOM creation, editing, and analysis.
"""

import streamlit as st
import pandas as pd
from datetime import datetime, date
from typing import Dict, List, Optional
import time
import logging

from utils.auth import AuthManager
from modules.bom import BOMManager
from modules.inventory import InventoryManager
from modules.common import (
    format_number,
    create_status_indicator,
    export_to_excel,
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
    return BOMManager(), InventoryManager()

bom_manager, inv_manager = get_managers()

# ==================== Session State ====================

def initialize_session_state():
    """Initialize session state variables"""
    defaults = {
        'current_tab': 0,
        'selected_bom': None,
        'editing_bom': None,
        'form_data': {},
        'filters': {}
    }
    
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)

initialize_session_state()

# ==================== BOM List Tab ====================

def render_bom_list():
    """Render BOM list with filters"""
    st.markdown("### 📋 Bill of Materials List")
    
    # Filters
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        bom_type = st.selectbox(
            "BOM Type",
            ["All", "KITTING", "CUTTING", "REPACKING"],
            key="filter_bom_type"
        )
    
    with col2:
        status = st.selectbox(
            "Status",
            ["All", "DRAFT", "ACTIVE", "INACTIVE"],
            key="filter_status"
        )
    
    with col3:
        search = st.text_input(
            "Search",
            placeholder="Code or name...",
            key="filter_search"
        )
    
    with col4:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🔍 Search", use_container_width=True):
            st.rerun()
    
    # Get filtered BOMs
    try:
        boms = bom_manager.get_boms(
            bom_type=bom_type if bom_type != "All" else None,
            status=status if status != "All" else None,
            search=search if search else None
        )
        
        if boms.empty:
            st.info("No BOMs found matching the criteria")
            return
        
        # Display metrics
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total BOMs", len(boms))
        with col2:
            active_count = len(boms[boms['status'] == 'ACTIVE'])
            st.metric("Active", active_count)
        with col3:
            draft_count = len(boms[boms['status'] == 'DRAFT'])
            st.metric("Draft", draft_count)
        with col4:
            inactive_count = len(boms[boms['status'] == 'INACTIVE'])
            st.metric("Inactive", inactive_count)
        
        st.markdown("---")
        
        # Format display
        display_df = boms.copy()
        display_df['status'] = display_df['status'].apply(create_status_indicator)
        
        # Display table
        columns_to_show = ['bom_code', 'bom_name', 'bom_type', 'product_name', 
                          'output_qty', 'uom', 'status', 'material_count', 'usage_count']
        
        st.dataframe(
            display_df[columns_to_show],
            use_container_width=True,
            hide_index=True
        )
        
        # Quick Actions
        st.markdown("### Quick Actions")
        col1, col2, col3 = st.columns([2, 2, 1])
        
        with col1:
            selected_bom = st.selectbox(
                "Select BOM",
                boms['bom_code'].tolist(),
                key="selected_bom_code"
            )
            
            if selected_bom:
                selected_row = boms[boms['bom_code'] == selected_bom].iloc[0]
                st.session_state.selected_bom = selected_row['id']
        
        with col2:
            action = st.selectbox(
                "Action",
                ["View Details", "Edit", "Copy", "Change Status", "Delete"]
            )
        
        with col3:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Execute", type="primary", use_container_width=True):
                execute_bom_action(action, st.session_state.selected_bom)
        
    except Exception as e:
        st.error(f"Error loading BOMs: {str(e)}")

# ==================== Create BOM Tab ====================

def render_create_bom():
    """Render create BOM form"""
    st.markdown("### ➕ Create New BOM")
    
    with st.form("create_bom_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        
        with col1:
            bom_name = st.text_input(
                "BOM Name *",
                placeholder="Enter BOM name"
            )
            
            bom_type = st.selectbox(
                "BOM Type *",
                ["KITTING", "CUTTING", "REPACKING"]
            )
            
            effective_date = st.date_input(
                "Effective Date",
                value=date.today()
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
                    options=list(product_options.keys())
                )
                
                product_id = product_options.get(selected_product)
                
                # Get product UOM
                if product_id:
                    product_info = products[products['id'] == product_id].iloc[0]
                    uom = product_info.get('uom', 'PCS')
                else:
                    uom = 'PCS'
            else:
                st.error("No products found")
                product_id = None
                uom = 'PCS'
            
            output_qty = st.number_input(
                "Output Quantity *",
                min_value=0.01,
                value=1.0,
                step=1.0,
                format="%.2f"
            )
            
            st.text_input("UOM", value=uom, disabled=True)
        
        # Notes
        notes = st.text_area(
            "Notes",
            placeholder="Optional notes...",
            height=100
        )
        
        # Submit buttons
        st.markdown("---")
        col1, col2, col3 = st.columns([3, 1, 1])
        
        with col2:
            submitted = st.form_submit_button(
                "Create BOM",
                type="primary",
                use_container_width=True
            )
        
        with col3:
            cancel = st.form_submit_button(
                "Cancel",
                use_container_width=True
            )
        
        if submitted:
            # Validation
            if not bom_name:
                UIHelpers.show_message("BOM name is required", "error")
            elif not product_id:
                UIHelpers.show_message("Product is required", "error")
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
                        'materials': [],  # Materials will be added via Edit
                        'created_by': st.session_state.get('user_id', 1)
                    }
                    
                    bom_code = bom_manager.create_bom(bom_data)
                    UIHelpers.show_message(
                        f"✅ BOM {bom_code} created successfully! Use Edit to add materials.", 
                        "success"
                    )
                    time.sleep(2)
                    st.rerun()
                    
                except Exception as e:
                    UIHelpers.show_message(f"Error creating BOM: {str(e)}", "error")

# ==================== Edit BOM Tab ====================

def render_edit_bom():
    """Render BOM editing interface"""
    st.markdown("### ✏️ Edit BOM")
    
    # BOM selection
    boms = bom_manager.get_boms()
    
    if boms.empty:
        st.info("No BOMs available for editing")
        return
    
    # Only allow editing DRAFT BOMs
    editable_boms = boms[boms['status'] == 'DRAFT']
    
    if editable_boms.empty:
        st.warning("Only DRAFT BOMs can be edited. No DRAFT BOMs found.")
        return
    
    bom_options = {
        f"{row['bom_name']} ({row['bom_code']})": row['id']
        for _, row in editable_boms.iterrows()
    }
    
    selected_bom = st.selectbox(
        "Select BOM to Edit",
        options=list(bom_options.keys())
    )
    
    if selected_bom:
        bom_id = bom_options[selected_bom]
        st.session_state.editing_bom = bom_id
        
        # Get BOM info and details
        bom_info = bom_manager.get_bom_info(bom_id)
        bom_details = bom_manager.get_bom_details(bom_id)
        
        if bom_info:
            # Show BOM info
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("BOM Code", bom_info['bom_code'])
            with col2:
                st.metric("Product", bom_info['product_name'])
            with col3:
                st.metric("Output", f"{bom_info['output_qty']} {bom_info['uom']}")
            
            # Materials section
            st.markdown("---")
            st.markdown("### Materials")
            
            # Current materials
            if not bom_details.empty:
                st.markdown("#### Current Materials")
                
                # Display current materials
                for idx, row in bom_details.iterrows():
                    col1, col2, col3, col4, col5 = st.columns([3, 1, 1, 1, 1])
                    
                    with col1:
                        st.text(f"{row['material_name']} ({row['material_code']})")
                    with col2:
                        st.text(f"{row['quantity']} {row['uom']}")
                    with col3:
                        st.text(f"Scrap: {row['scrap_rate']}%")
                    with col4:
                        st.text(f"Stock: {row['current_stock']}")
                    with col5:
                        if st.button("Remove", key=f"remove_{row['material_id']}"):
                            try:
                                bom_manager.remove_material(bom_id, row['material_id'])
                                UIHelpers.show_message("Material removed", "success")
                                time.sleep(1)
                                st.rerun()
                            except Exception as e:
                                UIHelpers.show_message(f"Error: {str(e)}", "error")
                
                st.markdown("---")
            else:
                st.info("No materials added yet")
            
            # Add new material
            st.markdown("#### Add New Material")
            
            with st.form("add_material_form"):
                col1, col2 = st.columns(2)
                
                with col1:
                    # Product selection
                    products = get_products()
                    material_options = {
                        f"{row['name']} ({row['code']})": row['id']
                        for _, row in products.iterrows()
                    }
                    
                    selected_material = st.selectbox(
                        "Select Material",
                        options=list(material_options.keys())
                    )
                    
                    material_id = material_options.get(selected_material)
                    
                    material_type = st.selectbox(
                        "Material Type",
                        ["RAW_MATERIAL", "PACKAGING", "CONSUMABLE"]
                    )
                
                with col2:
                    quantity = st.number_input(
                        "Quantity",
                        min_value=0.0001,
                        value=1.0,
                        step=0.1,
                        format="%.4f"
                    )
                    
                    # Get material UOM
                    if material_id:
                        mat_info = products[products['id'] == material_id].iloc[0]
                        mat_uom = mat_info.get('uom', 'PCS')
                    else:
                        mat_uom = 'PCS'
                    
                    st.text_input("UOM", value=mat_uom, disabled=True)
                    
                    scrap_rate = st.number_input(
                        "Scrap Rate (%)",
                        min_value=0.0,
                        max_value=100.0,
                        value=0.0,
                        step=0.5
                    )
                
                # Add button
                if st.form_submit_button("Add Material", type="primary", use_container_width=True):
                    try:
                        # Check if material already exists
                        if not bom_details.empty and material_id in bom_details['material_id'].values:
                            UIHelpers.show_message("Material already exists in BOM", "warning")
                        else:
                            materials = [{
                                'material_id': material_id,
                                'material_type': material_type,
                                'quantity': quantity,
                                'uom': mat_uom,
                                'scrap_rate': scrap_rate
                            }]
                            
                            bom_manager.add_materials(bom_id, materials)
                            UIHelpers.show_message("✅ Material added successfully!", "success")
                            time.sleep(1)
                            st.rerun()
                            
                    except Exception as e:
                        UIHelpers.show_message(f"Error adding material: {str(e)}", "error")

# ==================== Where Used Tab ====================

def render_where_used():
    """Render where used analysis"""
    st.markdown("### 🔍 Where Used Analysis")
    
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
            st.error("No products found")
            product_id = None
    
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        search = st.button("🔍 Search", type="primary", use_container_width=True)
    
    if search and product_id:
        try:
            where_used = bom_manager.get_where_used(product_id)
            
            if where_used.empty:
                st.info(f"This product is not used in any BOM")
            else:
                st.success(f"Found in {len(where_used)} BOM(s)")
                
                # Format display
                display_df = where_used.copy()
                display_df['bom_status'] = display_df['bom_status'].apply(create_status_indicator)
                display_df['total_requirement'] = display_df['quantity'].apply(
                    lambda x: format_number(x, 4)
                )
                
                columns_to_show = ['bom_code', 'bom_name', 'bom_type', 'bom_status',
                                  'output_product_name', 'quantity', 'uom', 'scrap_rate']
                
                st.dataframe(
                    display_df[columns_to_show],
                    use_container_width=True,
                    hide_index=True
                )
                
        except Exception as e:
            st.error(f"Error searching where used: {str(e)}")

# ==================== Analysis Tab ====================

def render_analysis():
    """Render BOM analysis"""
    st.markdown("### 📊 BOM Analysis")
    
    try:
        # Material usage summary
        st.markdown("#### Material Usage Summary")
        material_usage = bom_manager.get_material_usage_summary()
        
        if not material_usage.empty:
            # Display top 10 materials
            top_materials = material_usage.head(10)
            
            col1, col2 = st.columns([3, 1])
            
            with col1:
                st.dataframe(
                    top_materials[['material_name', 'material_code', 'usage_count', 
                                  'total_base_quantity', 'active_bom_count']],
                    use_container_width=True,
                    hide_index=True
                )
            
            with col2:
                st.metric("Total Materials", len(material_usage))
                st.metric("Avg Usage", f"{material_usage['usage_count'].mean():.1f}")
                st.metric("Max Usage", material_usage['usage_count'].max())
        else:
            st.info("No material usage data available")
        
        # BOM validation
        st.markdown("---")
        st.markdown("#### BOM Validation")
        
        all_boms = bom_manager.get_boms()
        if not all_boms.empty:
            col1, col2 = st.columns([2, 1])
            
            with col1:
                selected_bom_validate = st.selectbox(
                    "Select BOM to Validate",
                    all_boms['bom_code'].tolist(),
                    key="validate_bom"
                )
            
            with col2:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("Validate", use_container_width=True):
                    if selected_bom_validate:
                        bom_row = all_boms[all_boms['bom_code'] == selected_bom_validate].iloc[0]
                        validation_result = bom_manager.validate_bom_materials(bom_row['id'])
                        
                        if validation_result['valid']:
                            st.success("✅ BOM is valid")
                        else:
                            st.error("❌ BOM has errors")
                        
                        if validation_result['errors']:
                            st.error("**Errors:**")
                            for error in validation_result['errors']:
                                st.write(f"- {error}")
                        
                        if validation_result['warnings']:
                            st.warning("**Warnings:**")
                            for warning in validation_result['warnings']:
                                st.write(f"- {warning}")
        
    except Exception as e:
        st.error(f"Error loading analysis: {str(e)}")

# ==================== Action Handler ====================

def execute_bom_action(action: str, bom_id: Optional[int]):
    """Execute selected action on BOM"""
    if not bom_id:
        UIHelpers.show_message("Please select a BOM first", "warning")
        return
    
    try:
        if action == "View Details":
            # Get and display BOM details
            bom_info = bom_manager.get_bom_info(bom_id)
            bom_details = bom_manager.get_bom_details(bom_id)
            
            with st.expander("BOM Information", expanded=True):
                if bom_info:
                    col1, col2 = st.columns(2)
                    with col1:
                        st.write(f"**Code:** {bom_info.get('bom_code', 'N/A')}")
                        st.write(f"**Name:** {bom_info.get('bom_name', 'N/A')}")
                        st.write(f"**Type:** {bom_info.get('bom_type', 'N/A')}")
                    with col2:
                        st.write(f"**Product:** {bom_info.get('product_name', 'N/A')}")
                        st.write(f"**Output:** {bom_info.get('output_qty', 0)} {bom_info.get('uom', '')}")
                        st.write(f"**Status:** {bom_info.get('status', 'N/A')}")
                
                if not bom_details.empty:
                    st.markdown("**Materials:**")
                    st.dataframe(bom_details, use_container_width=True, hide_index=True)
                else:
                    st.info("No materials defined for this BOM")
        
        elif action == "Edit":
            st.session_state.current_tab = 2  # Switch to Edit tab
            st.session_state.editing_bom = bom_id
            st.rerun()
        
        elif action == "Change Status":
            col1, col2, col3 = st.columns([2, 1, 1])
            with col1:
                new_status = st.selectbox(
                    "New Status",
                    ["DRAFT", "ACTIVE", "INACTIVE"],
                    key="new_status"
                )
            with col2:
                if st.button("Update", type="primary"):
                    bom_manager.update_bom_status(
                        bom_id,
                        new_status,
                        st.session_state.get('user_id', 1)
                    )
                    UIHelpers.show_message(f"Status updated to {new_status}", "success")
                    time.sleep(1)
                    st.rerun()
        
        elif action == "Copy":
            new_name = st.text_input("New BOM Name", key="copy_name")
            if st.button("Copy BOM"):
                if new_name:
                    new_code = bom_manager.copy_bom(
                        bom_id,
                        new_name,
                        st.session_state.get('user_id', 1)
                    )
                    UIHelpers.show_message(f"BOM copied successfully: {new_code}", "success")
                    time.sleep(1)
                    st.rerun()
                else:
                    UIHelpers.show_message("Please enter a name for the new BOM", "warning")
        
        elif action == "Delete":
            if UIHelpers.confirm_action("Delete this BOM?", f"delete_bom_{bom_id}"):
                bom_manager.delete_bom(
                    bom_id,
                    st.session_state.get('user_id', 1)
                )
                UIHelpers.show_message("BOM deleted successfully", "success")
                time.sleep(1)
                st.rerun()
            
    except Exception as e:
        UIHelpers.show_message(f"Error: {str(e)}", "error")

# ==================== Main Application ====================

def main():
    """Main application entry point"""
    st.title("📋 BOM Management")
    
    # Create tabs
    tab_list = ["📋 BOM List", "➕ Create BOM", "✏️ Edit BOM", "🔍 Where Used", "📊 Analysis"]
    tabs = st.tabs(tab_list)
    
    # Update current tab from session state
    if st.session_state.current_tab == 2:  # If redirected to Edit tab
        st.session_state.current_tab = 2
    
    with tabs[0]:
        render_bom_list()
    
    with tabs[1]:
        render_create_bom()
    
    with tabs[2]:
        render_edit_bom()
    
    with tabs[3]:
        render_where_used()
    
    with tabs[4]:
        render_analysis()
    
    # Footer
    st.markdown("---")
    st.caption("Manufacturing Module v2.0 - BOM Management")


if __name__ == "__main__":
    main()