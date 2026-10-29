"""Kiểm thử agent bằng client Gemini giả (không gọi mạng, không tốn hạn mức). Chạy: python tests/test_agent.py

Chỉ kiểm tra phần mã của mình: vòng lặp function-calling, gom nguồn, bảo vệ số liệu, xử lý lỗi/chặn/hết bước.
KHÔNG kiểm tra chất lượng câu trả lời của Gemini thật, cũng không kiểm tra server chấp nhận schema công cụ;
việc đó cần khóa GEMINI_API_KEY thật.
"""
import os
import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from google.genai import types  # noqa: E402

from src.agent.agent import REFUSAL_TEXT, AgentConfigError, VinamilkAgent, _clean_schema, make_client  # noqa: E402
from src.agent.guard import find_unsupported_numbers, numbers_in_text  # noqa: E402
from src.agent.prompts import SYSTEM_PROMPT  # noqa: E402
from src.agent.toolbox import Toolbox  # noqa: E402

USAGE = NS(prompt_token_count=100, candidates_token_count=20)


def text(t):
    return types.Part(text=t)


def call(name, **args):
    return types.Part.from_function_call(name=name, args=args)


def resp(parts, finish="STOP"):
    return NS(candidates=[NS(content=types.Content(role="model", parts=parts), finish_reason=NS(name=finish))],
              usage_metadata=USAGE)


class FakeClient:
    def __init__(self, script):
        self.script, self.calls = list(script), []
        self.models = self

    def generate_content(self, **kw):
        # chụp nội dung ngay lúc gọi: agent sẽ rút gọn lịch sử sau khi trả lời xong
        self.calls.append({**kw, "contents": list(kw["contents"]), "n_contents": len(kw["contents"])})
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def agent(script, **kw):
    kw.setdefault("fallback_models", ())                  # mặc định không có mô hình dự phòng để kịch bản dễ đoán
    return VinamilkAgent(client=FakeClient(script), toolbox=kw.pop("toolbox", Toolbox(retriever=object())), **kw)


def test_parallel_tool_calls_loop_and_sources():
    a = agent([resp([text("Để mình tra."), call("get_metric", metric="doanh thu thuần", period="Q1/2026"),
                     call("get_growth", metric="doanh thu thuần", period="Q1/2026", kind="yoy")]),
               resp([text("Doanh thu thuần quý 1/2026 là 16.148,7 tỷ đồng, tăng 24,6% so với cùng kỳ.")])])
    hist = []
    r = a.ask("Doanh thu thuần Q1/2026 và tăng trưởng?", hist)
    assert r.answer.startswith("Doanh thu thuần quý 1/2026") and r.steps == 2 and r.stop_reason == "STOP"
    assert [t.name for t in r.tool_calls] == ["get_metric", "get_growth"] and all(t.ok for t in r.tool_calls)
    assert r.unsupported_numbers == [] and r.warnings == []
    assert {s["doc"] for s in r.sources} == {"q1-2026"} and any(s["page"] == 11 for s in r.sources)
    # ở bước 2, nội dung gửi đi: user, model(gọi hàm), user(kết quả); mọi kết quả hàm nằm trong MỘT lượt user
    sent = a.client.calls[1]["contents"]
    assert [c.role for c in sent] == ["user", "model", "user"]
    assert [p.function_response.name for p in sent[2].parts] == ["get_metric", "get_growth"]
    assert "output" in sent[2].parts[0].function_response.response
    # xong câu hỏi, lịch sử chỉ còn hỏi + đáp dạng văn bản (không còn chữ ký suy luận hay kết quả hàm)
    assert [c.role for c in hist] == ["user", "model"]
    assert hist[1].parts[0].text == r.answer and not any(p.function_call or p.function_response for c in hist for p in c.parts)
    assert r.model == "gemini-3.8-flash"
    cfg = a.client.calls[0]["config"]
    assert a.client.calls[0]["model"] == "gemini-3.8-flash" and cfg.system_instruction == SYSTEM_PROMPT
    assert cfg.automatic_function_calling.disable is True
    decls = {d.name: d for d in cfg.tools[0].function_declarations}
    assert set(decls) >= {"get_metric", "get_ratio", "get_growth", "search_documents", "calculate"}
    assert set(decls["get_metric"].parameters_json_schema["properties"]) == {"metric", "period", "basis"}
    assert r.usage == {"input_tokens": 200, "output_tokens": 40}


def test_multi_turn_history_is_append_only():
    a = agent([resp([text("Câu 1")]), resp([text("Câu 2")])])
    hist = []
    a.ask("a", hist)
    snapshot = list(hist)
    a.ask("b", hist)
    assert hist[:2] == snapshot and len(hist) == 4 and a.client.calls[1]["n_contents"] == 3


def test_unsupported_number_is_flagged():
    a = agent([resp([call("get_metric", metric="doanh thu thuần", period="Q1/2026")]),
               resp([text("Doanh thu là 16.500 tỷ đồng.")])])
    assert a.ask("q").unsupported_numbers == ["16.500"]


def test_tool_error_is_reported_as_error_result():
    a = agent([resp([call("get_metric", metric="doanh thu thuần", period="Q3/2026")]),
               resp([text("Chưa có báo cáo quý 3/2026.")])])
    r = a.ask("Doanh thu Q3/2026?", [])
    fr = a.client.calls[1]["contents"][2].parts[0].function_response.response
    assert fr["error"].startswith("LỖI:") and not r.tool_calls[0].ok and r.sources == []


def test_unknown_tool_does_not_crash():
    a = agent([resp([call("xoa_du_lieu", x=1)]), resp([text("Xong")])])
    a.ask("q", [])
    assert "error" in a.client.calls[1]["contents"][2].parts[0].function_response.response


def test_max_steps_stops_loop_with_warning():
    loop = [resp([call("get_metric", metric="tong tai san", period="Q1/2026")]) for _ in range(3)]
    r = agent(loop, max_steps=3).ask("q")
    assert r.steps == 3 and any("hết 3 bước" in w for w in r.warnings) and r.answer


def test_exception_rolls_back_history():
    a = agent([RuntimeError("mạng lỗi")])
    hist = [types.Content(role="user", parts=[text("cũ")]), types.Content(role="model", parts=[text("cũ")])]
    try:
        a.ask("mới", hist)
        raise AssertionError("phải ném lỗi")
    except RuntimeError:
        pass
    assert len(hist) == 2


def test_blocked_and_max_tokens():
    blocked = NS(candidates=[NS(content=None, finish_reason=NS(name="SAFETY"))], usage_metadata=USAGE)
    r = agent([blocked]).ask("q")
    assert r.answer == REFUSAL_TEXT and r.warnings
    r = agent([NS(candidates=[], usage_metadata=USAGE)]).ask("q")                  # prompt bị chặn: không có ứng viên
    assert r.answer == REFUSAL_TEXT
    r = agent([resp([text("dở dang")], finish="MAX_TOKENS")]).ask("q")
    assert r.answer == "dở dang" and any("cắt" in w for w in r.warnings)


class HttpError(Exception):
    def __init__(self, code):
        super().__init__(f"{code} loi")
        self.code = code


def test_transient_server_errors_are_retried():
    a = agent([HttpError(503), HttpError(500), resp([text("Đã có kết quả.")])], retry_delays=(0, 0, 0))
    r = a.ask("q")
    assert r.answer == "Đã có kết quả." and len(a.client.calls) == 3
    a = agent([HttpError(503)] * 4, retry_delays=(0, 0, 0))                       # hỏng dai dẳng: thử 1 + 3 lần rồi ném lỗi
    try:
        a.ask("q")
        raise AssertionError("phải ném lỗi sau khi hết lần thử")
    except HttpError:
        pass
    assert len(a.client.calls) == 4
    a = agent([HttpError(429)], retry_delays=(0, 0, 0))                           # 429/400 không thử lại ngay
    try:
        a.ask("q")
    except HttpError:
        pass
    assert len(a.client.calls) == 1


def test_falls_back_to_next_model_when_primary_is_overloaded():
    script = [HttpError(503)] * 3 + [resp([text("Từ mô hình dự phòng.")])]               # chính: 1 + 2 lần thử rồi bỏ
    a = agent(script, model="chinh", fallback_models=("du-phong",), retry_delays=(0, 0))
    r = a.ask("q")
    assert r.answer == "Từ mô hình dự phòng." and r.model == "du-phong"
    assert [c["model"] for c in a.client.calls] == ["chinh", "chinh", "chinh", "du-phong"]


def test_quota_or_missing_model_falls_through_but_bad_request_does_not():
    a = agent([HttpError(429), HttpError(404), resp([text("ok")])], model="a", fallback_models=("b", "c"))
    assert a.ask("q").model == "c" and len(a.client.calls) == 3                           # 429, 404 không thử lại, sang tiếp
    a = agent([HttpError(400)], model="a", fallback_models=("b",))
    try:
        a.ask("q")
        raise AssertionError("400 phải ném lỗi ngay")
    except HttpError:
        pass
    assert len(a.client.calls) == 1
    a = agent([HttpError(503)] * 8, model="a", fallback_models=("b",), retry_delays=(0, 0))   # mọi mô hình hỏng: ném lỗi đầu tiên
    try:
        a.ask("q")
        raise AssertionError("hết mô hình phải ném lỗi")
    except HttpError as e:
        assert e.code == 503


def test_model_is_pinned_within_one_question_and_failed_model_rests_for_the_next():
    script = [HttpError(503)] * 3 + [resp([call("get_metric", metric="tong tai san", period="Q1/2026")]),
                                     resp([text("Xong.")]),                               # bước 2 vẫn phải là "du-phong"
                                     resp([text("Câu sau.")])]                           # mô hình chính vừa hỏng nên nghỉ vài phút, câu sau dùng dự phòng
    a = agent(script, model="chinh", fallback_models=("du-phong",), retry_delays=(0, 0))
    a.ask("q1", hist := [])
    assert [c["model"] for c in a.client.calls] == ["chinh", "chinh", "chinh", "du-phong", "du-phong"]
    a.ask("q2", hist)
    assert a.client.calls[-1]["model"] == "du-phong" and a.client.calls[-1]["n_contents"] == 3


def test_thought_parts_are_not_shown():
    thought = types.Part(text="suy nghĩ nội bộ", thought=True)
    assert agent([resp([thought, text("Câu trả lời.")])]).ask("q").answer == "Câu trả lời."


def test_search_documents_with_real_retriever():
    tb = Toolbox()                                              # dựng chỉ mục từ data/processed/chunks.jsonl
    out = tb.run("search_documents", {"query": "Vay ngắn hạn 30/6/2025", "period": "Q2/2025", "k": 3})
    assert out["ok"] and all(s["doc"] == "q2-2025" for s in out["sources"]) and "mã số 320" in out["text"]
    assert not tb.run("search_documents", {})["ok"]
    assert not tb.run("search_documents", {"query": "x", "period": "hôm qua"})["ok"]
    assert tb.run("get_metric", {"metric": "tổng tài sản", "period": "Q2/2026"})["ok"]


def test_schema_cleaning_keeps_parameter_names_and_drops_unsupported_keys():
    s = {"type": "object", "required": ["query"], "additionalProperties": False, "properties": {
        "query": {"type": "string", "description": "d"},
        "k": {"type": "integer", "minimum": 1, "maximum": 8, "default": 5},
        "type": {"type": "string", "enum": ["a", "b"]}}}                      # tham số tên "type" không bị lọc nhầm
    out = _clean_schema(s)
    assert set(out["properties"]) == {"query", "k", "type"} and "additionalProperties" not in out
    assert out["properties"]["k"] == {"type": "integer", "minimum": 1, "maximum": 8}
    assert out["properties"]["type"]["enum"] == ["a", "b"]


def test_guard():
    assert numbers_in_text("Doanh thu 16.148,7 tỷ, tăng 24,6%, mã 10, năm 2026") == [16148.7, 24.6]
    tools = [{"value": 16_148_657_871_623, "growth": 0.246282, "text": "tăng 3.191,1 tỷ đồng"}]
    assert find_unsupported_numbers("16.148,7 tỷ; 24,6%; 3.191,1 tỷ; 16.148.657.871.623 VND", tools) == []
    assert find_unsupported_numbers("16.200,0 tỷ; 25,9%", tools) == ["16.200,0", "25,9"]
    assert find_unsupported_numbers("Quý 1/2026, mã số 10, năm 2025, 12 tháng", tools) == []


def test_make_client_needs_api_key():
    keys = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
    saved = {k: os.environ.pop(k, None) for k in keys}
    try:
        try:
            make_client()
            raise AssertionError("phải báo thiếu khóa")
        except AgentConfigError:
            pass
        os.environ["GEMINI_API_KEY"] = "khoa-gia"
        assert type(make_client()).__name__ == "Client"
    finally:
        os.environ.pop("GEMINI_API_KEY", None)
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


def test_system_prompt_lists_all_six_periods():
    from src.agent.prompts import SYSTEM_PROMPT
    for q in ("Q1/2025", "Q2/2025", "Q3/2025", "Q4/2025", "Q1/2026", "Q2/2026"):
        assert q in SYSTEM_PROMPT


def test_deadline_stops_retries_and_raises():
    a = agent([], deadline_s=0.0001)
    import time as _t
    _t.sleep(0.01)
    try:
        a._deadline = _t.monotonic() - 1
        a._generate([], None)
    except TimeoutError:
        return
    raise AssertionError("đáng lẽ phải hết thời gian")


def test_timeout_504_skips_retries_and_model_cools_down():
    class Err(Exception):
        code = 504

    a = agent([], fallback_models=("b",), retry_delays=(0, 0))
    ok = resp([text("ok")])
    a.client.script = [Err("deadline"), ok, ok]
    first = a._generate([], None)
    assert first[0] == "b" and len(a.client.calls) == 2                    # 504: không thử lại mô hình chính, sang thẳng mô hình b
    second = a._generate([], None)
    assert second[0] == "b" and len(a.client.calls) == 3                   # mô hình chính đang "nghỉ", không gọi lại


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
