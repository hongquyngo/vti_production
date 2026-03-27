# utils/supply_chain_production/production_help.py

"""
User Guide for Production Planning — floating popover.

Comprehensive guide for training and reference.
Reorganized in v1.3.0 with deep Settings parameter guidance.

Structure:
  Part I:   Getting Started (overview, prerequisites, quick start)
  Part II:  Settings Deep-Dive (BOM LT, fallback LT, priority, planning, yield)
  Part III: Using the Module (filter scope, generate, 3 view modes, 4 result tabs)
  Part IV:  Reference (concepts, export, FAQ)

Usage:
    from utils.supply_chain_production.production_help import render_user_guide_button
    render_user_guide_button()
"""

import streamlit as st

VERSION = "1.3.0"


# =============================================================================
# GUIDE CONTENT
# =============================================================================

GUIDE_SECTIONS = [

    # =========================================================================
    # PART I — GETTING STARTED
    # =========================================================================

    {
        'id': 'overview',
        'title': '1. Tổng quan',
        'icon': '🏭',
        'part': 'I',
        'content': """
**Production Planning** (Kế hoạch Sản xuất) là module Layer 3 trong SCM Planning Pipeline.

**Chức năng chính:**
- Nhận danh sách sản phẩm thiếu hụt từ Supply Chain GAP
- Kiểm tra nguyên vật liệu sẵn có (2-pass: individual + contention)
- Tạo đề xuất Lệnh Sản xuất (MO) với lịch trình, ưu tiên, và hành động cụ thể

**Vị trí trong pipeline:**
```
Supply Chain GAP ──┬── PO Planning  (mua hàng — Layer 3 Phase 1)
                   └── Production Planning (sản xuất — Layer 3 Phase 2) ← bạn đang ở đây
```

PO và Production Planning là 2 nhánh **song song** từ GAP, không phải tuần tự.

**5 tab giao diện:**

| Tab | Mô tả |
|-----|-------|
| 📊 Overview | KPIs, ma trận urgency × readiness, top urgent, reconciliation |
| ✅ Ready | Sản phẩm sẵn sàng sản xuất — 3 chế độ xem: Summary / Schedule / Detail |
| ⏳ Waiting | Chờ NVL — bottleneck analysis, ETA forecast |
| 🔴 Blocked | Bị chặn + unschedulable — cần can thiệp |
| ⚙️ Settings | Cấu hình tham số — **làm 1 lần, dùng mãi** |

**Nguyên tắc ZERO ASSUMPTION:** Mọi tham số phải được cấu hình rõ ràng. Không có giá trị mặc định ẩn.
Nếu thiếu cấu hình → hệ thống dừng và thông báo rõ ràng.
""",
    },

    {
        'id': 'prerequisites',
        'title': '2. Điều kiện tiên quyết',
        'icon': '✅',
        'part': 'I',
        'content': """
**Bước 1: Chạy Supply Chain GAP** (bắt buộc)
- Vào trang **Supply Chain GAP** → chạy phân tích với cấu hình phù hợp
- GAP xác định sản phẩm nào thiếu hụt và cần sản xuất
- Kết quả GAP được lưu trong session — không cần export

**Bước 2: Cấu hình Settings** (bắt buộc, lần đầu)
- Vào tab **⚙️ Settings** → điền các thông số bắt buộc
- Hoặc dùng **⚡ Apply Defaults** để điền nhanh từ dữ liệu lịch sử
- Cấu hình lưu vào DB — **chỉ cần làm 1 lần**, sau đó chỉ chỉnh sửa khi cần

**Không bắt buộc nhưng có lợi:**
- Chạy **PO Planning** trước → Production Planning sẽ có thêm ETA nguyên vật liệu từ PO → cải thiện độ chính xác của ngày bắt đầu sản xuất
- Thiết lập **BOM Lead Times** per BOM → chính xác hơn fallback defaults

**Thứ tự khuyến nghị:**
```
1. GAP (bắt buộc) → 2. PO Planning (khuyến nghị) → 3. Production Planning
```
""",
    },

    {
        'id': 'quick_start',
        'title': '3. Quick Start — Cấu hình nhanh',
        'icon': '⚡',
        'part': 'I',
        'content': """
Khi mở trang lần đầu và chưa có cấu hình, hệ thống hiện thanh **Quick Start**:

> 💡 Quick start available. Historical data found: CUTTING avg 2.5d (992 MOs)...
> [⚡ Apply Defaults]

**Khi bấm "Apply Defaults"**, hệ thống sẽ:**
1. **Lead time:** Lấy từ lịch sử MO đã hoàn thành (làm tròn lên, tối thiểu 1 ngày)
2. **Priority weights:** Áp dụng tỷ lệ chuẩn 40 / 25 / 20 / 15
3. **Planning horizon:** 60 ngày
4. **Historical override:** Tắt (bảo thủ — dùng config value, không tự override)
5. Tất cả giá trị được lưu vào DB ngay lập tức → trang tự reload → sẵn sàng chạy

**Sau khi Apply**, bạn vẫn nên review và chỉnh sửa nếu cần. Đặc biệt:
- Lead time cho từng BOM type có phù hợp thực tế không?
- Priority weights có phản ánh ưu tiên kinh doanh không?

**Xem chi tiết từng tham số ở mục 4–8 bên dưới.**
""",
    },

    # =========================================================================
    # PART II — SETTINGS DEEP-DIVE
    # =========================================================================

    {
        'id': 'settings_bom_lt',
        'title': '4. ⚙️ BOM Lead Times — Lead time per BOM',
        'icon': '🏭',
        'part': 'II',
        'content': """
**Đây là cấp cấu hình chính xác nhất.** Mỗi BOM có lead time riêng.

**Vị trí:** Tab Settings → panel **"🏭 BOM Lead Times"** ở đầu trang.

**Ý nghĩa:**
- Lead time = thời gian từ khi bắt đầu sản xuất → hoàn thành (bao gồm setup, processing, QC)
- Mỗi BOM có thể có lead time khác nhau dù cùng BOM type (vd: BOM cắt cuộn lớn khác cuộn nhỏ)
- Có thể map theo nhà máy (plant) nếu cùng BOM nhưng khác xưởng sẽ có thời gian khác

**Cách điền:**

| Trường | Ý nghĩa | Cách chọn giá trị |
|--------|---------|-------------------|
| **Standard LT** | Lead time tiêu chuẩn (ngày) | Dùng cho lập lịch. Hỏi quản đốc: "Bình thường cần bao nhiêu ngày?" |
| **Min LT** | Best-case (ngày) | Khi NVL đủ, máy trống, team đầy đủ. Thường = 60-80% Standard |
| **Max LT** | Worst-case (ngày) | Khi gặp trục trặc (máy hỏng, thiếu người, QC fail). Thường = 150-200% Standard |
| **Plant** | Nhà máy | Chọn "Global" nếu chỉ có 1 xưởng. Chọn plant cụ thể nếu có nhiều xưởng |

**3 cách tạo BOM Lead Times:**

1. **📥 Bulk Fill from Historical** — tự động điền từ lịch sử MO đã hoàn thành
   - Chỉ điền cho BOM chưa có config (không ghi đè)
   - Standard LT = ceil(avg historical) = làm tròn lên → bảo thủ
   - Min/Max lấy từ lịch sử thực tế
   - Nên dùng khi mới bắt đầu → sau đó review + chỉnh tay

2. **✏️ Edit BOM Lead Time** — chỉnh tay từng BOM
   - Chọn BOM → điền Standard/Min/Max → Save
   - Dùng khi biết rõ lead time cụ thể (vd: BOM mới, thay đổi quy trình)

3. **🏭 Manage Plants** — quản lý nhà máy (nếu có nhiều xưởng)
   - Tạo plant → sau đó có thể set lead time per BOM per plant

**Gợi ý lịch sử:** Bảng overview hiện "Hist Avg", "Hist Min", "Hist Max", "MOs" —
dùng để tham khảo. VD: "Hist Avg 2.5d, 42 MOs" = trung bình 2.5 ngày từ 42 MO đã hoàn thành.

**Khi nào cần cập nhật?**
- Thay đổi quy trình sản xuất (máy mới, layout mới)
- Thay đổi nhân sự (thêm/giảm ca)
- Mùa cao điểm vs thấp điểm
""",
    },

    {
        'id': 'settings_lt_fallback',
        'title': '5. ⚙️ Lead Time Fallback — Giá trị mặc định',
        'icon': '📅',
        'part': 'II',
        'content': """
**Vị trí:** Tab Settings → expander **"📅 Lead Time — Fallback Defaults"**

**Ý nghĩa:** Khi một BOM chưa có row trong bảng BOM Lead Times, hệ thống dùng giá trị này.
Đây là **lưới an toàn** — đảm bảo mọi BOM đều có lead time để lên lịch.

**⚠️ BẮT BUỘC** — nếu để trống, hệ thống KHÔNG THỂ lên lịch sản xuất.

**3 giá trị cần điền:**

| BOM Type | Ý nghĩa | Cách chọn giá trị | Ví dụ thực tế |
|----------|---------|-------------------|---------------|
| **CUTTING** (✂️ Cắt) | Cắt 1 input lớn → N output nhỏ (vd: cuộn băng keo lớn → cuộn nhỏ) | Hỏi xưởng cắt: "Trung bình 1 đơn cắt mất bao lâu?" Cộng thêm 1 ngày buffer | VD: avg 2.5d → điền **3 ngày** |
| **REPACKING** (📦 Đóng gói) | Đóng gói lại format khác (vd: thùng lớn → hộp lẻ) | Thường nhanh nhất. Nếu lịch sử = 0d, điền tối thiểu **1 ngày** | VD: avg 0.0d → điền **1 ngày** |
| **KITTING** (🔧 Ghép bộ) | Kết hợp N input → 1 output (vd: bộ kit sản phẩm) | Phụ thuộc số component. Nếu lịch sử = 1.8d → điền **2 ngày** | VD: avg 1.8d → điền **2 ngày** |

**💡 Dưới mỗi ô nhập** có gợi ý: "📊 Historical: avg 2.5d from 992 MOs across 40 BOMs"
→ Dùng con số này + buffer 0.5–1 ngày = giá trị phù hợp.

**Quy tắc: Nên điền lớn hơn trung bình lịch sử**, vì:
- Fallback dùng cho BOM chưa có data riêng → bảo thủ tốt hơn
- Deadline trễ = đặt hàng sớm hơn → an toàn hơn deadline sớm = trễ giao hàng

---

**Historical Override (Tùy chọn nâng cao)**

Khi bật **"Use historical lead time override"**:
- Hệ thống sẽ thay thế giá trị cấu hình bằng trung bình lịch sử **nếu có đủ dữ liệu**
- Ngưỡng: "Min MOs per product" (mặc định 5) + "Min MOs per BOM type" (mặc định 10)

**Khi nào nên bật?**
- Khi dữ liệu lịch sử phong phú (>1000 MO completed) và ổn định
- Khi muốn hệ thống tự điều chỉnh theo thực tế

**Khi nào KHÔNG nên bật?**
- Mới bắt đầu dùng, dữ liệu ít
- Có thay đổi lớn về quy trình (data cũ không còn đại diện)
- Muốn kiểm soát hoàn toàn lead time
""",
    },

    {
        'id': 'settings_priority',
        'title': '6. ⚙️ Priority Weights — Trọng số ưu tiên',
        'icon': '⚖️',
        'part': 'II',
        'content': """
**Vị trí:** Tab Settings → expander **"⚖️ Priority Weights"**

**Ý nghĩa:** Mỗi MO suggestion được chấm điểm ưu tiên (priority score) từ 4 yếu tố.
**Điểm thấp hơn = khẩn cấp hơn = đứng đầu danh sách.**

Trọng số quyết định yếu tố nào quan trọng hơn. **Tổng PHẢI = 100%.**

**4 yếu tố và cách chọn trọng số:**

| Yếu tố | Ý nghĩa | Tăng trọng số khi... | Giảm khi... | Gợi ý |
|---------|---------|---------------------|-------------|-------|
| **Time urgency** | Còn bao lâu đến ngày cần hàng | Thường xuyên giao trễ, deadline là ưu tiên #1 | Lead time ngắn, ít áp lực thời gian | **40%** |
| **Material readiness** | NVL sẵn sàng đến đâu (Ready > Partial > Blocked) | Muốn ưu tiên sản xuất ngay cái có NVL đủ | Không quan tâm NVL đủ hay thiếu | **25%** |
| **At-risk value** | Giá trị tiền hàng bị ảnh hưởng (USD) | Sản phẩm giá trị cao cần ưu tiên hơn | Tất cả sản phẩm cùng tầm quan trọng | **20%** |
| **Customer linkage** | Có đơn hàng (SO) liên kết không | Khách hàng đã đặt hàng cần ưu tiên tuyệt đối | Sản xuất chủ yếu để kho, ít đơn hàng | **15%** |

**Các kịch bản phổ biến:**

| Kịch bản | Time | Readiness | Value | Customer |
|----------|------|-----------|-------|----------|
| **Chuẩn (khuyến nghị)** | 40 | 25 | 20 | 15 |
| **Giao hàng là ưu tiên #1** | 50 | 15 | 15 | 20 |
| **Tối ưu hiệu suất xưởng** | 20 | 45 | 20 | 15 |
| **Bảo vệ doanh thu** | 25 | 15 | 40 | 20 |
| **Khách hàng trước hết** | 30 | 10 | 15 | 45 |

**Ví dụ cụ thể:** Với trọng số chuẩn 40/25/20/15:
- Item A: Overdue + Ready + $50K + có SO → score ≈ 5 (rất thấp = ưu tiên cao)
- Item B: Planned + Blocked + $1K + không SO → score ≈ 75 (cao = ưu tiên thấp)
""",
    },

    {
        'id': 'settings_planning',
        'title': '7. ⚙️ Planning Parameters — Tham số lập kế hoạch',
        'icon': '📋',
        'part': 'II',
        'content': """
**Vị trí:** Tab Settings → expander **"📋 Planning Parameters"**

**2 tham số:**

---

**1. Planning Horizon (ngày) — BẮT BUỘC**

**Ý nghĩa:** Khi GAP không có ngày cụ thể cho sản phẩm, hệ thống dùng:
`demand_date = hôm nay + planning_horizon`

**Cách chọn:**
- **60 ngày (khuyến nghị):** Phù hợp đa số trường hợp. Lead time trung bình 3 ngày + buffer 57 ngày = đủ thời gian lên kế hoạch
- **30 ngày:** Nếu muốn chỉ focus ngắn hạn (nhưng dễ bị nhiều item OVERDUE)
- **90 ngày:** Nếu lead time dài (vd: nhập NVL từ nước ngoài 30-60 ngày)

**Quy tắc:**
- Planning horizon < max lead time → item sẽ bị OVERDUE ngay từ đầu → không tốt
- Planning horizon quá lớn → item nằm trong "PLANNED" nhiều → giảm urgency → planner mất focus

---

**2. Allow Partial Production (on/off)**

**Ý nghĩa:** Khi bật, tab Waiting hiện thêm cột **"Max Producible Now"** — số lượng tối đa có thể sản xuất ngay với NVL hiện có.

**Cách chọn:**
- **ON (khuyến nghị):** Planner biết có thể sản xuất 1 phần trước khi NVL đủ. Hữu ích khi cần giao gấp
- **OFF:** Ẩn cột Max Now. Chỉ hiện khi NVL đủ 100% mới đề xuất sản xuất

**Lưu ý:** Bật/tắt KHÔNG ảnh hưởng MO suggestion qty — chỉ ảnh hưởng thông tin hiển thị.
""",
    },

    {
        'id': 'settings_yield',
        'title': '8. ⚙️ Yield Setup — Hệ số phế phẩm',
        'icon': '📊',
        'part': 'II',
        'content': """
**Vị trí:** Tab Settings → expander **"📊 Yield Setup — Optional"**

**Ý nghĩa:** Bù đắp hao hụt trong sản xuất. Nếu scrap rate = 5%, hệ thống sẽ đề xuất sản xuất nhiều hơn 5% để đảm bảo đủ output.

**Mặc định:** Dùng scrap rate đã khai báo trong BOM detail line. Nếu BOM line có scrap_rate = 3% → yield_multiplier = 100/(100-3) ≈ 1.031

**Khi nào cần cấu hình thêm?**

Chỉ khi scrap rate thực tế **khác nhiều** so với BOM:
- BOM khai scrap 2% nhưng thực tế luôn hao 8% → cần override
- Quy trình đã cải tiến, scrap thực tế thấp hơn BOM → override để giảm qty

**Tùy chọn:**

| Tùy chọn | Ý nghĩa | Khi nào bật |
|-----------|---------|-------------|
| **Historical yield override** | Dùng tỷ lệ yield thực tế từ MO đã hoàn thành | Khi có >5 MO completed per product VÀ scrap rate BOM không chính xác |
| **Default scrap % per BOM type** | Scrap rate mặc định khi BOM line không có giá trị | Khi nhiều BOM line để trống scrap_rate |

**Khuyến nghị cho phần lớn người dùng:** Để mặc định (OFF + không điền). Scrap rate từ BOM là đủ chính xác.
""",
    },

    # =========================================================================
    # PART III — USING THE MODULE
    # =========================================================================

    {
        'id': 'filter_scope',
        'title': '9. Display Filter Scope — Lọc theo Brand/Sản phẩm',
        'icon': '🔍',
        'part': 'III',
        'content': """
Khi Supply Chain GAP được chạy với **brand filter** (vd: chỉ phân tích brand "3M"),
Production Planning sẽ tự động phát hiện và hiện **bộ chọn scope**:

```
🔍 GAP Display Filter Detected
SCM GAP was analyzed with filter: Brand: 3M

🎯 Filtered — Brand: 3M          🟠 Full — all products
42 of 388 FG products              388 FG products

MO Planning scope:  ◉ Filtered (Brand: 3M)  ○ Full (all 388 FG)
```

**2 lựa chọn:**
- **🎯 Filtered:** Chỉ tạo MO suggestion cho sản phẩm matching filter (42 sản phẩm brand 3M)
- **🟠 Full:** Tạo MO suggestion cho TẤT CẢ sản phẩm (388 sản phẩm)

**Khi nào chọn Filtered?**
- Khi chỉ muốn focus brand cụ thể (vd: review kế hoạch sản xuất cho 3M)
- Nhanh hơn, kết quả gọn hơn

**Khi nào chọn Full?**
- Khi muốn xem toàn bộ bức tranh sản xuất
- Khi NVL dùng chung giữa nhiều brand → cần xem contention đầy đủ
""",
    },

    {
        'id': 'generate',
        'title': '10. Generate — Chạy đề xuất MO',
        'icon': '🔄',
        'part': 'III',
        'content': """
**Nút "🔄 Generate MO Suggestions"** khả dụng khi:
- ✅ Settings đầy đủ (progress bar 100%)
- ✅ Supply Chain GAP đã chạy

**Pipeline xử lý khi bấm Generate:**

```
1. Filter Scope     → Áp dụng brand/product filter nếu có
2. Config Gate      → Kiểm tra cấu hình đầy đủ
3. Extract from GAP → Lấy danh sách sản phẩm cần sản xuất
4. SO Linkage       → Kiểm tra sản phẩm nào có đơn hàng
5. Material Check   → 2-pass kiểm tra NVL (cá nhân → tranh chấp)
6. Schedule         → Lên lịch sản xuất (backward scheduling, 4-tier LT)
7. Prioritize       → Chấm điểm ưu tiên (4 yếu tố × weights)
8. Build MO Lines   → Tạo đề xuất MO với 40+ trường thông tin
9. Categorize       → Phân loại: Ready / Waiting / Blocked
10. Reconciliation  → Kiểm tra đối chiếu (input = output, không mất item)
```

Thời gian xử lý: thường **< 5 giây** cho ~130 sản phẩm.

**Kết quả không lưu DB** — chạy on-the-fly mỗi lần Generate.
""",
    },

    {
        'id': 'view_modes',
        'title': '11. 3 chế độ xem — Summary / Schedule / Detail',
        'icon': '👁️',
        'part': 'III',
        'content': """
Mỗi tab kết quả (Ready, Waiting, Blocked) có **3 chế độ xem** chuyển qua nút radio:

---

**📊 Summary — Tổng hợp nhanh**

Dành cho: Nắm bức tranh tổng thể trong 10 giây.

| Tab | Summary hiện gì |
|-----|-----------------|
| ✅ Ready | By Workshop (BOM Type) + By Start Week + By Brand |
| ⏳ Waiting | Bottleneck Materials + ETA Forecast + Almost Ready highlight |
| 🔴 Blocked | (không có Summary — chuyển Detail / Schedule) |

---

**📅 Schedule — Lịch sản xuất Product × Date**

Dành cho: **Lên kế hoạch sản xuất cụ thể** — view quan trọng nhất cho planner.

Bảng dạng pivot: Hàng = Sản phẩm, Cột = Ngày (hoặc Tuần), Ô = Số lượng.

3 điều khiển:
- **Cell values:** Suggested Qty / Batches / Shortage Qty / At Risk Value ($)
- **Date column:** Start Date / Completion Date / Demand Date
- **Period:** Daily / Weekly

Màu sắc: Ô có giá trị cao = màu đậm hơn. Cột Total = tổng cộng. Hàng Total = tổng cộng.

---

**📋 Detail — Bảng chi tiết**

Dành cho: Review từng dòng MO, xem tất cả 20+ cột thông tin.

Đây là bảng flat truyền thống với đầy đủ: Priority, Urgency, Code, Product, BOM, Shortage,
Suggested Qty, Batches, Readiness, Materials, Bottleneck, Start, Completion, At Risk, Action, v.v.
""",
    },

    {
        'id': 'tab_ready',
        'title': '12. Tab ✅ Ready — Sẵn sàng sản xuất',
        'icon': '✅',
        'part': 'III',
        'content': """
Hiển thị các MO suggestion có **đầy đủ nguyên vật liệu** → có thể tạo MO ngay.

**5 KPI cards ở đầu tab:**
- MO Lines: tổng số item ready
- Total Batches: tổng batch cần chạy
- Total Qty: tổng số lượng đề xuất
- Value ($): tổng giá trị at-risk
- Brands: số brand khác nhau

**Hành động cho Planner:**

1. Mở **📊 Summary** → xem "By Workshop" để phân công xưởng
   - VD: "CUTTING: 35 items, 180 batches" → giao xưởng cắt
   - VD: "REPACKING: 8 items, 25 batches" → giao xưởng đóng gói

2. Mở **📅 Schedule** → xem Product × Date → biết hôm nay/mai cần sản xuất gì

3. Mở **📋 Detail** → sắp xếp theo Priority → tạo MO cho item đầu danh sách trước

**Cột Product:** Hiển thị đầy đủ: Tên sản phẩm, Package size, Brand.
VD: "Băng keo OPP 48mm × 100m (Vietape)"
""",
    },

    {
        'id': 'tab_waiting',
        'title': '13. Tab ⏳ Waiting — Chờ nguyên vật liệu',
        'icon': '⏳',
        'part': 'III',
        'content': """
Hiển thị các item có **NVL một phần** — chưa đủ để sản xuất toàn bộ.

**5 KPI cards:**
- Waiting Items: tổng số item chờ
- Value ($): tổng giá trị at-risk
- Has ETA: bao nhiêu item có ngày dự kiến NVL về
- Almost Ready: bao nhiêu item ≥80% NVL đã đủ
- Bottleneck NVL: bao nhiêu loại NVL gây tắc nghẽn

**📊 Summary → 2 view quan trọng:**

1. **🧱 Bottleneck Materials** — NVL nào gây tắc nhiều nhất?
   - Sắp theo "Blocks N products" giảm dần
   - Biết NVL nào cần push PO trước → unlock nhiều MO nhất
   - VD: "MAT-001 blocks 8 products, $45K value blocked, ETA: 2026-04-05"
   - → Gọi supplier push giao MAT-001 = unlock 8 sản phẩm

2. **📅 ETA Forecast** — Tuần sau có thêm bao nhiêu item chuyển sang Ready?
   - VD: "W14: 12 items unlock, $30K" → tuần sau xưởng sẽ có thêm 12 item để sản xuất
   - "🟢 5 items ≥80% ready" → cân nhắc sản xuất partial trước

**Hành động:**
- Push PO cho bottleneck materials (check PO Planning)
- Items "Almost Ready" → cân nhắc partial production nếu giao gấp
""",
    },

    {
        'id': 'tab_blocked',
        'title': '14. Tab 🔴 Blocked — Bị chặn',
        'icon': '🔴',
        'part': 'III',
        'content': """
Gồm **2 loại:**

**1. Blocked — NVL không có, không có ETA**
- Không có NVL nào sẵn sàng
- Không có PO hoặc thông tin ETA
- **Hành động:** Tạo PO mới (check PO Planning) hoặc liên hệ supplier

**2. Unschedulable — Không thể lên lịch**
- Thiếu cấu hình lead time cho loại BOM
- BOM type không hợp lệ
- Không có BOM active

Mỗi item Unschedulable hiện **Reason** + **Fix Action** cụ thể:
> ⚙️ Missing Lead Time Config → "Go to Settings → Lead Time Setup"

**Hành động:**
1. Fix Unschedulable trước (cấu hình thiếu)
2. Re-Generate → item sẽ chuyển sang Ready/Waiting/Blocked
3. Blocked items → tạo PO cho NVL thiếu
""",
    },

    {
        'id': 'tab_overview',
        'title': '15. Tab 📊 Overview — Tổng quan',
        'icon': '📊',
        'part': 'III',
        'content': """
Tổng hợp toàn bộ kết quả — dành cho **báo cáo nhanh và quản lý**.

**Nội dung từ trên xuống:**

1. **Data Flow:** GAP → Ready / Waiting / Blocked / Unschedulable (1 dòng tóm tắt)

2. **KPI Cards:** Ready count, Waiting, Blocked, At-Risk Value, Overdue/Delayed

3. **Urgency Distribution Bar:** Thanh màu: 🚨 Overdue | 🔴 Critical | 🟠 Urgent | 🟡 This Week | 🔵 Planned

4. **🎯 Urgency × Readiness Matrix:** Bảng 2 chiều: Urgency (hàng) × Readiness (cột). Ô = count ($value).
   **Góc trên-trái (Critical + Ready) = hành động ngay.** VD: "2 ($8,000)" = 2 item critical mà NVL đã đủ.

5. **Top 5 Urgent Items:** Danh sách nhanh 5 item cần xử lý gấp nhất.

6. **BOM Type Breakdown:** Phân bổ theo loại BOM (tổng, ready, value).

7. **Data Reconciliation:** Kiểm tra Total Input = Ready + Waiting + Blocked + Unschedulable. "Balanced ✅" = không mất item.
""",
    },

    # =========================================================================
    # PART IV — REFERENCE
    # =========================================================================

    {
        'id': 'concepts',
        'title': '16. Giải thích khái niệm',
        'icon': '📚',
        'part': 'IV',
        'content': """
**Urgency Levels (Mức khẩn cấp)**

| Level | Điều kiện | Ý nghĩa |
|-------|-----------|---------|
| 🚨 OVERDUE | must_start_by < hôm nay | Đã trễ deadline sản xuất — cần làm ngay |
| 🔴 CRITICAL | ≤ 3 ngày | Phải bắt đầu trong 3 ngày |
| 🟠 URGENT | ≤ 7 ngày | Phải bắt đầu trong 1 tuần |
| 🟡 THIS_WEEK | ≤ 14 ngày | Lên kế hoạch tuần này/tuần sau |
| 🔵 PLANNED | > 14 ngày | Có thời gian lập kế hoạch |

**Backward Scheduling (Lên lịch ngược)**

```
demand_date        = Ngày cần hàng (từ GAP hoặc planning_horizon fallback)
must_start_by      = demand_date − lead_time
actual_start       = MAX(must_start_by, ngày NVL sẵn sàng, hôm nay)
expected_completion = actual_start + lead_time
is_delayed         = actual_start > must_start_by
```

Lead time giải quyết theo 4 tầng ưu tiên:
```
Tier 1a: BOM + Plant specific  (bom_lead_times + plant_id)
Tier 1b: BOM global            (bom_lead_times + plant IS NULL)
Tier 1c: BOM type default      (production_planning_config fallback)
Tier 2:  Historical override   (nếu bật + đủ dữ liệu lịch sử)
```

**Material Contention (Tranh chấp NVL)**

Khi nhiều sản phẩm cùng cần 1 loại NVL và tổng cầu > tổng cung:
1. **Pass 1:** Kiểm tra riêng từng sản phẩm (NVL đủ/thiếu)
2. **Pass 2:** Phân bổ NVL cho sản phẩm có at-risk value cao hơn trước
3. Sản phẩm bị giảm phân bổ → có thể chuyển từ READY → PARTIAL

**Yield Multiplier (Hệ số sản lượng)**

Bù đắp phế phẩm: scrap rate 5% → yield_multiplier = 1/0.95 ≈ 1.053
Suggested Qty = Shortage × yield_multiplier, làm tròn lên theo batch size (BOM output qty).
""",
    },

    {
        'id': 'export',
        'title': '17. Export Excel',
        'icon': '📥',
        'part': 'IV',
        'content': """
Nút **📥 Export Excel** (cuối trang, dưới tabs) tạo file 6 sheets:

| Sheet | Nội dung | Gửi cho |
|-------|---------|---------|
| **Ready MOs** | MO sẵn sàng — có action, priority, schedule | Bộ phận sản xuất |
| **Waiting MOs** | Chờ NVL — có bottleneck, ETA, contention | Bộ phận mua hàng |
| **Blocked MOs** | Bị chặn — cần can thiệp | Quản lý sản xuất |
| **Unschedulable** | Không lên lịch được — reason + fix | IT / Admin |
| **Material Matrix** | Sản phẩm × NVL × coverage % | Kho / NVL |
| **Summary** | KPIs, reconciliation, config snapshot | Quản lý |

Format: Header màu, freeze panes, auto-filter, hàng tô màu theo urgency/readiness.
Tên file: `MO_Suggestions_YYYYMMDD_HHMM.xlsx`
""",
    },

    {
        'id': 'faq',
        'title': '18. FAQ & Xử lý sự cố',
        'icon': '❓',
        'part': 'IV',
        'content': """
**Q: Nút Generate bị disable?**
→ Kiểm tra: (1) GAP đã chạy chưa? (2) Settings progress bar đã 100% chưa?

**Q: "No MO suggestions needed"?**
→ GAP không tìm thấy sản phẩm sản xuất nào thiếu. Kiểm tra GAP filters (MO_EXPECTED có ON không?).

**Q: Nhiều item Unschedulable?**
→ Thiếu lead time config. Vào Settings → Lead Time Fallback Defaults → điền giá trị cho cả 3 BOM type.

**Q: Kết quả khác lần chạy trước?**
→ Bình thường. Mỗi lần Generate lấy data mới nhất từ GAP + DB. Nếu GAP chạy lại với filter khác → MO khác.

**Q: Priority score tôi quá cao/thấp?**
→ Điều chỉnh priority weights trong Settings. Time weight cao → item gần deadline ưu tiên. Value weight cao → item giá trị lớn ưu tiên.

**Q: Contention flag nhưng NVL có vẻ đủ?**
→ Contention = TỔNG CẦU từ nhiều sản phẩm > cung. Mỗi sản phẩm riêng lẻ có thể đủ, gộp lại thì không.

**Q: Muốn chỉ xem 1 brand?**
→ Filter ở GAP level (brand filter trong Supply Chain GAP). Production Planning tự phát hiện và hiện scope selector.

**Q: Schedule grid toàn số 0?**
→ Tất cả item cùng start date → chỉ 1 cột có data. Chuyển sang "Weekly" hoặc đổi Date column.

**Q: Khi nào cần cập nhật Settings?**
→ Khi: thay đổi quy trình sản xuất, thay đổi nhân sự/ca, chuyển mùa, hoặc lead time thực tế khác config > 20%.
""",
    },
]


# =============================================================================
# RENDER FUNCTIONS
# =============================================================================

def render_user_guide_button():
    """Render the user guide button + popover."""
    with st.popover("📖 Hướng dẫn sử dụng", use_container_width=False):
        st.markdown(
            f"## 🏭 Production Planning — Hướng dẫn sử dụng\n"
            f"*Phiên bản {VERSION} — Tài liệu tra cứu & training*"
        )
        st.markdown("---")

        # Table of contents grouped by part
        parts = {
            'I': 'Bắt đầu',
            'II': 'Cấu hình Settings',
            'III': 'Sử dụng module',
            'IV': 'Tra cứu',
        }
        for part_key, part_label in parts.items():
            sections = [s for s in GUIDE_SECTIONS if s.get('part') == part_key]
            toc = " · ".join(f"{s['icon']} {s['title'].split('. ', 1)[-1]}" for s in sections)
            st.caption(f"**Part {part_key}: {part_label}** — {toc}")

        st.markdown("")

        # Render each section as expander, grouped
        current_part = None
        for section in GUIDE_SECTIONS:
            part = section.get('part', '')
            if part != current_part:
                current_part = part
                part_label = parts.get(part, '')
                st.markdown(f"---\n#### Part {part}: {part_label}")

            with st.expander(
                f"{section['icon']} {section['title']}",
                expanded=False,
            ):
                st.markdown(section['content'])


def render_user_guide_sidebar():
    """Render the user guide in sidebar as expandable sections."""
    st.markdown("### 📖 Hướng dẫn")
    for section in GUIDE_SECTIONS:
        with st.expander(f"{section['icon']} {section['title']}", expanded=False):
            st.markdown(section['content'])


def get_guide_section(section_id: str) -> dict:
    """Get a specific guide section by ID."""
    for s in GUIDE_SECTIONS:
        if s['id'] == section_id:
            return s
    return {}


def get_guide_markdown() -> str:
    """Export full guide as single markdown string."""
    parts_map = {
        'I': 'Bắt đầu',
        'II': 'Cấu hình Settings',
        'III': 'Sử dụng module',
        'IV': 'Tra cứu',
    }
    output = [
        f"# 🏭 Production Planning — Hướng dẫn sử dụng\n",
        f"*Phiên bản {VERSION}*\n",
        "---\n",
    ]
    current_part = None
    for section in GUIDE_SECTIONS:
        part = section.get('part', '')
        if part != current_part:
            current_part = part
            output.append(f"\n# Part {part}: {parts_map.get(part, '')}\n")
        output.append(f"## {section['icon']} {section['title']}\n")
        output.append(section['content'].strip())
        output.append("\n---\n")
    return "\n".join(output)