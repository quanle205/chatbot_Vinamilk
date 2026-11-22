"""Kiểm thử bộ đánh giá nhánh công ty: tính độc lập của hai tập, bộ chấm có thật sự bắt lỗi, và chặn hồi quy. Chạy: python tests/test_company_eval.py"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))

import company_eval as ce  # noqa: E402


def load(name):
    return [json.loads(line) for line in (ROOT / "eval" / name).read_text(encoding="utf-8").splitlines() if line.strip()]


def test_dev_and_validation_sets_are_disjoint_and_complete():
    dev, val = load("golden_companies.jsonl"), load("validation_companies.jsonl")
    assert len(dev) >= 60 and len(val) >= 60
    assert not ({c["question"] for c in dev} & {c["question"] for c in val})
    assert not ({c["id"] for c in dev} & {c["id"] for c in val})
    categories = {c["category"] for c in dev}
    assert categories == {c["category"] for c in val} and len(categories) >= 12      # cùng các nhóm câu hỏi ở cả hai tập
    for case in dev + val:
        assert case["behavior"] in {"answer", "refuse", "no_data"}
        if case["behavior"] == "answer":
            assert case["contains"], case["id"]                                       # câu trả lời số liệu phải có đáp án để chấm
    # Không hỏi cùng một dữ kiện ở hai tập: với tra số, mỗi đáp án (số VND) chỉ xuất hiện ở một tập
    numbers = lambda rows: {t for c in rows if c["category"] == "tra_so" for t in c["contains"]}      # noqa: E731
    assert not (numbers(dev) & numbers(val))


def test_scorer_catches_the_failures_it_is_meant_to_catch():
    case = {"id": "x", "category": "tra_so", "question": "q", "behavior": "answer", "contains": ["1.863,8"], "absent": ["Bạn muốn xem"],
            "any_of": [], "expect_sources": True}
    good = ce.score(case, {"answer": "KIDO 1.863,8 tỷ đồng", "sources": [{"page": 9}]}, 200, 0.1)
    assert good["pass"], good
    assert not ce.score(case, {"answer": "KIDO 9,5 tỷ đồng", "sources": [{"page": 9}]}, 200, 0.1)["pass"]                 # sai số
    assert not ce.score(case, {"answer": "KIDO 1.863,8 tỷ đồng", "sources": []}, 200, 0.1)["pass"]                      # thiếu nguồn
    assert not ce.score(case, {"answer": "1.863,8 Bạn muốn xem nợ nào", "sources": [{"page": 9}]}, 200, 0.1)["pass"]     # hỏi lại nhầm
    assert not ce.score(case, {"answer": "1.863,8 tỷ; Doanh thu thuan 12,615,062,955,827", "sources": [{"page": 9}]}, 200, 0.1)["pass"]  # lẫn chữ OCR thô
    assert not ce.score(case, {"detail": "lỗi"}, 503, 0.1)["pass"]
    refuse = {"id": "r", "category": "ngoai_pham_vi", "question": "q", "behavior": "refuse", "contains": [], "absent": [],
              "any_of": ["chỉ trả lời"], "expect_sources": False}
    assert ce.score(refuse, {"answer": "Mình chỉ trả lời về số liệu. Dự báo năm 2027."}, 200, 0.1)["pass"]             # "2027." không phải số tiền
    assert not ce.score(refuse, {"answer": "Chỉ trả lời... doanh thu 1.863,8 tỷ"}, 200, 0.1)["pass"]
    low, high = ce.wilson(69, 69)
    assert 0.94 < low < 1.0 and high == 1.0


def test_company_branch_has_no_regression_on_both_sets():
    for name in ("golden_companies.jsonl", "validation_companies.jsonl"):
        results = ce.run(load(name))
        failed = [(r["id"], r["failures"]) for r in results if not r["pass"]]
        assert len(failed) <= 2, failed                                                    # hạn mức hồi quy: tối đa 2 câu sai mỗi tập (thực tế hiện 0)
        assert all(r["seconds"] < 5 for r in results)                                        # nhánh quy tắc phải trả lời nhanh


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception as e:                                              # noqa: BLE001
                fails += 1
                print(f"FAIL {name}: {type(e).__name__}: {e}")
    sys.exit(1 if fails else 0)
