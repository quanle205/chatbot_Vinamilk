"""Truy cập số liệu từ DuckDB, theo kỳ báo cáo và cơ sở tính (quý / lũy kế / số dư).

Mỗi giá trị trả về kèm nguồn (báo cáo, trang PDF, mã số, trạng thái số liệu) và các lưu ý
(số suy ra, số "đã phân loại lại"), để câu trả lời của chatbot truy vết được về PDF gốc.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from ..rag.text import find_periods
from .metrics import Metric

DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "processed" / "financials.duckdb"
QUARTER_END_DAY = {1: "31/3", 2: "30/6", 3: "30/9", 4: "31/12"}


class DataUnavailable(Exception):
    """Không có số liệu cho kỳ/chỉ tiêu được hỏi (khác với lỗi chương trình)."""


@dataclass(frozen=True, order=True)
class Period:
    year: int
    quarter: int

    @staticmethod
    def parse(text: str) -> "Period":
        docs, _ = find_periods(text)
        if len(docs) != 1:
            m = re.search(r"(20\d\d)\D{0,3}q([1-4])", text.lower())          # 2026Q1
            if m:
                return Period(int(m.group(1)), int(m.group(2)))
            raise ValueError(f"Không hiểu kỳ '{text}'. Dùng dạng 'Q1/2026'.")
        q, y = next(iter(docs))[1], next(iter(docs)).split("-")[1]
        return Period(int(y), int(q))

    @property
    def doc(self) -> str:
        return f"q{self.quarter}-{self.year}"

    def prev(self) -> "Period":
        return Period(self.year, self.quarter - 1) if self.quarter > 1 else Period(self.year - 1, 4)

    def minus_year(self) -> "Period":
        return Period(self.year - 1, self.quarter)

    def __str__(self):
        return f"Q{self.quarter}/{self.year}"


@dataclass
class Value:
    value: int
    sources: list = field(default_factory=list)     # [{doc, statement, code, label, ky, page, status}]
    notes: list = field(default_factory=list)
    description: str = ""                           # vd "quý 1/2026", "tại ngày 31/3/2026"


def version_of(doc: str) -> str:
    return "TT99" if int(doc.split("-")[1]) >= 2026 else "TT200"


class Facts:
    def __init__(self, db_path: str | Path = DEFAULT_DB):
        con = duckdb.connect(str(db_path), read_only=True)
        rows = con.execute("SELECT doc, quarter, year, statement, code, label, ky, value, repair_status, page "
                           "FROM statements").fetchall()
        con.close()
        self.cells: dict = {}
        self.docs: set[str] = set()
        for doc, q, y, st, code, label, ky, value, status, page in rows:
            self.docs.add(doc)
            self.cells[(doc, st, code, ky)] = dict(doc=doc, statement=st, code=code, label=label, ky=ky,
                                                   value=int(value), status=status,
                                                   page=None if page is None else int(page))

    # ---------------------------------------------------------------- ô đơn
    def periods(self) -> list[Period]:
        return sorted(Period(int(d.split("-")[1]), int(d[1])) for d in self.docs)

    def _cell(self, m: Metric, doc: str, ky: str) -> Value | None:
        code = m.codes[version_of(doc)]
        c = self.cells.get((doc, m.statement, code, ky))
        if c is None:
            return None
        notes = []
        if c["status"] == "MANUAL":
            notes.append("số đã được đối chiếu thủ công với PDF")
        elif c["status"] == "DERIVED":
            notes.append("số tính lại từ các dòng thành phần của báo cáo (dòng gốc OCR không đọc được)")
        elif c["status"].startswith("REPAIRED"):
            notes.append("số OCR đã được sửa tự động bằng ràng buộc kế toán")
        src = {k: c[k] for k in ("doc", "statement", "code", "label", "ky", "page")} | {"status": c["status"]}
        return Value(c["value"], [src], notes)

    def _need(self, v: Value | None, m: Metric, doc: str, ky: str) -> Value:
        if v is None:
            if doc not in self.docs:
                raise DataUnavailable(f"Chưa có báo cáo {doc.upper()} (có: {', '.join(sorted(self.docs))}).")
            raise DataUnavailable(f"Báo cáo {doc.upper()} không có '{m.name}' ({ky}).")
        return v

    # ---------------------------------------------------------------- số dư
    def balance(self, m: Metric, p: Period) -> Value:
        """Số dư cuối quý p."""
        if m.kind != "balance":
            raise DataUnavailable(f"'{m.name}' là chỉ tiêu phát sinh, không có số dư tại thời điểm.")
        v = self._cell(m, p.doc, "cuoi_ky")
        if v is None and p.quarter == 4:                          # cuối năm 2024: lấy số đầu năm 2025
            v = self._cell(m, Period(p.year + 1, 1).doc, "dau_nam")
            if v:
                v.notes.append("lấy từ cột 1/1 của báo cáo quý 1 năm sau")
        v = self._need(v, m, p.doc, "cuoi_ky")
        v.description = f"tại ngày {QUARTER_END_DAY[p.quarter]}/{p.year}"
        return v

    def opening(self, m: Metric, p: Period, basis: str = "quy") -> Value:
        """Số dư đầu kỳ: đầu quý (basis='quy') hoặc đầu năm (basis='luy_ke')."""
        if basis == "luy_ke" or p.quarter == 1:
            v = self._need(self._cell(m, Period(p.year, 1).doc, "dau_nam"), m, Period(p.year, 1).doc, "dau_nam")
            v.description = f"tại ngày 1/1/{p.year}"
            if p.year >= 2026:
                v.notes.append("số đầu năm 2026 đã phân loại lại theo TT99")
            return v
        return self.balance(m, p.prev())

    # ---------------------------------------------------------------- phát sinh
    def _cum(self, m: Metric, p: Period, which: str) -> Value:
        """Lũy kế từ đầu năm đến cuối quý p (which = current | prior: kỳ này | cùng kỳ năm trước)."""
        if m.statement == "KQKD" and p.quarter == 1:
            ky = "quy_nay" if which == "current" else "quy_cung_ky"
        else:
            ky = "luy_ke_nay" if which == "current" else "luy_ke_cung_ky"
        v = self._need(self._cell(m, p.doc, ky), m, p.doc, ky)
        if which == "prior" and p.year >= 2026:
            v.notes.append("số cùng kỳ năm trước trong báo cáo 2026 đã phân loại lại")
        return v

    def flow(self, m: Metric, p: Period, basis: str = "quy", which: str = "current") -> Value:
        """Số phát sinh: basis = 'quy' (riêng quý p) hoặc 'luy_ke' (từ đầu năm đến cuối quý p)."""
        if m.kind != "flow":
            raise DataUnavailable(f"'{m.name}' là số dư tại thời điểm, dùng balance.")
        ref = p if which == "current" else p.minus_year()
        if basis == "luy_ke":
            v = self._cum(m, p, which)
            v.description = (f"{3 * p.quarter} tháng đầu năm {ref.year}" if p.quarter < 4 else f"cả năm {ref.year}")
            return v
        # basis == "quy"
        if m.statement == "KQKD" and p.quarter < 4:
            ky = "quy_nay" if which == "current" else "quy_cung_ky"
            v = self._need(self._cell(m, p.doc, ky), m, p.doc, ky)
            if which == "prior" and p.year >= 2026:
                v.notes.append("số cùng kỳ năm trước trong báo cáo 2026 đã phân loại lại")
        elif p.quarter == 1:
            v = self._cum(m, p, which)
        else:                                                     # Q4 của KQKD, mọi quý >1 của LCTT
            cur = self._cum(m, p, which)
            prev = self._cum(m, p.prev(), which)
            v = Value(cur.value - prev.value, cur.sources + prev.sources,
                      sorted(set(cur.notes + prev.notes)) + [
                          f"số suy ra: lũy kế {3 * p.quarter} tháng trừ lũy kế {3 * (p.quarter - 1)} tháng "
                          "(báo cáo không in số riêng quý này)"])
        v.description = f"quý {p.quarter}/{ref.year}"
        return v
