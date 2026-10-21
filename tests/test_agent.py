"""Kiểm thử agent bằng client giả (không gọi Claude thật, không tốn tiền). Chạy: python tests/test_agent.py

Chỉ kiểm tra phần mã của mình: vòng lặp tool-use, gom nguồn, bảo vệ số liệu, xử lý lỗi/từ chối/hết bước.
KHÔNG kiểm tra chất lượng câu trả lời của mô hình thật; việc đó cần gọi Vertex AI (xem README).
"""
import os
import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agent.agent import REFUSAL_TEXT, AgentConfigError, VinamilkAgent, make_client  # noqa: E402
from src.agent.guard import find_unsupported_numbers, numbers_in_text  # noqa: E402
from src.agent.prompts import SYSTEM_PROMPT  # noqa: E402
from src.agent.toolbox import Toolbox  # noqa: E402


def text(t):
    return NS(type="text", text=t)


def tool(id_, name, **inp):
    return NS(type="tool_use", id=id_, name=name, input=inp)


def resp(content, stop):
    return NS(content=content, stop_reason=stop, usage=NS(input_tokens=100, output_tokens=20))


class FakeClient:
    def __init__(self, script):
        self.script, self.calls = list(script), []
        self.messages = self

    def create(self, **kw):
        self.calls.append({**kw, "n_messages": len(kw["messages"])})
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def agent(script, **kw):
    return VinamilkAgent(client=FakeClient(script), toolbox=kw.pop("toolbox", Toolbox(retriever=object())), **kw)


def test_parallel_tool_calls_loop_and_sources():
    a = agent([resp([text("Để mình tra."), tool("t1", "get_metric", metric="doanh thu thuần", period="Q1/2026"),
                     tool("t2", "get_growth", metric="doanh thu thuần", period="Q1/2026", kind="yoy")], "tool_use"),
               resp([text("Doanh thu thuần quý 1/2026 là 16.148,7 tỷ đồng, tăng 24,6% so với cùng kỳ.")], "end_turn")])
    msgs = []
    r = a.ask("Doanh thu thuần Q1/2026 và tăng trưởng?", msgs)
    assert r.answer.startswith("Doanh thu thuần quý 1/2026") and r.steps == 2 and r.stop_reason == "end_turn"
    assert [t.name for t in r.tool_calls] == ["get_metric", "get_growth"] and all(t.ok for t in r.tool_calls)
    assert r.unsupported_numbers == [] and r.warnings == []
    assert {s["doc"] for s in r.sources} == {"q1-2026"} and any(s["page"] == 11 for s in r.sources)
    # tất cả tool_result trong MỘT tin nhắn user, đúng id; lịch sử: user, assistant, user(tool_result), assistant
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert [b["tool_use_id"] for b in msgs[2]["content"]] == ["t1", "t2"]
    first = a.client.calls[0]
    assert first["system"] == SYSTEM_PROMPT and first["model"] == "claude-opus-5-5"
    assert "tool_choice" not in first and "thinking" not in first and first["output_config"] == {"effort": "medium"}
    assert {t["name"] for t in first["tools"]} >= {"get_metric", "get_ratio", "get_growth", "search_documents", "calculate"}
    assert r.usage == {"input_tokens": 200, "output_tokens": 40}


def test_multi_turn_history_is_append_only():
    a = agent([resp([text("Câu 1")], "end_turn"), resp([text("Câu 2")], "end_turn")])
    msgs = []
    a.ask("a", msgs)
    snapshot = list(msgs)
    a.ask("b", msgs)
    assert msgs[:2] == snapshot and len(msgs) == 4 and a.client.calls[1]["n_messages"] == 3


def test_unsupported_number_is_flagged():
    a = agent([resp([tool("t1", "get_metric", metric="doanh thu thuần", period="Q1/2026")], "tool_use"),
               resp([text("Doanh thu là 16.500 tỷ đồng.")], "end_turn")])
    assert a.ask("q").unsupported_numbers == ["16.500"]


def test_tool_error_is_reported_as_error_result():
    a = agent([resp([tool("t1", "get_metric", metric="doanh thu thuần", period="Q3/2026")], "tool_use"),
               resp([text("Chưa có báo cáo quý 3/2026.")], "end_turn")])
    msgs = []
    r = a.ask("Doanh thu Q3/2026?", msgs)
    tr = msgs[2]["content"][0]
    assert tr["is_error"] is True and tr["content"].startswith("LỖI:") and not r.tool_calls[0].ok and r.sources == []


def test_unknown_tool_does_not_crash():
    a = agent([resp([tool("t1", "xoa_du_lieu", x=1)], "tool_use"), resp([text("Xong")], "end_turn")])
    msgs = []
    a.ask("q", msgs)
    assert msgs[2]["content"][0]["is_error"] is True


def test_max_steps_stops_loop_with_warning():
    loop = [resp([tool(f"t{i}", "get_metric", metric="tong tai san", period="Q1/2026")], "tool_use") for i in range(3)]
    r = agent(loop, max_steps=3).ask("q")
    assert r.steps == 3 and any("hết 3 bước" in w for w in r.warnings) and r.answer


def test_exception_rolls_back_history():
    a = agent([RuntimeError("mạng lỗi")])
    msgs = [{"role": "user", "content": "cũ"}, {"role": "assistant", "content": "cũ"}]
    try:
        a.ask("mới", msgs)
        raise AssertionError("phải ném lỗi")
    except RuntimeError:
        pass
    assert len(msgs) == 2


def test_refusal_and_max_tokens():
    r = agent([resp([], "refusal")]).ask("q")
    assert r.answer == REFUSAL_TEXT and r.warnings
    r = agent([resp([text("dở dang")], "max_tokens")]).ask("q")
    assert r.answer == "dở dang" and any("cắt" in w for w in r.warnings)


def test_search_documents_with_real_retriever():
    tb = Toolbox()                                              # nạp data/processed/retriever.pkl
    out = tb.run("search_documents", {"query": "Vay ngắn hạn 30/6/2025", "period": "Q2/2025", "k": 3})
    assert out["ok"] and all(s["doc"] == "q2-2025" for s in out["sources"]) and "mã số 320" in out["text"]
    assert not tb.run("search_documents", {})["ok"]
    assert not tb.run("search_documents", {"query": "x", "period": "hôm qua"})["ok"]
    assert tb.run("get_metric", {"metric": "tổng tài sản", "period": "Q2/2026"})["ok"]


def test_guard():
    assert numbers_in_text("Doanh thu 16.148,7 tỷ, tăng 24,6%, mã 10, năm 2026") == [16148.7, 24.6]
    tools = [{"value": 16_148_657_871_623, "growth": 0.246282, "text": "tăng 3.191,1 tỷ đồng"}]
    assert find_unsupported_numbers("16.148,7 tỷ; 24,6%; 3.191,1 tỷ; 16.148.657.871.623 VND", tools) == []
    assert find_unsupported_numbers("16.200,0 tỷ; 25,9%", tools) == ["16.200,0", "25,9"]
    assert find_unsupported_numbers("Quý 1/2026, mã số 10, năm 2025, 12 tháng", tools) == []


def test_make_client_needs_project():
    saved = {k: os.environ.pop(k, None) for k in ("ANTHROPIC_VERTEX_PROJECT_ID", "GOOGLE_CLOUD_PROJECT")}
    try:
        try:
            make_client()
            raise AssertionError("phải báo thiếu project")
        except AgentConfigError:
            pass
        os.environ["ANTHROPIC_VERTEX_PROJECT_ID"] = "demo-project"
        c = make_client()
        assert type(c).__name__ == "AnthropicVertex"
    finally:
        os.environ.pop("ANTHROPIC_VERTEX_PROJECT_ID", None)
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


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
