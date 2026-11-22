"""Tăng trưởng giữa hai kỳ và cầu nối lợi nhuận ("vì sao lợi nhuận đổi") cho các công ty.

Tính thuần từ số đã đối chiếu, không qua mô hình. Cầu nối là phân rã số học của báo cáo kết quả kinh doanh (tổng các khoản mục đúng bằng
chênh lệch); nó cho biết khoản mục nào đóng góp bao nhiêu, không suy đoán nguyên nhân kinh doanh (giá nguyên liệu, khuyến mãi...).
"""
from __future__ import annotations

from src.consumer.catalog import METRICS
from src.consumer.insight import _has, pct
from src.rag.text import fmt_ty

GROWTH_WORDS = ("tang truong", "tang bao nhieu", "giam bao nhieu", "tang hay giam", "tang giam", "bao nhieu phan tram", "phan tram",
                "so voi cung ky", "so voi quy truoc", "so voi quy lien truoc", "so voi nam truoc", "cung ky nam truoc",
                "bien dong", "thay doi bao nhieu", "tang so voi", "giam so voi", "yoy", "qoq")
WHY_WORDS = ("vi sao", "tai sao", "do dau", "nguyen nhan", "ly do")
QOQ_WORDS = ("quy truoc", "quy lien truoc", "lien ke", "qoq")
YOY_WORDS = ("cung ky", "nam truoc", "yoy")
DEFAULT_METRICS = ("doanh_thu_thuan", "loi_nhuan_sau_thue")
PROFIT_LEVELS = ("loi_nhuan_sau_thue", "loi_nhuan_truoc_thue", "loi_nhuan_gop")      # từ thấp xuống cao trong cầu nối


def asked_growth(query: str) -> bool:
    return _has(query, GROWTH_WORDS) or "%" in query


def asked_why(query: str) -> bool:
    return _has(query, WHY_WORDS)


def quarter_key(period: str):
    """(năm, quý) của "Q2/2026"; None nếu không phải quý."""
    if period.startswith("Q") and "/" in period:
        return int(period[3:]), int(period[1])
    return None


def prev_quarter(period: str) -> str:
    year, quarter = quarter_key(period)
    return f"Q{quarter - 1}/{year}" if quarter > 1 else f"Q4/{year - 1}"


def last_year(period: str) -> str:
    year, quarter = quarter_key(period)
    return f"Q{quarter}/{year - 1}"


def pick_periods(query: str, requested: list, best_current) -> tuple:
    """(kỳ gốc, kỳ hiện tại, cách so sánh, đã tự chọn cách so sánh chưa).

    Nêu hai quý thì lấy làm hai mốc; một quý thì so với cùng kỳ năm trước (hoặc quý liền trước nếu câu nói vậy);
    không nêu quý thì lấy kỳ gần nhất có số do `best_current()` chọn.
    """
    quarters = sorted({p for p in requested if quarter_key(p)}, key=quarter_key)
    if len(quarters) >= 2:
        return quarters[0], quarters[-1], "range", False
    qoq, yoy = _has(query, QOQ_WORDS), _has(query, YOY_WORDS)
    kind = "qoq" if qoq and not yoy else "yoy"
    current = quarters[0] if quarters else best_current()
    if current is None:
        return None, None, kind, not (qoq or yoy)
    return (prev_quarter(current) if kind == "qoq" else last_year(current)), current, kind, not (qoq or yoy)


def period_word(kind: str) -> str:
    return {"yoy": "so với cùng kỳ năm trước", "qoq": "so với quý liền trước"}.get(kind, "giữa hai kỳ")


def signed_ty(x: float) -> str:
    """Số đồng có dấu, đổi sang tỷ đồng, định dạng Việt Nam (+1.234,5)."""
    return f"{x / 1e9:+,.1f}".replace(",", "_").replace(".", ",").replace("_", ".")


def growth_text(metric: str, base_label: str, cur_label: str, rows: list, kind: str) -> str:
    """Câu dẫn và bảng tăng trưởng của một chỉ tiêu. rows = [(tên, giá trị kỳ gốc, giá trị kỳ này, hai kỳ cùng phạm vi báo cáo?)]."""
    label = METRICS[metric][0]
    table = [f"| Doanh nghiệp | {base_label} (tỷ đồng) | {cur_label} (tỷ đồng) | Thay đổi (tỷ đồng) | Thay đổi (%) |", "|---|---:|---:|---:|---:|"]
    verdicts, ranked = [], []
    for name, base, cur, same_scope in rows:
        change = cur - base
        if not same_scope:
            cell, verdict = "—", "không so sánh được vì hai kỳ khác phạm vi báo cáo"
        elif base > 0:
            ratio = change / base
            cell = f"{ratio * 100:+.1f}%".replace(".", ",")
            verdict = f"{'tăng' if change > 0 else 'giảm' if change < 0 else 'không đổi'} {fmt_ty(abs(change))} tỷ đồng ({cell})"
            ranked.append((name, ratio))
        elif cur > 0:
            cell, verdict = "—", f"chuyển từ lỗ {fmt_ty(abs(base))} sang lãi {fmt_ty(cur)} tỷ đồng"
        else:
            cell, verdict = "—", f"{'lỗ thêm' if cur < base else 'bớt lỗ'} {fmt_ty(abs(change))} tỷ đồng (từ {fmt_ty(base)} xuống {fmt_ty(cur)})"
        table.append(f"| {name} | {fmt_ty(base)} | {fmt_ty(cur)} | {signed_ty(change)} | {cell} |")
        verdicts.append((name, verdict))
    if len(rows) == 1:
        name, base, cur, _ = rows[0]
        lead = f"**{label} {cur_label} của {name}** {verdicts[0][1]} {period_word(kind)} ({base_label}: {fmt_ty(base)} → {fmt_ty(cur)} tỷ đồng)."
    elif len(rows) <= 3:
        lead = f"**{label} {cur_label}** {period_word(kind)}: " + "; ".join(f"{n} {v}" for n, v in verdicts) + "."
    else:
        up = sum(1 for _, r in ranked if r > 0)
        lead = f"**{label} {cur_label}** {period_word(kind)}: {up}/{len(ranked)} doanh nghiệp tăng."
        if len(ranked) > 1:
            ranked.sort(key=lambda x: x[1], reverse=True)
            top, bottom = f"{ranked[0][1] * 100:+.1f}%".replace(".", ","), f"{ranked[-1][1] * 100:+.1f}%".replace(".", ",")
            lead += f" Tăng mạnh nhất: {ranked[0][0]} ({top}); yếu nhất: {ranked[-1][0]} ({bottom})."
        excluded = [n for n, v in verdicts if "không so sánh được" in v]
        if excluded:
            lead += f" Không so sánh được: {', '.join(excluded)} (hai kỳ khác phạm vi báo cáo)."
    return lead + "\n\n" + "\n".join(table)


def bridge_parts(base: dict, cur: dict, level: str):
    """[(khoản mục, đóng góp đồng)] của cầu nối đến mức `level`; tổng các đóng góp bằng đúng chênh lệch lợi nhuận ở mức đó. None nếu doanh thu không dương."""
    dt0, dt1, gp0, gp1 = base["doanh_thu_thuan"], cur["doanh_thu_thuan"], base["loi_nhuan_gop"], cur["loi_nhuan_gop"]
    if dt0 <= 0 or dt1 <= 0:
        return None
    m0, m1 = gp0 / dt0, gp1 / dt1
    parts = [("Doanh thu thuần thay đổi (giữ nguyên biên gộp kỳ gốc)", (dt1 - dt0) * m0),
             (f"Biên lợi nhuận gộp thay đổi ({pct(m0)} → {pct(m1)})", dt1 * (m1 - m0))]
    if level in ("loi_nhuan_truoc_thue", "loi_nhuan_sau_thue"):
        parts.append(("Chi phí và thu nhập khác (bán hàng, quản lý, tài chính, khác)",
                      (cur["loi_nhuan_truoc_thue"] - gp1) - (base["loi_nhuan_truoc_thue"] - gp0)))
    if level == "loi_nhuan_sau_thue":
        parts.append(("Thuế thu nhập doanh nghiệp",
                      (cur["loi_nhuan_sau_thue"] - cur["loi_nhuan_truoc_thue"]) - (base["loi_nhuan_sau_thue"] - base["loi_nhuan_truoc_thue"])))
    return parts


def bridge_text(name: str, base_label: str, cur_label: str, base: dict, cur: dict, target: str):
    """Cầu nối lợi nhuận giữa hai kỳ: (văn bản, mức đã phân rã) hoặc ("", None) nếu thiếu số.

    Lợi nhuận gộp = doanh thu x biên gộp nên chênh lệch gộp tách đúng thành hiệu ứng doanh thu (giữ biên kỳ gốc) và hiệu ứng biên.
    Dưới lợi nhuận gộp: chi phí và thu nhập khác (bán hàng, quản lý, tài chính, khác) rồi thuế. Tổng các khoản mục bằng đúng chênh lệch.
    """
    need = {"loi_nhuan_gop": ("doanh_thu_thuan", "loi_nhuan_gop"),
            "loi_nhuan_truoc_thue": ("doanh_thu_thuan", "loi_nhuan_gop", "loi_nhuan_truoc_thue"),
            "loi_nhuan_sau_thue": ("doanh_thu_thuan", "loi_nhuan_gop", "loi_nhuan_truoc_thue", "loi_nhuan_sau_thue")}
    for level in PROFIT_LEVELS[PROFIT_LEVELS.index(target):]:            # thiếu số ở mức đích thì lùi về mức cao nhất đủ số
        if all(k in base and k in cur for k in need[level]):
            break
    else:
        return "", None
    parts = bridge_parts(base, cur, level)
    if parts is None:
        return "", None
    total = cur[level] - base[level]
    label = METRICS[level][0]
    direction = "tăng" if total > 0 else "giảm" if total < 0 else "không đổi"
    lines = [f"**{label} {cur_label} của {name}** {direction} {fmt_ty(abs(total))} tỷ đồng so với {base_label} ({fmt_ty(base[level])} → {fmt_ty(cur[level])} tỷ đồng)."]
    if total:
        ranked = sorted(parts, key=lambda p: abs(p[1]), reverse=True)
        along = [p for p in ranked if p[1] * total > 0][:2]
        if along:
            lines.append(f"Khoản mục đóng góp nhiều nhất vào chiều {direction}: " + "; ".join(f"{p[0].split(' (')[0].lower()} ({signed_ty(p[1])} tỷ đồng)" for p in along) + ".")
        against = [p for p in ranked if p[1] * total < 0][:1]
        if against and abs(against[0][1]) > abs(total) * 0.1:
            lines.append(f"Ngược chiều: {against[0][0].split(' (')[0].lower()} ({signed_ty(against[0][1])} tỷ đồng).")
    table = ["| Khoản mục | Đóng góp (tỷ đồng) | Tác động |", "|---|---:|---|"]
    for part, value in parts:
        table.append(f"| {part} | {signed_ty(value)} | {'làm tăng' if value > 0 else 'làm giảm' if value < 0 else 'không đổi'} |")
    table.append(f"| **Tổng thay đổi {label.lower()}** | **{signed_ty(total)}** | {direction} |")
    note = f"\n\nChỉ phân rã được đến {label.lower()} vì thiếu số ở các khoản mục phía sau." if level != target else ""
    return "\n\n".join(["\n".join(lines), "\n".join(table)]) + note, level
