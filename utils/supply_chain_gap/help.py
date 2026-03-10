# utils/supply_chain_gap/help.py

"""
Help & Training Module for Supply Chain GAP Analysis
Comprehensive guide: usage instructions, definitions, formulas, Q&A

This module serves as:
- In-app help dialog for users
- Training material for new users
- Quick reference during daily operations
"""

import streamlit as st
from typing import Optional
from .constants import (
    STATUS_CONFIG, GAP_CATEGORIES, PRODUCT_TYPES,
    ACTION_TYPES, RAW_MATERIAL_STATUS, THRESHOLDS,
    FIELD_TOOLTIPS, FORMULA_HELP, SUPPLY_SOURCES, DEMAND_SOURCES,
    BOM_TYPES, MATERIAL_TYPES, MATERIAL_CATEGORIES, MAX_BOM_LEVELS,
    PERIOD_TYPES, PERIOD_CONFIG, VERSION
)


# =============================================================================
# FIELD TOOLTIP HELPERS
# =============================================================================

def render_field_tooltip(field_name: str) -> str:
    """Get tooltip text for a field"""
    return FIELD_TOOLTIPS.get(field_name, '')


def render_help_icon(field_name: str, key: str = None):
    """Render help icon with tooltip for a field"""
    tooltip = FIELD_TOOLTIPS.get(field_name, '')
    if tooltip:
        st.markdown(
            f'<span title="{tooltip}" style="cursor: help; color: #6B7280;">ℹ️</span>',
            unsafe_allow_html=True
        )


# =============================================================================
# FORMULA HELP SECTION (programmatic rendering)
# =============================================================================

def render_formula_help_section(section_key: str = 'all'):
    """
    Render formula help section from FORMULA_HELP constants.
    
    Args:
        section_key: 'level_1', 'level_2', 'classification', 'status_thresholds', 'actions', or 'all'
    """
    
    if section_key == 'all':
        sections = ['level_1', 'level_2', 'classification', 'status_thresholds', 'actions', 'period_gap']
    else:
        sections = [section_key] if section_key in FORMULA_HELP else []
    
    for key in sections:
        section = FORMULA_HELP.get(key, {})
        if not section:
            continue
        
        st.markdown(f"### {section.get('title', key)}")
        st.caption(section.get('description', ''))
        
        if 'formulas' in section:
            formula_data = []
            for formula in section['formulas']:
                formula_data.append({
                    'Field': f"`{formula[0]}`",
                    'Formula': f"`{formula[1]}`",
                    'Description': formula[2]
                })
            st.table(formula_data)
        
        if 'items' in section:
            for item in section['items']:
                if len(item) == 2:
                    st.markdown(f"- **{item[0]}**: {item[1]}")
                elif len(item) == 3:
                    st.markdown(f"- {item[2]} **{item[0]}**: {item[1]}")
        
        if 'shortage' in section:
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**🔴 Shortage Levels**")
                for status, threshold, icon in section['shortage']:
                    st.markdown(f"{icon} `{status}`: Coverage {threshold}")
            with col2:
                st.markdown("**🟢 Surplus Levels**")
                for status, threshold, icon in section['surplus']:
                    st.markdown(f"{icon} `{status}`: Coverage {threshold}")
        
        st.divider()


# =============================================================================
# MAIN HELP - POPOVER VERSION (preferred)
# =============================================================================

def render_help_popover():
    """
    Render help as a popover button — compact, accessible from anywhere.
    Uses tabs inside popover for navigation.
    """
    
    with st.popover("❓"):
        
        tab1, tab2, tab3 = st.tabs([
            "📖 Hướng dẫn",
            "📘 Định nghĩa & Công thức",
            "💬 Q&A"
        ])
        
        with tab1:
            _render_usage_guide()
        
        with tab2:
            _render_glossary()
            st.divider()
            _render_formulas()
        
        with tab3:
            _render_faq()


# =============================================================================
# MAIN HELP - TAB VERSION (for use inside st.tabs)
# =============================================================================

def render_help_tab():
    """
    Render comprehensive help content directly inside a tab.
    Uses expanders for sections so user can expand/collapse as needed.
    """
    
    st.markdown(
        f"#### 📖 Hướng dẫn & Tài liệu tham khảo — v{VERSION}",
    )
    st.caption("Nhấn vào từng mục để xem chi tiết. Có thể mở nhiều mục cùng lúc.")
    
    with st.expander("📘 **Hướng dẫn sử dụng**", expanded=False):
        _render_usage_guide()
    
    with st.expander("📗 **Thuật ngữ & Định nghĩa**", expanded=False):
        _render_glossary()
    
    with st.expander("📙 **Công thức tính toán**", expanded=False):
        _render_formulas()
    
    with st.expander("📕 **Câu hỏi thường gặp (FAQ)**", expanded=False):
        _render_faq()


# =============================================================================
# MAIN HELP - EXPANDER VERSION (legacy, for backward compatibility)
# =============================================================================

def render_help_dialog():
    """
    Render help as an expander (legacy).
    Prefer render_help_tab() for tab-based layout.
    """
    
    with st.expander("📖 **Hướng dẫn & Tài liệu tham khảo**", expanded=False):
        
        tab1, tab2, tab3, tab4 = st.tabs([
            "📘 Hướng dẫn sử dụng",
            "📗 Thuật ngữ & Định nghĩa",
            "📙 Công thức tính toán",
            "📕 Câu hỏi thường gặp"
        ])
        
        with tab1:
            _render_usage_guide()
        
        with tab2:
            _render_glossary()
        
        with tab3:
            _render_formulas()
        
        with tab4:
            _render_faq()


# =============================================================================
# TAB 1: HƯỚNG DẪN SỬ DỤNG
# =============================================================================

def _render_usage_guide():
    """Comprehensive step-by-step usage guide"""
    
    st.markdown("## 📘 Hướng dẫn sử dụng Supply Chain GAP Analysis")
    st.caption(f"Version {VERSION} — Tài liệu dành cho người dùng mới và tham khảo nhanh")
    
    # -------------------------------------------------------------------------
    # Tổng quan
    # -------------------------------------------------------------------------
    st.markdown("### 1. Tổng quan")
    st.markdown("""
    **Supply Chain GAP Analysis** là công cụ phân tích chênh lệch cung-cầu trong chuỗi cung ứng, 
    giúp nhận diện sản phẩm thiếu hụt (shortage) hoặc dư thừa (surplus) và đề xuất hành động 
    (tạo MO, PO) để đảm bảo đáp ứng nhu cầu khách hàng.
    
    Hệ thống phân tích **đa cấp (multi-level)**:
    - **Level 1 — Finished Goods (FG):** So sánh tổng nguồn cung vs tổng nhu cầu cho từng sản phẩm thành phẩm
    - **Level 2+ — Materials (Multi-level BOM):** Với sản phẩm Manufacturing có shortage, phân tích nguyên vật liệu qua BOM explosion đa cấp:
      - Nếu material là **bán thành phẩm** (có BOM riêng) → kiểm tra tồn kho → nếu thiếu → đi sâu thêm 1 level
      - Nếu material là **nguyên liệu** (không có BOM) → tính GAP để đề xuất mua
    - **Period Timeline:** Phân tích GAP theo thời kỳ (tuần/tháng) với carry-forward — biết **KHI NÀO** thiếu, không chỉ thiếu bao nhiêu
    """)
    
    st.info("""
    💡 **Tip:** Hệ thống hỗ trợ BOM nhiều cấp (A → B → C). Ví dụ: FG cần bán thành phẩm B, 
    B cần nguyên liệu A. Nếu B đã có tồn kho đủ, hệ thống sẽ **không** tính tiếp nhu cầu A (supply netting).
    Sản phẩm Trading (không có BOM) sẽ được đề xuất tạo PO mua trực tiếp.
    
    📅 **Period Timeline:** Mỗi tab (FG, Manufacturing, Trading, Raw Materials) đều có 2 phần:
    1. **Net GAP** — tổng thể thiếu/thừa bao nhiêu
    2. **Period Timeline** — thiếu/thừa KHI NÀO (theo tuần/tháng), với carry-forward và backlog
    """)
    
    # -------------------------------------------------------------------------
    # Quy trình sử dụng
    # -------------------------------------------------------------------------
    st.markdown("### 2. Quy trình sử dụng")
    
    st.markdown("#### Bước 1: Thiết lập bộ lọc (Configuration)")
    st.markdown("""
    Mở phần **🔧 Configuration** để chọn các điều kiện phân tích:
    
    | Bộ lọc | Mô tả | Gợi ý |
    |--------|-------|-------|
    | **Entity** | Chọn công ty/đơn vị cần phân tích | Chọn "All" để xem toàn bộ |
    | **Brands** | Lọc theo thương hiệu sản phẩm | Bỏ trống = tất cả brands |
    | **Products** | Lọc theo sản phẩm cụ thể | Dùng khi cần kiểm tra 1-2 sản phẩm |
    """)
    
    st.markdown("#### Bước 2: Chọn nguồn cung & nhu cầu")
    st.markdown("""
    | Nguồn cung (Supply Sources) | Ý nghĩa |
    |----------------------------|---------|
    | 📦 **Inventory** | Tồn kho hiện tại trong kho |
    | 📋 **CAN Pending** | Hàng đang chờ nhập kho (CAN = Consignment Advice Note) |
    | 🚛 **Transfer** | Hàng đang chuyển kho |
    | 📝 **Purchase Order** | Đơn hàng mua đang chờ giao |
    
    | Nguồn nhu cầu (Demand Sources) | Ý nghĩa |
    |-------------------------------|---------|
    | ✔ **Confirmed Orders** | Đơn hàng đã xác nhận (OC Pending) |
    | 📊 **Forecast** | Dự báo nhu cầu từ planning |
    """)
    
    st.warning("""
    ⚠️ **Lưu ý quan trọng:** Việc bỏ chọn một nguồn cung/cầu sẽ ảnh hưởng đến kết quả phân tích. 
    Ví dụ: Nếu bỏ chọn **Purchase Order**, hệ thống sẽ không tính hàng PO đang chờ vào nguồn cung, 
    có thể dẫn đến nhiều sản phẩm bị đánh giá shortage hơn thực tế.
    """)
    
    st.markdown("#### Bước 3: Tùy chọn phân tích (Options)")
    st.markdown("""
    | Tùy chọn | Mặc định | Ý nghĩa |
    |----------|----------|---------|
    | **FG Safety Stock** | ✅ Bật | Trừ tồn kho an toàn FG khỏi nguồn cung khả dụng |
    | **Raw Safety Stock** | ✅ Bật | Trừ tồn kho an toàn NVL khỏi nguồn cung khả dụng |
    | **Exclude Expired** | ✅ Bật | Loại bỏ tồn kho hết hạn khỏi nguồn cung |
    | **Alternatives** | ✅ Bật | Phân tích NVL thay thế khi NVL chính thiếu |
    | **Existing MO** | ✅ Bật | Tính thêm nhu cầu NVL từ MO đang pending |
    """)
    
    st.markdown("##### 📅 Period Analysis")
    st.markdown("""
    | Tùy chọn | Mặc định | Ý nghĩa |
    |----------|----------|---------|
    | **Period Type** | Weekly | Group supply/demand theo tuần (Weekly) hoặc tháng (Monthly) |
    | **Track Backlog** | ✅ Bật | Carry shortage sang kỳ tiếp theo. Khi bật: shortage period N → thêm demand period N+1 |
    """)
    
    st.info("""
    💡 **Track Backlog:** Khi bật, nhu cầu chưa đáp ứng (backlog) từ kỳ trước sẽ cộng vào nhu cầu kỳ hiện tại.
    Điều này cho thấy tình trạng "nợ đọng" tích lũy qua các kỳ — quan trọng cho lập kế hoạch sản xuất và đặt hàng.
    """)
    
    st.info("""
    💡 **Khi nào tắt Safety Stock?**
    - Khi muốn xem "true gap" (chênh lệch thực sự không tính safety stock)
    - Khi safety stock chưa được thiết lập chính xác cho sản phẩm
    - Khi đánh giá khả năng đáp ứng tối đa (worst case)
    """)
    
    st.markdown("#### Bước 4: Chạy phân tích")
    st.markdown("""
    - Nhấn **🔬 Analyze** để chạy phân tích
    - Hệ thống sẽ tính toán toàn bộ: FG GAP → Classification → Multi-level Material GAP → Actions → **Period Timeline**
    - Quá trình BOM explosion đa cấp: tự động đi sâu qua các bán thành phẩm cho đến nguyên liệu cuối cùng
    - Period Timeline tự động lấy **toàn bộ data** từ supply/demand (không cần chọn date range)
    - Kết quả hiển thị qua 5 tab, mỗi tab có 2 phần: Net GAP + Period Timeline
    - Nhấn **🔄 Reset** để xóa bộ lọc và kết quả, bắt đầu lại
    """)
    
    # -------------------------------------------------------------------------
    # Đọc hiểu kết quả
    # -------------------------------------------------------------------------
    st.markdown("### 3. Đọc hiểu kết quả")
    
    st.markdown("#### 📊 Tab FG Overview")
    st.markdown("""
    Đây là tab chính, hiển thị toàn cảnh cung-cầu sản phẩm thành phẩm:
    
    **Phần 1 — Net GAP:**
    - **Donut chart** (trái): Phân bố trạng thái GAP (Shortage / Optimal / Surplus / Inactive)
    - **Bar chart** (phải): Top 10 sản phẩm có giá trị rủi ro cao nhất (At Risk Value)
    - **Status badges**: Số lượng sản phẩm theo từng trạng thái chi tiết
    - **Quick filter**: Lọc nhanh theo nhóm (All / Shortage / Surplus / Critical)
    - **Bảng dữ liệu**: Chi tiết từng sản phẩm với Supply, Demand, GAP, Coverage, Status
    
    **Phần 2 — 📅 Period Timeline:**
    - **KPIs**: Tổng số kỳ, kỳ shortage, tỷ lệ fill trung bình, backlog cuối cùng
    - **Charts**: Shortage theo kỳ (bar) + Timeline GAP top sản phẩm (line)
    - **Pivot View** (mở rộng): Bảng cross-tab products × periods, 🔴 = kỳ quá khứ, 🟢 = hiện tại/tương lai
    - **Bảng chi tiết**: Begin Inv → Supply In → Available → Demand → Backlog → GAP → Fill % → Status
    - **Filters**: Product, Status (Shortage/Fulfilled), Period (Past/Future), Product Type (Matched/Demand Only/Supply Only)
    
    **Cách đọc bảng Net GAP:**
    
    | Cột | Ý nghĩa | Lưu ý |
    |-----|---------|-------|
    | Supply | Tổng nguồn cung khả dụng (đã trừ safety stock) | Không bao gồm hàng hết hạn (nếu bật Exclude Expired) |
    | Demand | Tổng nhu cầu từ OC + Forecast | Theo các nguồn đã chọn |
    | GAP | Supply - Demand | Âm = thiếu, Dương = dư |
    | Coverage | Supply ÷ Demand × 100% | Dưới 100% = không đủ đáp ứng |
    | Status | Phân loại theo mức Coverage | Xem chi tiết ở tab Thuật ngữ |
    
    **Cách đọc bảng Period GAP:**
    
    | Cột | Ý nghĩa | Lưu ý |
    |-----|---------|-------|
    | 🔴 | Kỳ quá khứ (đã qua) | Trống = kỳ hiện tại hoặc tương lai |
    | Begin Inv | Tồn kho đầu kỳ = carry-forward từ kỳ trước | Kỳ đầu tiên = 0 |
    | Supply In | Supply nhận trong kỳ (PO ETA, CAN arrival...) | Chỉ tính supply có ngày thuộc kỳ |
    | Available | Begin Inv + Supply In | Tổng hàng sẵn sàng trong kỳ |
    | Demand | Nhu cầu trong kỳ (OC required_date, forecast) | Chỉ tính demand có ngày thuộc kỳ |
    | Backlog In | Nhu cầu tồn đọng từ kỳ trước | Chỉ hiển thị khi bật Track Backlog |
    | Total Need | Demand + Backlog In | Tổng nhu cầu thực tế phải đáp ứng |
    | GAP | Available - Total Need | Âm = thiếu trong kỳ này |
    | Fill % | Available ÷ Total Need × 100% | Progress bar, <100% = không đáp ứng hết |
    | Backlog Out | Nhu cầu tồn đọng mang sang kỳ sau | = |GAP| khi shortage |
    | Type | Matched / Demand Only / Supply Only | Sản phẩm có cả supply lẫn demand, hay chỉ 1 bên |
    """)
    
    st.markdown("#### 🏭 Tab Manufacturing")
    st.markdown("""
    Hiển thị sản phẩm **có BOM** (có thể tự sản xuất) đang thiếu hụt:
    
    **Phần 1 — Net GAP:**
    - **Pie chart**: Tỷ lệ Manufacturing vs Trading
    - **Bảng dữ liệu**: Mỗi sản phẩm kèm trạng thái sản xuất:
      - ✅ **Can Produce**: Đủ NVL, có thể tạo MO ngay
      - ⚠️ **Cannot Produce**: Thiếu NVL, cần chờ hoặc mua thêm
    - **Reason**: Lý do cụ thể (NVL đủ, NVL thiếu, có alternative, ...)
    
    **Phần 2 — 📅 Period Timeline:**
    - Chỉ hiển thị sản phẩm Manufacturing → biết KHI NÀO cần sản xuất
    - Cùng carry-forward logic, nhưng chỉ lọc sản phẩm có BOM
    """)
    
    st.markdown("#### 🛒 Tab Trading")
    st.markdown("""
    Hiển thị sản phẩm **không có BOM** (cần mua trực tiếp) đang thiếu hụt:
    
    **Phần 1 — Net GAP:**
    - Tất cả sản phẩm Trading với shortage sẽ được đề xuất **Create PO**
    - Đây là sản phẩm không thể tự sản xuất, phải mua từ nhà cung cấp
    
    **Phần 2 — 📅 Period Timeline:**
    - Chỉ hiển thị sản phẩm Trading → biết KHI NÀO cần đặt PO (tính ngược theo lead time NCC)
    """)
    
    st.markdown("#### 🧪 Tab Raw Materials")
    st.markdown("""
    Phân tích nguyên vật liệu đa cấp cho sản phẩm Manufacturing có shortage:
    
    **🔶 Semi-Finished Products (Supply Netting)** — chỉ hiển thị khi có BOM đa cấp:
    - Bán thành phẩm là material có BOM riêng (ví dụ: B trong A → B → C)
    - Supply netting: Nếu tồn kho bán thành phẩm đủ → không cần tính tiếp BOM cấp dưới
    - Cột "Netting": cho biết supply đủ (✅ Supply covers) hay thiếu (🔽 Shortage propagates)
    
    **🧪 Raw Materials (Leaf Nodes)** — nguyên liệu cuối cùng:
    - **Bar chart**: Phân bố trạng thái GAP của NVL
    - **Bộ lọc nhanh**:
      - "Primary only": Chỉ xem NVL chính
      - "Shortage only": Chỉ xem NVL đang thiếu
      - "BOM Level": Lọc theo cấp BOM (nếu multi-level)
    - **Bảng dữ liệu**: Required, Supply, GAP, Coverage, BOM Level
    
    **Cột "Required" được tính từ BOM explosion đa cấp:**
    - Hệ thống đi qua từng cấp BOM, trừ tồn kho bán thành phẩm tại mỗi cấp (supply netting)
    - Chỉ nhu cầu thực sự (sau netting) được tính tiếp cho cấp dưới
    - Nếu bật "Existing MO": Cộng thêm nhu cầu từ MO đang pending chưa xuất kho
    
    **Phần 2 — 📅 Raw Material Period Timeline:**
    - Nhu cầu NVL theo kỳ = BOM explosion từ FG Manufacturing shortage **theo từng period**
    - Supply NVL: tổng tồn kho + PO đặt vào period đầu tiên (available now)
    - Carry-forward: surplus NVL từ kỳ trước chuyển sang kỳ sau
    - Trả lời câu hỏi: **"Khi nào cần mua NVL?"** — rất quan trọng cho procurement lead time
    """)
    
    st.markdown("#### 📋 Tab Actions")
    st.markdown("""
    Đề xuất hành động cần thực hiện, chia thành 3 nhóm:
    
    | Nhóm | Đối tượng | Hành động |
    |------|-----------|-----------|
    | 🏭 **MO** | Sản phẩm Manufacturing + Bán thành phẩm | CREATE_MO (đủ NVL), CREATE_MO_SEMI (bán thành phẩm), WAIT_RAW (thiếu NVL), USE_ALTERNATIVE (có NVL thay thế) |
    | 🛒 **PO-FG** | Sản phẩm Trading | CREATE_PO_FG (mua thành phẩm trực tiếp) |
    | 📦 **PO-Raw** | Nguyên vật liệu thiếu | CREATE_PO_RAW (mua NVL cho sản xuất) |
    
    Mỗi action kèm theo: mã sản phẩm, số lượng cần, đơn vị tính, mức ưu tiên, và lý do.
    """)
    
    # -------------------------------------------------------------------------
    # Export
    # -------------------------------------------------------------------------
    st.markdown("### 4. Xuất báo cáo (Export)")
    st.markdown("""
    Nhấn **📥 Export Excel** để tải file Excel chứa toàn bộ kết quả phân tích:
    
    | Sheet | Nội dung |
    |-------|---------|
    | **Summary** | Tổng quan metrics + bộ lọc đã dùng + period analysis metrics |
    | **FG GAP** | Bảng chi tiết FG GAP toàn bộ sản phẩm |
    | **Manufacturing** | Sản phẩm Manufacturing có shortage + trạng thái sản xuất |
    | **Trading** | Sản phẩm Trading có shortage |
    | **Semi-Finished** | Bán thành phẩm + supply netting status (nếu BOM đa cấp) |
    | **Raw Materials** | Bảng chi tiết NVL GAP + BOM Level |
    | **Actions** | Toàn bộ action recommendations |
    | **Period GAP** | FG Period Timeline — GAP theo kỳ với carry-forward/backlog |
    | **Raw Period GAP** | Raw Material Period Timeline — nhu cầu NVL theo kỳ |
    
    File Excel có thể dùng để: báo cáo cho management, chia sẻ với team mua hàng/sản xuất, 
    lưu trữ lịch sử phân tích.
    """)
    
    # -------------------------------------------------------------------------
    # Tips & Best practices
    # -------------------------------------------------------------------------
    st.markdown("### 5. Mẹo sử dụng hiệu quả")
    st.markdown("""
    1. **Phân tích hàng ngày:** Chạy phân tích mỗi sáng để nắm tình hình cung-cầu mới nhất
    2. **Kiểm tra Critical trước:** Dùng Quick Filter "🚨 Critical" để ưu tiên xử lý sản phẩm nghiêm trọng nhất
    3. **Xem Period Timeline:** Sau khi biết sản phẩm nào shortage, xem Period Timeline để biết **khi nào** 
       shortage xảy ra → lên kế hoạch sản xuất/đặt hàng theo lead time
    4. **Raw Material Period:** Xem tab Raw Materials → Period Timeline để biết khi nào cần mua NVL → 
       đặt PO trước lead time nhà cung cấp
    5. **Pivot View:** Mở Pivot View để thấy tổng quan GAP qua tất cả periods — 
       dễ spot pattern (ví dụ: shortage tập trung vào Q1)
    6. **Filter Past/Future:** Dùng filter "🟢 Future Only" để tập trung vào các kỳ sắp tới, 
       bỏ qua kỳ đã qua (🔴)
    7. **Đối chiếu với thực tế:** Kết quả phân tích dựa trên dữ liệu hệ thống — 
       luôn đối chiếu với tình hình thực tế kho, sản xuất, và giao hàng
    8. **So sánh Weekly vs Monthly:** Chạy 2 lần (Weekly + Monthly) — Weekly cho chi tiết, 
       Monthly cho xu hướng dài hạn
    9. **Export định kỳ:** Xuất Excel hàng tuần để theo dõi xu hướng thay đổi GAP theo thời gian
    """)


# =============================================================================
# TAB 2: THUẬT NGỮ & ĐỊNH NGHĨA
# =============================================================================

def _render_glossary():
    """Glossary of terms and definitions"""
    
    st.markdown("## 📗 Thuật ngữ & Định nghĩa")
    st.caption("Tra cứu nhanh các thuật ngữ, khái niệm, và trạng thái trong hệ thống")
    
    # -------------------------------------------------------------------------
    # Khái niệm cốt lõi
    # -------------------------------------------------------------------------
    st.markdown("### 1. Khái niệm cốt lõi")
    
    st.markdown("""
    | Thuật ngữ | Tiếng Việt | Định nghĩa |
    |-----------|-----------|------------|
    | **GAP** | Chênh lệch | Hiệu số giữa nguồn cung và nhu cầu. Dương = surplus, Âm = shortage |
    | **Supply** | Nguồn cung | Tổng số lượng hàng khả dụng từ các nguồn (tồn kho, PO, transfer, ...) |
    | **Demand** | Nhu cầu | Tổng số lượng hàng cần cho đơn hàng và dự báo |
    | **Safety Stock** | Tồn kho an toàn | Mức tồn kho tối thiểu cần duy trì để phòng ngừa rủi ro |
    | **Coverage Ratio** | Tỷ lệ đáp ứng | Available Supply ÷ Total Demand (%) — cho biết đáp ứng được bao nhiêu % nhu cầu |
    | **At Risk Value** | Giá trị rủi ro | Giá trị tiền (USD) có nguy cơ mất nếu không đáp ứng được nhu cầu |
    | **Net GAP** | Chênh lệch ròng | Available Supply - Total Demand (có tính safety stock) |
    | **True GAP** | Chênh lệch thực | Total Supply - Total Demand (không tính safety stock) |
    """)
    
    # -------------------------------------------------------------------------
    # Phân loại sản phẩm
    # -------------------------------------------------------------------------
    st.markdown("### 2. Phân loại sản phẩm (Product Classification)")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("""
        #### 🏭 Manufacturing
        - Sản phẩm **có BOM** (Bill of Materials)
        - Có thể **tự sản xuất** từ nguyên vật liệu
        - Khi shortage → Kiểm tra NVL → Tạo MO hoặc chờ NVL
        - BOM types: Cutting ✂️, Repacking 📦, Kitting 🔧, Assembly 🔩
        """)
    
    with col2:
        st.markdown("""
        #### 🛒 Trading
        - Sản phẩm **không có BOM**
        - **Không thể tự sản xuất**, phải mua từ nhà cung cấp
        - Khi shortage → Tạo PO mua trực tiếp
        - Ví dụ: hàng nhập khẩu, hàng thương mại
        """)
    
    # -------------------------------------------------------------------------
    # Nguồn cung & nhu cầu
    # -------------------------------------------------------------------------
    st.markdown("### 3. Nguồn cung (Supply Sources)")
    st.markdown("""
    | Nguồn | Key | Mô tả | Ưu tiên |
    |-------|-----|-------|---------|
    | 📦 **Inventory** | INVENTORY | Tồn kho thực tế đang có trong kho | Cao nhất — hàng sẵn sàng xuất |
    | 📋 **CAN Pending** | CAN_PENDING | Hàng đã có CAN nhưng chưa nhập kho (đang transit) | Cao — sẽ nhập trong thời gian ngắn |
    | 🚛 **Warehouse Transfer** | WAREHOUSE_TRANSFER | Hàng đang chuyển giữa các kho nội bộ | Trung bình — phụ thuộc logistics |
    | 📝 **Purchase Order** | PURCHASE_ORDER | Đơn hàng mua đã đặt, chờ nhà cung cấp giao | Thấp nhất — phụ thuộc NCC |
    """)
    
    st.markdown("### 4. Nguồn nhu cầu (Demand Sources)")
    st.markdown("""
    | Nguồn | Key | Mô tả | Ưu tiên |
    |-------|-----|-------|---------|
    | ✔ **Confirmed Orders** | OC_PENDING | Đơn hàng xác nhận (OC = Order Confirmation) chưa giao | Cao — cam kết với khách hàng |
    | 📊 **Forecast** | FORECAST | Dự báo nhu cầu từ bộ phận planning | Thấp hơn — dự báo có thể thay đổi |
    """)
    
    # -------------------------------------------------------------------------
    # Trạng thái GAP
    # -------------------------------------------------------------------------
    st.markdown("### 5. Trạng thái GAP (Status)")
    
    st.markdown("#### 🔴 Nhóm Shortage (Thiếu hụt)")
    st.markdown("""
    | Trạng thái | Coverage | Icon | Ý nghĩa | Hành động đề xuất |
    |-----------|----------|------|---------|-------------------|
    | **CRITICAL_SHORTAGE** | < 25% | 🚨 | Gần như không có hàng | Xử lý ngay lập tức |
    | **SEVERE_SHORTAGE** | < 50% | 🔴 | Chỉ đáp ứng dưới 50% nhu cầu | Ưu tiên cao |
    | **HIGH_SHORTAGE** | < 75% | 🟠 | Đáp ứng 50-75% nhu cầu | Cần hành động sớm |
    | **MODERATE_SHORTAGE** | < 90% | 🟡 | Gần đủ nhưng vẫn thiếu | Theo dõi và bổ sung |
    | **LIGHT_SHORTAGE** | < 100% | ⚠️ | Thiếu nhẹ, gần đủ | Theo dõi |
    """)
    
    st.markdown("#### 🟢 Nhóm Optimal & Surplus")
    st.markdown("""
    | Trạng thái | Coverage | Icon | Ý nghĩa | Lưu ý |
    |-----------|----------|------|---------|-------|
    | **BALANCED** | = 100% | ✅ | Cung = Cầu hoàn hảo | Lý tưởng nhưng hiếm xảy ra |
    | **LIGHT_SURPLUS** | ≤ 125% | 🔵 | Dư nhẹ, buffer hợp lý | Tốt — có dự phòng |
    | **MODERATE_SURPLUS** | ≤ 175% | 🟣 | Dư khá nhiều | Cân nhắc giảm mua/sản xuất |
    | **HIGH_SURPLUS** | ≤ 250% | 🟠 | Dư nhiều, tồn kho cao | Xem xét giảm tồn kho |
    | **SEVERE_SURPLUS** | > 250% | 🔴 | Tồn kho quá nhiều | Rủi ro hết hạn, đọng vốn |
    """)
    
    st.markdown("#### ⚪ Nhóm Inactive")
    st.markdown("""
    | Trạng thái | Điều kiện | Ý nghĩa |
    |-----------|-----------|---------|
    | **NO_DEMAND** | Có supply, không có demand | Tồn kho nhưng không có nhu cầu — có thể hàng slow-moving |
    | **NO_ACTIVITY** | Không có supply lẫn demand | Sản phẩm không hoạt động trong kỳ phân tích |
    """)
    
    # -------------------------------------------------------------------------
    # Nguyên vật liệu
    # -------------------------------------------------------------------------
    st.markdown("### 6. Nguyên vật liệu (Raw Materials)")
    
    st.markdown("""
    | Thuật ngữ | Định nghĩa |
    |-----------|------------|
    | **Primary Material** | NVL chính theo BOM — được sử dụng mặc định khi sản xuất |
    | **Alternative Material** | NVL thay thế — có thể dùng khi NVL chính không đủ |
    | **BOM Output Qty** | Số lượng thành phẩm tạo ra từ 1 batch sản xuất theo BOM |
    | **Qty Per Output** | Số lượng NVL cần cho 1 đơn vị thành phẩm |
    | **Scrap Rate** | Tỷ lệ hao hụt (%) trong quá trình sản xuất |
    | **Existing MO Demand** | Nhu cầu NVL từ các Manufacturing Order đang pending (chưa xuất kho) |
    """)
    
    st.markdown("### 7. BOM đa cấp (Multi-Level BOM)")
    st.markdown("""
    | Thuật ngữ | Định nghĩa |
    |-----------|------------|
    | **Semi-Finished Product** 🔶 | Bán thành phẩm — material có BOM riêng, có thể tự sản xuất từ NVL cấp dưới |
    | **Raw Material (Leaf)** 🧪 | Nguyên liệu cuối cùng — không có BOM, phải mua từ nhà cung cấp |
    | **BOM Level** | Cấp trong cây BOM (Level 1 = material trực tiếp, Level 2 = material của bán thành phẩm, ...) |
    | **Supply Netting** | Trừ tồn kho bán thành phẩm trước khi tính nhu cầu cấp dưới. Nếu tồn kho đủ → không cần sản xuất → không cần NVL cấp dưới |
    | **BOM Path** | Đường đi trong cây BOM: FG → Semi-B → Raw-A. Dùng để phát hiện cycle (vòng lặp) |
    | **Cumulative Qty** | Số lượng NVL cần cho 1 đơn vị FG gốc, tính compound qua tất cả cấp BOM |
    """)
    
    st.info(f"""
    💡 **Giới hạn BOM depth:** Tối đa {MAX_BOM_LEVELS} cấp. Cycle detection tự động ngăn vòng lặp vô hạn.
    """)
    
    st.markdown("### 8. Phân loại vật liệu trong BOM")
    st.markdown("""
    | Loại | Icon | Mô tả |
    |------|------|-------|
    | **Semi-Finished** | 🔶 | Bán thành phẩm — có BOM riêng, có thể sản xuất |
    | **Raw Material** | 🧪 | Nguyên liệu chính cho sản xuất (leaf node) |
    | **Packaging** | 📦 | Vật liệu đóng gói |
    | **Consumable** | 🔧 | Vật tư tiêu hao |
    """)
    
    # -------------------------------------------------------------------------
    # Period GAP Analysis
    # -------------------------------------------------------------------------
    st.markdown("### 9. Period GAP Analysis (Phân tích theo kỳ)")
    
    st.markdown("""
    | Thuật ngữ | Tiếng Việt | Định nghĩa |
    |-----------|-----------|------------|
    | **Period** | Kỳ phân tích | Đơn vị thời gian: Weekly (tuần ISO) hoặc Monthly (tháng) |
    | **Carry Forward** | Chuyển sang kỳ sau | Surplus cuối kỳ N → tồn kho đầu kỳ N+1 |
    | **Backlog** | Nhu cầu tồn đọng | Shortage cuối kỳ N → thêm demand đầu kỳ N+1 |
    | **Begin Inventory** | Tồn đầu kỳ | = Carry forward từ kỳ trước (kỳ đầu = 0) |
    | **Supply In Period** | Supply trong kỳ | Supply có availability_date/ETA thuộc kỳ |
    | **Demand In Period** | Demand trong kỳ | Demand có required_date/ETD thuộc kỳ |
    | **Effective Demand** | Nhu cầu thực tế | Demand in period + Backlog from previous |
    | **Fulfillment Rate** | Tỷ lệ đáp ứng | (Available / Effective Demand) × 100% |
    | **Past Period** 🔴 | Kỳ quá khứ | Kỳ đã kết thúc (week/month đã qua) — đánh dấu bằng 🔴 |
    | **Product Type** | Loại sản phẩm | Matched (cả supply + demand), Demand Only, Supply Only |
    | **Pivot View** | Bảng chéo | Cross-tab products × periods, color-coded theo GAP |
    """)
    
    st.info("""
    💡 **Carry Forward vs Backlog:**
    - **Carry Forward** (surplus): Khi supply > demand → dư thừa mang sang kỳ sau như tồn kho
    - **Backlog** (shortage): Khi demand > supply → thiếu hụt cộng vào demand kỳ sau
    - Khi tắt Track Backlog: chỉ carry forward dương (shortage không mang sang kỳ sau)
    - Khi bật Track Backlog (mặc định): backlog tích lũy → phản ánh đúng "nợ đọng" thực tế
    """)
    
    # -------------------------------------------------------------------------
    # Action types
    # -------------------------------------------------------------------------
    st.markdown("### 10. Loại hành động (Action Types)")
    st.markdown("""
    | Action | Icon | Điều kiện áp dụng | Mô tả chi tiết |
    |--------|------|-------------------|----------------|
    | **CREATE_MO** | 🏭 | Manufacturing + NVL đầy đủ | Tạo lệnh sản xuất (Manufacturing Order) để sản xuất FG từ NVL hiện có |
    | **CREATE_MO_SEMI** | 🔶 | Bán thành phẩm bị shortage | Tạo MO để sản xuất bán thành phẩm (intermediate product) |
    | **WAIT_RAW** | ⏳ | Manufacturing + NVL chính thiếu, không có alternative | Chờ NVL về (từ PO đang chờ hoặc cần tạo PO mua NVL) |
    | **USE_ALTERNATIVE** | 🔄 | Manufacturing + NVL chính thiếu + có alternative đủ | Sử dụng NVL thay thế có sẵn để sản xuất |
    | **CREATE_PO_FG** | 🛒 | Trading product có shortage | Tạo Purchase Order mua thành phẩm trực tiếp từ NCC |
    | **CREATE_PO_RAW** | 📦 | NVL chính thiếu + không có alternative | Tạo Purchase Order mua NVL cho sản xuất |
    """)
    
    # -------------------------------------------------------------------------
    # Giải thích các cột trong bảng
    # -------------------------------------------------------------------------
    st.markdown("### 11. Giải thích các cột dữ liệu")
    
    st.markdown("#### Bảng FG GAP")
    field_data = []
    fg_fields = [
        'total_supply', 'total_demand', 'safety_stock_qty', 'safety_gap',
        'available_supply', 'net_gap', 'true_gap', 'coverage_ratio',
        'at_risk_value', 'customer_count'
    ]
    for f in fg_fields:
        tooltip = FIELD_TOOLTIPS.get(f, '')
        if tooltip:
            field_data.append({'Field': f"`{f}`", 'Mô tả': tooltip})
    if field_data:
        st.table(field_data)
    
    st.markdown("#### Bảng Raw Material GAP")
    raw_fields = [
        'required_qty', 'existing_mo_demand', 'total_required_qty',
        'bom_output_quantity', 'quantity_per_output', 'scrap_rate',
        'can_produce', 'limiting_materials', 'is_primary', 'alternative_priority'
    ]
    raw_data = []
    for f in raw_fields:
        tooltip = FIELD_TOOLTIPS.get(f, '')
        if tooltip:
            raw_data.append({'Field': f"`{f}`", 'Mô tả': tooltip})
    if raw_data:
        st.table(raw_data)
    
    st.markdown("#### Bảng Period GAP")
    period_fields = [
        ('begin_inventory', 'Tồn kho đầu kỳ = carry forward từ kỳ trước (kỳ đầu tiên = 0)'),
        ('supply_in_period', 'Nguồn cung nhận trong kỳ (supply có availability_date thuộc kỳ)'),
        ('total_available', 'Begin Inv + Supply In Period — tổng hàng sẵn sàng trong kỳ'),
        ('demand_in_period', 'Nhu cầu trong kỳ (demand có required_date thuộc kỳ)'),
        ('backlog_from_prev', 'Nhu cầu tồn đọng từ kỳ trước (chỉ hiển thị khi Track Backlog = ON)'),
        ('effective_demand', 'Demand + Backlog = tổng nhu cầu thực tế cần đáp ứng trong kỳ'),
        ('gap_quantity', 'Total Available - Effective Demand (hoặc - Demand nếu Backlog OFF)'),
        ('fulfillment_rate', 'Total Available ÷ Effective Demand × 100%'),
        ('backlog_to_next', 'Shortage mang sang kỳ sau = |GAP| khi GAP < 0'),
        ('is_past', '🔴 = kỳ đã kết thúc (weekly: cuối tuần < today, monthly: tháng sau ≤ today)'),
        ('product_type', 'Matched (có cả supply + demand) / Demand Only / Supply Only'),
    ]
    st.table([{'Field': f'`{f}`', 'Mô tả': d} for f, d in period_fields])


# =============================================================================
# TAB 3: CÔNG THỨC TÍNH TOÁN
# =============================================================================

def _render_formulas():
    """Detailed formula documentation"""
    
    st.markdown("## 📙 Công thức tính toán chi tiết")
    st.caption("Tất cả công thức được sử dụng trong phân tích Supply Chain GAP")
    
    # -------------------------------------------------------------------------
    # Level 1: FG GAP
    # -------------------------------------------------------------------------
    st.markdown("### 📊 Level 1: Finished Goods GAP")
    st.markdown("Phân tích chênh lệch cung-cầu cho từng sản phẩm thành phẩm.")
    
    st.code("""
    ┌─────────────────────────────────────────────────────────────────┐
    │  BƯỚC 1: Tổng hợp nguồn cung                                  │
    │  total_supply = ∑ available_quantity (theo product_id)          │
    │  * Tổng từ: Inventory + CAN Pending + Transfer + PO            │
    │  * Chỉ tính nguồn đã chọn trong Supply Sources filter          │
    │  * Loại bỏ hàng hết hạn nếu bật "Exclude Expired"             │
    ├─────────────────────────────────────────────────────────────────┤
    │  BƯỚC 2: Tổng hợp nhu cầu                                     │
    │  total_demand = ∑ required_quantity (theo product_id)           │
    │  * Tổng từ: Confirmed Orders + Forecast                        │
    │  * Chỉ tính nguồn đã chọn trong Demand Sources filter          │
    │                                                                 │
    │  avg_unit_price_usd = total_value_usd / total_demand            │
    │  * Đơn giá bình quân (USD) — dùng để tính At Risk Value        │
    ├─────────────────────────────────────────────────────────────────┤
    │  BƯỚC 3: Tính toán GAP                                         │
    │  safety_gap       = total_supply - safety_stock_qty             │
    │  available_supply  = MAX(0, safety_gap)                         │
    │  net_gap           = available_supply - total_demand             │
    │  true_gap          = total_supply - total_demand                │
    ├─────────────────────────────────────────────────────────────────┤
    │  BƯỚC 4: Tỷ lệ và phân loại                                   │
    │  coverage_ratio = available_supply / total_demand               │
    │  gap_status     = classify(coverage_ratio)                      │
    │  at_risk_value  = |net_gap| × avg_unit_price_usd (nếu < 0)     │
    └─────────────────────────────────────────────────────────────────┘
    """, language="text")
    
    st.markdown("**Ví dụ minh họa:**")
    st.markdown("""
    Sản phẩm A có:
    - Inventory: 500, CAN Pending: 200, PO: 300 → **total_supply = 1,000**
    - OC Pending: 800, Forecast: 400 → **total_demand = 1,200**
    - Safety stock: 100
    
    Tính toán:
    - safety_gap = 1,000 - 100 = **900**
    - available_supply = MAX(0, 900) = **900**
    - net_gap = 900 - 1,200 = **-300** (shortage 300 đơn vị)
    - true_gap = 1,000 - 1,200 = **-200** (nếu không tính safety stock)
    - coverage_ratio = 900 / 1,200 = **75%** → **HIGH_SHORTAGE**
    - avg_unit_price_usd = $10/unit → at_risk_value = 300 × $10 = **$3,000**
    """)
    
    st.divider()
    
    # -------------------------------------------------------------------------
    # Level 2: Raw Material GAP
    # -------------------------------------------------------------------------
    st.markdown("### 🧪 Level 2+: Multi-Level Material GAP")
    st.markdown("Phân tích NVL đa cấp cho sản phẩm Manufacturing có shortage ở Level 1.")
    
    st.code("""
    ┌─────────────────────────────────────────────────────────────────┐
    │  VÒNG LẶP ĐA CẤP (Level 1 → Level N, tối đa 10 cấp)         │
    │                                                                 │
    │  Input: parent_shortage (FG shortage hoặc semi-finished gap)    │
    │                                                                 │
    │  FOR each BOM level:                                            │
    │  ┌───────────────────────────────────────────────────────┐      │
    │  │  BƯỚC A: BOM Explosion                                │      │
    │  │  required_qty = (parent_shortage / bom_output_qty)    │      │
    │  │                 × qty_per_output × (1 + scrap_rate%)  │      │
    │  ├───────────────────────────────────────────────────────┤      │
    │  │  BƯỚC B: Phân loại material                           │      │
    │  │  - is_leaf = TRUE  → Raw Material (không có BOM)      │      │
    │  │  - is_leaf = FALSE → Semi-Finished (có BOM riêng)     │      │
    │  ├───────────────────────────────────────────────────────┤      │
    │  │  BƯỚC C: Raw Materials → tích lũy demand              │      │
    │  │  → Gom lại để tính GAP cuối cùng (1 lần)             │      │
    │  ├───────────────────────────────────────────────────────┤      │
    │  │  BƯỚC D: Semi-Finished → SUPPLY NETTING               │      │
    │  │  available = MAX(0, total_supply - safety_stock)       │      │
    │  │  net_gap = available - required_qty                    │      │
    │  │                                                        │      │
    │  │  IF net_gap >= 0 → ✅ Supply đủ, DỪNG (không đi sâu) │      │
    │  │  IF net_gap < 0  → 🔽 Shortage |net_gap| propagate    │      │
    │  │                      sang level tiếp theo              │      │
    │  └───────────────────────────────────────────────────────┘      │
    │  END FOR                                                        │
    │                                                                 │
    │  SAU VÒNG LẶP: Tính GAP cho tất cả Raw Materials tích lũy     │
    │  total_required = required_qty + existing_mo_demand              │
    │  net_gap = available_supply - total_required                     │
    └─────────────────────────────────────────────────────────────────┘
    """, language="text")
    
    st.markdown("**Ví dụ minh họa BOM đa cấp:**")
    st.markdown("""
    Sản phẩm C (Manufacturing) shortage **200 đơn vị**. BOM chuỗi: A → B → C
    
    **Level 1:** BOM C cần 200 pcs bán thành phẩm B + 10 kg Packaging D
    - Semi-Finished B: tồn kho = 50 → available = 50, required = 200
      - net_gap = 50 - 200 = **-150** → shortage → propagate 150 sang level 2
    - Packaging D (leaf): tích lũy demand = 10 kg
    
    **Level 2:** BOM B cần nguyên liệu A (chỉ cho **150 pcs**, không phải 200!)
    - BOM B: output_qty = 50, qty_per_output = 5 kg A, scrap_rate = 2%
    - required_qty = (150 / 50) × 5 × 1.02 = **15.3 kg**
    - Raw A (leaf): tích lũy demand = 15.3 kg
    
    **Kết quả cuối cùng:**
    - raw_gap_df = [Packaging D: demand 10 kg, Raw A: demand 15.3 kg] + existing MO + supply → GAP
    - semi_finished_gap_df = [Semi-Finished B at level 1: gap = -150]
    
    **So sánh nếu KHÔNG có supply netting:**
    - Nhu cầu Raw A = (200/50) × 5 × 1.02 = 20.4 kg (tính cho cả 200, bỏ qua tồn kho B = 50)
    - Sai lệch: 20.4 vs 15.3 kg = thừa 5.1 kg → mua NVL không cần thiết!
    """)
    
    st.divider()
    
    # -------------------------------------------------------------------------
    # Status Classification
    # -------------------------------------------------------------------------
    st.markdown("### 📈 Phân loại trạng thái (Status Classification)")
    st.markdown("Trạng thái được phân loại dựa trên **Coverage Ratio**:")
    
    st.code("""
    IF total_demand = 0 AND total_supply = 0  → NO_ACTIVITY
    IF total_demand = 0                        → NO_DEMAND
    
    IF net_gap < 0 (Shortage):
        coverage < 25%   → CRITICAL_SHORTAGE  🚨
        coverage < 50%   → SEVERE_SHORTAGE    🔴
        coverage < 75%   → HIGH_SHORTAGE      🟠
        coverage < 90%   → MODERATE_SHORTAGE  🟡
        coverage < 100%  → LIGHT_SHORTAGE     ⚠️
    
    IF net_gap = 0        → BALANCED           ✅
    
    IF net_gap > 0 (Surplus):
        coverage ≤ 125%  → LIGHT_SURPLUS      🔵
        coverage ≤ 175%  → MODERATE_SURPLUS   🟣
        coverage ≤ 250%  → HIGH_SURPLUS       🟠
        coverage > 250%  → SEVERE_SURPLUS     🔴
    """, language="text")
    
    st.divider()
    
    # -------------------------------------------------------------------------
    # Action Logic
    # -------------------------------------------------------------------------
    st.markdown("### 📋 Logic đề xuất hành động (Action Recommendations)")
    
    st.code("""
    ┌─────────────────────────────────────────────────────────────────┐
    │  FG product có shortage (net_gap < 0)                          │
    │                                                                 │
    │  ├── Manufacturing (has_bom = 1)?                               │
    │  │   ├── NVL đầy đủ (all materials net_gap >= 0)?              │
    │  │   │   └── ✅ Action: CREATE_MO                              │
    │  │   │                                                          │
    │  │   ├── NVL chính thiếu + có Alternative đủ?                  │
    │  │   │   └── 🔄 Action: USE_ALTERNATIVE                       │
    │  │   │                                                          │
    │  │   └── NVL thiếu + không có Alternative?                     │
    │  │       ├── ⏳ Action: WAIT_RAW (cho FG)                      │
    │  │       └── 📦 Action: CREATE_PO_RAW (cho NVL thiếu)         │
    │  │                                                              │
    │  └── Trading (has_bom = 0)?                                     │
    │      └── 🛒 Action: CREATE_PO_FG                               │
    │                                                                 │
    │  Semi-Finished shortage (multi-level BOM):                      │
    │  └── Bán thành phẩm bị shortage sau supply netting              │
    │      └── 🔶 Action: CREATE_MO_SEMI (sản xuất bán thành phẩm)  │
    └─────────────────────────────────────────────────────────────────┘
    """, language="text")
    
    st.markdown("""
    **Lưu ý về Priority:**
    - Priority kế thừa từ GAP status của sản phẩm
    - CRITICAL_SHORTAGE / SEVERE_SHORTAGE → Priority 1 (ưu tiên cao nhất)
    - HIGH_SHORTAGE → Priority 2
    - MODERATE_SHORTAGE → Priority 3
    - LIGHT_SHORTAGE → Priority 4
    - Actions được sắp xếp theo priority tăng dần
    """)
    
    st.divider()
    
    # -------------------------------------------------------------------------
    # Period GAP - Carry Forward Logic
    # -------------------------------------------------------------------------
    st.markdown("### 📅 Period GAP — Carry Forward Logic")
    st.markdown("Phân tích GAP theo từng kỳ (tuần/tháng) với carry-forward và backlog tracking.")
    
    st.code("""
    ┌─────────────────────────────────────────────────────────────────┐
    │  KHỞI TẠO (cho mỗi sản phẩm):                                 │
    │  carry_forward = 0                                              │
    │  backlog = safety_stock_qty  (safety stock = "nợ" ban đầu)     │
    │                                                                 │
    │  FOR each period (sorted chronologically):                      │
    │  ┌───────────────────────────────────────────────────────┐      │
    │  │  begin_inventory   = carry_forward (từ kỳ trước)      │      │
    │  │  supply_in_period  = ∑ supply có date thuộc kỳ này    │      │
    │  │  total_available   = begin_inventory + supply_in       │      │
    │  │                                                        │      │
    │  │  demand_in_period  = ∑ demand có date thuộc kỳ này    │      │
    │  │  effective_demand  = demand_in + backlog (từ kỳ trước) │      │
    │  │                                                        │      │
    │  │  gap = total_available - effective_demand               │      │
    │  │                                                        │      │
    │  │  IF gap >= 0:  (SURPLUS — đủ hàng)                    │      │
    │  │    carry_forward = gap    ← dư mang sang kỳ sau       │      │
    │  │    backlog = 0            ← xóa nợ                    │      │
    │  │                                                        │      │
    │  │  IF gap < 0:   (SHORTAGE — thiếu hàng)                │      │
    │  │    carry_forward = 0     ← không còn gì để carry      │      │
    │  │    backlog = |gap|       ← nợ mang sang kỳ sau        │      │
    │  │                                                        │      │
    │  │  fulfillment_rate = total_available / effective_demand │      │
    │  └───────────────────────────────────────────────────────┘      │
    │  END FOR                                                        │
    └─────────────────────────────────────────────────────────────────┘
    """, language="text")
    
    st.markdown("**Ví dụ minh họa (Track Backlog = ON, Safety Stock = 50):**")
    st.markdown("""
    | Kỳ | Begin Inv | Supply In | Available | Demand | Backlog In | Total Need | GAP | Carry FW | Backlog Out |
    |----|-----------|-----------|-----------|--------|------------|------------|-----|----------|-------------|
    | W1 | 0 | 100 | 100 | 80 | 50 (safety) | 130 | -30 | 0 | 30 |
    | W2 | 0 | 200 | 200 | 150 | 30 | 180 | +20 | 20 | 0 |
    | W3 | 20 | 0 | 20 | 100 | 0 | 100 | -80 | 0 | 80 |
    | W4 | 0 | 300 | 300 | 50 | 80 | 130 | +170 | 170 | 0 |
    
    → W1: Safety stock 50 = "nợ" ban đầu, cộng demand 80 = need 130, supply 100 → shortage 30
    → W2: Backlog 30 từ W1 + demand 150 = need 180, supply 200 → surplus 20 carry forward
    → W3: Carry 20 + supply 0 = 20, demand 100 = shortage 80 → backlog 80
    → W4: Backlog 80 + demand 50 = 130, supply 300 → surplus 170 carry forward
    """)
    
    st.divider()
    
    st.markdown("### 📅 Raw Material Period GAP")
    st.markdown("""
    Nhu cầu NVL theo kỳ = BOM explosion từ FG manufacturing shortage **theo từng period**:
    
    1. Lấy FG Period GAP → lọc manufacturing products có shortage per period
    2. BOM explode shortage qty per period → raw demand by (material_id, period)
    3. Raw supply: tổng tồn kho + PO đặt vào period đầu tiên (available now)
    4. Apply carry-forward per material → biết KHI NÀO NVL hết
    
    **Ứng dụng:** So sánh "khi nào NVL hết" vs "lead time mua NVL" → biết phải đặt PO bao giờ.
    """)


# =============================================================================
# TAB 4: CÂU HỎI THƯỜNG GẶP (FAQ)
# =============================================================================

def _render_faq():
    """Frequently Asked Questions"""
    
    st.markdown("## 📕 Câu hỏi thường gặp (FAQ)")
    st.caption("Giải đáp các câu hỏi phổ biến khi sử dụng Supply Chain GAP Analysis")
    
    # -------------------------------------------------------------------------
    # Nhóm 1: Kết quả & Dữ liệu
    # -------------------------------------------------------------------------
    st.markdown("### 🔍 Kết quả & Dữ liệu")
    
    with st.expander("**Q1: Tại sao một số sản phẩm hiển thị NO_DEMAND hoặc NO_ACTIVITY?**"):
        st.markdown("""
        **NO_DEMAND** — Sản phẩm có tồn kho (supply) nhưng không có đơn hàng hoặc forecast trong hệ thống.
        Nguyên nhân có thể:
        - Đơn hàng chưa được tạo hoặc chưa confirm
        - Forecast chưa được cập nhật cho kỳ hiện tại
        - Sản phẩm đang trong giai đoạn slow-moving hoặc sắp ngừng kinh doanh
        
        **NO_ACTIVITY** — Không có cả supply lẫn demand. Sản phẩm có thể đã ngừng hoạt động 
        hoặc chưa có dữ liệu cho kỳ phân tích.
        
        **Hành động:** Kiểm tra lại trong module Sales Order và Forecast để đảm bảo dữ liệu đã cập nhật.
        """)
    
    with st.expander("**Q2: Net GAP và True GAP khác nhau thế nào?**"):
        st.markdown("""
        | | Net GAP | True GAP |
        |--|---------|----------|
        | **Công thức** | Available Supply - Total Demand | Total Supply - Total Demand |
        | **Safety Stock** | Có trừ safety stock | Không trừ safety stock |
        | **Ý nghĩa** | Chênh lệch "an toàn" — sau khi giữ lại safety stock | Chênh lệch "thực tế" — toàn bộ hàng vs nhu cầu |
        | **Khi nào dùng** | Mặc định — đánh giá khả năng đáp ứng bền vững | Khi muốn biết có đủ hàng "tuyệt đối" hay không |
        
        **Ví dụ:** Supply = 1000, Demand = 800, Safety = 300
        - Net GAP = MAX(0, 1000-300) - 800 = 700 - 800 = **-100** (shortage)
        - True GAP = 1000 - 800 = **+200** (surplus)
        
        → Hàng thực tế đủ, nhưng nếu giữ safety stock thì thiếu 100 đơn vị.
        """)
    
    with st.expander("**Q3: At Risk Value được tính bằng đơn vị tiền nào?**"):
        st.markdown("""
        **At Risk Value luôn tính bằng USD.**
        
        Công thức: `at_risk_value = |net_gap| × avg_unit_price_usd`
        
        Trong đó `avg_unit_price_usd = total_value_usd / total_demand`, lấy từ trường 
        `total_value_usd` trong unified_demand_view (đã quy đổi sang USD).
        
        **Lưu ý:** Nếu `total_value_usd` không có dữ liệu, at_risk_value sẽ = 0. 
        Kiểm tra đơn giá bán trong hệ thống đã được thiết lập đúng.
        """)
    
    with st.expander("**Q4: Tại sao Coverage Ratio hiển thị N/A?**"):
        st.markdown("""
        Coverage = N/A khi **total_demand = 0** (không có nhu cầu).
        
        Hệ thống không thể chia cho 0, nên hiển thị N/A thay vì số.
        Sản phẩm này sẽ được phân loại là **NO_DEMAND** hoặc **NO_ACTIVITY**.
        """)
    
    with st.expander("**Q5: Dữ liệu được lấy từ đâu và cập nhật khi nào?**"):
        st.markdown("""
        Dữ liệu lấy trực tiếp từ các SQL View trong database:
        
        | View | Dữ liệu |
        |------|---------|
        | `unified_supply_view` | Tổng hợp tồn kho, CAN, transfer, PO |
        | `unified_demand_view` | Tổng hợp OC pending, forecast |
        | `safety_stock_current_view` | Safety stock hiện hành |
        | `product_classification_view` | Phân loại Manufacturing / Trading |
        | `bom_explosion_view` | Chi tiết BOM và NVL (single-level, dùng cho tính toán) |
        | `bom_full_explosion_view` | BOM đa cấp recursive (dùng cho hiển thị & export) |
        | `manufacturing_raw_demand_view` | Nhu cầu NVL từ MO pending |
        | `raw_material_supply_summary_view` | Tổng hợp supply NVL |
        
        Dữ liệu được query **realtime** mỗi lần nhấn Analyze — phản ánh trạng thái mới nhất 
        tại thời điểm phân tích. Tuy nhiên, dữ liệu gốc (inventory, orders, ...) phụ thuộc vào 
        việc nhập liệu và đồng bộ từ các module khác.
        """)
    
    # -------------------------------------------------------------------------
    # Nhóm 2: Manufacturing & BOM
    # -------------------------------------------------------------------------
    st.markdown("### 🏭 Manufacturing & BOM")
    
    with st.expander("**Q6: Sản phẩm Manufacturing hiển thị 'Cannot Produce' — phải làm gì?**"):
        st.markdown("""
        **"Cannot Produce"** nghĩa là NVL không đủ để sản xuất. Các bước xử lý:
        
        1. **Kiểm tra tab Raw Materials:** Xem NVL nào đang shortage (dùng filter "Shortage only")
        2. **Kiểm tra NVL thay thế:** Nếu bật Alternatives, hệ thống sẽ tự kiểm tra. 
           Nếu có alternative đủ → action sẽ là USE_ALTERNATIVE thay vì WAIT_RAW
        3. **Xem tab Actions:** 
           - Nếu action = WAIT_RAW → Kiểm tra PO cho NVL đã đặt chưa, khi nào về
           - Nếu action = CREATE_PO_RAW → Cần tạo PO mua NVL
        4. **Liên hệ mua hàng:** Với NVL có action CREATE_PO_RAW, chuyển danh sách cho bộ phận mua hàng
        """)
    
    with st.expander("**Q7: Scrap Rate ảnh hưởng đến kết quả thế nào?**"):
        st.markdown("""
        **Scrap Rate** (tỷ lệ hao hụt) làm tăng nhu cầu NVL thực tế so với lý thuyết.
        
        Ví dụ: Cần sản xuất 100 FG, mỗi FG cần 2 kg NVL, scrap rate = 5%
        - Không tính scrap: 100 × 2 = 200 kg
        - Có tính scrap: 100 × 2 × 1.05 = **210 kg**
        
        Scrap rate được thiết lập trong BOM và có thể khác nhau theo BOM type:
        - Cutting ✂️: ~2% (cắt tấm lớn → mất phần viền)
        - Repacking 📦: ~0.5% (rất ít hao hụt)
        - Assembly 🔩: ~1% (lỗi lắp ráp)
        - Kitting 🔧: ~0% (chỉ ghép bộ, không gia công)
        """)
    
    with st.expander("**Q8: 'Existing MO Demand' là gì và tại sao cần tính?**"):
        st.markdown("""
        **Existing MO Demand** là nhu cầu NVL từ các Manufacturing Order (MO) đang ở trạng thái 
        CONFIRMED hoặc IN_PROGRESS — đã tạo MO nhưng chưa xuất kho NVL.
        
        **Tại sao cần tính?**
        Khi bạn có MO pending, NVL tồn kho tuy "hiển thị available" nhưng thực tế đã bị 
        "reserved" cho MO đó. Nếu không tính existing MO demand, hệ thống sẽ đánh giá NVL 
        đủ trong khi thực tế không đủ (vì một phần sẽ bị xuất cho MO cũ).
        
        **MO nào được tính?**
        - Mặc định: chỉ **CONFIRMED** và **IN_PROGRESS** (MO đã cam kết)
        - Nếu bật checkbox **"Include DRAFT MO"**: bao gồm cả **DRAFT** MO
        - Hệ thống đảm bảo cả hai phía (FG supply + raw demand) luôn nhìn cùng tập MO 
          → tránh double-count
        
        **Khi nào tắt?**
        - Khi MO pending đã quá hạn và có thể bị hủy
        - Khi muốn đánh giá supply NVL thuần túy (không tính commitment)
        """)
    
    with st.expander("**Q8b: BOM đa cấp (multi-level) hoạt động thế nào?**"):
        st.markdown("""
        Khi sản phẩm có quy trình sản xuất nhiều công đoạn (VD: A → B → C), hệ thống tự động 
        phân tích từng cấp:
        
        **Ví dụ:** FG Product C cần bán thành phẩm B, B cần nguyên liệu A.
        
        1. **Level 1:** FG C shortage → cần bán thành phẩm B
        2. **Supply Netting:** Kiểm tra tồn kho B
           - Nếu B đủ → DỪNG, không cần sản xuất B → không cần NVL A
           - Nếu B thiếu → tính net shortage B (trừ phần tồn kho đã có)
        3. **Level 2:** Net shortage B → BOM B → cần nguyên liệu A (chỉ cho phần thiếu!)
        
        **Ưu điểm supply netting:** Tránh đặt mua NVL thừa. Nếu tồn kho bán thành phẩm 
        đã có sẵn, hệ thống sẽ tận dụng trước khi tính nhu cầu NVL cấp dưới.
        """)
    
    with st.expander("**Q8c: Semi-Finished hiển thị 'Shortage propagates' — nghĩa là gì?**"):
        st.markdown("""
        Trong bảng Semi-Finished Products, cột **Netting** cho biết:
        
        - **✅ Supply covers:** Tồn kho bán thành phẩm đủ cho nhu cầu → không cần đi sâu thêm BOM
        - **🔽 Shortage propagates:** Tồn kho không đủ → phần thiếu được truyền xuống cấp BOM tiếp theo
        
        **Hành động khi thấy "Shortage propagates":**
        1. Kiểm tra tab Actions → sẽ có **CREATE_MO_SEMI** cho bán thành phẩm này
        2. Kiểm tra NVL cấp dưới (Raw Materials) → đảm bảo NVL đủ để sản xuất bán thành phẩm
        3. Nếu NVL cũng thiếu → sẽ có thêm **CREATE_PO_RAW**
        """)
    
    with st.expander("**Q8d: 'MO Expected' trong Supply Sources là gì? Tại sao quan trọng?**"):
        st.markdown("""
        **MO Expected** là sản lượng dự kiến từ các Manufacturing Order (MO) chưa hoàn thành.
        
        **Công thức:** `pending_output = planned_qty - produced_qty`
        
        **MO nào được tính?**
        - Mặc định: **CONFIRMED** và **IN_PROGRESS**
        - Bật checkbox **"Include DRAFT MO"** → bao gồm thêm **DRAFT** MO
        - Checkbox này đồng bộ cả hai phía: FG supply (MO Expected) + raw demand (Existing MO)
        
        **Tại sao cần bật?**
        
        Khi có MO đang sản xuất để fulfill OC/Forecast, nếu KHÔNG tính MO Expected vào FG supply:
        
        1. FG shortage bị tính **full** (không trừ phần MO đang cover)
        2. BOM explosion chạy trên full shortage → raw demand bị **thổi phồng**
        3. Existing MO Demand ở raw level lại cộng thêm → **double-count!**
        
        **Ví dụ:**
        - OC Demand = 100 PCS, Inventory = 20 PCS, MO đang sản xuất = 80 PCS
        - ❌ **MO Expected OFF:** Shortage = 80 → BOM explosion cho 80 → raw demand = 80 + existing MO raw = **160 (double!)**
        - ✅ **MO Expected ON:** Shortage = 0 (20 + 80 ≥ 100) → Không cần BOM explosion → raw demand chỉ = existing MO = **80 (đúng!)**
        
        **Bảng trạng thái an toàn:**
        
        | MO Expected | Existing MO | Kết quả |
        |---|---|---|
        | ✅ ON | ✅ ON | ✅ **Chuẩn** — FG supply có MO, raw có commitment |
        | ❌ OFF | ❌ OFF | ✅ **Worst-case** — chỉ tính inventory thực |
        | ✅ ON | ❌ OFF | ⚠️ OK nhưng raw thiếu commitment |
        | ❌ OFF | ✅ ON | ❌ **Double-count!** Hệ thống sẽ cảnh báo |
        
        **Khuyến nghị:** Luôn bật cả hai (MO Expected + Existing MO) — đây là cấu hình mặc định.
        """)
    
    with st.expander("**Q8e: Checkbox 'Include DRAFT MO' hoạt động thế nào?**"):
        st.markdown("""
        Checkbox này quyết định MO ở trạng thái **DRAFT** có được tính vào phân tích hay không.
        
        **Mặc định: TẮT (☐)**
        - Chỉ tính MO **CONFIRMED** và **IN_PROGRESS**
        - Lý do: DRAFT MO chưa được duyệt, có thể bị hủy bất kỳ lúc nào
        
        **Khi BẬT (☑):**
        - Bao gồm thêm DRAFT MO vào **cả hai phía đồng thời**:
          - 🏭 **FG Supply:** MO Expected output tăng (tính cả DRAFT planned_qty - produced_qty)
          - 🧪 **Raw Demand:** Existing MO demand tăng (tính cả NVL cho DRAFT MO)
        - Hai phía luôn đồng bộ → **không double-count**
        
        **Khi nào nên bật DRAFT?**
        
        | Tình huống | Nên bật? | Lý do |
        |-----------|---------|-------|
        | DRAFT MO gần như chắc chắn sẽ confirm | ✅ Bật | Phản ánh đúng kế hoạch sản xuất |
        | Đang lên kế hoạch, MO chưa chắc chắn | ❌ Tắt | Tránh tính nguồn cung chưa cam kết |
        | Muốn so sánh "có DRAFT" vs "không DRAFT" | 🔄 Toggle | Chạy 2 lần, so sánh kết quả |
        | Review cuối ngày cho team sản xuất | ✅ Bật | Thấy full picture bao gồm MO đang chuẩn bị |
        
        **Ví dụ thực tế:**
        - Demand = 208k, Inventory = 0, có DRAFT MO 100k
        - ☐ **DRAFT OFF:** FG shortage = 208k, raw demand = 208k (DRAFT invisible)
        - ☑ **DRAFT ON:** FG shortage = 108k (208k - 100k MO), raw demand = 108k + 100k = 208k ✅
        """)
    
    # -------------------------------------------------------------------------
    # Nhóm 3: Bộ lọc & Tùy chọn
    # -------------------------------------------------------------------------
    st.markdown("### 🔧 Bộ lọc & Tùy chọn")
    
    with st.expander("**Q9: Nên chọn Supply/Demand Sources nào?**"):
        st.markdown("""
        **Khuyến nghị mặc định:** Chọn tất cả (mặc định của hệ thống).
        
        **Khi nào bỏ bớt nguồn?**
        
        | Tình huống | Nguồn nên bỏ | Lý do |
        |-----------|-------------|-------|
        | Chỉ muốn xem tồn kho thực vs đơn hàng | Bỏ CAN, Transfer, PO, MO Expected / Bỏ Forecast | Đánh giá khả năng giao hàng ngay |
        | PO chưa chắc chắn (NCC chưa xác nhận) | Bỏ Purchase Order | Tránh tính nguồn cung không chắc chắn |
        | Forecast chưa chính xác | Bỏ Forecast | Chỉ tính nhu cầu đã confirm |
        | Muốn worst-case scenario | Chỉ giữ Inventory / Chỉ giữ OC_PENDING | Đánh giá tình huống xấu nhất |
        | MO chưa chắc hoàn thành | Bỏ MO Expected | Tránh tính sản lượng chưa chắc chắn |
        
        ⚠️ **Lưu ý:** Nếu bỏ MO Expected, nên tắt luôn "Existing MO Demand" ở phần Options 
        để tránh double-count (xem Q8d).
        """)
    
    with st.expander("**Q10: 'Exclude Expired' có ảnh hưởng nhiều không?**"):
        st.markdown("""
        Tùy thuộc vào ngành hàng:
        
        - **Ảnh hưởng lớn:** Ngành thực phẩm, hóa chất, dược phẩm — hàng có hạn sử dụng ngắn. 
          Nếu nhiều lô tồn kho sắp hết hạn, bật Exclude Expired sẽ giảm đáng kể total_supply.
        - **Ảnh hưởng nhỏ:** Ngành linh kiện điện tử, vật liệu bền — ít hàng hết hạn.
        
        **Khuyến nghị:** Luôn bật — hàng hết hạn không nên giao cho khách hàng.
        """)
    
    with st.expander("**Q11: Khi chọn Entity cụ thể, dữ liệu có bị ảnh hưởng gì?**"):
        st.markdown("""
        Khi chọn Entity (ví dụ: Prostech Vietnam), hệ thống chỉ lấy dữ liệu supply/demand 
        thuộc entity đó. Điều này có nghĩa:
        
        - Tồn kho ở entity khác sẽ **không được tính** vào supply
        - Đơn hàng của entity khác sẽ **không nằm** trong demand
        - Safety stock, BOM, classification vẫn dùng chung (nếu view không filter theo entity)
        
        **Tip:** Chọn "All" để có cái nhìn tổng thể toàn công ty, sau đó chọn entity cụ thể 
        để phân tích chi tiết cho từng đơn vị.
        """)
    
    # -------------------------------------------------------------------------
    # Nhóm 4: Xử lý tình huống
    # -------------------------------------------------------------------------
    st.markdown("### 🛠️ Xử lý tình huống")
    
    with st.expander("**Q12: Sản phẩm shortage nhưng True GAP dương — nên xử lý thế nào?**"):
        st.markdown("""
        Đây là tình huống **safety stock gây ra shortage "ảo"**.
        
        - **Net GAP < 0**: Sau khi giữ safety stock, không đủ hàng cho demand
        - **True GAP > 0**: Nếu dùng hết hàng (kể cả safety stock), vẫn đủ cho demand
        
        **Quyết định:**
        - Nếu sản phẩm **critical** (khách hàng lớn, đơn hàng gấp): Có thể tạm "ăn" vào safety stock 
          để giao hàng, đồng thời bổ sung hàng sớm nhất
        - Nếu sản phẩm **không gấp**: Giữ safety stock, tạo MO/PO để bổ sung trước khi giao
        
        **Tip:** So sánh cột Net GAP và True GAP để nhận diện tình huống này nhanh chóng.
        """)
    
    with st.expander("**Q13: Nhiều sản phẩm cùng shortage — ưu tiên xử lý sản phẩm nào?**"):
        st.markdown("""
        **Tiêu chí ưu tiên (từ cao đến thấp):**
        
        1. **Priority / GAP Status**: CRITICAL_SHORTAGE > SEVERE_SHORTAGE > HIGH_SHORTAGE
        2. **At Risk Value**: Sản phẩm có giá trị rủi ro cao → ưu tiên trước
        3. **Customer Count**: Sản phẩm ảnh hưởng nhiều khách hàng → ưu tiên trước
        4. **Khả năng xử lý**: Manufacturing + NVL đủ (CREATE_MO) → xử lý ngay được
        
        **Quy trình đề xuất:**
        1. Dùng Quick Filter "🚨 Critical" → xử lý nhóm CRITICAL trước
        2. Sắp xếp theo At Risk Value (export Excel → sort) → ưu tiên giá trị lớn
        3. Kiểm tra tab Actions → thực hiện CREATE_MO trước (có thể làm ngay), 
           sau đó CREATE_PO (cần thời gian chờ NCC)
        """)
    
    with st.expander("**Q14: NVL thay thế (Alternative) hoạt động thế nào?**"):
        st.markdown("""
        Khi NVL chính (Primary) shortage, hệ thống kiểm tra NVL thay thế (Alternative):
        
        1. Mỗi NVL chính có thể có 1 hoặc nhiều NVL thay thế, được thiết lập trong BOM
        2. NVL thay thế có **alternative_priority** (thứ tự ưu tiên sử dụng)
        3. Hệ thống kiểm tra: NVL thay thế có đủ số lượng để bù shortage NVL chính không?
           - **can_cover_shortage = True**: NVL thay thế đủ → Action: USE_ALTERNATIVE
           - **can_cover_shortage = False**: NVL thay thế cũng thiếu → Action: WAIT_RAW + CREATE_PO_RAW
        
        **Điều kiện để action là USE_ALTERNATIVE:**
        - NVL chính bị shortage (net_gap < 0)
        - Có NVL thay thế với net_gap ≥ |shortage NVL chính|
        - Tùy chọn "Alternatives" được bật
        """)
    
    with st.expander("**Q15: Kết quả phân tích khác với thực tế kho — nguyên nhân là gì?**"):
        st.markdown("""
        Các nguyên nhân phổ biến:
        
        | Nguyên nhân | Ảnh hưởng | Cách khắc phục |
        |------------|-----------|----------------|
        | Tồn kho chưa cập nhật | Supply cao/thấp hơn thực tế | Kiểm tra và cập nhật nhập/xuất kho |
        | Đơn hàng chưa nhập hệ thống | Demand thấp hơn thực tế | Nhập đầy đủ OC vào hệ thống |
        | PO chưa tạo/cập nhật | Supply thiếu nguồn PO | Cập nhật trạng thái PO |
        | Safety stock chưa chính xác | Net GAP bị lệch | Review và cập nhật safety stock |
        | Hàng hết hạn chưa xử lý | Supply tính hàng không dùng được | Bật "Exclude Expired" |
        | BOM chưa cập nhật | Required NVL sai | Kiểm tra BOM trong module sản xuất |
        | Transfer chưa hoàn thành | Supply tính hàng đang transit | Hoàn thành transfer hoặc bỏ chọn nguồn Transfer |
        
        **Tip:** Export Excel và đối chiếu từng dòng với dữ liệu thực tế để tìm sai lệch.
        """)
    
    # -------------------------------------------------------------------------
    # Nhóm 5: Export & Báo cáo
    # -------------------------------------------------------------------------
    st.markdown("### 📥 Export & Báo cáo")
    
    with st.expander("**Q16: File Excel export có thể dùng cho mục đích gì?**"):
        st.markdown("""
        - **Báo cáo management:** Sheet Summary chứa tổng quan metrics
        - **Chuyển cho team mua hàng:** Sheet Trading + Actions (PO-FG, PO-Raw)
        - **Chuyển cho team sản xuất:** Sheet Manufacturing + Actions (MO)
        - **Lưu trữ lịch sử:** So sánh kết quả qua các kỳ phân tích
        - **Phân tích nâng cao:** Import vào Excel/Power BI để phân tích thêm
        """)
    
    with st.expander("**Q17: Có thể lên lịch chạy tự động không?**"):
        st.markdown("""
        Hiện tại Supply Chain GAP Analysis chạy **thủ công** qua giao diện web. 
        Mỗi lần nhấn Analyze, hệ thống query dữ liệu mới nhất từ database.
        
        **Gợi ý quy trình:**
        - Chạy phân tích mỗi sáng đầu ngày làm việc
        - Export Excel và lưu với tên có ngày tháng
        - Review Critical/Severe shortage trước, gửi action items cho team liên quan
        """)
    
    # -------------------------------------------------------------------------
    # Nhóm 6: Period GAP Analysis
    # -------------------------------------------------------------------------
    st.markdown("### 📅 Period GAP Analysis")
    
    with st.expander("**Q18: Period Timeline khác gì với Net GAP?**"):
        st.markdown("""
        | | Net GAP | Period Timeline |
        |--|---------|----------------|
        | **Câu hỏi** | Thiếu/thừa **bao nhiêu**? | Thiếu/thừa **khi nào**? |
        | **Đơn vị** | Tổng hợp tất cả (1 số/product) | Theo từng kỳ (tuần/tháng) |
        | **Logic** | Supply - Demand (tĩnh) | Carry forward + Backlog (động) |
        | **Ứng dụng** | Biết tổng thể tình hình | Lên kế hoạch sản xuất/đặt hàng theo thời gian |
        
        **Ví dụ:** Net GAP = -500 PCS. Nhưng Period Timeline cho thấy:
        - W1-W3: đủ hàng (surplus carry forward)  
        - W4: bắt đầu shortage -200
        - W5: shortage tích lũy -500
        
        → Biết cần đặt PO hoặc tạo MO trước W4 (tính ngược lead time).
        """)
    
    with st.expander("**Q18b: Track Backlog hoạt động thế nào?**"):
        st.markdown("""
        **Track Backlog = ON (mặc định):**
        - Shortage kỳ N → cộng vào demand kỳ N+1 (effective_demand = demand + backlog)
        - Phản ánh đúng thực tế: nhu cầu chưa đáp ứng không biến mất, nó tích lũy
        - Safety stock được coi là "nợ ban đầu" (initial backlog)
        
        **Track Backlog = OFF:**
        - Shortage không mang sang kỳ sau
        - Chỉ carry forward surplus (dương)
        - Mỗi kỳ độc lập — dễ đọc nhưng không phản ánh tích lũy
        
        **Khuyến nghị:** Luôn bật Track Backlog — đây là cách tính chính xác nhất cho lập kế hoạch.
        """)
    
    with st.expander("**Q19: Tại sao kỳ đầu tiên có Backlog = Safety Stock?**"):
        st.markdown("""
        Safety stock được coi là **"nhu cầu dự trữ"** ngay từ đầu. 
        
        Ví dụ: Safety stock = 100, Supply W1 = 300, Demand W1 = 200
        - Effective demand = 200 (demand) + 100 (safety stock) = **300**
        - GAP = 300 (supply) - 300 (need) = **0** (balanced)
        - Nếu không tính safety stock: GAP = 300 - 200 = +100 (misleading — chưa tính dự trữ)
        
        Cách này đảm bảo supply phải đủ cho cả demand lẫn safety stock trước khi được coi là "fulfilled".
        """)
    
    with st.expander("**Q20: Kỳ quá khứ (🔴) có ảnh hưởng gì đến kết quả?**"):
        st.markdown("""
        Kỳ quá khứ **có ảnh hưởng** vì carry-forward logic:
        
        - Demand quá khứ chưa đáp ứng → backlog → ảnh hưởng kỳ hiện tại và tương lai
        - Supply quá khứ → carry forward → tăng available cho kỳ hiện tại
        
        **Tại sao giữ lại kỳ quá khứ?**
        - Thấy được lịch sử carry-forward/backlog
        - Hiểu tại sao kỳ hiện tại có backlog (bắt nguồn từ kỳ nào)
        
        **Nếu chỉ muốn xem tương lai:** Dùng filter "🟢 Future Only" trong bảng Period.
        """)
    
    with st.expander("**Q21: Raw Material Period GAP hoạt động thế nào?**"):
        st.markdown("""
        Raw Material Period GAP trả lời: **"Khi nào cần mua NVL?"**
        
        **Logic:**
        1. Lấy FG Period GAP → lọc Manufacturing products có shortage **theo từng kỳ**
        2. BOM explosion: shortage kỳ N → nhu cầu NVL kỳ N (theo BOM qty × scrap)
        3. Raw supply: tổng tồn kho NVL đặt vào **kỳ đầu tiên** (available now)
        4. Carry-forward per NVL: supply giảm dần → khi hết → backlog = cần mua
        
        **Ví dụ:** NVL X, tồn kho = 1,000 kg
        - W1: BOM demand 200 kg → available = 1000 - 200 = 800 carry forward
        - W2: BOM demand 300 kg → available = 800 - 300 = 500 carry forward
        - W3: BOM demand 600 kg → available = 500 - 600 = -100 → **shortage bắt đầu W3!**
        
        → Phải đặt PO mua NVL X trước W3 (tính ngược NCC lead time).
        """)
    
    with st.expander("**Q22: Period Type nên chọn Weekly hay Monthly?**"):
        st.markdown("""
        | | Weekly | Monthly |
        |--|--------|---------|
        | **Chi tiết** | Cao — theo tuần ISO | Thấp — theo tháng |
        | **Phù hợp** | Kế hoạch sản xuất ngắn hạn (1-3 tháng) | Planning dài hạn (6-12 tháng) |
        | **Số dòng dữ liệu** | Nhiều (52 kỳ/năm) | Ít (12 kỳ/năm) |
        | **Carry-forward** | Chính xác hơn (ngắn hơn giữa các kỳ) | Gộp nhiều → có thể miss shortage ngắn |
        
        **Khuyến nghị:** 
        - Dùng **Weekly** cho operational planning (sản xuất, xuất hàng)
        - Dùng **Monthly** cho strategic planning (budget, capacity, procurement)
        - Chạy cả 2 để so sánh: Weekly spot được shortage mà Monthly bỏ lỡ
        """)