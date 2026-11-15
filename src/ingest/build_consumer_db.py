"""Dựng DuckDB từ báo cáo gốc, dữ liệu OCR và các bảng đã đối chiếu."""
from contextlib import closing
import json
from pathlib import Path
from uuid import uuid4

import duckdb

from src.consumer.catalog import METRICS
from src.consumer.repository import DB_PATH
from src.ingest.consumer_documents import add_documents, note_chunks
from src.ingest.consumer_ocr import INTERIM, inputs
from src.ingest.consumer_tables import LAYOUTS, extract

PERIOD_CHECKS = Path(__file__).parent / "consumer_period_checks.json"
POINT_METRICS = {"tong_tai_san", "no_phai_tra", "von_chu_so_huu", "hang_ton_kho"}


def validate(rows):
    def vals(key):
        return rows[key][0]

    def equality(total, *parts):
        for target, *values in zip(vals(total), *(vals(part) for part in parts), strict=True):
            if target != sum(values):
                raise ValueError(f"{total}: {target:,} != {sum(values):,}")

    missing = METRICS.keys() - rows.keys()
    if missing:
        raise ValueError(f"Thiếu chỉ tiêu: {', '.join(sorted(missing))}")
    equality("tong_tai_san", "no_phai_tra", "von_chu_so_huu")
    equality("tong_tai_san", "_tong_nguon_von")
    equality("doanh_thu_thuan", "loi_nhuan_gop", "_gia_von")
    equality("_dong_tien_thuan", "dong_tien_kinh_doanh", "dong_tien_dau_tu", "dong_tien_tai_chinh")


def report_facts(company, period, rows):
    for metric in METRICS:
        values, statement, page = rows[metric]
        if metric in POINT_METRICS:
            by_basis = {"point": values[0]}
        elif period == "FY2025":
            by_basis = {"annual": values[0]}
        elif statement == "KQKD":
            by_basis = {"quy": values[0], "luy_ke": values[2] if len(values) == 4 else values[0]}
        else:
            by_basis = {"luy_ke": values[0]}
            if period == "Q1/2026":
                by_basis["quy"] = values[0]
        for basis, value in by_basis.items():
            yield company, period, metric, basis, value, statement, page


def main():
    reports, facts, notes = [], [], []
    raw_tables = {}
    for row in inputs(pilot_only=True):
        company = row["company_code"]
        period = row["period"][-2:] + "/2026" if row.get("period") else "FY2025"
        folder = INTERIM / Path(row["file"]).stem
        pages = {int(p.stem): json.loads(p.read_text(encoding="utf-8")) for p in folder.glob("*.json")}
        key = f"{company} {period}"
        try:
            table = extract(company, period, pages)
            validate(table)
        except (KeyError, ValueError) as error:
            raise SystemExit(f"{key}: {error}") from error
        if len(pages) != row["pages"]:
            raise SystemExit(f"{key}: cần OCR đủ {row['pages']} trang, hiện có {len(pages)}")
        scope = "hợp nhất" if company == "QNS" else "riêng"
        reports.append((company, period, row["period_end"], scope, row["source_url"]))
        facts.extend(report_facts(company, period, table))
        raw_tables[company, period] = table
        last_statement = max(sum(LAYOUTS[company, period], ()))
        for n in range(last_statement + 1, row["pages"] + 1):
            notes.extend((company, period, n, i, text) for i, text in enumerate(note_chunks(pages[n])))
    if len(reports) != len(LAYOUTS):
        raise SystemExit("Cần đủ 8 báo cáo MCM/QNS")

    # Đối chiếu riêng quý với chênh lệch hai cột lũy kế. Giữ nguyên số đã công bố.
    expected = json.loads(PERIOD_CHECKS.read_text(encoding="utf-8"))
    differences = []
    for company, period in raw_tables:
        if period not in ("Q2/2026", "Q3/2026"):
            continue
        current = raw_tables[company, period]
        previous = raw_tables[company, "Q1/2026" if period == "Q2/2026" else "Q2/2026"]
        for metric in METRICS:
            values, statement, _ = current[metric]
            if statement != "KQKD":
                continue
            base_index = 2 if period == "Q3/2026" else 0
            difference = values[0] - (values[2] - previous[metric][0][base_index])
            if expected.get(f"{company} {period}", {}).get(metric, 0) != difference:
                raise SystemExit(f"{company} {period} {metric}: chênh lệch {difference:,} đồng cần đối chiếu")
            if difference:
                differences.append((company, period, metric, difference))

    tmp = DB_PATH.with_name(f".{DB_PATH.stem}-{uuid4().hex}.building")
    with closing(duckdb.connect(str(tmp))) as db:
        db.execute("begin transaction")
        db.execute("""create table reports(company varchar, period varchar, period_end date, scope varchar,
                    url varchar, primary key(company, period))""")
        db.execute("""create table facts(company varchar, period varchar, metric varchar, basis varchar,
                    value bigint, statement varchar, page integer, primary key(company, period, metric, basis))""")
        db.execute("""create table notes(company varchar, period varchar, page integer, ordinal integer, content varchar,
                    primary key(company, period, page, ordinal))""")
        db.execute("""create table period_checks(company varchar, period varchar, metric varchar, difference bigint,
                    primary key(company, period, metric))""")
        db.executemany("insert into reports values (?,?,?,?,?)", reports)
        db.executemany("insert into facts values (?,?,?,?,?,?,?)", facts)
        db.executemany("insert into notes values (?,?,?,?,?)", notes)
        if differences:
            db.executemany("insert into period_checks values (?,?,?,?)", differences)
        add_documents(db)
        db.execute("commit")
    tmp.replace(DB_PATH)
    print(f"{DB_PATH.name}: {len(reports)} reports, {len(facts)} facts, {len(notes)} note chunks")


if __name__ == "__main__":
    main()
