// Hằng số dùng chung của giao diện.
export const PERIODS = ["Q2/2026", "Q1/2026", "Q4/2025", "Q3/2025", "Q2/2025", "Q1/2025"];   // mới nhất trước; khớp 6 kỳ có trong dữ liệu
export const ALL = "all";
export const KEY = { convs: "vnm.convs.v1", active: "vnm.active.v1", period: "vnm.period.v1", rail: "vnm.rail.v1" };
export const STATEMENTS = { KQKD: "Báo cáo kết quả hoạt động kinh doanh", CDKT: "Báo cáo tình hình tài chính", LCTT: "Báo cáo lưu chuyển tiền tệ" };
export const SUGGESTIONS = [
  ["Doanh thu", "Doanh thu thuần quý 2/2026 của Vinamilk là bao nhiêu?"],
  ["Lợi nhuận", "Lợi nhuận sau thuế quý 2/2026 là bao nhiêu và tăng giảm thế nào so với quý trước?"],
  ["So sánh cùng kỳ · Q2/2026 so với Q2/2025", "So sánh doanh thu thuần quý 2/2026 với cùng kỳ năm trước."],
  ["Tỷ số tài chính", "Biên lợi nhuận gộp quý 2/2026 là bao nhiêu?"],
  ["Xu hướng nhiều kỳ", "Lợi nhuận sau thuế biến động thế nào qua 6 kỳ từ Q1/2025 đến Q2/2026?"],
  ["Thuyết minh", "Các khoản vay và nợ thuê tài chính của Vinamilk gồm những gì?"],
];
export const CHART_METRICS = ["Doanh thu thuần", "Giá vốn hàng bán", "Lợi nhuận gộp", "Chi phí bán hàng", "Chi phí quản lý doanh nghiệp",
  "Lợi nhuận sau thuế", "Tổng tài sản", "Nợ phải trả", "Vốn chủ sở hữu", "Hàng tồn kho", "Lưu chuyển tiền từ hoạt động kinh doanh"];
export const EXPLAIN_METRICS = ["Lợi nhuận sau thuế", "Doanh thu thuần"];                 // chỉ hai chỉ tiêu này phân rã được (xem src/tools/explain.py)
