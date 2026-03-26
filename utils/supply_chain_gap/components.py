# utils/supply_chain_gap/components.py

"""
UI Components for Supply Chain GAP Analysis
KPI Cards, Sortable Tables, Drill-Down Dialog, Status Summary, Data Freshness

VERSION: 2.1.0
CHANGELOG:
- v2.1: @st.fragment for tab isolation (no full-page reruns on pagination/filter)
         @st.dialog for product drill-down (replaces inline selectbox)
         Row selection in FG table (click row → View Details → dialog)
- v2.0: Sortable columns, drill-down panel, data freshness, pagination
"""

import streamlit as st
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, List, Tuple
import logging

from .constants import (
    STATUS_CONFIG, GAP_CATEGORIES, PRODUCT_TYPES,
    ACTION_TYPES, RAW_MATERIAL_STATUS, UI_CONFIG,
    SUPPLY_SOURCES, DEMAND_SOURCES
)
from .result import SupplyChainGAPResult

logger = logging.getLogger(__name__)


# =============================================================================
# NUMBER FORMATTING HELPER
# =============================================================================

def _styled_dataframe(
    df: pd.DataFrame,
    qty_cols: Optional[List[str]] = None,
    currency_cols: Optional[List[str]] = None,
    pct_cols: Optional[List[str]] = None,
    decimal_cols: Optional[Dict[str, int]] = None
) -> 'pd.io.formats.style.Styler':
    """
    Apply thousand-separator formatting via pandas Styler.
    
    Streamlit's NumberColumn sprintf-js does NOT support %,.0f comma grouping.
    Use Styler.format instead — rendering shows commas while data stays numeric (sortable).
    
    Args:
        df: DataFrame to style
        qty_cols: columns to format as integers with comma: 221,500
        currency_cols: columns to format as currency: $701,928
        pct_cols: columns to format as percentage: 85.0%
        decimal_cols: dict {col: n_decimals} for decimal formatting
    """
    format_dict = {}
    
    if qty_cols:
        for col in qty_cols:
            if col in df.columns:
                format_dict[col] = '{:,.0f}'
    
    if currency_cols:
        for col in currency_cols:
            if col in df.columns:
                format_dict[col] = '${:,.0f}'
    
    if pct_cols:
        for col in pct_cols:
            if col in df.columns:
                format_dict[col] = '{:.1f}%'
    
    if decimal_cols:
        for col, n in decimal_cols.items():
            if col in df.columns:
                format_dict[col] = f'{{:,.{n}f}}'
    
    if format_dict:
        return df.style.format(format_dict, na_rep='-')
    return df


# =============================================================================
# DATA FRESHNESS INDICATOR
# =============================================================================

def render_data_freshness(state, on_refresh=None):
    """
    Render data freshness indicator with age + staleness warning + refresh.
    
    Returns:
        True if refresh button was clicked
    """
    if not state.has_result():
        return False
    
    age_display = state.get_data_age_display()
    is_stale = state.is_data_stale(threshold_minutes=30)
    last_calc = state.get_last_calculated()
    
    col1, col2, col3 = st.columns([2, 1, 1])
    
    with col1:
        time_str = last_calc.strftime('%H:%M:%S') if last_calc else ''
        if is_stale:
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:6px;">'
                f'<span style="color:#F59E0B;font-size:18px;">⚠️</span>'
                f'<span style="color:#92400E;font-size:13px;">'
                f'Data may be outdated — last analyzed <b>{age_display}</b> ({time_str})'
                f'</span></div>',
                unsafe_allow_html=True
            )
        else:
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:6px;">'
                f'<span style="color:#10B981;font-size:14px;">●</span>'
                f'<span style="color:#6B7280;font-size:13px;">'
                f'Analyzed {age_display} ({time_str})'
                f'</span></div>',
                unsafe_allow_html=True
            )
    
    with col3:
        refresh_clicked = st.button(
            "🔄 Refresh",
            key="scg_refresh_btn",
            width='stretch',
            type="secondary"
        )
        if refresh_clicked:
            return True
    
    return False


# =============================================================================
# KPI CARDS
# =============================================================================

def render_kpi_cards(result: SupplyChainGAPResult):
    """
    Render focused KPI cards — only actionable metrics.
    
    v2.3.1: FG metrics = filtered by brand/product. Raw metrics = full (shared resource).
    
    Row 1: Situation (what's the problem?)
    Row 2: Actions (what needs to be done?)
    """
    
    metrics = result.get_metrics_filtered()
    
    # Display filter banner
    if metrics.get('has_display_filter', False):
        filter_brands = metrics.get('filter_brands', [])
        filter_pids = metrics.get('filter_product_ids', [])
        filter_parts = []
        if filter_brands:
            filter_parts.append(f"Brand: {', '.join(filter_brands)}")
        if filter_pids:
            filter_parts.append(f"{len(filter_pids)} products selected")
        full_fg_total = len(result.fg_gap_df)
        filtered_fg_total = metrics.get('fg_total', 0)
        st.info(
            f"🔍 **Display filter:** {' · '.join(filter_parts)} — "
            f"FG shows {filtered_fg_total:,} of {full_fg_total:,} products. "
            f"Raw Materials shows full supply chain (shared resource)."
        )
    
    # Row 1: Situation
    cols = st.columns(4)
    
    with cols[0]:
        fg_total = metrics.get('fg_total', 0)
        fg_short = metrics.get('fg_shortage', 0)
        st.metric(
            label="🔴 FG Shortage",
            value=f"{fg_short:,}",
            delta=f"of {fg_total:,} products",
            delta_color="off",
            help="Số sản phẩm có Net GAP < 0\nNet GAP = Available Supply - Total Demand\nAvailable Supply = MAX(0, Total Supply - Safety Stock)"
        )
    
    with cols[1]:
        at_risk = metrics.get('at_risk_value', 0)
        st.metric(
            label="💰 At Risk Value",
            value=f"${at_risk:,.0f}",
            help="Tổng giá trị rủi ro (USD)\n= ∑ |Net GAP| × avg_unit_price_usd\nChỉ tính cho sản phẩm shortage"
        )
    
    with cols[2]:
        st.metric(
            label="👥 Affected Customers",
            value=f"{metrics.get('affected_customers', 0):,}",
            help="Số khách hàng có đơn hàng liên quan đến sản phẩm đang shortage"
        )
        # Dialog trigger button (only if there are affected customers)
        impact = result.customer_impact
        if impact and impact.affected_count > 0:
            if st.button("👁 View Details", key="scg_cust_dialog_btn", use_container_width=True):
                show_affected_customers_dialog()
    
    with cols[3]:
        raw_short = metrics.get('raw_shortage', 0)
        raw_total = metrics.get('raw_total', 0)
        st.metric(
            label="⚠️ Raw Shortage",
            value=f"{raw_short:,}",
            delta=f"of {raw_total:,} materials" if raw_total > 0 else None,
            delta_color="off",
            help="Số nguyên vật liệu có Net GAP < 0 (tính toàn bộ supply chain, không chỉ brand đang lọc)"
        )
    
    # Row 2: Actions
    st.markdown("##### 📋 Actions Required")
    cols = st.columns(3)
    
    has_filter = metrics.get('has_display_filter', False)
    
    with cols[0]:
        mo_total = metrics.get('mo_count', 0)
        mo_filtered = metrics.get('mo_filtered', mo_total)
        if has_filter and mo_filtered != mo_total:
            st.metric(label="🏭 MO to Create", value=f"{mo_filtered:,}",
                      delta=f"of {mo_total:,} total",
                      delta_color="off",
                      help="Lệnh sản xuất cần tạo.\nSố đầu = sản phẩm trong filter. Số sau = toàn bộ entity.")
        else:
            st.metric(label="🏭 MO to Create", value=f"{mo_total:,}",
                      help="Lệnh sản xuất cần tạo cho sản phẩm Manufacturing có shortage")
    with cols[1]:
        po_fg_total = metrics.get('po_fg_count', 0)
        po_fg_filtered = metrics.get('po_fg_filtered', po_fg_total)
        if has_filter and po_fg_filtered != po_fg_total:
            st.metric(label="🛒 PO for FG", value=f"{po_fg_filtered:,}",
                      delta=f"of {po_fg_total:,} total",
                      delta_color="off",
                      help="PO mua thành phẩm cần tạo.\nSố đầu = sản phẩm trong filter. Số sau = toàn bộ entity.")
        else:
            st.metric(label="🛒 PO for FG", value=f"{po_fg_total:,}",
                      help="PO mua thành phẩm cần tạo cho sản phẩm Trading đang shortage")
    with cols[2]:
        po_raw_total = metrics.get('po_raw_count', 0)
        po_raw_filtered = metrics.get('po_raw_filtered', po_raw_total)
        if has_filter and po_raw_filtered != po_raw_total:
            st.metric(label="📦 PO for Raw", value=f"{po_raw_filtered:,}",
                      delta=f"of {po_raw_total:,} total",
                      delta_color="off",
                      help="PO mua NVL cần tạo.\nSố đầu = NVL liên quan đến filter. Số sau = toàn bộ NVL shortage.")
        else:
            st.metric(label="📦 PO for Raw", value=f"{po_raw_total:,}",
                      help="PO mua NVL cần tạo cho NVL chính đang shortage")


@st.dialog("👥 Affected Customers Analysis", width="large")
def show_affected_customers_dialog():
    """
    Full-screen dialog for affected customer analysis.
    
    Retrieves result from session state.
    Shows:
    - Summary KPIs (customers, at-risk value, shortage products)
    - Tab 1: By Customer — aggregated per customer
    - Tab 2: By Product — aggregated per product
    - Tab 3: Detail Lines — customer × product with proportional at-risk
    """
    from .state import get_state
    
    state = get_state()
    result = state.get_result()
    
    if not result:
        st.error("No analysis result available")
        return
    
    impact = result.customer_impact
    if not impact or impact.affected_count == 0:
        st.info("No affected customers")
        return
    
    details = impact.details
    has_details = details is not None and not details.empty
    
    # =========================================================================
    # SUMMARY ROW
    # =========================================================================
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Customers Impacted", f"{impact.affected_count:,}")
    with col2:
        st.metric("Total At Risk", f"${impact.at_risk_value:,.0f}")
    with col3:
        shortage_products = len(details['product_id'].unique()) if has_details and 'product_id' in details.columns else 0
        st.metric("Shortage Products", f"{shortage_products:,}")
    
    if not has_details:
        st.divider()
        st.markdown("**Affected customers:**")
        for cust in impact.affected_customers[:30]:
            st.markdown(f"- {cust}")
        if len(impact.affected_customers) > 30:
            st.caption(f"... and {len(impact.affected_customers) - 30} more")
        return
    
    st.divider()
    
    # Ensure numeric columns
    for col in ['demand_qty', 'at_risk_qty', 'at_risk_value_usd', 'demand_value_usd', 'shortage_qty', 'net_gap']:
        if col in details.columns:
            details[col] = pd.to_numeric(details[col], errors='coerce').fillna(0)
    
    # =========================================================================
    # TABS
    # =========================================================================
    tab1, tab2, tab3 = st.tabs([
        "📊 By Customer",
        "📦 By Product",
        "📋 Detail Lines"
    ])
    
    # -------------------------------------------------------------------------
    # TAB 1: BY CUSTOMER
    # -------------------------------------------------------------------------
    with tab1:
        cust_agg_dict = {
            'product_id': 'nunique',
            'demand_qty': 'sum',
        }
        if 'at_risk_qty' in details.columns:
            cust_agg_dict['at_risk_qty'] = 'sum'
        if 'at_risk_value_usd' in details.columns:
            cust_agg_dict['at_risk_value_usd'] = 'sum'
        if 'demand_value_usd' in details.columns:
            cust_agg_dict['demand_value_usd'] = 'sum'
        
        cust_summary = details.groupby('customer').agg(cust_agg_dict).reset_index()
        cust_summary.rename(columns={'product_id': 'products_affected'}, inplace=True)
        
        # Sort by at-risk value descending
        sort_col = 'at_risk_value_usd' if 'at_risk_value_usd' in cust_summary.columns else 'demand_qty'
        cust_summary = cust_summary.sort_values(sort_col, ascending=False).reset_index(drop=True)
        
        # Round
        for col in ['demand_qty', 'at_risk_qty']:
            if col in cust_summary.columns:
                cust_summary[col] = cust_summary[col].round(0)
        if 'at_risk_value_usd' in cust_summary.columns:
            cust_summary['at_risk_value_usd'] = cust_summary['at_risk_value_usd'].round(0)
        if 'demand_value_usd' in cust_summary.columns:
            cust_summary['demand_value_usd'] = cust_summary['demand_value_usd'].round(0)
        
        cust_col_config = {
            'customer': st.column_config.TextColumn('Customer', width='large'),
            'products_affected': st.column_config.NumberColumn('Products', format="%d", width='small'),
            'demand_qty': st.column_config.NumberColumn('Total Demand'),
        }
        cust_display = ['customer', 'products_affected', 'demand_qty']
        
        if 'at_risk_qty' in cust_summary.columns:
            cust_display.append('at_risk_qty')
            cust_col_config['at_risk_qty'] = st.column_config.NumberColumn('At Risk Qty')
        if 'at_risk_value_usd' in cust_summary.columns:
            cust_display.append('at_risk_value_usd')
            cust_col_config['at_risk_value_usd'] = st.column_config.NumberColumn('At Risk ($)')
        if 'demand_value_usd' in cust_summary.columns:
            cust_display.append('demand_value_usd')
            cust_col_config['demand_value_usd'] = st.column_config.NumberColumn('Demand Value ($)')
        
        available = [c for c in cust_display if c in cust_summary.columns]
        
        st.caption(f"{len(cust_summary)} customers — sorted by at-risk value")
        styled = _styled_dataframe(
            cust_summary[available],
            qty_cols=['demand_qty', 'at_risk_qty'],
            currency_cols=['at_risk_value_usd', 'demand_value_usd']
        )
        st.dataframe(
            styled,
            column_config=cust_col_config,
            width='stretch',
            hide_index=True,
            height=min(500, 35 * len(cust_summary) + 38)
        )
    
    # -------------------------------------------------------------------------
    # TAB 2: BY PRODUCT
    # -------------------------------------------------------------------------
    with tab2:
        prod_agg_dict = {
            'customer': 'nunique',
            'demand_qty': 'sum',
        }
        if 'at_risk_qty' in details.columns:
            prod_agg_dict['at_risk_qty'] = 'sum'
        if 'at_risk_value_usd' in details.columns:
            prod_agg_dict['at_risk_value_usd'] = 'sum'
        
        # Also grab first-row product info
        for info_col in ['pt_code', 'product_name', 'package_size', 'brand', 'shortage_qty', 'gap_status', 'standard_uom']:
            if info_col in details.columns:
                prod_agg_dict[info_col] = 'first'
        
        prod_summary = details.groupby('product_id').agg(prod_agg_dict).reset_index()
        prod_summary.rename(columns={'customer': 'customer_count'}, inplace=True)
        
        sort_col = 'at_risk_value_usd' if 'at_risk_value_usd' in prod_summary.columns else 'shortage_qty'
        if sort_col in prod_summary.columns:
            prod_summary = prod_summary.sort_values(sort_col, ascending=False).reset_index(drop=True)
        
        # Format gap_status with icon
        if 'gap_status' in prod_summary.columns:
            prod_summary['status_display'] = prod_summary['gap_status'].apply(
                lambda x: f"{STATUS_CONFIG.get(x, {}).get('icon', '')} {x.replace('_', ' ').title()}" if pd.notna(x) else ''
            )
        
        # Round
        for col in ['demand_qty', 'at_risk_qty', 'shortage_qty', 'at_risk_value_usd']:
            if col in prod_summary.columns:
                prod_summary[col] = pd.to_numeric(prod_summary[col], errors='coerce').fillna(0).round(0)
        
        prod_display = []
        prod_col_config = {}
        
        for col, label, width in [
            ('pt_code', 'Code', 'small'),
            ('product_name', 'Part Number', 'medium'),
            ('package_size', 'Pkg Size', 'small'),
            ('brand', 'Brand', 'small'),
            ('standard_uom', 'UOM', 'small'),
        ]:
            if col in prod_summary.columns:
                prod_display.append(col)
                prod_col_config[col] = st.column_config.TextColumn(label, width=width)
        
        prod_display.append('customer_count')
        prod_col_config['customer_count'] = st.column_config.NumberColumn('Customers', format="%d", width='small')
        
        if 'shortage_qty' in prod_summary.columns:
            prod_display.append('shortage_qty')
            prod_col_config['shortage_qty'] = st.column_config.NumberColumn('Shortage')
        
        for col, label in [
            ('demand_qty', 'Total Demand'),
            ('at_risk_qty', 'At Risk Qty'),
            ('at_risk_value_usd', 'At Risk ($)'),
        ]:
            if col in prod_summary.columns:
                prod_display.append(col)
                prod_col_config[col] = st.column_config.NumberColumn(label)
        
        if 'status_display' in prod_summary.columns:
            prod_display.append('status_display')
            prod_col_config['status_display'] = st.column_config.TextColumn('Status', width='medium')
        
        available = [c for c in prod_display if c in prod_summary.columns]
        
        st.caption(f"{len(prod_summary)} shortage products — sorted by at-risk value")
        styled = _styled_dataframe(
            prod_summary[available],
            qty_cols=['shortage_qty', 'demand_qty', 'at_risk_qty'],
            currency_cols=['at_risk_value_usd']
        )
        st.dataframe(
            styled,
            column_config=prod_col_config,
            width='stretch',
            hide_index=True,
            height=min(500, 35 * len(prod_summary) + 38)
        )
    
    # -------------------------------------------------------------------------
    # TAB 3: DETAIL LINES (customer × product)
    # -------------------------------------------------------------------------
    with tab3:
        # Customer filter
        customers = sorted(details['customer'].dropna().unique().tolist()) if 'customer' in details.columns else []
        filtered_details = details.copy()
        
        if customers:
            selected_customer = st.selectbox(
                "Filter by customer",
                options=['All'] + customers,
                key="scg_cust_dialog_filter"
            )
            if selected_customer != 'All':
                filtered_details = filtered_details[filtered_details['customer'] == selected_customer]
        
        # Format gap_status with icon
        if 'gap_status' in filtered_details.columns:
            filtered_details['status_display'] = filtered_details['gap_status'].apply(
                lambda x: f"{STATUS_CONFIG.get(x, {}).get('icon', '')} {x.replace('_', ' ').title()}" if pd.notna(x) else ''
            )
        
        # Build display columns
        detail_display = []
        detail_col_config = {}
        
        for col, label, width in [
            ('customer', 'Customer', 'medium'),
            ('pt_code', 'Code', 'small'),
            ('product_name', 'Part Number', 'medium'),
            ('brand', 'Brand', 'small'),
            ('standard_uom', 'UOM', 'small'),
        ]:
            if col in filtered_details.columns:
                detail_display.append(col)
                detail_col_config[col] = st.column_config.TextColumn(label, width=width)
        
        for col, label in [
            ('demand_qty', 'Demand'),
            ('at_risk_qty', 'At Risk Qty'),
            ('at_risk_value_usd', 'At Risk ($)'),
            ('demand_value_usd', 'Demand Value ($)'),
            ('shortage_qty', 'Product Shortage'),
        ]:
            if col in filtered_details.columns:
                filtered_details[col] = pd.to_numeric(filtered_details[col], errors='coerce').fillna(0).round(0)
                detail_display.append(col)
                detail_col_config[col] = st.column_config.NumberColumn(label)
        
        if 'status_display' in filtered_details.columns:
            detail_display.append('status_display')
            detail_col_config['status_display'] = st.column_config.TextColumn('Status', width='small')
        
        available = [c for c in detail_display if c in filtered_details.columns]
        
        st.caption(
            f"Showing {len(filtered_details):,} lines — "
            f"At Risk Qty = customer's proportional share of product shortage"
        )
        if available:
            styled = _styled_dataframe(
                filtered_details[available],
                qty_cols=['demand_qty', 'at_risk_qty', 'shortage_qty'],
                currency_cols=['at_risk_value_usd', 'demand_value_usd']
            )
            st.dataframe(
                styled,
                column_config=detail_col_config,
                width='stretch',
                hide_index=True,
                height=min(500, 35 * len(filtered_details) + 38)
            )


# =============================================================================
# STATUS SUMMARY
# =============================================================================

def render_status_summary(gap_df: pd.DataFrame, key_prefix: str = "fg"):
    """Render status distribution summary"""
    if gap_df.empty or 'gap_status' not in gap_df.columns:
        return
    
    status_counts = gap_df['gap_status'].value_counts()
    cols = st.columns(min(len(status_counts), 6))
    
    for i, (status, count) in enumerate(status_counts.items()):
        if i >= 6:
            break
        config = STATUS_CONFIG.get(status, {})
        icon = config.get('icon', '❓')
        color = config.get('color', '#6B7280')
        with cols[i]:
            st.markdown(f"""
            <div style="text-align:center;padding:8px;background:white;border-radius:8px;border:1px solid #E5E7EB;">
                <span style="font-size:18px;">{icon}</span>
                <div style="font-size:20px;font-weight:600;color:{color};">{count}</div>
                <div style="font-size:11px;color:#6B7280;">{status.replace('_', ' ').title()}</div>
            </div>
            """, unsafe_allow_html=True)


# =============================================================================
# QUICK FILTER  (no st.rerun — fragment auto-reruns on button click)
# =============================================================================

def render_quick_filter(key_prefix: str = "fg") -> str:
    """Render quick filter buttons. Works inside @st.fragment without explicit rerun."""
    options = {
        'all': '📋 All',
        'shortage': '🔴 Shortage',
        'surplus': '📈 Surplus',
        'critical': '🚨 Critical'
    }
    
    cols = st.columns(len(options))
    selected = st.session_state.get(f'{key_prefix}_quick_filter', 'all')
    
    for i, (key, label) in enumerate(options.items()):
        with cols[i]:
            if st.button(label, key=f"{key_prefix}_qf_{key}", use_container_width=True,
                         type="primary" if selected == key else "secondary"):
                st.session_state[f'{key_prefix}_quick_filter'] = key
                # Fragment reruns automatically — no st.rerun() needed
    
    return st.session_state.get(f'{key_prefix}_quick_filter', 'all')


def apply_quick_filter(df: pd.DataFrame, filter_type: str) -> pd.DataFrame:
    """Apply quick filter to dataframe"""
    if df.empty or 'net_gap' not in df.columns:
        return df
    if filter_type == 'shortage':
        return df[df['net_gap'] < 0]
    elif filter_type == 'surplus':
        return df[df['net_gap'] > 0]
    elif filter_type == 'critical':
        return df[df['gap_status'].isin(['CRITICAL_SHORTAGE', 'SEVERE_SHORTAGE'])]
    return df


# =============================================================================
# SORTABLE DATA TABLES
# =============================================================================

def _get_column_config_fg() -> Dict[str, Any]:
    """Column config for FG GAP table — numeric types preserved for sorting"""
    return {
        'product_id': None,  # Hidden — used for selection lookup
        'pt_code': st.column_config.TextColumn('Code', width='small'),
        'product_name': st.column_config.TextColumn('Part Number', width='medium'),
        'package_size': st.column_config.TextColumn('Pkg Size', width='small'),
        'brand': st.column_config.TextColumn('Brand', width='small'),
        'standard_uom': st.column_config.TextColumn('UOM', width='small'),
        'total_supply': st.column_config.NumberColumn('Supply'),
        'total_demand': st.column_config.NumberColumn('Demand'),
        'net_gap': st.column_config.NumberColumn('GAP'),
        'coverage_pct': st.column_config.ProgressColumn('Coverage', format="%.0f%%", min_value=0, max_value=200),
        'gap_status_display': st.column_config.TextColumn('Status', width='medium'),
        'at_risk_value': st.column_config.NumberColumn('At Risk ($)'),
        'customer_count': st.column_config.NumberColumn('Customers', format="%d"),
    }


def render_fg_table(
    df: pd.DataFrame,
    items_per_page: int = 25,
    current_page: int = 1,
    enable_selection: bool = True,
    table_key: str = "fg_table"
) -> Dict[str, Any]:
    """
    Render FG GAP table with sortable columns + optional row selection.
    
    Returns dict with page info and selection:
        {page, total_pages, total_items, showing, selected_product_id}
    """
    if df.empty:
        st.info("No data to display")
        return {}
    
    # Pagination
    total_items = len(df)
    total_pages = max(1, (total_items + items_per_page - 1) // items_per_page)
    current_page = min(max(1, current_page), total_pages)
    start_idx = (current_page - 1) * items_per_page
    end_idx = min(start_idx + items_per_page, total_items)
    page_df = df.iloc[start_idx:end_idx].copy()
    
    # Display columns — product_id included but hidden via column_config
    display_cols = [
        'product_id',
        'pt_code', 'product_name', 'package_size', 'brand', 'standard_uom',
        'total_supply', 'total_demand', 'net_gap',
        'coverage_pct', 'gap_status_display', 'at_risk_value'
    ]
    
    # coverage_pct for ProgressColumn
    if 'coverage_ratio' in page_df.columns:
        page_df['coverage_pct'] = (
            pd.to_numeric(page_df['coverage_ratio'], errors='coerce').fillna(0) * 100
        ).clip(0, 200).round(0)
    else:
        page_df['coverage_pct'] = 0
    
    # Formatted status
    if 'gap_status' in page_df.columns:
        page_df['gap_status_display'] = page_df['gap_status'].apply(
            lambda x: f"{STATUS_CONFIG.get(x, {}).get('icon', '')} {x.replace('_', ' ').title()}"
        )
    else:
        page_df['gap_status_display'] = ''
    
    # Ensure numeric
    for col in ['total_supply', 'total_demand', 'net_gap']:
        if col in page_df.columns:
            page_df[col] = pd.to_numeric(page_df[col], errors='coerce').fillna(0).round(0)
    if 'at_risk_value' in page_df.columns:
        page_df['at_risk_value'] = pd.to_numeric(page_df['at_risk_value'], errors='coerce').fillna(0).round(0)
    
    available_cols = [c for c in display_cols if c in page_df.columns]
    
    selected_product_id = None
    
    # Apply thousand-separator styling
    styled = _styled_dataframe(
        page_df[available_cols],
        qty_cols=['total_supply', 'total_demand', 'net_gap'],
        currency_cols=['at_risk_value']
    )
    
    if enable_selection:
        event = st.dataframe(
            styled,
            column_config=_get_column_config_fg(),
            width='stretch',
            hide_index=True,
            height=min(400, 35 * len(page_df) + 38),
            on_select="rerun",
            selection_mode="single-row",
            key=table_key
        )
        selected_rows = event.selection.rows if event.selection else []
        if selected_rows and 'product_id' in page_df.columns:
            row_idx = selected_rows[0]
            if row_idx < len(page_df):
                selected_product_id = int(page_df.iloc[row_idx]['product_id'])
    else:
        st.dataframe(
            styled,
            column_config=_get_column_config_fg(),
            width='stretch',
            hide_index=True,
            height=min(400, 35 * len(page_df) + 38)
        )
    
    return {
        'page': current_page,
        'total_pages': total_pages,
        'total_items': total_items,
        'showing': f"{start_idx + 1}-{end_idx} of {total_items}",
        'selected_product_id': selected_product_id
    }


def render_manufacturing_table(
    result: SupplyChainGAPResult,
    items_per_page: int = 25,
    current_page: int = 1
) -> Dict[str, Any]:
    """Render manufacturing products with sortable columns + pagination"""
    mfg_shortage = result.get_manufacturing_shortage_filtered()
    if mfg_shortage.empty:
        st.info("🏭 No manufacturing products with shortage")
        return {}
    
    st.markdown(f"**{len(mfg_shortage)} Manufacturing Products with Shortage**")
    
    total_items = len(mfg_shortage)
    total_pages = max(1, (total_items + items_per_page - 1) // items_per_page)
    current_page = min(max(1, current_page), total_pages)
    start_idx = (current_page - 1) * items_per_page
    end_idx = min(start_idx + items_per_page, total_items)
    page_df = mfg_shortage.iloc[start_idx:end_idx]
    
    all_statuses = result.get_all_production_statuses()
    
    display_data = []
    for _, row in page_df.iterrows():
        product_id = row['product_id']
        status = all_statuses.get(product_id, result.get_production_status(product_id))
        can_produce = status.get('can_produce', False)
        display_data.append({
            'pt_code': row.get('pt_code', ''),
            'product_name': str(row.get('product_name', ''))[:50],
            'package_size': str(row.get('package_size', '')) if pd.notna(row.get('package_size')) else '',
            'brand': row.get('brand', ''),
            'standard_uom': row.get('standard_uom', ''),
            'net_gap': round(float(row.get('net_gap', 0)), 0),
            'at_risk_value': round(float(row.get('at_risk_value', 0)), 0) if pd.notna(row.get('at_risk_value')) else 0,
            'can_produce': '✅ Yes' if can_produce else '❌ No',
            'production_status': status.get('status', 'UNKNOWN'),
            'reason': status.get('reason', '')[:50],
            'bom_code': status.get('bom_code', '') or ''
        })
    
    display_df = pd.DataFrame(display_data)
    styled = _styled_dataframe(
        display_df,
        qty_cols=['net_gap'],
        currency_cols=['at_risk_value']
    )
    st.dataframe(
        styled,
        column_config={
            'pt_code': st.column_config.TextColumn('Code', width='small'),
            'product_name': st.column_config.TextColumn('Part Number', width='medium'),
            'package_size': st.column_config.TextColumn('Pkg Size', width='small'),
            'brand': st.column_config.TextColumn('Brand', width='small'),
            'standard_uom': st.column_config.TextColumn('UOM', width='small'),
            'net_gap': st.column_config.NumberColumn('GAP'),
            'at_risk_value': st.column_config.NumberColumn('At Risk ($)'),
            'can_produce': st.column_config.TextColumn('Producible', width='small'),
            'production_status': st.column_config.TextColumn('Status', width='small'),
            'reason': st.column_config.TextColumn('Reason', width='medium'),
            'bom_code': st.column_config.TextColumn('BOM', width='small'),
        },
        width='stretch', hide_index=True,
        height=min(400, 35 * len(display_df) + 38)
    )
    
    return {'page': current_page, 'total_pages': total_pages,
            'total_items': total_items, 'showing': f"{start_idx+1}-{end_idx} of {total_items}"}


def render_trading_table(
    result: SupplyChainGAPResult,
    items_per_page: int = 25,
    current_page: int = 1
) -> Dict[str, Any]:
    """Render trading products with sortable columns + pagination"""
    trading_shortage = result.get_trading_shortage_filtered()
    if trading_shortage.empty:
        st.info("🛒 No trading products with shortage")
        return {}
    
    st.markdown(f"**{len(trading_shortage)} Trading Products with Shortage**")
    
    total_items = len(trading_shortage)
    total_pages = max(1, (total_items + items_per_page - 1) // items_per_page)
    current_page = min(max(1, current_page), total_pages)
    start_idx = (current_page - 1) * items_per_page
    end_idx = min(start_idx + items_per_page, total_items)
    page_df = trading_shortage.iloc[start_idx:end_idx].copy()
    
    page_df['at_risk_value'] = pd.to_numeric(page_df.get('at_risk_value', 0), errors='coerce').fillna(0).round(0)
    page_df['net_gap'] = pd.to_numeric(page_df.get('net_gap', 0), errors='coerce').fillna(0).round(0)
    page_df['action'] = '🛒 Create PO'
    
    display_cols = ['pt_code', 'product_name', 'package_size', 'brand', 'standard_uom', 'net_gap', 'at_risk_value', 'action']
    available = [c for c in display_cols if c in page_df.columns]
    
    styled = _styled_dataframe(
        page_df[available],
        qty_cols=['net_gap'],
        currency_cols=['at_risk_value']
    )
    st.dataframe(
        styled,
        column_config={
            'pt_code': st.column_config.TextColumn('Code', width='small'),
            'product_name': st.column_config.TextColumn('Part Number', width='medium'),
            'package_size': st.column_config.TextColumn('Pkg Size', width='small'),
            'brand': st.column_config.TextColumn('Brand', width='small'),
            'standard_uom': st.column_config.TextColumn('UOM', width='small'),
            'net_gap': st.column_config.NumberColumn('GAP'),
            'at_risk_value': st.column_config.NumberColumn('At Risk ($)'),
            'action': st.column_config.TextColumn('Action', width='small'),
        },
        width='stretch', hide_index=True,
        height=min(400, 35 * len(page_df) + 38)
    )
    
    return {'page': current_page, 'total_pages': total_pages,
            'total_items': total_items, 'showing': f"{start_idx+1}-{end_idx} of {total_items}"}


def render_raw_material_table(
    result: SupplyChainGAPResult,
    items_per_page: int = 25,
    current_page: int = 1
) -> Dict[str, Any]:
    """Render raw material GAP table with sortable columns + pagination"""
    raw_df = result.raw_gap_df.copy()
    if raw_df.empty:
        st.info("🧪 No raw material data")
        return {}
    
    col1, col2, col3 = st.columns(3)
    with col1:
        show_primary_only = st.checkbox("Primary only", value=False, key="raw_primary_only")
    with col2:
        show_shortage_only = st.checkbox("Shortage only", value=False, key="raw_shortage_only")
    with col3:
        if 'bom_level' in raw_df.columns and raw_df['bom_level'].nunique() > 1:
            level_options = ['All'] + sorted(raw_df['bom_level'].unique().tolist())
            level_filter = st.selectbox("BOM Level", level_options, key="raw_level_filter")
            if level_filter != 'All':
                raw_df = raw_df[raw_df['bom_level'] == level_filter]
    
    if show_primary_only and 'is_primary' in raw_df.columns:
        raw_df = raw_df[raw_df['is_primary'].isin([1, True])]
    if show_shortage_only and 'net_gap' in raw_df.columns:
        raw_df = raw_df[raw_df['net_gap'] < 0]
    
    st.markdown(f"**{len(raw_df)} Raw Materials**")
    if raw_df.empty:
        st.info("No materials match current filters")
        return {}
    
    total_items = len(raw_df)
    total_pages = max(1, (total_items + items_per_page - 1) // items_per_page)
    current_page = min(max(1, current_page), total_pages)
    start_idx = (current_page - 1) * items_per_page
    end_idx = min(start_idx + items_per_page, total_items)
    page_df = raw_df.iloc[start_idx:end_idx].copy()
    
    for col in ['total_required_qty', 'total_supply', 'net_gap', 'safety_stock_qty']:
        if col in page_df.columns:
            page_df[col] = pd.to_numeric(page_df[col], errors='coerce').fillna(0).round(0)
    
    if 'coverage_ratio' in page_df.columns:
        page_df['coverage_pct'] = (pd.to_numeric(page_df['coverage_ratio'], errors='coerce').fillna(0) * 100).clip(0, 200).round(0)
    else:
        page_df['coverage_pct'] = 0
    
    display_cols = ['material_pt_code', 'material_name', 'material_package_size', 'material_brand', 'material_uom', 'material_type']
    col_config = {
        'material_pt_code': st.column_config.TextColumn('Code', width='small'),
        'material_name': st.column_config.TextColumn('Part Number', width='medium'),
        'material_package_size': st.column_config.TextColumn('Pkg Size', width='small'),
        'material_brand': st.column_config.TextColumn('Brand', width='small'),
        'material_uom': st.column_config.TextColumn('UOM', width='small'),
        'material_type': st.column_config.TextColumn('Type', width='small'),
    }
    if 'bom_level' in page_df.columns and page_df['bom_level'].nunique() > 1:
        display_cols.append('bom_level')
        col_config['bom_level'] = st.column_config.NumberColumn('Level', format="%d", width='small')
    
    # Demand breakdown columns (v2.3.1) — show when display filter is active
    has_breakdown = 'demand_from_selected' in page_df.columns and result.has_display_filter()
    if has_breakdown:
        for col in ['demand_from_selected', 'demand_from_others']:
            if col in page_df.columns:
                page_df[col] = pd.to_numeric(page_df[col], errors='coerce').fillna(0).round(0)
        filter_brands = result.applied_display_filter.get('brands', [])
        selected_label = ', '.join(filter_brands) if filter_brands else 'Selected'
        display_cols += ['demand_from_selected', 'demand_from_others']
        col_config.update({
            'demand_from_selected': st.column_config.NumberColumn(f'Demand ({selected_label})'),
            'demand_from_others': st.column_config.NumberColumn('Demand (Others)'),
        })
    
    display_cols += ['total_required_qty', 'total_supply', 'net_gap', 'coverage_pct']
    col_config.update({
        'total_required_qty': st.column_config.NumberColumn('Required'),
        'total_supply': st.column_config.NumberColumn('Supply'),
        'net_gap': st.column_config.NumberColumn('GAP'),
        'coverage_pct': st.column_config.ProgressColumn('Coverage', format="%.0f%%", min_value=0, max_value=200),
    })
    available = [c for c in display_cols if c in page_df.columns]
    
    styled = _styled_dataframe(
        page_df[available],
        qty_cols=['demand_from_selected', 'demand_from_others', 'total_required_qty', 'total_supply', 'net_gap']
    )
    st.dataframe(styled, column_config=col_config, width='stretch',
                 hide_index=True, height=min(400, 35 * len(page_df) + 38))
    
    return {'page': current_page, 'total_pages': total_pages,
            'total_items': total_items, 'showing': f"{start_idx+1}-{end_idx} of {total_items}"}


def render_semi_finished_table(
    result: SupplyChainGAPResult,
    items_per_page: int = 25,
    current_page: int = 1
) -> Dict[str, Any]:
    """Render semi-finished material GAP table with supply netting details"""
    semi_df = result.semi_finished_gap_df.copy()
    if semi_df.empty:
        st.info("🔶 No semi-finished materials (all BOMs are single-level)")
        return {}
    
    st.markdown(f"**{len(semi_df)} Semi-Finished Materials**")
    
    total_items = len(semi_df)
    total_pages = max(1, (total_items + items_per_page - 1) // items_per_page)
    current_page = min(max(1, current_page), total_pages)
    start_idx = (current_page - 1) * items_per_page
    end_idx = min(start_idx + items_per_page, total_items)
    page_df = semi_df.iloc[start_idx:end_idx].copy()
    
    for col in ['required_qty', 'total_supply', 'net_gap']:
        if col in page_df.columns:
            page_df[col] = pd.to_numeric(page_df[col], errors='coerce').fillna(0).round(0)
    
    display_cols = ['material_pt_code', 'material_name', 'material_package_size', 'material_brand', 'material_uom', 'bom_level',
                    'required_qty', 'total_supply', 'net_gap']
    available = [c for c in display_cols if c in page_df.columns]
    
    if 'net_gap' in page_df.columns:
        page_df['netting_status'] = page_df['net_gap'].apply(
            lambda x: '✅ Supply covers' if x >= 0 else '🔽 Shortage propagates')
        available.append('netting_status')
    
    styled = _styled_dataframe(
        page_df[available],
        qty_cols=['required_qty', 'total_supply', 'net_gap']
    )
    st.dataframe(
        styled,
        column_config={
            'material_pt_code': st.column_config.TextColumn('Code', width='small'),
            'material_name': st.column_config.TextColumn('Part Number', width='medium'),
            'material_package_size': st.column_config.TextColumn('Pkg Size', width='small'),
            'material_brand': st.column_config.TextColumn('Brand', width='small'),
            'material_uom': st.column_config.TextColumn('UOM', width='small'),
            'bom_level': st.column_config.NumberColumn('Level', format="%d", width='small'),
            'required_qty': st.column_config.NumberColumn('Required'),
            'total_supply': st.column_config.NumberColumn('Supply'),
            'net_gap': st.column_config.NumberColumn('GAP'),
            'netting_status': st.column_config.TextColumn('Netting', width='medium'),
        },
        width='stretch', hide_index=True,
        height=min(300, 35 * len(page_df) + 38)
    )
    return {'page': current_page, 'total_pages': total_pages,
            'total_items': total_items, 'showing': f"{start_idx+1}-{end_idx} of {total_items}"}


def render_action_table(
    result: SupplyChainGAPResult,
    action_type: str = 'all',
    items_per_page: int = 50,
    current_page: int = 1
) -> Dict[str, Any]:
    """Render action recommendations with sortable columns + pagination"""
    actions = result.get_all_actions()
    if not actions:
        st.info("📋 No actions to display")
        return {}
    
    if action_type == 'mo':
        actions = [a for a in actions if a['action_type'] in ['CREATE_MO', 'CREATE_MO_SEMI', 'WAIT_RAW', 'USE_ALTERNATIVE']]
    elif action_type == 'po_fg':
        actions = [a for a in actions if a['action_type'] == 'CREATE_PO_FG']
    elif action_type == 'po_raw':
        actions = [a for a in actions if a['action_type'] == 'CREATE_PO_RAW']
    
    if not actions:
        st.info("No actions of this type")
        return {}
    
    st.markdown(f"**{len(actions)} Actions**")
    
    rows = []
    for action in actions:
        ac = ACTION_TYPES.get(action['action_type'], {})
        rows.append({
            'action_display': f"{ac.get('icon', '📝')} {ac.get('label', action['action_type'])}",
            'pt_code': action.get('pt_code', ''),
            'product_name': str(action.get('product_name', ''))[:40],
            'package_size': action.get('package_size', ''),
            'brand': action.get('brand', ''),
            'quantity': round(float(action.get('quantity', 0)), 0),
            'uom': action.get('uom', ''),
            'priority': int(action.get('priority', 99)),
            'reason': str(action.get('reason', ''))[:50]
        })
    
    all_df = pd.DataFrame(rows)
    total_items = len(all_df)
    total_pages = max(1, (total_items + items_per_page - 1) // items_per_page)
    current_page = min(max(1, current_page), total_pages)
    start_idx = (current_page - 1) * items_per_page
    end_idx = min(start_idx + items_per_page, total_items)
    page_df = all_df.iloc[start_idx:end_idx]
    
    styled = _styled_dataframe(page_df, qty_cols=['quantity'])
    st.dataframe(
        styled,
        column_config={
            'action_display': st.column_config.TextColumn('Action', width='medium'),
            'pt_code': st.column_config.TextColumn('Code', width='small'),
            'product_name': st.column_config.TextColumn('Part Number', width='medium'),
            'package_size': st.column_config.TextColumn('Pkg Size', width='small'),
            'brand': st.column_config.TextColumn('Brand', width='small'),
            'quantity': st.column_config.NumberColumn('Qty'),
            'uom': st.column_config.TextColumn('UOM', width='small'),
            'priority': st.column_config.NumberColumn('Priority', format="%d"),
            'reason': st.column_config.TextColumn('Reason', width='medium'),
        },
        width='stretch', hide_index=True,
        height=min(400, 35 * len(page_df) + 38)
    )
    return {'page': current_page, 'total_pages': total_pages,
            'total_items': total_items, 'showing': f"{start_idx+1}-{end_idx} of {total_items}"}


# =============================================================================
# DRILL-DOWN DIALOG  (replaces inline selectbox approach)
# =============================================================================

@st.dialog("🔍 Product Detail", width="large")
def show_product_detail_dialog(product_id: int):
    """
    Modal dialog for product drill-down.
    
    Retrieves result from session state — no complex objects passed as args.
    Shows supply/demand breakdown, classification, BOM, raw materials, actions.
    """
    from .state import get_state
    
    state = get_state()
    result = state.get_result()
    if not result:
        st.error("No analysis result available")
        return
    
    product_row = result.fg_gap_df[result.fg_gap_df['product_id'] == product_id]
    if product_row.empty:
        st.warning("Product not found in results")
        return
    product = product_row.iloc[0]
    
    # --- Summary card ---
    gap_val = float(product.get('net_gap', 0))
    status = product.get('gap_status', 'UNKNOWN')
    cfg = STATUS_CONFIG.get(status, {})
    s_icon = cfg.get('icon', '❓')
    s_color = cfg.get('color', '#6B7280')
    
    st.markdown(f"""
    <div style="background:white;border-radius:10px;padding:16px 20px;border:1px solid #E5E7EB;
                box-shadow:0 1px 3px rgba(0,0,0,0.08);margin-bottom:12px;">
        <div style="display:flex;justify-content:space-between;align-items:center;">
            <div>
                <div style="font-size:11px;color:#6B7280;text-transform:uppercase;letter-spacing:0.5px;">
                    {product.get('pt_code', '')} · {product.get('brand', '')} · {product.get('standard_uom', '')}
                </div>
                <div style="font-size:18px;font-weight:700;color:#1F2937;margin-top:4px;">
                    {product.get('product_name', '')}
                </div>
            </div>
            <div style="text-align:right;">
                <div style="font-size:28px;font-weight:800;color:{s_color};">{gap_val:,.0f}</div>
                <div style="font-size:12px;color:{s_color};">{s_icon} {status.replace('_', ' ').title()}</div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # --- Supply / Demand / GAP breakdown ---
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("**📦 Supply Breakdown**")
        for src_key, src_map_key in [
            ('supply_inventory', 'INVENTORY'), ('supply_can_pending', 'CAN_PENDING'),
            ('supply_warehouse_transfer', 'WAREHOUSE_TRANSFER'),
            ('supply_purchase_order', 'PURCHASE_ORDER'), ('supply_mo_expected', 'MO_EXPECTED')
        ]:
            val = product.get(src_key, None)
            if pd.notna(val) and val > 0:
                lbl = SUPPLY_SOURCES.get(src_map_key, {}).get('label', src_key)
                st.markdown(f"- {lbl}: **{val:,.0f}**")
        st.markdown(f"**Total Supply: {product.get('total_supply', 0):,.0f}**")
    
    with col2:
        st.markdown("**📊 Demand Breakdown**")
        for src_key, src_map_key in [('demand_oc_pending', 'OC_PENDING'), ('demand_forecast', 'FORECAST')]:
            val = product.get(src_key, None)
            if pd.notna(val) and val > 0:
                lbl = DEMAND_SOURCES.get(src_map_key, {}).get('label', src_key)
                st.markdown(f"- {lbl}: **{val:,.0f}**")
        st.markdown(f"**Total Demand: {product.get('total_demand', 0):,.0f}**")
    
    with col3:
        st.markdown("**📐 GAP Calculation**")
        safety = product.get('safety_stock_qty', 0)
        avail = product.get('available_supply', 0)
        cov = product.get('coverage_ratio', 0)
        ar = product.get('at_risk_value', 0)
        st.markdown(f"- Safety Stock: **{safety:,.0f}**")
        st.markdown(f"- Available Supply: **{avail:,.0f}**")
        st.markdown(f"- Net GAP: **{gap_val:,.0f}**")
        st.markdown(f"- Coverage: **{cov*100:.1f}%**" if pd.notna(cov) and cov < 100 else "- Coverage: **N/A**")
        if ar > 0:
            st.markdown(f"- 💰 At Risk: **${ar:,.0f}**")
    
    # --- Classification + Production Status ---
    st.divider()
    prod_status = result.get_production_status(product_id)
    prod_type = prod_status.get('product_type', 'UNKNOWN')
    
    if prod_type == 'MANUFACTURING':
        _render_dialog_manufacturing(result, product_id, product, prod_status)
    elif prod_type == 'TRADING':
        _render_dialog_trading(product, prod_status)
    else:
        st.info("ℹ️ Product classification not available. Check if BOM data is loaded.")


def _render_dialog_manufacturing(result, product_id, product, prod_status):
    """Manufacturing detail inside drill-down dialog"""
    can_produce = prod_status.get('can_produce', False)
    bom_code = prod_status.get('bom_code', '') or 'N/A'
    reason = prod_status.get('reason', '')
    limiting = prod_status.get('limiting_materials', [])
    
    if can_produce:
        msg = "🔄 Can produce using alternative materials" if prod_status.get('status') == 'USE_ALTERNATIVE' \
              else "✅ Can produce (all materials available)"
        st.success(f"🏭 **Manufacturing** — BOM: `{bom_code}` — {msg}")
    else:
        st.warning(f"🏭 **Manufacturing** — BOM: `{bom_code}` — ❌ Cannot produce: {reason}")
        if limiting:
            st.caption(f"⚠️ Limiting materials: `{'`, `'.join(limiting[:5])}`")
    
    materials = result.get_raw_materials_for_fg(product_id)
    if materials.empty:
        st.info("No BOM materials found for this product")
        return
    
    st.markdown(f"**🧪 Raw Materials ({len(materials)} items)**")
    mat_data = []
    for _, mat in materials.iterrows():
        mat_gap = mat.get('net_gap', None)
        is_primary = mat.get('is_primary', 1) in [1, True]
        mat_data.append({
            'material_pt_code': mat.get('material_pt_code', ''),
            'material_name': str(mat.get('material_name', ''))[:40],
            'material_package_size': str(mat.get('material_package_size', '')) if pd.notna(mat.get('material_package_size')) else '',
            'material_brand': mat.get('material_brand', '') if pd.notna(mat.get('material_brand')) else '',
            'material_uom': mat.get('material_uom', '') if pd.notna(mat.get('material_uom')) else '',
            'type_label': '🔵 Primary' if is_primary else '🔄 Alt',
            'quantity_per_output': round(float(mat.get('quantity_per_output', 0) or 0), 2),
            'scrap_rate': round(float(mat.get('scrap_rate', 0) or 0), 1),
            'total_supply': round(float(mat.get('total_supply', 0)) if pd.notna(mat.get('total_supply')) else 0, 0),
            'net_gap': round(float(mat_gap), 0) if pd.notna(mat_gap) else None,
            'status_icon': '✅' if (pd.notna(mat_gap) and mat_gap >= 0) else ('🔴' if pd.notna(mat_gap) else '❓')
        })
    
    mat_df = pd.DataFrame(mat_data)
    styled = _styled_dataframe(mat_df, qty_cols=['total_supply', 'net_gap'])
    st.dataframe(styled, column_config={
        'material_pt_code': st.column_config.TextColumn('Code', width='small'),
        'material_name': st.column_config.TextColumn('Part Number', width='medium'),
        'material_package_size': st.column_config.TextColumn('Pkg Size', width='small'),
        'material_brand': st.column_config.TextColumn('Brand', width='small'),
        'material_uom': st.column_config.TextColumn('UOM', width='small'),
        'type_label': st.column_config.TextColumn('Type', width='small'),
        'quantity_per_output': st.column_config.NumberColumn('Qty/Output', format="%.2f"),
        'scrap_rate': st.column_config.NumberColumn('Scrap %', format="%.1f%%"),
        'total_supply': st.column_config.NumberColumn('Supply'),
        'net_gap': st.column_config.NumberColumn('GAP'),
        'status_icon': st.column_config.TextColumn('', width='small'),
    }, width='stretch', hide_index=True, height=min(300, 35 * len(mat_df) + 38))
    
    gap_val = float(product.get('net_gap', 0))
    if gap_val < 0:
        st.markdown("**📋 Recommended Action:**")
        uom = product.get('standard_uom', '')
        qty = abs(gap_val)
        if can_produce:
            if prod_status.get('status') == 'USE_ALTERNATIVE':
                st.markdown(f"🔄 **USE_ALTERNATIVE** — Produce `{qty:,.0f}` {uom} using alternative materials")
            else:
                st.markdown(f"🏭 **CREATE_MO** — Produce `{qty:,.0f}` {uom} (all materials sufficient)")
        else:
            st.markdown(f"⏳ **WAIT_RAW** — Need raw materials before producing `{qty:,.0f}` {uom}")
            if limiting:
                st.markdown(f"📦 **CREATE_PO_RAW** — Purchase: `{'`, `'.join(limiting[:5])}`")


def _render_dialog_trading(product, prod_status):
    """Trading detail inside drill-down dialog"""
    gap_val = float(product.get('net_gap', 0))
    st.info("🛒 **Trading** — No BOM (purchase directly from supplier)")
    if gap_val < 0:
        st.markdown("**📋 Recommended Action:**")
        st.markdown(f"🛒 **CREATE_PO_FG** — Purchase `{abs(gap_val):,.0f}` {product.get('standard_uom', '')} directly")


# =============================================================================
# PAGINATION
# =============================================================================

def render_pagination(current_page: int, total_pages: int, key_prefix: str = "main") -> int:
    """Render pagination controls. Callers use st.rerun(scope='fragment')."""
    if total_pages <= 1:
        return current_page
    
    cols = st.columns([1, 1, 2, 1, 1])
    with cols[0]:
        if st.button("⏮️", key=f"{key_prefix}_first", disabled=current_page <= 1):
            return 1
    with cols[1]:
        if st.button("◀️", key=f"{key_prefix}_prev", disabled=current_page <= 1):
            return current_page - 1
    with cols[2]:
        st.markdown(
            f"<div style='text-align:center;padding:8px;color:#6B7280;font-size:13px;'>"
            f"Page {current_page} of {total_pages}</div>",
            unsafe_allow_html=True)
    with cols[3]:
        if st.button("▶️", key=f"{key_prefix}_next", disabled=current_page >= total_pages):
            return current_page + 1
    with cols[4]:
        if st.button("⏭️", key=f"{key_prefix}_last", disabled=current_page >= total_pages):
            return total_pages
    return current_page


# =============================================================================
# FRAGMENT: FG OVERVIEW TAB
# =============================================================================

@st.fragment
def fg_charts_fragment(result: SupplyChainGAPResult, charts):
    """Fragment for FG charts — donut + value at risk + top shortages."""
    fg_df = result.get_fg_gap_filtered()
    col1, col2 = st.columns(2)
    with col1:
        st.plotly_chart(charts.create_status_donut(fg_df), width='stretch')
    with col2:
        st.plotly_chart(charts.create_top_items_bar(fg_df, 'shortage', 8), width='stretch')
    
    render_status_summary(fg_df, key_prefix="fg")


@st.fragment
def fg_table_fragment(result: SupplyChainGAPResult):
    """
    Fragment for FG table + quick filter + pagination + row-select drill-down.
    
    Interactions (filter, pagination, row click) rerun ONLY this fragment.
    """
    from .state import get_state
    state = get_state()
    
    # Quick filter
    quick_filter = render_quick_filter(key_prefix="fg")
    filtered_df = apply_quick_filter(result.get_fg_gap_filtered(), quick_filter)
    
    # Table controls
    col1, col2 = st.columns([1, 3])
    with col1:
        items_per_page = st.selectbox("Items per page", UI_CONFIG['items_per_page_options'],
                                       index=1, key="fg_items_per_page")
    with col2:
        search = st.text_input("Search", placeholder="Filter...", key="fg_search")
        if search:
            mask = filtered_df.astype(str).apply(
                lambda x: x.str.contains(search, case=False, na=False)).any(axis=1)
            filtered_df = filtered_df[mask]
    
    # FG Table with row selection
    page = state.get_page('fg')
    clear_counter = st.session_state.get('_fg_select_counter', 0)
    
    page_info = render_fg_table(
        filtered_df, items_per_page, page,
        enable_selection=True,
        table_key=f"fg_table_sel_{clear_counter}"
    )
    
    if not page_info:
        return
    
    # --- Selection action bar ---
    selected_pid = page_info.get('selected_product_id')
    
    if selected_pid is not None:
        sel_row = filtered_df[filtered_df['product_id'] == selected_pid]
        if not sel_row.empty:
            sel = sel_row.iloc[0]
            gv = sel.get('net_gap', 0)
            gi = '🔴' if gv < 0 else ('🟢' if gv > 0 else '⚪')
            
            col1, col2, col3 = st.columns([3, 1, 1])
            with col1:
                st.markdown(f"**{gi} Selected:** `{sel.get('pt_code', '')}` — "
                            f"{sel.get('product_name', '')} (GAP: {gv:,.0f})")
            with col2:
                if st.button("🔍 View Details", key="fg_view_detail", type="primary", use_container_width=True):
                    show_product_detail_dialog(selected_pid)
            with col3:
                if st.button("✖ Clear", key="fg_clear_select", use_container_width=True):
                    st.session_state['_fg_select_counter'] = clear_counter + 1
                    st.rerun(scope="fragment")
    else:
        st.caption("💡 Click a row to select, then **View Details** to inspect supply/demand, BOM, and actions.")
    
    # --- Pagination ---
    if page_info.get('total_pages', 1) > 1:
        new_page = render_pagination(page_info['page'], page_info['total_pages'], "fg")
        if new_page != page_info['page']:
            state.set_page(new_page, 'fg', page_info['total_pages'])
            st.rerun(scope="fragment")


# =============================================================================
# FRAGMENT: MANUFACTURING TAB
# =============================================================================

@st.fragment
def manufacturing_fragment(result: SupplyChainGAPResult, charts):
    """Fragment for Manufacturing tab — isolated reruns."""
    from .state import get_state
    state = get_state()
    
    if result.has_classification():
        mfg_shortage = result.get_manufacturing_shortage_filtered()
        
        # Production status from FULL data (raw material availability is global)
        all_statuses = result.get_all_production_statuses()
        # Filter to only filtered products
        filtered_mfg_ids = result.get_manufacturing_filtered()['product_id'].tolist() if not result.get_manufacturing_filtered().empty else []
        filtered_shortage_ids = [pid for pid in mfg_shortage['product_id'].tolist()] if not mfg_shortage.empty else []
        filtered_statuses = {pid: s for pid, s in all_statuses.items() if pid in filtered_shortage_ids}
        
        can_produce_count = sum(1 for s in filtered_statuses.values() if s.get('can_produce'))
        cannot_produce_count = len(filtered_statuses) - can_produce_count
        
        col1, col2, col3 = st.columns([1, 1, 1])
        with col1:
            st.plotly_chart(
                charts.create_classification_pie(len(result.get_manufacturing_filtered()), len(result.get_trading_filtered())),
                width='stretch')
        with col2:
            metrics = result.get_metrics_filtered()
            st.metric("Manufacturing Products", metrics.get('manufacturing_count', 0))
            st.metric("With Shortage", len(mfg_shortage))
        with col3:
            if all_statuses:
                st.metric("✅ Can Produce", can_produce_count,
                          help="Shortage products that have sufficient raw materials — ready to create MO")
                st.metric("❌ Cannot Produce", cannot_produce_count,
                          help="Shortage products missing raw materials — need PO for raw materials first")
            else:
                st.metric("BOM Analysis", "N/A")
    
    page = state.get_page('mfg')
    page_info = render_manufacturing_table(result, items_per_page=25, current_page=page)
    if page_info and page_info.get('total_pages', 1) > 1:
        new_page = render_pagination(page_info['page'], page_info['total_pages'], "mfg")
        if new_page != page_info['page']:
            state.set_page(new_page, 'mfg', page_info['total_pages'])
            st.rerun(scope="fragment")


# =============================================================================
# FRAGMENT: TRADING TAB
# =============================================================================

@st.fragment
def trading_fragment(result: SupplyChainGAPResult):
    """Fragment for Trading tab — isolated reruns."""
    from .state import get_state
    state = get_state()
    
    page = state.get_page('trading')
    page_info = render_trading_table(result, items_per_page=25, current_page=page)
    if page_info and page_info.get('total_pages', 1) > 1:
        new_page = render_pagination(page_info['page'], page_info['total_pages'], "trading")
        if new_page != page_info['page']:
            state.set_page(new_page, 'trading', page_info['total_pages'])
            st.rerun(scope="fragment")


# =============================================================================
# FRAGMENT: RAW MATERIALS TAB
# =============================================================================

@st.fragment
def raw_materials_fragment(result: SupplyChainGAPResult, charts):
    """Fragment for Raw Materials tab — isolated reruns."""
    from .state import get_state
    state = get_state()
    
    if not result.has_raw_data():
        st.info("No raw material data available")
        return
    
    metrics = result.get_metrics_filtered()
    rm = result.raw_metrics
    
    # --- Row 1: Metrics bar (compact) ---
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Materials", rm.get('total_materials', 0))
    c2.metric("🔴 Shortage", rm.get('shortage_count', 0))
    c3.metric("✅ Sufficient", rm.get('sufficient_count', 0))
    max_depth = metrics.get('max_bom_depth', 1)
    semi_count = metrics.get('semi_finished_total', 0)
    c4.metric("BOM Depth", f"{max_depth} levels" if max_depth > 1 else "1 level")
    c5.metric("Semi-Finished", semi_count)
    
    # --- Insight callout ---
    shortage_pct = (rm.get('shortage_count', 0) / max(rm.get('total_materials', 1), 1)) * 100
    if shortage_pct >= 50:
        st.error(
            f"⚠️ **{shortage_pct:.0f}% of materials in shortage** — "
            f"{rm.get('shortage_count', 0)} of {rm.get('total_materials', 0)} materials "
            f"cannot meet current production requirements. Immediate procurement action needed."
        )
    elif shortage_pct >= 25:
        st.warning(
            f"🟡 **{shortage_pct:.0f}% of materials in shortage** — "
            f"{rm.get('shortage_count', 0)} materials need procurement attention."
        )
    
    # --- Row 2: Charts (donut + top shortages) ---
    col1, col2 = st.columns(2)
    with col1:
        st.plotly_chart(charts.create_raw_material_status(result.raw_gap_df), width='stretch')
    with col2:
        st.plotly_chart(charts.create_raw_material_top_shortage(result.raw_gap_df), width='stretch')
    
    # --- Semi-finished section (only if multi-level) ---
    if result.has_semi_finished_data():
        st.markdown("#### 🔶 Semi-Finished Products (Supply Netting)")
        st.caption("Semi-finished products have their own BOMs. "
                   "Supply netting: if inventory covers demand, no further BOM explosion needed.")
        render_semi_finished_table(result, items_per_page=25, current_page=1)
        st.divider()
    
    # --- Raw materials table ---
    st.markdown("#### 🧪 Raw Materials (Leaf Nodes)")
    page = state.get_page('raw')
    page_info = render_raw_material_table(result, items_per_page=25, current_page=page)
    if page_info and page_info.get('total_pages', 1) > 1:
        new_page = render_pagination(page_info['page'], page_info['total_pages'], "raw")
        if new_page != page_info['page']:
            state.set_page(new_page, 'raw', page_info['total_pages'])
            st.rerun(scope="fragment")


# =============================================================================
# FRAGMENT: ACTIONS TAB
# =============================================================================

@st.fragment
def actions_fragment(result: SupplyChainGAPResult, charts):
    """Fragment for Actions tab — isolated reruns."""
    if not result.has_actions():
        st.success("✅ No actions required")
        return
    
    metrics = result.get_metrics_filtered()
    has_filter = metrics.get('has_display_filter', False)
    
    # Action counts
    mo_total = metrics.get('mo_count', 0)
    po_fg_total = metrics.get('po_fg_count', 0)
    po_raw_total = metrics.get('po_raw_count', 0)
    mo_filtered = metrics.get('mo_filtered', mo_total)
    po_fg_filtered = metrics.get('po_fg_filtered', po_fg_total)
    po_raw_filtered = metrics.get('po_raw_filtered', po_raw_total)
    
    # Filter label for chart legend
    filter_brands = metrics.get('filter_brands', [])
    filter_label = ', '.join(filter_brands) if filter_brands else 'Selected'
    
    col1, col2 = st.columns(2)
    with col1:
        if has_filter:
            st.plotly_chart(
                charts.create_action_summary(
                    mo_total, po_fg_total, po_raw_total,
                    mo_filtered=mo_filtered,
                    po_fg_filtered=po_fg_filtered,
                    po_raw_filtered=po_raw_filtered,
                    filter_label=filter_label
                ),
                width='stretch')
        else:
            st.plotly_chart(
                charts.create_action_summary(mo_total, po_fg_total, po_raw_total),
                width='stretch')
    
    # Tab labels with filtered/total
    if has_filter:
        mo_label = f"🏭 MO ({mo_filtered}/{mo_total})"
        po_fg_label = f"🛒 PO-FG ({po_fg_filtered}/{po_fg_total})"
        po_raw_label = f"📦 PO-Raw ({po_raw_filtered}/{po_raw_total})"
    else:
        mo_label = f"🏭 MO ({mo_total})"
        po_fg_label = f"🛒 PO-FG ({po_fg_total})"
        po_raw_label = f"📦 PO-Raw ({po_raw_total})"
    
    at1, at2, at3 = st.tabs([mo_label, po_fg_label, po_raw_label])
    with at1:
        render_action_table(result, action_type='mo')
    with at2:
        render_action_table(result, action_type='po_fg')
    with at3:
        render_action_table(result, action_type='po_raw')


# =============================================================================
# PERIOD GAP: REUSABLE COMPONENTS (v2.3)
# =============================================================================

def _render_period_kpis(period_df: pd.DataFrame, track_backlog: bool, period_type: str):
    """Render compact period KPIs with past/future breakdown."""
    from .period_calculator import format_period_display
    
    if period_df.empty:
        return
    
    id_col = 'material_id' if 'material_id' in period_df.columns else 'product_id'
    shortage = period_df[period_df['gap_quantity'] < 0]
    
    # Count past/future periods
    if 'is_past' in period_df.columns:
        past_periods = period_df[period_df['is_past']]['period'].nunique()
        future_periods = period_df[~period_df['is_past']]['period'].nunique()
        period_label = f"{period_df['period'].nunique()} (🔴{past_periods} past, 🟢{future_periods} future)"
    else:
        period_label = str(period_df['period'].nunique())
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("📅 Periods", period_label)
    c2.metric("🔴 Shortage Periods", shortage['period'].nunique() if not shortage.empty else 0)
    c3.metric("🔴 Shortage Items", shortage[id_col].nunique() if not shortage.empty else 0)
    avg_fill = period_df['fulfillment_rate'].mean() if 'fulfillment_rate' in period_df.columns else 0
    c4.metric("Avg Fill %", f"{avg_fill:.1f}%")
    
    if track_backlog and 'backlog_to_next' in period_df.columns:
        fb = period_df.groupby(id_col)['backlog_to_next'].last()
        total_backlog = fb.sum()
        with_backlog = (fb > 0).sum()
        if total_backlog > 0:
            bc1, bc2 = st.columns(2)
            bc1.metric("📦 Final Backlog", f"{total_backlog:,.0f}")
            bc2.metric("Items w/ Backlog", with_backlog)


def render_pivot_view(
    period_df: pd.DataFrame,
    period_type: str,
    key_prefix: str,
    code_col: str = 'pt_code',
    name_col: str = 'product_name'
):
    """Render pivot view: products × periods matrix with color coding."""
    from .period_calculator import create_pivot_data
    
    if period_df.empty:
        return
    
    pivot = create_pivot_data(period_df, period_type, code_col=code_col, name_col=name_col)
    if pivot.empty:
        return
    
    # Determine numeric columns (period columns)
    non_period_cols = [code_col, name_col, 'Category']
    period_cols = [c for c in pivot.columns if c not in non_period_cols]
    
    if not period_cols:
        return
    
    st.caption(
        f"**Category:** 🔺 = Net Shortage | 📈 = Net Surplus | ✅ = Balanced  \n"
        f"**Period:** 🔴 = Past | 🟢 = Current/Future"
    )
    
    # Apply color styling to numeric cells
    def _color_gap(val):
        if isinstance(val, (int, float)):
            if val < 0:
                return 'background-color: #fee2e2; color: #DC2626; font-weight: bold'
            elif val > 0:
                return 'background-color: #d1fae5; color: #059669'
        return ''
    
    styled = pivot.style.applymap(_color_gap, subset=period_cols).format(
        {c: '{:,.0f}' for c in period_cols}, na_rep='-'
    )
    
    st.dataframe(
        styled, width='stretch', hide_index=True,
        height=min(400, 35 * len(pivot) + 38)
    )


def render_period_detail_table(
    df: pd.DataFrame,
    items_per_page: int,
    page_key: str,
    track_backlog: bool,
    period_type: str,
    code_col: str = 'pt_code',
    name_col: str = 'product_name',
    brand_col: str = 'brand',
    uom_col: str = 'standard_uom'
):
    """Render period GAP detail table with pagination, past-period indicator, product type."""
    from .period_calculator import format_period_display
    from .state import get_state
    
    state = get_state()
    
    if df.empty:
        st.info("No data matches current filters")
        return
    
    id_col = 'material_id' if 'material_id' in df.columns else 'product_id'
    st.caption(f"**{len(df):,} rows** — {df[id_col].nunique()} items × {df['period'].nunique()} periods")
    
    total_items = len(df)
    total_pages = max(1, (total_items + items_per_page - 1) // items_per_page)
    page = state.get_page(page_key)
    page = min(max(1, page), total_pages)
    start_idx = (page - 1) * items_per_page
    end_idx = min(start_idx + items_per_page, total_items)
    page_df = df.iloc[start_idx:end_idx].copy()
    
    # Past period indicator (🔴 = past, blank = current/future)
    if 'is_past' in page_df.columns:
        page_df['_past'] = page_df['is_past'].apply(lambda x: '🔴' if x else '')
    else:
        page_df['_past'] = ''
    
    # Period label with date range
    page_df['period_label'] = page_df['period'].apply(
        lambda p: format_period_display(p, period_type)
    )
    
    # Build display columns — _past indicator first
    display_cols = ['_past', code_col, name_col, brand_col, uom_col,
                    'period_label', 'begin_inventory', 'supply_in_period', 'total_available',
                    'demand_in_period']
    if track_backlog:
        display_cols.extend(['backlog_from_prev', 'effective_demand'])
    display_cols.extend(['gap_quantity', 'fulfillment_rate', 'fulfillment_status'])
    if track_backlog:
        display_cols.append('backlog_to_next')
    # Product type (Matched / Demand Only / Supply Only) — only for FG
    if 'product_type' in page_df.columns:
        display_cols.append('product_type')
    # Backlog status
    if 'backlog_to_next' in page_df.columns:
        page_df['backlog_status'] = page_df['backlog_to_next'].apply(
            lambda x: 'Has Backlog' if x > 0 else 'No Backlog'
        )
        display_cols.append('backlog_status')
    
    available = [c for c in display_cols if c in page_df.columns]
    qty_cols = [c for c in ['begin_inventory', 'supply_in_period', 'total_available',
                            'demand_in_period', 'gap_quantity', 'backlog_from_prev',
                            'effective_demand', 'backlog_to_next'] if c in available]
    
    styled = _styled_dataframe(page_df[available], qty_cols=qty_cols, decimal_cols={'fulfillment_rate': 1})
    
    col_config = {
        '_past': st.column_config.TextColumn('', width='small'),
        code_col: st.column_config.TextColumn('Code', width='small'),
        name_col: st.column_config.TextColumn('Product', width='medium'),
        brand_col: st.column_config.TextColumn('Brand', width='small'),
        uom_col: st.column_config.TextColumn('UOM', width='small'),
        'period_label': st.column_config.TextColumn('Period', width='medium'),
        'begin_inventory': st.column_config.NumberColumn('Begin Inv'),
        'supply_in_period': st.column_config.NumberColumn('Supply In'),
        'total_available': st.column_config.NumberColumn('Available'),
        'demand_in_period': st.column_config.NumberColumn('Demand'),
        'backlog_from_prev': st.column_config.NumberColumn('Backlog In'),
        'effective_demand': st.column_config.NumberColumn('Total Need'),
        'gap_quantity': st.column_config.NumberColumn('GAP'),
        'fulfillment_rate': st.column_config.ProgressColumn('Fill %', format="%.0f%%", min_value=0, max_value=100),
        'fulfillment_status': st.column_config.TextColumn('Status', width='small'),
        'backlog_to_next': st.column_config.NumberColumn('Backlog Out'),
        'product_type': st.column_config.TextColumn('Type', width='small'),
        'backlog_status': st.column_config.TextColumn('Backlog', width='small'),
    }
    
    st.dataframe(styled, column_config=col_config, width='stretch',
                 hide_index=True, height=min(500, 35 * len(page_df) + 38))
    
    if total_pages > 1:
        new_page = render_pagination(page, total_pages, page_key)
        if new_page != page:
            state.set_page(new_page, page_key, total_pages)
            st.rerun(scope="fragment")


def _render_period_analysis_section(
    period_df: pd.DataFrame,
    charts,
    period_type: str,
    track_backlog: bool,
    key_prefix: str,
    page_key: str,
    code_col: str = 'pt_code',
    name_col: str = 'product_name',
    brand_col: str = 'brand',
    uom_col: str = 'standard_uom',
    id_col: str = 'product_id'
):
    """
    Reusable period analysis section — called within each tab fragment.
    Contains: KPIs → Charts → Pivot View → Filters → Detail Table
    """
    from .period_calculator import format_period_display, get_period_sort_key
    
    if period_df.empty:
        st.info("📅 No period data available for this category")
        return
    
    # KPIs
    _render_period_kpis(period_df, track_backlog, period_type)
    
    # Charts
    col1, col2 = st.columns(2)
    with col1:
        st.plotly_chart(
            charts.create_period_shortage_summary(period_df, period_type),
            width='stretch', key=f"{key_prefix}_shortage_summary_chart")
    with col2:
        st.plotly_chart(
            charts.create_period_gap_timeline(period_df, top_n=8, period_type=period_type),
            width='stretch', key=f"{key_prefix}_gap_timeline_chart")
    
    # Pivot View
    with st.expander("📊 Pivot View — GAP by Period", expanded=False, key=f"{key_prefix}_pivot_expander"):
        render_pivot_view(period_df, period_type, key_prefix, code_col=code_col, name_col=name_col)
    
    # Filters + Detail Table
    has_product_type = 'product_type' in period_df.columns
    
    if has_product_type:
        fc1, fc2, fc3, fc4, fc5 = st.columns([2, 1, 1, 1, 1])
    else:
        fc1, fc2, fc3, fc5 = st.columns([2, 1, 1, 1])
        fc4 = None
    
    with fc1:
        code_options = sorted(period_df[code_col].dropna().unique().tolist())
        sel_codes = st.multiselect("Filter", code_options, key=f"{key_prefix}_code_f", placeholder="All items")
    with fc2:
        status_f = st.selectbox("Status", ["All", "❌ Shortage", "✅ Fulfilled"], key=f"{key_prefix}_status_f")
    with fc3:
        period_f = st.selectbox("Period", ["All", "🟢 Future Only", "🔴 Past Only"],
                                key=f"{key_prefix}_period_f")
    if has_product_type and fc4:
        with fc4:
            type_f = st.selectbox("Type", ["All", "Matched", "Demand Only", "Supply Only"],
                                  key=f"{key_prefix}_type_f")
    else:
        type_f = "All"
    with fc5:
        ipp = st.selectbox("Items/page", UI_CONFIG['items_per_page_options'], index=1, key=f"{key_prefix}_ipp")
    
    filtered = period_df.copy()
    if sel_codes:
        filtered = filtered[filtered[code_col].isin(sel_codes)]
    if status_f == "❌ Shortage":
        filtered = filtered[filtered['gap_quantity'] < 0]
    elif status_f == "✅ Fulfilled":
        filtered = filtered[filtered['gap_quantity'] >= 0]
    if period_f == "🟢 Future Only" and 'is_past' in filtered.columns:
        filtered = filtered[~filtered['is_past']]
    elif period_f == "🔴 Past Only" and 'is_past' in filtered.columns:
        filtered = filtered[filtered['is_past']]
    if type_f != "All" and 'product_type' in filtered.columns:
        filtered = filtered[filtered['product_type'] == type_f]
    
    render_period_detail_table(
        filtered, ipp, page_key, track_backlog, period_type,
        code_col=code_col, name_col=name_col, brand_col=brand_col, uom_col=uom_col
    )


# =============================================================================
# PER-TAB PERIOD FRAGMENTS (v2.3)
# =============================================================================

@st.fragment
def fg_period_fragment(result: SupplyChainGAPResult, charts):
    """Period analysis for FG products (filtered by brand/product if active)."""
    if not result.has_period_data():
        st.caption("📅 No period data. Supply/demand need date columns.")
        return
    _render_period_analysis_section(
        result.get_fg_period_gap_filtered(), charts, result.period_type,
        result.filters_used.get('track_backlog', True),
        key_prefix='fg_p', page_key='fg_period'
    )


@st.fragment
def manufacturing_period_fragment(result: SupplyChainGAPResult, charts):
    """Period analysis for manufacturing products (filtered)."""
    if not result.has_period_data() or not result.has_classification():
        st.caption("📅 No period data for manufacturing products")
        return
    mfg_period = result.get_manufacturing_period_gap_filtered()
    if mfg_period.empty:
        st.caption("📅 No manufacturing products in period data")
        return
    _render_period_analysis_section(
        mfg_period, charts, result.period_type,
        result.filters_used.get('track_backlog', True),
        key_prefix='mfg_p', page_key='mfg_period'
    )


@st.fragment
def trading_period_fragment(result: SupplyChainGAPResult, charts):
    """Period analysis for trading products (filtered)."""
    if not result.has_period_data() or not result.has_classification():
        st.caption("📅 No period data for trading products")
        return
    trd_period = result.get_trading_period_gap_filtered()
    if trd_period.empty:
        st.caption("📅 No trading products in period data")
        return
    _render_period_analysis_section(
        trd_period, charts, result.period_type,
        result.filters_used.get('track_backlog', True),
        key_prefix='trd_p', page_key='trd_period'
    )


@st.fragment
def raw_period_fragment(result: SupplyChainGAPResult, charts):
    """Period analysis for raw materials (BOM-exploded from FG shortage)."""
    if not result.has_raw_period_data():
        st.caption("📅 No raw material period data (requires manufacturing shortage + BOM)")
        return
    _render_period_analysis_section(
        result.raw_period_gap_df, charts, result.period_type,
        result.filters_used.get('track_backlog', True),
        key_prefix='raw_p', page_key='raw_period',
        code_col='material_pt_code', name_col='material_name',
        brand_col='material_brand', uom_col='material_uom',
        id_col='material_id'
    )


# Backward compatibility alias
def period_gap_fragment(result, charts):
    """Deprecated: use fg_period_fragment instead."""
    fg_period_fragment(result, charts)


def render_period_gap_table(*args, **kwargs):
    """Deprecated: use render_period_detail_table instead."""
    render_period_detail_table(*args, **kwargs)