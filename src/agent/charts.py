"""Dựng dữ liệu biểu đồ/bảng cho giao diện từ KẾT QUẢ CÔNG CỤ (không lấy từ câu trả lời của mô hình).

Mỗi khối là dict thuần JSON:
  kind   series (xu hướng nhiều kỳ, có biểu đồ) | comparison (so sánh hai kỳ) | breakdown (phân rã chênh lệch)
  title, unit ("tỷ đồng"), scale (1e9: giá trị VND chia cho scale để ra đơn vị hiển thị)
  chart  True nếu giao diện nên vẽ biểu đồ (chỉ khi có từ 2 kỳ trở lên của get_series)
  rows   [{label, value, period?, source?}]   value giữ nguyên VND; source = {doc, statement, page, code} của số đó
  summary (chỉ series, từ 2 kỳ) {max, min: {label, value}, first, last: {label, value}, change, growth} do code tính để người dùng đánh giá nhanh
Định dạng số kiểu Việt Nam do giao diện đảm nhiệm.
"""
from __future__ import annotations

from ..tools.metrics import get_metric

SCALE = 1e9
UNIT = "tỷ đồng"
MAX_BLOCKS = 3
BASIS_WORDS = {"quy": "riêng quý", "luy_ke": "lũy kế từ đầu năm"}


def _source(sources: list) -> dict | None:
    if not sources:
        return None
    s = sources[0]
    return {"doc": s.get("doc"), "statement": s.get("statement"), "page": s.get("page"), "code": s.get("code")}


def _series(res: dict) -> dict | None:
    rows = res.get("rows") or []
    if not rows:
        return None
    try:
        m = get_metric(res.get("metric", ""))
    except KeyError:
        return None
    basis = "" if m.kind == "balance" else f" ({BASIS_WORDS.get(res.get('basis'), '')})"
    out = {"kind": "series", "title": f"{m.name}{basis}", "unit": UNIT, "scale": SCALE, "chart": len(rows) >= 2,
           "rows": [{"period": r["period"], "label": r["description"], "value": r["value"], "source": _source(r.get("sources", []))}
                    for r in rows]}
    if len(rows) >= 2:
        pick = lambda r: {"label": r["description"], "value": r["value"]}          # noqa: E731
        first, last = rows[0], rows[-1]
        out["summary"] = {"max": pick(max(rows, key=lambda r: r["value"])), "min": pick(min(rows, key=lambda r: r["value"])),
                          "first": pick(first), "last": pick(last), "change": last["value"] - first["value"],
                          "growth": None if first["value"] == 0 else (last["value"] - first["value"]) / abs(first["value"])}
    return out


def _comparison(res: dict) -> dict | None:
    if "current" not in res or "base" not in res or not res.get("current_label"):
        return None
    try:
        name = get_metric(res.get("metric", "")).name
    except KeyError:
        return None
    src = res.get("sources") or []
    return {"kind": "comparison", "title": f"{name}: {res['current_label']} so với {res['base_label']}", "unit": UNIT, "scale": SCALE,
            "chart": False, "change": res.get("change"), "growth": res.get("growth"),
            "rows": [{"label": res["current_label"], "value": res["current"], "source": _source(src)},
                     {"label": res["base_label"], "value": res["base"], "source": None}]}


def _breakdown(res: dict) -> dict | None:
    items = res.get("items") or []
    if not items:
        return None
    return {"kind": "breakdown", "title": f"Phân rã biến động {res['name']}: {res['current_label']} so với {res['base_label']}",
            "unit": UNIT, "scale": SCALE, "chart": False, "change": res.get("change"),
            "rows": [{"label": i["name"], "value": i["effect"], "source": None} for i in items]}


_BUILDERS = {"get_series": _series, "get_growth": _comparison, "explain_change": _breakdown}


def build_charts(tool_calls: list) -> list[dict]:
    """Từ các lượt gọi công cụ thành công của một câu hỏi -> danh sách khối biểu đồ/bảng (bỏ trùng, tối đa MAX_BLOCKS)."""
    out: list[dict] = []
    for tc in tool_calls:
        build = _BUILDERS.get(tc.name)
        if build is None or not tc.ok:
            continue
        block = build(tc.result)
        if block and block not in out:
            out.append(block)
    return out[:MAX_BLOCKS]
