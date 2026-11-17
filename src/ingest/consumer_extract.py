"""Trích chỉ tiêu từ trang PDF đã OCR theo NỘI DUNG (mã dòng và đẳng thức kế toán), không dựa vào tiêu đề trang.

Vì sao: OCR hay đọc sai tiêu đề ("tình hình tài chính" -> "tinh hinh tii chinh") nên bộ lọc theo tiêu đề bỏ sót cả bảng, trong khi số
trên bảng vẫn đọc tốt. Ở đây một bảng chỉ được nhận khi các con số tự thỏa đẳng thức của báo cáo, nên nhận nhầm gần như không thể:

- Cân đối kế toán: tổng tài sản = nợ phải trả + vốn chủ sở hữu ở CẢ HAI cột (cuối kỳ, đầu năm), và bằng tổng nguồn vốn nếu đọc được.
- Kết quả kinh doanh: doanh thu thuần - giá vốn = lợi nhuận gộp; (nếu có) lợi nhuận thuần + lợi nhuận khác = trước thuế; trước thuế - thuế = sau thuế.
- Lưu chuyển tiền tệ: dòng tiền kinh doanh + đầu tư + tài chính = lưu chuyển tiền thuần.

Chỉ ghi khi có đúng MỘT bộ số thỏa; nhiều bộ khác nhau (vd báo cáo riêng và hợp nhất cùng file) thì bỏ qua thay vì đoán.
Đơn vị: chỉ nhận số tính bằng đồng (loại bảng "nghìn đồng"/"triệu đồng") và tổng tài sản trong khoảng hợp lý.
"""
from __future__ import annotations

import re
from itertools import product
from statistics import median

from src.ingest.consumer_statements import AMOUNT_CHARS, page_header, row_candidates
from src.ingest.consumer_tables import amount, vertical

ASSET_RANGE = (5e10, 5e14)                       # tổng tài sản (đồng); ngoài khoảng này gần như chắc chắn sai đơn vị
SCALED_UNIT = ("nghin dong", "ngan dong", "trieu dong", "ty dong", "nghin vnd", "ngan vnd", "trieu vnd", "'000")


def near(word: str, target: str) -> bool:
    """`word` là `target` bị OCR đọc sai tối đa một ký tự (vd "hcp" ~ "hop")? Từ ngắn (< 3 ký tự) phải khớp tuyệt đối."""
    if word == target:
        return True
    if len(target) < 3 or abs(len(word) - len(target)) > 1:
        return False
    if len(word) == len(target):
        return sum(a != b for a, b in zip(word, target, strict=True)) <= 1
    longer, shorter = (word, target) if len(word) > len(target) else (target, word)
    return any(longer[:i] + longer[i + 1:] == shorter for i in range(len(longer)))


def has_phrase(header: str, phrase: str) -> bool:
    words, target = header.split(), phrase.split()
    return any(all(near(w, t) for w, t in zip(words[i:i + len(target)], target, strict=True))
               for i in range(len(words) - len(target) + 1))


def scope_of(header: str) -> str:
    """"hợp nhất" / "riêng" theo tiêu đề trang (so khớp mờ); không rõ thì "theo báo cáo" (cùng nghĩa với dữ liệu hiện có)."""
    consolidated, separate = has_phrase(header, "hop nhat"), has_phrase(header, "rieng")
    if consolidated and not separate:
        return "hợp nhất"
    if separate and not consolidated:
        return "riêng"
    return "theo báo cáo"


def scaled_units(header: str) -> bool:
    return any(token in header for token in SCALED_UNIT)

LOOSE_DIGITS = str.maketrans({"O": "0", "o": "0", "D": "0", "l": "1", "I": "1", "t": "1", "i": "1", "|": "1", "S": "5", "s": "5", "B": "8", "Z": "2", "z": "2"})


def row_digits(boxes: list, code: str) -> list:
    """Chuỗi chữ số (đã sửa các ký tự hay bị OCR lẫn vào số) của từng dòng có mã `code`, kể cả ô số bị hỏng không đọc được thành số."""
    out = []
    for anchor in boxes:
        if anchor[4].strip() != code or anchor[0] > .68:
            continue
        cells = sorted((b for b in boxes if b[0] >= max(.37, anchor[2] + .018) and -.007 <= vertical(b) - vertical(anchor) <= .019
                        and len(b[4].strip()) >= 4), key=lambda b: b[0])
        out.append(re.sub(r"\D", "", "".join(b[4].translate(LOOSE_DIGITS) for b in cells)))
    return out


def confirmed(boxes_by_page: dict, code: str, value: int, tolerance: int = 2) -> bool:
    """Số `value` (suy ra từ đẳng thức) có xuất hiện trong ô OCR hỏng của dòng `code` không (cùng độ dài, lệch tối đa `tolerance` chữ số)?"""
    target = str(abs(value))
    for boxes in boxes_by_page.values():
        for digits in row_digits(boxes, code):
            for i in range(len(digits) - len(target) + 1):
                if sum(a != b for a, b in zip(digits[i:i + len(target)], target, strict=True)) <= tolerance:
                    return True
    return False


def _cells(box: list) -> list:
    """(x, chuỗi số) của một ô OCR. OCR đôi khi gộp hai cột số của cùng dòng vào một ô ("15.041... 15.270..."): tách theo khoảng trắng,
    x của từng số nội suy theo vị trí ký tự trong ô. Ô một số giữ nguyên."""
    text = box[4].strip(" ;:|").translate(AMOUNT_CHARS)
    parts = [(m.start(), m.group()) for m in re.finditer(r"\S+", text)]
    if len(parts) < 2 or any(amount(p) is None or len(p) < 5 for _, p in parts):
        return [(box[0], text)]
    return [(box[0] + (box[2] - box[0]) * start / len(text), part) for start, part in parts]


def _row_numbers(boxes: list, code: str) -> list:
    """Các dòng có mã `code`: mỗi dòng là danh sách (x, giá trị) của các số cùng hàng, cột trái sang phải (cho phép thiếu số do OCR bỏ sót)."""
    rows = []
    for anchor in boxes:
        if anchor[4].strip() != code or anchor[0] > .68:
            continue
        numbers = []
        for box in boxes:
            if box[0] < max(.37, anchor[2] + .018) or not -.007 <= vertical(box) - vertical(anchor) <= .019:
                continue
            for x, cell in _cells(box):
                value = amount(cell)
                if value is not None and (len(cell) >= 5 or cell in {"-", "–", "—", "0"}):
                    numbers.append((x, vertical(box), value))
        for _, y, _ in numbers:
            row = sorted((x, value) for x, center, value in numbers if abs(center - y) < .005)
            if row and row not in rows:
                rows.append(row)
    return rows


def aligned_rows(boxes: list, codes: tuple, count: int) -> dict:
    """{mã: [các dòng, mỗi dòng là tuple `count` cột, ô OCR bỏ sót là None]}.

    Vị trí các cột lấy từ trung vị x của những dòng đọc đủ `count` số (cần ít nhất 3 dòng như vậy trên trang); số của dòng thiếu được gán
    vào cột gần nhất, và bỏ cả dòng nếu hai số rơi vào cùng một cột hoặc lệch quá nửa khoảng cách cột (tránh gán nhầm).
    """
    rows = {code: _row_numbers(boxes, code) for code in codes}
    full = [row for rs in rows.values() for row in rs if len(row) == count]
    if len(full) >= 3:
        centers = [median(row[i][0] for row in full) for i in range(count)]
    else:                                                      # ít dòng đủ số (OCR nhiễu cả hai cột): chia mọi số trên trang thành `count` cụm theo khoảng trống lớn nhất
        xs = sorted(x for rs in rows.values() for row in rs for x, _ in row)
        gaps = sorted(range(len(xs) - 1), key=lambda i: xs[i + 1] - xs[i], reverse=True)[:count - 1]
        if len(xs) < 2 * count or len(gaps) < count - 1:
            return {code: [tuple(v for _, v in row) for row in rs if len(row) == count] for code, rs in rows.items()}
        cuts = sorted(gaps)
        groups = [xs[a + 1:b + 1] for a, b in zip([-1, *cuts], [*cuts, len(xs) - 1])]
        centers = [median(g) for g in groups]
    if count > 1 and min(b - a for a, b in zip(centers, centers[1:])) < 0.05:
        return {code: [tuple(v for _, v in row) for row in rs if len(row) == count] for code, rs in rows.items()}      # cột quá sát nhau: không tin
    gap = min(b - a for a, b in zip(centers, centers[1:])) if count > 1 else 1
    out = {}
    for code, rs in rows.items():
        cleaned = []
        for row in rs:
            if len(row) == count:
                cleaned.append(tuple(v for _, v in row))
            elif 1 <= len(row) < count:
                slots = [None] * count
                for x, v in row:
                    k = min(range(count), key=lambda i: abs(centers[i] - x))
                    if abs(centers[k] - x) > gap / 2 or slots[k] is not None:
                        slots = None
                        break
                    slots[k] = v
                if slots:
                    cleaned.append(tuple(slots))
        out[code] = cleaned
    return out


def _balance(pages: dict) -> dict:
    """{(metric, 'point'): (giá trị cuối kỳ, trang, phạm vi, 'CDKT')}.

    Chỉ dùng cột cuối kỳ (cột đầu): tài sản = nợ phải trả + vốn chủ sở hữu, ba số 12-13 chữ số nên khớp tình cờ gần như không thể. Cột "đầu năm"
    hay bị OCR đọc nhiễu; dòng chỉ thiếu cột đó vẫn dùng được nhờ căn cột theo tọa độ (aligned_rows). Chỉ nhận khi đúng một giá trị tổng tài sản thỏa.
    """
    codes = ("140", "141", "149", "270", "280", "300", "400", "440")
    anchors = ("100", "110", "120", "130", "200", "210", "220", "230", "310", "330", "410", "411", "420", "421")      # chỉ để xác định vị trí hai cột
    cells = {code: {} for code in codes}
    for page, boxes in pages.items():
        if scaled_units(page_header(boxes)):
            continue
        for code, rows in aligned_rows(boxes, codes + anchors, 2).items():
            if code not in cells:
                continue
            for row in rows:
                if row[0] is not None:
                    cells[code].setdefault(row[0], page)
    assets = {**cells["270"], **cells["280"]}
    valid = {(a, d, e) for a, d, e in product(assets, cells["300"], cells["400"])
             if a == d + e and ASSET_RANGE[0] <= a <= ASSET_RANGE[1]}
    if not valid:                                               # một trong ba số bị OCR hỏng: suy ra từ hai số kia, chỉ nhận khi ô hỏng đối chứng khớp
        usable = {p: b for p, b in pages.items() if not scaled_units(page_header(b))}
        for a, d in product(assets, cells["300"]):
            e = a - d
            if ASSET_RANGE[0] <= a <= ASSET_RANGE[1] and 0 < e < a and not cells["400"] and confirmed(usable, "400", e):
                valid.add((a, d, e)); cells["400"][e] = assets[a]
        for a, e in product(assets, cells["400"]):
            d = a - e
            if ASSET_RANGE[0] <= a <= ASSET_RANGE[1] and 0 < d < a and not cells["300"] and confirmed(usable, "300", d):
                valid.add((a, d, e)); cells["300"][d] = assets[a]
        for d, e in product(cells["300"], cells["400"]):
            a = d + e
            if ASSET_RANGE[0] <= a <= ASSET_RANGE[1] and not assets and (confirmed(usable, "270", a) or confirmed(usable, "280", a)
                                                                         or confirmed(usable, "440", a)):
                valid.add((a, d, e)); assets[a] = cells["300"][d]
    if len({a for a, _, _ in valid}) != 1:                      # không có bộ nào, hoặc nhiều bộ khác nhau (vd riêng + hợp nhất): không đoán
        return {}
    a, d, e = next(iter(valid))
    totals = {v for v in cells["440"] if ASSET_RANGE[0] <= v <= ASSET_RANGE[1]}      # bỏ các số lạc (vd "0") khỏi phép so với tổng nguồn vốn
    if totals and a not in totals:                              # tổng nguồn vốn đã đọc được thì phải bằng tổng tài sản
        return {}
    pages_of = {"tong_tai_san": assets[a], "no_phai_tra": cells["300"][d], "von_chu_so_huu": cells["400"][e]}
    scope = scope_of(page_header(pages[assets[a]]))
    rows = {"tong_tai_san": a, "no_phai_tra": d, "von_chu_so_huu": e}
    if cells["149"]:                                           # tồn kho: chỉ nhận khi 140 = 141 + 149 đủ cả ba dòng (thiếu 149 từng làm lấy nhầm dòng 141)
        match = [v for v in cells["140"] if any(s_ + r_ == v for s_ in cells["141"] for r_ in cells["149"])]
        if len(match) == 1:
            rows["hang_ton_kho"], pages_of["hang_ton_kho"] = match[0], cells["140"][match[0]]
    return {(metric, "point"): (value, pages_of[metric], scope, "CDKT") for metric, value in rows.items()}


def balanced_income(candidates: dict) -> dict:
    """Doanh thu thuần / lợi nhuận gộp / trước thuế / sau thuế, mỗi giá trị chỉ nhận khi thỏa đẳng thức của chính báo cáo (một giá trị duy nhất).

    gộp: 10 - |11| = 20 · trước thuế: 30 + 40 = 50 · sau thuế: 50 -/+ (51 + 52) = 60, hoặc kiểm tra độc lập 61 + 62 = 60.
    """
    gross = {(revenue, profit) for revenue, cost, profit in product(candidates["10"], candidates["11"], candidates["20"])
             if revenue > 0 and cost != 0 and revenue - abs(cost) == profit}
    if len(gross) != 1:
        return {}
    revenue, gross_profit = gross.pop()
    rows = {"doanh_thu_thuan": revenue, "loi_nhuan_gop": gross_profit}
    pretax = {total for earnings, other, total in product(candidates["30"], candidates["40"], candidates["50"]) if earnings + other == total}
    if len(pretax) == 1:
        total = pretax.pop()
        rows["loi_nhuan_truoc_thue"] = total
        deferred = candidates["52"] or {0}
        after_tax = {net for current_tax, delayed_tax, net in product(candidates["51"], deferred, candidates["60"])
                     if total - (current_tax + delayed_tax) == net or total + (current_tax + delayed_tax) == net}
        if len(after_tax) == 1:
            rows["loi_nhuan_sau_thue"] = after_tax.pop()
    if "loi_nhuan_sau_thue" not in rows:                      # không có dòng thuế: dùng 61 + 62 = 60 (chủ sở hữu công ty mẹ + cổ đông không kiểm soát)
        split = {net for parent, minority, net in product(candidates["61"], candidates["62"], candidates["60"]) if parent + minority == net}
        if len(split) == 1:
            rows["loi_nhuan_sau_thue"] = split.pop()
    return rows


def _income(pages: dict, period: str, company: str) -> dict:
    """Kết quả kinh doanh. Bốn cột (quý này, quý trước, lũy kế này, lũy kế trước) cho cả riêng quý và lũy kế; hai cột chỉ rõ nghĩa ở Q1 và cả năm."""
    found = {}
    annual = period.startswith("FY")
    codes = ("10", "11", "20", "30", "40", "50", "51", "52", "60", "61", "62")
    for page, boxes in pages.items():
        header = page_header(boxes)
        if scaled_units(header):
            continue
        for count in (4, 2):
            if count == 2 and not (annual or period.startswith("Q1")):
                continue                                       # Q2-Q4 chỉ hai cột: không biết là riêng quý hay lũy kế
            candidates = aligned_rows(boxes, codes, count)
            if page + 1 in pages and not scaled_units(page_header(pages[page + 1])):          # báo cáo trải trên hai trang (vd 01-40 rồi 50-60)
                following = aligned_rows(pages[page + 1], codes, count)
                candidates = {code: candidates[code] + following[code] for code in codes}
            if annual:
                bases = {"annual": 0}
            elif count == 4:
                bases = {"quy": 0, "luy_ke": 2}
            else:
                bases = {"quy": 0, "luy_ke": 0}
            for basis, column in bases.items():
                options = {code: {row[column] for row in rows if row[column] is not None} for code, rows in candidates.items()}
                for metric, value in balanced_income(options).items():
                    found.setdefault((metric, basis), {})[value] = (page, scope_of(header))
    out = {}
    for (metric, basis), values in found.items():
        if len(values) == 1:                                   # nhiều giá trị khác nhau cho cùng một chỉ tiêu: bỏ qua
            (value, (page, scope)), = values.items()
            out[metric, basis] = (value, page, scope, "KQKD")
    return out


def _cash_flow(pages: dict, period: str, company: str) -> dict:
    """Lưu chuyển tiền tệ: báo cáo chỉ có số lũy kế (riêng quý chỉ có ở Q1)."""
    if period.startswith("FY"):
        bases = ("annual",)
    elif period.startswith("Q1") and company != "SBT":
        bases = ("quy", "luy_ke")
    else:
        bases = ("luy_ke",)
    found = {}
    for page, boxes in pages.items():
        header = page_header(boxes)
        if scaled_units(header):
            continue
        rows = [row_candidates(boxes, code, 2) for code in ("20", "30", "40", "50")]
        for operating, investing, financing, total in product(*rows):
            if all(a + b + c == d for a, b, c, d in zip(operating, investing, financing, total, strict=True)):
                found[(operating, investing, financing)] = (page, scope_of(header))
    if len(found) != 1:
        return {}
    (operating, investing, financing), (page, scope) = next(iter(found.items()))
    metrics = ("dong_tien_kinh_doanh", "dong_tien_dau_tu", "dong_tien_tai_chinh")
    return {(metric, basis): (values[0], page, scope, "LCTT")
            for metric, values in zip(metrics, (operating, investing, financing), strict=True) for basis in bases}


def extract_document(pages: dict, company: str, period: str) -> dict:
    """{(metric, basis): (giá trị, trang, phạm vi, báo cáo)} cho một tài liệu; `pages` = {số trang: các ô chữ OCR}."""
    rows = {}
    rows.update(_balance(pages))
    rows.update(_income(pages, period, company))
    rows.update(_cash_flow(pages, period, company))
    return rows
