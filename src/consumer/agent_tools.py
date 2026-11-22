"""Công cụ để trợ lý Gemini đọc dữ liệu của 11 công ty ngoài Vinamilk (số đã đối chiếu và toàn bộ chữ trong PDF).

Mỗi công cụ gọi đúng hàm đã dùng cho câu trả lời theo quy tắc (`service.lookup`, `ratio_answer`, `docqa.search`...), nên số và nguồn
giống hệt nhau; kết quả trả về dạng {"ok", "text", "sources", "notes"} như công cụ của Vinamilk. Nguồn đã ở dạng giao diện (có "ready")."""
from __future__ import annotations

import re

from src.consumer import docqa, insight, repository, service
from src.consumer.catalog import ALL_METRICS, COMPANIES, PERIODS, fold

PASSAGE_CHARS = 1400
_COMPANY = {"type": "string", "description": "Mã hoặc tên công ty: VNM, MCM, QNS, BBC, BHN, CMF, KDC, MCH, PAN, SAB, SBT, VCF (vd 'KDC', 'Masan', 'Sabeco')."}
_PERIOD = {"type": "string", "description": "Kỳ báo cáo: 'Q1/2025' ... 'Q3/2026' hoặc 'FY2025' (cả năm 2025). Mỗi công ty có các kỳ khác nhau; gọi list_companies để xem."}
_BASIS = {"type": "string", "enum": ["quy", "luy_ke"], "default": "quy", "description": "quy = riêng quý; luy_ke = từ đầu năm. Bỏ qua với chỉ tiêu số dư."}

SPECS = [
    {"name": "list_companies",
     "description": "Danh sách 12 công ty trong dữ liệu (Vinamilk và 11 công ty hàng tiêu dùng) cùng các kỳ báo cáo mỗi công ty có. Gọi khi cần biết công ty/kỳ nào có dữ liệu.",
     "input_schema": {"type": "object", "properties": {
         "company": {"type": "string", "description": "Chỉ xem một công ty (tùy chọn); bỏ trống để xem cả 12."}}}},
    {"name": "get_company_metric",
     "description": "Tra một chỉ tiêu đã đối chiếu của MỘT công ty ngoài Vinamilk (doanh thu thuần, giá vốn, lợi nhuận gộp/trước thuế/sau thuế, tổng tài sản, "
                    "tài sản ngắn/dài hạn, nợ phải trả, nợ ngắn/dài hạn, vốn chủ sở hữu, hàng tồn kho, dòng tiền). Trả số VND kèm trang PDF. "
                    "Với Vinamilk dùng get_metric. Chưa có số thì công cụ nói rõ; không tự đoán số.",
     "input_schema": {"type": "object", "required": ["company", "metric", "period"], "properties": {
         "company": _COMPANY, "metric": {"type": "string", "description": "Tên chỉ tiêu viết tự nhiên, vd 'doanh thu thuần', 'tổng tài sản'."},
         "period": _PERIOD, "basis": _BASIS}}},
    {"name": "get_company_ratio",
     "description": "Tỷ số của một công ty ngoài Vinamilk: biên lợi nhuận gộp, biên trước thuế, biên ròng, nợ trên vốn chủ, nợ trên tổng tài sản.",
     "input_schema": {"type": "object", "required": ["company", "ratio", "period"], "properties": {
         "company": _COMPANY, "ratio": {"type": "string", "description": "vd 'biên lợi nhuận ròng', 'nợ trên vốn chủ'."}, "period": _PERIOD, "basis": _BASIS}}},
    {"name": "get_company_growth",
     "description": "Tăng trưởng của một chỉ tiêu của một công ty ngoài Vinamilk: yoy = so với cùng kỳ năm trước, qoq = so với quý liền trước. Chỉ so hai kỳ cùng phạm vi báo cáo.",
     "input_schema": {"type": "object", "required": ["company", "metric", "period"], "properties": {
         "company": _COMPANY, "metric": {"type": "string"}, "period": _PERIOD,
         "kind": {"type": "string", "enum": ["yoy", "qoq"], "default": "yoy"}, "basis": _BASIS}}},
    {"name": "get_company_series",
     "description": "Chuỗi giá trị của một chỉ tiêu của một công ty ngoài Vinamilk qua các quý có báo cáo.",
     "input_schema": {"type": "object", "required": ["company", "metric"], "properties": {
         "company": _COMPANY, "metric": {"type": "string"}, "basis": _BASIS}}},
    {"name": "search_company_documents",
     "description": "Tìm đoạn chữ trong TOÀN BỘ PDF báo cáo của một công ty (kể cả Vinamilk): người (chủ tịch, Hội đồng quản trị, ban điều hành), "
                    "thông tin công ty (trụ sở, vốn điều lệ, kiểm toán, công ty con), hoạt động kinh doanh, thuyết minh. Trả các đoạn OCR có đánh số kèm "
                    "công ty/kỳ/trang. Chữ là OCR nên có thể sai dấu hoặc ký tự. Chỉ trả lời điều có trong các đoạn này; không có thì nói không tìm thấy.",
     "input_schema": {"type": "object", "required": ["company", "query"], "properties": {
         "company": _COMPANY, "query": {"type": "string", "description": "Các từ khóa chính của điều cần tìm, vd 'chủ tịch hội đồng quản trị', 'công ty kiểm toán', 'trụ sở chính'."},
         "period": {"type": "string", "description": "Giới hạn theo kỳ, vd 'Q2/2026' hoặc 'FY2025' (tùy chọn)."},
         "k": {"type": "integer", "minimum": 1, "maximum": 8, "default": 5}}}},
]
NAMES = {spec["name"] for spec in SPECS}


def resolve_company(text) -> str | None:
    text = str(text or "").strip()
    if text.upper() in COMPANIES or text.upper() == "VNM":
        return text.upper()
    query = fold(text)
    if service.matches(query, service.VNM_WORDS):
        return "VNM"
    found = service.question_companies(text)
    return found[0] if len(found) == 1 else None


def resolve_metric(text) -> str | None:
    text = str(text or "").strip()
    if text in ALL_METRICS:
        return text
    found = [m for m in service.question_metrics(fold(text)) if m in ALL_METRICS]
    return found[0] if found else None


def resolve_period(text) -> str | None:
    found = [p for p in service.requested_periods(str(text or "")) if p in PERIODS]
    return found[0] if found else None


def from_reply(reply: dict) -> dict:
    text = reply["answer"]
    if reply.get("notes"):
        text += "\n\nLưu ý: " + "; ".join(reply["notes"])
    return {"ok": True, "text": text, "sources": [{**s, "ready": True} for s in reply.get("sources", [])], "notes": reply.get("notes", [])}


def _list(args: dict) -> dict:
    available: dict[str, list[str]] = {}
    for code, period in repository.coverage():
        available.setdefault(code, []).append(period)
    only = resolve_company(args.get("company")) if args.get("company") else None
    lines = ["Vinamilk (VNM): Q1/2025 đến Q2/2026 (dùng get_metric, get_ratio, get_growth, get_series, search_documents)."] if only in (None, "VNM") else []
    for code, (name, _) in COMPANIES.items():
        if only and only != code:
            continue
        have = [p for p in PERIODS if p in available.get(code, [])]
        lines.append(f"{name} ({code}): {', '.join(have) or 'chưa có báo cáo'}")
    return {"ok": True, "text": "\n".join(lines), "sources": []}


def _search(args: dict) -> dict:
    code = resolve_company(args.get("company"))
    query = str(args.get("query", "")).strip()
    if not code:
        return {"ok": False, "error": f"Không nhận ra công ty '{args.get('company')}'. Gọi list_companies để xem mã."}
    if not query:
        return {"ok": False, "error": "Thiếu tham số 'query'."}
    k = max(1, min(int(args.get("k", 5) or 5), 8))
    period = args.get("period")
    hits = docqa.search(code, query, limit=60, min_coverage=0.5)               # mô hình tự đánh giá độ liên quan nên ngưỡng lỏng hơn câu trả lời quy tắc
    if period:
        want = resolve_period(period)
        hits = [h for h in hits if h.period == want]
    hits = hits[:k]
    if not hits:
        return {"ok": False, "error": f"Không tìm thấy đoạn chữ phù hợp trong PDF của {docqa.entity_name(code)}."}
    blocks = [f"[{i}] ({docqa.entity_name(h.company)} · {h.period} · trang {h.page})\n{re.sub(r'[ \t]+', ' ', h.text).strip()[:PASSAGE_CHARS]}" for i, h in enumerate(hits, 1)]
    return {"ok": True, "text": "\n\n".join(blocks), "sources": [{**docqa.source_of(h), "ready": True} for h in hits]}


def run(name: str, args: dict) -> dict:
    if name == "list_companies":
        return _list(args)
    if name == "search_company_documents":
        return _search(args)
    code = resolve_company(args.get("company"))
    if not code:
        return {"ok": False, "error": f"Không nhận ra công ty '{args.get('company')}'. Gọi list_companies để xem mã."}
    if code == "VNM":
        return {"ok": False, "error": "Vinamilk có công cụ riêng: dùng get_metric, get_ratio, get_growth, get_series."}
    basis = args.get("basis") if args.get("basis") in ("quy", "luy_ke") else "quy"
    if name == "get_company_series":
        metric = resolve_metric(args.get("metric"))
        if not metric:
            return {"ok": False, "error": f"Không nhận ra chỉ tiêu '{args.get('metric')}'."}
        return from_reply(service.answer_question(f"{ALL_METRICS[metric][0]} của {COMPANIES[code][0]} qua các quý", [code]))
    period = resolve_period(args.get("period"))
    if not period:
        return {"ok": False, "error": f"Kỳ '{args.get('period')}' không hợp lệ. Dùng dạng 'Q2/2026' hoặc 'FY2025'."}
    if name == "get_company_ratio":
        asked = insight.asked_ratios(fold(str(args.get("ratio", ""))))
        if not asked:
            return {"ok": False, "error": f"Không nhận ra tỷ số '{args.get('ratio')}'. Có: biên lợi nhuận gộp/trước thuế/ròng, nợ trên vốn chủ, nợ trên tổng tài sản."}
        return from_reply(service.ratio_answer([code], period, basis, asked))
    metric = resolve_metric(args.get("metric"))
    if not metric:
        return {"ok": False, "error": f"Không nhận ra chỉ tiêu '{args.get('metric')}'."}
    if name == "get_company_metric":
        return from_reply(service.lookup([code], metric, period, basis))
    if name == "get_company_growth":
        versus = "quý liền trước" if args.get("kind") == "qoq" else "cùng kỳ năm trước"
        suffix = " lũy kế" if basis == "luy_ke" else ""
        return from_reply(service.answer_question(f"Tăng trưởng {ALL_METRICS[metric][0]}{suffix} {PERIODS[period]} so với {versus} của {COMPANIES[code][0]}", [code]))
    return {"ok": False, "error": f"Không có công cụ '{name}'."}
