"""Bộ phân loại ý định câu hỏi (học có giám sát): TF-IDF n-gam ký tự + từ trên văn bản đã bỏ dấu, hồi quy logistic.

Huấn luyện mất vài giây trên CPU từ bộ câu hỏi sinh bởi dataset.py, nên không lưu file mô hình (tránh lệch phiên bản thư viện);
`get_classifier()` huấn luyện một lần khi cần rồi giữ trong bộ nhớ. Dùng trong agent để từ chối sớm câu hỏi ngoài phạm vi
mà không tốn lượt gọi Gemini.
"""
from __future__ import annotations

import threading

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, Pipeline

from ..rag.text import accent_free, normalize
from .dataset import build

OOS = "ngoai_pham_vi"
REFUSE_THRESHOLD = 0.8          # chọn từ bảng quét ngưỡng trong train_intent.py: 0 câu hợp lệ bị từ chối nhầm; từ chối nhầm tệ hơn để Gemini tự từ chối


def _prep(s: str) -> str:
    return accent_free(normalize(s))


def make_pipeline(C: float = 10.0) -> Pipeline:
    feats = FeatureUnion([
        ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), sublinear_tf=True, preprocessor=_prep)),
        ("word", TfidfVectorizer(analyzer="word", ngram_range=(1, 2), sublinear_tf=True, preprocessor=_prep)),
    ])
    return Pipeline([("f", feats), ("clf", LogisticRegression(C=C, max_iter=2000, class_weight="balanced"))])


def fit(pairs: list[tuple[str, str]], C: float = 10.0) -> Pipeline:
    X, y = zip(*pairs)
    return make_pipeline(C).fit(list(X), list(y))


class IntentClassifier:
    def __init__(self, model: Pipeline):
        self.model = model

    def predict_proba(self, question: str) -> dict[str, float]:
        p = self.model.predict_proba([question])[0]
        return dict(zip(self.model.classes_, (float(x) for x in p)))

    def predict(self, question: str) -> tuple[str, float]:
        p = self.predict_proba(question)
        label = max(p, key=p.get)
        return label, p[label]

    def is_out_of_scope(self, question: str, threshold: float = REFUSE_THRESHOLD) -> bool:
        return self.predict_proba(question).get(OOS, 0.0) >= threshold


_lock = threading.Lock()
_cached: IntentClassifier | None = None


def get_classifier() -> IntentClassifier:
    global _cached
    with _lock:
        if _cached is None:
            data = build()
            _cached = IntentClassifier(fit(data["train"] + data["test"]))      # bản chạy thật học cả hai tập; số đo báo cáo lấy từ train -> test
        return _cached
