# utils/production/completions/page.py
"""
Main UI orchestrator for Production Receipts domain
Renders the Production Receipts tab with unified metrics, filters, and receipts list

Version: 5.1.0
Changes:
- v5.1.0: Allow under-production MO completion
  - Ready-to-close banner differentiates target-met vs under-target orders
  - Blocked banner text simplified (no longer implies target must be met)
- v5.0.1: Fix dialog-opening buttons inside @st.fragment
  - st.rerun() inside @st.fragment defaults to scope="fragment" (Streamlit ≥1.37)
  - check_pending_dialogs() runs at page-level → needs scope="app" to trigger
  - Fixed: Production Receipt, Complete MO, Refresh buttons now use st.rerun(scope="app")
- v5.0.0: Client-side filtering — MAJOR performance overhaul
  - Single bulk DB query replaces per-page get_receipts + get_filtered_stats + get_duplicate_batch_info
  - All filtering, pagination, stats computed client-side with pandas (zero DB round-trips)
  - Dialog buttons use st.rerun(scope="app") to trigger page-level check_pending_dialogs()
  - PerformanceTimer instrumentation throughout for profiling
- v4.2.0: Dialog-based UI — eliminates full-page view switching
- v4.1.0: Filter & Performance improvements
- v4.0.0: Production Receipts refactoring
"""

import logging
from datetime import date
from typing import Dict, Any, Optional, Tuple

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
    format_product_display, get_aging_indicator, format_date,
    PerformanceTimer
)

logger = logging.getLogger(__name__)


# ==================== Parallel Bootstrap Cache ====================
# Single cache entry replaces 6 individual DB queries.
# On cache miss: 2 parallel queries (~185ms) instead of 6 sequential (~1050ms).
# On cache hit: 0ms (pure dict lookup).

@st.cache_data(ttl=30, show_spinner=False)
def _cached_bootstrap(_include_completed: bool) -> Dict[str, Any]:
    """
    Load ALL page data in one cached call.
    Internally runs 2 queries in parallel via ThreadPoolExecutor.
    
    Returns dict with:
    - 'receipts': DataFrame (all active receipts)
    - 'header': {'live_stats': {...}, 'ready_to_close': {...}}
    - 'connection_error': str or None
    """
    return CompletionQueries().bootstrap_all(include_completed=_include_completed)


# ==================== Client-Side Derived Data ====================
# Products, warehouses, and duplicate batches extracted from bulk receipts.
# Zero extra DB queries.

def _derive_products(receipts: pd.DataFrame) -> pd.DataFrame:
    """Extract unique products from receipts DataFrame — replaces get_products() query"""
    if receipts is None or receipts.empty:
        return pd.DataFrame(columns=['id', 'name', 'pt_code', 'package_size'])
    
    products = receipts[['product_id', 'product_name', 'pt_code', 'package_size']].drop_duplicates(
        subset=['product_id']
    ).rename(columns={'product_id': 'id', 'product_name': 'name'})
    
    return products.sort_values('name').reset_index(drop=True)


def _derive_warehouses(receipts: pd.DataFrame) -> pd.DataFrame:
    """Extract unique warehouses from receipts DataFrame — replaces get_warehouses() query"""
    if receipts is None or receipts.empty:
        return pd.DataFrame(columns=['id', 'name'])
    
    warehouses = receipts[['warehouse_id', 'warehouse_name']].drop_duplicates(
        subset=['warehouse_id']
    ).rename(columns={'warehouse_id': 'id', 'warehouse_name': 'name'})
    
    return warehouses.sort_values('name').reset_index(drop=True)


def _derive_duplicate_batches(receipts: pd.DataFrame) -> Dict[str, int]:
    """
    Compute duplicate batches from receipts DataFrame — replaces get_all_duplicate_batches() query.
    Returns {batch_no: order_count} for batches appearing in >1 MO.
    """
    if receipts is None or receipts.empty:
        return {}
    
    batch_orders = receipts.dropna(subset=['batch_no']).groupby('batch_no')['order_id'].nunique()
    dups = batch_orders[batch_orders > 1]
    return dups.to_dict()


# ==================== Client-Side Filter Engine ====================

def _apply_filters(df: pd.DataFrame, filters: Dict[str, Any]) -> pd.DataFrame:
    """
    Apply all filters client-side using pandas.
    Replaces server-side WHERE clauses in get_receipts().
    
    Returns:
        Filtered DataFrame (not paginated — full result set)
    """
    if df is None or df.empty:
        return pd.DataFrame()
    
    result = df.copy()
    
    # Date filter
    date_field = filters.get('date_field', 'receipt_date')
    from_date = filters.get('from_date')
    to_date = filters.get('to_date')
    
    if date_field and from_date and to_date:
        # Map filter field to DataFrame column
        col_map = {
            'receipt_date': 'receipt_date',
            'order_date': 'order_date',
            'scheduled_date': 'scheduled_date',
        }
        col_name = col_map.get(date_field, 'receipt_date')
        
        if col_name in result.columns:
            dt_col = pd.to_datetime(result[col_name], errors='coerce')
            from_ts = pd.Timestamp(from_date)
            to_ts = pd.Timestamp(to_date) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
            result = result[dt_col.between(from_ts, to_ts)]
    
    # Quality status
    quality_status = filters.get('quality_status')
    if quality_status:
        result = result[result['quality_status'] == quality_status]
    
    # Product
    product_id = filters.get('product_id')
    if product_id:
        result = result[result['product_id'] == product_id]
    
    # Warehouse
    warehouse_id = filters.get('warehouse_id')
    if warehouse_id:
        result = result[result['warehouse_id'] == warehouse_id]
    
    # Order No (LIKE)
    order_no = filters.get('order_no')
    if order_no:
        result = result[result['order_no'].str.contains(order_no, case=False, na=False)]
    
    # Batch No (LIKE)
    batch_no = filters.get('batch_no')
    if batch_no:
        result = result[result['batch_no'].str.contains(batch_no, case=False, na=False)]
    
    return result


def _compute_stats_client(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Compute summary statistics from filtered DataFrame.
    Replaces get_filtered_stats() DB query.
    """
    if df.empty:
        return {
            'total_count': 0, 'total_quantity': 0,
            'passed_count': 0, 'pending_count': 0, 'failed_count': 0,
            'passed_qty': 0, 'pending_qty': 0, 'failed_qty': 0,
            'pass_rate': 0,
        }
    
    total = len(df)
    passed = int((df['quality_status'] == 'PASSED').sum())
    pending = int((df['quality_status'] == 'PENDING').sum())
    failed = int((df['quality_status'] == 'FAILED').sum())
    
    total_qty = float(df['quantity'].sum())
    passed_qty = float(df.loc[df['quality_status'] == 'PASSED', 'quantity'].sum())
    pending_qty = float(df.loc[df['quality_status'] == 'PENDING', 'quantity'].sum())
    failed_qty = float(df.loc[df['quality_status'] == 'FAILED', 'quantity'].sum())
    
    return {
        'total_count': total,
        'total_quantity': total_qty,
        'passed_count': passed,
        'pending_count': pending,
        'failed_count': failed,
        'passed_qty': passed_qty,
        'pending_qty': pending_qty,
        'failed_qty': failed_qty,
        'pass_rate': round((passed / total * 100) if total > 0 else 0, 1),
    }


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

def _render_header_from_data(stats: Dict[str, Any]):
    """
    Page header with title and live operational stats.
    v5.0: Accepts pre-loaded stats from bootstrap — no DB call.
    """
    col1, col2 = st.columns([2, 1])
    with col1:
        st.subheader("📦 Production Receipts")
    with col2:
        ready = stats.get('ready_to_close', 0)
        ready_badge = f" · 🔒 <b>{ready}</b> ready to complete" if ready > 0 else ""
        st.markdown(
            f"<div style='text-align:right; padding-top:10px; font-size:0.9em;'>"
            f"🔄 <b>{stats.get('in_progress', 0)}</b> in progress &nbsp;·&nbsp; "
            f"📅 <b>{stats.get('today_count', 0)}</b> today"
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

def _render_filter_bar(all_receipts: Optional[pd.DataFrame]) -> Dict[str, Any]:
    """Render filter bar — products/warehouses derived from DataFrame (zero DB queries)"""
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
            products = _derive_products(all_receipts)
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
            warehouses = _derive_warehouses(all_receipts)
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
def _render_receipts_section(boot: Dict[str, Any]):
    """
    Fragment: filters + action bar + unified metrics + table.
    Reruns INDEPENDENTLY from the header.
    
    v5.0: Receives pre-loaded bootstrap data. On fragment rerun,
    _cached_bootstrap() is a cache hit (0ms) — no DB calls.
    """
    perf = PerformanceTimer("receipts_fragment")
    
    # On fragment rerun, re-fetch from cache (0ms cache hit)
    include_completed = st.session_state.get('completion_show_completed', False)
    with perf.step("bootstrap_refetch", "should be cache hit"):
        boot = _cached_bootstrap(include_completed)
    
    all_receipts = boot.get('receipts')
    
    with perf.step("render_filters"):
        filters = _render_filter_bar(all_receipts)
    
    with perf.step("render_action_bar"):
        _render_action_bar(filters)
    
    with perf.step("render_receipts_list"):
        _render_receipts_list(all_receipts, boot, filters, perf)
    
    perf.summary()


# ==================== Action Bar ====================

def _render_action_bar(filters: Dict[str, Any]):
    """Render action bar with help popover"""
    col1, col2, col3, col4, col5 = st.columns([1, 1, 1, 1, 1])

    with col1:
        if st.button("📦 Production Receipt", type="primary", width='stretch',
                      key="btn_record_output"):
            st.session_state['open_record_output_dialog'] = True
            st.rerun(scope="app")  # Must be app-level: check_pending_dialogs() is outside fragment

    with col2:
        if st.button("🔒 Complete MO", width='stretch',
                      key="btn_close_order"):
            st.session_state['open_close_order_select_dialog'] = True
            st.rerun(scope="app")  # Must be app-level: check_pending_dialogs() is outside fragment

    with col3:
        if st.button("📊 Export Excel", width='stretch',
                      key="btn_export_receipts"):
            _export_receipts_excel(filters)

    with col4:
        if st.button("🔄 Refresh", width='stretch',
                      key="btn_refresh_completions"):
            # Clear bootstrap cache to force fresh data
            _cached_bootstrap.clear()
            st.rerun(scope="app")  # Must be app-level: cache clear affects page-level bootstrap

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

def _render_ready_to_close_banner(ready_info: Dict[str, Any]):
    """Render banner — v5.1: supports under-production MOs in ready list."""
    
    if ready_info['ready_count'] > 0:
        ready_orders = ready_info['ready_orders']
        
        # Split into target-met vs under-target
        target_met = [o for o in ready_orders if float(o.get('produced_qty', 0)) >= float(o.get('planned_qty', 1))]
        under_target = [o for o in ready_orders if float(o.get('produced_qty', 0)) < float(o.get('planned_qty', 1))]
        
        orders_text = ", ".join(o['order_no'] for o in ready_orders[:5])
        if ready_info['ready_count'] > 5:
            orders_text += f" +{ready_info['ready_count'] - 5} more"
        
        if target_met and not under_target:
            # All target met
            st.success(
                f"✅ **{ready_info['ready_count']} MO(s) ready to complete** — "
                f"production target met, all QC resolved. "
                f"({orders_text})"
            )
        elif under_target and not target_met:
            # All under target
            st.info(
                f"🔒 **{ready_info['ready_count']} MO(s) ready to complete** — "
                f"all QC resolved (⚠️ all under target). "
                f"({orders_text})"
            )
        else:
            # Mixed
            st.success(
                f"✅ **{len(target_met)} MO(s) ready to complete** (target met) — "
                f"({', '.join(o['order_no'] for o in target_met[:3])})"
            )
            if under_target:
                under_text = ", ".join(o['order_no'] for o in under_target[:3])
                st.info(
                    f"🔒 **{len(under_target)} MO(s) ready to complete** (⚠️ under target) — "
                    f"({under_text})"
                )
    
    if ready_info['blocked_count'] > 0:
        st.warning(
            f"⏳ **{ready_info['blocked_count']} MO(s) have pending QC** — "
            f"resolve QC before completing."
        )


# ==================== Data Warnings ====================

def _compute_warnings(receipts: pd.DataFrame,
                      dup_batches: Dict[str, int]) -> pd.Series:
    """
    Compute warning flags for each receipt row.
    Returns Series of warning emoji strings aligned with receipts index.
    
    v5.0: Uses pre-loaded dup_batches dict instead of per-page DB query.
    """
    today = pd.Timestamp(get_vietnam_today())

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

def _render_receipts_list(all_receipts: Optional[pd.DataFrame], boot: Dict[str, Any],
                         filters: Dict[str, Any],
                         perf: Optional[PerformanceTimer] = None):
    """
    Render unified metrics + receipts table.
    
    v5.0: ALL data pre-loaded from bootstrap. Zero DB round-trips here.
    
    Data pipeline (all client-side):
    1. all_receipts → from bootstrap cache (already loaded)
    2. _apply_filters() → filtered DataFrame (pandas)
    3. _compute_stats_client() → stats dict (pandas)
    4. iloc slice → paginated page
    5. _derive_duplicate_batches() → warnings (pandas)
    """
    if perf is None:
        perf = PerformanceTimer("receipts_list")
    
    page_size = CompletionConstants.DEFAULT_PAGE_SIZE
    page = st.session_state.completions_page

    # Ready-to-close banner — from bootstrap (0 DB)
    with perf.step("ready_to_close_banner"):
        ready_info = boot.get('header', {}).get('ready_to_close', {})
        _render_ready_to_close_banner(ready_info)

    # Connection error check
    if all_receipts is None:
        error_msg = boot.get('connection_error') or "Cannot connect to database"
        st.error(f"🔌 **Database Connection Error**\n\n{error_msg}")
        st.info("💡 Check VPN/network connection or contact IT support")
        return

    # ── Client-side filtering (pandas — zero DB) ──
    with perf.step("client_filter", f"{len(all_receipts)} rows"):
        filtered = _apply_filters(all_receipts, filters)
    
    logger.info(f"[PERF] client_filter: {len(all_receipts)} total → {len(filtered)} filtered")

    # ── Stats from filtered data (pandas — zero DB) ──
    with perf.step("compute_stats"):
        stats = _compute_stats_client(filtered)
    
    total_count = stats['total_count']

    # Empty data check
    if filtered.empty:
        st.info("📭 No production receipts found matching the filters")
        return

    # ── Paginate with iloc ──
    with perf.step("paginate"):
        offset = (page - 1) * page_size
        receipts = filtered.iloc[offset:offset + page_size].reset_index(drop=True)
    
    # Avg yield from current page
    avg_yield = receipts['yield_rate'].mean() if not receipts.empty else 0

    # ── Unified Metrics ──
    with perf.step("render_metrics"):
        _render_metrics(stats, avg_yield)

    # ── Warnings (derived from DataFrame, zero DB) ──
    with perf.step("compute_warnings"):
        dup_batches = _derive_duplicate_batches(all_receipts)
        warnings_col = _compute_warnings(receipts, dup_batches)
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
            qc_help = "🔒 MO is completed — QC locked"
        elif selected_receipt['quality_status'] != 'PENDING':
            qc_help = f"🔒 QC decision is {selected_receipt['quality_status']} — final"

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            if st.button("👁️ View Details", type="primary",
                         width='stretch', key="btn_view_receipt"):
                show_receipt_details_dialog(selected_receipt['id'])

        with col2:
            if can_update_qc:
                if st.button("🔬 QC Decision",
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

def _export_receipts_excel(filters: Dict[str, Any]):
    """Export receipts to Excel — uses bootstrap cache, zero extra DB hit"""
    with st.spinner("Exporting..."):
        include_completed = not filters.get('exclude_completed', True)
        boot = _cached_bootstrap(include_completed)
        all_receipts = boot.get('receipts')
        
        if all_receipts is None or all_receipts.empty:
            st.warning("No receipts to export")
            return
        
        receipts = _apply_filters(all_receipts, filters)
        
        if receipts.empty:
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

    v5.0: Parallel bootstrap — 2 queries instead of 6.
    ┌──────────────────────────────────┐
    │  _cached_bootstrap() ← 1 call   │  2 parallel DB queries on cache miss
    │  (receipts + header data)        │  0ms on cache hit (TTL 30s)
    ├──────────────────────────────────┤
    │  Header + Live Badges            │  ← from bootstrap, no DB call
    ├──────────────────────────────────┤
    │  @st.fragment                    │
    │  ┌────────────────────────────┐  │
    │  │ Filters (derived from DF)  │  │  Products/warehouses from receipts DF
    │  │ Action Bar                 │  │  ← fragment reruns independently
    │  │ Ready-to-Complete Banner   │  │  from bootstrap, no DB call
    │  │ Unified Metrics (pandas)   │  │  _compute_stats_client()
    │  │ Warnings Bar (pandas)      │  │  _derive_duplicate_batches()
    │  │ Receipts Table + Actions   │  │  iloc pagination
    │  │ Pagination                 │  │
    │  └────────────────────────────┘  │
    └──────────────────────────────────┘
    """
    _init_session_state()
    
    perf = PerformanceTimer("render_completions_tab")
    
    with perf.step("check_pending_dialogs"):
        check_pending_dialogs()

    # ── Bootstrap: load all data (2 parallel queries on cache miss) ──
    include_completed = st.session_state.get('completion_show_completed', False)
    
    with perf.step("bootstrap"):
        boot = _cached_bootstrap(include_completed)

    # Header uses bootstrap data directly — no DB call
    with perf.step("render_header"):
        _render_header_from_data(boot.get('header', {}).get('live_stats', {}))
    
    with perf.step("render_receipts_section_call"):
        _render_receipts_section(boot)
    
    perf.summary()