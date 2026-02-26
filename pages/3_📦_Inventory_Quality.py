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
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, date, timedelta

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
        'iq_entity_filter': [],
        'iq_expiry_filter': 'All',
        'iq_brand_filter': [],
        'iq_age_filter': 'All',
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

def render_summary_cards(df: pd.DataFrame):
    """Render summary metric cards in 2 rows, computed from filtered DataFrame"""
    if df.empty:
        st.info("📭 No data to display metrics.")
        return
    
    # Compute category metrics from filtered df
    good_df = df[df['category'] == 'GOOD']
    quarantine_df = df[df['category'] == 'QUARANTINE']
    defective_df = df[df['category'] == 'DEFECTIVE']
    
    good = {
        'count': len(good_df),
        'quantity': good_df['quantity'].sum() if not good_df.empty else 0,
        'value': good_df['inventory_value_usd'].fillna(0).sum() if not good_df.empty else 0,
    }
    quarantine = {
        'count': len(quarantine_df),
        'quantity': quarantine_df['quantity'].sum() if not quarantine_df.empty else 0,
        'value': quarantine_df['inventory_value_usd'].fillna(0).sum() if not quarantine_df.empty else 0,
    }
    defective = {
        'count': len(defective_df),
        'quantity': defective_df['quantity'].sum() if not defective_df.empty else 0,
        'value': defective_df['inventory_value_usd'].fillna(0).sum() if not defective_df.empty else 0,
    }
    total_count = len(df)
    total_quantity = df['quantity'].sum()
    total_value = df['inventory_value_usd'].fillna(0).sum()
    
    # === Row 1: Quantity metrics (4 columns) ===
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(
            label="📗 Good Stock",
            value=f"{good['count']:,} items",
            delta=f"{format_quantity(good['quantity'])} units"
        )
    
    with col2:
        st.metric(
            label="📙 Quarantine (Pending QC)",
            value=f"{quarantine['count']:,} items",
            delta=f"{format_quantity(quarantine['quantity'])} units",
            delta_color="off"
        )
    
    with col3:
        st.metric(
            label="📕 Defective",
            value=f"{defective['count']:,} items",
            delta=f"{format_quantity(defective['quantity'])} units",
            delta_color="inverse"
        )
    
    with col4:
        st.metric(
            label="📦 Total Items",
            value=f"{total_count:,} items",
            delta=f"{format_quantity(total_quantity)} units",
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
    
    # Compute expiry metrics from filtered GOOD df
    today = get_vietnam_today()
    near_expiry_cutoff = today + timedelta(days=near_expiry_days)
    
    if not good_df.empty and 'expiry_date' in good_df.columns:
        expiry_dates = pd.to_datetime(good_df['expiry_date'], errors='coerce')
        has_expiry = expiry_dates.notna()
        
        expired_mask = has_expiry & (expiry_dates.dt.date < today)
        near_mask = has_expiry & (expiry_dates.dt.date >= today) & (expiry_dates.dt.date <= near_expiry_cutoff)
        
        expired_count = expired_mask.sum()
        expired_value = good_df.loc[expired_mask, 'inventory_value_usd'].fillna(0).sum()
        near_count = near_mask.sum()
        near_value = good_df.loc[near_mask, 'inventory_value_usd'].fillna(0).sum()
    else:
        expired_count = expired_value = near_count = near_value = 0
    
    # Healthy good value = good value - expired - near expiry
    healthy_good_value = good['value'] - expired_value - near_value
    
    # Value at Risk = Expired + Near Expiry + Defective + Quarantine
    at_risk_value = expired_value + near_value + defective['value'] + quarantine['value']
    
    vc1, vc2, vc3, vc4, vc5 = st.columns(5)
    
    with vc1:
        st.metric(
            label="💰 Total Inventory Value",
            value=format_currency(total_value),
            delta=f"{total_count:,} items",
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
            value=format_currency(near_value),
            delta=f"{near_count:,} items",
            delta_color="off"
        )
    
    with vc4:
        st.metric(
            label="🔴 Expired",
            value=format_currency(expired_value),
            delta=f"{expired_count:,} items",
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
    """Render filter controls including owning entity and expiry status"""
    col1, col2, col3, col4, col5 = st.columns([1.5, 2, 2, 2, 1.5])
    
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
        entities = data_loader.get_owning_entities()
        entity_options = {e['id']: e['name'] for e in entities}
        
        selected_entity_ids = st.multiselect(
            "Owning Entity",
            options=list(entity_options.keys()),
            format_func=lambda x: entity_options.get(x, 'Unknown'),
            placeholder="All Entities",
            key="iq_entity_filter"
        )
        entity_ids = tuple(selected_entity_ids) if selected_entity_ids else None
    
    with col4:
        expiry_options = ['All', 'Expired', 'Near Expiry', 'OK', 'No Expiry']
        expiry_display = {
            'All': '📅 All Expiry Status',
            'Expired': '🔴 Expired',
            'Near Expiry': '🟡 Expiring Soon (≤90d)',
            'OK': '🟢 OK (>90d)',
            'No Expiry': '⚪ No Expiry Date',
        }
        
        selected_expiry = st.selectbox(
            "Expiry Status",
            options=expiry_options,
            format_func=lambda x: expiry_display.get(x, x),
            key="iq_expiry_filter"
        )
    
    with col5:
        st.write("")  # Spacer
        st.write("")
        if st.button("🔄 Clear Filters", use_container_width=True):
            st.session_state['iq_category_filter'] = 'All'
            st.session_state['iq_warehouse_select'] = {'id': None, 'name': 'All Warehouses'}
            st.session_state['iq_entity_filter'] = []
            st.session_state['iq_expiry_filter'] = 'All'
            st.session_state['iq_brand_filter'] = []
            st.session_state['iq_age_filter'] = 'All'
            st.session_state['iq_product_search'] = ''
            st.session_state['iq_selected_idx'] = None
            st.rerun()
    
    # Row 2: Brand, Age, Search
    col_brand, col_age, col_search = st.columns([2.5, 2, 4.5])
    
    with col_brand:
        brands = data_loader.get_brands()
        brand_options = {b['name']: b['name'] for b in brands}
        
        selected_brands = st.multiselect(
            "Brand",
            options=list(brand_options.keys()),
            placeholder="All Brands",
            key="iq_brand_filter"
        )
    
    with col_age:
        age_options = ['All', '≥30 days', '≥60 days', '≥90 days', '≥180 days', '≥365 days']
        age_display = {
            'All': '⏳ All Ages',
            '≥30 days': '🟡 ≥ 30 days',
            '≥60 days': '🟠 ≥ 60 days',
            '≥90 days': '🔶 ≥ 90 days',
            '≥180 days': '🔴 ≥ 180 days',
            '≥365 days': '⛔ ≥ 1 year',
        }
        
        selected_age = st.selectbox(
            "Warehouse Age",
            options=age_options,
            format_func=lambda x: age_display.get(x, x),
            key="iq_age_filter"
        )
    
    with col_search:
        product_search = st.text_input(
            "Search Product",
            placeholder="Name, PT code, Legacy code, Pkg size...",
            key="iq_product_search"
        )
    
    return selected_category, warehouse_id, product_search, entity_ids, selected_expiry, selected_brands, selected_age


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
    
    # Keep numeric columns for proper sorting
    display_df['value_numeric'] = pd.to_numeric(display_df['inventory_value_usd'], errors='coerce').fillna(0)
    display_df['days_numeric'] = pd.to_numeric(display_df['days_in_warehouse'], errors='coerce').fillna(0).astype(int)
    
    # Handle package_size - fill empty with '-'
    display_df['package_size_display'] = display_df['package_size'].fillna('-').replace('', '-')
    
    # Handle owning_company_name - fill empty
    if 'owning_company_name' in display_df.columns:
        display_df['entity_display'] = display_df['owning_company_name'].fillna('-')
    else:
        display_df['entity_display'] = '-'
    
    # Format expiry date for display
    if 'expiry_date' in display_df.columns:
        display_df['expiry_display'] = pd.to_datetime(
            display_df['expiry_date'], errors='coerce'
        ).dt.strftime('%d/%m/%Y').fillna('-')
    else:
        display_df['expiry_display'] = '-'
    
    # Create editable dataframe with selection
    edited_df = st.data_editor(
        display_df[[
            'Select', 'category_display', 'product_name', 'package_size_display', 'pt_code', 'batch_number',
            'expiry_display', 'qty_display', 'warehouse_name', 'entity_display', 'source_type', 'days_numeric', 'value_numeric'
        ]].rename(columns={
            'category_display': 'Category',
            'product_name': 'Product',
            'package_size_display': 'Pkg Size',
            'pt_code': 'PT Code',
            'batch_number': 'Batch',
            'expiry_display': 'Expiry',
            'qty_display': 'Quantity',
            'warehouse_name': 'Warehouse',
            'entity_display': 'Entity',
            'source_type': 'Source',
            'days_numeric': 'Age',
            'value_numeric': 'Value'
        }),
        width='stretch',
        hide_index=True,
        height=450,
        disabled=['Category', 'Product', 'Pkg Size', 'PT Code', 'Batch', 'Expiry', 'Quantity', 'Warehouse', 'Entity', 'Source', 'Age', 'Value'],
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
            'Expiry': st.column_config.TextColumn('Expiry', width='medium'),
            'Quantity': st.column_config.TextColumn('Qty', width='small'),
            'Warehouse': st.column_config.TextColumn('Warehouse', width='medium'),
            'Entity': st.column_config.TextColumn('Entity', width='medium'),
            'Source': st.column_config.TextColumn('Source', width='medium'),
            'Age': st.column_config.NumberColumn('Age', format='%d days', width='small'),
            'Value': st.column_config.NumberColumn('Value', format='$ %.2f', width='small')
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
        st.markdown(f"**Owning Entity:** {safe_get(item, 'owning_company_name', '-')}")
    
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

def render_export_section(df: pd.DataFrame, category: str, warehouse_id: int, entity_ids: tuple = None):
    """Render export to Excel section"""
    col1, col2 = st.columns([1, 4])
    
    with col1:
        if st.button("📥 Export to Excel", use_container_width=True, key="btn_export"):
            try:
                export_df = data_loader.get_export_data(
                    category=category if category != 'All' else None,
                    warehouse_id=warehouse_id,
                    entity_ids=entity_ids
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
# TAB 3: ANALYTICS - Inventory Quality Analysis
# ============================================================================

# Color palette
_COLORS = {
    'primary': '#4472C4',
    'secondary': '#ED7D31',
    'accent': '#A5A5A5',
    'good': '#28a745',
    'warning': '#ffc107',
    'danger': '#dc3545',
    'info': '#17a2b8',
}

_AGING_COLORS = {
    '0-30 days': '#28a745',
    '31-60 days': '#7bc67e',
    '61-90 days': '#ffc107',
    '91-180 days': '#fd7e14',
    '181-365 days': '#dc3545',
    'Over 1 year': '#8b0000',
}

_EXPIRY_COLORS = {
    'Expired': '#dc3545',
    'Expiring Soon (≤30d)': '#fd7e14',
    'Expiring (31-90d)': '#ffc107',
    'Good (91-180d)': '#7bc67e',
    'Fresh (>180d)': '#28a745',
    'No Expiry': '#a5a5a5',
}

_CATEGORY_COLORS = {
    'GOOD': '#28a745',
    'QUARANTINE': '#ffc107',
    'DEFECTIVE': '#dc3545',
}


def _plotly_layout_defaults(fig, height=400):
    """Apply consistent layout defaults to plotly figures"""
    fig.update_layout(
        height=height,
        margin=dict(l=20, r=20, t=40, b=20),
        font=dict(size=12),
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        legend=dict(
            orientation='h',
            yanchor='bottom',
            y=-0.25,
            xanchor='center',
            x=0.5,
            font=dict(size=10),
        ),
    )
    return fig


def render_analytics():
    """Main renderer for the Analytics tab"""
    st.markdown("### 📊 Inventory Quality Analytics")
    st.caption("Visual analysis of inventory by brand, entity, warehouse, aging, and expiry")
    st.markdown("---")
    
    # Load full data (no filters — analytics shows everything)
    with st.spinner("Loading analytics data..."):
        df = data_loader.get_unified_inventory()
    
    if df.empty:
        st.info("📭 No inventory data available for analysis.")
        return
    
    # Prep numeric columns
    df['value'] = pd.to_numeric(df.get('inventory_value_usd'), errors='coerce').fillna(0)
    df['days'] = pd.to_numeric(df.get('days_in_warehouse'), errors='coerce').fillna(0)
    df['qty'] = pd.to_numeric(df.get('quantity'), errors='coerce').fillna(0)
    df['brand'] = df['brand'].fillna('(No Brand)')
    df['owning_company_name'] = df.get('owning_company_name', pd.Series(dtype=str)).fillna('Unknown')
    df['warehouse_name'] = df['warehouse_name'].fillna('Unknown')
    
    # Assign aging bucket
    df['age_bucket'] = pd.cut(
        df['days'],
        bins=[-1, 30, 60, 90, 180, 365, float('inf')],
        labels=['0-30 days', '31-60 days', '61-90 days', '91-180 days', '181-365 days', 'Over 1 year']
    )
    
    # Assign expiry bucket
    today = get_vietnam_today()
    expiry_dates = pd.to_datetime(df.get('expiry_date'), errors='coerce')
    conditions = [
        expiry_dates.isna(),
        expiry_dates.dt.date < today,
        expiry_dates.dt.date <= today + timedelta(days=30),
        expiry_dates.dt.date <= today + timedelta(days=90),
        expiry_dates.dt.date <= today + timedelta(days=180),
        expiry_dates.dt.date > today + timedelta(days=180),
    ]
    choices = ['No Expiry', 'Expired', 'Expiring Soon (≤30d)', 'Expiring (31-90d)', 'Good (91-180d)', 'Fresh (>180d)']
    df['expiry_bucket'] = np.select(conditions, choices, default='No Expiry')
    
    # ============================================================
    # KPI SUMMARY ROW
    # ============================================================
    total_value = df['value'].sum()
    total_items = len(df)
    total_qty = df['qty'].sum()
    n_brands = df['brand'].nunique()
    n_entities = df['owning_company_name'].nunique()
    n_warehouses = df['warehouse_name'].nunique()
    
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("💰 Total Value", format_currency(total_value))
    k2.metric("📦 Items", f"{total_items:,}")
    k3.metric("📊 Quantity", format_quantity(total_qty))
    k4.metric("🏷️ Brands", f"{n_brands:,}")
    k5.metric("🏢 Entities", f"{n_entities:,}")
    k6.metric("🏭 Warehouses", f"{n_warehouses:,}")
    
    st.markdown("---")
    
    # ============================================================
    # ROW 1: Category + Expiry Status
    # ============================================================
    r1c1, r1c2 = st.columns(2)
    
    with r1c1:
        st.markdown("##### 📦 Inventory by Category")
        cat_df = df.groupby('category').agg(
            items=('category', 'size'),
            value=('value', 'sum'),
            qty=('qty', 'sum')
        ).reset_index()
        cat_df['category_label'] = cat_df['category'].map({
            'GOOD': '📗 Good', 'QUARANTINE': '📙 Quarantine', 'DEFECTIVE': '📕 Defective'
        })
        
        fig_cat = go.Figure()
        fig_cat.add_trace(go.Bar(
            y=cat_df['category_label'],
            x=cat_df['value'],
            orientation='h',
            marker_color=[_CATEGORY_COLORS.get(c, '#999') for c in cat_df['category']],
            text=[format_currency(v) for v in cat_df['value']],
            textposition='auto',
            hovertemplate='%{y}<br>Value: %{text}<br>Items: %{customdata[0]:,}<extra></extra>',
            customdata=cat_df[['items']].values,
        ))
        fig_cat = _plotly_layout_defaults(fig_cat, height=250)
        fig_cat.update_layout(
            xaxis_title='Value (USD)', yaxis_title='',
            showlegend=False,
        )
        st.plotly_chart(fig_cat, use_container_width=True)
    
    with r1c2:
        st.markdown("##### 📅 Expiry Status Breakdown")
        expiry_order = ['Expired', 'Expiring Soon (≤30d)', 'Expiring (31-90d)', 'Good (91-180d)', 'Fresh (>180d)', 'No Expiry']
        exp_df = df.groupby('expiry_bucket').agg(
            items=('expiry_bucket', 'size'),
            value=('value', 'sum')
        ).reindex(expiry_order).dropna(subset=['items']).reset_index()
        exp_df.columns = ['status', 'items', 'value']
        exp_df['items'] = exp_df['items'].astype(int)
        
        fig_exp = px.pie(
            exp_df, values='value', names='status',
            color='status',
            color_discrete_map=_EXPIRY_COLORS,
            hole=0.45,
        )
        fig_exp.update_traces(
            textinfo='percent+label',
            textposition='outside',
            hovertemplate='%{label}<br>Value: $%{value:,.2f}<br>%{percent}<extra></extra>',
        )
        fig_exp = _plotly_layout_defaults(fig_exp, height=350)
        fig_exp.update_layout(showlegend=False)
        st.plotly_chart(fig_exp, use_container_width=True)
    
    st.markdown("---")
    
    # ============================================================
    # ROW 2: Brand + Entity
    # ============================================================
    r2c1, r2c2 = st.columns(2)
    
    with r2c1:
        st.markdown("##### 🏷️ Top Brands by Value")
        brand_df = df.groupby('brand').agg(
            items=('brand', 'size'),
            value=('value', 'sum'),
        ).sort_values('value', ascending=False).reset_index()
        
        # Show top 15, group rest as 'Others'
        if len(brand_df) > 15:
            top = brand_df.head(15)
            others_val = brand_df.iloc[15:]['value'].sum()
            others_items = brand_df.iloc[15:]['items'].sum()
            others_row = pd.DataFrame([{'brand': f'Others ({len(brand_df) - 15})', 'items': others_items, 'value': others_val}])
            brand_df = pd.concat([top, others_row], ignore_index=True)
        else:
            brand_df = brand_df
        
        fig_brand = go.Figure()
        fig_brand.add_trace(go.Bar(
            y=brand_df['brand'],
            x=brand_df['value'],
            orientation='h',
            marker_color=_COLORS['primary'],
            text=[format_currency(v) for v in brand_df['value']],
            textposition='outside',
            hovertemplate='%{y}<br>Value: %{text}<br>Items: %{customdata[0]:,}<extra></extra>',
            customdata=brand_df[['items']].values,
        ))
        chart_height = max(350, len(brand_df) * 28 + 60)
        fig_brand = _plotly_layout_defaults(fig_brand, height=chart_height)
        fig_brand.update_layout(
            xaxis_title='Value (USD)', yaxis_title='',
            yaxis=dict(autorange='reversed'),
            showlegend=False,
        )
        st.plotly_chart(fig_brand, use_container_width=True)
    
    with r2c2:
        st.markdown("##### 🏢 Value by Owning Entity")
        entity_df = df.groupby('owning_company_name').agg(
            items=('owning_company_name', 'size'),
            value=('value', 'sum'),
        ).sort_values('value', ascending=False).reset_index()
        
        fig_entity = px.pie(
            entity_df, values='value', names='owning_company_name',
            hole=0.45,
            color_discrete_sequence=px.colors.qualitative.Set2,
        )
        fig_entity.update_traces(
            textinfo='percent+label',
            textposition='outside',
            hovertemplate='%{label}<br>Value: $%{value:,.2f}<br>%{percent}<extra></extra>',
        )
        fig_entity = _plotly_layout_defaults(fig_entity, height=max(350, len(entity_df) * 28 + 60))
        fig_entity.update_layout(showlegend=False)
        st.plotly_chart(fig_entity, use_container_width=True)
    
    st.markdown("---")
    
    # ============================================================
    # ROW 3: Warehouse
    # ============================================================
    st.markdown("##### 🏭 Inventory by Warehouse")
    
    wh_df = df.groupby('warehouse_name').agg(
        items=('warehouse_name', 'size'),
        value=('value', 'sum'),
        qty=('qty', 'sum'),
    ).sort_values('value', ascending=False).reset_index()
    
    # Stacked bar by category per warehouse
    wh_cat_df = df.groupby(['warehouse_name', 'category']).agg(
        value=('value', 'sum')
    ).reset_index()
    
    fig_wh = go.Figure()
    for cat in ['GOOD', 'QUARANTINE', 'DEFECTIVE']:
        cat_data = wh_cat_df[wh_cat_df['category'] == cat]
        # Ensure all warehouses present
        cat_data = wh_df[['warehouse_name']].merge(cat_data, on='warehouse_name', how='left').fillna(0)
        label = {'GOOD': '📗 Good', 'QUARANTINE': '📙 Quarantine', 'DEFECTIVE': '📕 Defective'}
        fig_wh.add_trace(go.Bar(
            x=cat_data['warehouse_name'],
            y=cat_data['value'],
            name=label.get(cat, cat),
            marker_color=_CATEGORY_COLORS.get(cat, '#999'),
            hovertemplate='%{x}<br>' + label.get(cat, cat) + '<br>Value: $%{y:,.2f}<extra></extra>',
        ))
    
    fig_wh.update_layout(barmode='stack')
    fig_wh = _plotly_layout_defaults(fig_wh, height=400)
    fig_wh.update_layout(
        xaxis_title='', yaxis_title='Value (USD)',
        xaxis_tickangle=-30,
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
    )
    st.plotly_chart(fig_wh, use_container_width=True)
    
    st.markdown("---")
    
    # ============================================================
    # ROW 4: Aging + Aging Value Heatmap
    # ============================================================
    r4c1, r4c2 = st.columns(2)
    
    with r4c1:
        st.markdown("##### ⏳ Aging Distribution (Items)")
        age_order = ['0-30 days', '31-60 days', '61-90 days', '91-180 days', '181-365 days', 'Over 1 year']
        age_df = df.groupby('age_bucket', observed=False).agg(
            items=('age_bucket', 'size'),
            value=('value', 'sum'),
        ).reindex(age_order).fillna(0).reset_index()
        age_df.columns = ['bucket', 'items', 'value']
        age_df['items'] = age_df['items'].astype(int)
        
        fig_age = go.Figure()
        fig_age.add_trace(go.Bar(
            x=age_df['bucket'],
            y=age_df['items'],
            marker_color=[_AGING_COLORS.get(b, '#999') for b in age_df['bucket']],
            text=age_df['items'],
            textposition='outside',
            hovertemplate='%{x}<br>Items: %{y:,}<br>Value: $%{customdata[0]:,.2f}<extra></extra>',
            customdata=age_df[['value']].values,
        ))
        fig_age = _plotly_layout_defaults(fig_age, height=380)
        fig_age.update_layout(
            xaxis_title='', yaxis_title='Items',
            showlegend=False,
        )
        st.plotly_chart(fig_age, use_container_width=True)
    
    with r4c2:
        st.markdown("##### 💰 Aging Distribution (Value)")
        fig_age_v = go.Figure()
        fig_age_v.add_trace(go.Bar(
            x=age_df['bucket'],
            y=age_df['value'],
            marker_color=[_AGING_COLORS.get(b, '#999') for b in age_df['bucket']],
            text=[format_currency(v) for v in age_df['value']],
            textposition='outside',
            hovertemplate='%{x}<br>Value: %{text}<br>Items: %{customdata[0]:,}<extra></extra>',
            customdata=age_df[['items']].values,
        ))
        fig_age_v = _plotly_layout_defaults(fig_age_v, height=380)
        fig_age_v.update_layout(
            xaxis_title='', yaxis_title='Value (USD)',
            showlegend=False,
        )
        st.plotly_chart(fig_age_v, use_container_width=True)
    
    st.markdown("---")
    
    # ============================================================
    # ROW 5: Aging × Brand Heatmap
    # ============================================================
    st.markdown("##### 🔥 Value Heatmap: Brand × Warehouse Age")
    
    # Top 15 brands by value for readable heatmap
    top_brands = df.groupby('brand')['value'].sum().nlargest(15).index.tolist()
    heat_df = df[df['brand'].isin(top_brands)].copy()
    
    pivot = heat_df.pivot_table(
        values='value', index='brand', columns='age_bucket',
        aggfunc='sum', fill_value=0, observed=False
    )
    # Reorder columns
    age_cols = [c for c in age_order if c in pivot.columns]
    pivot = pivot[age_cols]
    # Sort by total value descending
    pivot['_total'] = pivot.sum(axis=1)
    pivot = pivot.sort_values('_total', ascending=True).drop('_total', axis=1)
    
    fig_heat = go.Figure(data=go.Heatmap(
        z=pivot.values,
        x=pivot.columns.tolist(),
        y=pivot.index.tolist(),
        colorscale='YlOrRd',
        text=[[format_currency(v) if v > 0 else '' for v in row] for row in pivot.values],
        texttemplate='%{text}',
        textfont=dict(size=10),
        hovertemplate='Brand: %{y}<br>Age: %{x}<br>Value: $%{z:,.2f}<extra></extra>',
        colorbar=dict(title='USD'),
    ))
    heatmap_height = max(400, len(pivot) * 32 + 80)
    fig_heat = _plotly_layout_defaults(fig_heat, height=heatmap_height)
    fig_heat.update_layout(
        xaxis_title='Warehouse Age',
        yaxis_title='',
        showlegend=False,
    )
    st.plotly_chart(fig_heat, use_container_width=True)
    
    st.markdown("---")
    
    # ============================================================
    # ROW 6: Expiry × Brand Heatmap
    # ============================================================
    st.markdown("##### 🔥 Value Heatmap: Brand × Expiry Status")
    
    pivot_exp = heat_df.pivot_table(
        values='value', index='brand', columns='expiry_bucket',
        aggfunc='sum', fill_value=0
    )
    expiry_col_order = [c for c in expiry_order if c in pivot_exp.columns]
    pivot_exp = pivot_exp[expiry_col_order]
    pivot_exp['_total'] = pivot_exp.sum(axis=1)
    pivot_exp = pivot_exp.sort_values('_total', ascending=True).drop('_total', axis=1)
    
    fig_heat_exp = go.Figure(data=go.Heatmap(
        z=pivot_exp.values,
        x=pivot_exp.columns.tolist(),
        y=pivot_exp.index.tolist(),
        colorscale='YlOrRd',
        text=[[format_currency(v) if v > 0 else '' for v in row] for row in pivot_exp.values],
        texttemplate='%{text}',
        textfont=dict(size=10),
        hovertemplate='Brand: %{y}<br>Expiry: %{x}<br>Value: $%{z:,.2f}<extra></extra>',
        colorbar=dict(title='USD'),
    ))
    heatmap_exp_height = max(400, len(pivot_exp) * 32 + 80)
    fig_heat_exp = _plotly_layout_defaults(fig_heat_exp, height=heatmap_exp_height)
    fig_heat_exp.update_layout(
        xaxis_title='Expiry Status',
        yaxis_title='',
        showlegend=False,
    )
    st.plotly_chart(fig_heat_exp, use_container_width=True)


# ============================================================================
# MAIN APPLICATION
# ============================================================================

def main():
    """Main application entry point"""
    try:
        render_header()
        st.markdown("---")
        
        # === Three tabs ===
        tab_dashboard, tab_period, tab_analytics = st.tabs([
            "📊 Dashboard",
            "📋 Inventory Summary",
            "📈 Analytics"
        ])
        
        # ---- Tab 1: Dashboard (existing functionality) ----
        with tab_dashboard:
            category, warehouse_id, product_search, entity_ids, expiry_filter, brand_filter, age_filter = render_filters()
            st.markdown("---")
            
            with st.spinner("Loading inventory data..."):
                df = data_loader.get_unified_inventory(
                    category=category if category != 'All' else None,
                    warehouse_id=warehouse_id,
                    product_search=product_search if product_search else None,
                    entity_ids=entity_ids
                )
            
            # Apply brand filter client-side
            if brand_filter and not df.empty and 'brand' in df.columns:
                df = df[df['brand'].isin(brand_filter)].reset_index(drop=True)
            
            # Apply age filter client-side (cumulative threshold)
            if age_filter != 'All' and not df.empty and 'days_in_warehouse' in df.columns:
                days = pd.to_numeric(df['days_in_warehouse'], errors='coerce')
                threshold_map = {
                    '≥30 days': 30, '≥60 days': 60, '≥90 days': 90,
                    '≥180 days': 180, '≥365 days': 365,
                }
                threshold = threshold_map.get(age_filter)
                if threshold is not None:
                    df = df[days >= threshold].reset_index(drop=True)
            
            # Apply expiry status filter client-side
            if expiry_filter != 'All' and not df.empty and 'expiry_date' in df.columns:
                today = get_vietnam_today()
                expiry_dates = pd.to_datetime(df['expiry_date'], errors='coerce')
                
                if expiry_filter == 'Expired':
                    df = df[expiry_dates.dt.date < today].reset_index(drop=True)
                elif expiry_filter == 'Near Expiry':
                    near_cutoff = today + timedelta(days=90)
                    df = df[(expiry_dates.dt.date >= today) & (expiry_dates.dt.date <= near_cutoff)].reset_index(drop=True)
                elif expiry_filter == 'OK':
                    near_cutoff = today + timedelta(days=90)
                    df = df[expiry_dates.dt.date > near_cutoff].reset_index(drop=True)
                elif expiry_filter == 'No Expiry':
                    df = df[expiry_dates.isna()].reset_index(drop=True)
            
            render_summary_cards(df)
            st.markdown("---")
            
            render_data_table(df)
            
            if not df.empty:
                st.markdown("---")
                render_export_section(df, category, warehouse_id, entity_ids)
            
            if st.session_state.get('iq_show_detail') and st.session_state.get('iq_detail_data'):
                show_detail_dialog(st.session_state['iq_detail_data'])
        
        # ---- Tab 2: Tổng hợp tồn kho ----
        with tab_period:
            render_period_summary()
        
        # ---- Tab 3: Analytics ----
        with tab_analytics:
            render_analytics()
    
    except Exception as e:
        st.error(f"An error occurred: {str(e)}")
        logger.error(f"Application error: {e}", exc_info=True)
        
        if st.button("🔄 Reload"):
            st.cache_data.clear()
            st.session_state['iq_selected_idx'] = None
            st.rerun()
    
    # Footer
    st.markdown("---")
    st.caption("Inventory Quality Dashboard v1.3")


if __name__ == "__main__":
    main()