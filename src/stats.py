"""Độ phủ dữ liệu của chatbot: kỳ báo cáo, chỉ tiêu có số liệu, đoạn thuyết minh và ảnh trang PDF dẫn chứng.

Chỉ đọc dữ liệu đã nạp trong bộ nhớ (Facts) và đếm tệp, không gọi mô hình; kết quả không đổi trong suốt vòng đời tiến trình nên được lưu đệm.
"""
from __future__ import annotations

import json
from collections import Counter
from functools import lru_cache
from pathlib import Path

from .paths import CHUNKS_PATH, PAGES_DIR
from .tools.facts import Facts, version_of
from .tools.metrics import METRICS

STANDARDS = {"TT200": "Thông tư 200", "TT99": "Thông tư 99"}


def build_coverage(facts: Facts, chunks_path: Path = CHUNKS_PATH, pages_dir: Path = PAGES_DIR) -> dict:
    periods = facts.periods()
    docs = [p.doc for p in periods]
    present = {(doc, st, code) for (doc, st, code, _ky) in facts.cells}                # (báo cáo, loại báo cáo, mã số) có ít nhất một ô số liệu
    with open(chunks_path, encoding="utf-8") as f:
        chunk_docs = Counter(json.loads(line)["doc"] for line in f if line.strip())

    def has(m, doc: str) -> bool:
        return (doc, m.statement, m.codes[version_of(doc)]) in present

    metrics = [{"key": m.key, "name": m.name, "statement": m.statement, "kind": m.kind, "have": [has(m, d) for d in docs]} for m in METRICS]
    per_period = []
    for i, p in enumerate(periods):
        images = len(list((pages_dir / p.doc).glob("*.webp"))) if (pages_dir / p.doc).is_dir() else 0
        per_period.append({"period": str(p), "doc": p.doc, "standard": STANDARDS[version_of(p.doc)],
                           "metrics": sum(m["have"][i] for m in metrics), "chunks": chunk_docs[p.doc], "page_images": images,
                           "cells": sum(1 for k in facts.cells if k[0] == p.doc)})
    return {"periods": per_period, "metrics": metrics,
            "totals": {"periods": len(periods), "metrics": sum(any(m["have"]) for m in metrics), "metrics_defined": len(metrics),
                       "chunks": sum(chunk_docs.values()), "page_images": sum(p["page_images"] for p in per_period), "cells": len(facts.cells)}}


@lru_cache(maxsize=1)
def coverage() -> dict:
    from .tools.registry import analyst
    return build_coverage(analyst().f)
