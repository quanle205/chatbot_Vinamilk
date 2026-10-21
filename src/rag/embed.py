"""Biểu diễn vector cho nhánh truy xuất thứ hai: TF-IDF n-gam ký tự không dấu (scikit-learn).

Chịu được lỗi OCR và sai khác dấu nhưng không hiểu đồng nghĩa. Đã thử mô hình embedding đa ngữ
(paraphrase-multilingual-MiniLM): không tốt hơn BM25 trên dữ liệu số liệu này nên không giữ lại.
"""
from __future__ import annotations

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from .text import accent_free, normalize


def _prep(s: str) -> str:
    return accent_free(normalize(s))


class NgramEmbedder:
    def __init__(self):
        self.vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, min_df=2,
                                   preprocessor=_prep)

    def fit(self, texts):
        self.vec.fit(texts)
        return self

    def encode_docs(self, texts):
        return self.vec.transform(texts)           # ma trận thưa, đã chuẩn hóa L2

    def encode_query(self, q):
        return self.vec.transform([q])


def similarity(doc_matrix, q_vec) -> np.ndarray:
    return np.asarray((doc_matrix @ q_vec.T).todense()).ravel()
