# utils/production/completions/help_guide.py
"""
Production Receipts — User Guide & Reference
Comprehensive help rendered as floating popover dialog

Version: 1.0.0
"""

import streamlit as st


def render_help_guide():
    """
    Render Production Receipts user guide as a wide st.dialog.
    Triggered from action bar button. Contains:
    - Workflow overview
    - Step-by-step instructions  
    - Validation rules & formulas
    - QC rules & inventory impact
    - Warnings & aging system
    - Terminology glossary
    - FAQ / Troubleshooting
    """
    _show_help_dialog()


@st.dialog("📚 Production Receipts — Hướng dẫn sử dụng", width="large")
def _show_help_dialog():
    """Full user guide dialog"""

    # ── Navigation tabs ──
    guide_tabs = st.tabs([
        "🔄 Quy trình",
        "📦 Nhập sản lượng",
        "🔬 Kiểm tra QC",
        "🔒 Đóng lệnh SX",
        "📐 Công thức",
        "⚠️ Cảnh báo",
        "📖 Thuật ngữ",
        "❓ FAQ",
    ])

    # ================================================================
    # TAB 1: Workflow Overview
    # ================================================================
    with guide_tabs[0]:
        st.markdown("## 🔄 Quy trình sản xuất — Tổng quan")

        st.markdown("""
Quy trình gồm **2 giai đoạn** rõ ràng. Lệnh sản xuất (MO) **không tự động đóng** —
người dùng chủ động đóng khi sẵn sàng.
""")

        st.markdown("""
```
                        Giai đoạn 1                    Giai đoạn 2
                    ┌─────────────────┐            ┌──────────────┐
  MO (IN_PROGRESS)  │  Nhập sản lượng │  (n lần)   │  Đóng lệnh   │  MO (COMPLETED)
  ─────────────────>│  + chia QC      │ ──────────>│  (1 lần)     │──────────────>
                    │  Record Output  │            │  Close Order │   🔒 Khóa
                    └─────────────────┘            └──────────────┘
                           │                              │
                    MO vẫn IN_PROGRESS              Điều kiện:
                    (không auto-complete)            ✅ Có receipt
                                                    ✅ 0 PENDING QC
                                                    ✅ NVL đã xuất
```
""")

        st.info(
            "💡 **Tại sao không auto-complete?**\n\n"
            "Trước đây, hệ thống tự đóng MO ngay khi sản lượng đạt kế hoạch. "
            "Điều này gây ra vấn đề: MO được đánh dấu COMPLETED trước khi QC kiểm tra xong, "
            "dẫn đến dữ liệu phân tích (BOM Variance, Yield Rate…) không chính xác.\n\n"
            "Bây giờ, người dùng kiểm soát hoàn toàn thời điểm đóng lệnh."
        )

        st.markdown("### Vòng đời MO (Manufacturing Order)")
        st.markdown("""
| Trạng thái | Ý nghĩa | Hành động được phép |
|:-----------|:--------|:-------------------|
| `DRAFT` | Nháp, chưa xác nhận | Sửa, xóa |
| `CONFIRMED` | Đã xác nhận, chờ sản xuất | Xuất NVL, bắt đầu SX |
| `IN_PROGRESS` | Đang sản xuất | Nhập sản lượng, xuất/trả NVL, cập nhật QC, đóng lệnh |
| `COMPLETED` | Đã đóng | **🔒 Chỉ xem** — không sửa được gì |
| `CANCELLED` | Đã hủy | Chỉ xem |
""")

        st.markdown("### Vòng đời QC (Quality Control)")
        st.markdown("""
| Trạng thái | Ý nghĩa | Chuyển thành | Kho |
|:-----------|:--------|:------------|:----|
| ⏳ `PENDING` | Chờ kiểm tra | → PASSED hoặc FAILED | ❌ Chưa vào kho |
| ✅ `PASSED` | Đạt chất lượng | 🔒 Không đổi được | ✅ Đã vào kho |
| ❌ `FAILED` | Không đạt | 🔒 Không đổi được | ❌ Không vào kho |
""")

        st.warning(
            "⚠️ **QC là một chiều (one-way).** Sau khi chuyển PENDING → PASSED hoặc FAILED, "
            "không thể đổi lại. Hãy kiểm tra kỹ trước khi xác nhận."
        )

    # ================================================================
    # TAB 2: Record Output (Phase 1)
    # ================================================================
    with guide_tabs[1]:
        st.markdown("## 📦 Giai đoạn 1 — Nhập sản lượng (Record Output)")

        st.markdown("""
Ghi nhận sản lượng thực tế từ dây chuyền sản xuất, đồng thời **chia QC ngay** 
tại thời điểm nhập.
""")

        st.markdown("### Hướng dẫn từng bước")

        st.markdown("""
**Bước 1:** Nhấn nút **📦 Record Output**

**Bước 2:** Chọn lệnh sản xuất (MO) từ dropdown
- Chỉ hiển thị MO có trạng thái `IN_PROGRESS`
- Thông tin MO sẽ hiện: kế hoạch, đã SX, còn lại

**Bước 3:** Nhập số lượng QC

| Ô nhập | Ý nghĩa | Ảnh hưởng kho |
|:-------|:--------|:-------------|
| ✅ **Passed** | Đạt chất lượng | ➕ Vào kho ngay |
| ⏳ **Pending** | Chờ kiểm tra | ❌ Chưa vào kho (cập nhật sau) |
| ❌ **Failed** | Không đạt | ❌ Không vào kho |

**Bước 4:** Điền thông tin bổ sung
- **Batch No**: Mã lô (tự tạo, có thể sửa)
- **Expiry Date**: Hạn sử dụng thành phẩm
- **Defect Type**: Loại lỗi (chỉ hiện khi Failed > 0)
- **Notes**: Ghi chú

**Bước 5:** Xem Preview → nhấn **📦 Record Output**
""")

        st.markdown("### Điều kiện nhập (Validation)")
        st.markdown("""
| Điều kiện | Yêu cầu | Giải thích |
|:----------|:--------|:-----------|
| MO Status | `IN_PROGRESS` | Chỉ MO đang sản xuất |
| Tổng QC | Passed + Pending + Failed > 0 | Phải có sản lượng |
| Batch No | Không trống | Mã lô để truy xuất nguồn gốc |
| NVL chính | `issued_qty > 0` | Nguyên vật liệu chính (RAW_MATERIAL) phải được xuất kho |
| Vượt kế hoạch | **Không giới hạn** | Ghi đúng thực tế — nếu SX 150% thì nhập 150% |
""")

        st.markdown("### Cảnh báo (không chặn)")
        st.markdown("""
| Cảnh báo | Khi nào | Có chặn? |
|:---------|:--------|:---------|
| 📈 Overproduction | Sản lượng > kế hoạch | ⚠️ Cảnh báo, cho phép tiếp |
| 🔁 Duplicate Batch | Mã lô trùng MO khác | ⚠️ Cảnh báo, cho phép tiếp |
| 📅 Expired | Hạn sử dụng đã qua | ⚠️ Cảnh báo, cho phép tiếp |
""")

        st.markdown("### Kết quả sau khi nhập")
        st.markdown("""
- Tạo **1-3 phiếu nhập kho** (Production Receipt) tùy chia QC:
  - Chỉ Passed → 1 phiếu PASSED
  - Passed + Failed → 2 phiếu (PASSED + FAILED)
  - Passed + Pending + Failed → 3 phiếu
- Phiếu PASSED → hàng **vào kho ngay** (`stockInProduction`)
- Phiếu PENDING/FAILED → **không** tạo inventory
- MO: `produced_qty` += tổng, trạng thái **vẫn IN_PROGRESS**
""")

        st.info(
            "💡 **Có thể nhập nhiều lần.** Mỗi lần Record Output tạo thêm receipt(s) mới. "
            "Ví dụ: lô 1 sáng 100 PCS, lô 2 chiều 80 PCS — nhập 2 lần."
        )

    # ================================================================
    # TAB 3: QC Resolution
    # ================================================================
    with guide_tabs[2]:
        st.markdown("## 🔬 Cập nhật QC cho phiếu PENDING")

        st.markdown("""
Khi nhập sản lượng, nếu có phần **⏳ Pending** (chờ kiểm tra), 
bộ phận QC sẽ cập nhật kết quả sau.
""")

        st.markdown("### Quy tắc chuyển trạng thái")
        st.markdown("""
| Từ | Sang | Cho phép? | Kho | Ghi chú |
|:---|:-----|:---------|:----|:--------|
| ⏳ PENDING | ✅ PASSED | ✅ Có | ➕ Tạo `stockInProduction` | Hàng vào kho |
| ⏳ PENDING | ❌ FAILED | ✅ Có | Không thay đổi | Hàng lỗi |
| ⏳ PENDING | ⏳ PENDING | ❌ Không | — | Không cho giữ nguyên |
| ✅ PASSED | Bất kỳ | 🔒 **Khóa** | — | Đã xác nhận rồi |
| ❌ FAILED | Bất kỳ | 🔒 **Khóa** | — | Đã xác nhận rồi |
""")

        st.markdown("### Hướng dẫn cập nhật")
        st.markdown("""
1. Chọn phiếu PENDING trong bảng (tick checkbox)
2. Nhấn nút **✏️ Update Quality**
3. Chia số lượng vào **Passed** và/hoặc **Failed**
   - Tổng phải = số lượng phiếu gốc
   - Nếu chia 2 phần → hệ thống tạo phiếu mới (split)
4. Nếu có Failed → chọn **Defect Type** (bắt buộc)
5. Nhấn **✅ Update QC Result**
""")

        st.markdown("### Chia tách phiếu (Split)")
        st.markdown("""
Khi phiếu PENDING được chia thành cả PASSED và FAILED:

| Phiếu | Trạng thái | Số lượng |
|:-------|:----------|:---------|
| Phiếu gốc | → PASSED | Phần đạt |
| Phiếu mới | → FAILED | Phần lỗi |

Phiếu gốc luôn giữ trạng thái ưu tiên cao nhất (PASSED > FAILED).
""")

        st.markdown("### Cảnh báo Aging (quá hạn kiểm tra)")
        st.markdown("""
Phiếu PENDING lâu ngày sẽ hiện cảnh báo trong bảng:

| Thời gian | Icon | Mức độ | Ý nghĩa |
|:----------|:-----|:-------|:--------|
| ≤ 3 ngày | ⏳ | Bình thường | QC đang xử lý |
| 4–7 ngày | 🟡 | Cảnh báo | Nên kiểm tra sớm |
| 8–14 ngày | 🟠 | Khẩn | QC quá hạn |
| > 14 ngày | 🔴 | Nghiêm trọng | Ảnh hưởng đóng lệnh |
""")

        st.warning(
            "⚠️ **Phiếu PENDING chặn đóng lệnh.** "
            "MO không thể Close Order nếu còn phiếu PENDING. "
            "Hãy cập nhật QC trước khi đóng."
        )

        st.markdown("### Khi nào nút Update Quality bị khóa?")
        st.markdown("""
| Tình huống | Nút hiển thị | Lý do |
|:-----------|:------------|:------|
| Phiếu PENDING, MO IN_PROGRESS | ✏️ Update Quality | Bình thường |
| Phiếu PASSED hoặc FAILED | 🔒 QC Locked | QC đã xác nhận — không đổi được |
| MO đã COMPLETED | 🔒 QC Locked | Lệnh đã đóng — toàn bộ bị khóa |
""")

    # ================================================================
    # TAB 4: Close Order (Phase 2)
    # ================================================================
    with guide_tabs[3]:
        st.markdown("## 🔒 Giai đoạn 2 — Đóng lệnh sản xuất (Close Order)")

        st.markdown("""
Đóng lệnh là bước **cuối cùng** — xác nhận sản xuất hoàn tất. 
Sau khi đóng, **không thể** nhập thêm, sửa QC, hay xuất/trả NVL.
""")

        st.markdown("### Điều kiện đóng lệnh")
        st.markdown("""
| # | Điều kiện | Yêu cầu | Giải thích |
|:--|:----------|:--------|:-----------|
| 1 | MO Status | `IN_PROGRESS` | Chỉ MO đang chạy |
| 2 | Có phiếu nhập | ≥ 1 receipt | Phải có sản lượng ghi nhận |
| 3 | PENDING QC | = 0 | **Tất cả** phiếu phải PASSED hoặc FAILED |
| 4 | NVL chính | issued | RAW_MATERIAL phải đã xuất kho |
""")

        st.markdown("### Hướng dẫn đóng lệnh")
        st.markdown("""
**Cách 1: Từ Action Bar**
1. Nhấn **🔒 Close Order** trong thanh công cụ
2. Hệ thống hiện danh sách MO sẵn sàng đóng
3. Nhấn **🔒 Close** bên cạnh MO cần đóng
4. Xem checklist validation → nhấn **🔒 Confirm Close**

**Cách 2: Từ gợi ý (Banner)**
- Khi MO đạt đủ sản lượng và QC xong, banner xanh hiện:
  *"✅ N order(s) ready to close"*
- Nhấn vào để xem và đóng
""")

        st.markdown("### Sau khi đóng lệnh")
        st.markdown("""
| Hành động | Cho phép? |
|:----------|:---------|
| Nhập thêm sản lượng | ❌ Bị chặn |
| Cập nhật QC | ❌ Bị chặn |
| Xuất NVL (Material Issue) | ❌ Bị chặn |
| Trả NVL (Material Return) | ❌ Bị chặn |
| Xem phiếu nhập | ✅ Cho phép (chỉ xem) |
| Xuất PDF | ✅ Cho phép |
| Xuất Excel | ✅ Cho phép |
""")

        st.error(
            "🚫 **Không thể mở lại (reopen) lệnh đã đóng.** "
            "Hãy chắc chắn mọi thứ đã hoàn tất trước khi Close."
        )

        st.markdown("### Ảnh hưởng đến báo cáo")
        st.markdown("""
- **BOM Variance**: Chỉ tính MO có `status = COMPLETED` → dữ liệu chính xác hơn
- **Overview**: MO chuyển từ "In Progress" sang "Completed"
- **Yield Rate**: Giữ nguyên (đã tính từ produced_qty / planned_qty)
""")

    # ================================================================
    # TAB 5: Formulas
    # ================================================================
    with guide_tabs[4]:
        st.markdown("## 📐 Công thức tính toán")

        st.markdown("### Sản lượng")
        st.markdown("""
| Chỉ số | Công thức | Ví dụ |
|:-------|:----------|:------|
| **Tổng SX** (Total Produced) | `Passed + Pending + Failed` | 80 + 15 + 5 = **100** |
| **Còn lại** (Remaining) | `Planned − Produced` | 200 − 150 = **50** |
| **Tiến độ** (Progress) | `Produced ÷ Planned × 100%` | 150 ÷ 200 = **75%** |
| **Yield Rate** | `Produced ÷ Planned × 100%` | 210 ÷ 200 = **105%** |
""")

        st.markdown("### Chất lượng")
        st.markdown("""
| Chỉ số | Công thức | Ví dụ |
|:-------|:----------|:------|
| **Pass Rate** | `PASSED count ÷ Total count × 100%` | 18 ÷ 20 = **90%** |
| **Yield Indicator** | ≥ 95% → ✅, ≥ 85% → ⚠️, < 85% → ❌ | 91.4% → ⚠️ |
""")

        st.markdown("### NVL (Material)")
        st.markdown("""
| Chỉ số | Công thức |
|:-------|:----------|
| **Required Qty** | `(MO.planned_qty ÷ BOM.output_qty) × BOM_Detail.quantity × (1 + scrap_rate%)` |
| **Issued Qty** | Tổng tương đương (equivalent) đã xuất, trừ đã trả. Đơn vị theo NVL chính |
| **Issue Status** | PENDING (0%), PARTIAL (>0%), ISSUED (≥100%) |
""")

        st.markdown("### Inventory")
        st.markdown("""
| Sự kiện | Loại inventory | Trường liên kết |
|:--------|:--------------|:---------------|
| Receipt PASSED | `stockInProduction` | `action_detail_id = receipt.id` |
| Material Issue | `stockOutProduction` | `action_detail_id = issue_detail.id` |
| Material Return (GOOD) | `stockInReturn` | Tạo mới hoặc cộng lại remain |
""")

        st.info(
            "💡 **remain** trong `inventory_histories` = số lượng còn lại trong kho. "
            "Khi hàng được bán/xuất, remain giảm dần. Khi = 0 → hết hàng batch đó."
        )

    # ================================================================
    # TAB 6: Warnings & Icons
    # ================================================================
    with guide_tabs[5]:
        st.markdown("## ⚠️ Hệ thống cảnh báo")

        st.markdown("### Cảnh báo trong bảng phiếu nhập")
        st.markdown("""
Cột **⚠️** hiển thị các icon cảnh báo cho từng phiếu:

| Icon | Tên | Mô tả | Mức độ |
|:-----|:----|:------|:-------|
| 🔁 | Duplicate Batch | Mã lô (batch_no) xuất hiện ở **nhiều MO khác nhau** | Cảnh báo |
| 📅 | Expired | Hạn sử dụng (expired_date) **đã qua** | Cảnh báo |
| 📈 | Overproduction | Yield Rate > 100% — SX vượt kế hoạch | Thông tin |
| ⏳ | Pending QC | Phiếu chưa được kiểm tra chất lượng | Cần hành động |
| 🟡 | Aging Warning | PENDING > 3 ngày | Cần hành động |
| 🟠 | Aging Urgent | PENDING > 7 ngày | Khẩn |
| 🔴 | Aging Critical | PENDING > 14 ngày | Nghiêm trọng |
| 🔒 | Completed | MO đã đóng — phiếu bị khóa | Thông tin |
""")

        st.markdown("### Banner Ready-to-Close")
        st.markdown("""
Hiển thị phía trên bảng khi có MO đủ điều kiện đóng:

| Banner | Ý nghĩa |
|:-------|:--------|
| ✅ **N order(s) ready to close** | Đạt kế hoạch + QC xong → có thể đóng |
| ⏳ **N order(s) met target but have pending QC** | Đạt kế hoạch nhưng còn PENDING → giải quyết QC trước |
""")

        st.markdown("### Cảnh báo khi nhập sản lượng")
        st.markdown("""
Hiển thị trong form Record Output:

| Cảnh báo | Điều kiện | Chặn? |
|:---------|:----------|:------|
| ⚠️ Overproduction | `total > remaining` | Không — ghi đúng thực tế |
| ⚠️ Duplicate Batch | `batch_no` trùng MO khác | Không — có thể cùng batch |
| ⚠️ Expired | `expiry_date < today` | Không — có thể là hàng cũ |
| ⚠️ Defect Type required | `failed_qty > 0` mà chưa chọn loại lỗi | **Có** — bắt buộc chọn |
""")

    # ================================================================
    # TAB 7: Glossary
    # ================================================================
    with guide_tabs[6]:
        st.markdown("## 📖 Thuật ngữ — Glossary")

        st.markdown("""
| Thuật ngữ | Viết tắt | Tiếng Việt | Mô tả |
|:----------|:---------|:-----------|:------|
| Manufacturing Order | MO | Lệnh sản xuất | Tài liệu điều phối SX từ BOM |
| Production Receipt | PR | Phiếu nhập kho TP | Ghi nhận sản lượng + kết quả QC |
| Bill of Materials | BOM | Định mức NVL | Công thức SX: input → output |
| Quality Control | QC | Kiểm tra chất lượng | Kiểm tra sản phẩm đạt/không đạt |
| Material Issue | MI | Phiếu xuất NVL | Xuất nguyên vật liệu cho SX |
| Material Return | MR | Phiếu trả NVL | Trả NVL thừa về kho |
| Yield Rate | — | Tỷ lệ hoàn thành | Produced ÷ Planned × 100% |
| Pass Rate | — | Tỷ lệ đạt QC | PASSED ÷ Total × 100% |
| Batch No | — | Mã lô | Mã truy xuất nguồn gốc sản phẩm |
| UOM | — | Đơn vị tính | PCS, ROLL, BOX, SET, KG… |
| FEFO | — | First Expiry First Out | Xuất hàng hết hạn trước |
| Remaining | — | Còn lại | Planned − Produced |
| `stockInProduction` | — | Nhập kho từ SX | Loại inventory khi PASSED |
| `stockOutProduction` | — | Xuất kho cho SX | Loại inventory khi Issue NVL |
""")

        st.markdown("### Mã chứng từ — Document Numbering")
        st.markdown("""
| Loại | Format | Ví dụ |
|:-----|:-------|:------|
| Lệnh SX | `MO-YYYYMMDD-XXX` | MO-20260321-001 |
| Phiếu nhập TP | `PR-YYYYMMDD-XXX` | PR-20260321-001 |
| Phiếu xuất NVL | `MI-YYYYMMDD-XXX` | MI-20260321-001 |
| Phiếu trả NVL | `MR-YYYYMMDD-XXX` | MR-20260321-001 |
| Mã lô | `BATCH-YYYYMMDD-HHMM` | BATCH-20260321-1430 |
""")

        st.markdown("### Loại lỗi — Defect Types")
        st.markdown("""
| Mã | Tên | Tiếng Việt |
|:---|:----|:-----------|
| `VISUAL` | Visual Defect | Lỗi ngoại quan |
| `DIMENSIONAL` | Dimensional | Sai kích thước |
| `FUNCTIONAL` | Functional | Lỗi chức năng |
| `CONTAMINATION` | Contamination | Nhiễm bẩn |
| `PACKAGING` | Packaging | Lỗi đóng gói |
| `OTHER` | Other | Khác |
""")

    # ================================================================
    # TAB 8: FAQ
    # ================================================================
    with guide_tabs[7]:
        st.markdown("## ❓ Câu hỏi thường gặp — FAQ")

        # Q1
        with st.expander("**Q1: Tôi nhập sai số lượng, sửa lại được không?**", expanded=False):
            st.markdown("""
**Không thể sửa** phiếu đã tạo. Thay vào đó:

- Nếu nhập **thừa**: Liên hệ IT để hỗ trợ điều chỉnh dữ liệu
- Nếu nhập **thiếu**: Nhập thêm 1 lần Record Output với số lượng còn thiếu
- Nếu nhập **sai MO**: Liên hệ IT

**Lý do**: Phiếu nhập kho đã tạo inventory record. Sửa số liệu trực tiếp 
sẽ phá vỡ tính toàn vẹn dữ liệu.
""")

        # Q2
        with st.expander("**Q2: Tại sao nút Update Quality bị khóa (🔒)?**", expanded=False):
            st.markdown("""
Nút bị khóa trong 2 trường hợp:

1. **Phiếu đã PASSED hoặc FAILED**: QC đã xác nhận, không đổi được
2. **MO đã COMPLETED**: Toàn bộ bị khóa sau khi đóng lệnh

**Giải pháp**: Nếu cần sửa, liên hệ IT.
""")

        # Q3
        with st.expander("**Q3: Sản xuất vượt kế hoạch (> 100%), có được không?**", expanded=False):
            st.markdown("""
**Được.** Hệ thống không giới hạn. Ghi đúng thực tế sản xuất.

Ví dụ: Kế hoạch 200 PCS, thực tế SX 230 PCS → nhập 230. 
Yield Rate = 115%, hiện icon 📈 (thông tin, không chặn).
""")

        # Q4
        with st.expander("**Q4: Không thể đóng lệnh — \"N receipts still PENDING\"?**", expanded=False):
            st.markdown("""
MO không thể Close khi còn phiếu **⏳ PENDING QC**.

**Giải pháp**:
1. Trong bảng phiếu, lọc Quality = PENDING
2. Chọn từng phiếu → nhấn ✏️ Update Quality
3. Chia Passed / Failed → xác nhận
4. Lặp lại cho đến khi hết PENDING
5. Quay lại Close Order
""")

        # Q5
        with st.expander("**Q5: Phiếu cũ không hiện trong bảng?**", expanded=False):
            st.markdown("""
Mặc định, phiếu từ MO đã COMPLETED **bị ẩn**.

**Giải pháp**: Mở **🔍 Filters** → tick ☑️ **"Show completed orders"** 
→ phiếu từ MO COMPLETED sẽ hiện lại (chỉ xem, không sửa được).
""")

        # Q6
        with st.expander("**Q6: Batch number trùng, có sao không?**", expanded=False):
            st.markdown("""
Hệ thống **cảnh báo** (🔁) nhưng **không chặn**. 

Trùng batch giữa các MO khác nhau có thể hợp lệ (ví dụ: cùng lô NVL).
Tuy nhiên, nếu trùng do nhập nhầm → sửa batch trước khi submit.
""")

        # Q7
        with st.expander("**Q7: Hàng vào kho khi nào?**", expanded=False):
            st.markdown("""
Hàng chỉ vào kho (`stockInProduction`) khi QC = **PASSED**:

| Tình huống | Vào kho? | Thời điểm |
|:-----------|:---------|:----------|
| Record Output → Passed=100 | ✅ Ngay | Lúc nhập sản lượng |
| Record Output → Pending=100 | ❌ Chưa | — |
| Update QC: Pending → Passed | ✅ Lúc update | Khi QC xác nhận |
| Update QC: Pending → Failed | ❌ Không | — |
""")

        # Q8
        with st.expander("**Q8: Close Order rồi muốn mở lại được không?**", expanded=False):
            st.markdown("""
**Không.** Hiện tại chưa có tính năng Reopen Order.

Nếu cần mở lại, liên hệ IT để hỗ trợ trực tiếp trên database.
""")

        st.markdown("---")
        st.caption(
            "📧 Liên hệ IT support nếu cần hỗ trợ thêm. "
            "Sử dụng nút 👎 dưới mỗi câu trả lời để báo lỗi hệ thống."
        )
