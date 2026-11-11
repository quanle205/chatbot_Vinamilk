"""Đánh giá đầu-cuối chatbot trên bộ câu hỏi vàng eval/golden.jsonl (cần GEMINI_API_KEY thật).

Độ đo (mỗi câu chấm các tiêu chí áp dụng được; câu "đạt" khi qua hết):
  tool      gọi đúng công cụ với đúng tham số chính (mã chỉ tiêu/tỷ số, kỳ, kind, basis)
  number    câu trả lời nêu đúng số kỳ vọng (khớp theo độ chính xác người viết, mọi đơn vị VND/tỷ/%)
  source    nguồn trả kèm có (báo cáo, mã số) kỳ vọng
  text      (thuyết minh) kết quả truy xuất chứa đoạn chữ kỳ vọng
  refuse    câu ngoài phạm vi bị từ chối, không lộ số liệu
  no_data   câu hỏi kỳ không có dữ liệu: không bịa số, nói rõ là không có
  halluc    (tính trên mọi câu) số trong câu trả lời không khớp công cụ nào = bị guard gắn cờ
  overrefuse (tính trên câu hợp lệ) bị từ chối nhầm
Kèm độ trễ p50/p95, token, số lượt công cụ. Khoảng tin cậy Wilson 95% vì mẫu nhỏ.

Chạy:
  python eval/e2e_eval.py --limit 10              # thử nhanh
  python eval/e2e_eval.py                         # toàn bộ 86 câu
  python eval/e2e_eval.py --category tra_so --sleep 4
Báo cáo JSON (kèm câu trả lời từng câu để đọc lại lỗi) lưu ở eval/reports/.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agent.guard import NUM_RE, matches_pool, parse_vn  # noqa: E402
from src.rag.text import accent_free  # noqa: E402

GOLDEN = Path(__file__).with_name("golden.jsonl")
REPORTS = Path(__file__).with_name("reports")
NO_DATA_WORDS = re.compile(r"không có|chưa có|không cung cấp|không nằm|ngoài phạm vi|chỉ có dữ liệu|không tìm thấy", re.I)
REFUSAL_PREFIX = "Mình không thể trả lời"
RESULT_KEY = {"base": "base_kind"}           # tên tham số gọi -> tên trường trong kết quả công cụ


def load_golden(path: Path = GOLDEN) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def _same(a, b) -> bool:
    return str(a).strip().lower() == str(b).strip().lower()


def _is_balance(metric_key) -> bool:
    from src.tools.metrics import BY_KEY
    return bool(metric_key) and metric_key in BY_KEY and BY_KEY[metric_key].kind == "balance"


def check_tool(case: dict, calls: list) -> bool:
    """Có lệnh gọi thành công đúng tên công cụ và mọi tham số kỳ vọng (đối chiếu trên kết quả đã chuẩn hóa của công cụ)."""
    for c in calls:
        if not c.ok or c.name not in case["expect_tool"]:
            continue
        good = True
        for k, want in case.get("expect_args", {}).items():
            if c.name == "get_metric" and k == "kind":
                continue
            if k == "basis" and (c.result.get("basis") == "so_du" or _is_balance(c.result.get("metric"))):
                continue                      # chỉ tiêu số dư (bảng cân đối): quý/lũy kế không có nghĩa
            got = c.result.get(RESULT_KEY.get(k, k))
            if k == "period" and c.name == "search_documents":
                got = c.input.get("period")
                good = good and got is not None and want.replace("/", "").lower() in str(got).replace("/", "").lower()
                continue
            if got is None and k in c.input:
                got = c.input[k]
            if got is None or not _same(got, want):
                good = False
        if good:
            return True
    return False


def answer_numbers(answer: str) -> list[tuple[float, int]]:
    return [parse_vn(m.group(0)) for m in NUM_RE.finditer(answer)]


def check_numbers(case: dict, answer: str) -> tuple[bool, int]:
    nums = answer_numbers(answer)
    hits = sum(any(matches_pool(n, dec, [v]) for n, dec in nums) for v in case["expect_values"])
    need = case.get("min_values", len(case["expect_values"]))
    return hits >= need, hits


def check_sources(case: dict, sources: list) -> bool:
    have = {(s.get("doc"), str(s.get("code"))) for s in sources}
    return any((s["doc"], str(s["code"])) in have for s in case["expect_sources"])


def check_text(case: dict, calls: list) -> bool:
    needle = accent_free(case["expect_text"]).lower()
    return any(c.ok and c.name == "search_documents" and needle in accent_free(c.text).lower() for c in calls)


def is_refusal(res) -> bool:
    return res.stop_reason == "OUT_OF_SCOPE" or res.answer.startswith(REFUSAL_PREFIX)


def score_case(case: dict, res) -> dict:
    """Chấm một câu từ AgentResult. Hàm thuần (không gọi mạng) nên kiểm thử được bằng kết quả giả."""
    calls, ans = res.tool_calls, res.answer
    s: dict = {"halluc": bool(res.unsupported_numbers)}
    beh = case["behavior"]
    if beh == "refuse":
        ok_calls = [c for c in calls if c.ok]
        s["refuse"] = is_refusal(res) or (not ok_calls and not answer_numbers(ans))
        s["refused_by"] = "bộ phân loại" if res.stop_reason == "OUT_OF_SCOPE" else ("mô hình" if s["refuse"] else None)
    elif beh == "no_data":
        failed = any(not c.ok for c in calls)
        s["no_data"] = not answer_numbers(ans) and (failed or bool(NO_DATA_WORDS.search(ans)))
        s["overrefuse"] = False
    else:
        s["overrefuse"] = is_refusal(res)
        s["tool"] = check_tool(case, calls)
        if "expect_values" in case:
            s["number"], s["values_hit"] = check_numbers(case, ans)
        if "expect_sources" in case:
            s["source"] = check_sources(case, res.sources)
        if "expect_text" in case:
            s["text"] = check_text(case, calls)
    criteria = [k for k in ("tool", "number", "source", "text", "refuse", "no_data") if k in s]
    s["pass"] = all(s[k] for k in criteria) and not s["halluc"] and not s.get("overrefuse", False)
    return s


def run_case(agent, case: dict) -> dict:
    t0 = time.monotonic()
    try:
        res = agent.ask(case["question"])
    except Exception as e:                                    # noqa: BLE001 - lỗi mạng/hạn mức tính là một kết quả, không dừng cả lượt
        return {"id": case["id"], "category": case["category"], "question": case["question"], "error": f"{type(e).__name__}: {e}"[:300],
                "pass": False, "latency_s": round(time.monotonic() - t0, 2)}
    out = score_case(case, res)
    out.update(id=case["id"], category=case["category"], question=case["question"], answer=res.answer,
               tools=[c.name for c in res.tool_calls], stop=res.stop_reason, model=res.model, steps=res.steps,
               unsupported=res.unsupported_numbers, usage=res.usage, latency_s=round(time.monotonic() - t0, 2))
    return out


def pct(k: int, n: int) -> str:
    lo, hi = wilson(k, n)
    return f"{k}/{n} = {k / n:.0%} [CI95 {lo:.0%}–{hi:.0%}]" if n else "n/a"


def percentile(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))] if xs else 0.0


def summarize(results: list[dict]) -> dict:
    ok = [r for r in results if "error" not in r]
    cats: dict[str, list] = {}
    for r in results:
        cats.setdefault(r["category"], []).append(r)
    metrics = {}
    for k in ("tool", "number", "source", "text", "refuse", "no_data"):
        sub = [r for r in ok if k in r]
        metrics[k] = (sum(bool(r[k]) for r in sub), len(sub))
    answerable = [r for r in ok if "overrefuse" in r and r["category"] not in ("ngoai_du_lieu",)]
    lat = [r["latency_s"] for r in results]
    return {
        "n": len(results), "errors": len(results) - len(ok),
        "pass": (sum(r["pass"] for r in ok), len(ok)),                       # lỗi hạn mức/mạng không tính vào độ chính xác
        "by_category": {c: (sum(r["pass"] for r in rs if "error" not in r), sum("error" not in r for r in rs)) for c, rs in cats.items()},
        "metrics": metrics,
        "hallucination": (sum(r["halluc"] for r in ok), len(ok)),
        "overrefuse": (sum(r["overrefuse"] for r in answerable), len(answerable)),
        "models": dict(Counter(r.get("model", "") for r in ok)),
        "latency_p50": percentile(lat, 0.5), "latency_p95": percentile(lat, 0.95),
        "tokens_in": sum(r.get("usage", {}).get("input_tokens", 0) for r in ok),
        "tokens_out": sum(r.get("usage", {}).get("output_tokens", 0) for r in ok),
    }


def print_summary(s: dict) -> None:
    print(f"\n===== KẾT QUẢ ĐẦU-CUỐI ({s['n']} câu, {s['errors']} lỗi gọi) =====")
    print("Đạt toàn phần        :", pct(*s["pass"]))
    for c, (k, n) in s["by_category"].items():
        print(f"  - {c:15s}:", pct(k, n))
    labels = {"tool": "Chọn đúng công cụ+tham số", "number": "Đúng số liệu", "source": "Đúng nguồn trích dẫn", "text": "Truy xuất đúng đoạn thuyết minh",
              "refuse": "Từ chối đúng (ngoài phạm vi)", "no_data": "Không bịa khi thiếu dữ liệu"}
    for k, (hit, n) in s["metrics"].items():
        if n:
            print(f"{labels[k]:32s}:", pct(hit, n))
    print(f"{'Hallucination (số bị gắn cờ)':32s}:", pct(*s["hallucination"]), "(càng thấp càng tốt)")
    print(f"{'Từ chối nhầm câu hợp lệ':32s}:", pct(*s["overrefuse"]), "(càng thấp càng tốt)")
    print("Mô hình đã trả lời:", s.get("models"))
    print(f"Độ trễ p50/p95: {s['latency_p50']:.1f}s / {s['latency_p95']:.1f}s | token vào/ra: {s['tokens_in']}/{s['tokens_out']}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--golden", default=str(GOLDEN))
    ap.add_argument("--limit", type=int, help="chỉ chạy N câu đầu (đã trộn đều theo nhóm)")
    ap.add_argument("--category", action="append", help="chỉ chạy nhóm này (lặp được)")
    ap.add_argument("--sleep", type=float, default=2.0, help="nghỉ giữa các câu để không vượt hạn mức khóa miễn phí")
    ap.add_argument("--model", help="mô hình Gemini (mặc định như ứng dụng)")
    ap.add_argument("--no-intent-filter", action="store_true", help="tắt bộ phân loại từ chối sớm để đo riêng khả năng từ chối của mô hình")
    ap.add_argument("--no-fallback", action="store_true", help="không chuyển sang mô hình dự phòng: mô hình chỉ định lỗi thì ghi là lỗi, để số đo đúng là của mô hình đó")
    ap.add_argument("--out", help="đường dẫn báo cáo JSON")
    ap.add_argument("--errors-only", action="store_true", help="với --rerun: chỉ chạy lại câu lỗi gọi mạng/hạn mức, không chạy lại câu đã chấm (giữ nguyên điểm sạch)")
    ap.add_argument("--rerun", help="báo cáo JSON cũ: chỉ chạy lại các câu lỗi gọi hoặc chưa đạt rồi gộp kết quả vào báo cáo đó")
    a = ap.parse_args()

    cases = load_golden(Path(a.golden))
    previous: dict[str, dict] = {}
    if a.rerun:
        old = json.loads(Path(a.rerun).read_text(encoding="utf-8"))["results"]
        previous = {r["id"]: r for r in old}
        redo = {r["id"] for r in old if "error" in r or (not r["pass"] and not a.errors_only)}
        cases = [c for c in cases if c["id"] in redo]
    if a.category:
        cases = [c for c in cases if c["category"] in a.category]
    if a.limit:                                                # lấy xen kẽ giữa các nhóm để mẫu nhỏ vẫn đủ loại
        groups: dict[str, list] = {}
        for c in cases:
            groups.setdefault(c["category"], []).append(c)
        mixed = [g.pop(0) for _ in range(max(map(len, groups.values()))) for g in groups.values() if g]
        cases = mixed[: a.limit]

    from src.agent import AgentConfigError, VinamilkAgent        # noqa: E402
    from src.agent.agent import make_client                       # noqa: E402
    try:
        make_client()
    except AgentConfigError as e:
        sys.exit(f"{e}\nĐặt GEMINI_API_KEY (hoặc chạy qua chay.ps1 để nạp từ secrets.toml) rồi chạy lại.")
    agent = VinamilkAgent(model=a.model, deadline_s=45, intent_filter=not a.no_intent_filter,
                          fallback_models=() if a.no_fallback else None)

    results = []
    for i, case in enumerate(cases, 1):
        r = run_case(agent, case)
        results.append(r)
        flag = "OK " if r["pass"] else "SAI"
        print(f"[{i:3d}/{len(cases)}] {flag} {case['id']:16s} {r['latency_s']:5.1f}s  {case['question'][:60]}" + (f"  !! {r['error']}" if "error" in r else ""), flush=True)
        if a.sleep and i < len(cases):
            time.sleep(a.sleep)

    if previous:                                               # gộp: kết quả chạy lại thay thế kết quả cũ cùng id
        merged = {**previous, **{r["id"]: r for r in results}}
        results = [merged[c["id"]] for c in load_golden(Path(a.golden)) if c["id"] in merged]
    s = summarize(results)
    print_summary(s)
    REPORTS.mkdir(exist_ok=True)
    out = Path(a.out) if a.out else Path(a.rerun) if a.rerun else REPORTS / f"e2e-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps({"summary": s, "results": results}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("Báo cáo:", out)
    fails = [r for r in results if not r["pass"]]
    if fails:
        print("\nCác câu chưa đạt (xem answer trong báo cáo):")
        for r in fails[:15]:
            why = r.get("error") or [k for k in ("tool", "number", "source", "text", "refuse", "no_data") if k in r and not r[k]] + (["halluc"] if r.get("halluc") else []) + (["overrefuse"] if r.get("overrefuse") else [])
            print(f"  {r['id']:16s} {why}  {r['question'][:55]}")


if __name__ == "__main__":
    main()
