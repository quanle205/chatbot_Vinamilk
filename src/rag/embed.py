"""Biểu diễn vector cho truy xuất ngữ nghĩa. Hai backend cùng giao diện fit/encode_docs/encode_query:

  ngram     TF-IDF n-gam ký tự không dấu (scikit-learn, chạy ngay, không tải mô hình).
            Chịu được lỗi OCR và sai khác dấu, nhưng KHÔNG hiểu đồng nghĩa.
  fastembed mô hình embedding đa ngữ chạy trên CPU qua ONNX (cần tải trọng số lần đầu).
"""
from __future__ import annotations

import numpy as np

from .text import accent_free, normalize

DEFAULT_FASTEMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"  # ~0,22 GB, 384 chiều


def _prep(s: str) -> str:
    return accent_free(normalize(s))


class NgramEmbedder:
    name = "ngram"

    def __init__(self):
        from sklearn.feature_extraction.text import TfidfVectorizer
        self.vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, min_df=2,
                                   preprocessor=_prep)

    def fit(self, texts):
        self.vec.fit(texts)
        return self

    def encode_docs(self, texts):
        return self.vec.transform(texts)           # ma trận thưa, đã chuẩn hóa L2

    def encode_query(self, q):
        return self.vec.transform([q])


class FastEmbedder:
    name = "fastembed"

    def __init__(self, model: str = DEFAULT_FASTEMBED_MODEL):
        self.model_name = model
        self._model = None
        self.e5 = "e5" in model.lower()

    @property
    def model(self):                      # nạp lười: phiên ONNX không pickle được nên không lưu cùng chỉ mục
        if self._model is None:
            from fastembed import TextEmbedding
            self._model = TextEmbedding(model_name=self.model_name)
        return self._model

    def __getstate__(self):
        return {**self.__dict__, "_model": None}

    def fit(self, texts):
        return self

    def encode_docs(self, texts):
        pre = "passage: " if self.e5 else ""
        return np.array(list(self.model.embed([pre + t for t in texts], batch_size=16)), dtype=np.float32)

    def encode_query(self, q):
        pre = "query: " if self.e5 else ""
        return np.array(list(self.model.embed([pre + q])), dtype=np.float32)


def make_embedder(kind: str = "ngram", **kw):
    if kind == "ngram":
        return NgramEmbedder()
    if kind == "fastembed":
        return FastEmbedder(**kw)
    raise ValueError(f"backend không hỗ trợ: {kind}")


def similarity(doc_matrix, q_vec) -> np.ndarray:
    s = doc_matrix @ q_vec.T if not isinstance(doc_matrix, np.ndarray) else doc_matrix @ q_vec[0]
    return np.asarray(s.todense()).ravel() if hasattr(s, "todense") else np.asarray(s).ravel()
