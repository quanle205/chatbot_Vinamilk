"""
parse_statements.py  (v3) - tách 3 báo cáo chính (CĐKT, KQKD, LCTT) từ kết quả OCR.

Đầu vào : financial_rows.csv do preprocess_vinamilk_v2.py tạo ra (dùng cột doc, page, raw)
Đầu ra  : statements_long.csv  - mỗi dòng = 1 chỉ tiêu x 1 cột số liệu (định dạng "long", dễ chunk/embedding)
          validation_report.txt - kết quả kiểm tra đẳng thức kế toán + đối chiếu chéo giữa các quý
          unparsed_rows.csv     - các dòng có số nhưng không đọc được mã số (cần soát tay)

Ý tưởng chính (khác v2):
  1. Mã số nằm GIỮA dòng (nhãn  mã  thuyết-minh  số  số), không phải đầu dòng.
  2. Số cột tự suy ra (Q2/Q3 có 4 cột trong KQKD: quý này, quý trước, lũy kế này, lũy kế trước).
  3. Sửa lỗi OCR bằng ràng buộc kế toán (VD 270 = 100 + 200), chỉ sửa khi chênh lệch <= 2 ký tự
     so với chuỗi OCR gốc; luôn giữ lại giá trị OCR gốc để đối chiếu.
  4. Bỏ phiếu giữa các quý cho số dư đầu năm (cột 1/1/YYYY phải giống nhau ở Q1, Q2, Q3, Q4).

Chạy:  python parse_statements.py --csv financial_rows.csv --output ./data_clean
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from difflib import SequenceMatcher
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

# ------------------------------------------------------------------ nhãn chuẩn
# TT200 (BCTC 2025) và TT99/2025 (BCTC 2026) đánh mã khác nhau -> tách theo phiên bản.
LABELS_BS_200 = {
    "100": "Tài sản ngắn hạn", "110": "Tiền và các khoản tương đương tiền", "111": "Tiền",
    "112": "Các khoản tương đương tiền", "120": "Các khoản đầu tư tài chính ngắn hạn",
    "123": "Đầu tư nắm giữ đến ngày đáo hạn (ngắn hạn)", "130": "Các khoản phải thu ngắn hạn",
    "131": "Phải thu khách hàng", "132": "Trả trước cho người bán", "136": "Phải thu ngắn hạn khác",
    "137": "Dự phòng phải thu khó đòi", "140": "Hàng tồn kho", "141": "Hàng tồn kho",
    "149": "Dự phòng giảm giá hàng tồn kho", "150": "Tài sản ngắn hạn khác",
    "151": "Chi phí trả trước ngắn hạn", "152": "Thuế giá trị gia tăng được khấu trừ",
    "200": "Tài sản dài hạn", "210": "Các khoản phải thu dài hạn", "216": "Phải thu dài hạn khác",
    "220": "Tài sản cố định", "221": "Tài sản cố định hữu hình", "222": "TSCĐ hữu hình - Nguyên giá",
    "223": "TSCĐ hữu hình - Giá trị hao mòn lũy kế", "227": "Tài sản cố định vô hình",
    "228": "TSCĐ vô hình - Nguyên giá", "229": "TSCĐ vô hình - Giá trị hao mòn lũy kế",
    "230": "Bất động sản đầu tư", "231": "BĐS đầu tư - Nguyên giá",
    "232": "BĐS đầu tư - Giá trị hao mòn lũy kế", "240": "Tài sản dở dang dài hạn",
    "242": "Xây dựng cơ bản dở dang", "250": "Các khoản đầu tư tài chính dài hạn",
    "251": "Đầu tư vào các công ty con", "252": "Đầu tư vào các công ty liên doanh, liên kết",
    "253": "Đầu tư góp vốn vào các đơn vị khác", "254": "Dự phòng giảm giá đầu tư tài chính dài hạn",
    "255": "Đầu tư nắm giữ đến ngày đáo hạn (dài hạn)", "260": "Tài sản dài hạn khác",
    "261": "Chi phí trả trước dài hạn", "262": "Tài sản thuế thu nhập hoãn lại", "270": "TỔNG TÀI SẢN",
    "300": "NỢ PHẢI TRẢ", "310": "Nợ ngắn hạn", "311": "Phải trả người bán",
    "312": "Người mua trả tiền trước", "313": "Thuế phải nộp Ngân sách Nhà nước",
    "314": "Phải trả người lao động", "315": "Chi phí phải trả", "318": "Doanh thu chưa thực hiện ngắn hạn",
    "319": "Phải trả ngắn hạn khác", "320": "Vay ngắn hạn", "321": "Dự phòng phải trả ngắn hạn",
    "322": "Quỹ khen thưởng và phúc lợi", "330": "Nợ dài hạn", "337": "Phải trả dài hạn khác",
    "400": "VỐN CHỦ SỞ HỮU", "410": "Vốn chủ sở hữu", "411": "Vốn cổ phần", "412": "Thặng dư vốn cổ phần",
    "418": "Quỹ đầu tư phát triển", "421": "Lợi nhuận sau thuế chưa phân phối",
    "421a": "LNST chưa phân phối lũy kế đến cuối kỳ trước", "421b": "LNST chưa phân phối kỳ này",
    "440": "TỔNG NGUỒN VỐN",
    # BCTC hợp nhất
    "121": "Chứng khoán kinh doanh", "122": "Dự phòng giảm giá chứng khoán kinh doanh",
    "153": "Thuế phải thu Ngân sách Nhà nước", "211": "Phải thu dài hạn của khách hàng",
    "241": "Chi phí sản xuất kinh doanh dở dang dài hạn", "269": "Lợi thế thương mại",
    "338": "Vay dài hạn", "341": "Thuế thu nhập hoãn lại phải trả", "414": "Vốn khác của chủ sở hữu",
    "417": "Chênh lệch quy đổi tiền tệ", "429": "Lợi ích cổ đông không kiểm soát",
}
LABELS_BS_99 = {
    **{k: v for k, v in LABELS_BS_200.items() if k in {
        "100", "110", "111", "112", "120", "123", "130", "131", "132", "140", "141", "200", "210",
        "220", "221", "222", "223", "227", "228", "229", "300", "310", "311", "312", "330",
        "400", "411", "412", "440"}},
    "135": "Phải thu ngắn hạn khác", "136": "Dự phòng phải thu khó đòi",
    "142": "Dự phòng giảm giá hàng tồn kho", "160": "Tài sản ngắn hạn khác",
    "161": "Chi phí chờ phân bổ ngắn hạn", "162": "Thuế giá trị gia tăng được khấu trừ",
    "215": "Phải thu dài hạn khác", "240": "Bất động sản đầu tư", "241": "BĐS đầu tư - Nguyên giá",
    "242": "BĐS đầu tư - Giá trị hao mòn lũy kế", "250": "Tài sản dở dang dài hạn",
    "252": "Xây dựng cơ bản dở dang", "260": "Các khoản đầu tư tài chính dài hạn",
    "261": "Đầu tư vào các công ty con", "262": "Đầu tư vào các công ty liên doanh, liên kết",
    "263": "Đầu tư góp vốn vào các đơn vị khác", "264": "Dự phòng giảm giá đầu tư tài chính dài hạn",
    "265": "Đầu tư nắm giữ đến ngày đáo hạn (dài hạn)", "270": "Tài sản dài hạn khác",
    "271": "Chi phí chờ phân bổ dài hạn", "272": "Tài sản thuế thu nhập hoãn lại", "280": "TỔNG TÀI SẢN",
    "313": "Phải trả cổ tức", "314": "Thuế phải nộp Nhà nước", "315": "Phải trả người lao động",
    "316": "Chi phí phải trả", "319": "Doanh thu chờ phân bổ ngắn hạn", "320": "Phải trả ngắn hạn khác",
    "321": "Vay ngắn hạn", "322": "Dự phòng phải trả ngắn hạn", "323": "Quỹ khen thưởng và phúc lợi",
    "338": "Phải trả dài hạn khác", "420": "Lợi nhuận sau thuế chưa phân phối",
    "420a": "LNST chưa phân phối lũy kế đến cuối kỳ trước", "420b": "LNST chưa phân phối kỳ này",
    # BCTC hợp nhất (TT99 thêm nhóm tài sản sinh học 150/230)
    "121": "Chứng khoán kinh doanh", "122": "Dự phòng giảm giá chứng khoán kinh doanh",
    "150": "Tài sản sinh học ngắn hạn", "151": "Súc vật nuôi lấy sản phẩm một lần ngắn hạn",
    "152": "Cây trồng lấy sản phẩm một lần ngắn hạn", "163": "Thuế phải thu Nhà nước",
    "230": "Tài sản sinh học dài hạn", "231": "Súc vật nuôi cho sản phẩm định kỳ",
    "232": "Súc vật nuôi chưa đến giai đoạn trưởng thành", "233": "Súc vật nuôi đã đến giai đoạn trưởng thành",
    "234": "Súc vật nuôi trưởng thành - Nguyên giá", "235": "Súc vật nuôi trưởng thành - Giá trị hao mòn lũy kế",
    "237": "Súc vật nuôi lấy sản phẩm một lần dài hạn", "251": "Chi phí sản xuất kinh doanh dở dang dài hạn",
    "279": "Lợi thế thương mại", "339": "Vay dài hạn", "342": "Thuế thu nhập hoãn lại phải trả",
    "414": "Vốn khác của chủ sở hữu", "417": "Chênh lệch quy đổi tiền tệ", "418": "Quỹ đầu tư phát triển",
    "429": "Lợi ích cổ đông không kiểm soát",
}
LABELS_IS_200 = {
    "01": "Doanh thu bán hàng và cung cấp dịch vụ", "02": "Các khoản giảm trừ doanh thu",
    "10": "Doanh thu thuần về bán hàng và cung cấp dịch vụ", "11": "Giá vốn hàng bán và dịch vụ cung cấp",
    "20": "Lợi nhuận gộp về bán hàng và cung cấp dịch vụ", "21": "Doanh thu hoạt động tài chính",
    "22": "Chi phí tài chính", "23": "Trong đó: Chi phí lãi vay", "25": "Chi phí bán hàng",
    "26": "Chi phí quản lý doanh nghiệp", "30": "Lợi nhuận thuần từ hoạt động kinh doanh",
    "31": "Thu nhập khác", "32": "Chi phí khác", "40": "Kết quả từ hoạt động khác",
    "50": "Lợi nhuận kế toán trước thuế", "51": "Chi phí thuế TNDN hiện hành",
    "52": "Chi phí/(lợi ích) thuế TNDN hoãn lại", "60": "Lợi nhuận sau thuế TNDN",
    # BCTC hợp nhất
    "24": "Lãi chia từ công ty liên kết, liên doanh", "61": "Chủ sở hữu của Công ty",
    "62": "Lợi ích cổ đông không kiểm soát",
}
# TT99 đánh lại mã phần tài chính: 22/23/24 và lãi liên kết chuyển sang 27.
LABELS_IS_99 = {**{k: v for k, v in LABELS_IS_200.items() if k not in {"21", "24"}},
                "22": "Doanh thu hoạt động tài chính", "23": "Chi phí tài chính",
                "24": "Trong đó: Chi phí đi vay", "27": "Lãi chia từ công ty liên kết, liên doanh"}
LABELS_CF = {
    "01": "Lợi nhuận kế toán trước thuế", "02": "Khấu hao và phân bổ", "03": "Các khoản dự phòng",
    "04": "Lỗ/(lãi) chênh lệch tỷ giá do đánh giá lại các khoản mục tiền tệ có gốc ngoại tệ",
    "05": "Thu nhập từ cổ tức, lãi tiền gửi và lãi/lỗ từ hoạt động đầu tư khác", "06": "Chi phí lãi vay",
    "08": "Lợi nhuận từ hoạt động kinh doanh trước những thay đổi vốn lưu động",
    "09": "Biến động các khoản phải thu", "10": "Biến động hàng tồn kho",
    "11": "Biến động các khoản phải trả và nợ phải trả khác", "12": "Biến động chi phí trả trước",
    "14": "Tiền lãi vay đã trả", "15": "Thuế thu nhập doanh nghiệp đã nộp",
    "17": "Tiền chi khác cho hoạt động kinh doanh", "20": "Lưu chuyển tiền thuần từ hoạt động kinh doanh",
    "21": "Tiền chi mua tài sản cố định và tài sản dài hạn khác",
    "22": "Tiền thu từ thanh lý tài sản cố định và xây dựng cơ bản dở dang",
    "23": "Tiền chi gửi tiền có kỳ hạn", "24": "Tiền thu từ tiền gửi có kỳ hạn",
    "25": "Tiền chi đầu tư góp vốn vào công ty con", "26": "Tiền thu hồi đầu tư góp vốn vào đơn vị khác",
    "27": "Tiền thu lãi tiền gửi và cổ tức", "30": "Lưu chuyển tiền thuần từ hoạt động đầu tư",
    "33": "Tiền thu từ đi vay", "34": "Tiền chi trả nợ gốc vay", "36": "Tiền chi trả cổ tức",
    "40": "Lưu chuyển thuần từ hoạt động tài chính", "50": "Lưu chuyển tiền thuần trong kỳ",
    "60": "Tiền và các khoản tương đương tiền đầu kỳ",
    "61": "Ảnh hưởng của thay đổi tỷ giá hối đoái đối với tiền và các khoản tương đương tiền",
    "70": "Tiền và các khoản tương đương tiền cuối kỳ",
    "31": "Tiền chi mua thêm phần vốn góp của cổ đông không kiểm soát vào công ty con",
    "62": "Chênh lệch quy đổi tiền tệ",
    # BCTC hợp nhất in trùng mã 02/05 cho hai dòng điều chỉnh -> tách thành mã phụ.
    "02b": "Phân bổ lợi thế thương mại", "05b": "Lãi chia từ công ty liên kết, liên doanh",
}
# (báo cáo, mã) -> (mã phụ, từ khóa nhãn không dấu) cho các dòng trùng mã.
ALT_CODES = {("LCTT", "02"): ("02b", ("loi the thuong mai",)), ("LCTT", "05"): ("05b", ("lien ket", "lien doanh"))}
# Mã in đậm của LCTT hay bị OCR đọc sai: 30 -> 39, 40 -> 49 (39/49 không tồn tại trong LCTT).
BOLD_ALIAS = {("LCTT", "39"): "30", ("LCTT", "49"): "40"}


def fix_cf_codes(rs: list) -> None:
    """LCTT: dòng tổng có mã OCR hỏng hẳn ('sọ', '4g', 'gg'...) -> khôi phục theo nhãn và thứ tự.

    'Lưu chuyển tiền thuần từ hoạt động ...' lần lượt là 20, 30, 40; '... đầu kỳ' là 60.
    """
    labels = LABELS_CF
    seen = {r.code for r in rs if r.code in labels}
    for r in rs:
        if r.code in labels:
            continue
        lab = accent_free(r.label)
        if "chuyen" in lab and ("thuan" in lab or "dong" in lab) and "trong ky" not in lab:
            nxt = next((c for c in ("20", "30", "40") if c not in seen), None)
            if nxt:
                r.code = nxt
        elif ("dau ky" in lab or "tuong duong tien" in lab) and "60" not in seen:
            r.code = "60"
        if r.code in labels:
            seen.add(r.code)
            r.note = (r.note + '; ' if r.note else '') + 'CODE_FROM_ORDER'


def prefix_code(r, labels: dict) -> None:
    """CĐKT: mã 3 chữ số mất 1 chữ số cuối ('25' -> 255, '11' -> 111) -> chọn theo nhãn trong nhóm."""
    if r.code is None or r.code in labels or len(r.code) != 2:
        return
    cands = [c for c in labels if len(c) == 3 and c.startswith(r.code)]
    scored = sorted(((label_similarity(r.label, labels[c]), c) for c in cands), reverse=True)
    if scored and scored[0][0] >= 0.5 and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.06):
        r.code = scored[0][1]
        r.note = (r.note + '; ' if r.note else '') + 'CODE_FROM_PREFIX'


def labels_for(version: str, stmt: str) -> dict:
    if stmt == "CDKT":
        return LABELS_BS_99 if version == "TT99" else LABELS_BS_200
    if stmt == "KQKD":
        return LABELS_IS_99 if version == "TT99" else LABELS_IS_200
    return LABELS_CF


# ------------------------------------------------------------------ đẳng thức kế toán
# parent = Σ sign * child ; chỉ dùng các child thực sự xuất hiện trong báo cáo.
def _p(parent, *children):
    return parent, [(c[1:], -1) if c.startswith("-") else (c, 1) for c in children]


EQ = {
    ("TT200", "CDKT"): [
        _p("100", "110", "120", "130", "140", "150"), _p("110", "111", "112"),
        _p("120", "121", "122", "123"), _p("130", "131", "132", "133", "134", "135", "136", "137"),
        _p("140", "141", "149"), _p("150", "151", "152", "153"),
        _p("200", "210", "220", "230", "240", "250", "260"), _p("210", "211", "216"),
        _p("220", "221", "227"), _p("221", "222", "223"), _p("227", "228", "229"),
        _p("230", "231", "232"), _p("240", "241", "242"),
        _p("250", "251", "252", "253", "254", "255"), _p("260", "261", "262", "269"),
        _p("270", "100", "200"), _p("300", "310", "330"),
        _p("310", "311", "312", "313", "314", "315", "318", "319", "320", "321", "322"),
        _p("330", "337", "338", "341"), _p("400", "410"),
        _p("410", "411", "412", "414", "417", "418", "421", "429"),
        _p("421", "421a", "421b"), _p("440", "300", "400"), _p("270", "440"),
    ],
    ("TT99", "CDKT"): [
        _p("100", "110", "120", "130", "140", "150", "160"), _p("110", "111", "112"),
        _p("120", "121", "122", "123"),
        _p("130", "131", "132", "135", "136"), _p("140", "141", "142"), _p("150", "151", "152"),
        _p("160", "161", "162", "163"),
        _p("200", "210", "220", "230", "240", "250", "260", "270"), _p("210", "215"),
        _p("220", "221", "227"), _p("221", "222", "223"), _p("227", "228", "229"),
        _p("230", "231", "237"), _p("231", "232", "233"), _p("233", "234", "235"),
        _p("240", "241", "242"), _p("250", "251", "252"),
        _p("260", "261", "262", "263", "264", "265"), _p("270", "271", "272", "279"),
        _p("280", "100", "200"), _p("300", "310", "330"),
        _p("310", "311", "312", "313", "314", "315", "316", "319", "320", "321", "322", "323"),
        _p("330", "338", "339", "342"), _p("400", "411", "412", "414", "417", "418", "420", "429"),
        _p("420", "420a", "420b"),
        _p("440", "300", "400"), _p("280", "440"),
    ],
}
_IS = [_p("10", "01", "-02"), _p("20", "10", "-11"), _p("40", "31", "-32"), _p("50", "30", "40"),
       _p("60", "50", "-51", "-52"), _p("60", "61", "62")]
EQ[("TT200", "KQKD")] = _IS + [_p("30", "20", "21", "-22", "24", "-25", "-26")]
EQ[("TT99", "KQKD")] = _IS + [_p("30", "20", "22", "-23", "-25", "-26", "27")]
_CF = [_p("08", "01", "02", "02b", "03", "04", "05", "05b", "06"),
       _p("20", "08", "09", "10", "11", "12", "14", "15", "17"),
       _p("30", "21", "22", "23", "24", "25", "26", "27"), _p("40", "31", "33", "34", "36"),
       _p("50", "20", "30", "40"), _p("70", "50", "60", "61", "62")]
EQ[("TT200", "LCTT")] = _CF
EQ[("TT99", "LCTT")] = _CF


def version_of(year: int) -> str:
    return "TT99" if year >= 2026 else "TT200"


# ------------------------------------------------------------------ làm sạch số OCR
CONFUSE = {"!": "1", "I": "1", "l": "1", "|": "1", "O": "0", "o": "0", "$": "5", "S": "5",
           "B": "8", "Q": "0", "§": "?", "ã": "?"}
MONEY_CHARS = re.compile(r"[0-9!ILloOoSBQ$§ãQ|.,/\\]+")
CODE_RE = re.compile(r"(?=.*\d)[0-9IlOo!|Q]{2,3}[ab]?")   # '1Q' -> 10
NOTE_RE = re.compile(r"^[Vv][\w.()\[\]§]{0,10}$")
STRIP = "()[]{}|;:_—–=¿\"“”'`"


def norm_digits(tok: str) -> str:
    return "".join(CONFUSE.get(ch, ch) for ch in tok if ch.isalnum() or ch in "§$!|")


@dataclass
class Val:
    raw: str                    # chuỗi OCR gốc
    digits: str                 # chữ số sau khi sửa ký tự dễ nhầm ('?' = chữ số không đọc được)
    neg: bool
    value: int | None
    status: str = "OCR"         # OCR | REPAIRED_IDENTITY | REPAIRED_VOTE
    ocr_value: int | None = None

    def set(self, v: int, status: str):
        if self.ocr_value is None:
            self.ocr_value = self.value
        self.value, self.status = v, status


def make_val(raw: str, neg: bool) -> Val:
    d = norm_digits(raw.strip(STRIP + "-"))
    d = re.sub(r"[^0-9?]", "", d)
    v = None if (not d or "?" in d) else (-int(d) if neg else int(d))
    return Val(raw=raw, digits=d, neg=neg, value=v)


def as_money(tok: str):
    t = tok.strip()
    neg = t.startswith("(")
    # Gạch đầu cột dính vào số ('-53.312...') và ngoặc rác giữa chữ số ('221.0(02') là nhiễu OCR.
    core = re.sub(r"(?<=[0-9.])[()](?=[0-9])", "", t.lstrip("-–—").strip(STRIP))
    if not core or not MONEY_CHARS.fullmatch(core):
        return None
    # OCR hay đọc dấu chấm phân cách hàng nghìn thành '/'. Chỉ chuẩn hóa
    # khi dấu này nằm giữa các ký tự số/OCR-number; không dùng cho token văn bản.
    core = re.sub(r"(?<=[0-9])[/\\](?=[0-9])", ".", core)
    d = norm_digits(core)
    if len(re.sub(r"[^0-9?]", "", d)) < 5:
        return None
    return core, neg


GROUP_OK = re.compile(r"^\d{1,3}([.,]\d{3})*$")


def tokenize(line: str) -> list[str]:
    s = unicodedata.normalize("NFC", line)
    s = re.sub(r"(?<=\d)\s+(?=[.,]\d)", "", s)       # '4.053 .810' -> '4.053.810'
    s = re.sub(r"(?<=[.,])\s+(?=\d)", "", s)          # '650. 768'  -> '650.768'
    toks, raw = [], s.split()
    i = 0
    while i < len(raw):
        t = raw[i]
        if t.startswith("(") and not re.search(r"[)}\]]$", t):  # '(149.164.963 486)' -> 1 token
            j = i + 1
            while j < len(raw) and j <= i + 2 and not re.search(r"[)}\]]$", raw[j - 1]):
                t += raw[j]
                j += 1
            i = j
        else:
            i += 1
        toks.append(t)
    return toks


def accent_free(s: str) -> str:
    s = unicodedata.normalize("NFD", s.replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower()


@dataclass
class Row:
    doc: str
    page: int
    code: str | None
    label: str
    items: list = field(default_factory=list)   # Val hoặc None (dấu '-' = 0)
    raw: str = ""
    stmt: str = ""
    note: str = ""


def parse_line(line: str, doc: str, page: int) -> Row | None:
    toks = tokenize(line)
    first_money = next((i for i, t in enumerate(toks) if as_money(t)), None)
    if first_money is None:
        return None

    # Mã số thường đứng ngay trước cột tiền, nhưng OCR có thể chèn mã thuyết minh
    # (V.1, V.14...) hoặc ký tự rác vào giữa. Tìm ngược tối đa 4 token.
    code = None
    note = ""
    code_idx = None
    for k in range(first_money - 1, max(-1, first_money - 5), -1):
        t = toks[k]
        if NOTE_RE.match(t) or t in {"-", "–", "—", "=", "_", ";", ".", ","}:
            continue
        t = t.strip(",.;:|[](){}'\"")             # ',320' '11]' '122.' 'l4)'
        if CODE_RE.fullmatch(t):
            code = norm_digits(t).lower().replace("?", "")
            code_idx = k
            break
        m = re.fullmatch(r"42([01ïil|])([a6bï])", t)  # '4216', '42ïb' -> 421b
        if m:
            code = "42" + ("0" if m.group(1) == "0" else "1") + ("a" if m.group(2) == "a" else "b")
            code_idx = k
            break

    # Nếu mã không nằm riêng một token, thử công thức trong nhãn.
    if code is None:
        m = re.search(r"\((\d{1,3}[ab]?)\s*=", line)
        if m:
            code = m.group(1)

    label_end = code_idx if code_idx is not None else first_money
    label = re.sub(r"\s+", " ", " ".join(toks[:label_end])).strip(" .:-;|")

    # Lấy toàn bộ money tokens sau vùng nhãn; dấu '-' chỉ là placeholder cột.
    items = []
    start_items = code_idx + 1 if code_idx is not None else first_money
    for t in toks[start_items:]:
        mm = as_money(t)
        if mm:
            items.append(make_val(*mm))
        elif t in {"-", "–", "—"} and len(items) < 4:
            items.append(None)

    return Row(doc=doc, page=page, code=code, label=label, items=items, raw=line.strip(), note=note)


def label_similarity(a: str, b: str) -> float:
    a, b = accent_free(a), accent_free(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def infer_code_from_label(r: Row, labels: dict, threshold: float = 0.68):
    """Khôi phục mã khi OCR làm mất mã nhưng nhãn vẫn đủ rõ.

    Chỉ nhận khi có đúng một ứng viên tốt và khoảng cách với ứng viên thứ hai
    đủ lớn; không đoán khi hai mã có thể cùng phù hợp.
    """
    if not r.label:
        return
    scored = sorted(
        ((label_similarity(r.label, lab), code) for code, lab in labels.items()),
        reverse=True,
    )
    if not scored or scored[0][0] < threshold:
        return
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.06:
        return
    r.code = scored[0][1]
    r.note = (r.note + '; ' if r.note else '') + 'CODE_FROM_LABEL'

def normalize_items(items: list, n_cols: int) -> list:
    """Chuẩn hóa cột sau OCR mà không ghép bừa các số hợp lệ.

    Nếu đã có đúng n_cols số tiền thì bỏ toàn bộ dấu '-' chen giữa chúng
    (OCR thường đọc đường kẻ/bộ phân cách thành em-dash). Chỉ giữ None khi
    thực sự thiếu số. Điều này ngăn lỗi kiểu 3.290T + 5.967T bị ghép thành
    một số 3.29e25.
    """
    vals = [v for v in items if v is not None]
    if len(vals) == n_cols:
        return vals

    items = list(items)
    while len(items) > n_cols:
        # Ưu tiên bỏ dấu '-' / None dư trước, vì đây thường là separator OCR.
        none_idx = next((i for i, v in enumerate(items) if v is None), None)
        if none_idx is not None:
            items.pop(none_idx)
            continue
        # Chỉ ghép mảnh nếu một token thực sự có định dạng nhóm số lỗi.
        merged = False
        for i in range(len(items) - 1):
            a, b = items[i], items[i + 1]
            if a and b and not GROUP_OK.match(a.raw.strip(STRIP)):
                d = a.digits + b.digits
                if len(d) <= 16:
                    items[i:i + 2] = [Val(raw=a.raw + b.raw, digits=d, neg=a.neg,
                                          value=(-int(d) if a.neg else int(d)) if "?" not in d else None)]
                    merged = True
                    break
        if not merged:
            break
    return items


def merge_surplus(items: list, n_cols: int) -> list:
    # Giữ tên hàm để tương thích; logic mới an toàn hơn.
    return normalize_items(items, n_cols)


# ------------------------------------------------------------------ phân đoạn báo cáo
def find_section_pages(parsed: list[Row], version: str):
    """Tìm trang bắt đầu KQKD/LCTT bằng cả mã và nhãn, thay vì mã đơn lẻ.

    Đây là điểm sửa quan trọng của v6: mã 40/41 xuất hiện trong CĐKT nhưng
    không được phép làm parser nhảy sang KQKD.
    """
    bs_labels = labels_for(version, "CDKT")
    kq_labels = labels_for(version, "KQKD")
    cf_labels = labels_for(version, "LCTT")
    pages = defaultdict(list)
    for r in parsed:
        pages[r.page].append(r)

    def page_score(rs, labels, cf=False):
        score = 0.0
        hits = 0
        for r in rs:
            best = max((label_similarity(r.label, lab) for lab in labels.values()), default=0)
            code_hit = r.code in labels
            if code_hit and best >= 0.45:
                score += 2.0 + best
                hits += 1
            elif best >= 0.72:
                score += 1.0 + best
                hits += 1
        return score, hits

    ordered = sorted(pages)
    bs_candidates = []
    kq_candidates = []
    cf_candidates = []
    # Mã chỉ xuất hiện đặc trưng ở LCTT; tránh nhầm trang KQKD vì mã 50/60
    # cũng có nhãn "Lợi nhuận kế toán...".
    cf_distinct = {"03", "04", "05", "06", "08", "09", "12", "14", "15", "17",
                   "24", "27", "33", "34", "36", "61", "70"}
    for pg in ordered:
        sb, hb = page_score(pages[pg], bs_labels)
        sq, hq = page_score(pages[pg], kq_labels)
        sc, hc = page_score(pages[pg], cf_labels, cf=True)
        distinct_hits = sum(1 for r in pages[pg] if r.code in cf_distinct)
        distinct_label_hits = sum(1 for r in pages[pg]
                                  if max((label_similarity(r.label, cf_labels[c]) for c in cf_distinct), default=0) >= 0.68)
        if hb >= 3 and sb >= 6.0:
            bs_candidates.append((pg, sb, hb))
        if hq >= 2 and sq >= 4.0:
            kq_candidates.append((pg, sq, hq))
        if distinct_hits >= 2 or distinct_label_hits >= 2:
            cf_candidates.append((pg, sc, hc))

    bs_page = min((x[0] for x in bs_candidates), default=None)
    kq_page = min((x[0] for x in kq_candidates if bs_page is None or x[0] > bs_page), default=None)
    cf_page = min((x[0] for x in cf_candidates if kq_page is None or x[0] > kq_page), default=None)

    # Tìm trang cuối của LCTT trong tối đa 3 trang liên tiếp. Sau đó thường là
    # phần Thuyết minh; tuyệt đối không đẩy toàn bộ 40+ trang Thuyết minh vào LCTT.
    cf_end = None
    if cf_page is not None:
        for pg in ordered:
            if pg < cf_page or pg > cf_page + 2:
                continue
            sq, hq = page_score(pages[pg], cf_labels, cf=True)
            has_cf_code = any(r.code in cf_labels for r in pages[pg])
            has_cf_label = any(max((label_similarity(r.label, lab) for lab in cf_labels.values()), default=0) >= 0.60 for r in pages[pg])
            if hq >= 1 or has_cf_code or has_cf_label:
                cf_end = pg
    if cf_end is None:
        cf_end = cf_page
    return bs_page, kq_page, cf_page, cf_end


def segment(rows: list[Row], version: str) -> list[Row]:
    """Phân đoạn theo trang + nhãn/mã.

    CĐKT -> trang bắt đầu KQKD -> trang bắt đầu LCTT. Không dùng mã 40/41
    để chuyển section vì các mã này cũng xuất hiện trong CĐKT.
    """
    if not rows:
        return []
    bs_page, kq_page, cf_page, cf_end = find_section_pages(rows, version)
    out = []
    for r in rows:
        if bs_page is None or r.page < bs_page:
            continue
        if kq_page is None or r.page < kq_page:
            r.stmt = "CDKT"
        elif cf_page is None or r.page < cf_page:
            r.stmt = "KQKD"
        elif r.page <= cf_end:
            r.stmt = "LCTT"
        else:
            # Sau LCTT là Thuyết minh; không đưa các mã/số trong thuyết minh
            # vào ba báo cáo chính.
            continue
        out.append(r)
    return out

def snap_code(r: Row, known: set[str]):
    """Mã OCR sai 1 ký tự (vd '64' thay vì '60', '0' hay 'm1')."""
    if r.code in known or r.code is None:
        return
    cands = [c for c in known if len(c) == len(r.code) and sum(a != b for a, b in zip(c, r.code)) == 1]
    if len(cands) == 1:
        r.code = cands[0]


# ------------------------------------------------------------------ sửa lỗi bằng đẳng thức
def edit_distance(a: str, b: str) -> int:
    """Levenshtein, '?' khớp với mọi chữ số."""
    dp = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        prev, dp[0] = dp[0], i
        for j in range(1, len(b) + 1):
            cur = dp[j]
            cost = 0 if (a[i - 1] == b[j - 1] or "?" in (a[i - 1], b[j - 1])) else 1
            dp[j] = min(dp[j] + 1, dp[j - 1] + 1, prev + cost)
            prev = cur
    return dp[len(b)]


def residual(eq, vals: dict, c: int):
    """Tính residual chỉ khi *đủ toàn bộ* thành phần của phương trình.

    V6 có một lỗi quan trọng: nếu một child không tồn tại trong báo cáo, hàm
    vẫn tính phương trình với các child còn lại. Điều này biến phương trình
    thiếu dữ liệu thành mismatch giả (ví dụ LCTT.70 khi thiếu 50/60).
    V7 coi trường hợp đó là INCOMPLETE_EQUATION và không dùng để sửa/đánh lỗi.
    """
    parent, children = eq
    mem = [parent] + [ch for ch, _ in children]
    got = {}
    for m in mem:
        if m not in vals or c >= len(vals[m]):
            return None
        v = vals[m][c]
        if v is None or v.value is None:
            return None
        got[m] = v.value
    return got[parent] - sum(s * got[ch] for ch, s in children)


def failing(eqs, vals, ncols):
    return [(i, c) for i, eq in enumerate(eqs) for c in range(ncols)
            if (r := residual(eq, vals, c)) not in (None, 0)]


def repair_identity(eqs, vals: dict, ncols: int):
    """Sửa theo đẳng thức nhưng chỉ commit khi có đúng một ứng viên tốt nhất.

    Tránh trường hợp nhiều biến cùng có thể được chỉnh để làm phép toán đúng;
    khi đó giữ nguyên OCR và để validation report cảnh báo.
    """
    changed = 0
    for _ in range(12):
        fails = failing(eqs, vals, ncols)
        if not fails:
            break
        candidates = []
        for i, c in fails:
            eq = eqs[i]
            R = residual(eq, vals, c)
            parent, children = eq
            signs = {parent: 1, **{ch: -s for ch, s in children}}
            for m, sgn in signs.items():
                if m not in vals or c >= len(vals[m]) or vals[m][c] is None:
                    continue
                v = vals[m][c]
                if sgn == 0 or R % sgn:
                    continue
                new = v.value - R // sgn if v.value is not None else None
                if new is None:
                    known = sum(signs[x] * vals[x][c].value for x in signs
                                if x != m and x in vals and c < len(vals[x]) and vals[x][c] and vals[x][c].value is not None)
                    new = -known // sgn
                if edit_distance(str(abs(new)), v.digits) > 2:
                    continue
                old = v.value
                v.value = new
                n_fail = len(failing(eqs, vals, ncols))
                v.value = old
                candidates.append((n_fail, i, c, m, new))

        if not candidates:
            break
        best_fail = min(x[0] for x in candidates)
        best = [x for x in candidates if x[0] == best_fail]
        # Chỉ sửa khi duy nhất một biến là ứng viên tốt nhất.
        unique_targets = {(x[2], x[3], x[4]) for x in best}
        if len(unique_targets) != 1 or best_fail >= len(fails):
            break
        _, _, c, m, new = best[0]
        vals[m][c].set(new, "REPAIRED_IDENTITY")
        changed += 1
    return changed


# ------------------------------------------------------------------ V7 audit helpers
# V7 giữ nguyên pipeline V6 nhưng làm validation bảo thủ hơn: không tính phương
# trình thiếu thành phần, và tách mismatch nhỏ do OCR khỏi mismatch cần xem tay.

# ------------------------------------------------------------------ chính
def build(df: pd.DataFrame):
    all_rows, unparsed = [], []
    meta = {}
    for doc, g in df.groupby("doc", sort=True):
        q, y = doc.split("-")
        year, ver = int(y), version_of(int(y))
        parsed = []
        for _, rr in g.sort_values("page", kind="stable").iterrows():
            r = parse_line(str(rr.raw), doc, int(rr.page))
            if r:
                parsed.append(r)
        stmt_rows = segment(parsed, ver)
        for stmt in ("CDKT", "KQKD", "LCTT"):
            rs = [r for r in stmt_rows if r.stmt == stmt]
            labels = labels_for(ver, stmt)
            known = set(labels)
            for r in rs:
                r.code = BOLD_ALIAS.get((stmt, r.code), r.code)
                if stmt == "CDKT":
                    prefix_code(r, labels)
                # Nếu mã OCR không thuộc section, dùng nhãn để khôi phục trước.
                if r.code not in known:
                    infer_code_from_label(r, labels)
                snap_code(r, known)
                # Sau snap, nếu vẫn bất thường, thử nhãn lần cuối.
                if r.code not in known:
                    infer_code_from_label(r, labels)
                alt = ALT_CODES.get((stmt, r.code))
                if alt and any(k in accent_free(r.label) for k in alt[1]):
                    r.code = alt[0]
            if stmt == "LCTT":
                fix_cf_codes(rs)
            counts = Counter(len(r.items) for r in rs if r.code)
            # Chỉ coi 2/4 là cấu hình hợp lệ. Không để một vài dòng lỗi
            # làm kéo cả statement từ 4 cột xuống 2 cột.
            c2, c4 = counts.get(2, 0), counts.get(4, 0)
            total_valid_shape = c2 + c4
            if total_valid_shape == 0:
                n_cols, col_conf = 2, 0.0
            elif c4 > c2:
                n_cols, col_conf = 4, c4 / total_valid_shape
            else:
                n_cols, col_conf = 2, c2 / total_valid_shape
            column_uncertain = col_conf < 0.60 or (c2 and c4 and min(c2, c4) / max(c2, c4) >= 0.50)
            if column_uncertain:
                # Giữ lựa chọn phổ biến nhất để không phá pipeline, nhưng ghi rõ cảnh báo.
                for r in rs:
                    if r.code:
                        r.note = (r.note + '; ' if r.note else '') + f'COLUMN_COUNT_UNCERTAIN:{n_cols}({col_conf:.0%})'
            for r in rs:
                r.items = merge_surplus(r.items, n_cols)
                # Số >16 chữ số gần như chắc chắn là ghép nhầm cột/OCR, không cho
                # đi thẳng vào dataset cuối. Giữ raw để soát tay.
                if any(v is not None and v.value is not None and len(str(abs(v.value))) > 16 for v in r.items):
                    r.note = (r.note + '; ' if r.note else '') + 'SUSPICIOUS_HUGE_NUMBER'
                    unparsed.append(dict(doc=doc, stmt=stmt, page=r.page, code=r.code,
                                         n_values=len(r.items), expected=n_cols, raw=r.raw))
                    continue
                nonempty_values = sum(v is not None for v in r.items)
                headerish = any(k in accent_free(r.label) for k in ("ma thuyet", "ban hanh theo thong tu", "ngay thang nam"))
                if (r.code is not None or nonempty_values >= 1) and not headerish and len(r.items) != n_cols:
                    unparsed.append(dict(doc=doc, stmt=stmt, page=r.page, code=r.code,
                                         n_values=len(r.items), expected=n_cols, raw=r.raw))
            meta[(doc, stmt)] = dict(n_cols=n_cols, col_conf=col_conf, column_uncertain=column_uncertain, version=ver, year=year, quarter=q.upper())
            all_rows += [r for r in rs if r.code and len(r.items) == n_cols and "SUSPICIOUS_HUGE_NUMBER" not in r.note]
    return all_rows, meta, unparsed


def derive_missing(key, vals: dict, row_of: dict, meta_row: dict) -> list[str]:
    """Dòng chỉ tiêu cha bị OCR hỏng hẳn (vd mã '1Q', 'lọ') -> tính lại từ đẳng thức.

    Chỉ tính khi đủ mọi dòng con và mọi cột đều có số; đánh dấu DERIVED để
    repair/soát tay biết đây không phải số đọc từ PDF.
    """
    msgs, n = [], meta_row["n_cols"]
    labels = labels_for(meta_row["version"], key[1])
    changed = True
    while changed:
        changed = False
        for parent, children in EQ[(meta_row["version"], key[1])]:
            if parent in vals or not all(
                    ch in vals and len(vals[ch]) == n and all(v is not None and v.value is not None for v in vals[ch])
                    for ch, _ in children):
                continue
            out = [sum(s * vals[ch][c].value for ch, s in children) for c in range(n)]
            vals[parent] = [Val(raw="", digits=str(abs(x)), neg=x < 0, value=x, status="DERIVED") for x in out]
            first = row_of[(key, children[0][0])]
            row_of[(key, parent)] = Row(doc=key[0], page=first.page, code=parent, label=labels.get(parent, parent),
                                        raw=f"DERIVED {parent} = " + " ".join(('+' if s > 0 else '-') + ch for ch, s in children),
                                        stmt=key[1])
            msgs.append(f"  [{key[0]} {key[1]}] tính {parent} = {' '.join(('+' if s > 0 else '-') + ch for ch, s in children)}: "
                        + ", ".join(f"{x:,}" for x in out))
            changed = True
    return msgs


def vote_bs_opening(by_doc: dict, meta: dict) -> list[str]:
    """Số dư đầu năm (cột 2 của CĐKT) phải giống nhau ở mọi quý cùng năm."""
    msgs = []
    by_year = defaultdict(list)
    for (doc, stmt), vals in by_doc.items():
        if stmt == "CDKT":
            by_year[meta[(doc, stmt)]["year"]].append((doc, vals))
    for year, docs in by_year.items():
        if len(docs) < 3:
            continue
        codes = set().union(*[set(v) for _, v in docs])
        for code in sorted(codes):
            cur = [(d, v[code][1]) for d, v in docs if code in v and len(v[code]) > 1 and v[code][1] and v[code][1].value is not None]
            if len(cur) < 3:
                continue
            top, n = Counter(x.value for _, x in cur).most_common(1)[0]
            # Chỉ tự động sửa khi có đồng thuận mạnh. 2/4 không phải đa số đủ an toàn.
            if n < 3:
                continue
            for d, x in cur:
                if x.value != top and edit_distance(str(abs(top)), x.digits) <= 3:
                    x.set(top, "REPAIRED_VOTE")
                    msgs.append(f"  [{d}] mã {code} số dư đầu năm {x.ocr_value:,} -> {top:,} (đa số {n}/{len(cur)} quý)")
    return msgs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="financial_rows.csv")
    ap.add_argument("--pages-dir", default=None,
                    help="Đọc thẳng mọi dòng OCR từ q*-*.jsonl (không qua bộ lọc nhãn của preprocess)")
    ap.add_argument("--output", default="./data_clean")
    a = ap.parse_args()
    out = Path(a.output)
    out.mkdir(parents=True, exist_ok=True)
    if a.pages_dir:
        df = pd.DataFrame([dict(doc=r["doc"], page=r["page"], raw=line)
                           for f in sorted(Path(a.pages_dir).glob("q*-*.jsonl"))
                           for r in map(json.loads, f.read_text(encoding="utf-8").splitlines())
                           for line in r["text"].splitlines() if line.strip()])
    else:
        df = pd.read_csv(a.csv, encoding="utf-8-sig")

    rows, meta, unparsed = build(df)

    # Gom theo mã nhưng không mù quáng giữ dòng đầu tiên. Khi OCR tạo duplicate,
    # chọn ứng viên có label chuẩn, đủ cột và ít ký tự nghi ngờ hơn; nếu vẫn hòa
    # thì giữ dòng đầu để bảo toàn tính ổn định.
    by_doc: dict = defaultdict(dict)
    row_of: dict = {}

    def row_score(r, meta_row):
        lab_ok = accent_free(r.label) == accent_free(labels_for(meta_row["version"], r.stmt).get(r.code, ""))
        enough = len(r.items) == meta_row["n_cols"]
        suspicious = sum(1 for v in r.items if v is not None and ("?" in v.digits or v.value is None))
        # Ưu tiên số có dấu phân nhóm hợp lệ; giảm mạnh điểm cho số quá dài.
        grouped = sum(1 for v in r.items if v is not None and GROUP_OK.match(v.raw.strip(STRIP)))
        huge = sum(1 for v in r.items if v is not None and v.value is not None and len(str(abs(v.value))) > 16)
        return (int(lab_ok), int(enough), grouped, -huge, -suspicious, -r.page)

    for r in rows:
        key = (r.doc, r.stmt)
        m = meta[key]
        if r.code not in by_doc[key] or row_score(r, m) > row_score(row_of[(key, r.code)], m):
            by_doc[key][r.code] = [v for v in r.items]
            row_of[(key, r.code)] = r

    report = ["=== BÁO CÁO KIỂM TRA ==="]
    # 1. bỏ phiếu số dư đầu năm
    report.append("\n[1] Bỏ phiếu số dư đầu năm giữa các quý:")
    report += vote_bs_opening(by_doc, meta) or ["  (không có thay đổi)"]
    report.append("\n[1b] Tính chỉ tiêu bị mất dòng OCR từ đẳng thức:")
    derived = []
    for key in sorted(by_doc):
        derived += derive_missing(key, by_doc[key], row_of, meta[key])
    report += derived or ["  (không có)"]
    # 2. sửa bằng đẳng thức
    report.append("\n[2] Kiểm tra đẳng thức kế toán:")
    summary = []
    for key, vals in sorted(by_doc.items()):
        m = meta[key]
        # Chỉ đưa phương trình vào kiểm tra khi parent tồn tại; child thiếu
        # được giữ lại trong eq để residual() nhận diện INCOMPLETE_EQUATION.
        eqs = [(p, ch) for p, ch in EQ[(m["version"], key[1])] if p in vals]
        incomplete = 0
        for eq in eqs:
            for c in range(m["n_cols"]):
                if residual(eq, vals, c) is None:
                    parent, children = eq
                    members = [parent] + [x for x, _ in children]
                    if any(x not in vals or c >= len(vals[x]) or vals[x][c] is None or vals[x][c].value is None for x in members):
                        incomplete += 1
        before = len(failing(eqs, vals, m["n_cols"]))
        fixed = repair_identity(eqs, vals, m["n_cols"])
        left = failing(eqs, vals, m["n_cols"])
        total = len(eqs) * m["n_cols"]
        summary.append((key, len(vals), total, before, fixed, len(left), incomplete))
        if m.get("column_uncertain"):
            report.append(f"  CẢNH BÁO [{key[0]} {key[1]}] số cột không chắc chắn: {m['n_cols']} (confidence {m['col_conf']:.0%})")
        for i, c in left:
            p, ch = eqs[i]
            report.append(f"  LỆCH [{key[0]} {key[1]}] {p} = {' '.join(('+' if s > 0 else '-') + x for x, s in ch)} "
                          f"(cột {c + 1}) chênh {residual(eqs[i], vals, c):,}")
    report.append("\n  doc | báo cáo | số chỉ tiêu | số phép kiểm | lệch trước sửa | đã sửa | còn lệch | phương trình thiếu dữ liệu")
    for (doc, st), n, tot, b, f, l, inc in summary:
        report.append(f"  {doc} | {st} | {n} | {tot} | {b} | {f} | {l} | {inc}")

    # 3. đối chiếu chéo
    report.append("\n[3] Đối chiếu chéo:")
    cross_audit = {}
    for doc in sorted({d for d, _ in by_doc}):
        bs, cf = by_doc.get((doc, "CDKT"), {}), by_doc.get((doc, "LCTT"), {})
        c110 = bs.get("110", [None])[0]
        c70 = cf.get("70", [None])[0]
        audit = {"status": "NOT_CHECKED", "reason": "", "reference_value": None}
        if c110 and c70 and c110.value is not None and c70.value is not None:
            ref, got = c110.value, c70.value
            audit["reference_value"] = ref
            if ref == got:
                audit["status"] = "VALID"
                report.append(f"  {doc}: CĐKT.110 (cuối kỳ) vs LCTT.70 -> OK")
            else:
                diff = got - ref
                # Không tự sửa. Chỉ gắn cờ OCR_SUSPECT khi sai khác rất nhỏ và
                # chuỗi OCR có thể biến thành giá trị tham chiếu bằng ít thay đổi.
                ed = edit_distance(str(abs(ref)), c70.digits)
                if abs(diff) <= 1000 and ed <= 2:
                    audit["status"] = "OCR_SUSPECT"
                    audit["reason"] = f"LCTT.70 lệch {diff:+,}; edit_distance={ed}; không tự sửa"
                    report.append(f"  {doc}: CĐKT.110 (cuối kỳ) vs LCTT.70 -> OCR_SUSPECT (chênh {diff:+,}, edit_distance={ed})")
                else:
                    audit["status"] = "MANUAL_REVIEW"
                    audit["reason"] = f"LCTT.70 lệch {diff:+,}; edit_distance={ed}"
                    report.append(f"  {doc}: CĐKT.110 (cuối kỳ) vs LCTT.70 -> MANUAL_REVIEW (chênh {diff:+,}, edit_distance={ed})")
        cross_audit[doc] = audit

    # xuất CSV long
    recs = []
    for (key, code), r in row_of.items():
        m = meta[key]
        lab = labels_for(m["version"], key[1]).get(code)
        for ci, v in enumerate(by_doc[key][code]):
            recs.append(dict(
                doc=key[0], quarter=m["quarter"], year=m["year"], statement=key[1], code=code,
                label=lab or r.label, label_ocr=r.label, label_in_dict=lab is not None, col=ci + 1,
                value=(v.value if v else 0), value_ocr=(v.ocr_value if v and v.ocr_value is not None else (v.value if v else 0)),
                status=("OCR" if v is None else v.status), page=r.page, note_ref=r.note, raw=r.raw,
                column_confidence=m["col_conf"], column_count_uncertain=m["column_uncertain"],
                audit_status=cross_audit.get(key[0], {}).get("status", ""),
                audit_reason=cross_audit.get(key[0], {}).get("reason", ""),
                audit_reference_value=cross_audit.get(key[0], {}).get("reference_value", ""),
            ))
    pd.DataFrame(recs).to_csv(out / "statements_long.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(unparsed).to_csv(out / "unparsed_rows.csv", index=False, encoding="utf-8-sig")
    (out / "validation_report.txt").write_text("\n".join(report), encoding="utf-8")
    print("\n".join(report))
    print(f"\nĐã ghi {len(recs)} dòng -> {out / 'statements_long.csv'};  {len(unparsed)} dòng cần soát tay")


if __name__ == "__main__":
    main()
