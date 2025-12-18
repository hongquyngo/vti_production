# utils/production/completions/page.py
"""
Main UI orchestrator for Completions domain
Renders the Completions tab with dashboard, completion form, and receipts list

Version: 1.2.0
Changes:
- v1.2.0: Improved product display (pt_code | name (package_size))
         Added Order Date column alongside Receipt Date
- v1.1.0: Added Help section with validation rules and calculation formulas
"""

import logging
from datetime import timedelta
from typing import Dict, Any, Optional

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
    calculate_percentage, format_datetime, format_datetime_vn, get_vietnam_today, get_vietnam_now,
    export_to_excel, get_date_filter_presets, CompletionConstants
)

logger = logging.getLogger(__name__)


# ==================== Session State ====================

def _init_session_state():
    """Initialize session state for completions tab"""
    defaults = {
        'completions_page': 1,
        'completions_view': 'receipts',  # 'receipts', 'create', or 'help'
    }
    
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


# ==================== Helper Functions ====================

def _format_product_display(row) -> str:
    """
    Format product display: pt_code | name (package_size)
    
    Examples:
    - VT001 | Vietape FP5309 Gasket PU Foam Tape (100m/roll)
    - VT002 | 3M Polyester Film Electrical Tape 74
    """
    pt_code = row.get('pt_code', '') or ''
    name = row.get('product_name', '') or ''
    package_size = row.get('package_size', '') or ''
    
    # Build display string
    if pt_code:
        display = f"{pt_code} | {name}"
    else:
        display = name
    
    # Add package_size if available
    if package_size:
        display = f"{display} ({package_size})"
    
    return display


def _format_date_display(dt, fmt: str = '%d-%b-%Y') -> str:
    """Format date for display"""
    if pd.isna(dt) or dt is None:
        return ''
    
    try:
        if isinstance(dt, str):
            from datetime import datetime
            dt = datetime.strptime(dt, '%Y-%m-%d')
        return dt.strftime(fmt)
    except:
        return str(dt)[:10] if dt else ''


# ==================== Help Section ====================

def _render_help_section():
    """Render help section with validation rules and formulas"""
    st.subheader("📚 Production Completion Help")
    
    # Back button
    if st.button("⬅️ Back to Receipts", key="btn_back_from_help"):
        st.session_state.completions_view = 'receipts'
        st.rerun()
    
    st.markdown("---")
    
    # Table of Contents
    st.markdown("""
    ### 📑 Table of Contents
    1. [Validation Rules](#validation-rules)
    2. [Calculation Formulas](#calculation-formulas)
    3. [Quality Status Flow](#quality-status-flow)
    4. [Inventory Impact](#inventory-impact)
    5. [Terminology](#terminology)
    """)
    
    st.markdown("---")
    
    # 1. Validation Rules
    st.markdown("### 🔒 Validation Rules")
    st.markdown("""
    Để hoàn thành (complete) một Production Order, các điều kiện sau **BẮT BUỘC** phải thỏa mãn:
    """)
    
    validation_data = {
        "Điều kiện": [
            "Order Status",
            "Produced Quantity", 
            "Max Quantity",
            "Batch Number",
            "Raw Materials Issued"
        ],
        "Yêu cầu": [
            "= IN_PROGRESS",
            "> 0",
            "≤ Remaining × 1.5",
            "Không được để trống",
            "Tất cả đã được issue (issued_qty > 0)"
        ],
        "Giải thích": [
            "Chỉ orders đang sản xuất mới có thể record output",
            "Số lượng sản xuất phải là số dương",
            "Cho phép sản xuất vượt 50% so với kế hoạch còn lại",
            "Mỗi lô sản xuất phải có mã batch để truy xuất",
            "Nguyên liệu chính phải được xuất kho (cho phép xuất thiếu/thừa)"
        ]
    }
    st.table(pd.DataFrame(validation_data))
    
    with st.expander("💡 Chi tiết về Raw Materials Validation", expanded=False):
        st.markdown("""
        **Logic kiểm tra:**
        ```
        ❌ Không cho complete nếu có material thỏa:
           • material_type = 'RAW_MATERIAL' (hoặc NULL)
           • issued_qty = 0 (chưa issue gì cả)
        
        ✅ Cho phép complete nếu:
           • Tất cả RAW_MATERIAL có issued_qty > 0
           • Không yêu cầu issued_qty = required_qty (cho phép sai số)
        ```
        
        **Lý do cho phép issue thiếu/thừa:**
        - Sai số trong quá trình cân đo
        - Hao hụt thực tế khác với dự tính
        - Điều chỉnh công thức trong sản xuất
        
        **Lưu ý:** PACKAGING và CONSUMABLE không bắt buộc phải issue.
        """)
    
    st.markdown("---")
    
    # 2. Calculation Formulas
    st.markdown("### 📐 Calculation Formulas")
    
    st.markdown("#### Production Progress")
    st.latex(r"\text{Progress (\%)} = \frac{\text{Produced Qty}}{\text{Planned Qty}} \times 100")
    
    st.markdown("#### Remaining Quantity")
    st.latex(r"\text{Remaining} = \text{Planned Qty} - \text{Produced Qty}")
    
    st.markdown("#### Max Allowed Input (khi record output)")
    st.latex(r"\text{Max Qty} = \text{Remaining} \times 1.5")
    
    st.markdown("#### Yield Rate")
    st.latex(r"\text{Yield Rate (\%)} = \frac{\text{Produced Qty}}{\text{Planned Qty}} \times 100")
    
    st.markdown("#### Quality Pass Rate")
    st.latex(r"\text{Pass Rate (\%)} = \frac{\text{PASSED Qty}}{\text{Total Qty}} \times 100")
    
    with st.expander("📊 Yield Rate Indicators", expanded=False):
        yield_data = {
            "Yield Rate": ["≥ 95%", "85% - 94%", "< 85%"],
            "Indicator": ["✅ Excellent", "⚠️ Acceptable", "❌ Below Target"],
            "Màu sắc": ["Xanh lá", "Vàng", "Đỏ"]
        }
        st.table(pd.DataFrame(yield_data))
    
    st.markdown("---")
    
    # 3. Quality Status Flow
    st.markdown("### 🔄 Quality Status Flow")
    
    st.markdown("""
    ```
    ┌─────────────┐
    │   PENDING   │  ← Trạng thái mặc định khi tạo receipt
    └──────┬──────┘
           │
           ▼
    ┌──────┴──────┐
    │   QC Check  │
    └──────┬──────┘
           │
      ┌────┴────┐
      │         │
      ▼         ▼
    ┌─────┐   ┌─────┐
    │PASSED│   │FAILED│
    └─────┘   └─────┘
    ```
    """)
    
    status_data = {
        "Status": ["⏳ PENDING", "✅ PASSED", "❌ FAILED"],
        "Mô tả": [
            "Chờ kiểm tra chất lượng",
            "Đạt yêu cầu chất lượng",
            "Không đạt yêu cầu"
        ],
        "Inventory Impact": [
            "❌ Không cập nhật tồn kho",
            "✅ Cộng vào tồn kho",
            "❌ Không cập nhật tồn kho"
        ]
    }
    st.table(pd.DataFrame(status_data))
    
    with st.expander("🔬 Partial QC (Chia tách receipt)", expanded=False):
        st.markdown("""
        **Hỗ trợ 7 kịch bản QC:**
        
        | # | Kịch bản | Kết quả |
        |---|----------|---------|
        | 1 | 100% PASSED | Original receipt → PASSED |
        | 2 | 100% PENDING | Original receipt → PENDING |
        | 3 | 100% FAILED | Original receipt → FAILED |
        | 4 | PASSED + FAILED | Split thành 2 receipts |
        | 5 | PASSED + PENDING | Split thành 2 receipts |
        | 6 | PENDING + FAILED | Split thành 2 receipts |
        | 7 | PASSED + PENDING + FAILED | Split thành 3 receipts |
        
        **Nguyên tắc split:**
        - Original receipt giữ status có priority cao nhất
        - Priority: PASSED > PENDING > FAILED
        - Tạo receipt mới cho các status còn lại
        """)
    
    st.markdown("---")
    
    # 4. Inventory Impact
    st.markdown("### 📦 Inventory Impact")
    
    st.markdown("""
    **Khi tạo Production Receipt:**
    """)
    
    inv_data = {
        "Quality Status": ["PASSED", "PENDING", "FAILED"],
        "Inventory Action": [
            "✅ Tạo `stockInProduction` record",
            "❌ Không tạo inventory record",
            "❌ Không tạo inventory record"
        ],
        "Ghi chú": [
            "Hàng vào kho target_warehouse ngay",
            "Chờ QC xong mới vào kho",
            "Hàng lỗi không nhập kho"
        ]
    }
    st.table(pd.DataFrame(inv_data))
    
    st.markdown("""
    **Khi cập nhật Quality Status:**
    """)
    
    change_data = {
        "Thay đổi": [
            "PENDING → PASSED",
            "PENDING → FAILED", 
            "PASSED → PENDING",
            "PASSED → FAILED",
            "FAILED → PASSED",
            "FAILED → PENDING"
        ],
        "Inventory Action": [
            "➕ Tạo `stockInProduction`",
            "Không thay đổi",
            "➖ Xóa khỏi tồn kho (remain = 0)",
            "➖ Xóa khỏi tồn kho (remain = 0)",
            "➕ Tạo `stockInProduction`",
            "Không thay đổi"
        ]
    }
    st.table(pd.DataFrame(change_data))
    
    st.markdown("---")
    
    # 5. Terminology
    st.markdown("### 📖 Terminology")
    
    terms_data = {
        "Thuật ngữ": [
            "Production Order (MO)",
            "Production Receipt (PR)",
            "Planned Qty",
            "Produced Qty",
            "Remaining Qty",
            "Yield Rate",
            "Batch No",
            "RAW_MATERIAL",
            "PACKAGING",
            "CONSUMABLE",
            "stockInProduction"
        ],
        "Tiếng Việt": [
            "Lệnh sản xuất",
            "Phiếu nhập kho thành phẩm",
            "Số lượng kế hoạch",
            "Số lượng đã sản xuất",
            "Số lượng còn lại",
            "Tỷ lệ hoàn thành",
            "Mã lô sản xuất",
            "Nguyên liệu chính",
            "Bao bì đóng gói",
            "Vật tư tiêu hao",
            "Nhập kho từ sản xuất"
        ],
        "Mô tả": [
            "Lệnh chỉ đạo sản xuất một sản phẩm từ BOM",
            "Ghi nhận số lượng thành phẩm sản xuất được",
            "Số lượng mục tiêu cần sản xuất",
            "Tổng số đã sản xuất (có thể từ nhiều receipts)",
            "Planned - Produced",
            "Produced / Planned × 100%",
            "Mã để truy xuất nguồn gốc sản phẩm",
            "Nguyên liệu bắt buộc phải issue trước khi complete",
            "Không bắt buộc issue",
            "Không bắt buộc issue",
            "Loại inventory khi nhập kho từ sản xuất"
        ]
    }
    st.table(pd.DataFrame(terms_data))
    
    st.markdown("---")
    
    # Contact
    st.info("""
    💬 **Cần hỗ trợ thêm?**
    
    Liên hệ team IT hoặc sử dụng nút 👎 để báo lỗi.
    """)


# ==================== Filter Bar ====================

def _render_filter_bar(queries: CompletionQueries) -> Dict[str, Any]:
    """Render filter bar and return selected filters"""
    presets = get_date_filter_presets()
    
    with st.expander("🔍 Filters", expanded=False):
        col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
        
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
            product_options = ["All Products"] + products['name'].tolist() if not products.empty else ["All Products"]
            selected_product = st.selectbox(
                "Product",
                options=product_options,
                key="completion_product_filter"
            )
            product_id = None
            if selected_product != "All Products" and not products.empty:
                product_id = int(products[products['name'] == selected_product]['id'].iloc[0])
        
        with col4:
            warehouses = queries.get_warehouses()
            warehouse_options = ["All Warehouses"] + warehouses['name'].tolist() if not warehouses.empty else ["All Warehouses"]
            selected_warehouse = st.selectbox(
                "Warehouse",
                options=warehouse_options,
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
        st.info("💡 **Troubleshooting:**\n- Check if VPN is connected\n- Verify network connection\n- Contact IT support if issue persists")
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
        col1, col2, col3 = st.columns(3)
        passed_count = len(receipts[receipts['quality_status'] == 'PASSED'])
        pending_count = len(receipts[receipts['quality_status'] == 'PENDING'])
        failed_count = len(receipts[receipts['quality_status'] == 'FAILED'])
        
        total_receipts = len(receipts)
        
        with col1:
            st.metric("✅ PASSED", passed_count, 
                     f"{calculate_percentage(passed_count, total_receipts)}%")
        with col2:
            st.metric("⏳ PENDING", pending_count,
                     f"{calculate_percentage(pending_count, total_receipts)}%")
        with col3:
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
    if st.session_state.completions_selected_idx is not None and st.session_state.completions_selected_idx < len(display_df):
        display_df.loc[st.session_state.completions_selected_idx, 'Select'] = True
    
    # Format dates: Receipt Date and Order Date
    display_df['receipt_date_display'] = display_df['receipt_date'].apply(
        lambda x: format_datetime_vn(x, '%d-%b-%Y')
    )
    display_df['order_date_display'] = display_df['order_date'].apply(
        lambda x: _format_date_display(x, '%d-%b-%Y')
    )
    
    # Format Product: pt_code | name (package_size)
    display_df['product_display'] = display_df.apply(_format_product_display, axis=1)
    
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
            'order_no', 'product_display', 'qty_display', 'batch_no', 
            'quality_display', 'yield_display', 'warehouse_name'
        ]].rename(columns={
            'receipt_no': 'Receipt No',
            'receipt_date_display': 'Receipt Date',
            'order_date_display': 'Order Date',
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
        disabled=['Receipt No', 'Receipt Date', 'Order Date', 'Order No', 'Product', 
                  'Quantity', 'Batch', 'Quality', 'Yield', 'Warehouse'],
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
            new_selection = [idx for idx in selected_indices if idx != st.session_state.completions_selected_idx]
            if new_selection:
                st.session_state.completions_selected_idx = new_selection[0]
                st.rerun()
        else:
            st.session_state.completions_selected_idx = selected_indices[0]
    else:
        st.session_state.completions_selected_idx = None
    
    # Action buttons - only show when row is selected
    if st.session_state.completions_selected_idx is not None:
        selected_receipt = receipts.iloc[st.session_state.completions_selected_idx]
        
        st.markdown("---")
        # Show selected receipt info with improved product display
        product_info = _format_product_display(selected_receipt)
        st.markdown(f"**Selected:** `{selected_receipt['receipt_no']}` | {selected_receipt['order_no']} | {product_info}")
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            if st.button("👁️ View Details", type="primary", use_container_width=True, key="btn_view_receipt"):
                show_receipt_details_dialog(selected_receipt['id'])
        
        with col2:
            if st.button("✏️ Update Quality", use_container_width=True, key="btn_update_quality"):
                show_update_quality_dialog(selected_receipt['id'])
        
        with col3:
            if st.button("📄 Export PDF", use_container_width=True, key="btn_pdf_receipt"):
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
            st.session_state.completions_selected_idx = None  # Reset selection on page change
            st.rerun()
    
    with col2:
        st.markdown(f"<div style='text-align:center'>Page {page} of {total_pages} | Total: {total_count} receipts</div>", unsafe_allow_html=True)
    
    with col3:
        if st.button("Next ➡️", disabled=page >= total_pages, key="btn_next_receipt"):
            st.session_state.completions_page = page + 1
            st.session_state.completions_selected_idx = None  # Reset selection on page change
            st.rerun()


# ==================== Action Bar ====================

def _render_action_bar(queries: CompletionQueries, filters: Dict[str, Any]):
    """Render action bar"""
    col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
    
    with col1:
        if st.button("✅ Record Output", type="primary", use_container_width=True,
                    key="btn_record_output"):
            st.session_state.completions_view = 'create'
            st.rerun()
    
    with col2:
        if st.button("📊 Export Excel", use_container_width=True, key="btn_export_receipts"):
            _export_receipts_excel(queries, filters)
    
    with col3:
        if st.button("🔄 Refresh", use_container_width=True, key="btn_refresh_completions"):
            st.rerun()
    
    with col4:
        if st.button("❓ Help", use_container_width=True, key="btn_help_completions"):
            st.session_state.completions_view = 'help'
            st.rerun()


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
        export_df['Product'] = export_df.apply(_format_product_display, axis=1)
        
        # Format dates
        export_df['Receipt Date'] = export_df['receipt_date'].apply(
            lambda x: format_datetime_vn(x, '%d/%m/%Y %H:%M') if pd.notna(x) else ''
        )
        export_df['Order Date'] = export_df['order_date'].apply(
            lambda x: _format_date_display(x, '%d/%m/%Y') if pd.notna(x) else ''
        )
        
        # Select and rename columns
        export_df = export_df[[
            'receipt_no', 'Receipt Date', 'Order Date', 'order_no', 'Product', 'pt_code',
            'quantity', 'uom', 'batch_no', 'quality_status', 'yield_rate', 'warehouse_name'
        ]].copy()
        
        export_df.columns = [
            'Receipt No', 'Receipt Date', 'Order Date', 'Order No', 'Product', 'PT Code',
            'Quantity', 'UOM', 'Batch', 'Quality Status', 'Yield Rate', 'Warehouse'
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
    Main function to render the Completions tab
    Called from the main Production page
    """
    _init_session_state()
    
    # Check for pending dialogs
    check_pending_dialogs()
    
    queries = CompletionQueries()
    
    # Check current view
    if st.session_state.completions_view == 'help':
        _render_help_section()
        return
    
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
    
    # Dashboard
    render_dashboard()

    # Filters
    filters = _render_filter_bar(queries)

    # Action bar
    _render_action_bar(queries, filters)

    # Receipts list
    _render_receipts_list(queries, filters)