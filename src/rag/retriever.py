"""Truy xuất lai: BM25 + vector, hợp nhất bằng Reciprocal Rank Fusion (RRF).

RRF(d) = Σ_r 1 / (k + rank_r(d)), k = 60: chỉ dùng thứ hạng nên không cần chuẩn hóa điểm BM25 và cosine.
Kỳ báo cáo trong câu hỏi (Q1/2026, 6 tháng đầu năm 2025...) được dùng làm bộ lọc cứng theo `doc`,
vì mọi báo cáo đều có cùng tên chỉ tiêu và BM25/vector không phân biệt được kỳ nếu chỉ dựa vào nội dung.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .bm25 import BM25
from .embed import NgramEmbedder, similarity
from .text import accent_free, find_periods

RRF_K = 60
CANDIDATES = 50
NUMERIC_HINTS = ("bao nhieu", "bang bao", "la bao", "tong", "doanh thu", "loi nhuan", "gia von", "chi phi",
                 "tai san", "no phai tra", "von chu so huu", "tien ", "bien", "so sanh", "tang", "giam")


@dataclass
class Hit:
    chunk: dict
    score: float
    ranks: dict          # {"bm25": rank, "vector": rank} (1-based, thiếu = không lọt top CANDIDATES)


class HybridRetriever:
    def __init__(self, chunks: list[dict]):
        self.chunks = chunks
        texts = [c["text"] for c in chunks]
        self.bm25 = BM25(texts)
        self.embedder = NgramEmbedder().fit(texts)
        # Đã đo (eval/retrieval_check.py, 14 câu từ khóa + 10 câu đồng nghĩa): nhánh vector kém BM25 và
        # trọng số bằng BM25 làm hybrid tụt hạng (MRR 0,57-0,77 so với 0,84), nên giữ trọng số thấp.
        self.vector_weight = 0.15
        self.doc_vecs = self.embedder.encode_docs(texts)
        self.docs = np.array([c["doc"] for c in chunks])
        self.kinds = np.array([c["kind"] for c in chunks])

    @staticmethod
    def from_jsonl(path: str | Path) -> "HybridRetriever":
        with open(path, encoding="utf-8") as f:
            return HybridRetriever([json.loads(line) for line in f if line.strip()])

    # ---------------------------------------------------------------- tìm kiếm
    def _allowed(self, query: str, docs: set[str] | None) -> np.ndarray:
        found_docs, years = find_periods(query)
        want = docs or found_docs
        mask = np.ones(len(self.chunks), dtype=bool)
        if want:
            mask &= np.isin(self.docs, list(want))
        elif years:
            mask &= np.isin(self.docs, [d for d in set(self.docs) if int(d.split("-")[1]) in years])
        return mask

    @staticmethod
    def _rank(scores: np.ndarray, mask: np.ndarray, n: int) -> list[int]:
        s = np.where(mask & (scores > 0), scores, -np.inf)
        idx = np.argsort(-s)[:n]
        return [int(i) for i in idx if np.isfinite(s[i])]

    def search(self, query: str, k: int = 6, docs: set[str] | None = None, mode: str = "hybrid",
               weights: dict | None = None) -> list[Hit]:
        w = {"bm25": 1.0, "vector": self.vector_weight, **(weights or {})}
        mask = self._allowed(query, docs)
        rankings: dict[str, list[int]] = {}
        if mode in ("hybrid", "bm25"):
            rankings["bm25"] = self._rank(self.bm25.scores(query), mask, CANDIDATES)
        if mode in ("hybrid", "vector"):
            rankings["vector"] = self._rank(similarity(self.doc_vecs, self.embedder.encode_query(query)), mask, CANDIDATES)

        fused: dict[int, float] = {}
        for name, ranking in rankings.items():
            for r, i in enumerate(ranking, 1):
                fused[i] = fused.get(i, 0.0) + w[name] / (RRF_K + r)
        # Câu hỏi hỏi số liệu -> đoạn bảng số liệu (đã đối chiếu) ưu tiên hơn đoạn thuyết minh.
        if any(h in accent_free(query.lower()) for h in NUMERIC_HINTS):
            for i in fused:
                if self.kinds[i] == "bang_so_lieu":
                    fused[i] *= 1.15
        top = sorted(fused, key=fused.get, reverse=True)[:k]
        return [Hit(self.chunks[i], fused[i],
                    {name: r.index(i) + 1 for name, r in rankings.items() if i in r}) for i in top]
