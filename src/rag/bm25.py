"""BM25 Okapi tự cài (958 đoạn nên không cần thư viện ngoài), có lọc theo tập đoạn cho phép."""
from __future__ import annotations

import math
from collections import Counter

import numpy as np

from .text import tokenize


class BM25:
    def __init__(self, texts: list[str], k1: float = 0.9, b: float = 0.5):
        self.k1, self.b = k1, b
        docs = [tokenize(t) for t in texts]
        self.n = len(docs)
        self.dl = np.array([len(d) for d in docs], dtype=float)
        self.avgdl = self.dl.mean() if self.n else 0.0
        self.tf: list[Counter] = [Counter(d) for d in docs]
        df = Counter(t for d in self.tf for t in d)
        self.idf = {t: math.log(1 + (self.n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.postings: dict[str, list[int]] = {}
        for i, d in enumerate(self.tf):
            for t in d:
                self.postings.setdefault(t, []).append(i)

    def scores(self, query: str) -> np.ndarray:
        s = np.zeros(self.n)
        norm = self.k1 * (1 - self.b + self.b * self.dl / self.avgdl)
        for t in set(tokenize(query)):
            idf = self.idf.get(t)
            if idf is None:
                continue
            for i in self.postings[t]:
                f = self.tf[i][t]
                s[i] += idf * f * (self.k1 + 1) / (f + norm[i])
        return s
