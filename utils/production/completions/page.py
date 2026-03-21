# utils/production/completions/page.py
"""
Main UI orchestrator for Production Receipts domain
Renders the Production Receipts tab with unified metrics, filters, and receipts list

Version: 4.2.0
Changes:
- v4.2.0: Dialog-based UI — eliminates full-page view switching
  - Record Output / Close Order open as @st.dialog overlays
  - No more completions_view state, no "Back to Receipts" navigation
  - Receipts page always renders — dialogs overlay on top
  - Removed _render_close_order_view (moved to dialogs.py)
- v4.1.0: Filter & Performance improvements
  - Added date type filter: receipt_date, order_date, scheduled_date
  - Added custom date range with date pickers alongside presets
  - Show date label (dd/mm — dd/mm) when preset selected
  - Cached lookup queries (products, warehouses) with TTL
  - Cached live_stats and ready_to_close with short TTL
- v4.0.0: Production Receipts refactoring
"""

import logging
from datetime import date
from typing import Dict, Any

import streamlit as st
import pandas as pd

from .queries import CompletionQueries
from .dialogs import (
    show_receipt_details_dialog, show_update_quality_dialog,
    show_pdf_dialog, show_close_order_dialog,
    show_close_order_select_dialog, check_pending_dialogs
)
from .help_guide import render_help_guide
from .common import (
    format_number, create_status_indicator, get_yield_indicator,
    calculate_percentage, format_datetime_vn, get_vietnam_today,
    export_to_excel, get_date_filter_presets, CompletionConstants,
    format_product_display, get_aging_indicator, format_date
)

logger = logging.getLogger(__name__)


# ==================== Cached Lookups (Performance) ====================

@st.cache_data(ttl=300, show_spinner=False)
def _cached_get_products() -> pd.DataFrame:
    """Cache product dropdown options — TTL 5 min"""
    return CompletionQueries().get_products()


@st.cache_data(ttl=300, show_spinner=False)
def _cached_get_warehouses() -> pd.DataFrame:
    """Cache warehouse dropdown options — TTL 5 min"""
    return CompletionQueries().get_warehouses()


@st.cache_data(ttl=30, show_spinner=False)
def _cached_get_live_stats() -> Dict[str, int]:
    """Cache header KPIs — TTL 30s"""
    return CompletionQueries().get_live_stats()


@st.cache_data(ttl=30, show_spinner=False)
def _cached_get_ready_to_close() -> Dict[str, Any]:
    """Cache ready-to-close banner data — TTL 30s"""
    return CompletionQueries().get_ready_to_close_orders()


# ==================== Session State ====================

def _init_session_state():
    """Initialize session state for completions tab"""
    defaults = {
        'completions_page': 1,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


# ==================== Helper Functions ====================

def _format_product_display_row(row) -> str:
    """Format product display for DataFrame row (apply() usage)"""
    return format_product_display(row.to_dict() if hasattr(row, 'to_dict') else dict(row))


def _format_date_display(dt, fmt: str = '%d-%b-%Y') -> str:
    """Format date for display"""
    if pd.isna(dt) or dt is None:
        return ''
    try:
        if isinstance(dt, str):
            from datetime import datetime
            dt = datetime.strptime(dt, '%Y-%m-%d')
        return dt.strftime(fmt)
    except Exception:
        return str(dt)[:10] if dt else ''


# ==================== Header ====================

def _render_header(queries: CompletionQueries):
    """
    Page header with title and live operational stats.
    Renders ONCE outside fragment — not affected by filter/pagination.
    Shows real-time KPIs: In Progress orders + Today's receipts + Ready to close.
    Uses cached stats for performance.
    """
    stats = _cached_get_live_stats()

    col1, col2 = st.columns([2, 1])
    with col1:
        st.subheader("📦 Production Receipts")
    with col2:
        ready = stats.get('ready_to_close', 0)
        ready_badge = f" · 🔒 <b>{ready}</b> ready to close" if ready > 0 else ""
        st.markdown(
            f"<div style='text-align:right; padding-top:10px; font-size:0.9em;'>"
            f"🔄 <b>{stats['in_progress']}</b> in progress &nbsp;·&nbsp; "
            f"📅 <b>{stats['today_count']}</b> today"
            f"{ready_badge}"
            f"</div>",
            unsafe_allow_html=True
        )


# ==================== Help ====================

def _render_help_button():
    """Render help button that opens the full user guide dialog."""
    if st.button("📚 Help", width='stretch', key="btn_help_guide"):
        render_help_guide()


# ==================== Date Type Options ====================

DATE_TYPE_OPTIONS = {
    'receipt_date': '📦 Receipt Date',
    'order_date': '📋 Order Date',
    'scheduled_date': '📅 Scheduled Date',
}


# ==================== Filter Bar ====================

def _render_filter_bar(queries: CompletionQueries) -> Dict[str, Any]:
    """Render filter bar with date type, preset/custom range, and cached lookups"""
    presets = get_date_filter_presets()
    preset_keys = list(presets.keys()) + ["Custom"]

    with st.expander("🔍 Filters", expanded=False):
        # Row 1: Date Type + Date Range (preset or custom)
        col1, col2, col3, col4 = st.columns([1.2, 1.2, 1, 1])

        with col1:
            date_type = st.selectbox(
                "Date Type",
                options=list(DATE_TYPE_OPTIONS.keys()),
                format_func=lambda x: DATE_TYPE_OPTIONS[x],
                key="completion_date_type"
            )

        with col2:
            date_range = st.selectbox(
                "Date Range",
                options=preset_keys,
                index=6,  # Last 30 Days
                key="completion_date_range"
            )

        is_custom = (date_range == "Custom")

        if is_custom:
            today = get_vietnam_today()
            with col3:
                from_date = st.date_input(
                    "From",
                    value=today.replace(day=1),
                    key="completion_custom_from"
                )
            with col4:
                to_date = st.date_input(
                    "To",
                    value=today,
                    key="completion_custom_to"
                )
        else:
            from_date, to_date = presets[date_range]
            # Show date label for preset
            with col3:
                st.markdown(
                    f"<div style='padding-top:28px; font-size:0.85em; color:#666;'>"
                    f"📅 {format_date(from_date, '%d/%m/%Y')} — {format_date(to_date, '%d/%m/%Y')}"
                    f"</div>",
                    unsafe_allow_html=True
                )

        # Row 2: Quality, Product, Warehouse
        col1, col2, col3 = st.columns(3)

        with col1:
            quality_options = ['All'] + [q[0] for q in CompletionConstants.QUALITY_STATUSES]
            quality_status = st.selectbox(
                "Quality Status",
                options=quality_options,
                key="completion_quality_filter"
            )

        with col2:
            products = _cached_get_products()
            product_options = (
                ["All Products"] + products['name'].tolist()
                if not products.empty else ["All Products"]
            )
            selected_product = st.selectbox(
                "Product", options=product_options,
                key="completion_product_filter"
            )
            product_id = None
            if selected_product != "All Products" and not products.empty:
                product_id = int(products[products['name'] == selected_product]['id'].iloc[0])

        with col3:
            warehouses = _cached_get_warehouses()
            warehouse_options = (
                ["All Warehouses"] + warehouses['name'].tolist()
                if not warehouses.empty else ["All Warehouses"]
            )
            selected_warehouse = st.selectbox(
                "Warehouse", options=warehouse_options,
                key="completion_warehouse_filter"
            )
            warehouse_id = None
            if selected_warehouse != "All Warehouses" and not warehouses.empty:
                warehouse_id = int(warehouses[warehouses['name'] == selected_warehouse]['id'].iloc[0])

        # Row 3: Text search + show completed toggle
        col5, col6, col7 = st.columns([2, 2, 1])
        with col5:
            order_no = st.text_input(
                "🔍 Order No",
                placeholder="Search by order number...",
                key="completion_order_filter"
            )
        with col6:
            batch_no = st.text_input(
                "🔍 Batch No",
                placeholder="Search by batch number...",
                key="completion_batch_filter"
            )
        with col7:
            st.markdown("<div style='padding-top:20px'></div>", unsafe_allow_html=True)
            show_completed = st.checkbox(
                "Show completed",
                value=False,
                key="completion_show_completed",
                help="Include receipts from COMPLETED manufacturing orders"
            )

    return {
        'from_date': from_date,
        'to_date': to_date,
        'date_field': date_type,
        'quality_status': quality_status if quality_status != 'All' else None,
        'product_id': product_id,
        'warehouse_id': warehouse_id,
        'order_no': order_no if order_no else None,
        'batch_no': batch_no if batch_no else None,
        'exclude_completed': not show_completed
    }


# ==================== Receipts Section (Fragment) ====================

@st.fragment
def _render_receipts_section(queries: CompletionQueries):
    """
    Fragment: filters + action bar + unified metrics + table.
    Reruns INDEPENDENTLY from the header.
    """
    filters = _render_filter_bar(queries)
    _render_action_bar(queries, filters)
    _render_receipts_list(queries, filters)


# ==================== Action Bar ====================

def _render_action_bar(queries: CompletionQueries, filters: Dict[str, Any]):
    """Render action bar with help popover"""
    col1, col2, col3, col4, col5 = st.columns([1, 1, 1, 1, 1])

    with col1:
        if st.button("📦 Record Output", type="primary", width='stretch',
                      key="btn_record_output"):
            st.session_state['open_record_output_dialog'] = True
            st.rerun()

    with col2:
        if st.button("🔒 Close Order", width='stretch',
                      key="btn_close_order"):
            st.session_state['open_close_order_select_dialog'] = True
            st.rerun()

    with col3:
        if st.button("📊 Export Excel", width='stretch',
                      key="btn_export_receipts"):
            _export_receipts_excel(queries, filters)

    with col4:
        if st.button("🔄 Refresh", width='stretch',
                      key="btn_refresh_completions"):
            # Clear cached lookups to force fresh data
            _cached_get_products.clear()
            _cached_get_warehouses.clear()
            _cached_get_live_stats.clear()
            _cached_get_ready_to_close.clear()
            st.rerun()

    with col5:
        _render_help_button()


# ==================== Unified Metrics ====================

def _render_metrics(stats: Dict[str, Any], avg_yield: float):
    """
    Single unified metrics row — replaces both dashboard metrics
    and receipts list summary + quality breakdown.
    Stats for ALL filtered data (not just current page).
    """
    with st.container(border=True):
        c1, c2, c3, c4, c5, c6 = st.columns(6)

        with c1:
            st.metric("📦 Receipts", format_number(stats['total_count'], 0))

        with c2:
            st.metric("📊 Quantity", format_number(stats['total_quantity'], 0))

        with c3:
            st.metric(
                "✅ Passed",
                format_number(stats['passed_count'], 0),
                delta=f"{stats['pass_rate']}%",
                delta_color="off"
            )

        with c4:
            pending = stats['pending_count']
            st.metric(
                "⏳ Pending",
                format_number(pending, 0),
                delta="needs QC" if pending > 0 else None,
                delta_color="off"
            )

        with c5:
            st.metric(
                "❌ Failed",
                format_number(stats['failed_count'], 0),
            )

        with c6:
            yield_indicator = get_yield_indicator(avg_yield) if avg_yield > 0 else ""
            st.metric(
                "📈 Yield",
                f"{avg_yield:.1f}% {yield_indicator}" if avg_yield > 0 else "N/A"
            )


# ==================== Ready-to-Close Banner ====================

def _render_ready_to_close_banner(queries: CompletionQueries):
    """Render banner showing orders ready to close or blocked by pending QC."""
    ready_info = _cached_get_ready_to_close()
    
    if ready_info['ready_count'] > 0:
        orders_text = ", ".join(
            o['order_no'] for o in ready_info['ready_orders'][:5]
        )
        if ready_info['ready_count'] > 5:
            orders_text += f" +{ready_info['ready_count'] - 5} more"
        
        st.success(
            f"✅ **{ready_info['ready_count']} order(s) ready to close** — "
            f"production target met, all QC resolved. "
            f"({orders_text})"
        )
    
    if ready_info['blocked_count'] > 0:
        st.warning(
            f"⏳ **{ready_info['blocked_count']} order(s) met target but have pending QC** — "
            f"resolve QC before closing."
        )


# ==================== Data Warnings ====================

def _compute_warnings(receipts: pd.DataFrame,
                      queries: CompletionQueries) -> pd.Series:
    """
    Compute warning flags for each receipt row.
    Returns Series of warning emoji strings aligned with receipts index.
    Includes aging indicators for PENDING receipts.
    """
    today = pd.Timestamp(get_vietnam_today())

    batch_list = receipts['batch_no'].dropna().tolist()
    dup_batches = queries.get_duplicate_batch_info(batch_list)

    def _row_warnings(row):
        warnings = []
        if row.get('batch_no') and row['batch_no'] in dup_batches:
            warnings.append('🔁')
        if pd.notna(row.get('expired_date')):
            if pd.Timestamp(row['expired_date']) < today:
                warnings.append('📅')
        if row.get('yield_rate', 0) > 100:
            warnings.append('📈')
        if row.get('quality_status') == 'PENDING':
            age_days = row.get('age_days')
            aging_icon = get_aging_indicator(age_days) if pd.notna(age_days) else ''
            if aging_icon:
                warnings.append(aging_icon)
            else:
                warnings.append('⏳')
        if row.get('order_status') == 'COMPLETED':
            warnings.append('🔒')
        return ' '.join(warnings)

    return receipts.apply(_row_warnings, axis=1)


def _render_warnings_summary(warnings_col: pd.Series):
    """Render compact warning summary above the receipts table."""
    if warnings_col.str.len().sum() == 0:
        return

    counts = {
        '🔁': (warnings_col.str.contains('🔁', na=False).sum(), 'duplicate batch'),
        '📅': (warnings_col.str.contains('📅', na=False).sum(), 'expired'),
        '📈': (warnings_col.str.contains('📈', na=False).sum(), 'overproduction'),
        '⏳': (warnings_col.str.contains('⏳', na=False).sum(), 'pending QC'),
    }

    parts = [f"{e} {c} {l}" for e, (c, l) in counts.items() if c > 0]
    total_affected = (warnings_col.str.len() > 0).sum()

    st.warning(
        f"**⚠️ {total_affected} receipt(s) have warnings:** {' · '.join(parts)}"
    )


# ==================== Receipts List ====================

def _render_receipts_list(queries: CompletionQueries, filters: Dict[str, Any]):
    """
    Render unified metrics + receipts table.

    Layout:
    1. Metrics row (from get_filtered_stats — all filtered data)
    2. Warnings bar (from current page data)
    3. Table (current page data)
    4. Selected row actions
    5. Pagination
    """
    page_size = CompletionConstants.DEFAULT_PAGE_SIZE
    page = st.session_state.completions_page
    exclude_completed = filters.get('exclude_completed', True)
    date_field = filters.get('date_field', 'receipt_date')

    # Ready-to-close banner
    _render_ready_to_close_banner(queries)

    # Get current page data
    receipts = queries.get_receipts(
        from_date=filters['from_date'],
        to_date=filters['to_date'],
        quality_status=filters['quality_status'],
        product_id=filters['product_id'],
        warehouse_id=filters['warehouse_id'],
        order_no=filters['order_no'],
        batch_no=filters['batch_no'],
        exclude_completed=exclude_completed,
        date_field=date_field,
        page=page,
        page_size=page_size
    )

    # Connection error check
    if receipts is None:
        error_msg = queries.get_last_error() or "Cannot connect to database"
        st.error(f"🔌 **Database Connection Error**\n\n{error_msg}")
        st.info("💡 Check VPN/network connection or contact IT support")
        return

    # Get stats for ALL filtered data (single query, not just current page)
    stats = queries.get_filtered_stats(
        from_date=filters['from_date'],
        to_date=filters['to_date'],
        quality_status=filters['quality_status'],
        product_id=filters['product_id'],
        warehouse_id=filters['warehouse_id'],
        order_no=filters['order_no'],
        batch_no=filters['batch_no'],
        exclude_completed=exclude_completed,
        date_field=date_field
    )

    total_count = stats['total_count']

    # Empty data check
    if receipts.empty:
        st.info("📭 No production receipts found matching the filters")
        return

    # Avg yield from current page (order-level metric)
    avg_yield = receipts['yield_rate'].mean() if not receipts.empty else 0

    # ── Unified Metrics ──
    _render_metrics(stats, avg_yield)

    # ── Warnings ──
    warnings_col = _compute_warnings(receipts, queries)
    _render_warnings_summary(warnings_col)

    # ── Table ──
    st.markdown("### 📋 Receipts List")

    if 'completions_selected_idx' not in st.session_state:
        st.session_state.completions_selected_idx = None

    display_df = receipts.copy()
    display_df['alerts'] = warnings_col

    # Single selection
    display_df['Select'] = False
    if (st.session_state.completions_selected_idx is not None
            and st.session_state.completions_selected_idx < len(display_df)):
        display_df.loc[st.session_state.completions_selected_idx, 'Select'] = True

    # Format columns
    display_df['receipt_date_display'] = display_df['receipt_date'].apply(
        lambda x: format_datetime_vn(x, '%d-%b-%Y')
    )
    display_df['order_date_display'] = display_df['order_date'].apply(
        lambda x: _format_date_display(x, '%d-%b-%Y')
    )
    display_df['scheduled_date_display'] = display_df['scheduled_date'].apply(
        lambda x: _format_date_display(x, '%d-%b-%Y')
    )
    display_df['product_display'] = display_df.apply(_format_product_display_row, axis=1)
    display_df['quality_display'] = display_df['quality_status'].apply(create_status_indicator)
    display_df['yield_display'] = display_df['yield_rate'].apply(
        lambda x: f"{x:.1f}% {get_yield_indicator(x)}"
    )
    display_df['qty_display'] = display_df.apply(
        lambda x: f"{format_number(x['quantity'], 0)} {x['uom']}", axis=1
    )

    edited_df = st.data_editor(
        display_df[[
            'Select', 'alerts', 'receipt_no', 'receipt_date_display', 'order_date_display',
            'scheduled_date_display', 'order_no', 'product_display', 'qty_display',
            'batch_no', 'quality_display', 'yield_display', 'warehouse_name'
        ]].rename(columns={
            'alerts': '⚠️',
            'receipt_no': 'Receipt No',
            'receipt_date_display': 'Receipt Date',
            'order_date_display': 'Order Date',
            'scheduled_date_display': 'Scheduled Date',
            'order_no': 'Order No',
            'product_display': 'Product',
            'qty_display': 'Quantity',
            'batch_no': 'Batch',
            'quality_display': 'Quality',
            'yield_display': 'Yield',
            'warehouse_name': 'Warehouse'
        }),
        width='stretch',
        hide_index=True,
        disabled=['⚠️', 'Receipt No', 'Receipt Date', 'Order Date', 'Scheduled Date', 'Order No',
                  'Product', 'Quantity', 'Batch', 'Quality', 'Yield', 'Warehouse'],
        column_config={
            'Select': st.column_config.CheckboxColumn(
                '✓', help='Select row', default=False, width='small'
            ),
            '⚠️': st.column_config.TextColumn(
                '⚠️',
                help='🔁 Duplicate · 📅 Expired · 📈 Over · ⏳ QC',
                width='small'
            ),
            'Product': st.column_config.TextColumn(
                'Product', help='pt_code | name (package_size)', width='large'
            )
        },
        key="completions_table_editor"
    )

    # Handle single selection
    selected_indices = edited_df[edited_df['Select'] == True].index.tolist()

    if selected_indices:
        if len(selected_indices) > 1:
            new_selection = [idx for idx in selected_indices
                            if idx != st.session_state.completions_selected_idx]
            if new_selection:
                st.session_state.completions_selected_idx = new_selection[0]
                st.rerun(scope="fragment")
        else:
            st.session_state.completions_selected_idx = selected_indices[0]
    else:
        st.session_state.completions_selected_idx = None

    # Action buttons for selected row
    if st.session_state.completions_selected_idx is not None:
        selected_receipt = receipts.iloc[st.session_state.completions_selected_idx]

        st.markdown("---")
        product_info = format_product_display(selected_receipt.to_dict())
        qc_status = create_status_indicator(selected_receipt['quality_status'])
        order_status = selected_receipt.get('order_status', '')
        
        st.markdown(
            f"**Selected:** `{selected_receipt['receipt_no']}` "
            f"| {selected_receipt['order_no']} | {product_info} | {qc_status}"
        )

        # Check if QC update is allowed
        can_update_qc = (
            selected_receipt['quality_status'] == 'PENDING'
            and order_status != 'COMPLETED'
        )
        
        qc_help = ""
        if order_status == 'COMPLETED':
            qc_help = "🔒 Order is COMPLETED — QC locked"
        elif selected_receipt['quality_status'] != 'PENDING':
            qc_help = f"🔒 QC is {selected_receipt['quality_status']} — final"

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            if st.button("👁️ View Details", type="primary",
                         width='stretch', key="btn_view_receipt"):
                show_receipt_details_dialog(selected_receipt['id'])

        with col2:
            if can_update_qc:
                if st.button("✏️ Update Quality",
                             width='stretch', key="btn_update_quality"):
                    show_update_quality_dialog(selected_receipt['id'])
            else:
                st.button("🔒 QC Locked",
                         width='stretch', key="btn_update_quality",
                         disabled=True, help=qc_help)

        with col3:
            if st.button("📄 Export PDF",
                         width='stretch', key="btn_pdf_receipt"):
                show_pdf_dialog(selected_receipt['id'], selected_receipt['receipt_no'])
    else:
        st.info("💡 Tick checkbox to select a receipt and perform actions")

    # Pagination
    st.markdown("---")
    total_pages = max(1, (total_count + page_size - 1) // page_size)

    col1, col2, col3 = st.columns([1, 2, 1])

    with col1:
        if st.button("⬅️ Previous", disabled=page <= 1, key="btn_prev_receipt"):
            st.session_state.completions_page = max(1, page - 1)
            st.session_state.completions_selected_idx = None
            st.rerun(scope="fragment")

    with col2:
        st.markdown(
            f"<div style='text-align:center'>"
            f"Page {page} of {total_pages} · {total_count} receipts total"
            f"</div>",
            unsafe_allow_html=True
        )

    with col3:
        if st.button("Next ➡️", disabled=page >= total_pages, key="btn_next_receipt"):
            st.session_state.completions_page = page + 1
            st.session_state.completions_selected_idx = None
            st.rerun(scope="fragment")


# ==================== Excel Export ====================

def _export_receipts_excel(queries: CompletionQueries, filters: Dict[str, Any]):
    """Export receipts to Excel"""
    with st.spinner("Exporting..."):
        receipts = queries.get_receipts(
            from_date=filters['from_date'],
            to_date=filters['to_date'],
            quality_status=filters['quality_status'],
            product_id=filters['product_id'],
            warehouse_id=filters['warehouse_id'],
            order_no=filters['order_no'],
            batch_no=filters['batch_no'],
            exclude_completed=filters.get('exclude_completed', True),
            date_field=filters.get('date_field', 'receipt_date'),
            page=1,
            page_size=10000
        )

        if receipts is None or receipts.empty:
            st.warning("No receipts to export")
            return

        export_df = receipts.copy()
        export_df['Product'] = export_df.apply(_format_product_display_row, axis=1)
        export_df['Receipt Date'] = export_df['receipt_date'].apply(
            lambda x: format_datetime_vn(x, '%d/%m/%Y %H:%M') if pd.notna(x) else ''
        )
        export_df['Order Date'] = export_df['order_date'].apply(
            lambda x: _format_date_display(x, '%d/%m/%Y') if pd.notna(x) else ''
        )
        export_df['Scheduled Date'] = export_df['scheduled_date'].apply(
            lambda x: _format_date_display(x, '%d/%m/%Y') if pd.notna(x) else ''
        )

        export_df = export_df[[
            'receipt_no', 'Receipt Date', 'Order Date', 'Scheduled Date', 'order_no',
            'Product', 'pt_code', 'legacy_pt_code', 'brand_name', 'quantity', 'uom',
            'batch_no', 'quality_status', 'yield_rate', 'warehouse_name'
        ]].copy()

        export_df.columns = [
            'Receipt No', 'Receipt Date', 'Order Date', 'Scheduled Date', 'Order No',
            'Product (Full)', 'PT Code', 'Legacy Code', 'Brand', 'Quantity', 'UOM',
            'Batch', 'Quality Status', 'Yield Rate', 'Warehouse'
        ]

        excel_data = export_to_excel(export_df)
        filename = f"Production_Receipts_{get_vietnam_today().strftime('%Y%m%d')}.xlsx"

        st.download_button(
            label="💾 Download Excel",
            data=excel_data,
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_receipts_excel"
        )


# ==================== Main Render Function ====================

def render_completions_tab():
    """
    Main function to render the Production Receipts tab.

    Layout v4.2 (dialog-based):
    ┌──────────────────────────────────┐
    │  Header + Live Badges            │  ← renders once
    ├──────────────────────────────────┤
    │  @st.fragment                    │
    │  ┌────────────────────────────┐  │
    │  │ Filters (+ show completed) │  │
    │  │ Action Bar (Record/Close)  │  │  ← fragment reruns independently
    │  │ Ready-to-Close Banner      │  │
    │  │ Unified Metrics (6 cols)   │  │  Record Output / Close Order
    │  │ Warnings Bar               │  │  open as @st.dialog overlays
    │  │ Receipts Table + Actions   │  │  — no page navigation needed
    │  │ Pagination                 │  │
    │  └────────────────────────────┘  │
    └──────────────────────────────────┘
    """
    _init_session_state()
    check_pending_dialogs()

    queries = CompletionQueries()

    # Always render: Header (once) + Fragment (interactive)
    _render_header(queries)
    _render_receipts_section(queries)