"""Tra số, tỷ số tài chính, tăng trưởng và chuỗi thời gian từ số liệu BCTC đã đối chiếu.

Mọi hàm trả về dict có `ok`, `text` (câu tiếng Việt ngắn để đưa vào ngữ cảnh LLM), số liệu cấu trúc,
`sources` (báo cáo + trang PDF + mã số) và `notes` (số suy ra / đã phân loại lại / đã sửa OCR).
Lỗi do thiếu dữ liệu trả `ok=False` kèm lý do, không ném ngoại lệ ra ngoài.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..rag.text import fmt_ty, fmt_vnd
from .facts import DataUnavailable, Facts, Period, Value
from .metrics import Metric, find_metrics, get_metric

STATEMENT_VI = {"CDKT": "Báo cáo tình hình tài chính", "KQKD": "Báo cáo kết quả hoạt động kinh doanh",
                "LCTT": "Báo cáo lưu chuyển tiền tệ"}


def fmt_pct(x: float) -> str:
    return f"{x * 100:,.1f}%".replace(",", "_").replace(".", ",").replace("_", ".")


def fmt_num(x: float, nd: int = 2) -> str:
    return f"{x:,.{nd}f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _src_text(sources: list) -> str:
    seen, out = set(), []
    for s in sources:
        k = (s["doc"], s["statement"], s["page"])
        if k not in seen:
            seen.add(k)
            out.append(f"{s['doc']} {STATEMENT_VI[s['statement']]} trang PDF {s['page']} (mã {s['code']})")
    return "; ".join(out)


def _merge(values: list[Value]) -> tuple[list, list]:
    src, notes = [], []
    for v in values:
        src += [s for s in v.sources if s not in src]
        notes += [n for n in v.notes if n not in notes]
    return src, notes


SNAPSHOT = {"thanh_toan_hien_hanh", "thanh_toan_nhanh", "tl_no_von", "tl_no_tai_san"}


@dataclass
class Ratio:
    key: str
    name: str
    unit: str                                   # "%" | "lần" | "ngày"
    formula: str
    aliases: tuple
    fn: Callable                                 # (Analyst, Period, basis) -> (giá trị, {tên: Value}, quy năm được?)
    periodic: bool = False


class Analyst:
    def __init__(self, facts: Facts | None = None):
        self.f = facts or Facts()
        self.ratios = {r.key: r for r in _build_ratios()}

    # ================================================================ tra số
    def value(self, metric: str | Metric, p: Period, basis: str = "quy", which: str = "current") -> Value:
        m = metric if isinstance(metric, Metric) else get_metric(metric)
        return self.f.balance(m, p) if m.kind == "balance" else self.f.flow(m, p, basis, which)

    def metric(self, metric: str, period: str, basis: str = "quy") -> dict:
        try:
            m = get_metric(metric)
            p = Period.parse(period)
            v = self.value(m, p, basis)
        except (DataUnavailable, KeyError, ValueError) as e:
            return {"ok": False, "error": str(e)}
        text = (f"{m.name} {v.description}: {fmt_vnd(v.value)} VND (≈ {fmt_ty(v.value)} tỷ đồng). "
                f"Nguồn: {_src_text(v.sources)}.")
        if v.notes:
            text += " Lưu ý: " + "; ".join(v.notes) + "."
        return {"ok": True, "text": text, "metric": m.key, "name": m.name, "period": str(p),
                "basis": basis if m.kind == "flow" else "so_du", "description": v.description,
                "value": v.value, "unit": "VND", "sources": v.sources, "notes": v.notes}

    def search_metrics(self, text: str, limit: int = 5) -> dict:
        hits = find_metrics(text, limit)
        return {"ok": True, "matches": [{"key": m.key, "name": m.name, "statement": m.statement, "kind": m.kind}
                                        for m in hits],
                "text": "; ".join(f"{m.key} = {m.name}" for m in hits) or "Không tìm thấy chỉ tiêu phù hợp."}

    # ================================================================ tỷ số
    def ratio(self, ratio: str, period: str, basis: str = "quy") -> dict:
        try:
            r = self._find_ratio(ratio)
            p = Period.parse(period)
            val, inputs, annual = r.fn(self, p, basis)
        except (DataUnavailable, KeyError, ValueError, ZeroDivisionError) as e:
            return {"ok": False, "error": str(e) if not isinstance(e, ZeroDivisionError) else "Mẫu số bằng 0."}
        src, notes = _merge(list(inputs.values()))
        shown = fmt_pct(val) if r.unit == "%" else f"{fmt_num(val)} {r.unit}"
        months = 3 * p.quarter if basis == "luy_ke" else 3
        if r.key in SNAPSHOT:                                   # tỷ số tính trên số dư tại một thời điểm
            label = self.f.balance(get_metric("tong_tai_san"), p).description
        elif basis == "luy_ke":
            label = f"{months} tháng đầu năm {p.year}" if p.quarter < 4 else f"cả năm {p.year}"
        else:
            label = f"quý {p.quarter}/{p.year}"
        text = f"{r.name} {label}: {shown} (công thức: {r.formula})."
        out = {"ok": True, "ratio": r.key, "name": r.name, "period": str(p), "basis": basis, "value": val,
               "unit": r.unit, "formula": r.formula, "inputs": {k: v.value for k, v in inputs.items()},
               "sources": src, "notes": notes}
        if annual and months != 12:                             # ROE/ROA/vòng quay: quy về năm để so sánh được
            av = val * 12 / months
            out["annualized"] = av
            text += f" Quy năm (×{12 // months}): " + (fmt_pct(av) if r.unit == "%" else f"{fmt_num(av)} {r.unit}/năm") + "."
        if notes:
            text += " Lưu ý: " + "; ".join(notes) + "."
        text += f" Nguồn: {_src_text(src)}."
        out["text"] = text
        return out

    def _find_ratio(self, text: str) -> Ratio:
        from ..rag.text import accent_free, normalize
        if text in self.ratios:
            return self.ratios[text]
        q = accent_free(normalize(text)).replace("_", " ")
        best, best_len = None, 0
        for r in self.ratios.values():
            for a in (r.name, *r.aliases):
                a = accent_free(normalize(a))
                if a in q:                                       # tên nằm trong câu hỏi: alias dài thắng
                    score = len(a) + 100
                elif len(q) >= 8 and q in a:                     # câu hỏi là phần của tên ("thanh toán hiện hành")
                    score = len(q)
                else:
                    continue
                if score > best_len:
                    best, best_len = r, score
        if best is None:
            raise KeyError(f"Không có tỷ số '{text}'. Có: " + ", ".join(f"{r.key} ({r.name})" for r in self.ratios.values()))
        return best

    # ================================================================ tăng trưởng
    def growth(self, metric: str, period: str, kind: str = "yoy", basis: str = "quy") -> dict:
        """kind: yoy (so với cùng kỳ năm trước), qoq (so với quý trước), ytd (số dư so với đầu năm)."""
        try:
            m = get_metric(metric)
            p = Period.parse(period)
            if kind == "yoy":
                if m.kind == "flow":
                    cur, prev = self.f.flow(m, p, basis), self.f.flow(m, p, basis, "prior")
                else:
                    cur, prev = self.f.balance(m, p), self.f.balance(m, p.minus_year())
                what = "so với cùng kỳ năm trước"
            elif kind == "qoq":
                if m.kind == "flow":
                    cur, prev = self.f.flow(m, p, "quy"), self.f.flow(m, p.prev(), "quy")
                else:
                    cur, prev = self.f.balance(m, p), self.f.opening(m, p, "quy")
                what = "so với quý liền trước"
            elif kind == "ytd":
                if m.kind != "balance":
                    raise DataUnavailable("ytd chỉ áp dụng cho chỉ tiêu số dư (so cuối kỳ với đầu năm).")
                cur, prev = self.f.balance(m, p), self.f.opening(m, p, "luy_ke")
                what = "so với đầu năm"
            else:
                raise ValueError("kind phải là yoy, qoq hoặc ytd.")
        except (DataUnavailable, KeyError, ValueError) as e:
            return {"ok": False, "error": str(e)}
        src, notes = _merge([cur, prev])
        delta = cur.value - prev.value
        pct = None if prev.value == 0 else delta / abs(prev.value)
        if prev.value < 0:
            notes.append("kỳ gốc âm nên tỷ lệ tăng trưởng chỉ mang tính tham khảo")
        if pct is None:
            notes.append("kỳ gốc bằng 0, không tính được tỷ lệ")
        head = f"{m.name} {cur.description}: {fmt_vnd(cur.value)} VND (≈ {fmt_ty(cur.value)} tỷ); kỳ gốc ({prev.description}): " \
               f"{fmt_vnd(prev.value)} VND (≈ {fmt_ty(prev.value)} tỷ)."
        text = head + (f" Thay đổi {what}: {'+' if delta >= 0 else ''}{fmt_ty(delta)} tỷ đồng ({'+' if (pct or 0) >= 0 else ''}{fmt_pct(pct)})."
                       if pct is not None else f" Thay đổi {what}: {fmt_ty(delta)} tỷ đồng.")
        if notes:
            text += " Lưu ý: " + "; ".join(notes) + "."
        text += f" Nguồn: {_src_text(src)}."
        return {"ok": True, "text": text, "metric": m.key, "period": str(p), "kind": kind, "basis": basis,
                "current": cur.value, "base": prev.value, "change": delta, "growth": pct,
                "sources": src, "notes": notes}

    # ================================================================ chuỗi
    def series(self, metric: str, basis: str = "quy") -> dict:
        try:
            m = get_metric(metric)
        except KeyError as e:
            return {"ok": False, "error": str(e)}
        rows = []
        for p in self.f.periods():
            try:
                v = self.value(m, p, basis)
            except DataUnavailable:
                continue
            rows.append({"period": str(p), "description": v.description, "value": v.value,
                         "notes": v.notes, "sources": v.sources})
        if not rows:
            return {"ok": False, "error": f"Không có số liệu '{m.name}' với cơ sở '{basis}'."}
        text = f"{m.name} ({'số dư cuối kỳ' if m.kind == 'balance' else 'cơ sở ' + basis}), đơn vị tỷ đồng: " + \
               "; ".join(f"{r['description']}: {fmt_ty(r['value'])}" for r in rows) + "."
        derived = [r["description"] for r in rows if any("suy ra" in n for n in r["notes"])]
        if derived:
            text += " Số suy ra (báo cáo không in sẵn): " + ", ".join(derived) + "."
        return {"ok": True, "text": text, "metric": m.key, "basis": basis, "rows": rows}


# ====================================================================== định nghĩa tỷ số
def _avg(a: Value, b: Value, label: str) -> Value:
    v = Value((a.value + b.value) / 2, a.sources + [s for s in b.sources if s not in a.sources],
              sorted(set(a.notes + b.notes)), label)
    return v


def _bal_sub(an: Analyst, p: Period, keys: tuple, opening: bool, basis: str) -> Value:
    """Số dư của (k0 - k1 - ...) tại cuối kỳ hoặc đầu kỳ."""
    vals = [(an.f.opening(get_metric(k), p, basis) if opening else an.f.balance(get_metric(k), p)) for k in keys]
    src, notes = _merge(vals)
    return Value(vals[0].value - sum(v.value for v in vals[1:]), src, notes, vals[0].description)


def _margin(num: str, den: str = "doanh_thu_thuan"):
    def fn(an, p, basis):
        n, d = an.value(num, p, basis), an.value(den, p, basis)
        return n.value / d.value, {get_metric(num).name: n, get_metric(den).name: d}, False
    return fn


def _ratio_bal(num: tuple, den: tuple):
    def fn(an, p, basis):
        n, d = _bal_sub(an, p, num, False, basis), _bal_sub(an, p, den, False, basis)
        return n.value / d.value, {" - ".join(num): n, " - ".join(den): d}, False
    return fn


def _return_on(num_key: str, avg_keys: tuple):
    def fn(an, p, basis):
        n = an.value(num_key, p, basis)
        o, c = _bal_sub(an, p, avg_keys, True, basis), _bal_sub(an, p, avg_keys, False, basis)
        a = _avg(o, c, "bình quân đầu và cuối kỳ")
        name = " - ".join(get_metric(k).name for k in avg_keys)
        return n.value / a.value, {get_metric(num_key).name: n, f"{name} bình quân": a}, True
    return fn


def _quick(an, p, basis):
    cash = [an.f.balance(get_metric(k), p) for k in ("tien", "dau_tu_ngan_han", "phai_thu_ngan_han")]
    d = an.f.balance(get_metric("no_ngan_han"), p)
    s = Value(sum(v.value for v in cash), *_merge(cash), "tiền + đầu tư ngắn hạn + phải thu ngắn hạn")
    return s.value / d.value, {"Tiền + đầu tư TC ngắn hạn + phải thu ngắn hạn": s, "Nợ ngắn hạn": d}, False


def _coverage(an, p, basis):
    t, i = an.value("loi_nhuan_truoc_thue", p, basis), an.value("chi_phi_lai_vay", p, basis)
    ebit = Value(t.value + i.value, *_merge([t, i]))
    return ebit.value / i.value, {"Lợi nhuận trước thuế + lãi vay": ebit, "Chi phí lãi vay": i}, False


def _inv_turn(an, p, basis):
    g = an.value("gia_von", p, basis)
    o = an.f.opening(get_metric("hang_ton_kho"), p, basis)
    c = an.f.balance(get_metric("hang_ton_kho"), p)
    a = _avg(o, c, "bình quân đầu và cuối kỳ")
    return g.value / a.value, {"Giá vốn hàng bán": g, "Hàng tồn kho bình quân": a}, True


def _inv_days(an, p, basis):
    t, ins, annual = _inv_turn(an, p, basis)
    months = 3 * p.quarter if basis == "luy_ke" else 3
    return (30 * months) / t, ins, False


def _build_ratios() -> list[Ratio]:
    R = Ratio
    return [
        R("bien_loi_nhuan_gop", "Biên lợi nhuận gộp", "%", "Lợi nhuận gộp / Doanh thu thuần",
          ("biên lãi gộp", "gross margin", "tỷ suất lợi nhuận gộp"), _margin("loi_nhuan_gop")),
        R("bien_loi_nhuan_hdkd", "Biên lợi nhuận hoạt động", "%", "Lợi nhuận thuần từ HĐKD / Doanh thu thuần",
          ("biên lợi nhuận từ hoạt động kinh doanh", "operating margin"), _margin("loi_nhuan_hdkd")),
        R("bien_loi_nhuan_truoc_thue", "Biên lợi nhuận trước thuế", "%", "Lợi nhuận trước thuế / Doanh thu thuần",
          ("biên lãi trước thuế",), _margin("loi_nhuan_truoc_thue")),
        R("bien_loi_nhuan_rong", "Biên lợi nhuận ròng", "%", "Lợi nhuận sau thuế / Doanh thu thuần",
          ("biên lợi nhuận sau thuế", "biên lãi ròng", "net margin", "biên lợi nhuận"), _margin("loi_nhuan_sau_thue")),
        R("ty_le_chi_phi_ban_hang", "Tỷ lệ chi phí bán hàng trên doanh thu", "%", "Chi phí bán hàng / Doanh thu thuần",
          ("chi phí bán hàng trên doanh thu", "chi phí bán hàng/doanh thu"), _margin("chi_phi_ban_hang")),
        R("ty_le_chi_phi_qldn", "Tỷ lệ chi phí quản lý trên doanh thu", "%", "Chi phí QLDN / Doanh thu thuần",
          ("chi phí quản lý trên doanh thu",), _margin("chi_phi_qldn")),
        R("roe", "ROE (lợi nhuận trên vốn chủ sở hữu)", "%",
          "LNST của chủ sở hữu công ty mẹ / VCSH thuộc công ty mẹ bình quân (VCSH - lợi ích cổ đông không kiểm soát)",
          ("roe", "tỷ suất sinh lời trên vốn chủ sở hữu", "lợi nhuận trên vốn chủ"),
          _return_on("lnst_chu_so_huu", ("von_chu_so_huu", "loi_ich_co_dong_khong_kiem_soat")), periodic=True),
        R("roa", "ROA (lợi nhuận trên tổng tài sản)", "%", "Lợi nhuận sau thuế / Tổng tài sản bình quân",
          ("roa", "tỷ suất sinh lời trên tổng tài sản", "lợi nhuận trên tài sản"),
          _return_on("loi_nhuan_sau_thue", ("tong_tai_san",)), periodic=True),
        R("thanh_toan_hien_hanh", "Hệ số thanh toán hiện hành", "lần", "Tài sản ngắn hạn / Nợ ngắn hạn",
          ("current ratio", "khả năng thanh toán hiện hành", "thanh toán ngắn hạn"), _ratio_bal(("tai_san_ngan_han",), ("no_ngan_han",))),
        R("thanh_toan_nhanh", "Hệ số thanh toán nhanh", "lần", "(Tiền + đầu tư TC ngắn hạn + phải thu ngắn hạn) / Nợ ngắn hạn",
          ("quick ratio", "khả năng thanh toán nhanh"), _quick),
        R("tl_no_von", "Hệ số nợ trên vốn chủ sở hữu", "lần", "Nợ phải trả / Vốn chủ sở hữu",
          ("d/e", "nợ trên vốn chủ", "đòn bẩy tài chính", "nợ/vốn chủ"), _ratio_bal(("no_phai_tra",), ("von_chu_so_huu",))),
        R("tl_no_tai_san", "Hệ số nợ trên tổng tài sản", "%", "Nợ phải trả / Tổng tài sản",
          ("nợ trên tổng tài sản", "tỷ lệ nợ"), _ratio_bal(("no_phai_tra",), ("tong_tai_san",))),
        R("kha_nang_tra_lai", "Khả năng thanh toán lãi vay", "lần", "(Lợi nhuận trước thuế + chi phí lãi vay) / Chi phí lãi vay",
          ("interest coverage", "khả năng trả lãi", "hệ số thanh toán lãi vay"), _coverage),
        R("ton_kho_vong_quay", "Vòng quay hàng tồn kho", "lần", "Giá vốn hàng bán / Hàng tồn kho bình quân",
          ("vòng quay tồn kho", "inventory turnover"), _inv_turn, periodic=True),
        R("ton_kho_so_ngay", "Số ngày tồn kho", "ngày", "Số ngày trong kỳ / Vòng quay hàng tồn kho",
          ("số ngày hàng tồn kho", "days inventory"), _inv_days),
    ]
