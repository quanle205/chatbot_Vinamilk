"""Phân tích nhiều doanh nghiệp từ các giá trị đã đối chiếu."""
from src.consumer import catalog, repository
from src.tools.facts import Period
from src.web.sources import source_links

COMPANIES = {"VNM": "Vinamilk", **{code: data[0] for code, data in catalog.COMPANIES.items()}}
LEGACY_METRICS = {"dong_tien_kinh_doanh": "luu_chuyen_hdkd", "dong_tien_dau_tu": "luu_chuyen_dau_tu",
                  "dong_tien_tai_chinh": "luu_chuyen_tai_chinh"}
RATIOS = (
    ("Sinh lời", "Biên lợi nhuận gộp", "loi_nhuan_gop", "doanh_thu_thuan", "%"),
    ("Sinh lời", "Biên lợi nhuận trước thuế", "loi_nhuan_truoc_thue", "doanh_thu_thuan", "%"),
    ("Sinh lời", "Biên lợi nhuận ròng", "loi_nhuan_sau_thue", "doanh_thu_thuan", "%"),
    ("Đòn bẩy", "Hệ số nợ trên vốn chủ sở hữu", "no_phai_tra", "von_chu_so_huu", "lần"),
    ("Đòn bẩy", "Hệ số nợ trên tổng tài sản", "no_phai_tra", "tong_tai_san", "%"),
)


def periods(company, analyst):
    if company == "VNM":
        return [str(p) for p in analyst.f.periods()]
    available = {r[0] for r in repository.documents(company)}
    return [p for p in catalog.PERIODS if p in available]


def value(company, period, metric, basis, analyst):
    if company == "VNM":
        key = LEGACY_METRICS.get(metric, metric)
        result = analyst.metric(key, period, basis)
        if result.get("ok") and result["metric"] == key:
            return result["value"], source_links(result["sources"]), "hợp nhất"
        return None
    rows = repository.facts([company], period, metric, basis)
    if rows:
        _, number, statement, page, url, scope, _ = rows[0]
        return number, [repository.source(company, period, scope, page, url, statement)], scope
    if (metric.startswith("dong_tien_") and basis == "quy"
            and period[:2] in {"Q2", "Q3", "Q4"} and company != "SBT"):
        prior = f"Q{int(period[1]) - 1}{period[2:]}"
        current = value(company, period, metric, "luy_ke", analyst)
        previous = value(company, prior, metric, "luy_ke", analyst)
        if current and previous and current[2] == previous[2] and current[2] in {"riêng", "hợp nhất"}:
            return current[0] - previous[0], [*current[1], *previous[1]], current[2]
    return None


def chart(companies, metrics, mode, period, basis, kind, analyst):
    def row(company, p, metric, label):
        record = value(company, p, metric, basis, analyst)
        return {"period": p, "label": label, "value": record[0] if record else None,
                "sources": record[1] if record else [],
                "source": record[1][0] if record and record[1] else None,
                "scope": record[2] if record else None}

    def matrix(metric, name):
        """Nhiều doanh nghiệp cùng một chỉ tiêu: hàng = doanh nghiệp, cột = kỳ (xu hướng theo quý hoặc hai kỳ so sánh)."""
        if mode == "series":
            quarters = [p for p in catalog.PERIODS if p.startswith("Q")]
            reported = [quarters.index(p) for c in companies for p in periods(c, analyst) if p in quarters]
            columns = quarters[min(reported):max(reported) + 1] if reported else []
        else:
            selected = Period.parse(period)
            columns = [str(selected.prev() if kind == "qoq" else selected.minus_year()), period]
        rows = []
        for company in companies:
            cells = [row(company, p, metric, p) for p in columns]
            sources = list({(src["url"], src.get("page")): src for cell in cells for src in cell["sources"]}.values())
            scopes = sorted({cell["scope"] for cell in cells if cell["scope"]})
            item = {"label": f"{COMPANIES[company]} ({company})", "cells": cells, "sources": sources, "scope": ", ".join(scopes)}
            if (mode == "growth" and all(cell["value"] is not None for cell in cells)
                    and cells[0]["scope"] == cells[1]["scope"] and cells[0]["scope"] != "theo báo cáo"):
                prior, current = (cell["value"] for cell in cells)
                item["change"] = current - prior
                item["growth"] = (current - prior) / abs(prior) if prior else None
            rows.append(item)
        title = f"{name} · " + ("xu hướng theo quý" if mode == "series" else f"{columns[0]} so với {columns[1]}")
        return {"kind": "matrix", "title": title, "unit": "tỷ đồng", "scale": 1e9, "columns": columns, "rows": rows,
                "growth": mode == "growth",
                "chart": mode == "series" and any(sum(c["value"] is not None for c in r["cells"]) >= 2 for r in rows)}

    blocks = []
    for metric in metrics:
        name = catalog.METRICS[metric][0]
        if metric not in {"tong_tai_san", "no_phai_tra", "von_chu_so_huu", "hang_ton_kho"} and not (period or "").startswith("FY"):
            name += " (lũy kế)" if basis == "luy_ke" else " (riêng quý)"
        if len(companies) > 1 and mode in {"series", "growth"}:
            blocks.append(matrix(metric, name))
            continue
        if mode == "companies":
            rows = [row(c, period, metric, f"{COMPANIES[c]} ({c})") for c in companies]
            blocks.append({"kind": "companies", "title": f"{name} · {catalog.PERIODS.get(period, period)}",
                           "unit": "tỷ đồng", "scale": 1e9, "rows": rows,
                           "chart": sum(r["value"] is not None for r in rows) >= 2})
            continue
        for company in companies:
            if mode == "series":
                reported = [p for p in periods(company, analyst) if p.startswith("Q")]
                quarters = [p for p in catalog.PERIODS if p.startswith("Q")]
                chosen = quarters[quarters.index(reported[0]):quarters.index(reported[-1]) + 1] if reported else []
            else:
                selected = Period.parse(period)
                base = selected.prev() if kind == "qoq" else selected.minus_year()
                chosen = [str(base), period]
            rows = [row(company, p, metric, p) for p in chosen]
            block = {"kind": "series" if mode == "series" else "comparison",
                     "title": f"{COMPANIES[company]} · {name}", "unit": "tỷ đồng", "scale": 1e9,
                     "rows": rows, "chart": mode == "series" and sum(r["value"] is not None for r in rows) >= 2}
            if (mode == "growth" and all(r["value"] is not None for r in rows)
                    and rows[0]["scope"] == rows[1]["scope"] and rows[0]["scope"] != "theo báo cáo"):
                prior, current = (r["value"] for r in rows)
                block["change"] = current - prior
                block["growth"] = (current - prior) / abs(prior) if prior else None
            blocks.append(block)
    return blocks


def ratios(company, period, basis, analyst):
    available = periods(company, analyst)
    if period not in available:
        raise ValueError(f"Chưa có báo cáo {period} của {COMPANIES[company]}.")
    annual = period.startswith("FY")
    selected = None if annual else Period.parse(period)
    prior = None if annual else str(selected.prev() if basis == "quy" else selected.minus_year())
    comparable = [p for p in available if p.startswith("FY") == annual]
    metrics = sorted({metric for _, _, a, b, _ in RATIOS for metric in (a, b)})
    records = {(p, metric): (number, [repository.source(company, p, scope, page, url, statement)], scope)
               for _, p, metric, number, statement, page, url, scope, _ in
               repository.fact_rows([company], comparable, metrics, basis)}
    groups = {}
    for group, name, numerator, denominator, unit in RATIOS:
        history = []
        for p in comparable:
            a, b = records.get((p, numerator)), records.get((p, denominator))
            same_scope = a and b and a[2] == b[2] and (a[2] != "theo báo cáo" or
                        a[1][0]["url"].split("#")[0] == b[1][0]["url"].split("#")[0])
            number = a[0] / b[0] if same_scope and b[0] != 0 else None
            history.append({"period": p, "value": number})
        current = next(h["value"] for h in history if h["period"] == period)
        previous = next((h["value"] for h in history if h["period"] == prior), None)
        items = groups.setdefault(group, [])
        if current is None:
            items.append({"name": name, "value": None, "error": "Thiếu số liệu đầu vào cùng phạm vi hoặc mẫu số bằng 0."})
            continue
        a, b = records[period, numerator], records[period, denominator]
        sources = {s["url"]: s for s in [*a[1], *b[1]]}
        items.append({"name": name, "value": current, "unit": unit, "history": history,
                      "formula": f"{catalog.METRICS[numerator][0]} / {catalog.METRICS[denominator][0]}",
                      "sources": list(sources.values()), "notes": [], "scope": a[2],
                      "delta": current - previous if previous is not None else None})
    return {"period": period, "basis": basis, "compare_period": prior,
            "compare_label": "quý liền trước" if basis == "quy" else "cùng kỳ năm trước",
            "groups": [{"name": name, "items": items} for name, items in groups.items()]}
