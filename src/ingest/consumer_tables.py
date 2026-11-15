"""Đọc ba bảng chính của tám báo cáo mẫu theo vị trí cột và mã chỉ tiêu."""
import re
from statistics import median

# Ảnh PDF đánh số từ 1. Các trang thuyết minh bắt đầu sau ba bảng chính.
LAYOUTS = {
    ("MCM", "FY2025"): ((6, 7, 8), (9,), (10, 11)),
    ("MCM", "Q1/2026"): ((4, 5, 6), (7,), (8, 9)),
    ("MCM", "Q2/2026"): ((4, 5, 6), (7, 8), (9, 10)),
    ("MCM", "Q3/2026"): ((4, 5, 6), (7, 8), (9, 10)),
    ("QNS", "FY2025"): ((7, 8), (9,), (10,)),
    ("QNS", "Q1/2026"): ((2, 3), (4,), (5,)),
    ("QNS", "Q2/2026"): ((2, 3), (4,), (5,)),
    ("QNS", "Q3/2026"): ((2, 3), (4,), (5,)),
}
STATEMENTS = ("CDKT", "KQKD", "LCTT")
AMOUNT = re.compile(r"(?:\(?-?\d{1,3}(?:[.,]\d{3})+\)?|-?\d{1,3}|[–—-])$")


def codes(period):
    return (
        {"270" if period == "FY2025" else "280": "tong_tai_san", "300": "no_phai_tra",
         "400": "von_chu_so_huu", "140": "hang_ton_kho", "440": "_tong_nguon_von"},
        {"10": "doanh_thu_thuan", "20": "loi_nhuan_gop", "50": "loi_nhuan_truoc_thue",
         "60": "loi_nhuan_sau_thue", "11": "_gia_von"},
        {"20": "dong_tien_kinh_doanh", "30": "dong_tien_dau_tu", "40": "dong_tien_tai_chinh",
         "50": "_dong_tien_thuan"},
    )


def vertical(box):
    return (box[1] + box[3]) / 2


def amount(text):
    text = text.strip().replace(" ", "").replace("−", "-").replace("’", "")
    if not AMOUNT.fullmatch(text):
        return None
    digits = re.sub(r"\D", "", text)
    return int(digits or "0") * (-1 if text.startswith(("-", "(")) else 1)


def table_rows(boxes, mapping, count, code_width, tolerance=.008):
    digits = [b for b in boxes if re.fullmatch(r"\d{2,3}", b[4]) and code_width[0] < b[0] < code_width[1]]
    if not digits:
        return {}
    center = median(b[0] for b in digits)
    rows = {}
    for b in digits:
        if b[4] not in mapping or abs(b[0] - center) > .04:
            continue
        candidates = [x for x in boxes if x[0] > b[0] + .045 and amount(x[4]) is not None]
        other = [x for x in candidates if abs(vertical(x) - vertical(b)) < tolerance]
        if len(other) < count:
            # Some wrapped labels put the code on the first line and amounts on the second.
            other = [x for x in candidates if .005 < vertical(x) - vertical(b) < .022 and len(x[4]) >= 5]
        other.sort(key=lambda x: x[0])
        if len(other) < count:
            continue
        values = tuple(amount(x[4]) for x in other[-count:])
        if mapping[b[4]] in rows and rows[mapping[b[4]]] != values:
            raise ValueError(f"Mã {b[4]} xuất hiện nhiều lần")
        rows[mapping[b[4]]] = values
    return rows


def extract(company, period, pages):
    rows = {}
    for i, numbers in enumerate(LAYOUTS[(company, period)]):
        count = 4 if i == 1 and period != "FY2025" and (company == "QNS" or period != "Q1/2026") else 2
        if company == "MCM":
            income = (.29, .40) if count == 4 else (.45, .515)
            widths = ((.42, .51), income, (.49, .60))
        else:
            income = (.37, .48) if count == 4 else (.49, .58)
            widths = ((.48, .57), income, (.54, .64))
        mapping = codes(period)[i]
        for n in numbers:
            for key, values in table_rows(pages[n], mapping, count, widths[i]).items():
                rows[key] = (values, STATEMENTS[i], n)
    return rows
