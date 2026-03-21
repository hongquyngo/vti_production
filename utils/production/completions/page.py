# utils/production/completions/page.py
"""
Main UI orchestrator for Completions domain
Renders the Completions tab with unified metrics, filters, and receipts list

Version: 3.0.0
Changes:
- v3.0.0: Layout redesign — removed duplicate metrics & quality breakdowns
  - Removed separate dashboard section (all-time metrics not actionable)
  - Removed 2x Quality Breakdown expanders (redundant)
  - Added get_live_stats() for header badges (In Progress + Today)
  - Added get_filtered_stats() for accurate metrics across ALL filtered data
  - Single unified metrics row: count, qty, passed, pending, failed, yield
  - Table visible without scrolling (~240px overhead vs ~600px before)
- v2.1.0: Post-validation warnings in Receipts List table
- v2.0.0: Help → popover, @st.fragment for receipts section
- v1.3.0: Added Scheduled Date column

Requires: Streamlit >= 1.37 (for @st.fragment and st.rerun(scope=...))
"""

import logging
from typing import Dict, Any

import streamlit as st
import pandas as pd

from .queries import CompletionQueries
from .forms import render_completion_form
from .dialogs import (
    show_receipt_details_dialog, show_update_quality_dialog,
    show_pdf_dialog, check_pending_dialogs
)
from .common import (
    format_number, create_status_indicator, get_yield_indicator,
    calculate_percentage, format_datetime_vn, get_vietnam_today,
    export_to_excel, get_date_filter_presets, CompletionConstants,
    format_product_display
)

logger = logging.getLogger(__name__)


# ==================== Session State ====================

def _init_session_state():
    """Initialize session state for completions tab"""
    defaults = {
        'completions_page': 1,
        'completions_view': 'receipts',  # 'receipts' or 'create'
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
    Shows real-time KPIs: In Progress orders + Today's receipts.
    """
    stats = queries.get_live_stats()

    col1, col2 = st.columns([2, 1])
    with col1:
        st.subheader("✅ Production Completions")
    with col2:
        st.markdown(
            f"<div style='text-align:right; padding-top:10px; font-size:0.9em;'>"
            f"🔄 <b>{stats['in_progress']}</b> in progress &nbsp;·&nbsp; "
            f"📅 <b>{stats['today_count']}</b> today"
            f"</div>",
            unsafe_allow_html=True
        )


# ==================== Help Popover ====================

def _render_help_popover():
    """
    Render full help as st.popover — no page rerun needed.
    Contains validation rules, formulas, quality flow,
    inventory impact, alerts, and terminology.
    """
    with st.popover("❓ Help", use_container_width=True):
        st.markdown("### 📚 Production Completion Help")

        st.markdown("#### 🔒 Validation Rules")
        st.markdown("Để hoàn thành (complete) một Production Order:")
        st.markdown("""\
| Điều kiện | Yêu cầu | Giải thích |
|-----------|---------|------------|
| Order Status | = `IN_PROGRESS` | Chỉ orders đang sản xuất |
| Produced Qty | > 0 | Số lượng phải là số dương |
| Max Qty | ≤ Remaining × 1.5 | Cho phép vượt 50% kế hoạch |
| Batch No | Không trống | Mã batch để truy xuất |
| Raw Materials | `issued_qty > 0` | NVL chính phải được issue |
| Pending QC | Không có receipt PENDING | Khi order sẽ auto-complete |\
""")

        st.markdown("""\
> 💡 **Raw Materials:** Chỉ kiểm tra `RAW_MATERIAL` (hoặc NULL).  
> PACKAGING & CONSUMABLE không bắt buộc.\
""")

        st.markdown("---")

        st.markdown("#### ⚠️ Alert Warnings")
        st.markdown("""\
| Icon | Cảnh báo | Mô tả |
|------|---------|-------|
| 🔁 | Duplicate Batch | Batch number trùng với order khác |
| 📅 | Expired | Sản phẩm đã quá hạn sử dụng |
| 📈 | Overproduction | Yield rate > 100% |
| ⏳ | Pending QC | Chưa kiểm tra chất lượng |\
""")

        st.markdown("""\
> 🔁 📅 📈 là **warning** (không block).  
> ⏳ sẽ **block** order auto-complete nếu có receipt PENDING.\
""")

        st.markdown("---")

        st.markdown("#### 📐 Calculation Formulas")
        st.markdown("""\
| Công thức | Cách tính |
|-----------|-----------|
| **Progress** | Produced ÷ Planned × 100% |
| **Remaining** | Planned − Produced |
| **Max Input** | Remaining × 1.5 |
| **Yield Rate** | Produced ÷ Planned × 100% |
| **Pass Rate** | PASSED Count ÷ Total Count × 100% |\
""")

        st.markdown("---")

        st.markdown("#### 🔄 Quality Status Flow")
        st.markdown("""\
| Status | Inventory Impact |
|--------|-----------------|
| ⏳ PENDING | ❌ Không cập nhật tồn kho |
| ✅ PASSED | ✅ Cộng vào tồn kho |
| ❌ FAILED | ❌ Không cập nhật tồn kho |\
""")

        st.markdown("---")

        st.markdown("#### 📦 Inventory Impact khi cập nhật QC")
        st.markdown("""\
| Thay đổi | Action |
|----------|--------|
| PENDING → **PASSED** | ➕ Tạo `stockInProduction` |
| PENDING → FAILED | Không thay đổi |
| **PASSED** → PENDING | ➖ Set `remain = 0` |
| **PASSED** → FAILED | ➖ Set `remain = 0` |
| FAILED → **PASSED** | ➕ Tạo `stockInProduction` |
| FAILED → PENDING | Không thay đổi |\
""")

        st.markdown("---")

        st.markdown("#### 🔬 Partial QC (Chia tách receipt)")
        st.markdown("""\
| # | Kịch bản | Kết quả |
|---|----------|---------|
| 1 | 100% PASSED | Original → PASSED |
| 2 | 100% PENDING | Original → PENDING |
| 3 | 100% FAILED | Original → FAILED |
| 4-7 | Mixed | Split thành 2-3 receipts |\
""")

        st.markdown("""\
> **Priority:** PASSED > PENDING > FAILED.  
> Original receipt giữ status priority cao nhất.\
""")

        st.markdown("---")

        st.markdown("#### 📖 Thuật ngữ")
        st.markdown("""\
| Thuật ngữ | Mô tả |
|-----------|-------|
| MO | Lệnh sản xuất |
| PR | Phiếu nhập kho thành phẩm |
| Yield Rate | Produced ÷ Planned × 100% |
| stockInProduction | Loại inventory từ SX |\
""")

        st.caption("💬 Liên hệ team IT hoặc sử dụng nút 👎 để báo lỗi.")


# ==================== Filter Bar ====================

def _render_filter_bar(queries: CompletionQueries) -> Dict[str, Any]:
    """Render filter bar and return selected filters"""
    presets = get_date_filter_presets()

    with st.expander("🔍 Filters", expanded=False):
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            date_range = st.selectbox(
                "Date Range",
                options=list(presets.keys()),
                index=6,  # Last 30 Days
                key="completion_date_range"
            )
            from_date, to_date = presets[date_range]

        with col2:
            quality_options = ['All'] + [q[0] for q in CompletionConstants.QUALITY_STATUSES]
            quality_status = st.selectbox(
                "Quality Status",
                options=quality_options,
                key="completion_quality_filter"
            )

        with col3:
            products = queries.get_products()
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

        with col4:
            warehouses = queries.get_warehouses()
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

        col5, col6 = st.columns(2)
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

    return {
        'from_date': from_date,
        'to_date': to_date,
        'quality_status': quality_status if quality_status != 'All' else None,
        'product_id': product_id,
        'warehouse_id': warehouse_id,
        'order_no': order_no if order_no else None,
        'batch_no': batch_no if batch_no else None
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
    col1, col2, col3, col4 = st.columns([1, 1, 1, 1])

    with col1:
        if st.button("✅ Record Output", type="primary", use_container_width=True,
                      key="btn_record_output"):
            st.session_state.completions_view = 'create'
            st.rerun()

    with col2:
        if st.button("📊 Export Excel", use_container_width=True,
                      key="btn_export_receipts"):
            _export_receipts_excel(queries, filters)

    with col3:
        if st.button("🔄 Refresh", use_container_width=True,
                      key="btn_refresh_completions"):
            st.rerun()

    with col4:
        _render_help_popover()


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


# ==================== Data Warnings ====================

def _compute_warnings(receipts: pd.DataFrame,
                      queries: CompletionQueries) -> pd.Series:
    """
    Compute warning flags for each receipt row.
    Returns Series of warning emoji strings aligned with receipts index.
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
            warnings.append('⏳')
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

    # Get current page data
    receipts = queries.get_receipts(
        from_date=filters['from_date'],
        to_date=filters['to_date'],
        quality_status=filters['quality_status'],
        product_id=filters['product_id'],
        warehouse_id=filters['warehouse_id'],
        order_no=filters['order_no'],
        batch_no=filters['batch_no'],
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
        batch_no=filters['batch_no']
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
        use_container_width=True,
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
        st.markdown(
            f"**Selected:** `{selected_receipt['receipt_no']}` "
            f"| {selected_receipt['order_no']} | {product_info}"
        )

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            if st.button("👁️ View Details", type="primary",
                         use_container_width=True, key="btn_view_receipt"):
                show_receipt_details_dialog(selected_receipt['id'])

        with col2:
            if st.button("✏️ Update Quality",
                         use_container_width=True, key="btn_update_quality"):
                show_update_quality_dialog(selected_receipt['id'])

        with col3:
            if st.button("📄 Export PDF",
                         use_container_width=True, key="btn_pdf_receipt"):
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
    Main function to render the Completions tab.

    Layout v3.0 (Redesigned):
    ┌──────────────────────────────────┐
    │  Header + Live Badges            │  ← renders once
    ├──────────────────────────────────┤
    │  @st.fragment                    │
    │  ┌────────────────────────────┐  │
    │  │ Filters (expander)         │  │
    │  │ Action Bar (+ Help popover)│  │  ← fragment reruns independently
    │  │ Unified Metrics (6 cols)   │  │
    │  │ Warnings Bar               │  │
    │  │ Receipts Table + Actions   │  │
    │  │ Pagination                 │  │
    │  └────────────────────────────┘  │
    └──────────────────────────────────┘
    """
    _init_session_state()
    check_pending_dialogs()

    queries = CompletionQueries()

    # Create view — full page, not inside fragment
    if st.session_state.completions_view == 'create':
        if st.button("⬅️ Back to Receipts", key="btn_back_to_receipts"):
            st.session_state.completions_view = 'receipts'
            st.session_state.pop('completion_success', None)
            st.session_state.pop('completion_info', None)
            st.rerun()

        render_completion_form()
        return

    # Receipts view — Header (once) + Fragment (interactive)
    _render_header(queries)
    _render_receipts_section(queries)