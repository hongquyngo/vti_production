# pages/3_📦_Inventory_Quality.py
"""
Inventory Quality Dashboard
Track and manage Good, Quarantine, and Defective inventory

Version: 1.2.0
Changes:
- v1.2: Added "Tổng hợp tồn kho" (Inventory Period Summary) tab
- v1.1: Checkbox selection pattern like Production module
- v1.1: Action buttons appear when row selected
- v1.1: Detail popup dialog

Features:
- Tab 1: Dashboard - Summary metrics, unified inventory table, detail dialog
- Tab 2: Tổng hợp tồn kho - Period-based inventory summary report
  + Period presets (This Month, Last Month, Quarter, Year, Custom)
  + Opening / Stock In / Stock Out / Closing per product
  + Export to Excel with formatted header
"""

import re
import streamlit as st
import logging
import pandas as pd
from datetime import datetime, date

from utils.auth import AuthManager
from utils.inventory_quality.common import (
    InventoryQualityConstants,
    format_quantity,
    format_currency,
    format_date,
    format_days,
    format_report_qty,
    create_excel_download,
    create_period_summary_excel,
    get_period_dates,
    get_vietnam_today,
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
    today = get_vietnam_today()
    defaults = {
        # Dashboard tab
        'iq_selected_idx': None,
        'iq_show_detail': False,
        'iq_detail_data': None,
        # Period summary tab
        'iq_period_preset': 'this_month',
        'iq_period_from': today.replace(day=1),
        'iq_period_to': today,
        # Period selection
        'iq_period_selected_idx': None,
        'iq_period_show_detail': False,
        'iq_period_detail_data': None,
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


# ============================================================================
# TAB 1: DASHBOARD
# ============================================================================

# ==================== Summary Cards ====================

def render_summary_cards():
    """Render summary metric cards in 2 rows: Quantity + Value"""
    metrics = data_loader.get_summary_metrics()
    
    # === Row 1: Quantity metrics (4 columns) ===
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
        total = metrics.get('TOTAL', {})
        st.metric(
            label="📦 Total Items",
            value=f"{total.get('count', 0):,} items",
            delta=f"{format_quantity(total.get('quantity', 0))} units",
            delta_color="off"
        )
    
    # === Row 2: Value metrics with expiry breakdown ===
    # Near expiry threshold selector
    threshold_col, spacer = st.columns([2, 8])
    with threshold_col:
        near_expiry_days = st.selectbox(
            "Near Expiry Threshold",
            options=[30, 60, 90, 180],
            index=2,  # default 90 days
            format_func=lambda x: f"⏱️ {x} days",
            key="iq_near_expiry_days",
            label_visibility="collapsed"
        )
    
    # Load expiry metrics
    expiry = data_loader.get_expiry_metrics(near_expiry_days=near_expiry_days)
    
    expired = expiry.get('expired', {})
    near_exp = expiry.get('near_expiry', {})
    total_value = expiry.get('total_value', 0)
    
    defective_value = metrics.get('DEFECTIVE', {}).get('value', 0)
    quarantine_value = metrics.get('QUARANTINE', {}).get('value', 0)
    good_value = metrics.get('GOOD', {}).get('value', 0)
    
    # Healthy good value = good value - expired - near expiry
    healthy_good_value = good_value - expired.get('value', 0) - near_exp.get('value', 0)
    
    # Value at Risk = Expired + Near Expiry + Defective + Quarantine
    at_risk_value = (expired.get('value', 0) + near_exp.get('value', 0) 
                     + defective_value + quarantine_value)
    
    vc1, vc2, vc3, vc4, vc5 = st.columns(5)
    
    with vc1:
        st.metric(
            label="💰 Total Inventory Value",
            value=format_currency(total_value),
            delta=f"{expiry.get('total_count', 0):,} items",
            delta_color="off"
        )
    
    with vc2:
        pct_healthy = (healthy_good_value / total_value * 100) if total_value > 0 else 0
        st.metric(
            label="📗 Healthy Good Value",
            value=format_currency(healthy_good_value),
            delta=f"{pct_healthy:.1f}% of total",
            delta_color="off"
        )
    
    with vc3:
        st.metric(
            label=f"🟡 Near Expiry (≤{near_expiry_days}d)",
            value=format_currency(near_exp.get('value', 0)),
            delta=f"{near_exp.get('count', 0):,} items",
            delta_color="off"
        )
    
    with vc4:
        st.metric(
            label="🔴 Expired",
            value=format_currency(expired.get('value', 0)),
            delta=f"{expired.get('count', 0):,} items",
            delta_color="inverse"
        )
    
    with vc5:
        st.metric(
            label="⚠️ Total Value at Risk",
            value=format_currency(at_risk_value),
            delta="Expired + Near Expiry + Defect + QC",
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
            placeholder="Name, PT code, Legacy code, Pkg size...",
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
    
    # Handle package_size - fill empty with '-'
    display_df['package_size_display'] = display_df['package_size'].fillna('-').replace('', '-')
    
    # Create editable dataframe with selection
    edited_df = st.data_editor(
        display_df[[
            'Select', 'category_display', 'product_name', 'package_size_display', 'pt_code', 'batch_number',
            'qty_display', 'warehouse_name', 'source_type', 'days_display', 'value_display'
        ]].rename(columns={
            'category_display': 'Category',
            'product_name': 'Product',
            'package_size_display': 'Pkg Size',
            'pt_code': 'PT Code',
            'batch_number': 'Batch',
            'qty_display': 'Quantity',
            'warehouse_name': 'Warehouse',
            'source_type': 'Source',
            'days_display': 'Age',
            'value_display': 'Value'
        }),
        width='stretch',
        hide_index=True,
        height=450,
        disabled=['Category', 'Product', 'Pkg Size', 'PT Code', 'Batch', 'Quantity', 'Warehouse', 'Source', 'Age', 'Value'],
        column_config={
            'Select': st.column_config.CheckboxColumn(
                '✓',
                help='Select row to view details',
                default=False,
                width='small'
            ),
            'Category': st.column_config.TextColumn('Category', width='medium'),
            'Product': st.column_config.TextColumn('Product', width='large'),
            'Pkg Size': st.column_config.TextColumn('Pkg Size', width='small'),
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
        st.markdown(f"**Package Size:** {safe_get(item, 'package_size', '-')}")
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


# ==================== Dashboard Export ====================

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


# ============================================================================
# TAB 2: TỔNG HỢP TỒN KHO (Inventory Period Summary)
# ============================================================================

def _on_period_preset_change():
    """Callback when period preset changes - update from/to dates"""
    preset = st.session_state.get('iq_period_preset', 'this_month')
    if preset != 'custom':
        from_d, to_d = get_period_dates(preset)
        st.session_state['iq_period_from'] = from_d
        st.session_state['iq_period_to'] = to_d


def render_period_filters():
    """
    Render filters for period inventory summary.
    
    Returns:
        Tuple of (from_date, to_date, warehouse_id, product_search) or (None,...) if invalid
    """
    presets = InventoryQualityConstants.PERIOD_PRESETS
    
    col1, col2, col3, col4, col5 = st.columns([2, 1.5, 1.5, 2, 2])
    
    with col1:
        preset = st.selectbox(
            "Report Period",
            options=list(presets.keys()),
            format_func=lambda x: presets[x],
            key="iq_period_preset",
            on_change=_on_period_preset_change
        )
    
    is_custom = (preset == 'custom')
    
    with col2:
        from_date = st.date_input(
            "From Date",
            key="iq_period_from",
            disabled=not is_custom,
        )
    
    with col3:
        to_date = st.date_input(
            "To Date",
            key="iq_period_to",
            disabled=not is_custom,
        )
    
    with col4:
        warehouses = data_loader.get_warehouses()
        warehouse_options = [{'id': None, 'name': 'All Warehouses'}] + warehouses
        
        selected_warehouse = st.selectbox(
            "Warehouse",
            options=warehouse_options,
            format_func=lambda x: x.get('name', 'Unknown'),
            key="iq_period_warehouse"
        )
        warehouse_id = selected_warehouse.get('id') if selected_warehouse else None
    
    with col5:
        product_search = st.text_input(
            "Search Product",
            placeholder="Name, PT code, Legacy code, Pkg size...",
            key="iq_period_product_search"
        )
    
    # Validate dates
    if from_date > to_date:
        st.error("⚠️ 'From Date' must be before or equal to 'To Date'")
        return None, None, None, None
    
    return from_date, to_date, warehouse_id, product_search or None


def render_period_metrics(df: pd.DataFrame):
    """Render summary metrics for period report"""
    if df.empty:
        return
    
    total_opening = df['opening_qty'].sum()
    total_in = df['stock_in_qty'].sum()
    total_out = df['stock_out_qty'].sum()
    total_closing = df['closing_qty'].sum()
    
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        st.metric("📦 Products", f"{len(df):,}")
    with col2:
        st.metric("📊 Opening", format_quantity(total_opening))
    with col3:
        st.metric("📥 Stock In", format_quantity(total_in))
    with col4:
        st.metric("📤 Stock Out", format_quantity(total_out))
    with col5:
        net = total_in - total_out
        st.metric(
            "📊 Closing",
            format_quantity(total_closing),
            delta=f"Net: {'+' if net >= 0 else ''}{format_quantity(net)}",
            delta_color="normal"
        )


def render_period_table(df: pd.DataFrame, from_date=None, to_date=None, warehouse_id=None):
    """Render period summary data table with single-row checkbox selection"""
    if df.empty:
        st.info("📭 No inventory movements found for the selected period and filters.")
        return
    
    st.markdown(f"**Found {len(df):,} products** | 💡 Tick checkbox to select a product and view transaction details")
    
    # Prepare display dataframe - reset index for consistent positioning
    display_df = df.reset_index(drop=True).copy()
    
    # Set Select column based on session state (single selection)
    display_df['Select'] = False
    if (st.session_state.iq_period_selected_idx is not None 
            and st.session_state.iq_period_selected_idx < len(display_df)):
        display_df.loc[st.session_state.iq_period_selected_idx, 'Select'] = True
    
    # Format product name with package size
    display_df['product_name_display'] = display_df.apply(
        lambda r: f"{r['product_name']} ({r['package_size']})" 
        if pd.notna(r.get('package_size')) and str(r.get('package_size', '')).strip() 
        else r['product_name'], axis=1
    )
    
    # Format quantity columns for display - show blank for zero values
    for col in ['opening_qty', 'stock_in_qty', 'stock_out_qty', 'closing_qty']:
        display_df[f'{col}_display'] = display_df[col].apply(format_report_qty)
    
    # Create editable dataframe with selection
    edited_df = st.data_editor(
        display_df[[
            'Select', 'product_code', 'legacy_code', 'product_name_display', 'uom',
            'opening_qty_display', 'stock_in_qty_display', 'stock_out_qty_display', 'closing_qty_display'
        ]].rename(columns={
            'product_code': 'Product Code',
            'legacy_code': 'Legacy Code',
            'product_name_display': 'Product Name',
            'uom': 'UOM',
            'opening_qty_display': 'Opening',
            'stock_in_qty_display': 'Stock In',
            'stock_out_qty_display': 'Stock Out',
            'closing_qty_display': 'Closing',
        }),
        width='stretch',
        hide_index=True,
        height=min(500, 35 * len(display_df) + 38),
        disabled=['Product Code', 'Legacy Code', 'Product Name', 'UOM',
                  'Opening', 'Stock In', 'Stock Out', 'Closing'],
        column_config={
            'Select': st.column_config.CheckboxColumn(
                '✓',
                help='Select product to view transaction details',
                default=False,
                width='small'
            ),
            'Product Code': st.column_config.TextColumn('Product Code', width='medium'),
            'Legacy Code': st.column_config.TextColumn('Legacy Code', width='medium'),
            'Product Name': st.column_config.TextColumn('Product Name', width='large'),
            'UOM': st.column_config.TextColumn('UOM', width='small'),
            'Opening': st.column_config.TextColumn('Opening', width='medium'),
            'Stock In': st.column_config.TextColumn('Stock In', width='medium'),
            'Stock Out': st.column_config.TextColumn('Stock Out', width='medium'),
            'Closing': st.column_config.TextColumn('Closing', width='medium'),
        },
        key="iq_period_table_editor"
    )
    
    # Handle single selection - find newly selected row
    selected_indices = edited_df[edited_df['Select'] == True].index.tolist()
    
    if selected_indices:
        # If multiple selected (user clicked new one), keep only the newest
        if len(selected_indices) > 1:
            new_selection = [idx for idx in selected_indices 
                            if idx != st.session_state.iq_period_selected_idx]
            if new_selection:
                st.session_state.iq_period_selected_idx = new_selection[0]
                st.rerun()
        else:
            st.session_state.iq_period_selected_idx = selected_indices[0]
    else:
        st.session_state.iq_period_selected_idx = None
    
    # Action buttons - only show when row is selected
    if (st.session_state.iq_period_selected_idx is not None 
            and st.session_state.iq_period_selected_idx < len(display_df)):
        selected_row = display_df.iloc[st.session_state.iq_period_selected_idx]
        product_name = selected_row.get('product_name', 'Unknown')
        product_code = selected_row.get('product_code', '')
        opening = format_report_qty(selected_row.get('opening_qty', 0))
        closing = format_report_qty(selected_row.get('closing_qty', 0))
        
        st.markdown("---")
        st.markdown(
            f"**Selected:** `{product_code}` | {product_name} "
            f"| Opening: **{opening}** → Closing: **{closing}**"
        )
        
        col1, col2, col3 = st.columns([1, 1, 3])
        
        with col1:
            if st.button("🔍 View Details", type="primary", use_container_width=True, 
                         key="btn_period_detail"):
                st.session_state['iq_period_detail_data'] = {
                    'product_id': int(selected_row['product_id']),
                    'product_code': product_code,
                    'legacy_code': selected_row.get('legacy_code', ''),
                    'product_name': product_name,
                    'package_size': selected_row.get('package_size', ''),
                    'brand': selected_row.get('brand', ''),
                    'uom': selected_row.get('uom', ''),
                    'opening_qty': float(selected_row.get('opening_qty', 0)),
                    'stock_in_qty': float(selected_row.get('stock_in_qty', 0)),
                    'stock_out_qty': float(selected_row.get('stock_out_qty', 0)),
                    'closing_qty': float(selected_row.get('closing_qty', 0)),
                    'from_date': from_date,
                    'to_date': to_date,
                    'warehouse_id': warehouse_id,
                }
                st.session_state['iq_period_show_detail'] = True
                st.rerun()
        
        with col2:
            if st.button("❌ Deselect", use_container_width=True, key="btn_period_deselect"):
                st.session_state['iq_period_selected_idx'] = None
                st.rerun()
    else:
        st.info("💡 Tick checkbox to select a product and view transaction details")


def _format_txn_type(raw_type: str) -> str:
    """Format inventory history transaction type for display"""
    if not raw_type:
        return '-'
    display_map = {
        'stockIn': 'Purchase',
        'stockInOpeningBalance': 'Opening Balance',
        'stockInProduction': 'Production Receipt',
        'stockInProductionReturn': 'Production Return',
        'stockInWarehouseTransfer': 'WH Transfer In',
        'stockOutDelivery': 'Delivery',
        'stockOutProduction': 'Material Issue',
        'stockOutWarehouseTransfer': 'WH Transfer Out',
        'stockOutInternalUse': 'Internal Use',
    }
    if raw_type in display_map:
        return display_map[raw_type]
    # Fallback: camelCase to Title Case with spaces
    display = raw_type
    if display.startswith('stockIn'):
        display = display[7:]
    elif display.startswith('stockOut'):
        display = display[8:]
    if display:
        display = re.sub(r'([A-Z])', r' \1', display).strip().title()
    return display or raw_type


def _render_reference_detail(detail: dict, lines: pd.DataFrame = None):
    """Render reference document detail based on doc_type"""
    doc_type = detail.get('doc_type', 'Unknown')
    
    # Note for unsupported types
    if detail.get('_note'):
        st.info(detail['_note'])
        return
    
    renderer_map = {
        'Purchase': _render_ref_purchase,
        'Production Receipt': _render_ref_production_receipt,
        'Material Return': _render_ref_material_return,
        'Material Issue': _render_ref_material_issue,
        'Delivery': _render_ref_delivery,
        'Warehouse Transfer': _render_ref_warehouse_transfer,
        'Internal Use': _render_ref_internal_use,
        'Opening Balance': _render_ref_opening_balance,
    }
    
    renderer = renderer_map.get(doc_type)
    if renderer:
        with st.expander(f"📄 {doc_type} Detail", expanded=True):
            renderer(detail)
            # Show line items if available
            if lines is not None and not lines.empty:
                st.markdown("---")
                st.markdown(f"**📋 Document Lines** ({len(lines)} items)")
                st.dataframe(
                    lines,
                    width='stretch',
                    hide_index=True,
                    height=min(300, 35 * len(lines) + 38),
                )
    else:
        st.info(f"Detail view not available for type: {doc_type}")


def _render_ref_purchase(d: dict):
    """Render Purchase (PO → Arrival → Stock In) detail"""
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("**📋 Purchase Order**")
        st.markdown(f"PO Number: `{d.get('po_number', '-')}`")
        st.markdown(f"PO Date: {format_date(d.get('po_date'))}")
        st.markdown(f"PO Type: {d.get('po_type', '-')}")
        if d.get('external_ref_number'):
            st.markdown(f"External Ref: `{d['external_ref_number']}`")
    with col2:
        st.markdown("**📦 Arrival**")
        st.markdown(f"Arrival Note: `{d.get('arrival_note_number', '-')}`")
        st.markdown(f"Arrival Date: {format_date(d.get('arrival_date'))}")
        st.markdown(f"Status: {d.get('arrival_status', '-')}")
        st.markdown(f"Ship Method: {d.get('ship_method', '-')}")
    with col3:
        st.markdown("**💰 Cost & Vendor**")
        st.markdown(f"Vendor: {d.get('vendor_name', '-')}")
        landed = d.get('landed_cost')
        cur = d.get('landed_cost_currency', '')
        st.markdown(f"Landed Cost: {format_currency(landed) if landed else '-'} {cur}")
        st.markdown(f"Arrival Qty: {format_quantity(d.get('arrival_quantity'))}")
        st.markdown(f"Stocked In: {format_quantity(d.get('stocked_in_qty'))}")


def _render_ref_production_receipt(d: dict):
    """Render Production Receipt detail"""
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("**📋 Receipt**")
        st.markdown(f"Receipt No: `{d.get('receipt_no', '-')}`")
        st.markdown(f"Receipt Date: {format_date(d.get('receipt_date'))}")
        st.markdown(f"QC Status: {d.get('quality_status', '-')}")
        if d.get('defect_type'):
            st.markdown(f"Defect Type: {d['defect_type']}")
    with col2:
        st.markdown("**📦 Product**")
        st.markdown(f"Batch: `{d.get('batch_no', '-')}`")
        st.markdown(f"Quantity: {format_quantity(d.get('quantity'))} {d.get('uom', '')}")
        st.markdown(f"Expiry: {format_date(d.get('expired_date'))}")
        st.markdown(f"Warehouse: {d.get('warehouse_name', '-')}")
    with col3:
        st.markdown("**🏭 Manufacturing Order**")
        st.markdown(f"MO: `{d.get('mo_number', '-')}`")
        st.markdown(f"MO Status: {d.get('mo_status', '-')}")
        st.markdown(f"Planned Qty: {format_quantity(d.get('planned_qty'))}")
        st.markdown(f"Produced Qty: {format_quantity(d.get('produced_qty'))}")
        if d.get('bom_name'):
            st.markdown(f"BOM: {d['bom_name']}")
    if d.get('notes'):
        st.markdown(f"**Notes:** {d['notes']}")


def _render_ref_material_return(d: dict):
    """Render Material Return detail"""
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("**📋 Return**")
        st.markdown(f"Return No: `{d.get('return_no', '-')}`")
        st.markdown(f"Return Date: {format_date(d.get('return_date'))}")
        st.markdown(f"Status: {d.get('status', '-')}")
        st.markdown(f"Reason: {d.get('reason', '-')}")
    with col2:
        st.markdown("**📦 Material**")
        st.markdown(f"Material: {d.get('material_name', '-')}")
        st.markdown(f"Batch: `{d.get('batch_no', '-')}`")
        st.markdown(f"Quantity: {format_quantity(d.get('quantity'))} {d.get('uom', '')}")
        st.markdown(f"Condition: {d.get('condition', '-')}")
    with col3:
        st.markdown("**🔗 References**")
        st.markdown(f"MO: `{d.get('mo_number', '-')}`")
        st.markdown(f"Original Issue: `{d.get('original_issue_no', '-')}`")
        st.markdown(f"Warehouse: {d.get('warehouse_name', '-')}")
        if d.get('returned_by_name') and d['returned_by_name'].strip():
            st.markdown(f"Returned By: {d['returned_by_name']}")


def _render_ref_material_issue(d: dict):
    """Render Material Issue detail"""
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("**📋 Issue**")
        st.markdown(f"Issue No: `{d.get('issue_no', '-')}`")
        st.markdown(f"Issue Date: {format_date(d.get('issue_date'))}")
        st.markdown(f"Status: {d.get('status', '-')}")
    with col2:
        st.markdown("**📦 Material**")
        st.markdown(f"Material: {d.get('material_name', '-')}")
        st.markdown(f"PT Code: `{d.get('pt_code', '-')}`")
        st.markdown(f"Batch: `{d.get('batch_no', '-')}`")
        st.markdown(f"Quantity: {format_quantity(d.get('quantity'))} {d.get('uom', '')}")
        if d.get('is_alternative'):
            st.markdown(f"⚠️ Alternative for: {d.get('original_material_name', '-')}")
    with col3:
        st.markdown("**🏭 Manufacturing**")
        st.markdown(f"MO: `{d.get('mo_number', '-')}`")
        st.markdown(f"MO Status: {d.get('mo_status', '-')}")
        st.markdown(f"Warehouse: {d.get('warehouse_name', '-')}")
        if d.get('issued_by_name') and d['issued_by_name'].strip():
            st.markdown(f"Issued By: {d['issued_by_name']}")
    if d.get('notes'):
        st.markdown(f"**Notes:** {d['notes']}")


def _render_ref_delivery(d: dict):
    """Render Delivery detail"""
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("**📋 Delivery Note**")
        st.markdown(f"DN Number: `{d.get('dn_number', '-')}`")
        st.markdown(f"Status: {d.get('status', '-')}")
        st.markdown(f"Shipment: {d.get('shipment_status', '-')}")
    with col2:
        st.markdown("**📅 Dates**")
        st.markdown(f"Dispatch: {format_date(d.get('dispatch_date'))}")
        st.markdown(f"Delivered: {format_date(d.get('date_delivered'))}")
        st.markdown(f"Method: {d.get('delivery_method', '-')}")
    with col3:
        st.markdown("**🏢 Parties**")
        st.markdown(f"Buyer: {d.get('buyer_name', '-')}")
        st.markdown(f"Seller: {d.get('seller_name', '-')}")
        if d.get('carrier_name'):
            st.markdown(f"Carrier: {d['carrier_name']}")
        st.markdown(f"Warehouse: {d.get('warehouse_name', '-')}")


def _render_ref_warehouse_transfer(d: dict):
    """Render Warehouse Transfer detail"""
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**📋 Transfer**")
        st.markdown(f"Transfer No: `{d.get('warehouse_transfer_number', '-')}`")
        st.markdown(f"Date: {format_date(d.get('created_date'))}")
        finished = '✅ Yes' if d.get('is_finished') else '⏳ No'
        st.markdown(f"Finished: {finished}")
    with col2:
        st.markdown("**🏢 Info**")
        st.markdown(f"Company: {d.get('company_name', '-')}")
        st.markdown(f"Warehouse: {d.get('warehouse_name', '-')}")
        st.markdown(f"Created By: {d.get('created_by_name', '-')}")


def _render_ref_internal_use(d: dict):
    """Render Internal Use detail"""
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**📋 Internal Use**")
        st.markdown(f"Number: `{d.get('internal_use_number', '-')}`")
        st.markdown(f"Date: {format_date(d.get('created_date'))}")
    with col2:
        st.markdown("**🏢 Info**")
        st.markdown(f"Company: {d.get('company_name', '-')}")
        st.markdown(f"Requester: {d.get('requester_name', '-')}")
        st.markdown(f"Warehouse: {d.get('warehouse_name', '-')}")


def _render_ref_opening_balance(d: dict):
    """Render Opening Balance detail"""
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Date:** {format_date(d.get('created_date'))}")
        st.markdown(f"**Quantity:** {format_quantity(d.get('quantity'))} {d.get('uom', '')}")
    with col2:
        st.markdown(f"**Batch:** `{d.get('batch_no', '-')}`")
        st.markdown(f"**Warehouse:** {d.get('warehouse_name', '-')}")


@st.dialog("📋 Product Period Detail", width="large")
def show_period_detail_dialog(detail_data: dict):
    """Show detailed stock in/out transactions for selected product in period"""
    product_name = detail_data.get('product_name', 'Unknown')
    product_code = detail_data.get('product_code', '')
    legacy_code = detail_data.get('legacy_code', '')
    uom = detail_data.get('uom', '')
    pkg = detail_data.get('package_size', '')
    from_date = detail_data.get('from_date')
    to_date = detail_data.get('to_date')
    
    # Header
    st.markdown(f"### 📦 {product_name}")
    code_parts = [f"`{product_code}`"]
    if legacy_code:
        code_parts.append(f"Legacy: `{legacy_code}`")
    if pkg:
        code_parts.append(f"Pkg: {pkg}")
    code_parts.append(f"UOM: {uom}")
    st.markdown(" | ".join(code_parts))
    
    if from_date and to_date:
        st.markdown(
            f"**Period:** {from_date.strftime('%d/%m/%Y')} → {to_date.strftime('%d/%m/%Y')}"
        )
    st.markdown("---")
    
    # Summary metrics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("📊 Opening", format_quantity(detail_data.get('opening_qty', 0)))
    with col2:
        st.metric("📥 Stock In", format_quantity(detail_data.get('stock_in_qty', 0)))
    with col3:
        st.metric("📤 Stock Out", format_quantity(detail_data.get('stock_out_qty', 0)))
    with col4:
        st.metric("📊 Closing", format_quantity(detail_data.get('closing_qty', 0)))
    
    st.markdown("---")
    
    # Load detailed transactions
    st.markdown("#### 📝 Transaction Details")
    
    with st.spinner("Loading transactions..."):
        txn_df = data_loader.get_product_period_detail(
            product_id=detail_data['product_id'],
            from_date=from_date,
            to_date=to_date,
            warehouse_id=detail_data.get('warehouse_id'),
        )
    
    if txn_df.empty:
        st.info("No transactions found for this product in the selected period.")
    else:
        # Separate Stock In and Stock Out for tabbed view
        tab_all, tab_in, tab_out = st.tabs([
            f"📋 All ({len(txn_df)})",
            f"📥 Stock In ({len(txn_df[txn_df['direction'] == 'Stock In'])})",
            f"📤 Stock Out ({len(txn_df[txn_df['direction'] == 'Stock Out'])})"
        ])
        
        def _render_txn_table(data: pd.DataFrame):
            """Render a transaction dataframe"""
            if data.empty:
                st.info("No transactions.")
                return
            
            disp = data.copy()
            
            # Format date
            disp['transaction_date'] = pd.to_datetime(
                disp['transaction_date']
            ).dt.strftime('%d/%m/%Y %H:%M')
            
            # Format direction with icon
            disp['direction'] = disp['direction'].apply(
                lambda x: '📥 In' if x == 'Stock In' else '📤 Out'
            )
            
            # Clean up type display
            disp['transaction_type'] = disp['transaction_type'].apply(_format_txn_type)
            
            # Format quantity
            disp['quantity'] = disp['quantity'].apply(format_quantity)
            
            # Fill NaN for display
            for col in ['reference_no', 'related_order', 'batch_no', 'created_by_name']:
                if col in disp.columns:
                    disp[col] = disp[col].fillna('-')
            
            # Select & rename columns
            col_map = {
                'transaction_date': 'Date',
                'direction': 'Direction',
                'transaction_type': 'Type',
                'reference_no': 'Reference',
                'related_order': 'MO/Order',
                'batch_no': 'Batch',
                'quantity': 'Quantity',
                'uom': 'UOM',
                'warehouse_name': 'Warehouse',
                'created_by_name': 'Created By',
            }
            
            existing = [c for c in col_map if c in disp.columns]
            disp = disp[existing].rename(columns=col_map)
            
            st.dataframe(
                disp,
                width='stretch',
                hide_index=True,
                height=min(400, 35 * len(disp) + 38),
                column_config={
                    'Date': st.column_config.TextColumn('Date', width='medium'),
                    'Direction': st.column_config.TextColumn('Direction', width='small'),
                    'Type': st.column_config.TextColumn('Type', width='medium'),
                    'Reference': st.column_config.TextColumn('Reference', width='medium'),
                    'MO/Order': st.column_config.TextColumn('MO/Order', width='medium'),
                    'Batch': st.column_config.TextColumn('Batch', width='medium'),
                    'Quantity': st.column_config.TextColumn('Quantity', width='small'),
                    'UOM': st.column_config.TextColumn('UOM', width='small'),
                    'Warehouse': st.column_config.TextColumn('Warehouse', width='medium'),
                    'Created By': st.column_config.TextColumn('Created By', width='medium'),
                }
            )
        
        with tab_all:
            _render_txn_table(txn_df)
        
        with tab_in:
            _render_txn_table(txn_df[txn_df['direction'] == 'Stock In'].reset_index(drop=True))
        
        with tab_out:
            _render_txn_table(txn_df[txn_df['direction'] == 'Stock Out'].reset_index(drop=True))
        
        # ---- Reference Detail Section ----
        st.markdown("---")
        st.markdown("#### 🔎 Reference Document Detail")
        st.caption("Select a transaction to view its source document")
        
        # Build selectbox options from txn_df
        txn_labels = ["-- Select a transaction --"]
        for idx, row in txn_df.iterrows():
            ref = row.get('reference_no', '-') or '-'
            txn_type_display = _format_txn_type(row.get('transaction_type', ''))
            txn_date = pd.to_datetime(row['transaction_date']).strftime('%d/%m/%Y') if pd.notna(row.get('transaction_date')) else ''
            direction = '📥' if row.get('direction') == 'Stock In' else '📤'
            txn_labels.append(f"{direction} {txn_date} | {txn_type_display} | {ref}")
        
        selected_idx = st.selectbox(
            "Transaction",
            options=range(len(txn_labels)),
            format_func=lambda i: txn_labels[i],
            key="iq_ref_detail_select",
            label_visibility="collapsed"
        )
        
        if selected_idx > 0:
            row_data = txn_df.iloc[selected_idx - 1]
            ih_id = int(row_data['id'])
            txn_type = row_data.get('transaction_type', '')
            
            with st.spinner("Loading reference detail..."):
                ref_detail = data_loader.get_reference_detail(ih_id, txn_type)
                ref_lines = data_loader.get_reference_lines(ih_id, txn_type)
            
            if ref_detail:
                _render_reference_detail(ref_detail, ref_lines)
            else:
                st.info("No additional detail available for this transaction.")
    
    # Close button
    st.markdown("---")
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        if st.button("✖️ Close", use_container_width=True, key="btn_close_period_detail"):
            st.session_state['iq_period_show_detail'] = False
            st.session_state['iq_period_detail_data'] = None
            st.rerun()


def render_period_export(df: pd.DataFrame, from_date, to_date):
    """Render export button for period summary"""
    if df.empty:
        return
    
    # Prepare export DataFrame with proper column names
    export_df = df[[
        'product_code', 'legacy_code', 'product_name', 'uom',
        'opening_qty', 'stock_in_qty', 'stock_out_qty', 'closing_qty'
    ]].copy()
    
    # Append package_size to product name
    export_df['product_name'] = df.apply(
        lambda r: f"{r['product_name']} ({r['package_size']})" 
        if pd.notna(r.get('package_size')) and str(r.get('package_size', '')).strip() 
        else r['product_name'], axis=1
    )
    
    export_df.columns = [
        'Product Code', 'Legacy Code', 'Product Name', 'UOM',
        'Opening (Qty)', 'Stock In (Qty)', 'Stock Out (Qty)', 'Closing (Qty)'
    ]
    
    col1, col2 = st.columns([1, 4])
    with col1:
        try:
            excel_data = create_period_summary_excel(export_df, from_date, to_date)
            
            from_str = from_date.strftime('%Y%m%d')
            to_str = to_date.strftime('%Y%m%d')
            filename = f"inventory_summary_{from_str}_{to_str}.xlsx"
            
            st.download_button(
                label="📥 Export Excel",
                data=excel_data,
                file_name=filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key="download_period_excel"
            )
        except Exception as e:
            st.error(f"Export failed: {str(e)}")
            logger.error(f"Period export error: {e}", exc_info=True)


def render_period_summary():
    """Main renderer for the Period Summary tab"""
    st.markdown("### 📋 Inventory Period Summary")
    st.caption("Opening balance / Stock In / Stock Out / Closing balance by product")
    st.markdown("---")
    
    # Filters
    result = render_period_filters()
    if result[0] is None:
        return
    
    from_date, to_date, warehouse_id, product_search = result
    
    st.markdown("---")
    
    # Report title (centered)
    st.markdown(
        f"<h4 style='text-align:center; margin-bottom:2px;'>INVENTORY PERIOD SUMMARY</h4>"
        f"<p style='text-align:center; color:#666; margin-top:0;'>"
        f"From {from_date.strftime('%d/%m/%Y')} to {to_date.strftime('%d/%m/%Y')}</p>",
        unsafe_allow_html=True
    )
    
    # Load data
    with st.spinner("Loading inventory summary..."):
        df = data_loader.get_inventory_period_summary(
            from_date=from_date,
            to_date=to_date,
            warehouse_id=warehouse_id,
            product_search=product_search
        )
    
    # Metrics row
    render_period_metrics(df)
    st.markdown("---")
    
    # Data table with selection
    render_period_table(df, from_date=from_date, to_date=to_date, warehouse_id=warehouse_id)
    
    # Export
    if not df.empty:
        st.markdown("---")
        render_period_export(df, from_date, to_date)
    
    # Detail dialog
    if st.session_state.get('iq_period_show_detail') and st.session_state.get('iq_period_detail_data'):
        show_period_detail_dialog(st.session_state['iq_period_detail_data'])


# ============================================================================
# MAIN APPLICATION
# ============================================================================

def main():
    """Main application entry point"""
    try:
        render_header()
        st.markdown("---")
        
        # === Two tabs ===
        tab_dashboard, tab_period = st.tabs([
            "📊 Dashboard",
            "📋 Inventory Summary"
        ])
        
        # ---- Tab 1: Dashboard (existing functionality) ----
        with tab_dashboard:
            render_summary_cards()
            st.markdown("---")
            
            category, warehouse_id, product_search = render_filters()
            st.markdown("---")
            
            with st.spinner("Loading inventory data..."):
                df = data_loader.get_unified_inventory(
                    category=category if category != 'All' else None,
                    warehouse_id=warehouse_id,
                    product_search=product_search if product_search else None
                )
            
            render_data_table(df)
            
            if not df.empty:
                st.markdown("---")
                render_export_section(df, category, warehouse_id)
            
            if st.session_state.get('iq_show_detail') and st.session_state.get('iq_detail_data'):
                show_detail_dialog(st.session_state['iq_detail_data'])
        
        # ---- Tab 2: Tổng hợp tồn kho (new) ----
        with tab_period:
            render_period_summary()
    
    except Exception as e:
        st.error(f"An error occurred: {str(e)}")
        logger.error(f"Application error: {e}", exc_info=True)
        
        if st.button("🔄 Reload"):
            st.cache_data.clear()
            st.session_state['iq_selected_idx'] = None
            st.rerun()
    
    # Footer
    st.markdown("---")
    st.caption("Inventory Quality Dashboard v1.2")


if __name__ == "__main__":
    main()