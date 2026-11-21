"""So sánh bốn mô hình phân loại ý định trên cùng đặc trưng. Chạy: python -m src.train.compare_models

Quy trình: (1) chọn siêu tham số của từng mô hình bằng kiểm chứng chéo 5 fold trên tập train, chia fold theo mẫu câu
(GroupKFold) để fold kiểm tra chỉ gồm mẫu câu chưa thấy; chia ngẫu nhiên thì câu cùng mẫu rơi vào cả hai phía và F1 gần 1,00
ở mọi cấu hình nên không dùng được; (2) huấn luyện lại trên toàn bộ train với siêu tham số đã chọn; (3) đo một lần trên tập test
(chỉ tiêu, mẫu câu, chủ đề chưa thấy) và trên tập giữ lại sạch (mẫu câu viết sau khi chốt train, dataset.build_holdout).
Kết quả ghi vào eval/intent_comparison.json.
"""
import json
import sys
from pathlib import Path

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, precision_recall_fscore_support
from sklearn.model_selection import GroupKFold
from sklearn.naive_bayes import ComplementNB
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.svm import LinearSVC

from .dataset import LABELS, build, build_holdout
from .intent import OOS, _prep

OUT = Path(__file__).resolve().parents[2] / "eval" / "intent_comparison.json"

CANDIDATES = {
    "Hồi quy logistic": ("C", [1, 10, 100], lambda v: LogisticRegression(C=v, max_iter=2000, class_weight="balanced")),
    "SVM tuyến tính": ("C", [0.1, 1, 10], lambda v: LinearSVC(C=v, class_weight="balanced")),
    "Naive Bayes (Complement)": ("alpha", [0.01, 0.1, 1.0], lambda v: ComplementNB(alpha=v)),
    "Random Forest": ("max_depth", [None, 30], lambda v: RandomForestClassifier(n_estimators=300, max_depth=v,
                                                                              class_weight="balanced", random_state=0, n_jobs=-1)),
}


def pipeline(clf):
    feats = FeatureUnion([
        ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), sublinear_tf=True, preprocessor=_prep)),
        ("word", TfidfVectorizer(analyzer="word", ngram_range=(1, 2), sublinear_tf=True, preprocessor=_prep)),
    ])
    return Pipeline([("f", feats), ("clf", clf)])


def cv_f1(make, X, y, groups, folds=5):
    scores = []
    for tr, te in GroupKFold(n_splits=folds).split(X, y, groups):
        model = pipeline(make()).fit([X[i] for i in tr], [y[i] for i in tr])
        scores.append(f1_score([y[i] for i in te], model.predict([X[i] for i in te]), average="macro", labels=LABELS, zero_division=0))
    return float(np.mean(scores)), float(np.std(scores))


def evaluate(model, pairs):
    X, y = [q for q, _ in pairs], [l for _, l in pairs]
    pred = model.predict(X)
    p, r, f, _ = precision_recall_fscore_support(y, pred, labels=LABELS, average="macro", zero_division=0)
    oos = [i for i, l in enumerate(y) if l == OOS]
    return {"accuracy": accuracy_score(y, pred), "precision": p, "recall": r, "f1_macro": f,
            "oos_caught": sum(pred[i] == OOS for i in oos), "oos_total": len(oos),
            "in_scope_refused": sum(pred[i] == OOS for i, l in enumerate(y) if l != OOS)}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    d = build(groups=True)
    X, y, groups = [q for q, _ in d["train"]], [l for _, l in d["train"]], d["train_groups"]
    assert len(groups) == len(X)
    holdout = build_holdout()
    print(f"train {len(X)} câu ({len(set(groups))} mẫu câu), test {len(d['test'])}, giữ lại {len(holdout)}\n")
    rows = []
    for name, (param, values, factory) in CANDIDATES.items():
        cv = {v: cv_f1(lambda v=v: factory(v), X, y, groups) for v in values}
        best = max(values, key=lambda v: cv[v][0])
        model = pipeline(factory(best)).fit(X, y)
        row = {"model": name, "param": param, "value": best, "cv_f1": cv[best][0], "cv_std": cv[best][1],
               "cv_all": {str(v): round(cv[v][0], 3) for v in values},
               "test": evaluate(model, d["test"]), "holdout": evaluate(model, holdout)}
        rows.append(row)
        t, h = row["test"], row["holdout"]
        print(f"{name:26s} {param}={best!s:5s} CV F1 {cv[best][0]:.3f}±{cv[best][1]:.3f} | test acc {t['accuracy']:.3f} "
              f"P {t['precision']:.3f} R {t['recall']:.3f} F1 {t['f1_macro']:.3f} | giữ lại F1 {h['f1_macro']:.3f}, "
              f"bắt ngoài PV {h['oos_caught']}/{h['oos_total']}")
    # mô hình đang chạy trong hệ thống: hồi quy logistic C = 10 (intent.py)
    prod = pipeline(LogisticRegression(C=10, max_iter=2000, class_weight="balanced"))
    cv = cv_f1(lambda: LogisticRegression(C=10, max_iter=2000, class_weight="balanced"), X, y, groups)
    prod.fit(X, y)
    rows.append({"model": "Hồi quy logistic (đang dùng)", "param": "C", "value": 10, "cv_f1": cv[0], "cv_std": cv[1],
                 "test": evaluate(prod, d["test"]), "holdout": evaluate(prod, holdout)})
    t, h = rows[-1]["test"], rows[-1]["holdout"]
    print(f"{'Hồi quy logistic (đang dùng)':26s} C=10    CV F1 {cv[0]:.3f}±{cv[1]:.3f} | test acc {t['accuracy']:.3f} "
          f"P {t['precision']:.3f} R {t['recall']:.3f} F1 {t['f1_macro']:.3f} | giữ lại F1 {h['f1_macro']:.3f}, "
          f"bắt ngoài PV {h['oos_caught']}/{h['oos_total']}")
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print(f"\nĐã ghi {OUT}")


if __name__ == "__main__":
    main()
