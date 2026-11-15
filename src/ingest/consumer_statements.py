"""Đọc các chỉ tiêu có thể đối chiếu bằng đẳng thức của báo cáo."""
from itertools import product
import re

from src.consumer.catalog import fold
from src.ingest.consumer_tables import amount, vertical

AMOUNT_CHARS = str.maketrans("Oo", "00")


def row_candidates(boxes, code, count):
    candidates = set()
    for anchor in boxes:
        if anchor[4].strip() != code or anchor[0] > .68:
            continue
        numbers = []
        for box in boxes:
            if box[0] < max(.37, anchor[2] + .018):
                continue
            difference = vertical(box) - vertical(anchor)
            if not -.007 <= difference <= .019:
                continue
            cell = box[4].strip(" ;:|").translate(AMOUNT_CHARS)
            value = amount(cell)
            if value is not None and (len(cell) >= 5 or cell in {"-", "–", "—", "0"}):
                numbers.append((box[0], vertical(box), value))
            elif " " in cell:
                parts = cell.split()
                values = [amount(part) for part in parts]
                if all(value is not None and len(part) >= 5 for part, value in zip(parts, values, strict=True)):
                    width = (box[2] - box[0]) / len(values)
                    numbers.extend((box[0] + i * width, vertical(box), value)
                                   for i, value in enumerate(values))
        for _, y, _ in numbers:
            row = sorted((x, value) for x, center, value in numbers if abs(center - y) < .005)
            if len(row) == count:
                candidates.add(tuple(value for _, value in row))
    return candidates


def balanced_income(candidates):
    gross = {
        (revenue, profit) for revenue, cost, profit in product(
            candidates["10"], candidates["11"], candidates["20"]
        ) if revenue > 0 and cost != 0 and revenue - abs(cost) == profit
    }
    if len(gross) != 1:
        return {}
    revenue, gross_profit = gross.pop()
    rows = {"doanh_thu_thuan": revenue, "loi_nhuan_gop": gross_profit}
    pretax = {
        total for earnings, other, total in product(candidates["30"], candidates["40"], candidates["50"])
        if earnings + other == total
    }
    if len(pretax) == 1:
        total = pretax.pop()
        rows["loi_nhuan_truoc_thue"] = total
        deferred = candidates["52"] or {0}
        after_tax = {
            net for current_tax, delayed_tax, net in product(candidates["51"], deferred, candidates["60"])
            if total - (current_tax + delayed_tax) == net or total + (current_tax + delayed_tax) == net
        }
        if len(after_tax) == 1:
            rows["loi_nhuan_sau_thue"] = after_tax.pop()
    return rows


def page_header(boxes):
    return fold(" ".join(b[4] for b in sorted(boxes, key=lambda b: (round(vertical(b) / .006), b[0]))
                         if b[1] < .31))


def uses_vnd(header, default_vnd=False):
    return ((default_vnd or re.search(r"\bvnd\b", header))
            and not re.search(r"\b(nghin|ngan|trieu|ty)\s+(dong|vnd)\b", header))


def statement_scope(header):
    if re.search(r"\bh[oqeg]p nhat\b", header):
        return "hợp nhất"
    return "riêng" if "rieng" in header else "theo báo cáo"


def read_income(boxes, header, period, company, split_statement):
    form_code = re.search(r"\bb\s*0[2z]a?\s*[-–]?\s*dn\b", header)
    heading = {"kinh", "doanh", "ket", "qua"}.issubset(re.findall(r"\w+", header))
    if not (split_statement or form_code or heading):
        return {}
    if period.startswith("FY"):
        columns = ((2, {"annual": 0}),)
    else:
        quarter = period[1]
        cumulative = re.search(r"\bluy\b|\b(sau|chin|muoi hai|0[69])\s+thang\b|\b0?1/0?1/20\d\d\b", header)
        columns = ((4, {"quy": 0, "luy_ke": 2}),) if cumulative or quarter == "1" else ()
        if quarter == "1" and company != "SBT":
            columns += ((2, {"quy": 0, "luy_ke": 0}),)
    for count, bases in columns:
        candidates = {code: row_candidates(boxes, code, count)
                      for code in ("10", "11", "20", "30", "40", "50", "51", "52", "60")}
        scope = statement_scope(header)
        rows = {}
        for basis, column in bases.items():
            options = {code: {row[column] for row in values} for code, values in candidates.items()}
            for metric, value in balanced_income(options).items():
                rows[metric, basis] = value, scope
        if rows:
            return rows
    return {}


def read_balance(pages):
    """Đối chiếu tổng tài sản với nợ và vốn trên cùng báo cáo."""
    cells = {code: {} for code in ("140", "141", "149", "270", "280", "300", "400", "440")}
    for page, boxes, scope in pages:
        for code, values in cells.items():
            for row in row_candidates(boxes, code, 2):
                values.setdefault(row, (page, scope))
    assets = cells["270"] | cells["280"]
    validated = {
        (asset, debt, equity) for asset, debt, equity in product(assets, cells["300"], cells["400"])
        if all(a == d + e for a, d, e in zip(asset, debt, equity, strict=True))
        and (not cells["440"] or asset in cells["440"])
    }
    if len(validated) != 1:
        return {}
    asset, debt, equity = validated.pop()
    rows = {
        "tong_tai_san": (asset, assets),
        "no_phai_tra": (debt, cells["300"]),
        "von_chu_so_huu": (equity, cells["400"]),
    }
    inventory = cells["140"].keys() & {
        tuple(a + b for a, b in zip(stock, reserve, strict=True))
        for stock, reserve in product(cells["141"], cells["149"] or {(0, 0)})
    }
    if len(inventory) == 1:
        rows["hang_ton_kho"] = (inventory.pop(), cells["140"])
    return {(metric, "point"): (values[0], *lookup[values])
            for metric, (values, lookup) in rows.items()}


def read_cash_flow(boxes, header, period, company, split_statement):
    if not (split_statement or "chuyen tien te" in header):
        return {}
    if period.startswith("FY"):
        bases = ("annual",)
    elif period.startswith("Q1") and company != "SBT":
        bases = ("quy", "luy_ke")
    elif re.search(r"\bluy\s+k\w+\b|\b(sau|chin|muoi hai)\s+thang\b|\b0?1/0?1/20\d\d\b", header):
        bases = ("luy_ke",)
    else:
        return {}
    codes = ("20", "30", "40", "50")
    candidates = [row_candidates(boxes, code, 2) for code in codes]
    flows = {
        (operating, investing, financing)
        for operating, investing, financing, total in product(*candidates)
        if all(a + b + c == d for a, b, c, d in zip(operating, investing, financing, total, strict=True))
    }
    if len(flows) != 1:
        return {}
    metrics = ("dong_tien_kinh_doanh", "dong_tien_dau_tu", "dong_tien_tai_chinh")
    scope = statement_scope(header)
    return {(metric, basis): (values[0], scope)
            for metric, values in zip(metrics, flows.pop(), strict=True) for basis in bases}
