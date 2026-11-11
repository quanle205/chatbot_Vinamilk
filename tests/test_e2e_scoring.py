"""Kiểm thử bộ chấm điểm đầu-cuối (eval/e2e_eval.py) và bộ câu hỏi vàng, không gọi mạng. Chạy: python tests/test_e2e_scoring.py

Ý tưởng "oracle": với mỗi câu vàng, gọi đúng công cụ kỳ vọng và dùng nguyên văn kết quả công cụ làm câu trả lời.
Câu trả lời lý tưởng đó phải được chấm 100%: nếu không, golden set hoặc bộ chấm sai. Sau đó thêm các phép thử đối chứng
(sai số, sai kỳ, số bịa, không từ chối, từ chối nhầm) phải bị chấm là SAI, để bộ chấm không "dễ dãi".
"""
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agent.agent import REFUSAL_TEXT, AgentResult, ToolCall  # noqa: E402
from src.agent.answer import used_sources  # noqa: E402
from src.agent.guard import find_unsupported_numbers  # noqa: E402
from src.agent.toolbox import Toolbox, result_for_model  # noqa: E402

spec = importlib.util.spec_from_file_location("e2e_eval", ROOT / "eval" / "e2e_eval.py")
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)

TOOLBOX = Toolbox()
CASES = ev.load_golden()
VALID = ev.load_golden(ROOT / "eval" / "validation.jsonl")


def make_call(name, args):
    out = TOOLBOX.run(name, args)
    text, err = result_for_model(out)
    return ToolCall(name, args, not err, text, out)


def finish(answer, calls, stop="STOP"):
    res = AgentResult(answer=answer, tool_calls=calls, stop_reason=stop)
    res.unsupported_numbers = find_unsupported_numbers(answer, [c.result for c in calls])
    res.sources = used_sources(answer, calls)
    return res


def oracle(case):
    """Câu trả lời lý tưởng cho một câu vàng."""
    beh = case["behavior"]
    if beh == "refuse":
        return finish(REFUSAL_TEXT, [], "OUT_OF_SCOPE")
    if beh == "no_data":
        return finish("Mình không có dữ liệu cho kỳ này; dữ liệu chỉ gồm Q1/2025 đến Q2/2026.", [])
    tool = case["expect_tool"][0]
    args = dict(case["expect_args"])
    if tool == "search_documents":
        args = {"query": case["question"], "period": args["period"]}
    elif tool == "get_ratio":
        args["ratio"] = args.pop("ratio")
    c = make_call(tool, args)
    return finish(c.text, [c])


def test_golden_file_is_well_formed():
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids)) and len(CASES) >= 80
    cats = {c["category"] for c in CASES}
    assert {"tra_so", "ty_so", "tang_truong", "xu_huong", "giai_thich", "thuyet_minh", "ngoai_pham_vi", "ngoai_du_lieu"} <= cats
    for c in CASES:
        assert c["behavior"] in ("answer", "refuse", "no_data")
        if "expect_values" in c:
            assert c["expect_values"] and c.get("min_values", 1) <= len(c["expect_values"])


def test_oracle_answers_score_perfectly():
    bad = []
    for c in CASES + VALID:
        s = ev.score_case(c, oracle(c))
        if not s["pass"]:
            bad.append((c["id"], {k: v for k, v in s.items() if v is False or k == "halluc" and v}))
    assert not bad, bad


def test_wrong_number_is_caught():
    case = next(c for c in CASES if c["id"] == "tra_so-01")
    call = make_call("get_metric", dict(case["expect_args"]))
    res = finish("Doanh thu thuần quý 1/2026 là 15.000,0 tỷ đồng.", [call])
    s = ev.score_case(case, res)
    assert s["number"] is False and s["halluc"] is True and not s["pass"]


def test_wrong_period_or_metric_is_caught():
    case = next(c for c in CASES if c["id"] == "tra_so-01")
    for args in ({**case["expect_args"], "period": "Q2/2026"}, {**case["expect_args"], "metric": "gia_von"}):
        call = make_call("get_metric", args)
        s = ev.score_case(case, finish(call.text, [call]))
        assert s["tool"] is False and not s["pass"], args


def test_missing_tool_call_is_caught():
    case = next(c for c in CASES if c["id"] == "tra_so-01")
    s = ev.score_case(case, finish("Khoảng 16.148,7 tỷ đồng.", []))
    assert s["tool"] is False and s["halluc"] is True and not s["pass"]


def test_refusal_checks():
    case = next(c for c in CASES if c["category"] == "ngoai_pham_vi")
    ok = ev.score_case(case, finish(REFUSAL_TEXT, [], "OUT_OF_SCOPE"))
    assert ok["pass"] and ok["refused_by"] == "bộ phân loại"
    leaked = ev.score_case(case, finish("Giá cổ phiếu VNM là 61.500 đồng.", []))
    assert leaked["refuse"] is False and not leaked["pass"]


def test_over_refusal_is_counted():
    case = next(c for c in CASES if c["id"] == "tra_so-01")
    s = ev.score_case(case, finish(REFUSAL_TEXT, [], "OUT_OF_SCOPE"))
    assert s["overrefuse"] is True and not s["pass"]


def test_no_data_must_not_invent_numbers():
    case = next(c for c in CASES if c["category"] == "ngoai_du_lieu")
    assert ev.score_case(case, finish("Không có dữ liệu cho kỳ này.", []))["pass"]
    assert not ev.score_case(case, finish("Doanh thu khoảng 17.000,5 tỷ đồng.", []))["pass"]


def test_summary_and_wilson():
    lo, hi = ev.wilson(86, 86)
    assert 0.95 < lo < 1.0 and hi == 1.0
    assert ev.wilson(0, 0) == (0.0, 0.0)
    rs = [{"id": "a", "category": "x", "pass": True, "halluc": False, "overrefuse": False, "tool": True, "latency_s": 1.0, "usage": {"input_tokens": 5, "output_tokens": 2}},
          {"id": "b", "category": "x", "pass": False, "error": "boom", "latency_s": 3.0}]
    s = ev.summarize(rs)
    assert s["pass"] == (1, 1) and s["errors"] == 1 and s["metrics"]["tool"] == (1, 1)


def test_golden_and_holdout_do_not_leak_into_training():
    """Câu vàng và tập giữ lại không được trùng câu huấn luyện của bộ phân loại, nếu không số đo bị thổi phồng."""
    from src.rag.text import accent_free, normalize
    from src.train.dataset import build, build_holdout

    def key(q):
        return accent_free(normalize(q)).strip(" ?.!").lower()
    d = build()
    seen = {key(q) for q, _ in d["train"] + d["test"]}
    golden_q = {key(c["question"]) for c in CASES}
    assert not (golden_q & seen), sorted(golden_q & seen)
    valid_q = {key(c["question"]) for c in VALID}
    assert not (valid_q & seen), sorted(valid_q & seen)
    assert not (valid_q & golden_q), "tập kiểm chứng trùng golden: mất tính độc lập"
    assert len(VALID) >= 40
    holdout_q = {key(q) for q, _ in build_holdout()}
    assert not (holdout_q & {key(q) for q, _ in d["train"] + d["test"]}), "tập giữ lại trùng dữ liệu huấn luyện"


def test_intent_filter_has_no_false_refusals_on_golden():
    """Bộ lọc ý định trong sản phẩm không được từ chối nhầm câu hợp lệ nào trong bộ vàng."""
    from src.train.intent import get_classifier
    clf = get_classifier()
    wrong = [c["question"] for c in CASES + VALID if c["behavior"] != "refuse" and clf.is_out_of_scope(c["question"])]
    assert not wrong, wrong


if __name__ == "__main__":
    fns = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for n, f in fns:
        try:
            f()
            print("PASS", n)
        except Exception as e:                                             # noqa: BLE001
            failed += 1
            print("FAIL", n, "->", repr(e)[:600])
    sys.exit(1 if failed else 0)
