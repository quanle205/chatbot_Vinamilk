"""Tiện ích văn bản tiếng Việt cho truy xuất: chuẩn hóa, tách token, nhận diện kỳ báo cáo."""
from __future__ import annotations

import re
import unicodedata

WORD_RE = re.compile(r"\w+", re.UNICODE)


def accent_free(s: str) -> str:
    s = unicodedata.normalize("NFD", s.replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def normalize(s: str) -> str:
    return unicodedata.normalize("NFC", s).lower()


def tokenize(s: str) -> list[str]:
    """Âm tiết có dấu + bigram không dấu.

    Tiếng Việt viết tách âm tiết nên bigram ("doanh thu", "loi nhuan") giữ được
    nghĩa của từ ghép; bản không dấu chịu được lỗi OCR mất/sai dấu (thuê/thuế).
    """
    syl = WORD_RE.findall(normalize(s))
    flat = [accent_free(w) for w in syl]
    return syl + [f"{a}_{b}" for a, b in zip(flat, flat[1:])]


# ------------------------------------------------------------------ kỳ báo cáo
QUARTER_END = {"Q1": "31/3", "Q2": "30/6", "Q3": "30/9", "Q4": "31/12"}
ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4}
MONTHS_TO_Q = {3: 1, 6: 2, 9: 3, 12: 4}


def period_label(quarter: str, year: int) -> str:
    return f"{quarter}/{year}"


def find_periods(query: str) -> tuple[set[str], set[int]]:
    """Trả về (doc cụ thể, năm) nhắc tới trong câu hỏi.

    Nhận: Q1/2026, quý 1 năm 2026, quý I/2026, 6 tháng đầu năm 2025, năm 2025.
    """
    q = accent_free(normalize(query))
    docs: set[str] = set()
    for m in re.finditer(r"\b(?:q|quy)\s*([1-4]|iv|iii|ii|i)\b\s*(?:/|-|nam)?\s*(20\d\d)", q):
        n = ROMAN.get(m.group(1)) or int(m.group(1))
        docs.add(f"q{n}-{m.group(2)}")
    for m in re.finditer(r"\b(3|6|9|12)\s*thang(?:\s*dau)?\s*(?:nam)?\s*(20\d\d)", q):
        docs.add(f"q{MONTHS_TO_Q[int(m.group(1))]}-{m.group(2)}")
    years = {int(y) for y in re.findall(r"\b(20\d\d)\b", q)}
    return docs, years


# ------------------------------------------------------------------ số tiền
def fmt_vnd(v: int) -> str:
    s = f"{abs(int(v)):,}".replace(",", ".")
    return f"({s})" if v < 0 else s


def fmt_ty(v: int) -> str:
    s = f"{abs(v) / 1e9:,.1f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"-{s}" if v < 0 else s
