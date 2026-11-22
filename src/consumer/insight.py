"""Phân tích có cấu trúc cho câu hỏi về các công ty: tỷ số, xếp hạng, tăng trưởng, cầu nối lợi nhuận, đánh giá.

Mọi số đều tính từ các chỉ tiêu đã đối chiếu (không qua mô hình). Các hàm nhận số liệu của từng bên dưới dạng
`entities = [(tên, {chỉ tiêu: giá trị đồng}, phạm vi báo cáo)]` do `service.py` nạp, để module này không phụ thuộc cách nạp.
"""
from __future__ import annotations

from statistics import median

from src.consumer import repository
from src.consumer.catalog import COMPANIES, METRICS, PERIODS, fold
from src.rag.text import fmt_ty

# Tỷ số tính từ các chỉ tiêu chung của 12 công ty. "better": chiều tốt hơn (cao hơn tốt hơn, hay thấp hơn tốt hơn).
RATIOS = {
    "bien_gop": {"name": "Biên lợi nhuận gộp", "num": "loi_nhuan_gop", "den": "doanh_thu_thuan", "better": "high",
                 "words": ("bien loi nhuan gop", "bien gop", "bien lai gop", "ty suat loi nhuan gop")},
    "bien_truoc_thue": {"name": "Biên lợi nhuận trước thuế", "num": "loi_nhuan_truoc_thue", "den": "doanh_thu_thuan", "better": "high",
                        "words": ("bien loi nhuan truoc thue", "bien truoc thue", "bien lntt")},
    "bien_rong": {"name": "Biên lợi nhuận ròng", "num": "loi_nhuan_sau_thue", "den": "doanh_thu_thuan", "better": "high",
                  "words": ("bien loi nhuan rong", "bien rong", "bien lai rong", "bien loi nhuan sau thue", "bien lnst",
                            "ty suat loi nhuan rong")},
    "no_von": {"name": "Nợ phải trả / vốn chủ sở hữu", "num": "no_phai_tra", "den": "von_chu_so_huu", "better": "low",
               "words": ("no tren von chu so huu", "no tren von chu", "no tren von", "he so no tren von", "ty le no tren von",
                         "no/von", "don bay", "ty le no", "he so no", "d/e")},
    "no_ts": {"name": "Nợ phải trả / tổng tài sản", "num": "no_phai_tra", "den": "tong_tai_san", "better": "low",
              "words": ("no tren tong tai san", "ty le no tren tai san", "no phai tra tren tong tai san", "no/tong tai san")},
}
GENERIC_MARGIN = ("bien loi nhuan", "bien lai", "ty suat loi nhuan", "bien ln")      # không nói gộp hay ròng: hiện cả hai


def _has(query: str, words) -> bool:
    import re
    return any(re.search(rf"(?<!\w){re.escape(w)}(?!\w)", query) for w in words)


def asked_ratios(query: str) -> list:
    """Các tỷ số được hỏi trong câu (đã bỏ dấu, chữ thường); rỗng nếu câu không hỏi tỷ số."""
    found = [key for key, spec in RATIOS.items() if _has(query, spec["words"])]
    if "no_ts" in found and "no_von" in found and not _has(query, ("no tren von", "ty le no tren von", "he so no tren von", "don bay", "d/e")):
        found.remove("no_von")                                 # "tỷ lệ nợ trên tổng tài sản" chứa "tỷ lệ nợ" nhưng không phải nợ trên vốn chủ
    if not found and _has(query, GENERIC_MARGIN):
        found = ["bien_gop", "bien_rong"]
    return found


def ratio_of(values: dict, key: str):
    spec = RATIOS[key]
    num, den = values.get(spec["num"]), values.get(spec["den"])
    return None if num is None or not den or den <= 0 else num / den


def pct(x: float) -> str:
    return f"{x * 100:.1f}%".replace(".", ",")


def points(x: float) -> str:
    """Chênh lệch hai tỷ lệ, tính bằng điểm phần trăm, có dấu."""
    return f"{x * 100:+.1f}".replace(".", ",") + " điểm %"


def missing_line(codes: list, period: str, name) -> str:
    """Các bên không có trong bảng và lý do: chưa có báo cáo kỳ đó, hay có báo cáo nhưng chưa đối chiếu được số cần dùng."""
    no_report, no_number = [], []
    for code in codes:
        if code == "VNM":
            no_number.append(name(code))
        elif repository.documents(code, period):
            no_number.append(name(code))
        else:
            no_report.append(name(code))
    parts = []
    if no_report:
        parts.append(f"{', '.join(no_report)} (chưa có báo cáo kỳ này)")
    if no_number:
        parts.append(f"{', '.join(no_number)} (có báo cáo nhưng chưa đối chiếu được số cần dùng)")
    return f"**Chưa có trong bảng:** {'; '.join(parts)}." if parts else ""


def ratio_ranking(period: str, entities: list, keys: list, query: str) -> str:
    """Xếp các bên theo tỷ số được hỏi (không phải theo giá trị tuyệt đối), kèm tử số, mẫu số và nhận xét."""
    main = keys[0]
    spec = RATIOS[main]
    rows = [(name, values, scope, ratio_of(values, main)) for name, values, scope in entities if ratio_of(values, main) is not None]
    lowest_first = _has(query, ("thap nhat", "nho nhat", "it nhat")) or (
        spec["better"] == "low" and not _has(query, ("cao nhat", "lon nhat", "nhieu nhat")))
    rows.sort(key=lambda r: r[3], reverse=not lowest_first)
    others = [k for k in keys[1:] if k != main]
    header = ["#", "Doanh nghiệp", spec["name"], *[RATIOS[k]["name"] for k in others],
              f"{METRICS[spec['num']][0]} (tỷ đồng)", f"{METRICS[spec['den']][0]} (tỷ đồng)", "Phạm vi"]
    lines = [f"**{spec['name']} · {period}** — {len(rows)} doanh nghiệp, xếp {'từ thấp đến cao' if lowest_first else 'từ cao đến thấp'}", "",
             "| " + " | ".join(header) + " |", "|---:|---|" + "---:|" * (len(header) - 3) + "---|"]
    for i, (name, values, scope, value) in enumerate(rows, 1):
        extra = [pct(ratio_of(values, k)) if ratio_of(values, k) is not None else "—" for k in others]
        lines.append(f"| {i} | {name} | **{pct(value)}** | " + " | ".join(extra + [fmt_ty(values[spec['num']]), fmt_ty(values[spec['den']]), scope or "—"]) + " |")
    ordered = sorted(rows, key=lambda r: r[3])
    low, high = ordered[0], ordered[-1]
    mid = median(r[3] for r in rows)
    notes = ["", "**Nhận xét**", "",
             f"- **Cao nhất:** {high[0]} ({pct(high[3])}); **thấp nhất:** {low[0]} ({pct(low[3])}); trung vị {len(rows)} doanh nghiệp: {pct(mid)}."]
    vnm = next((i for i, r in enumerate(rows, 1) if r[0] == "Vinamilk"), None)
    if vnm:
        notes.append(f"- **Vinamilk** đứng thứ {vnm}/{len(rows)} trong bảng ({pct(next(r[3] for r in rows if r[0] == 'Vinamilk'))}).")
    if spec["better"] == "low":
        notes.append("- Tỷ lệ càng cao nghĩa là doanh nghiệp dùng nhiều nợ hơn so với " + ("vốn chủ sở hữu." if main == "no_von" else "tổng tài sản."))
    else:
        notes.append("- Biên càng cao nghĩa là mỗi đồng doanh thu giữ lại được nhiều lợi nhuận hơn; không phụ thuộc quy mô doanh nghiệp.")
    return "\n".join(lines + notes)


def focus_lines(entities: list, keys: list) -> list:
    """Nhận xét cho tỷ số được hỏi khi so sánh ít bên (bảng đã có đủ cột): ai cao hơn và chênh bao nhiêu điểm %."""
    out = []
    for key in keys:
        spec = RATIOS[key]
        have = [(name, ratio_of(values, key)) for name, values, _ in entities if ratio_of(values, key) is not None]
        if len(have) < 2:
            continue
        have.sort(key=lambda x: x[1], reverse=True)
        top, bottom = have[0], have[-1]
        detail = ", ".join(f"{n} {pct(v)}" for n, v in have)
        suffix = " (dùng nhiều nợ hơn)" if spec["better"] == "low" else ""
        out.append(f"- **{spec['name']}:** {detail}. {top[0]} cao hơn {bottom[0]} {points(top[1] - bottom[1])}{suffix}.")
    return out
