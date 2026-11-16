"""Lập chỉ mục từng trang PDF và giữ nguồn cho từng tài liệu."""
from collections import defaultdict
import json
from pathlib import Path

from src.ingest.consumer_extract import extract_document
from src.ingest.consumer_ocr import INTERIM, RAW, inputs


def note_chunks(boxes, chunk_lines=12, overlap=3, whole_page=False):
    tokens = boxes if whole_page else [b for b in boxes if .09 < b[1] < .95 and .06 < b[0] < .93]
    lines = []
    for box in sorted(tokens, key=lambda b: (b[1], b[0])):
        if lines and box[1] - lines[-1][0][1] < .005:
            lines[-1].append(box)
        else:
            lines.append([box])
    content = [" ".join(b[4] for b in sorted(line, key=lambda b: b[0])) for line in lines]
    for start in range(0, len(content), chunk_lines - overlap):
        chunk = "\n".join(content[start:start + chunk_lines])
        if len(chunk) >= (25 if whole_page else 100):
            yield chunk


def report_period(row):
    if period := row.get("period"):
        year, quarter = period.split("-")
        return f"{quarter}/{year}"
    year = int(row["period_end"][:4])
    if row["company_code"] == "SBT":
        return f"FY{year - 1}-{year}"
    return f"FY{year}"


def add_documents(db):
    db.execute("""create table documents(
        id varchar primary key, company varchar, period varchar, url varchar,
        statement varchar, pages integer, indexed_pages integer
    )""")
    db.execute("""create table document_chunks(
        id varchar, page integer, ordinal integer, content varchar,
        primary key(id, page, ordinal)
    )""")
    db.execute("""create table document_facts(
        id varchar, metric varchar, basis varchar, value bigint, page integer, scope varchar, statement varchar
    )""")
    documents, chunks = [], []
    candidates = defaultdict(list)
    verified_periods = set(db.execute("select company, period from reports").fetchall())
    for row in inputs():
        path = Path(row["file"])
        if not (RAW / path).is_file():
            raise FileNotFoundError(RAW / path)
        section = path.stem.rsplit("-", 1)[-1]
        section = section if section in {"CDKT", "KQKD", "LCTT"} else "Báo cáo"
        company, period = row["company_code"], report_period(row)
        needs_facts = (company, period) not in verified_periods
        indexed = 0
        pages = {}
        for file in sorted((INTERIM / path.stem).glob("*.json")):
            boxes = json.loads(file.read_text(encoding="utf-8"))
            page = int(file.stem)
            parts = list(note_chunks(boxes, whole_page=True))
            if parts:
                indexed += 1
                chunks.extend((path.stem, page, i, part) for i, part in enumerate(parts))
            if needs_facts:
                pages[page] = boxes
        if needs_facts:                                   # trích theo nội dung + đẳng thức kế toán (xem consumer_extract.py)
            for (metric, basis), (value, page, scope, statement) in extract_document(pages, company, period).items():
                candidates[company, period, metric, basis].append((path.stem, metric, basis, value, page, scope, statement))
        documents.append((path.stem, company, period,
                          row["source_url"], section, row["pages"], indexed))
    db.executemany("insert into documents values (?,?,?,?,?,?,?)", documents)
    if chunks:
        db.executemany("insert into document_chunks values (?,?,?,?)", chunks)
    facts = [values[0] for values in candidates.values()
             if len({row[3] for row in values}) == 1]
    if facts:
        db.executemany("insert into document_facts values (?,?,?,?,?,?,?)", facts)
    print(f"{len(documents)} PDF, {sum(row[-1] for row in documents)} trang có văn bản, "
          f"{len(chunks)} đoạn, {len(facts)} chỉ tiêu được đối chiếu tự động")
