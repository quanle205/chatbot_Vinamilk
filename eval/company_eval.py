"""Chấm nhánh trả lời công ty (và các nhánh xác định của Vinamilk) trên tập câu hỏi do build_company_golden.py dựng.

Chạy offline: gọi thẳng /api/ask của ứng dụng (không cần khóa Gemini, không tốn hạn mức), nên kết quả lặp lại được.
Mỗi câu đạt khi: mọi chuỗi trong `contains` đều xuất hiện, không chuỗi nào trong `absent`, ít nhất một chuỗi trong `any_of` (nếu có), và
- câu trả lời có nguồn (trang PDF) khi `expect_sources`;
- câu từ chối (`refuse`) thực sự từ chối; câu thiếu số (`no_data`) nói rõ "Chưa có";
- không lẫn chữ OCR thô (số viết bằng dấu phẩy "12,615,062,955,827" hay từ "thuan"/"thuån") và không tự bịa ">= 4 nhóm số" ngoài số có thật.
Chạy: python eval/company_eval.py --golden eval/golden_companies.jsonl      (tập dev: để tìm lỗi)
      python eval/company_eval.py --golden eval/validation_companies.jsonl  (tập kiểm chứng: chỉ chấm, không sửa mã theo nó)
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OCR_NUMBERS = re.compile(r"\d{1,3}(,\d{3}){3,}")           # số OCR viết bằng dấu phẩy
OCR_WORDS = ("thuan", "thuån", "nhuan", "tong cong tai san")  # chữ OCR bỏ dấu lọt vào câu trả lời


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, centre - half), min(1.0, centre + half)


def score(case: dict, reply: dict, status: int, seconds: float) -> dict:
    answer = reply.get("answer") or reply.get("detail") or ""
    failures = []
    if status != 200:
        failures.append(f"HTTP {status}")
    failures += [f"thiếu: {text!r}" for text in case.get("contains", []) if text not in answer]
    failures += [f"không được có: {text!r}" for text in case.get("absent", []) if text in answer]
    if case.get("any_of") and not any(text in answer for text in case["any_of"]):
        failures.append(f"cần một trong: {case['any_of']}")
    if case.get("expect_sources") and not reply.get("sources"):
        failures.append("thiếu nguồn (trang PDF)")
    if case["behavior"] == "refuse" and re.search(r"\d{1,3}(?:[.,]\d{3})+", answer):
        failures.append("câu từ chối nhưng có nêu số")
    if case["behavior"] == "no_data" and "Chưa có" not in answer:
        failures.append("không nói rõ chưa có dữ liệu")
    if OCR_NUMBERS.search(answer) or any(word in answer for word in OCR_WORDS):
        failures.append("lẫn chữ OCR thô")
    return {"id": case["id"], "category": case["category"], "question": case["question"], "pass": not failures, "failures": failures,
            "seconds": round(seconds, 3), "answer": answer}


def run(cases: list[dict]) -> list[dict]:
    from fastapi.testclient import TestClient

    import api.index as api
    client = TestClient(api.app)
    results = []
    for case in cases:
        api.ASK_LIMIT.reset()
        api.BROWSE_LIMIT.reset()
        start = time.perf_counter()
        response = client.post("/api/ask", json={"question": case["question"]})
        results.append(score(case, response.json(), response.status_code, time.perf_counter() - start))
    return results


def summarize(results: list[dict]) -> dict:
    by_category = defaultdict(lambda: [0, 0])
    for r in results:
        by_category[r["category"]][1] += 1
        by_category[r["category"]][0] += r["pass"]
    ok = sum(r["pass"] for r in results)
    times = sorted(r["seconds"] for r in results)
    return {"n": len(results), "pass": ok, "ci95": wilson(ok, len(results)), "by_category": dict(by_category),
            "p50_s": times[len(times) // 2], "p95_s": times[int(len(times) * 0.95) - 1], "failed": [r for r in results if not r["pass"]],
            "failure_types": Counter(f.split(":")[0] for r in results for f in r["failures"])}


def print_summary(s: dict) -> None:
    lo, hi = s["ci95"]
    print(f"Đạt {s['pass']}/{s['n']} = {s['pass'] / s['n']:.0%} (CI95 {lo:.0%}-{hi:.0%}) | p50 {s['p50_s']:.2f}s, p95 {s['p95_s']:.2f}s")
    for category, (k, n) in sorted(s["by_category"].items()):
        print(f"  {category:14s} {k}/{n}")
    for r in s["failed"]:
        print(f"  SAI [{r['id']}] {r['question']}")
        for failure in r["failures"]:
            print(f"       - {failure}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--golden", default=str(ROOT / "eval/golden_companies.jsonl"))
    parser.add_argument("--out", help="ghi báo cáo JSON (kèm câu trả lời từng câu)")
    parser.add_argument("--min-pass", type=float, default=0.0, help="thoát mã 1 nếu tỷ lệ đạt thấp hơn ngưỡng (dùng trong CI)")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    cases = [json.loads(line) for line in Path(args.golden).read_text(encoding="utf-8").splitlines() if line.strip()]
    results = run(cases)
    summary = summarize(results)
    print_summary(summary)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps({"summary": {k: v for k, v in summary.items() if k != "failed"}, "results": results}, ensure_ascii=False, indent=1), encoding="utf-8")
    sys.exit(1 if summary["pass"] / summary["n"] < args.min_pass else 0)


if __name__ == "__main__":
    main()
