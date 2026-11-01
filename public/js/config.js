// Hằng số dùng chung của giao diện.
export const PERIODS = ["Q2/2026", "Q1/2026", "Q4/2025", "Q3/2025", "Q2/2025", "Q1/2025"];   // mới nhất trước; khớp 6 kỳ có trong dữ liệu
export const ALL = "all";
export const KEY = { convs: "vnm.convs.v1", active: "vnm.active.v1", period: "vnm.period.v1" };
export const STATEMENTS = { KQKD: "Báo cáo kết quả hoạt động kinh doanh", CDKT: "Báo cáo tình hình tài chính", LCTT: "Báo cáo lưu chuyển tiền tệ" };
export const SUGGESTIONS = [
  ["Doanh thu", "Doanh thu thuần quý 2/2026 của Vinamilk là bao nhiêu?"],
  ["Lợi nhuận", "Lợi nhuận sau thuế quý 2/2026 là bao nhiêu và tăng giảm thế nào so với quý trước?"],
  ["So sánh cùng kỳ · Q2/2026 so với Q2/2025", "So sánh doanh thu thuần quý 2/2026 với cùng kỳ năm trước."],
  ["Tỷ số tài chính", "Biên lợi nhuận gộp quý 2/2026 là bao nhiêu?"],
  ["Xu hướng nhiều kỳ", "Lợi nhuận sau thuế biến động thế nào qua 6 kỳ từ Q1/2025 đến Q2/2026?"],
  ["Thuyết minh", "Các khoản vay và nợ thuê tài chính của Vinamilk gồm những gì?"],
];
export const CHART_METRICS = ["doanh thu thuần", "giá vốn hàng bán", "lợi nhuận gộp", "chi phí bán hàng", "chi phí quản lý doanh nghiệp",
  "lợi nhuận sau thuế", "tổng tài sản", "nợ phải trả", "vốn chủ sở hữu", "hàng tồn kho", "lưu chuyển tiền từ hoạt động kinh doanh"];
export const EXPLAIN_METRICS = ["lợi nhuận sau thuế", "doanh thu thuần"];                 // chỉ hai chỉ tiêu này phân rã được (xem src/tools/explain.py)
export const NOTE_EXAMPLES = ["các khoản vay ngắn hạn", "dự phòng phải thu khó đòi", "thuế thu nhập hoãn lại", "chi phí bán hàng", "hàng tồn kho"];
