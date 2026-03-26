# utils/supply_chain_production/production_help.py

"""
User Guide for Production Planning — floating popover.

Comprehensive guide for training and reference. Covers:
- Page overview & pipeline context
- Settings configuration (all 4 groups)
- Running MO generation
- Reading each result tab
- Interpreting priority, urgency, readiness
- Material contention explained
- Export & next steps
- FAQ / Troubleshooting

Usage:
    from utils.supply_chain_production.production_help import render_user_guide_button
    render_user_guide_button()
"""

import streamlit as st

VERSION = "1.0.1"


# =============================================================================
# GUIDE CONTENT — structured for both popover and standalone reference
# =============================================================================

GUIDE_SECTIONS = [
    {
        'id': 'overview',
        'title': '1. Tổng quan',
        'icon': '🏭',
        'content': """
**Production Planning** (Kế hoạch Sản xuất) là module Layer 3 trong SCM Planning Pipeline.

**Chức năng:** Nhận kết quả phân tích thiếu hụt từ Supply Chain GAP, kiểm tra nguyên vật liệu sẵn có,
và tạo đề xuất Lệnh Sản xuất (Manufacturing Order — MO) với lịch trình, ưu tiên, và hành động cụ thể.

**Pipeline vị trí:**
```
Supply Chain GAP ──┬── PO Planning (mua hàng)
                   └── Production Planning (sản xuất) ← bạn đang ở đây
```

**Nguyên tắc ZERO ASSUMPTION:** Tất cả thông số phải được cấu hình rõ ràng.
Không có giá trị mặc định ẩn. Nếu thiếu cấu hình → hệ thống dừng và thông báo rõ ràng.
""",
    },
    {
        'id': 'prerequisites',
        'title': '2. Điều kiện tiên quyết',
        'icon': '✅',
        'content': """
Trước khi sử dụng Production Planning, cần hoàn thành:

**Bước 1: Chạy Supply Chain GAP**
- Vào trang **Supply Chain GAP** → chạy phân tích
- GAP sẽ xác định sản phẩm nào thiếu hụt và cần sản xuất
- Kết quả GAP được lưu trong session — không cần export

**Bước 2: Cấu hình Settings (lần đầu)**
- Vào tab **⚙️ Settings** → điền các thông số bắt buộc
- Hoặc dùng **⚡ Apply Defaults** để điền nhanh từ dữ liệu lịch sử
- Cấu hình lưu vào DB — chỉ cần làm 1 lần

**Không bắt buộc nhưng có lợi:**
- Chạy PO Planning trước → Production Planning sẽ có thêm thông tin ETA nguyên vật liệu từ PO
""",
    },
    {
        'id': 'settings',
        'title': '3. Cấu hình Settings',
        'icon': '⚙️',
        'content': """
Tab Settings có 4 nhóm cấu hình:

---

**📅 Lead Time Setup (Bắt buộc)**

Thời gian sản xuất tính bằng ngày cho mỗi loại BOM:
- **Cutting** — Cắt cuộn lớn → nhiều cuộn nhỏ (ví dụ: tape rolls)
- **Repacking** — Đóng gói lại format khác (ví dụ: bulk → retail)
- **Kitting** — Lắp ráp nhiều thành phần → 1 sản phẩm (ví dụ: kit assembly)

💡 Dưới mỗi ô nhập có **gợi ý lịch sử**: "📊 Historical: avg 2.5d from 992 MOs"
— dùng để tham khảo khi điền giá trị.

**Historical Override (Tùy chọn):** Khi bật, hệ thống sẽ dùng lead time thực tế từ
các MO đã hoàn thành thay vì giá trị cấu hình. Chỉ áp dụng khi có đủ dữ liệu
(ví dụ: ≥ 5 MOs cho 1 sản phẩm, ≥ 10 MOs cho 1 loại BOM).

---

**⚖️ Priority Weights (Bắt buộc)**

Trọng số để xếp hạng ưu tiên MO. **Tổng phải = 100%**.

| Thành phần | Mô tả | Gợi ý |
|------------|-------|-------|
| Time urgency | Còn bao lâu đến ngày cần hàng | 40% |
| Material readiness | Nguyên vật liệu sẵn sàng đến đâu | 25% |
| At-risk value | Giá trị tiền hàng bị ảnh hưởng | 20% |
| Customer linkage | Có đơn hàng khách hàng liên kết không | 15% |

---

**📋 Planning Parameters (Bắt buộc)**

- **Planning horizon:** Ngày dự phòng khi GAP không có ngày cụ thể. Mặc định: 60 ngày.
- **Allow partial production:** Hiện số lượng tối đa có thể sản xuất khi vật liệu chỉ đủ một phần.

---

**📊 Yield Setup (Tùy chọn)**

Điều chỉnh sản lượng dựa trên tỷ lệ phế phẩm thực tế. Mặc định: dùng scrap rate từ BOM.
Bật historical override để dùng yield thực tế từ MO đã hoàn thành.
""",
    },
    {
        'id': 'quick_start',
        'title': '4. Quick Start — Cấu hình nhanh',
        'icon': '⚡',
        'content': """
Khi mở trang lần đầu và chưa có cấu hình, hệ thống sẽ hiện thanh **Quick Start**:

> 💡 Quick start available. Historical data found: CUTTING avg 2.5d (992 MOs)...
> [⚡ Apply Defaults]

**Khi bấm "Apply Defaults":**
1. Lead time: Lấy từ dữ liệu lịch sử (làm tròn lên, tối thiểu 1 ngày)
2. Priority weights: Áp dụng chuẩn 40/25/20/15
3. Planning horizon: 60 ngày
4. Tất cả giá trị được lưu vào DB ngay lập tức
5. Trang tự reload → sẵn sàng chạy

**Sau khi Apply**, bạn vẫn có thể chỉnh sửa bất kỳ giá trị nào → Save lại.
""",
    },
    {
        'id': 'generate',
        'title': '5. Chạy Generate MO Suggestions',
        'icon': '🔄',
        'content': """
**Nút "🔄 Generate MO Suggestions"** sẽ khả dụng khi:
- ✅ Settings đã đầy đủ (progress bar 100%)
- ✅ Supply Chain GAP đã chạy (pipeline bar hiện ✓)

**Pipeline xử lý khi bấm Generate:**

```
1. Config Gate      → Kiểm tra cấu hình đầy đủ
2. Extract from GAP → Lấy danh sách sản phẩm cần sản xuất
3. SO Linkage       → Kiểm tra sản phẩm nào có đơn hàng
4. Material Check   → 2-pass kiểm tra NVL (cá nhân + tranh chấp)
5. Schedule         → Lên lịch sản xuất (backward scheduling)
6. Build MO Lines   → Tạo đề xuất MO với 40+ trường thông tin
7. Categorize       → Phân loại: Ready / Waiting / Blocked
8. Reconciliation   → Kiểm tra đối chiếu (input = output)
```

Thời gian xử lý: thường < 5 giây cho ~130 sản phẩm.
""",
    },
    {
        'id': 'tab_ready',
        'title': '6. Tab ✅ Ready — Sẵn sàng sản xuất',
        'icon': '✅',
        'content': """
Hiển thị các MO suggestion có **đầy đủ nguyên vật liệu** → có thể tạo MO ngay.

**Các cột chính:**

| Cột | Ý nghĩa |
|-----|---------|
| **Priority** | Điểm ưu tiên (thấp = cần làm trước). Tính từ 4 thành phần weights |
| **Urgency** | Mức khẩn cấp: 🚨 Overdue, 🔴 Critical, 🟠 Urgent, 🟡 This Week, 🔵 Planned |
| **Code / Product** | Mã sản phẩm và tên |
| **Shortage** | Số lượng thiếu từ GAP |
| **Suggested Qty** | Số lượng đề xuất sản xuất (đã tính yield + batch rounding) |
| **Batches** | Số batch cần chạy (= suggested ÷ BOM output qty) |
| **Start / Completion** | Ngày bắt đầu và hoàn thành dự kiến |
| **Action** | 🏭 Create MO — tạo lệnh sản xuất |

**Hành động:** Sắp xếp theo Priority → tạo MO cho các item ở đầu danh sách trước.
""",
    },
    {
        'id': 'tab_waiting',
        'title': '7. Tab ⏳ Waiting — Chờ nguyên vật liệu',
        'icon': '⏳',
        'content': """
Hiển thị các item có **nguyên vật liệu một phần** — chưa đủ để sản xuất toàn bộ.

**Thông tin bổ sung:**

| Cột | Ý nghĩa |
|-----|---------|
| **Readiness** | 🟡 Partial — một số NVL đã có |
| **Materials Ready** | Ví dụ: "3/5" = 3 trong 5 loại NVL đã đủ |
| **Max Now** | Số lượng tối đa có thể sản xuất ngay với NVL hiện có |
| **Bottleneck** | NVL gây tắc nghẽn — cần mua/chờ nhận |
| **Bottleneck ETA** | Ngày dự kiến NVL tắc nghẽn về đủ |
| **Contention** | "Yes" nếu NVL này bị nhiều sản phẩm tranh nhau |

**Phần "Top bottleneck materials"** hiện các NVL gây tắc nghẽn nhiều sản phẩm nhất.

**Hành động:**
- Kiểm tra PO Planning → đã có PO cho NVL bottleneck chưa?
- Nếu Allow Partial = On → cân nhắc sản xuất partial với Max Now
""",
    },
    {
        'id': 'tab_blocked',
        'title': '8. Tab 🔴 Blocked — Bị chặn',
        'icon': '🔴',
        'content': """
Gồm 2 loại:

**1. Blocked — NVL không có và không có ETA**
- Không có NVL nào sẵn sàng
- Không có PO hoặc thông tin ETA
- Cần tạo PO mới hoặc kiểm tra nguồn cung

**2. Unschedulable — Không thể lên lịch**
- Thiếu cấu hình lead time cho loại BOM
- BOM type không hợp lệ (không phải CUTTING/REPACKING/KITTING)
- Không có BOM active

Mỗi item Unschedulable hiện **Reason** và **Fix Action** cụ thể, ví dụ:
> ⚙️ Missing Lead Time Config — Go to Settings → Lead Time Setup

**Hành động:** Fix Unschedulable items trước (cấu hình thiếu), sau đó re-Generate.
""",
    },
    {
        'id': 'tab_timeline',
        'title': '9. Tab 📅 Timeline — Lịch sản xuất',
        'icon': '📅',
        'content': """
**Gantt Chart:**
- Mỗi thanh = 1 MO suggestion, từ Start → Completion
- Màu: 🟢 Ready, 🟡 Waiting, 🔴 Blocked
- Đường đỏ nét đứt = Ngày hôm nay
- Tối đa 30 items (sắp theo ngày bắt đầu)

**Weekly Production Schedule:**
- Bảng tổng hợp theo tuần: số MO, số Ready, giá trị

**Cách đọc:** Các thanh nằm trước đường "Today" = **OVERDUE** (đã trễ deadline).
Cần ưu tiên xử lý trước.
""",
    },
    {
        'id': 'tab_overview',
        'title': '10. Tab 📊 Overview — Tổng quan',
        'icon': '📊',
        'content': """
Tổng hợp toàn bộ kết quả:

**KPI Cards:**
- ✅ Ready: số item sẵn sàng / tổng MO lines
- ⏳ Waiting: chờ NVL
- 🔴 Blocked: bị chặn + unschedulable
- 💰 At-Risk Value: tổng giá trị tiền hàng bị ảnh hưởng
- 🚨 Overdue / Delayed: số item đã trễ

**Urgency Distribution Bar:**
Thanh ngang màu hiển thị phân bổ urgency: Overdue | Critical | Urgent | This Week | Planned

**Top 5 Urgent Items:** Danh sách 5 item cần xử lý gấp nhất.

**BOM Type Breakdown:** Phân bổ theo loại BOM (Cutting/Repacking/Kitting).

**Data Reconciliation:**
Kiểm tra đối chiếu: Total Input = Ready + Waiting + Blocked + Unschedulable + Errors.
Nếu **Balanced** ✅ = không có item nào bị mất trong quá trình xử lý.
""",
    },
    {
        'id': 'concepts',
        'title': '11. Giải thích khái niệm',
        'icon': '📚',
        'content': """
**Priority Score (Điểm ưu tiên)**
- Thấp hơn = khẩn cấp hơn (cần xử lý trước)
- Tính từ 4 yếu tố theo trọng số đã cấu hình
- Ví dụ: item OVERDUE + READY + giá trị cao + có SO → priority thấp nhất → đầu danh sách

**Urgency Levels (Mức khẩn cấp)**

| Level | Điều kiện | Ý nghĩa |
|-------|-----------|---------|
| 🚨 OVERDUE | must_start_by < hôm nay | Đã trễ deadline sản xuất |
| 🔴 CRITICAL | ≤ 3 ngày | Phải bắt đầu trong 3 ngày |
| 🟠 URGENT | ≤ 7 ngày | Phải bắt đầu trong 1 tuần |
| 🟡 THIS_WEEK | ≤ 14 ngày | Lên kế hoạch tuần này/tuần sau |
| 🔵 PLANNED | > 14 ngày | Có thời gian lập kế hoạch |

**Backward Scheduling (Lên lịch ngược)**
```
demand_date        = Ngày cần hàng (từ GAP period data)
must_start_by      = demand_date − lead_time
actual_start       = MAX(must_start_by, ngày NVL sẵn sàng, hôm nay)
expected_completion = actual_start + lead_time
is_delayed         = actual_start > must_start_by
```

**Material Contention (Tranh chấp NVL)**

Khi nhiều sản phẩm cùng cần 1 loại NVL và tổng cầu > cung:
1. **Pass 1:** Kiểm tra riêng từng sản phẩm
2. **Pass 2:** Phân bổ NVL cho sản phẩm có giá trị at-risk cao hơn trước
3. Sản phẩm bị giảm phân bổ → có thể chuyển từ READY → PARTIAL

Cột "Contention = Yes" báo hiệu item bị ảnh hưởng bởi tranh chấp NVL.

**Yield Multiplier (Hệ số sản lượng)**

Bù đắp phế phẩm: nếu scrap rate = 5% → yield_multiplier = 1/0.95 ≈ 1.0526
Suggested Qty = Shortage × yield_multiplier, làm tròn lên theo batch size.
""",
    },
    {
        'id': 'export',
        'title': '12. Export Excel',
        'icon': '📥',
        'content': """
Nút **📥 Export Excel** tạo file Excel 6 sheets:

| Sheet | Nội dung |
|-------|---------|
| **Ready MOs** | Danh sách MO sẵn sàng — gửi cho bộ phận sản xuất |
| **Waiting MOs** | Chờ NVL — gửi cho bộ phận mua hàng |
| **Blocked MOs** | Bị chặn — cần can thiệp |
| **Unschedulable** | Không lên lịch được — cần fix cấu hình |
| **Material Matrix** | Ma trận NVL: sản phẩm × NVL × coverage % |
| **Summary** | KPIs, reconciliation, config snapshot |

File có format chuyên nghiệp: header màu, freeze panes, auto-filter,
hàng tô màu theo urgency/readiness, format tiền tệ & số.

Tên file: `MO_Suggestions_YYYYMMDD_HHMM.xlsx`
""",
    },
    {
        'id': 'faq',
        'title': '13. FAQ & Xử lý sự cố',
        'icon': '❓',
        'content': """
**Q: Nút Generate bị disable?**
- Kiểm tra pipeline bar ở trên: GAP đã chạy chưa? (cần hiện ✓)
- Kiểm tra Settings: progress bar đã 100% chưa?

**Q: "No MO suggestions needed"?**
- GAP không tìm thấy sản phẩm sản xuất nào thiếu hụt
- Kiểm tra lại GAP filters (MO_EXPECTED có ON không?)

**Q: Nhiều item Unschedulable?**
- Thiếu lead time config cho loại BOM → vào Settings → Lead Time Setup
- BOM type không hợp lệ → kiểm tra BOM header trong hệ thống

**Q: Kết quả khác lần chạy trước?**
- Production Planning chạy on-the-fly, không lưu DB
- Mỗi lần Generate lấy dữ liệu mới nhất từ GAP + DB
- Nếu GAP được chạy lại với filter khác → kết quả MO sẽ khác

**Q: Muốn chỉ xem sản phẩm 1 brand?**
- Filter ở GAP level (dùng brand/product filter trong Supply Chain GAP)
- Production Planning sẽ tự động chỉ xử lý sản phẩm trong filter

**Q: Priority score của tôi quá cao/thấp?**
- Điều chỉnh priority weights trong Settings
- Time urgency weight cao → item gần deadline được ưu tiên
- Value weight cao → item giá trị cao được ưu tiên

**Q: Contention flag nhưng NVL có vẻ đủ?**
- Contention xảy ra khi TỔNG CẦU từ nhiều sản phẩm > cung
- Mỗi sản phẩm riêng lẻ có thể đủ, nhưng gộp lại thì không
- Item với at-risk value cao hơn được phân bổ trước
""",
    },
]


# =============================================================================
# RENDER FUNCTIONS
# =============================================================================

def render_user_guide_button():
    """
    Render the user guide button + popover using st.popover.
    Wide floating popover with full guide content.
    """
    with st.popover("📖 Hướng dẫn sử dụng", use_container_width=False):
        st.markdown(
            f"## 🏭 Production Planning — Hướng dẫn sử dụng\n"
            f"*Phiên bản {VERSION} — Tài liệu tra cứu & training*"
        )
        st.markdown("---")

        # Table of contents
        toc_parts = [
            f"**{s['icon']} {s['title']}**"
            for s in GUIDE_SECTIONS
        ]
        st.caption("Mục lục: " + " · ".join(toc_parts))

        st.markdown("")

        # Render each section as expander
        for section in GUIDE_SECTIONS:
            with st.expander(
                f"{section['icon']} {section['title']}",
                expanded=False,
            ):
                st.markdown(section['content'])


def render_user_guide_sidebar():
    """
    Render the user guide in sidebar as expandable sections.
    Alternative to popover for narrower layout.
    """
    st.markdown("### 📖 Hướng dẫn")
    for section in GUIDE_SECTIONS:
        with st.expander(f"{section['icon']} {section['title']}", expanded=False):
            st.markdown(section['content'])


def get_guide_section(section_id: str) -> dict:
    """Get a specific guide section by ID. For programmatic access."""
    for s in GUIDE_SECTIONS:
        if s['id'] == section_id:
            return s
    return {}


def get_guide_markdown() -> str:
    """Export full guide as single markdown string — for documentation export."""
    parts = [
        f"# 🏭 Production Planning — Hướng dẫn sử dụng\n",
        f"*Phiên bản {VERSION}*\n",
        "---\n",
    ]
    for section in GUIDE_SECTIONS:
        parts.append(f"## {section['icon']} {section['title']}\n")
        parts.append(section['content'].strip())
        parts.append("\n---\n")
    return "\n".join(parts)
