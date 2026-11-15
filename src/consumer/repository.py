"""Tra cứu chỉ tiêu và truy xuất nội dung PDF theo doanh nghiệp, kỳ."""
from contextlib import closing
from functools import lru_cache
import re

import duckdb

from src.paths import PROCESSED
from src.consumer.catalog import fold
from src.rag.bm25 import BM25
from src.rag.text import tokenize

DB_PATH = PROCESSED / "consumer.duckdb"
AMOUNT_IN_LINE = re.compile(r"\d{1,3}(?:[.,]\s*\d{3})+|\d{4,}")


def open_db():
    return closing(duckdb.connect(str(DB_PATH), read_only=True, config={"threads": 1}))


def source(company, period, scope, page, url, statement):
    return {
        "doc": f"{company} · {period} · {scope}", "statement": statement,
        "page": page, "url": f"{url.split('#', 1)[0]}#page={page}", "is_pdf": True,
    }


def facts(companies, period, metric, basis):
    return [(company, *record) for company, _, _, *record in fact_rows(companies, [period], [metric], basis)]


def fact_rows(companies, periods, metrics, basis):
    with open_db() as db:
        return db.execute(
            """with available as (
                   select f.company, f.period, f.metric, f.basis, f.value, f.statement, f.page,
                          r.url, r.scope, p.difference
                   from facts f join reports r using(company, period)
                   left join period_checks p using(company, period, metric)
                   union all
                   select d.company, d.period, f.metric, f.basis, f.value, f.statement, f.page,
                          d.url, f.scope, null
                   from document_facts f join documents d using(id)
               )
               select company, period, metric, value, statement, page, url, scope, difference from available
               where company in (select unnest(?)) and period in (select unnest(?)) and metric in (select unnest(?))
               and basis in (?, 'point', 'annual')""",
            [companies, periods, metrics, basis],
        ).fetchall()


@lru_cache(maxsize=8)
def _notes_index(company, period):
    with open_db() as db:
        rows = db.execute(
            """select n.page, n.content, r.url, r.scope
               from notes n join reports r using(company, period)
               where company=? and period=? order by n.page, n.ordinal""",
            [company, period],
        ).fetchall()
    return rows, BM25([text for _, text, _, _ in rows]) if rows else None


def notes(company, period, query, limit=2):
    rows, index = _notes_index(company, period)
    if index is None:
        return []
    # Require a shared phrase, rather than citing pages matched only by common words.
    phrases = {t for t in tokenize(query) if "_" in t}
    scores = index.scores(query)
    ranked = sorted(range(len(rows)), key=lambda i: (-scores[i], i))
    out = []
    for i in ranked:
        page, content, url, scope = rows[i]
        if scores[i] <= 0 or not phrases.intersection(index.tf[i]):
            continue
        if any(item["source"]["page"] == page for item in out):
            continue
        out.append({"text": content, "source": source(company, period, scope, page, url, "Thuyết minh")})
        if len(out) == limit:
            break
    return out


def documents(company, period=None):
    with open_db() as db:
        return db.execute(
            """select period, url, statement from documents
               where company=? and (? is null or period=?) order by id""",
            [company, period, period],
        ).fetchall()


def coverage():
    with open_db() as db:
        return db.execute("select distinct company, period from documents").fetchall()


@lru_cache(maxsize=24)
def _document_index(company, period):
    with open_db() as db:
        rows = db.execute(
            """select c.id, c.page, c.content, d.url, d.statement
               from document_chunks c join documents d using(id)
               where d.company=? and d.period=? order by c.id, c.page, c.ordinal""",
            [company, period],
        ).fetchall()
    return rows, BM25([row[2] for row in rows]) if rows else None


def excerpts(company, period, topic, aliases=(), statement=None, limit=2):
    rows, index = _document_index(company, period)
    if index is None:
        return []
    phrases = {t for t in tokenize(topic) if "_" in t}
    scores = index.scores(topic)
    out, selected = [], set()
    for i in sorted(range(len(rows)), key=lambda i: (-scores[i], i)):
        document, page, content, url, section = rows[i]
        if (document, page) in selected or scores[i] <= 0:
            continue
        if statement and section not in ("Báo cáo", statement):
            continue
        if aliases:
            lines = content.splitlines()
            content = "\n".join(line for line in lines if any(a in fold(line) for a in aliases)
                                and AMOUNT_IN_LINE.search(line))
            if not content:
                continue
        elif not phrases.intersection(index.tf[i]):
            continue
        out.append({"text": content, "source": source(company, period, "PDF", page, url, section)})
        selected.add((document, page))
        if len(out) >= limit:
            break
    return out
