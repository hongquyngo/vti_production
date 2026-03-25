# utils/supply_chain_planning/po_planning_components.py

"""
UI Components for PO Planning — Streamlit fragments and tables.

Components:
- KPI cards (urgency, value, vendor count)
- Urgency distribution bar
- Vendor PO groups (expandable cards)
- PO lines table (sortable, paginated)
- Unmatched items panel
- Fragments for tab isolation
"""

import streamlit as st
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, List
import logging

from .planning_constants import (
    URGENCY_LEVELS, SHORTAGE_SOURCE, PRICE_SOURCE,
    PO_PLANNING_UI, VENDOR_RELIABILITY
)
from .po_result import POSuggestionResult, POLineItem, VendorPOGroup

logger = logging.getLogger(__name__)


# =============================================================================
# STYLED DATAFRAME HELPER (consistent with supply_chain_gap)
# =============================================================================

def _styled_dataframe(
    df: pd.DataFrame,
    qty_cols: Optional[List[str]] = None,
    currency_cols: Optional[List[str]] = None,
    pct_cols: Optional[List[str]] = None,
) -> 'pd.io.formats.style.Styler':
    """Apply thousand-separator formatting via pandas Styler."""
    fmt = {}
    if qty_cols:
        for c in qty_cols:
            if c in df.columns:
                fmt[c] = '{:,.0f}'
    if currency_cols:
        for c in currency_cols:
            if c in df.columns:
                fmt[c] = '${:,.2f}'
    if pct_cols:
        for c in pct_cols:
            if c in df.columns:
                fmt[c] = '{:.1f}%'
    return df.style.format(fmt, na_rep='-') if fmt else df


# =============================================================================
# KPI CARDS
# =============================================================================

def render_po_kpi_cards(result: POSuggestionResult):
    """Render top-level KPI cards for PO Planning."""
    metrics = result.get_summary()

    cols = st.columns(5)

    with cols[0]:
        st.metric(
            label="📦 PO Lines",
            value=f"{metrics.get('total_po_lines', 0):,}",
            delta=f"{metrics.get('fg_lines', 0)} FG + {metrics.get('raw_lines', 0)} Raw",
            delta_color="off",
        )

    with cols[1]:
        st.metric(
            label="🏭 Vendors",
            value=f"{metrics.get('total_vendors', 0):,}",
        )

    with cols[2]:
        st.metric(
            label="💰 Total Value",
            value=f"${metrics.get('total_value_usd', 0):,.0f}",
        )

    with cols[3]:
        overdue = metrics.get('overdue_count', 0)
        critical = metrics.get('critical_count', 0)
        if overdue > 0:
            st.metric(
                label="🚨 Overdue",
                value=f"{overdue}",
                delta=f"{critical} critical total",
                delta_color="off",
            )
        elif critical > 0:
            st.metric(label="🔴 Critical", value=f"{critical}")
        else:
            st.metric(label="✅ No Urgent", value="0")

    with cols[4]:
        unmatched = metrics.get('unmatched_count', 0)
        if unmatched > 0:
            st.metric(
                label="❌ No Vendor",
                value=f"{unmatched}",
                help="Products with no costbook or PO history — need vendor sourcing",
            )
        else:
            st.metric(label="✅ All Matched", value="100%")


# =============================================================================
# URGENCY DISTRIBUTION
# =============================================================================

def render_urgency_bar(result: POSuggestionResult):
    """Render horizontal urgency distribution bar."""
    dist = result.get_urgency_distribution()
    if not dist:
        return

    total = sum(dist.values())
    if total == 0:
        return

    # Build segments
    segments_html = []
    for level_key in ['OVERDUE', 'CRITICAL', 'URGENT', 'THIS_WEEK', 'PLANNED']:
        count = dist.get(level_key, 0)
        if count == 0:
            continue
        cfg = URGENCY_LEVELS.get(level_key, {})
        pct = count / total * 100
        color = cfg.get('color', '#6B7280')
        icon = cfg.get('icon', '')
        label = cfg.get('label', level_key)
        segments_html.append(
            f'<div style="width:{pct:.1f}%;background:{color};color:white;'
            f'text-align:center;padding:6px 2px;font-size:12px;font-weight:600;'
            f'white-space:nowrap;overflow:hidden;">'
            f'{icon} {count}</div>'
        )

    bar_html = (
        '<div style="display:flex;border-radius:8px;overflow:hidden;'
        'margin:4px 0 8px 0;">' + ''.join(segments_html) + '</div>'
    )

    # Legend
    legend_parts = []
    for level_key in ['OVERDUE', 'CRITICAL', 'URGENT', 'THIS_WEEK', 'PLANNED']:
        count = dist.get(level_key, 0)
        if count == 0:
            continue
        cfg = URGENCY_LEVELS.get(level_key, {})
        legend_parts.append(
            f'<span style="margin-right:12px;">'
            f'{cfg.get("icon", "")} <b>{cfg.get("label", level_key)}</b>: {count}'
            f'</span>'
        )

    legend_html = (
        f'<div style="font-size:12px;color:#6B7280;">'
        + ''.join(legend_parts) + '</div>'
    )

    st.markdown(bar_html + legend_html, unsafe_allow_html=True)


# =============================================================================
# VENDOR PO GROUPS (Summary Cards)
# =============================================================================

def render_vendor_summary_table(result: POSuggestionResult):
    """Render vendor summary as a sortable table."""
    vendor_df = result.get_vendor_summary_df()
    if vendor_df.empty:
        st.info("No vendor groups")
        return

    # Add urgency icon
    vendor_df['urgency_display'] = vendor_df['max_urgency_level'].apply(
        lambda x: f"{URGENCY_LEVELS.get(x, {}).get('icon', '')} {URGENCY_LEVELS.get(x, {}).get('label', x)}"
    )

    display_cols = [
        'vendor_name', 'vendor_code', 'vendor_location_type',
        'total_lines', 'total_value_usd', 'primary_currency',
        'urgency_display', 'trade_term', 'payment_term',
    ]
    available = [c for c in display_cols if c in vendor_df.columns]

    styled = _styled_dataframe(
        vendor_df[available],
        currency_cols=['total_value_usd'],
    )

    st.dataframe(
        styled,
        column_config={
            'vendor_name': st.column_config.TextColumn('Vendor', width='large'),
            'vendor_code': st.column_config.TextColumn('Code', width='small'),
            'vendor_location_type': st.column_config.TextColumn('Location', width='small'),
            'total_lines': st.column_config.NumberColumn('Lines', format="%d"),
            'total_value_usd': st.column_config.NumberColumn('Value (USD)'),
            'primary_currency': st.column_config.TextColumn('Currency', width='small'),
            'urgency_display': st.column_config.TextColumn('Urgency', width='medium'),
            'trade_term': st.column_config.TextColumn('Trade Term', width='small'),
            'payment_term': st.column_config.TextColumn('Payment', width='small'),
        },
        width='stretch',
        hide_index=True,
        height=min(400, 35 * len(vendor_df) + 38),
    )


# =============================================================================
# VENDOR PO DETAIL (Expandable per vendor)
# =============================================================================

def render_vendor_po_detail(result: POSuggestionResult, vendor_id: int):
    """Render PO lines for a specific vendor inside an expander."""
    group = result.vendor_groups.get(vendor_id)
    if not group or not group.lines:
        st.info("No lines for this vendor")
        return

    lines_data = [l.to_dict() for l in group.lines]
    df = pd.DataFrame(lines_data)

    display_cols = [
        'pt_code', 'product_name', 'shortage_source', 'standard_uom',
        'shortage_qty', 'pending_po_qty', 'net_shortage_qty', 'suggested_qty',
        'unit_price_usd', 'line_value_usd',
        'price_source', 'lead_time_days', 'urgency_display',
        'must_order_by',
    ]

    # Add urgency display
    df['urgency_display'] = df['urgency_level'].apply(
        lambda x: f"{URGENCY_LEVELS.get(x, {}).get('icon', '')} {URGENCY_LEVELS.get(x, {}).get('label', x)}"
    )

    # Source display
    df['shortage_source'] = df['shortage_source'].apply(
        lambda x: SHORTAGE_SOURCE.get(x, {}).get('icon', '') + ' ' + SHORTAGE_SOURCE.get(x, {}).get('label', x)
    )

    available = [c for c in display_cols if c in df.columns]

    styled = _styled_dataframe(
        df[available],
        qty_cols=['shortage_qty', 'pending_po_qty', 'net_shortage_qty', 'suggested_qty'],
        currency_cols=['unit_price_usd', 'line_value_usd'],
    )

    st.dataframe(
        styled,
        column_config={
            'pt_code': st.column_config.TextColumn('Code', width='small'),
            'product_name': st.column_config.TextColumn('Product', width='medium'),
            'shortage_source': st.column_config.TextColumn('Source', width='small'),
            'standard_uom': st.column_config.TextColumn('UOM', width='small'),
            'shortage_qty': st.column_config.NumberColumn('Shortage'),
            'pending_po_qty': st.column_config.NumberColumn('Pending PO'),
            'net_shortage_qty': st.column_config.NumberColumn('Net Need'),
            'suggested_qty': st.column_config.NumberColumn('Order Qty'),
            'unit_price_usd': st.column_config.NumberColumn('Price/u (USD)'),
            'line_value_usd': st.column_config.NumberColumn('Value (USD)'),
            'price_source': st.column_config.TextColumn('Price Src', width='small'),
            'lead_time_days': st.column_config.NumberColumn('LT (d)', format="%d"),
            'urgency_display': st.column_config.TextColumn('Urgency', width='medium'),
            'must_order_by': st.column_config.DateColumn('Must Order By', format='YYYY-MM-DD'),
        },
        width='stretch',
        hide_index=True,
        height=min(350, 35 * len(df) + 38),
    )


# =============================================================================
# ALL PO LINES TABLE (flat view with filtering)
# =============================================================================

def render_po_lines_table(
    result: POSuggestionResult,
    filter_source: str = 'all',
    filter_urgency: str = 'all',
    filter_vendor: Optional[int] = None,
    items_per_page: int = 25,
    current_page: int = 1,
    table_key: str = 'po_lines',
) -> Dict[str, Any]:
    """
    Render full PO lines table with filters and pagination.
    Returns page_info dict.
    """
    lines_df = result.get_all_lines_df()
    if lines_df.empty:
        st.info("📋 No PO suggestions generated")
        return {}

    # Apply filters
    if filter_source == 'fg':
        lines_df = lines_df[lines_df['shortage_source'] == 'FG_TRADING']
    elif filter_source == 'raw':
        lines_df = lines_df[lines_df['shortage_source'] == 'RAW_MATERIAL']

    if filter_urgency == 'overdue':
        lines_df = lines_df[lines_df['urgency_level'] == 'OVERDUE']
    elif filter_urgency == 'critical':
        lines_df = lines_df[lines_df['urgency_level'].isin(['OVERDUE', 'CRITICAL'])]
    elif filter_urgency == 'urgent':
        lines_df = lines_df[lines_df['urgency_level'].isin(['OVERDUE', 'CRITICAL', 'URGENT'])]

    if filter_vendor is not None:
        lines_df = lines_df[lines_df['vendor_id'] == filter_vendor]

    if lines_df.empty:
        st.info("No lines match current filters")
        return {}

    # Sort by urgency priority
    lines_df = lines_df.sort_values(['urgency_priority', 'line_value_usd'],
                                     ascending=[True, False]).reset_index(drop=True)

    # Pagination
    total_items = len(lines_df)
    total_pages = max(1, (total_items + items_per_page - 1) // items_per_page)
    current_page = min(max(1, current_page), total_pages)
    start = (current_page - 1) * items_per_page
    end = min(start + items_per_page, total_items)
    page_df = lines_df.iloc[start:end].copy()

    # Add display columns
    page_df['urgency_display'] = page_df['urgency_level'].apply(
        lambda x: f"{URGENCY_LEVELS.get(x, {}).get('icon', '')} {URGENCY_LEVELS.get(x, {}).get('label', x)}"
    )
    page_df['source_icon'] = page_df['shortage_source'].apply(
        lambda x: SHORTAGE_SOURCE.get(x, {}).get('icon', '')
    )
    page_df['price_icon'] = page_df['price_source'].apply(
        lambda x: PRICE_SOURCE.get(x, {}).get('icon', '')
    )

    display_cols = [
        'urgency_display', 'source_icon', 'pt_code', 'product_name', 'brand',
        'standard_uom', 'vendor_name',
        'net_shortage_qty', 'suggested_qty',
        'unit_price_usd', 'line_value_usd', 'currency_code',
        'price_icon', 'lead_time_days',
        'must_order_by',
    ]
    available = [c for c in display_cols if c in page_df.columns]

    styled = _styled_dataframe(
        page_df[available],
        qty_cols=['net_shortage_qty', 'suggested_qty'],
        currency_cols=['unit_price_usd', 'line_value_usd'],
    )

    st.dataframe(
        styled,
        column_config={
            'urgency_display': st.column_config.TextColumn('Urgency', width='medium'),
            'source_icon': st.column_config.TextColumn('', width='small'),
            'pt_code': st.column_config.TextColumn('Code', width='small'),
            'product_name': st.column_config.TextColumn('Product', width='large'),
            'brand': st.column_config.TextColumn('Brand', width='small'),
            'standard_uom': st.column_config.TextColumn('UOM', width='small'),
            'vendor_name': st.column_config.TextColumn('Vendor', width='medium'),
            'net_shortage_qty': st.column_config.NumberColumn('Need'),
            'suggested_qty': st.column_config.NumberColumn('Order Qty'),
            'unit_price_usd': st.column_config.NumberColumn('$/unit'),
            'line_value_usd': st.column_config.NumberColumn('Value $'),
            'currency_code': st.column_config.TextColumn('Curr', width='small'),
            'price_icon': st.column_config.TextColumn('Src', width='small'),
            'lead_time_days': st.column_config.NumberColumn('LT', format="%d"),
            'must_order_by': st.column_config.DateColumn('Must Order', format='YYYY-MM-DD'),
        },
        width='stretch',
        hide_index=True,
        height=min(500, 35 * len(page_df) + 38),
        key=table_key,
    )

    return {
        'page': current_page,
        'total_pages': total_pages,
        'total_items': total_items,
        'showing': f"{start + 1}-{end} of {total_items}",
    }


# =============================================================================
# UNMATCHED ITEMS PANEL
# =============================================================================

def render_unmatched_panel(result: POSuggestionResult):
    """Render unmatched items (no vendor found)."""
    unmatched_df = result.get_unmatched_df()
    if unmatched_df.empty:
        return

    st.warning(
        f"⚠️ **{len(unmatched_df)} products have no vendor** — "
        f"need costbook setup or vendor sourcing"
    )

    display_cols = ['pt_code', 'product_name', 'brand', 'shortage_source',
                    'shortage_qty', 'uom', 'reason']
    available = [c for c in display_cols if c in unmatched_df.columns]

    styled = _styled_dataframe(unmatched_df[available], qty_cols=['shortage_qty'])

    st.dataframe(
        styled,
        column_config={
            'pt_code': st.column_config.TextColumn('Code', width='small'),
            'product_name': st.column_config.TextColumn('Product', width='large'),
            'brand': st.column_config.TextColumn('Brand', width='small'),
            'shortage_source': st.column_config.TextColumn('Source', width='small'),
            'shortage_qty': st.column_config.NumberColumn('Shortage'),
            'uom': st.column_config.TextColumn('UOM', width='small'),
            'reason': st.column_config.TextColumn('Reason', width='large'),
        },
        width='stretch',
        hide_index=True,
        height=min(250, 35 * len(unmatched_df) + 38),
    )


# =============================================================================
# PAGINATION (reuse from supply_chain_gap pattern)
# =============================================================================

def render_pagination(
    current_page: int,
    total_pages: int,
    key_prefix: str
) -> int:
    """Render pagination controls. Returns new page number."""
    if total_pages <= 1:
        return current_page

    cols = st.columns([1, 1, 3, 1, 1])
    with cols[0]:
        if st.button("⏮️", key=f"{key_prefix}_first", disabled=current_page <= 1):
            return 1
    with cols[1]:
        if st.button("◀️", key=f"{key_prefix}_prev", disabled=current_page <= 1):
            return current_page - 1
    with cols[2]:
        st.markdown(
            f'<div style="text-align:center;padding:6px;color:#6B7280;">'
            f'Page {current_page} of {total_pages}</div>',
            unsafe_allow_html=True)
    with cols[3]:
        if st.button("▶️", key=f"{key_prefix}_next", disabled=current_page >= total_pages):
            return current_page + 1
    with cols[4]:
        if st.button("⏭️", key=f"{key_prefix}_last", disabled=current_page >= total_pages):
            return total_pages
    return current_page


# =============================================================================
# DATA RECONCILIATION PANEL
# =============================================================================

def render_reconciliation_panel(result: POSuggestionResult):
    """
    Render data flow reconciliation: Input → Output.
    Shows exactly where every item from GAP result ended up.
    No items should "disappear" without explanation.
    """
    recon = result.get_reconciliation()
    total_input = recon.get('total_input', 0)

    if total_input == 0:
        return

    with st.expander("📐 **Data Reconciliation** — GAP Input → PO Output", expanded=False):
        # Row 1: Input from GAP
        st.markdown("**📥 Input from SCM GAP**")
        ic1, ic2, ic3 = st.columns(3)
        ic1.metric("Total Items", f"{total_input}")
        ic2.metric("🛒 FG Trading", f"{recon.get('input_fg', 0)}")
        ic3.metric("🧪 Raw Material", f"{recon.get('input_raw', 0)}")

        st.divider()

        # Row 2: Output breakdown
        st.markdown("**📤 Processing Result**")
        oc1, oc2, oc3, oc4 = st.columns(4)
        oc1.metric("✅ PO Lines Created", f"{recon.get('matched', 0)}",
                    delta=f"{recon.get('matched_fg', 0)} FG + {recon.get('matched_raw', 0)} Raw",
                    delta_color="off")
        oc2.metric("⏭️ Skipped (PO Covers)", f"{recon.get('skipped_pending_po', 0)}",
                    help="Existing pending PO already covers the shortage — no new PO needed")
        oc3.metric("❌ No Vendor", f"{recon.get('unmatched', 0)}",
                    delta=f"{recon.get('unmatched_fg', 0)} FG + {recon.get('unmatched_raw', 0)} Raw",
                    delta_color="off")

        errors = recon.get('processing_errors', 0)
        validation_skip = recon.get('input_skipped_validation', 0)
        other = errors + validation_skip
        if other > 0:
            oc4.metric("⚠️ Other", f"{other}",
                        delta=f"{errors} errors, {validation_skip} invalid",
                        delta_color="off")
        else:
            oc4.metric("⚠️ Other", "0")

        # Row 3: Balance check
        accounted = recon.get('total_accounted', 0)
        discrepancy = recon.get('discrepancy', 0)
        if discrepancy == 0:
            st.success(
                f"✅ **Balanced:** {total_input} input = "
                f"{recon.get('matched', 0)} matched + "
                f"{recon.get('skipped_pending_po', 0)} skipped + "
                f"{recon.get('unmatched', 0)} unmatched"
                f"{f' + {other} other' if other else ''}"
            )
        else:
            st.warning(
                f"⚠️ **Discrepancy:** {total_input} input ≠ {accounted} accounted "
                f"(diff = {discrepancy}). Check processing logs."
            )

        # Skipped items detail table (if any)
        if result.has_skipped():
            st.markdown("**⏭️ Skipped Items — Pending PO Covers Shortage**")
            skipped_df = result.get_skipped_df()
            display_cols = ['pt_code', 'product_name', 'shortage_source',
                            'shortage_qty', 'pending_po_qty', 'vendor_name', 'reason']
            available = [c for c in display_cols if c in skipped_df.columns]

            styled = _styled_dataframe(
                skipped_df[available],
                qty_cols=['shortage_qty', 'pending_po_qty'],
            )
            st.dataframe(
                styled,
                column_config={
                    'pt_code': st.column_config.TextColumn('Code', width='small'),
                    'product_name': st.column_config.TextColumn('Product', width='large'),
                    'shortage_source': st.column_config.TextColumn('Source', width='small'),
                    'shortage_qty': st.column_config.NumberColumn('Shortage'),
                    'pending_po_qty': st.column_config.NumberColumn('Pending PO'),
                    'vendor_name': st.column_config.TextColumn('Vendor', width='medium'),
                    'reason': st.column_config.TextColumn('Reason', width='large'),
                },
                width='stretch', hide_index=True,
                height=min(250, 35 * len(skipped_df) + 38),
            )


# =============================================================================
# FRAGMENT: OVERVIEW TAB
# =============================================================================

@st.fragment
def po_overview_fragment(result: POSuggestionResult):
    """Fragment: KPIs + urgency bar + reconciliation + vendor summary."""
    render_po_kpi_cards(result)

    st.markdown("##### 📊 Urgency Distribution")
    render_urgency_bar(result)

    # Insight callouts
    overdue = result.get_overdue_lines()
    if overdue:
        overdue_value = sum(l.line_value_usd for l in overdue)
        st.error(
            f"🚨 **{len(overdue)} items are OVERDUE** — "
            f"must-order-by date has passed. "
            f"Total at-risk value: **${overdue_value:,.0f}**. "
            f"Order immediately to minimize delay."
        )

    if result.has_unmatched():
        render_unmatched_panel(result)

    # Data reconciliation — shows where every input item ended up
    render_reconciliation_panel(result)


# =============================================================================
# FRAGMENT: VENDOR GROUPS TAB
# =============================================================================

@st.fragment
def po_vendor_groups_fragment(result: POSuggestionResult):
    """Fragment: Vendor summary + expandable PO detail per vendor."""
    if not result.vendor_groups:
        st.info("No vendor groups — run PO planning first")
        return

    st.markdown(f"##### 🏭 {len(result.vendor_groups)} Vendors")
    render_vendor_summary_table(result)

    st.divider()
    st.markdown("##### 📋 PO Lines by Vendor")

    for vid, group in result.vendor_groups.items():
        urgency_cfg = URGENCY_LEVELS.get(group.max_urgency_level, {})
        icon = urgency_cfg.get('icon', '📦')
        label = f"{icon} {group.vendor_name} — {group.total_lines} lines, ${group.total_value_usd:,.0f}"

        with st.expander(label, expanded=(group.max_urgency_priority <= 2)):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Lines", group.total_lines)
            c2.metric("Value", f"${group.total_value_usd:,.0f}")
            c3.metric("Currency", group.primary_currency)
            c4.metric("Terms", f"{group.trade_term} / {group.payment_term}" if group.trade_term else "N/A")

            render_vendor_po_detail(result, vid)


# =============================================================================
# FRAGMENT: ALL LINES TAB (flat view with filters)
# =============================================================================

@st.fragment
def po_all_lines_fragment(result: POSuggestionResult):
    """Fragment: Filterable flat PO lines table with pagination."""
    if not result.has_lines():
        st.info("No PO lines — run PO planning first")
        return

    metrics = result.get_summary()

    # Filter controls
    fc1, fc2, fc3, fc4 = st.columns([1, 1, 2, 1])

    with fc1:
        source_opts = {
            'all': f"All ({metrics['total_po_lines']})",
            'fg': f"🛒 FG ({metrics['fg_lines']})",
            'raw': f"🧪 Raw ({metrics['raw_lines']})",
        }
        source_filter = st.selectbox(
            "Source", list(source_opts.keys()),
            format_func=lambda x: source_opts[x],
            key="po_source_filter"
        )

    with fc2:
        dist = result.get_urgency_distribution()
        urgency_opts = {'all': 'All Urgency'}
        for lvl in ['overdue', 'critical', 'urgent']:
            key_upper = lvl.upper()
            cnt = dist.get(key_upper, 0)
            if cnt > 0:
                cfg = URGENCY_LEVELS.get(key_upper, {})
                urgency_opts[lvl] = f"{cfg.get('icon', '')} {cfg.get('label', lvl)} ({cnt})"
        urgency_filter = st.selectbox(
            "Urgency", list(urgency_opts.keys()),
            format_func=lambda x: urgency_opts[x],
            key="po_urgency_filter"
        )

    with fc3:
        vendors = [(None, 'All Vendors')]
        for vid, grp in result.vendor_groups.items():
            vendors.append((vid, f"{grp.vendor_name} ({grp.total_lines})"))
        vendor_filter = st.selectbox(
            "Vendor",
            [v[0] for v in vendors],
            format_func=lambda x: dict(vendors)[x],
            key="po_vendor_filter"
        )

    with fc4:
        ipp = st.selectbox(
            "Per page",
            PO_PLANNING_UI['items_per_page_options'],
            index=1,
            key="po_ipp"
        )

    # Page state
    page_key = 'po_lines_page'
    current_page = st.session_state.get(page_key, 1)

    page_info = render_po_lines_table(
        result,
        filter_source=source_filter,
        filter_urgency=urgency_filter,
        filter_vendor=vendor_filter,
        items_per_page=ipp,
        current_page=current_page,
        table_key="po_lines_tbl",
    )

    if page_info and page_info.get('total_pages', 1) > 1:
        new_page = render_pagination(
            page_info['page'], page_info['total_pages'], 'po_lines'
        )
        if new_page != page_info['page']:
            st.session_state[page_key] = new_page
            st.rerun(scope="fragment")


# =============================================================================
# FRAGMENT: COVERAGE & PRICING TAB
# =============================================================================

@st.fragment
def po_coverage_fragment(result: POSuggestionResult):
    """Fragment: Price source coverage and vendor reliability analysis."""
    lines_df = result.get_all_lines_df()
    if lines_df.empty:
        st.info("No data")
        return

    # Price source breakdown
    st.markdown("##### 📗 Price Source Coverage")
    source_counts = lines_df['price_source'].value_counts()
    c1, c2, c3 = st.columns(3)
    for i, (src, count) in enumerate(source_counts.items()):
        cfg = PRICE_SOURCE.get(src, {})
        with [c1, c2, c3][i % 3]:
            st.metric(
                f"{cfg.get('icon', '')} {cfg.get('label', src)}",
                f"{count} lines"
            )

    st.divider()

    # Vendor reliability breakdown
    st.markdown("##### 📊 Vendor Reliability")
    if 'vendor_reliability' in lines_df.columns:
        rel_counts = lines_df.groupby('vendor_reliability').agg(
            lines=('product_id', 'count'),
            value=('line_value_usd', 'sum'),
        ).reset_index()

        rel_order = ['RELIABLE', 'AVERAGE', 'UNRELIABLE', 'UNKNOWN']
        rel_icons = {'RELIABLE': '✅', 'AVERAGE': '⚠️', 'UNRELIABLE': '🔴', 'UNKNOWN': '❓'}

        for _, row in rel_counts.iterrows():
            rel = row['vendor_reliability']
            icon = rel_icons.get(rel, '')
            st.markdown(
                f"- {icon} **{rel}**: {int(row['lines'])} lines, ${row['value']:,.0f}"
            )

    st.divider()

    # MOQ/SPQ impact
    st.markdown("##### 📦 MOQ/SPQ Impact")
    moq_applied = lines_df['moq_applied'].sum()
    spq_applied = lines_df['spq_applied'].sum()
    total_excess = lines_df['excess_qty'].sum()

    c1, c2, c3 = st.columns(3)
    c1.metric("MOQ Applied", f"{int(moq_applied)} lines")
    c2.metric("SPQ Rounded", f"{int(spq_applied)} lines")
    c3.metric("Total Excess", f"{total_excess:,.0f} units")

    # Lines where MOQ caused significant excess
    if moq_applied > 0:
        high_excess = lines_df[
            (lines_df['moq_applied']) &
            (lines_df['excess_qty'] > lines_df['net_shortage_qty'])
        ]
        if not high_excess.empty:
            st.caption(
                f"⚠️ {len(high_excess)} lines where MOQ > 2× actual need — "
                f"consider negotiating smaller MOQ with vendor"
            )