# pages/2_📋_BOM.py - Bill of Materials Management (Enhanced)
import streamlit as st
import pandas as pd
from datetime import date
import time
from typing import Dict, List, Optional, Tuple
from utils.auth import AuthManager
from modules.bom import BOMManager
from modules.common import (
    get_products, 
    format_number, 
    create_status_indicator,
    show_success_message, 
    show_error_message,
    confirm_action, 
    create_download_button,
    get_warehouses
)
import logging

logger = logging.getLogger(__name__)

# Page config
st.set_page_config(
    page_title="BOM Management",
    page_icon="📋",
    layout="wide"
)

# Authentication
auth = AuthManager()
auth.require_auth()

# Initialize BOM manager
bom_manager = BOMManager()

# Page header
st.title("📋 Bill of Materials (BOM) Management")

# Initialize session state
if 'bom_view' not in st.session_state:
    st.session_state.bom_view = 'list'
if 'selected_bom' not in st.session_state:
    st.session_state.selected_bom = None
if 'temp_materials' not in st.session_state:
    st.session_state.temp_materials = []
if 'product_info_cache' not in st.session_state:
    st.session_state.product_info_cache = {}

# Helper functions
def get_product_options_with_info() -> Tuple[Dict[str, int], Dict[int, Dict], pd.DataFrame]:
    """Get products with full information for dropdowns and auto-fill"""
    products = get_products()
    product_options = {}
    product_info = {}
    
    if not products.empty:
        for _, prod in products.iterrows():
            display_name = f"{prod['name']} ({prod['code']})"
            product_options[display_name] = prod['id']
            product_info[prod['id']] = {
                'name': prod['name'],
                'code': prod['code'],
                'uom': prod['uom'],
                'package_size': prod.get('package_size', ''),
                'total_stock': prod.get('total_stock', 0)
            }
    
    # Cache product info for later use
    st.session_state.product_info_cache = product_info
    
    return product_options, product_info, products

def format_bom_type(bom_type: str) -> str:
    """Format BOM type with icon"""
    type_icons = {
        'KITTING': '📦',
        'CUTTING': '✂️',
        'REPACKING': '📋'
    }
    return f"{type_icons.get(bom_type, '📄')} {bom_type}"

def validate_material_addition(material_id: int, quantity: float, scrap_rate: float) -> Tuple[bool, Optional[str]]:
    """Validate material before adding to BOM"""
    if not material_id:
        return False, "Please select a material"
    if quantity <= 0:
        return False, "Quantity must be greater than 0"
    if scrap_rate < 0 or scrap_rate > 100:
        return False, "Scrap rate must be between 0 and 100"
    return True, None

def cleanup_session_state():
    """Clean up temporary session state variables"""
    keys_to_clean = [k for k in st.session_state.keys() if k.startswith('confirm_delete_')]
    for key in keys_to_clean:
        del st.session_state[key]

# Top navigation
col1, col2, col3, col4 = st.columns(4)
with col1:
    if st.button("📋 BOM List", use_container_width=True, 
                type="primary" if st.session_state.bom_view == 'list' else "secondary"):
        st.session_state.bom_view = 'list'
        st.session_state.selected_bom = None
        cleanup_session_state()
        
with col2:
    if st.button("➕ Create BOM", use_container_width=True, 
                type="primary" if st.session_state.bom_view == 'create' else "secondary"):
        st.session_state.bom_view = 'create'
        st.session_state.temp_materials = []
        
with col3:
    if st.button("✏️ View/Edit BOM", use_container_width=True, 
                type="primary" if st.session_state.bom_view == 'edit' else "secondary"):
        st.session_state.bom_view = 'edit'
        
with col4:
    if st.button("📊 BOM Analysis", use_container_width=True, 
                type="primary" if st.session_state.bom_view == 'analysis' else "secondary"):
        st.session_state.bom_view = 'analysis'

st.markdown("---")

# Content based on view
if st.session_state.bom_view == 'list':
    # BOM List View
    st.subheader("📋 Bill of Materials List")
    
    # Filters
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        filter_type = st.selectbox("BOM Type", ["All", "KITTING", "CUTTING", "REPACKING"])
    with col2:
        filter_status = st.selectbox("Status", ["All", "DRAFT", "ACTIVE", "INACTIVE"])
    with col3:
        filter_product = st.text_input("Product Name/Code", placeholder="Search...")
    with col4:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🔄 Refresh", use_container_width=True):
            st.rerun()
    
    # Get BOMs
    boms = bom_manager.get_boms(
        bom_type=None if filter_type == "All" else filter_type,
        status=None if filter_status == "All" else filter_status,
        search=filter_product if filter_product else None
    )
    
    if not boms.empty:
        # Summary metrics
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total BOMs", len(boms))
        with col2:
            active_count = len(boms[boms['status'] == 'ACTIVE'])
            st.metric("Active BOMs", active_count)
        with col3:
            kitting_count = len(boms[boms['bom_type'] == 'KITTING'])
            st.metric("Kitting BOMs", kitting_count)
        with col4:
            draft_count = len(boms[boms['status'] == 'DRAFT'])
            st.metric("Draft BOMs", draft_count)
        
        st.markdown("---")
        
        # Display BOMs
        for idx, bom in boms.iterrows():
            with st.expander(
                f"{bom['bom_code']} - {bom['bom_name']} | {create_status_indicator(bom['status'])}", 
                expanded=False
            ):
                # BOM header info
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.write(f"**Type:** {format_bom_type(bom['bom_type'])}")
                    st.write(f"**Product:** {bom['product_name']}")
                    st.write(f"**Output:** {format_number(bom['output_qty'])} {bom['uom']}")
                
                with col2:
                    st.write(f"**Version:** {bom['version']}")
                    st.write(f"**Effective Date:** {bom['effective_date']}")
                    if bom['expiry_date']:
                        st.write(f"**Expiry Date:** {bom['expiry_date']}")
                
                with col3:
                    st.write(f"**Materials:** {bom.get('material_count', 0)}")
                    st.write(f"**Usage Count:** {bom.get('usage_count', 0)}")
                    st.write(f"**Created By:** {bom.get('created_by_name', 'System')}")
                
                # Action buttons
                col1, col2, col3 = st.columns(3)
                with col1:
                    if st.button("👁️ View Details", key=f"view_{bom['id']}", use_container_width=True):
                        st.session_state.selected_bom = bom['id']
                        st.session_state.bom_view = 'edit'
                        st.rerun()
                
                with col2:
                    if bom['status'] == 'ACTIVE' and st.button(
                        "📋 Copy BOM", key=f"copy_{bom['id']}", use_container_width=True
                    ):
                        try:
                            new_code = bom_manager.create_new_version(
                                bom['id'], st.session_state.user_id
                            )
                            show_success_message(f"Created new BOM version: {new_code}")
                            time.sleep(2)
                            st.rerun()
                        except Exception as e:
                            show_error_message("Error creating new version", str(e))
                
                with col3:
                    if bom['usage_count'] == 0 and st.button(
                        "🗑️ Delete", key=f"delete_{bom['id']}", use_container_width=True
                    ):
                        if st.session_state.get(f'confirm_delete_{bom["id"]}'):
                            try:
                                bom_manager.delete_bom(bom['id'], st.session_state.user_id)
                                show_success_message(f"Deleted BOM {bom['bom_code']}")
                                time.sleep(2)
                                st.rerun()
                            except Exception as e:
                                show_error_message("Error deleting BOM", str(e))
                        else:
                            st.session_state[f'confirm_delete_{bom["id"]}'] = True
                            st.warning("Click Delete again to confirm")
        
        # Export button
        st.markdown("---")
        if st.button("📥 Export BOM List to Excel", use_container_width=True):
            export_data = boms[['bom_code', 'bom_name', 'bom_type', 'product_name', 
                              'output_qty', 'uom', 'status', 'version', 'effective_date']]
            create_download_button(
                export_data,
                f"BOM_List_{date.today()}.xlsx",
                "Download BOM List",
                "excel"
            )
    else:
        st.info("No BOMs found matching the criteria")

elif st.session_state.bom_view == 'create':
    # Create New BOM
    st.subheader("➕ Create New BOM")
    
    # Get product options with info
    product_options, product_info, products = get_product_options_with_info()
    
    # Basic Information
    st.markdown("### Basic Information")
    col1, col2 = st.columns(2)
    
    with col1:
        bom_name = st.text_input("BOM Name*", placeholder="e.g., Standard Kit A")
        bom_type = st.selectbox("BOM Type*", ["KITTING", "CUTTING", "REPACKING"])
        
        if product_options:
            selected_product = st.selectbox(
                "Output Product*", 
                options=list(product_options.keys()),
                key='output_product_select'
            )
            product_id = product_options[selected_product] if selected_product else None
        else:
            st.error("No products found. Please add products first.")
            product_id = None
            selected_product = None
    
    with col2:
        output_qty = st.number_input("Output Quantity*", min_value=0.01, value=1.0, step=0.01)
        
        # Auto-fill UOM from selected product
        if product_id and product_id in product_info:
            uom = st.text_input(
                "UOM*", 
                value=product_info[product_id]['uom'], 
                disabled=True,
                help="Unit of Measure is automatically set from the selected product"
            )
        else:
            uom = st.text_input("UOM*", value="PCS")
        
        effective_date = st.date_input("Effective Date*", value=date.today())
    
    # Notes
    notes = st.text_area("Notes", placeholder="Optional notes about this BOM...")
    
    # Materials Section
    st.markdown("### Materials")
    
    # Add material section
    with st.container():
        col1, col2, col3, col4, col5, col6 = st.columns([3, 1.5, 1, 1.5, 1, 1])
        
        with col1:
            material_options = [""] + list(product_options.keys()) if product_options else [""]
            material_select = st.selectbox(
                "Select Material",
                options=material_options,
                key="new_material_select"
            )
        
        with col2:
            material_qty = st.number_input(
                "Quantity", 
                min_value=0.0001, 
                value=1.0, 
                step=0.0001, 
                key="new_material_qty"
            )
        
        with col3:
            # Auto-fill UOM for selected material
            if material_select and material_select != "" and material_select in product_options:
                selected_material_id = product_options[material_select]
                material_uom = st.text_input(
                    "UOM", 
                    value=product_info.get(selected_material_id, {}).get('uom', 'PCS'),
                    disabled=True,
                    key="new_material_uom"
                )
            else:
                material_uom = st.text_input("UOM", value="PCS", key="new_material_uom")
        
        with col4:
            material_type = st.selectbox(
                "Type", 
                ["RAW_MATERIAL", "PACKAGING", "CONSUMABLE"], 
                key="new_material_type"
            )
        
        with col5:
            scrap_rate = st.number_input(
                "Scrap %", 
                min_value=0.0, 
                max_value=50.0, 
                value=0.0, 
                step=0.1, 
                key="new_scrap_rate"
            )
        
        with col6:
            if st.button("➕ Add", use_container_width=True, type="primary"):
                if material_select and material_select != "":
                    # Validate
                    material_id = product_options[material_select]
                    is_valid, error_msg = validate_material_addition(
                        material_id, material_qty, scrap_rate
                    )
                    
                    if not is_valid:
                        st.error(error_msg)
                    else:
                        # Check if already exists
                        existing = [
                            m for m in st.session_state.temp_materials 
                            if m['material_id'] == material_id
                        ]
                        if existing:
                            st.warning("Material already added")
                        else:
                            st.session_state.temp_materials.append({
                                'material_id': material_id,
                                'material_name': material_select.split(" (")[0],
                                'quantity': material_qty,
                                'uom': material_uom,
                                'material_type': material_type,
                                'scrap_rate': scrap_rate
                            })
                            st.success("Material added!")
                            st.rerun()
                else:
                    st.error("Please select a material")
    
    # Display current materials
    if st.session_state.temp_materials:
        st.markdown("**Current Materials:**")
        
        # Create materials table
        for idx, material in enumerate(st.session_state.temp_materials):
            col1, col2, col3, col4, col5, col6 = st.columns([3, 1.5, 1, 1.5, 1, 1])
            
            with col1:
                st.text(material['material_name'])
            with col2:
                st.text(f"{material['quantity']:.4f}")
            with col3:
                st.text(material['uom'])
            with col4:
                st.text(material['material_type'])
            with col5:
                st.text(f"{material['scrap_rate']:.1f}%")
            with col6:
                if st.button("🗑️", key=f"remove_{idx}", use_container_width=True):
                    st.session_state.temp_materials.pop(idx)
                    st.rerun()
        
        # Clear all button
        if st.button("🗑️ Clear All Materials", type="secondary"):
            st.session_state.temp_materials = []
            st.rerun()
    else:
        st.info("No materials added yet. Add at least one material to create BOM.")
    
    # Submit section
    st.markdown("---")
    col1, col2, col3 = st.columns([2, 1, 2])
    with col2:
        create_disabled = not (bom_name and product_id and st.session_state.temp_materials)
        
        if st.button("Create BOM", type="primary", use_container_width=True, disabled=create_disabled):
            try:
                # Create BOM data
                bom_data = {
                    'bom_name': bom_name,
                    'bom_type': bom_type,
                    'product_id': product_id,
                    'output_qty': output_qty,
                    'uom': uom,
                    'effective_date': effective_date,
                    'notes': notes,
                    'materials': st.session_state.temp_materials,
                    'created_by': st.session_state.user_id
                }
                
                # Create BOM
                with st.spinner("Creating BOM..."):
                    bom_code = bom_manager.create_bom(bom_data)
                
                show_success_message(f"✅ BOM {bom_code} created successfully!")
                st.balloons()
                
                # Clear temp materials
                st.session_state.temp_materials = []
                time.sleep(2)
                st.session_state.bom_view = 'list'
                st.rerun()
                
            except Exception as e:
                show_error_message("Error creating BOM", str(e))
                logger.error(f"Error creating BOM: {e}")

elif st.session_state.bom_view == 'edit':
    # View/Edit BOM
    st.subheader("✏️ View/Edit BOM")
    
    # BOM selection if not already selected
    if not st.session_state.selected_bom:
        boms = bom_manager.get_boms()
        if not boms.empty:
            col1, col2 = st.columns([3, 1])
            with col1:
                bom_options = dict(zip(
                    boms['bom_code'] + " - " + boms['bom_name'] + " (" + 
                    boms['status'] + ")", 
                    boms['id']
                ))
                selected = st.selectbox("Select BOM to View/Edit", options=list(bom_options.keys()))
            with col2:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("Load BOM", type="primary", use_container_width=True):
                    st.session_state.selected_bom = bom_options[selected]
                    st.rerun()
        else:
            st.info("No BOMs found")
            if st.button("Create New BOM"):
                st.session_state.bom_view = 'create'
                st.rerun()
    else:
        # Load BOM details
        try:
            bom_info = bom_manager.get_bom_info(st.session_state.selected_bom)
            bom_details = bom_manager.get_bom_details(st.session_state.selected_bom)
            
            if not bom_info:
                st.error("BOM not found")
                st.session_state.selected_bom = None
                st.rerun()
            
            # Display BOM header info
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("BOM Code", bom_info['bom_code'])
            with col2:
                st.metric("Status", create_status_indicator(bom_info['status']))
            with col3:
                st.metric("Version", bom_info['version'])
            with col4:
                st.metric("Type", format_bom_type(bom_info['bom_type']))
            
            # BOM Information
            st.markdown(f"### {bom_info['bom_name']}")
            
            col1, col2 = st.columns(2)
            with col1:
                st.write(f"**Output Product:** {bom_info['product_name']}")
                st.write(f"**Output Quantity:** {format_number(bom_info['output_qty'])} {bom_info['uom']}")
                st.write(f"**Effective Date:** {bom_info['effective_date']}")
                if bom_info.get('expiry_date'):
                    st.write(f"**Expiry Date:** {bom_info['expiry_date']}")
            
            with col2:
                st.write(f"**Created Date:** {bom_info['created_date']}")
                st.write(f"**Created By:** {bom_info.get('created_by_name', 'System')}")
                if bom_info.get('notes'):
                    st.write(f"**Notes:** {bom_info['notes']}")
                usage_count = bom_info.get('total_usage', 0)
                active_orders = bom_info.get('active_orders', 0)
                st.write(f"**Usage:** {usage_count} times ({active_orders} active)")
            
            # Materials
            st.markdown("### Materials")
            if not bom_details.empty:
                # Calculate totals
                bom_details['total_qty_with_scrap'] = (
                    bom_details['quantity'] * (1 + bom_details['scrap_rate']/100)
                )
                
                # Display materials
                st.dataframe(
                    bom_details[[
                        'material_name', 'material_code', 'material_type', 
                        'quantity', 'uom', 'scrap_rate', 'total_qty_with_scrap', 
                        'current_stock'
                    ]],
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "material_name": "Material",
                        "material_code": "Code",
                        "material_type": "Type",
                        "quantity": st.column_config.NumberColumn("Base Qty", format="%.4f"),
                        "uom": "UOM",
                        "scrap_rate": st.column_config.NumberColumn("Scrap %", format="%.1f"),
                        "total_qty_with_scrap": st.column_config.NumberColumn("Total Qty", format="%.4f"),
                        "current_stock": st.column_config.NumberColumn("Stock", format="%.2f")
                    }
                )
                
                # Export materials
                if st.button("📥 Export Materials List"):
                    create_download_button(
                        bom_details,
                        f"BOM_Materials_{bom_info['bom_code']}_{date.today()}.csv",
                        "Download Materials",
                        "csv"
                    )
            else:
                st.warning("No materials found for this BOM")
            
            # Actions
            st.markdown("### Actions")
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                # Status update
                current_status = bom_info['status']
                status_options = {
                    'DRAFT': ['ACTIVE', 'INACTIVE'],
                    'ACTIVE': ['INACTIVE'],
                    'INACTIVE': ['ACTIVE', 'DRAFT']
                }
                
                new_status = st.selectbox(
                    "Change Status", 
                    [current_status] + status_options.get(current_status, [])
                )
                
                if st.button("Update Status", use_container_width=True, 
                            disabled=(new_status == current_status)):
                    try:
                        bom_manager.update_bom_status(
                            st.session_state.selected_bom, 
                            new_status, 
                            st.session_state.user_id
                        )
                        show_success_message(f"✅ BOM status updated to {new_status}")
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        show_error_message("Error updating BOM status", str(e))
            
            with col2:
                if st.button("📋 Create New Version", use_container_width=True):
                    try:
                        new_code = bom_manager.create_new_version(
                            st.session_state.selected_bom,
                            st.session_state.user_id
                        )
                        show_success_message(f"✅ Created new version: {new_code}")
                        time.sleep(2)
                        st.session_state.selected_bom = None
                        st.session_state.bom_view = 'list'
                        st.rerun()
                    except Exception as e:
                        show_error_message("Error creating new version", str(e))
            
            with col3:
                # Validate BOM
                if st.button("🔍 Validate BOM", use_container_width=True):
                    validation = bom_manager.validate_bom_materials(st.session_state.selected_bom)
                    if validation['valid']:
                        st.success("✅ BOM is valid")
                    else:
                        for error in validation['errors']:
                            st.error(error)
                    for warning in validation.get('warnings', []):
                        st.warning(warning)
            
            with col4:
                if st.button("← Back to List", use_container_width=True):
                    st.session_state.selected_bom = None
                    st.session_state.bom_view = 'list'
                    st.rerun()
                    
        except Exception as e:
            show_error_message("Error loading BOM", str(e))
            logger.error(f"Error loading BOM: {e}")
            st.session_state.selected_bom = None

elif st.session_state.bom_view == 'analysis':
    # BOM Analysis
    st.subheader("📊 BOM Analysis")
    
    # Analysis type selection
    analysis_type = st.selectbox(
        "Select Analysis Type",
        ["Material Usage Summary", "Where Used Analysis", "BOM Comparison", "Cost Analysis"]
    )
    
    if analysis_type == "Material Usage Summary":
        st.markdown("### Material Usage Analysis")
        
        with st.spinner("Analyzing material usage..."):
            material_usage = bom_manager.get_material_usage_summary()
        
        if not material_usage.empty:
            # Summary metrics
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Materials", len(material_usage))
            with col2:
                avg_usage = material_usage['usage_count'].mean()
                st.metric("Avg Usage per Material", f"{avg_usage:.1f} BOMs")
            with col3:
                if len(material_usage) > 0:
                    st.metric("Most Used Material", material_usage.iloc[0]['material_name'])
            
            # Top 10 chart
            st.markdown("**Top 10 Most Used Materials**")
            top_materials = material_usage.head(10)
            
            # Create bar chart
            chart_data = top_materials.set_index('material_name')[['usage_count']]
            st.bar_chart(chart_data)
            
            # Detailed table
            st.markdown("**Detailed Material Usage**")
            st.dataframe(
                material_usage,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "material_name": "Material",
                    "material_code": "Code",
                    "usage_count": st.column_config.NumberColumn("Used in # BOMs", format="%d"),
                    "total_base_quantity": st.column_config.NumberColumn("Total Quantity", format="%.2f"),
                    "avg_scrap_rate": st.column_config.NumberColumn("Avg Scrap %", format="%.1f"),
                    "bom_types": "BOM Types",
                    "active_bom_count": st.column_config.NumberColumn("Active BOMs", format="%d")
                }
            )
            
            # Export
            if st.button("📥 Export Material Usage Report"):
                create_download_button(
                    material_usage,
                    f"Material_Usage_Report_{date.today()}.csv",
                    "Download Report",
                    "csv"
                )
        else:
            st.info("No material usage data found")
    
    elif analysis_type == "Where Used Analysis":
        st.markdown("### Where Used Analysis")
        st.write("Find all BOMs where a specific product/material is used")
        
        # Get product options
        product_options, _, _ = get_product_options_with_info()
        
        if product_options:
            col1, col2 = st.columns([3, 1])
            with col1:
                selected_product = st.selectbox(
                    "Select Product/Material", 
                    options=list(product_options.keys())
                )
            with col2:
                st.markdown("<br>", unsafe_allow_html=True)
                analyze_btn = st.button("Analyze", type="primary", use_container_width=True)
            
            if analyze_btn and selected_product:
                product_id = product_options[selected_product]
                
                with st.spinner("Searching BOMs..."):
                    where_used = bom_manager.get_where_used(product_id)
                
                if not where_used.empty:
                    st.success(f"**{selected_product} is used in {len(where_used)} BOM(s):**")
                    
                    # Separate by status
                    active_boms = where_used[where_used['bom_status'] == 'ACTIVE']
                    inactive_boms = where_used[where_used['bom_status'] != 'ACTIVE']
                    
                    if not active_boms.empty:
                        st.markdown("**Active BOMs:**")
                        st.dataframe(
                            active_boms[[
                                'bom_code', 'bom_name', 'output_product_name', 
                                'quantity', 'uom', 'material_type', 'total_requirement'
                            ]],
                            use_container_width=True,
                            hide_index=True,
                            column_config={
                                "bom_code": "BOM Code",
                                "bom_name": "BOM Name",
                                "output_product_name": "Output Product",
                                "quantity": st.column_config.NumberColumn("Base Qty", format="%.4f"),
                                "uom": "UOM",
                                "material_type": "Type",
                                "total_requirement": st.column_config.NumberColumn("Total Req", format="%.4f")
                            }
                        )
                    
                    if not inactive_boms.empty:
                        with st.expander("Other BOMs (Draft/Inactive)"):
                            st.dataframe(
                                inactive_boms[[
                                    'bom_code', 'bom_name', 'bom_status', 
                                    'quantity', 'uom'
                                ]],
                                use_container_width=True,
                                hide_index=True
                            )
                    
                    # Export
                    if st.button("📥 Export Where Used Report"):
                        create_download_button(
                            where_used,
                            f"Where_Used_{selected_product.split(' (')[0]}_{date.today()}.csv",
                            "Download Report",
                            "csv"
                        )
                else:
                    st.info(f"{selected_product} is not used in any BOM")
        else:
            st.error("No products found in the system")
    
    elif analysis_type == "BOM Comparison":
        st.markdown("### BOM Comparison")
        
        # Get active BOMs for comparison
        active_boms = bom_manager.get_boms(status='ACTIVE')
        
        if len(active_boms) >= 2:
            col1, col2 = st.columns(2)
            
            with col1:
                bom1_options = dict(zip(
                    active_boms['bom_code'] + " - " + active_boms['bom_name'],
                    active_boms['id']
                ))
                selected_bom1 = st.selectbox("Select First BOM", options=list(bom1_options.keys()))
            
            with col2:
                # Filter out selected BOM1
                bom2_list = [k for k in bom1_options.keys() if k != selected_bom1]
                selected_bom2 = st.selectbox("Select Second BOM", options=bom2_list)
            
            if st.button("Compare BOMs", type="primary"):
                bom1_id = bom1_options[selected_bom1]
                bom2_id = bom1_options[selected_bom2]
                
                # Get details for both BOMs
                bom1_details = bom_manager.get_bom_details(bom1_id)
                bom2_details = bom_manager.get_bom_details(bom2_id)
                
                # Merge for comparison
                comparison = pd.merge(
                    bom1_details[['material_id', 'material_name', 'quantity', 'uom']],
                    bom2_details[['material_id', 'material_name', 'quantity', 'uom']],
                    on=['material_id', 'material_name'],
                    how='outer',
                    suffixes=('_bom1', '_bom2')
                )
                
                # Calculate differences
                comparison['qty_diff'] = (
                    comparison['quantity_bom2'].fillna(0) - 
                    comparison['quantity_bom1'].fillna(0)
                )
                comparison['status'] = comparison.apply(
                    lambda row: 'Only in BOM1' if pd.isna(row['quantity_bom2']) 
                    else 'Only in BOM2' if pd.isna(row['quantity_bom1'])
                    else 'Different' if row['qty_diff'] != 0
                    else 'Same', axis=1
                )
                
                # Display comparison
                st.markdown("### Comparison Results")
                
                # Summary
                col1, col2, col3 = st.columns(3)
                with col1:
                    same_count = len(comparison[comparison['status'] == 'Same'])
                    st.metric("Same Materials", same_count)
                with col2:
                    diff_count = len(comparison[comparison['status'] == 'Different'])
                    st.metric("Different Quantities", diff_count)
                with col3:
                    unique_count = len(
                        comparison[comparison['status'].isin(['Only in BOM1', 'Only in BOM2'])]
                    )
                    st.metric("Unique Materials", unique_count)
                
                # Detailed comparison
                st.dataframe(
                    comparison,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "material_name": "Material",
                        "quantity_bom1": st.column_config.NumberColumn(
                            f"Qty ({selected_bom1.split(' - ')[0]})", 
                            format="%.4f"
                        ),
                        "quantity_bom2": st.column_config.NumberColumn(
                            f"Qty ({selected_bom2.split(' - ')[0]})", 
                            format="%.4f"
                        ),
                        "qty_diff": st.column_config.NumberColumn("Difference", format="%.4f"),
                        "status": "Status"
                    }
                )
        else:
            st.info("Need at least 2 active BOMs for comparison")
    
    elif analysis_type == "Cost Analysis":
        st.markdown("### Cost Analysis")
        st.info("Cost analysis feature will be available once pricing data is integrated")
        
        # Placeholder for future cost analysis
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Material Cost", "N/A", help="Requires pricing data")
        with col2:
            st.metric("Labor Cost", "N/A", help="Requires labor rates")
        with col3:
            st.metric("Total Cost", "N/A", help="Sum of all costs")

# Footer
st.markdown("---")
st.caption("BOM Management System v2.0 - Enhanced Edition")