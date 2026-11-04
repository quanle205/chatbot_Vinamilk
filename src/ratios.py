"""Bảng chỉ số tài chính cho một kỳ: giá trị, thay đổi so với kỳ so sánh và lịch sử các kỳ (vẽ đường nhỏ).

Mọi số do `Analyst.ratio` tính từ số liệu đã đối chiếu (cùng công cụ mà trợ lý gọi), không qua mô hình.
"""
from __future__ import annotations

from .tools.analyst import Analyst
from .tools.facts import Period

# (nhóm, [mã tỷ số]) theo thứ tự hiển thị; mã khớp `_build_ratios` trong tools/analyst.py
GROUPS = [
    ("Sinh lời", ["bien_loi_nhuan_gop", "bien_loi_nhuan_hdkd", "bien_loi_nhuan_rong", "roe", "roa"]),
    ("Chi phí", ["ty_le_chi_phi_ban_hang", "ty_le_chi_phi_qldn"]),
    ("Thanh khoản", ["thanh_toan_hien_hanh", "thanh_toan_nhanh"]),
    ("Đòn bẩy", ["tl_no_von", "tl_no_tai_san", "kha_nang_tra_lai"]),
    ("Hoạt động", ["ton_kho_vong_quay", "ton_kho_so_ngay"]),
]


def build_ratios(an: Analyst, period: str, basis: str = "quy") -> dict:
    """Trả {period, basis, compare_label, groups: [{name, items: [...]}]}; chỉ số không tính được có `value` None và `error`."""
    p = Period.parse(period)
    periods = an.f.periods()
    if p not in periods:
        raise ValueError(f"Chưa có số liệu kỳ {p}.")
    base = p.prev() if basis == "quy" else p.minus_year()                     # quý: so quý liền trước; lũy kế: so cùng kỳ năm trước
    compare = {"quy": "quý liền trước", "luy_ke": "cùng kỳ năm trước"}[basis]
    groups = []
    for name, keys in GROUPS:
        items = []
        for key in keys:
            history = []
            for q in periods:
                r = an.ratio(key, str(q), basis)
                history.append({"period": str(q), "value": r["value"] if r.get("ok") else None})
            cur = an.ratio(key, str(p), basis)
            if not cur.get("ok"):
                items.append({"key": key, "name": _name(an, key), "value": None, "error": cur.get("error", "Không tính được.")})
                continue
            prior = next((h["value"] for h in history if h["period"] == str(base)), None)
            items.append({"key": key, "name": cur["name"], "unit": cur["unit"], "formula": cur["formula"], "value": cur["value"],
                          "annualized": cur.get("annualized"), "delta": None if prior is None else cur["value"] - prior,
                          "history": history, "sources": cur["sources"], "notes": cur["notes"]})
        groups.append({"name": name, "items": items})
    return {"period": str(p), "basis": basis, "compare_label": compare, "compare_period": str(base), "groups": groups}


def _name(an: Analyst, key: str) -> str:
    return an._find_ratio(key).name
