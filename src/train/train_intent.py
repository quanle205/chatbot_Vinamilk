"""Huấn luyện và đánh giá bộ phân loại ý định. Chạy: python -m src.train.train_intent

Tập test dùng chỉ tiêu, mẫu câu và chủ đề chưa thấy khi huấn luyện (xem dataset.py). Ngoài ra kiểm tra trên các câu hỏi
thật đã dùng ở nơi khác (ví dụ gợi ý trong giao diện, bộ câu hỏi truy xuất): không được từ chối nhầm câu nào.
"""
import sys
from collections import Counter

from sklearn.metrics import classification_report, confusion_matrix

from ..rag.text import accent_free
from .dataset import LABELS, build
from .intent import OOS, REFUSE_THRESHOLD, IntentClassifier, fit

REAL_IN_SCOPE = [
    "Doanh thu thuần quý 1/2026 là bao nhiêu và tăng bao nhiêu so với cùng kỳ?", "Biên lợi nhuận gộp quý 2/2026 so với quý 2/2025?",
    "Tổng tài sản và nợ phải trả tại 30/6/2026?", "ROE 6 tháng đầu năm 2026 là bao nhiêu?", "Dòng tiền từ hoạt động kinh doanh quý 4/2025?",
    "bao cao tai chinh quy 3 2025", "doanh thu quý 1 năm 2025", "Lợi nhuận sau thuế quý 2 năm 2026?", "Tổng tài sản tại ngày 31/12/2025",
    "Chi phí lãi vay Q1/2025 trong thuyết minh chi phí tài chính", "Dự phòng trợ cấp thôi việc quý 1 năm 2026", "Hàng tồn kho cuối quý 2/2025",
    "Công ty lời bao nhiêu trước khi đóng thuế quý 1/2026?", "Lượng tiền công ty đang nắm giữ cuối quý 3/2025", "Tổng nợ của công ty tại 31/12/2025",
]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    d = build()
    print(f"train: {len(d['train'])} câu {dict(Counter(l for _, l in d['train']))}")
    print(f"test : {len(d['test'])} câu {dict(Counter(l for _, l in d['test']))}")
    clf = IntentClassifier(fit(d["train"]))
    X = [q for q, _ in d["test"]]
    y = [l for _, l in d["test"]]
    pred = [clf.predict(q)[0] for q in X]
    print("\n" + classification_report(y, pred, labels=LABELS, digits=3, zero_division=0))
    print("ma trận nhầm lẫn (hàng = thật, cột = dự đoán):", LABELS)
    print(confusion_matrix(y, pred, labels=LABELS))

    refused = [(q, l) for q, l in d["test"] if clf.is_out_of_scope(q)]
    wrong = [q for q, l in refused if l != OOS]
    oos_total = sum(1 for _, l in d["test"] if l == OOS)
    print(f"\nNgưỡng từ chối {REFUSE_THRESHOLD}: từ chối {len(refused)} câu, trong đó nhầm câu hợp lệ: {len(wrong)}/{len(d['test']) - oos_total}; "
          f"bắt được ngoài phạm vi: {len(refused) - len(wrong)}/{oos_total}")
    for q in wrong[:10]:
        print("  nhầm:", q)

    real = REAL_IN_SCOPE + [accent_free(q) for q in REAL_IN_SCOPE]
    oos_p = [clf.predict_proba(q).get(OOS, 0.0) for q, l in d["test"] if l == OOS]
    in_p = [clf.predict_proba(q).get(OOS, 0.0) for q, l in d["test"] if l != OOS]
    real_p = [clf.predict_proba(q).get(OOS, 0.0) for q in real]
    print("\nQuét ngưỡng từ chối (câu ngoài phạm vi bắt được / câu hợp lệ bị từ chối nhầm trong test / trong câu thật):")
    for t in (0.5, 0.6, 0.7, 0.8, 0.9):
        print(f"  {t}: {sum(p >= t for p in oos_p)}/{len(oos_p)} | {sum(p >= t for p in in_p)}/{len(in_p)} | {sum(p >= t for p in real_p)}/{len(real_p)}")

    bad = [q for q in real if clf.is_out_of_scope(q)]
    print(f"Câu hỏi thật hợp lệ bị từ chối nhầm: {len(bad)}/{len(real)}")
    for q in bad:
        print("  nhầm:", q)


if __name__ == "__main__":
    main()
