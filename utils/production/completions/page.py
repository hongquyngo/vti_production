# utils/production/completions/page.py
"""
Main UI orchestrator for Completions domain
Renders the Completions tab with dashboard, completion form, and receipts list

Version: 2.0.0
Changes:
- v2.0.0: Help → popover (no full page rerun), @st.fragment for receipts section
  - Removed full-page Help view, replaced with st.popover in action bar
  - Wrapped filters + action bar + receipts list in @st.fragment
  - Pagination & row selection use st.rerun(scope="fragment") instead of full rerun
  - Dashboard renders once, unaffected by filter/select/pagination interactions
- v1.3.0: Added Scheduled Date column (ngày dự kiến hoàn thành sản xuất)
- v1.2.0: Improved product display, Added Order Date column
- v1.1.0: Added Help section with validation rules and calculation formulas

Requires: Streamlit >= 1.37 (for @st.fragment and st.rerun(scope=...))
"""

import logging
from typing import Dict, Any

import streamlit as st
import pandas as pd

from .queries import CompletionQueries
from .dashboard import render_dashboard
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
    """
    Format product display for DataFrame row.
    Wrapper around common.format_product_display() for apply() usage.

    Format: PT_CODE (LEGACY|NEW) | NAME | PKG_SIZE (BRAND)
    """
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


# ==================== Help Popover ====================

def _render_help_popover():
    """
    Render simplified help as st.popover — lightweight, no page rerun.
    Replaces the old full-page Help view.
    """
    with st.popover("❓ Help", use_container_width=True):
        st.markdown("### 📚 Production Completion Help")

        # Validation Rules
        st.markdown("#### 🔒 Validation Rules")
        st.markdown("""\
| Điều kiện | Yêu cầu |
|-----------|---------|
| Order Status | = `IN_PROGRESS` |
| Produced Qty | > 0, tối đa 150% remaining |
| Batch No | Bắt buộc (không trống) |
| Raw Materials | Tất cả phải được issue (`issued_qty > 0`) |

> 💡 **PACKAGING** & **CONSUMABLE** không bắt buộc issue.\
""")

        st.markdown("---")

        # Quality → Inventory
        st.markdown("#### 🔄 Quality Status & Inventory")
        st.markdown("""\
| Thay đổi | Inventory |
|----------|-----------|
| Tạo mới → **PASSED** | ➕ Tạo `stockInProduction` |
| Tạo mới → PENDING / FAILED | Không tạo inventory |
| PENDING/FAILED → **PASSED** | ➕ Thêm vào tồn kho |
| **PASSED** → PENDING/FAILED | ➖ Xóa khỏi tồn kho (`remain = 0`) |
| PENDING ↔ FAILED | Không thay đổi |\
""")

        st.markdown("---")

        # Partial QC
        st.markdown("#### 🔬 Partial QC")
        st.markdown("""\
Hỗ trợ chia receipt thành **PASSED + PENDING + FAILED**.

**Split priority:** PASSED > PENDING > FAILED  
Original receipt giữ status có priority cao nhất.  
Tạo receipt mới cho phần còn lại.\
""")

        st.markdown("---")

        # Formulas
        st.markdown("#### 📐 Công thức")
        st.markdown("""\
- **Progress** = Produced ÷ Planned × 100%
- **Remaining** = Planned − Produced
- **Max Input** = Remaining × 1.5
- **Yield Rate** = Produced ÷ Planned × 100%
- **Pass Rate** = PASSED Qty ÷ Total Qty × 100%\
""")

        st.markdown("---")

        # Yield Indicators
        st.markdown("#### 📊 Yield Indicators")
        st.markdown("""\
| Yield | Indicator |
|-------|-----------|
| ≥ 95% | ✅ Excellent |
| 85–94% | ⚠️ Acceptable |
| < 85% | ❌ Below Target |\
""")

        st.caption("💬 Liên hệ IT nếu cần hỗ trợ thêm")


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
    Fragment: filters + action bar + receipts list.

    Reruns INDEPENDENTLY from the rest of the page.
    Filter changes, row selection, and pagination only rerun this fragment,
    leaving the dashboard and header untouched.

    Uses st.rerun(scope="fragment") for fragment-scoped reruns (pagination, selection).
    Uses st.rerun() (full page) only for view changes (Record Output) and full Refresh.
    """
    filters = _render_filter_bar(queries)
    _render_action_bar(queries, filters)
    _render_receipts_list(queries, filters)


# ==================== Receipts List ====================

def _render_receipts_list(queries: CompletionQueries, filters: Dict[str, Any]):
    """Render production receipts list with improved product display and dates"""
    page_size = CompletionConstants.DEFAULT_PAGE_SIZE
    page = st.session_state.completions_page

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

    # Check for connection error (returns None)
    if receipts is None:
        error_msg = queries.get_last_error() or "Cannot connect to database"
        st.error(f"🔌 **Database Connection Error**\n\n{error_msg}")
        st.info("💡 Check VPN/network connection or contact IT support")
        return

    total_count = queries.get_receipts_count(
        from_date=filters['from_date'],
        to_date=filters['to_date'],
        quality_status=filters['quality_status'],
        product_id=filters['product_id'],
        warehouse_id=filters['warehouse_id'],
        order_no=filters['order_no'],
        batch_no=filters['batch_no']
    )

    # Check for empty data (returns empty DataFrame)
    if receipts.empty:
        st.info("📭 No production receipts found matching the filters")
        return

    # Summary metrics
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Total Receipts", len(receipts))

    with col2:
        total_qty = receipts['quantity'].sum()
        st.metric("Total Quantity", format_number(total_qty, 0))

    with col3:
        passed = len(receipts[receipts['quality_status'] == 'PASSED'])
        pass_rate = calculate_percentage(passed, len(receipts), 1)
        indicator = get_yield_indicator(pass_rate)
        st.metric("Pass Rate", f"{pass_rate}% {indicator}")

    with col4:
        avg_yield = receipts['yield_rate'].mean()
        yield_indicator = get_yield_indicator(avg_yield)
        st.metric("Avg Yield Rate", f"{avg_yield:.1f}% {yield_indicator}")

    # Quality breakdown expander
    with st.expander("📈 Quality Breakdown", expanded=False):
        qcol1, qcol2, qcol3 = st.columns(3)
        total_receipts = len(receipts)
        passed_count = len(receipts[receipts['quality_status'] == 'PASSED'])
        pending_count = len(receipts[receipts['quality_status'] == 'PENDING'])
        failed_count = len(receipts[receipts['quality_status'] == 'FAILED'])

        with qcol1:
            st.metric("✅ PASSED", passed_count,
                       f"{calculate_percentage(passed_count, total_receipts)}%")
        with qcol2:
            st.metric("⏳ PENDING", pending_count,
                       f"{calculate_percentage(pending_count, total_receipts)}%")
        with qcol3:
            st.metric("❌ FAILED", failed_count,
                       f"{calculate_percentage(failed_count, total_receipts)}%")

    st.markdown("---")
    st.markdown("### 📋 Receipts List")

    # Initialize selected index in session state
    if 'completions_selected_idx' not in st.session_state:
        st.session_state.completions_selected_idx = None

    # Prepare display
    display_df = receipts.copy()

    # Set Select column based on session state (single selection)
    display_df['Select'] = False
    if (st.session_state.completions_selected_idx is not None
            and st.session_state.completions_selected_idx < len(display_df)):
        display_df.loc[st.session_state.completions_selected_idx, 'Select'] = True

    # Format dates: Receipt Date, Order Date, and Scheduled Date
    display_df['receipt_date_display'] = display_df['receipt_date'].apply(
        lambda x: format_datetime_vn(x, '%d-%b-%Y')
    )
    display_df['order_date_display'] = display_df['order_date'].apply(
        lambda x: _format_date_display(x, '%d-%b-%Y')
    )
    display_df['scheduled_date_display'] = display_df['scheduled_date'].apply(
        lambda x: _format_date_display(x, '%d-%b-%Y')
    )

    # Format Product: pt_code | name (package_size)
    display_df['product_display'] = display_df.apply(_format_product_display_row, axis=1)

    # Format other columns
    display_df['quality_display'] = display_df['quality_status'].apply(create_status_indicator)
    display_df['yield_display'] = display_df['yield_rate'].apply(
        lambda x: f"{x:.1f}% {get_yield_indicator(x)}"
    )
    display_df['qty_display'] = display_df.apply(
        lambda x: f"{format_number(x['quantity'], 0)} {x['uom']}", axis=1
    )

    # Create editable dataframe with selection
    edited_df = st.data_editor(
        display_df[[
            'Select', 'receipt_no', 'receipt_date_display', 'order_date_display',
            'scheduled_date_display', 'order_no', 'product_display', 'qty_display',
            'batch_no', 'quality_display', 'yield_display', 'warehouse_name'
        ]].rename(columns={
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
        disabled=['Receipt No', 'Receipt Date', 'Order Date', 'Scheduled Date', 'Order No',
                  'Product', 'Quantity', 'Batch', 'Quality', 'Yield', 'Warehouse'],
        column_config={
            'Select': st.column_config.CheckboxColumn(
                '✓',
                help='Select row to perform actions',
                default=False,
                width='small'
            ),
            'Product': st.column_config.TextColumn(
                'Product',
                help='pt_code | name (package_size)',
                width='large'
            )
        },
        key="completions_table_editor"
    )

    # Handle single selection - find newly selected row
    selected_indices = edited_df[edited_df['Select'] == True].index.tolist()

    if selected_indices:
        # If multiple selected (user clicked new one), keep only the newest
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

    # Action buttons - only show when row is selected
    if st.session_state.completions_selected_idx is not None:
        selected_receipt = receipts.iloc[st.session_state.completions_selected_idx]

        st.markdown("---")
        # Show selected receipt info with improved product display
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
            f"Page {page} of {total_pages} | Total: {total_count} receipts"
            f"</div>",
            unsafe_allow_html=True
        )

    with col3:
        if st.button("Next ➡️", disabled=page >= total_pages, key="btn_next_receipt"):
            st.session_state.completions_page = page + 1
            st.session_state.completions_selected_idx = None
            st.rerun(scope="fragment")


# ==================== Action Bar ====================

def _render_action_bar(queries: CompletionQueries, filters: Dict[str, Any]):
    """Render action bar with help popover"""
    col1, col2, col3, col4 = st.columns([1, 1, 1, 1])

    with col1:
        if st.button("✅ Record Output", type="primary", use_container_width=True,
                      key="btn_record_output"):
            st.session_state.completions_view = 'create'
            st.rerun()  # Full rerun — switches to create view

    with col2:
        if st.button("📊 Export Excel", use_container_width=True,
                      key="btn_export_receipts"):
            _export_receipts_excel(queries, filters)

    with col3:
        if st.button("🔄 Refresh", use_container_width=True,
                      key="btn_refresh_completions"):
            st.rerun()  # Full rerun — refreshes dashboard + data

    with col4:
        _render_help_popover()


def _export_receipts_excel(queries: CompletionQueries, filters: Dict[str, Any]):
    """Export receipts to Excel with improved product display"""
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

        # Create export dataframe with improved columns
        export_df = receipts.copy()

        # Format product display
        export_df['Product'] = export_df.apply(_format_product_display_row, axis=1)

        # Format dates
        export_df['Receipt Date'] = export_df['receipt_date'].apply(
            lambda x: format_datetime_vn(x, '%d/%m/%Y %H:%M') if pd.notna(x) else ''
        )
        export_df['Order Date'] = export_df['order_date'].apply(
            lambda x: _format_date_display(x, '%d/%m/%Y') if pd.notna(x) else ''
        )
        export_df['Scheduled Date'] = export_df['scheduled_date'].apply(
            lambda x: _format_date_display(x, '%d/%m/%Y') if pd.notna(x) else ''
        )

        # Select and rename columns — include legacy code and brand for detailed export
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
    Called from the main Production page.

    Layout:
    ┌──────────────────────────────────┐
    │  Header + Dashboard              │  ← renders once
    ├──────────────────────────────────┤
    │  @st.fragment                    │
    │  ┌────────────────────────────┐  │
    │  │ Filters                    │  │  ← fragment reruns independently
    │  │ Action Bar (+ Help popover)│  │    on filter change, row select,
    │  │ Receipts List + Pagination │  │    or pagination click
    │  └────────────────────────────┘  │
    └──────────────────────────────────┘
    """
    _init_session_state()

    # Check for pending dialogs (must be at page level, before fragment)
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

    # Receipts view
    st.subheader("✅ Production Completions")

    # Dashboard — outside fragment, renders once
    render_dashboard()

    # Fragment: filters + action bar + receipts list
    _render_receipts_section(queries)