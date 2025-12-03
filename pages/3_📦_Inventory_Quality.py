# pages/3_📦_Inventory_Quality.py
"""
Inventory Quality Dashboard
Track and manage Good, Quarantine, and Defective inventory

Version: 1.0.0
Features:
- Summary metrics cards
- Unified inventory table with single-row selection
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
    init_session_state,
    clear_selection,
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

init_session_state()
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
            clear_selection()
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
            clear_selection()
            st.rerun()
    
    return selected_category, warehouse_id, product_search


# ==================== Data Table ====================

def render_data_table(df: pd.DataFrame):
    """Render inventory data table with single-row selection"""
    if df.empty:
        st.info("No inventory items found matching the selected filters.")
        return
    
    st.markdown(f"**Found {len(df):,} items**")
    
    # Prepare display dataframe
    display_df = df.copy()
    
    # Add row index for selection
    display_df.insert(0, 'Select', False)
    display_df.insert(1, '#', range(1, len(display_df) + 1))
    
    # Category badge
    display_df['Category'] = display_df['category'].apply(
        lambda x: InventoryQualityConstants.CATEGORY_DISPLAY.get(x, x)
    )
    
    # Format columns
    display_df['Quantity'] = display_df['quantity'].apply(format_quantity)
    display_df['Value'] = display_df['inventory_value_usd'].apply(
        lambda x: format_currency(x) if pd.notna(x) else '-'
    )
    display_df['Days'] = display_df['days_in_warehouse'].apply(format_days)
    
    # Select columns to display
    columns_to_show = [
        '#', 'Category', 'product_name', 'pt_code', 'batch_number',
        'Quantity', 'uom', 'warehouse_name', 'source_type', 'Days', 'Value'
    ]
    
    # Filter existing columns
    columns_to_show = [c for c in columns_to_show if c in display_df.columns]
    
    # Column configuration
    column_config = {
        '#': st.column_config.NumberColumn('#', width='small'),
        'Category': st.column_config.TextColumn('Category', width='medium'),
        'product_name': st.column_config.TextColumn('Product', width='large'),
        'pt_code': st.column_config.TextColumn('PT Code', width='medium'),
        'batch_number': st.column_config.TextColumn('Batch', width='medium'),
        'Quantity': st.column_config.TextColumn('Qty', width='small'),
        'uom': st.column_config.TextColumn('UOM', width='small'),
        'warehouse_name': st.column_config.TextColumn('Warehouse', width='medium'),
        'source_type': st.column_config.TextColumn('Source', width='medium'),
        'Days': st.column_config.TextColumn('Age', width='small'),
        'Value': st.column_config.TextColumn('Value', width='small')
    }
    
    # Single row selection using radio buttons
    st.markdown("##### Select an item to view details:")
    
    # Create selection options
    selection_options = []
    for idx, row in df.iterrows():
        category_icon = {'GOOD': '📗', 'QUARANTINE': '📙', 'DEFECTIVE': '📕'}.get(row['category'], '📦')
        label = f"{category_icon} {row['product_name']} | Batch: {row.get('batch_number', 'N/A')} | Qty: {format_quantity(row['quantity'])} | {row.get('warehouse_name', 'N/A')}"
        selection_options.append((idx, label, row))
    
    # Display table
    st.dataframe(
        display_df[columns_to_show],
        use_container_width=True,
        hide_index=True,
        height=400,
        column_config=column_config
    )
    
    # Selection via selectbox below table
    st.markdown("---")
    col1, col2 = st.columns([3, 1])
    
    with col1:
        selected_idx = st.selectbox(
            "Select item to view details",
            options=range(len(df)),
            format_func=lambda i: f"Row {i+1}: {df.iloc[i]['product_name']} - {df.iloc[i].get('batch_number', 'N/A')}",
            key="iq_row_selector",
            index=None,
            placeholder="Click to select an item..."
        )
    
    with col2:
        st.write("")
        st.write("")
        if selected_idx is not None:
            if st.button("🔍 View Details", type="primary", use_container_width=True):
                st.session_state['iq_selected_row'] = df.iloc[selected_idx].to_dict()
                st.session_state['iq_show_detail_dialog'] = True
                st.rerun()
    
    return df


# ==================== Detail Dialog ====================

@st.dialog("📋 Inventory Item Details", width="large")
def render_detail_dialog(item: dict):
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
    st.markdown("#### 🏭 Location")
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown(f"**Warehouse:** {safe_get(item, 'warehouse_name', '-')}")
    
    with col2:
        st.markdown(f"**Source:** {safe_get(item, 'source_type', '-')}")
    
    st.markdown("---")
    
    # Category-specific details
    if category == 'GOOD':
        render_good_details(item)
    elif category == 'QUARANTINE':
        render_quarantine_details(item)
    elif category == 'DEFECTIVE':
        render_defective_details(item)
    
    # Close button
    st.markdown("---")
    if st.button("✖️ Close", use_container_width=True):
        st.session_state['iq_show_detail_dialog'] = False
        st.session_state['iq_selected_row'] = None
        st.rerun()


def render_good_details(item: dict):
    """Render details specific to GOOD inventory"""
    st.markdown("#### 📊 Stock Details")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown(f"**Days in Warehouse:** {format_days(safe_get(item, 'days_in_warehouse'))}")
        st.markdown(f"**Age Category:** {safe_get(item, 'age_category', '-')}")
    
    with col2:
        st.markdown(f"**Expiry Status:** {safe_get(item, 'expiry_status', '-')}")
        st.markdown(f"**Value (USD):** {format_currency(safe_get(item, 'inventory_value_usd'))}")
    
    with col3:
        st.markdown(f"**PO Number:** {safe_get(item, 'po_number', '-')}")
        st.markdown(f"**Vendor:** {safe_get(item, 'vendor_name', '-')}")
    
    # Arrival info if available
    if safe_get(item, 'arrival_date'):
        st.markdown("---")
        st.markdown("#### 🚚 Arrival Information")
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown(f"**Arrival Date:** {format_date(safe_get(item, 'arrival_date'))}")
            st.markdown(f"**Arrival Note:** {safe_get(item, 'arrival_note_number', '-')}")
        
        with col2:
            st.markdown(f"**Landed Cost:** {format_currency(safe_get(item, 'arrival_landed_cost'))}")


def render_quarantine_details(item: dict):
    """Render details specific to QUARANTINE inventory"""
    st.markdown("#### ⏳ QC Pending Details")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown(f"**Days Pending:** {format_days(safe_get(item, 'days_in_warehouse'))}")
        st.markdown(f"**Manufacturing Order:** {safe_get(item, 'related_order_no', '-')}")
    
    with col2:
        st.markdown(f"**Defect Type:** {safe_get(item, 'defect_type', '-')}")
    
    # Notes
    notes = safe_get(item, 'notes')
    if notes:
        st.markdown("---")
        st.markdown("#### 📝 Notes")
        st.text_area("", value=notes, disabled=True, height=100, label_visibility="collapsed")


def render_defective_details(item: dict):
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
        st.text_area("", value=notes, disabled=True, height=100, label_visibility="collapsed")


# ==================== Export ====================

def render_export_section(df: pd.DataFrame, category: str, warehouse_id: int):
    """Render export to Excel section"""
    st.markdown("---")
    
    col1, col2, col3 = st.columns([2, 2, 4])
    
    with col1:
        if st.button("📥 Export to Excel", use_container_width=True):
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
                        use_container_width=True
                    )
                else:
                    st.warning("No data to export")
                    
            except Exception as e:
                st.error(f"Export failed: {str(e)}")
                logger.error(f"Export error: {e}", exc_info=True)
    
    with col2:
        st.caption(f"Total: {len(df):,} items")


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
        
        # Data Table
        render_data_table(df)
        
        # Export Section
        if not df.empty:
            render_export_section(df, category, warehouse_id)
        
        # Detail Dialog
        if st.session_state.get('iq_show_detail_dialog') and st.session_state.get('iq_selected_row'):
            render_detail_dialog(st.session_state['iq_selected_row'])
    
    except Exception as e:
        st.error(f"An error occurred: {str(e)}")
        logger.error(f"Application error: {e}", exc_info=True)
        
        if st.button("🔄 Reload"):
            st.cache_data.clear()
            clear_selection()
            st.rerun()
    
    # Footer
    st.markdown("---")
    st.caption("Inventory Quality Dashboard v1.0")


if __name__ == "__main__":
    main()
