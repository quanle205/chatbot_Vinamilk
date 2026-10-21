"""Giai đoạn 2 - chia đoạn (chunking) tài liệu cho RAG.

Hai nguồn:
  bang_so_lieu  3 báo cáo chính lấy từ bảng statements (số đã sửa/đối chiếu), mỗi dòng
                ghi rõ chỉ tiêu, mã số, kỳ và số tiền; không dùng văn bản OCR của các trang này.
  van_ban       các trang còn lại (thông tin chung, thuyết minh): bỏ header lặp, tách theo
                mục thuyết minh, gói ~900 ký tự, chồng lấp 2 dòng giữa các đoạn.
Mỗi đoạn có tiền tố ngữ cảnh [kỳ · phần · trang] để cả BM25 lẫn embedding thấy được kỳ báo cáo.
Chạy: python -m src.rag.chunking --db data/processed/financials.duckdb --out data/processed/chunks.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import duckdb

from .text import QUARTER_END, accent_free, fmt_ty, fmt_vnd, period_label

CHUNK_CHARS = 900
OVERLAP_LINES = 2
ROWS_PER_TABLE_CHUNK = 12

STATEMENT_NAMES = {
    "CDKT": "Báo cáo tình hình tài chính hợp nhất (bảng cân đối kế toán)",
    "KQKD": "Báo cáo kết quả hoạt động kinh doanh hợp nhất",
    "LCTT": "Báo cáo lưu chuyển tiền tệ hợp nhất",
}
HEADER_PATTERNS = [r"^cong ty c.\s*phan sua viet nam", r"^thuyet minh bao cao tai chinh",
                   r"^bao cao .* hop nhat .* ket thuc", r"^ngay \d+ thang \d+ nam \d+", r"cua bo tai chinh\)?$",
                   r"^mau b 0", r"^\(ban hanh theo"]
HEADING_RE = re.compile(r"^\s*(\d{1,2}|[IVX]{1,4})\s*[.,)]\s+\D")


def ky_text(ky: str, quarter: str, year: int) -> str:
    qn = int(quarter[1])
    months = 3 * qn
    luy_ke = (lambda y: f"cả năm {y}") if qn == 4 else (lambda y: f"{months} tháng đầu năm {y}")
    return {
        "cuoi_ky": f"tại ngày {QUARTER_END[quarter]}/{year}",
        "dau_nam": f"tại ngày 1/1/{year}",
        "quy_nay": f"quý {qn}/{year}",
        "quy_cung_ky": f"quý {qn}/{year - 1}",
        "luy_ke_nay": luy_ke(year),
        "luy_ke_cung_ky": luy_ke(year - 1),
    }.get(ky, ky)


def code_key(code: str):
    m = re.match(r"(\d+)(\w*)", code)
    return (int(m.group(1)), m.group(2)) if m else (999, code)


def table_chunks(con) -> list[dict]:
    rows = con.execute("""SELECT doc, quarter, year, statement, code, label, ky, value, page
                          FROM statements ORDER BY doc, statement, code, col""").fetchall()
    groups: dict = {}
    for doc, q, y, st, code, label, ky, value, page in rows:
        g = groups.setdefault((doc, q, int(y), st), {})
        item = g.setdefault(code, {"label": label, "vals": [], "page": page})
        item["vals"].append((ky, int(value)))
        if item["page"] is None and page is not None:
            item["page"] = page
    out = []
    for (doc, q, y, st), items in groups.items():
        codes = sorted(items, key=code_key)
        for i in range(0, len(codes), ROWS_PER_TABLE_CHUNK):
            part = codes[i:i + ROWS_PER_TABLE_CHUNK]
            pages = sorted({int(items[c]["page"]) for c in part if items[c]["page"] is not None})
            lines = [f"[{period_label(q, y)} · {STATEMENT_NAMES[st]} · trang {','.join(map(str, pages))}]"]
            for c in part:
                vals = "; ".join(f"{ky_text(ky, q, y)}: {fmt_vnd(v)} VND (≈ {fmt_ty(v)} tỷ đồng)"
                                 for ky, v in items[c]["vals"])
                lines.append(f"- {items[c]['label']} (mã số {c}): {vals}")
            out.append(dict(doc=doc, quarter=q, year=y, page=pages[0] if pages else None, kind="bang_so_lieu",
                            section=STATEMENT_NAMES[st], heading=st, text="\n".join(lines)))
    return out


def is_header(line: str) -> bool:
    a = accent_free(line.strip().lower())
    return any(re.search(p, a) for p in HEADER_PATTERNS)


def text_chunks(con) -> list[dict]:
    span = dict((d, (lo, hi)) for d, lo, hi in con.execute(
        "SELECT doc, min(page), max(page) FROM statements WHERE page IS NOT NULL GROUP BY doc").fetchall())
    pages = con.execute("SELECT doc, quarter, year, page, text FROM pages ORDER BY doc, page").fetchall()
    out, heading, cur_doc = [], "", None
    for doc, q, y, page, text in pages:
        lo, hi = span.get(doc, (10**6, -1))
        if lo <= page <= hi:
            continue                                   # trang 3 báo cáo chính -> đã có bang_so_lieu
        if doc != cur_doc:
            heading, cur_doc = "", doc
        section = "Thông tin chung và báo cáo của Ban Tổng Giám đốc" if page < lo else "Thuyết minh báo cáo tài chính hợp nhất"
        lines = text.splitlines()
        while lines and is_header(lines[0]):
            lines.pop(0)
        lines = [l for i, l in enumerate(lines) if not (i < 6 and is_header(l)) and l.strip()]

        buf: list[str] = []
        def emit():
            if sum(len(l) for l in buf) < 40:
                return
            prefix = f"[{period_label(q, int(y))} · {section} · trang {page}]" + (f" {heading}" if heading and not HEADING_RE.match(buf[0]) else "")
            out.append(dict(doc=doc, quarter=q, year=int(y), page=page, kind="van_ban",
                            section=section, heading=heading, text=prefix + "\n" + "\n".join(buf)))
        for line in lines:
            if HEADING_RE.match(line) and len(line) < 120:
                if sum(len(l) for l in buf) > 300:
                    emit()
                    buf = []
                heading = line.strip()
            buf.append(line)
            if sum(len(l) for l in buf) > CHUNK_CHARS:
                emit()
                buf = buf[-OVERLAP_LINES:]
        if buf and (len(buf) > OVERLAP_LINES or not out or out[-1]["page"] != page):
            emit()
    return out


def build(db: Path) -> list[dict]:
    con = duckdb.connect(str(db), read_only=True)
    chunks = table_chunks(con) + text_chunks(con)
    con.close()
    for i, c in enumerate(chunks):
        c["id"] = f"{c['doc']}#{c['kind']}#{i}"
    return chunks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/processed/financials.duckdb")
    ap.add_argument("--out", default="data/processed/chunks.jsonl")
    a = ap.parse_args()
    chunks = build(Path(a.db))
    with open(a.out, "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    n_tab = sum(c["kind"] == "bang_so_lieu" for c in chunks)
    lens = sorted(len(c["text"]) for c in chunks)
    print(f"{len(chunks)} đoạn ({n_tab} bảng số liệu, {len(chunks) - n_tab} văn bản); "
          f"độ dài trung vị {lens[len(lens) // 2]} ký tự, max {lens[-1]} -> {a.out}")


if __name__ == "__main__":
    main()
