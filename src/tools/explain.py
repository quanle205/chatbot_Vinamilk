"""Giải thích biến động: phân rã chênh lệch lợi nhuận sau thuế (hoặc doanh thu thuần) giữa hai kỳ theo khoản mục của báo cáo KQKD.

Mọi số do code tính từ số liệu đã đối chiếu; mô hình chỉ diễn giải. Phép phân rã là đồng nhất thức kế toán:
  LNST = doanh thu thuần - giá vốn + (doanh thu TC - chi phí TC) + lãi liên kết - chi phí bán hàng - chi phí QLDN
         + kết quả hoạt động khác - thuế TNDN (hiện hành + hoãn lại)
Mỗi dòng có `effect` = tác động của dòng đó lên chỉ tiêu (chi phí tăng thì effect âm). Tổng `effect` bằng đúng chênh lệch;
nếu số liệu hai kỳ có lệch (vd phân loại lại số cùng kỳ) thì thêm dòng "Khoản khác" để tổng vẫn khớp.
"""
from __future__ import annotations

from ..rag.text import fmt_ty
from .analyst import _merge, _src_text, fmt_pct
from .facts import DataUnavailable, Period
from .metrics import get_metric

# (khoá hiển thị, tên, [(mã chỉ tiêu, dấu)])
PROFIT_PARTS = [
    ("doanh_thu", "Doanh thu thuần", [("doanh_thu_thuan", 1)]),
    ("gia_von", "Giá vốn hàng bán", [("gia_von", -1)]),
    ("hoat_dong_tai_chinh", "Hoạt động tài chính (doanh thu trừ chi phí tài chính)", [("doanh_thu_tai_chinh", 1), ("chi_phi_tai_chinh", -1)]),
    ("lai_lien_ket", "Lãi chia từ công ty liên kết, liên doanh", [("lai_lien_ket", 1)]),
    ("chi_phi_ban_hang", "Chi phí bán hàng", [("chi_phi_ban_hang", -1)]),
    ("chi_phi_qldn", "Chi phí quản lý doanh nghiệp", [("chi_phi_qldn", -1)]),
    ("hoat_dong_khac", "Kết quả từ hoạt động khác", [("loi_nhuan_khac", 1)]),
    ("thue_tndn", "Thuế TNDN (hiện hành và hoãn lại)", [("thue_tndn_hien_hanh", -1), ("thue_tndn_hoan_lai", -1)]),
]
REVENUE_PARTS = [
    ("doanh_thu_gop", "Doanh thu bán hàng và cung cấp dịch vụ", [("doanh_thu_ban_hang", 1)]),
    ("giam_tru", "Các khoản giảm trừ doanh thu", [("giam_tru_doanh_thu", -1)]),
]
TARGETS = {"loi_nhuan_sau_thue": ("lợi nhuận sau thuế", PROFIT_PARTS),
           "doanh_thu_thuan": ("doanh thu thuần", REVENUE_PARTS)}
BASE_WORDS = {"yoy": "cùng kỳ năm trước", "qoq": "quý liền trước"}


def _signed(x: float) -> str:
    return ("+" if x >= 0 else "") + fmt_ty(x)


def explain_change(an, metric: str, period: str, base: str = "yoy", basis: str = "quy") -> dict:
    try:
        m = get_metric(metric)
        if m.key not in TARGETS:
            raise ValueError("explain_change chỉ hỗ trợ 'lợi nhuận sau thuế' và 'doanh thu thuần'.")
        if base not in BASE_WORDS:
            raise ValueError("base phải là yoy (so với cùng kỳ năm trước) hoặc qoq (so với quý liền trước).")
        if base == "qoq" and basis != "quy":
            raise ValueError("So với quý liền trước chỉ áp dụng cho số liệu riêng quý (basis=quy).")
        p = Period.parse(period)

        def get(key: str, cur: bool):
            mm = get_metric(key)
            if cur:
                return an.f.flow(mm, p, basis)
            return an.f.flow(mm, p, basis, "prior") if base == "yoy" else an.f.flow(mm, p.prev(), "quy")

        head_cur, head_base = get(m.key, True), get(m.key, False)
        name, parts = TARGETS[m.key]
        items, values = [], [head_cur, head_base]
        for key, label, comps in parts:
            cur = base_v = 0
            for code, sign in comps:
                c, b = get(code, True), get(code, False)
                values += [c, b]
                cur += sign * c.value
                base_v += sign * b.value
            items.append({"key": key, "name": label, "current": cur, "base": base_v, "effect": cur - base_v})
    except (DataUnavailable, KeyError, ValueError) as e:
        return {"ok": False, "error": str(e)}

    total = head_cur.value - head_base.value
    src, notes = _merge(values)
    residual = total - sum(i["effect"] for i in items)
    if abs(residual) >= 1:                                   # số liệu hai kỳ không khớp đồng nhất thức: nêu rõ thay vì làm tròn che đi
        items.append({"key": "khac", "name": "Khoản khác / chênh lệch phân loại", "current": 0, "base": 0, "effect": residual})
        notes.append("có chênh lệch do phân loại lại số liệu giữa các kỳ, được gộp vào 'Khoản khác'")
    for i in items:
        i["share"] = None if total == 0 else i["effect"] / total          # tỷ trọng đóng góp trong tổng chênh lệch
    drivers = sorted(items, key=lambda i: -abs(i["effect"]))[:2]
    word = "tăng" if total >= 0 else "giảm"
    verb = lambda e: "làm tăng" if e >= 0 else "làm giảm"                  # noqa: E731
    text = (f"Biến động {name} {head_cur.description} so với {BASE_WORDS[base]} ({head_base.description}): "
            f"{fmt_ty(head_base.value)} -> {fmt_ty(head_cur.value)} tỷ đồng, {word} {fmt_ty(abs(total))} tỷ đồng"
            + (f" ({_signed_pct(total, head_base.value)})" if head_base.value else "") + ". "
            "Đóng góp của từng khoản mục (tỷ đồng, dấu + là làm tăng, dấu - là làm giảm "
            f"{name}): " + "; ".join(f"{i['name']} {_signed(i['effect'])}" for i in items) + ". "
            f"Tổng các đóng góp bằng đúng chênh lệch {_signed(total)} tỷ đồng. "
            f"Yếu tố tác động lớn nhất: " + "; ".join(f"{d['name']} ({verb(d['effect'])} {fmt_ty(abs(d['effect']))} tỷ đồng)" for d in drivers) + ".")
    if notes:
        text += " Lưu ý: " + "; ".join(notes) + "."
    text += f" Nguồn: {_src_text(src)}."
    return {"ok": True, "text": text, "metric": m.key, "name": name, "period": str(p), "base_kind": base, "basis": basis,
            "current_label": head_cur.description, "base_label": head_base.description,
            "current": head_cur.value, "base": head_base.value, "change": total, "items": items,
            "sources": src, "notes": notes}


def _signed_pct(total: float, base: float) -> str:
    pct = total / abs(base)
    return ("+" if pct >= 0 else "") + fmt_pct(pct)
