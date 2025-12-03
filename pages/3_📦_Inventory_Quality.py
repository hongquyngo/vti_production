# pages/3_📦_Inventory_Quality.py
"""
Inventory Quality Dashboard
Track and manage Good, Quarantine, and Defective inventory

Version: 1.1.0
Changes:
- Checkbox selection pattern like Production module
- Action buttons appear when row selected
- Detail popup dialog

Features:
- Summary metrics cards
- Unified inventory table with single-row checkbox selection
- Action buttons (View Details)
- Detail popup dialog
- Export to Excel
- Filter by Category, Warehouse, Product
"""

import streamlit as st
import logging
import pandas as pd
from datetime import datetime

from utils.auth import AuthManager
from utils.inventory_quality.common import (
    InventoryQualityConstants,
    format_quantity,
    format_currency,
    format_date,
    format_days,
    create_excel_download,
    safe_get
)
from utils.inventory_quality.data import InventoryQualityData

logger = logging.getLogger(__name__)

# ==================== Page Configuration ====================

st.set_page_config(
    page_title="Inventory Quality",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ==================== Authentication ====================

auth = AuthManager()
auth.require_auth()

# ==================== Initialize ====================

def _init_session_state():
    """Initialize session state for Inventory Quality page"""
    defaults = {
        'iq_selected_idx': None,
        'iq_show_detail': False,
        'iq_detail_data': None,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)

_init_session_state()
data_loader = InventoryQualityData()

# ==================== Header ====================

def render_header():
    """Render page header with refresh button"""
    col1, col2 = st.columns([4, 1])
    
    with col1:
        st.title("📦 Inventory Quality Dashboard")
        st.caption("Track Good, Quarantine, and Defective inventory")
    
    with col2:
        if st.button("🔄 Refresh", use_container_width=True):
            st.cache_data.clear()
            st.session_state['iq_selected_idx'] = None
            st.rerun()


# ==================== Summary Cards ====================

def render_summary_cards():
    """Render summary metric cards"""
    metrics = data_loader.get_summary_metrics()
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        good = metrics.get('GOOD', {})
        st.metric(
            label="📗 Good Stock",
            value=f"{good.get('count', 0):,} items",
            delta=f"{format_quantity(good.get('quantity', 0))} units"
        )
    
    with col2:
        quarantine = metrics.get('QUARANTINE', {})
        st.metric(
            label="📙 Quarantine (Pending QC)",
            value=f"{quarantine.get('count', 0):,} items",
            delta=f"{format_quantity(quarantine.get('quantity', 0))} units",
            delta_color="off"
        )
    
    with col3:
        defective = metrics.get('DEFECTIVE', {})
        st.metric(
            label="📕 Defective",
            value=f"{defective.get('count', 0):,} items",
            delta=f"{format_quantity(defective.get('quantity', 0))} units",
            delta_color="inverse"
        )
    
    with col4:
        defective_value = metrics.get('DEFECTIVE', {}).get('value', 0)
        quarantine_value = metrics.get('QUARANTINE', {}).get('value', 0)
        at_risk = defective_value + quarantine_value
        st.metric(
            label="💰 Value at Risk",
            value=format_currency(at_risk),
            delta="Defective + Quarantine",
            delta_color="off"
        )


# ==================== Filters ====================

def render_filters():
    """Render filter controls"""
    col1, col2, col3, col4 = st.columns([2, 2, 3, 2])
    
    with col1:
        category_options = ['All', 'GOOD', 'QUARANTINE', 'DEFECTIVE']
        category_display = {
            'All': '🔍 All Categories',
            'GOOD': '📗 Good',
            'QUARANTINE': '📙 Quarantine',
            'DEFECTIVE': '📕 Defective'
        }
        
        selected_category = st.selectbox(
            "Category",
            options=category_options,
            format_func=lambda x: category_display.get(x, x),
            key="iq_category_filter"
        )
    
    with col2:
        warehouses = data_loader.get_warehouses()
        warehouse_options = [{'id': None, 'name': 'All Warehouses'}] + warehouses
        
        selected_warehouse = st.selectbox(
            "Warehouse",
            options=warehouse_options,
            format_func=lambda x: x.get('name', 'Unknown'),
            key="iq_warehouse_select"
        )
        warehouse_id = selected_warehouse.get('id') if selected_warehouse else None
    
    with col3:
        product_search = st.text_input(
            "Search Product",
            placeholder="Enter product name or PT code...",
            key="iq_product_search"
        )
    
    with col4:
        st.write("")  # Spacer
        st.write("")
        if st.button("🔄 Clear Filters", use_container_width=True):
            st.session_state['iq_category_filter'] = 'All'
            st.session_state['iq_warehouse_select'] = {'id': None, 'name': 'All Warehouses'}
            st.session_state['iq_product_search'] = ''
            st.session_state['iq_selected_idx'] = None
            st.rerun()
    
    return selected_category, warehouse_id, product_search


# ==================== Category Indicator ====================

def create_category_indicator(category: str) -> str:
    """Create category indicator with icon"""
    indicators = {
        'GOOD': '📗 Good',
        'QUARANTINE': '📙 Quarantine',
        'DEFECTIVE': '📕 Defective'
    }
    return indicators.get(category, category)


# ==================== Data Table with Checkbox Selection ====================

def render_data_table(df: pd.DataFrame):
    """Render inventory data table with single-row checkbox selection"""
    if df.empty:
        st.info("📭 No inventory items found matching the selected filters.")
        return None
    
    st.markdown(f"**Found {len(df):,} items** | 💡 Tick checkbox to select an item and view details")
    
    # Initialize selected index in session state
    if 'iq_selected_idx' not in st.session_state:
        st.session_state.iq_selected_idx = None
    
    # Prepare display dataframe - reset index for consistent positioning
    display_df = df.reset_index(drop=True).copy()
    
    # Set Select column based on session state (single selection)
    display_df['Select'] = False
    if st.session_state.iq_selected_idx is not None and st.session_state.iq_selected_idx < len(display_df):
        display_df.loc[st.session_state.iq_selected_idx, 'Select'] = True
    
    # Format columns for display
    display_df['category_display'] = display_df['category'].apply(create_category_indicator)
    display_df['qty_display'] = display_df.apply(
        lambda x: f"{format_quantity(x['quantity'])} {x.get('uom', '')}", axis=1
    )
    display_df['value_display'] = display_df['inventory_value_usd'].apply(
        lambda x: format_currency(x) if pd.notna(x) else '-'
    )
    display_df['days_display'] = display_df['days_in_warehouse'].apply(format_days)
    
    # Create editable dataframe with selection
    edited_df = st.data_editor(
        display_df[[
            'Select', 'category_display', 'product_name', 'pt_code', 'batch_number',
            'qty_display', 'warehouse_name', 'source_type', 'days_display', 'value_display'
        ]].rename(columns={
            'category_display': 'Category',
            'product_name': 'Product',
            'pt_code': 'PT Code',
            'batch_number': 'Batch',
            'qty_display': 'Quantity',
            'warehouse_name': 'Warehouse',
            'source_type': 'Source',
            'days_display': 'Age',
            'value_display': 'Value'
        }),
        use_container_width=True,
        hide_index=True,
        height=450,
        disabled=['Category', 'Product', 'PT Code', 'Batch', 'Quantity', 'Warehouse', 'Source', 'Age', 'Value'],
        column_config={
            'Select': st.column_config.CheckboxColumn(
                '✓',
                help='Select row to view details',
                default=False,
                width='small'
            ),
            'Category': st.column_config.TextColumn('Category', width='medium'),
            'Product': st.column_config.TextColumn('Product', width='large'),
            'PT Code': st.column_config.TextColumn('PT Code', width='medium'),
            'Batch': st.column_config.TextColumn('Batch', width='medium'),
            'Quantity': st.column_config.TextColumn('Qty', width='small'),
            'Warehouse': st.column_config.TextColumn('Warehouse', width='medium'),
            'Source': st.column_config.TextColumn('Source', width='medium'),
            'Age': st.column_config.TextColumn('Age', width='small'),
            'Value': st.column_config.TextColumn('Value', width='small')
        },
        key="iq_table_editor"
    )
    
    # Handle single selection - find newly selected row
    selected_indices = edited_df[edited_df['Select'] == True].index.tolist()
    
    if selected_indices:
        # If multiple selected (user clicked new one), keep only the newest
        if len(selected_indices) > 1:
            # Find the new selection (not the previously stored one)
            new_selection = [idx for idx in selected_indices if idx != st.session_state.iq_selected_idx]
            if new_selection:
                st.session_state.iq_selected_idx = new_selection[0]
                st.rerun()
        else:
            st.session_state.iq_selected_idx = selected_indices[0]
    else:
        st.session_state.iq_selected_idx = None
    
    # Action buttons - only show when row is selected
    if st.session_state.iq_selected_idx is not None and st.session_state.iq_selected_idx < len(display_df):
        selected_item = display_df.iloc[st.session_state.iq_selected_idx]
        category = selected_item.get('category', '')
        product_name = selected_item.get('product_name', 'Unknown')
        batch = selected_item.get('batch_number', 'N/A')
        qty = format_quantity(selected_item.get('quantity', 0))
        
        st.markdown("---")
        st.markdown(f"**Selected:** {create_category_indicator(category)} | `{product_name}` | Batch: `{batch}` | Qty: {qty}")
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            if st.button("🔍 View Details", type="primary", use_container_width=True, key="btn_view_detail"):
                st.session_state['iq_detail_data'] = selected_item.to_dict()
                st.session_state['iq_show_detail'] = True
                st.rerun()
        
        with col2:
            # Placeholder for future actions
            st.button("📋 Actions", use_container_width=True, disabled=True, 
                     help="Coming soon: QC Approve, Repair, Scrap", key="btn_actions")
        
        with col3:
            if st.button("❌ Deselect", use_container_width=True, key="btn_deselect"):
                st.session_state['iq_selected_idx'] = None
                st.rerun()
    else:
        st.info("💡 Tick checkbox to select an item and perform actions")
    
    return df


# ==================== Detail Dialog ====================

@st.dialog("📋 Inventory Item Details", width="large")
def show_detail_dialog(item: dict):
    """Render detail popup dialog for selected item"""
    category = item.get('category', 'UNKNOWN')
    
    # Header with category badge
    category_display = InventoryQualityConstants.CATEGORY_DISPLAY.get(category, category)
    st.markdown(f"### {category_display}")
    st.markdown("---")
    
    # Product Info Section
    st.markdown("#### 📦 Product Information")
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown(f"**Product:** {safe_get(item, 'product_name', '-')}")
        st.markdown(f"**PT Code:** {safe_get(item, 'pt_code', '-')}")
        st.markdown(f"**Brand:** {safe_get(item, 'brand', '-')}")
    
    with col2:
        st.markdown(f"**Batch:** {safe_get(item, 'batch_number', '-')}")
        st.markdown(f"**Quantity:** {format_quantity(safe_get(item, 'quantity'))} {safe_get(item, 'uom', '')}")
        st.markdown(f"**Expiry Date:** {format_date(safe_get(item, 'expiry_date'))}")
    
    st.markdown("---")
    
    # Location Section
    st.markdown("#### 🏭 Location & Source")
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown(f"**Warehouse:** {safe_get(item, 'warehouse_name', '-')}")
        st.markdown(f"**Days in Warehouse:** {format_days(safe_get(item, 'days_in_warehouse'))}")
    
    with col2:
        st.markdown(f"**Source:** {safe_get(item, 'source_type', '-')}")
        st.markdown(f"**Age Category:** {safe_get(item, 'age_category', '-')}")
    
    st.markdown("---")
    
    # Category-specific details
    if category == 'GOOD':
        _render_good_details(item)
    elif category == 'QUARANTINE':
        _render_quarantine_details(item)
    elif category == 'DEFECTIVE':
        _render_defective_details(item)
    
    # Close button
    st.markdown("---")
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        if st.button("✖️ Close", use_container_width=True, key="btn_close_dialog"):
            st.session_state['iq_show_detail'] = False
            st.session_state['iq_detail_data'] = None
            st.rerun()


def _render_good_details(item: dict):
    """Render details specific to GOOD inventory"""
    st.markdown("#### 📊 Stock Details")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown(f"**Expiry Status:** {safe_get(item, 'expiry_status', '-')}")
        st.markdown(f"**Value (USD):** {format_currency(safe_get(item, 'inventory_value_usd'))}")
    
    with col2:
        st.markdown(f"**PO Number:** {safe_get(item, 'po_number', '-')}")
        st.markdown(f"**Vendor:** {safe_get(item, 'vendor_name', '-')}")
    
    with col3:
        st.markdown(f"**Arrival Date:** {format_date(safe_get(item, 'arrival_date'))}")
        st.markdown(f"**Landed Cost:** {format_currency(safe_get(item, 'arrival_landed_cost'))}")


def _render_quarantine_details(item: dict):
    """Render details specific to QUARANTINE inventory"""
    st.markdown("#### ⏳ QC Pending Details")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown(f"**Status:** QC Pending")
        st.markdown(f"**Days Pending:** {format_days(safe_get(item, 'days_in_warehouse'))}")
    
    with col2:
        st.markdown(f"**Manufacturing Order:** {safe_get(item, 'related_order_no', '-')}")
    
    # Notes
    notes = safe_get(item, 'notes')
    if notes:
        st.markdown("---")
        st.markdown("#### 📝 Notes")
        st.text_area("", value=notes, disabled=True, height=80, label_visibility="collapsed")


def _render_defective_details(item: dict):
    """Render details specific to DEFECTIVE inventory"""
    st.markdown("#### ⚠️ Defect Details")
    
    col1, col2 = st.columns(2)
    
    with col1:
        defect_type = safe_get(item, 'defect_type', '-')
        defect_display = InventoryQualityConstants.DEFECT_TYPES.get(defect_type, defect_type)
        st.markdown(f"**Defect Type:** {defect_display}")
        st.markdown(f"**Days Since Defect:** {format_days(safe_get(item, 'days_in_warehouse'))}")
    
    with col2:
        st.markdown(f"**Related Order:** {safe_get(item, 'related_order_no', '-')}")
        st.markdown(f"**Source:** {safe_get(item, 'source_type', '-')}")
    
    # Notes
    notes = safe_get(item, 'notes')
    if notes:
        st.markdown("---")
        st.markdown("#### 📝 Notes / Reason")
        st.text_area("", value=notes, disabled=True, height=80, label_visibility="collapsed")


# ==================== Export Section ====================

def render_export_section(df: pd.DataFrame, category: str, warehouse_id: int):
    """Render export to Excel section"""
    col1, col2 = st.columns([1, 4])
    
    with col1:
        if st.button("📥 Export to Excel", use_container_width=True, key="btn_export"):
            try:
                export_df = data_loader.get_export_data(
                    category=category if category != 'All' else None,
                    warehouse_id=warehouse_id
                )
                
                if not export_df.empty:
                    excel_data = create_excel_download(export_df)
                    
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    filename = f"inventory_quality_{timestamp}.xlsx"
                    
                    st.download_button(
                        label="⬇️ Download Excel",
                        data=excel_data,
                        file_name=filename,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="download_excel"
                    )
                else:
                    st.warning("No data to export")
                    
            except Exception as e:
                st.error(f"Export failed: {str(e)}")
                logger.error(f"Export error: {e}", exc_info=True)


# ==================== Main Application ====================

def main():
    """Main application entry point"""
    try:
        render_header()
        st.markdown("---")
        
        # Summary Cards
        render_summary_cards()
        st.markdown("---")
        
        # Filters
        category, warehouse_id, product_search = render_filters()
        st.markdown("---")
        
        # Load Data
        with st.spinner("Loading inventory data..."):
            df = data_loader.get_unified_inventory(
                category=category if category != 'All' else None,
                warehouse_id=warehouse_id,
                product_search=product_search if product_search else None
            )
        
        # Data Table with selection
        render_data_table(df)
        
        # Export Section
        if not df.empty:
            st.markdown("---")
            render_export_section(df, category, warehouse_id)
        
        # Show Detail Dialog if triggered
        if st.session_state.get('iq_show_detail') and st.session_state.get('iq_detail_data'):
            show_detail_dialog(st.session_state['iq_detail_data'])
    
    except Exception as e:
        st.error(f"An error occurred: {str(e)}")
        logger.error(f"Application error: {e}", exc_info=True)
        
        if st.button("🔄 Reload"):
            st.cache_data.clear()
            st.session_state['iq_selected_idx'] = None
            st.rerun()
    
    # Footer
    st.markdown("---")
    st.caption("Inventory Quality Dashboard v1.1")


if __name__ == "__main__":
    main()