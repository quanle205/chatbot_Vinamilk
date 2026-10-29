"""Tìm lưới tham số truy xuất (k1, b của BM25 và trọng số nhánh vector) trên bộ câu hỏi sinh tự động, có tách train/test.
Chạy: python -m src.train.tune_retrieval [--quick]

Mỗi câu hỏi hỏi một chỉ tiêu ở một kỳ; đoạn đúng là đoạn bảng số liệu của kỳ đó có dòng "(mã số N)" đúng mã của chỉ tiêu theo
chuẩn TT200 (2025) hoặc TT99 (2026) và đúng mục báo cáo. Tập test gồm các CHỈ TIÊU không có trong train, nên cấu hình được chọn
trên train rồi đo trên test (khác với 24 câu viết tay trong eval/retrieval_check.py, nơi trọng số 0,15 được chọn ngay trên bộ đo).
"""
import argparse
import itertools
import random
import sys
import time

from ..rag.bm25 import BM25
from ..rag.retriever import HybridRetriever
from ..tools.metrics import METRICS

SECTION_OF = {"CDKT": "tình hình tài chính", "KQKD": "kết quả hoạt động", "LCTT": "lưu chuyển tiền tệ"}
TEMPLATES = ["{t} {p}", "{t} {p} là bao nhiêu?"]
K1S, BS, WVECS = (0.9, 1.2, 1.5, 2.0), (0.5, 0.75, 0.9), (0.0, 0.05, 0.15, 0.3)


def build_cases(chunks: list[dict], seed: int = 3, test_share: float = 0.3):
    rng = random.Random(seed)
    tables = [c for c in chunks if c["kind"] == "bang_so_lieu"]
    keys = sorted(m.key for m in METRICS)
    rng.shuffle(keys)
    test_keys = set(keys[: int(len(keys) * test_share)])
    cases = {"train": [], "test": []}
    for m in METRICS:
        for doc in sorted({c["doc"] for c in tables}):
            std = "TT200" if doc.endswith("2025") else "TT99"
            needle = f"(mã số {m.codes[std]})"
            hits = [c for c in tables if c["doc"] == doc and SECTION_OF[m.statement] in c["section"].lower() and needle in c["text"]]
            if not hits:
                continue
            quarter, year = hits[0]["quarter"], hits[0]["year"]
            term = rng.choice([m.name.lower(), *[a for a in m.aliases if " " in a]])
            q = rng.choice(TEMPLATES).format(t=term, p=f"{quarter}/{year}")
            cases["test" if m.key in test_keys else "train"].append((q, doc, m.statement, needle))
    return cases


def evaluate(r: HybridRetriever, cases, k: int = 6):
    hit = rr = 0.0
    for q, doc, stmt, needle in cases:
        rank = next((i for i, h in enumerate(r.search(q, k=k), 1)
                     if h.chunk["doc"] == doc and needle in h.chunk["text"] and SECTION_OF[stmt] in h.chunk["section"].lower()), None)
        if rank:
            hit += 1
            rr += 1 / rank
    n = max(len(cases), 1)
    return hit / n, rr / n


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunks", default="data/processed/chunks.jsonl")
    ap.add_argument("--quick", action="store_true", help="lưới nhỏ để chạy thử")
    a = ap.parse_args()
    r = HybridRetriever.from_jsonl(a.chunks)
    texts = [c["text"] for c in r.chunks]
    cases = build_cases(r.chunks)
    print(f"câu hỏi: train {len(cases['train'])}, test {len(cases['test'])} (tách theo chỉ tiêu)")
    base = (1.5, 0.75, 0.15)
    grid = [base] if a.quick else list(itertools.product(K1S, BS, WVECS))
    rows = []
    t0 = time.time()
    for k1, b, wv in grid:
        r.bm25 = BM25(texts, k1=k1, b=b)
        r.vector_weight = wv
        rows.append(((k1, b, wv), evaluate(r, cases["train"]), evaluate(r, cases["test"])))
    print(f"đã thử {len(rows)} cấu hình trong {time.time() - t0:.0f} giây\n")
    rows.sort(key=lambda x: (-x[1][1], -x[1][0]))                     # chọn theo MRR trên train
    print("k1    b     w_vec | train Hit@6 / MRR | test Hit@6 / MRR")
    for (k1, b, wv), tr, te in rows[:8]:
        print(f"{k1:<5} {b:<5} {wv:<5} | {tr[0]:.3f} / {tr[1]:.3f}     | {te[0]:.3f} / {te[1]:.3f}")
    best = rows[0]
    cur = next((x for x in rows if x[0] == base), None)
    print(f"\nChọn theo train: k1={best[0][0]}, b={best[0][1]}, w_vec={best[0][2]} -> test Hit@6 {best[2][0]:.3f}, MRR {best[2][1]:.3f}")
    if cur:
        print(f"Cấu hình hiện dùng (1,5; 0,75; 0,15):            test Hit@6 {cur[2][0]:.3f}, MRR {cur[2][1]:.3f}")
    bm25_only = [x for x in rows if x[0][2] == 0.0]
    if bm25_only:
        x = bm25_only[0]
        print(f"BM25 đứng riêng tốt nhất (w_vec=0): k1={x[0][0]}, b={x[0][1]} -> test Hit@6 {x[2][0]:.3f}, MRR {x[2][1]:.3f}")


if __name__ == "__main__":
    main()
