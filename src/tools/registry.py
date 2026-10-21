"""Đăng ký công cụ cho agent: mô tả JSON Schema (định dạng tool-use của Claude API) + hàm gọi theo tên.

    from src.tools.registry import TOOL_SPECS, call_tool
    call_tool("get_metric", {"metric": "doanh thu thuần", "period": "Q1/2026"})
"""
from __future__ import annotations

from .analyst import Analyst
from .calc import calculate

_PERIOD = {"type": "string", "description": "Kỳ báo cáo, dạng 'Q1/2026'. Có Q1/2025 đến Q2/2026."}
_BASIS = {"type": "string", "enum": ["quy", "luy_ke"], "default": "quy",
          "description": "quy = riêng quý đó; luy_ke = từ đầu năm đến cuối quý (6 tháng, 9 tháng, cả năm). "
                         "Bỏ qua với chỉ tiêu số dư (bảng cân đối kế toán)."}

TOOL_SPECS = [
    {"name": "get_metric",
     "description": "Tra một số liệu tài chính hợp nhất của Vinamilk (doanh thu, lợi nhuận, tài sản, nợ, dòng tiền...) "
                    "trong một kỳ. Trả số VND kèm nguồn (trang PDF, mã số). Luôn dùng công cụ này thay vì tự nhớ số. "
                    "Tên chỉ tiêu viết tự nhiên bằng tiếng Việt được; nếu không chắc, gọi search_metrics trước.",
     "input_schema": {"type": "object", "required": ["metric", "period"], "properties": {
         "metric": {"type": "string", "description": "Tên hoặc mã chỉ tiêu, vd 'doanh thu thuần', 'tong_tai_san'."},
         "period": _PERIOD, "basis": _BASIS}}},
    {"name": "get_ratio",
     "description": "Tính tỷ số tài chính: biên lợi nhuận (gộp, hoạt động, trước thuế, ròng), tỷ lệ chi phí, ROE, ROA, "
                    "thanh toán hiện hành/nhanh, nợ trên vốn chủ, nợ trên tài sản, khả năng trả lãi, vòng quay và số ngày tồn kho. "
                    "ROE/ROA/vòng quay trả cả số theo kỳ và số quy năm.",
     "input_schema": {"type": "object", "required": ["ratio", "period"], "properties": {
         "ratio": {"type": "string", "description": "Tên hoặc mã tỷ số, vd 'ROE', 'biên lợi nhuận gộp'."},
         "period": _PERIOD, "basis": _BASIS}}},
    {"name": "get_growth",
     "description": "Tăng trưởng của một chỉ tiêu: yoy = so với cùng kỳ năm trước, qoq = so với quý liền trước, "
                    "ytd = số dư cuối kỳ so với đầu năm. Trả số tuyệt đối và tỷ lệ %.",
     "input_schema": {"type": "object", "required": ["metric", "period"], "properties": {
         "metric": {"type": "string"}, "period": _PERIOD,
         "kind": {"type": "string", "enum": ["yoy", "qoq", "ytd"], "default": "yoy"}, "basis": _BASIS}}},
    {"name": "get_series",
     "description": "Chuỗi giá trị của một chỉ tiêu qua mọi kỳ có dữ liệu (Q1/2025 đến Q2/2026), để so sánh xu hướng.",
     "input_schema": {"type": "object", "required": ["metric"], "properties": {
         "metric": {"type": "string"}, "basis": _BASIS}}},
    {"name": "search_metrics",
     "description": "Tìm tên chỉ tiêu chuẩn từ cách gọi thông thường (vd 'lãi ròng' -> loi_nhuan_sau_thue).",
     "input_schema": {"type": "object", "required": ["text"], "properties": {"text": {"type": "string"}}}},
    {"name": "calculate",
     "description": "Máy tính số học cho phép tính khác (chênh lệch, tỷ trọng, trung bình...). Chỉ nhận số viết kiểu "
                    "16148.7 (dấu chấm thập phân, không có dấu phân cách nghìn). Không dùng để tra số liệu.",
     "input_schema": {"type": "object", "required": ["expression"], "properties": {
         "expression": {"type": "string", "description": "vd '(16148.7 - 12957.5) / 12957.5 * 100'"}}}},
]

_analyst: Analyst | None = None


def analyst() -> Analyst:
    global _analyst
    if _analyst is None:
        _analyst = Analyst()
    return _analyst


def call_tool(name: str, args: dict) -> dict:
    a = analyst()
    try:
        if name == "get_metric":
            return a.metric(args["metric"], args["period"], args.get("basis", "quy"))
        if name == "get_ratio":
            return a.ratio(args["ratio"], args["period"], args.get("basis", "quy"))
        if name == "get_growth":
            return a.growth(args["metric"], args["period"], args.get("kind", "yoy"), args.get("basis", "quy"))
        if name == "get_series":
            return a.series(args["metric"], args.get("basis", "quy"))
        if name == "search_metrics":
            return a.search_metrics(args["text"])
        if name == "calculate":
            v = calculate(args["expression"])
            from .analyst import fmt_num
            return {"ok": True, "value": v, "text": f"{args['expression']} = {fmt_num(v, 4)}"}
    except KeyError as e:
        return {"ok": False, "error": f"Thiếu tham số {e}."}
    except (ValueError, SyntaxError, ZeroDivisionError, TypeError) as e:
        return {"ok": False, "error": f"Lỗi tính toán: {e}"}
    return {"ok": False, "error": f"Không có công cụ '{name}'. Có: {', '.join(t['name'] for t in TOOL_SPECS)}."}

