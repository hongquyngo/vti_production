# utils/production/completions/page.py
"""
Main UI orchestrator for Production Receipts domain
Renders the Production Receipts tab with unified metrics, filters, and receipts list

Version: 4.0.0
Changes:
- v4.0.0: Production Receipts refactoring
  - Renamed from "Completions" to "Production Receipts"
  - Added "Show completed orders" filter (default: unchecked)
  - Added Ready-to-Close banner for orders meeting close conditions
  - Added Close Order button in action bar
  - Update Quality button disabled for non-PENDING or COMPLETED MOs
  - Added aging indicators in warnings column
  - Updated header badges to include ready_to_close count
- v3.0.0: Layout redesign
"""

import logging
from typing import Dict, Any

import streamlit as st
import pandas as pd

from .queries import CompletionQueries
from .forms import render_completion_form
from .dialogs import (
    show_receipt_details_dialog, show_update_quality_dialog,
    show_pdf_dialog, show_close_order_dialog, check_pending_dialogs
)
from .common import (
    format_number, create_status_indicator, get_yield_indicator,
    calculate_percentage, format_datetime_vn, get_vietnam_today,
    export_to_excel, get_date_filter_presets, CompletionConstants,
    format_product_display, get_aging_indicator
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
    Shows real-time KPIs: In Progress orders + Today's receipts + Ready to close.
    """
    stats = queries.get_live_stats()

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


# ==================== Help Popover ====================

def _render_help_popover():
    """
    Render full help as st.popover — no page rerun needed.
    Contains validation rules, formulas, quality flow,
    inventory impact, alerts, and terminology.
    """
    with st.popover("❓ Help", use_container_width=True):
        st.markdown("### 📚 Production Receipts Help")

        st.markdown("#### 📦 Record Output (Phase 1)")
        st.markdown("""\
| Điều kiện | Yêu cầu | Giải thích |
|-----------|---------|------------|
| Order Status | = `IN_PROGRESS` | Chỉ orders đang sản xuất |
| QC Breakdown | Passed + Pending + Failed > 0 | Chia QC ngay lúc receipt |
| Batch No | Không trống | Mã batch để truy xuất |
| Raw Materials | `issued_qty > 0` | NVL chính phải được issue |
| Overproduction | Không giới hạn | Ghi đúng thực tế |\
""")

        st.markdown("---")
        
        st.markdown("#### 🔒 Close Order (Phase 2)")
        st.markdown("""\
| Điều kiện | Yêu cầu | Giải thích |
|-----------|---------|------------|
| Có receipt | ≥ 1 | Phải có ít nhất 1 phiếu nhập |
| PENDING QC | = 0 | Tất cả QC phải resolved |
| Raw Materials | issued | NVL chính đã xuất |
| Action | Manual confirm | User phải nhấn Close |\
""")

        st.markdown("""\
> 💡 **MO không auto-complete.** Sau khi Record Output, MO vẫn IN_PROGRESS.  
> User chủ động Close Order khi sẵn sàng.\
""")

        st.markdown("---")

        st.markdown("#### 🔄 QC Status Flow")
        st.markdown("""\
| Transition | Cho phép? | Inventory |
|-----------|----------|-----------|
| Receipt → PASSED | ✅ | ➕ Vào kho |
| Receipt → PENDING | ✅ | ❌ Chưa vào kho |
| Receipt → FAILED | ✅ | ❌ Không vào kho |
| PENDING → PASSED | ✅ | ➕ Vào kho |
| PENDING → FAILED | ✅ | Không thay đổi |
| PASSED → bất kỳ | 🔒 Locked | — |
| FAILED → bất kỳ | 🔒 Locked | — |
| MO COMPLETED → sửa QC | 🔒 Locked | — |\
""")

        st.markdown("---")

        st.markdown("#### ⚠️ Alert Warnings")
        st.markdown("""\
| Icon | Cảnh báo | Mô tả |
|------|---------|-------|
| 🔁 | Duplicate Batch | Batch number trùng MO khác |
| 📅 | Expired | Sản phẩm đã quá hạn |
| 📈 | Overproduction | Yield > 100% |
| ⏳ | Pending QC | Chưa kiểm tra chất lượng |
| 🟡🟠🔴 | Aging | PENDING lâu (>3/7/14 ngày) |
| 🔒 | Completed | Order đã đóng |\
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
        
        show_completed = st.checkbox(
            "Show completed orders",
            value=False,
            key="completion_show_completed",
            help="Include receipts from COMPLETED manufacturing orders"
        )

    return {
        'from_date': from_date,
        'to_date': to_date,
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
        if st.button("📦 Record Output", type="primary", use_container_width=True,
                      key="btn_record_output"):
            st.session_state.completions_view = 'create'
            st.rerun()

    with col2:
        if st.button("🔒 Close Order", use_container_width=True,
                      key="btn_close_order"):
            st.session_state.completions_view = 'close_order'
            st.rerun()

    with col3:
        if st.button("📊 Export Excel", use_container_width=True,
                      key="btn_export_receipts"):
            _export_receipts_excel(queries, filters)

    with col4:
        if st.button("🔄 Refresh", use_container_width=True,
                      key="btn_refresh_completions"):
            st.rerun()

    with col5:
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


# ==================== Ready-to-Close Banner ====================

def _render_ready_to_close_banner(queries: CompletionQueries):
    """Render banner showing orders ready to close or blocked by pending QC."""
    ready_info = queries.get_ready_to_close_orders()
    
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
        exclude_completed=exclude_completed
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
                         use_container_width=True, key="btn_view_receipt"):
                show_receipt_details_dialog(selected_receipt['id'])

        with col2:
            if can_update_qc:
                if st.button("✏️ Update Quality",
                             use_container_width=True, key="btn_update_quality"):
                    show_update_quality_dialog(selected_receipt['id'])
            else:
                st.button("🔒 QC Locked",
                         use_container_width=True, key="btn_update_quality",
                         disabled=True, help=qc_help)

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
            exclude_completed=filters.get('exclude_completed', True),
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


# ==================== Close Order View ====================

def _render_close_order_view(queries: CompletionQueries):
    """Render close order selection and confirmation view."""
    st.subheader("🔒 Close Manufacturing Order")
    st.caption("Select an order to close. All QC must be resolved before closing.")
    
    ready_info = queries.get_ready_to_close_orders()
    
    if ready_info['ready_count'] == 0 and ready_info['blocked_count'] == 0:
        st.info("📭 No orders are ready to close. Orders need to meet their production target first.")
        return
    
    # Show ready orders
    if ready_info['ready_count'] > 0:
        st.success(f"✅ **{ready_info['ready_count']} order(s) ready to close**")
        
        for order in ready_info['ready_orders']:
            with st.container(border=True):
                col1, col2, col3 = st.columns([3, 2, 1])
                with col1:
                    yield_pct = calculate_percentage(order['produced_qty'], order['planned_qty'])
                    st.markdown(
                        f"**{order['order_no']}** | {order['product_name']}"
                    )
                    st.caption(
                        f"Produced: {format_number(order['produced_qty'], 2)}"
                        f" / {format_number(order['planned_qty'], 2)} {order['uom']}"
                        f" ({yield_pct}%)"
                    )
                with col2:
                    st.caption(f"Receipts: {order['receipt_count']}")
                with col3:
                    if st.button("🔒 Close", key=f"close_order_{order['id']}",
                                use_container_width=True):
                        show_close_order_dialog(int(order['id']))
    
    # Show blocked orders
    if ready_info['blocked_count'] > 0:
        st.warning(f"⏳ **{ready_info['blocked_count']} order(s) blocked by pending QC**")
        
        for order in ready_info['blocked_orders']:
            st.caption(
                f"• **{order['order_no']}** — {order['product_name']} "
                f"({int(order['pending_count'])} pending receipts)"
            )


# ==================== Main Render Function ====================

def render_completions_tab():
    """
    Main function to render the Production Receipts tab.

    Layout v4.0:
    ┌──────────────────────────────────┐
    │  Header + Live Badges            │  ← renders once
    ├──────────────────────────────────┤
    │  @st.fragment                    │
    │  ┌────────────────────────────┐  │
    │  │ Filters (+ show completed) │  │
    │  │ Action Bar (Record/Close)  │  │  ← fragment reruns independently
    │  │ Ready-to-Close Banner      │  │
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
    
    # Close Order view
    if st.session_state.completions_view == 'close_order':
        if st.button("⬅️ Back to Receipts", key="btn_back_from_close"):
            st.session_state.completions_view = 'receipts'
            st.rerun()
        
        _render_close_order_view(queries)
        return

    # Receipts view — Header (once) + Fragment (interactive)
    _render_header(queries)
    _render_receipts_section(queries)