"""Dựng chỉ mục truy xuất từ chunks.jsonl.
Chạy: python -m src.rag.build_index [--embedder ngram|fastembed] [--model TÊN_MÔ_HÌNH]
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from .embed import make_embedder
from .retriever import HybridRetriever


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunks", default="data/processed/chunks.jsonl")
    ap.add_argument("--out", default="data/processed/retriever.pkl")
    ap.add_argument("--embedder", default="ngram", choices=["ngram", "fastembed"])
    ap.add_argument("--model", default=None, help="Tên mô hình fastembed (mặc định paraphrase-multilingual-MiniLM-L12-v2)")
    a = ap.parse_args()
    t = time.time()
    emb = make_embedder(a.embedder, **({"model": a.model} if a.model else {}))
    r = HybridRetriever.from_jsonl(a.chunks, emb)
    r.save(a.out)
    print(f"{len(r.chunks)} đoạn, embedder={emb.name}, {time.time() - t:.1f}s -> {a.out} ({Path(a.out).stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
