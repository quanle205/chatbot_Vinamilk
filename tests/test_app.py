"""Kiểm thử giao diện Streamlit ngoại tuyến (AppTest), dùng client Gemini giả. Chạy: python tests/test_app.py"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import streamlit as st  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

import src.agent.agent as agent_mod  # noqa: E402
from test_agent import FakeClient, call, resp, text  # noqa: E402

APP = str(ROOT / "app" / "streamlit_app.py")
ORIGINAL_MAKE_CLIENT = agent_mod.make_client


def fresh(script=None, **env):
    st.cache_resource.clear()
    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "SESSION_LIMIT", "DAILY_LIMIT"):
        os.environ.pop(k, None)
    os.environ.update(env)
    agent_mod.make_client = (lambda: FakeClient(script)) if script is not None else ORIGINAL_MAKE_CLIENT
    return AppTest.from_file(APP, default_timeout=60).run()


def all_text(at):
    return " ".join([m.value for m in at.markdown] + [e.value for e in at.error] + [w.value for w in at.warning]
                    + [s.value for s in at.success])


def test_loads_and_lookup_tab_works_without_llm():
    at = fresh()
    assert not at.exception and len(at.tabs) == 2
    assert at.success and "Doanh thu thuần quý 2/2026: 18.847.347.464.988" in at.success[0].value   # mặc định, tra trực tiếp


def test_chat_without_key_shows_friendly_message():
    at = fresh()
    at.chat_input[0].set_value("Doanh thu Q1/2026?").run()
    assert not at.exception
    assert "chưa cấu hình khóa Gemini" in all_text(at) and "GEMINI_API_KEY" in all_text(at)


def test_chat_with_agent_shows_answer_sources_and_warning():
    script = [resp([call("get_metric", metric="doanh thu thuần", period="Q1/2026")]),
              resp([text("Doanh thu thuần quý 1/2026 là 16.148,7 tỷ đồng, lợi nhuận 99.999 tỷ.")])]
    at = fresh(script, GEMINI_API_KEY="demo")
    at.chat_input[0].set_value("Doanh thu Q1/2026?").run()
    assert not at.exception
    body = all_text(at)
    assert "16.148,7 tỷ đồng" in body and "không khớp" in body and "99.999" in body       # số bịa bị cảnh báo
    assert any("Công cụ đã dùng" in e.label for e in at.expander)


def test_session_limit_and_api_errors_are_handled():
    class RateLimit(Exception):
        code = 429
    at = fresh([RateLimit("quota")] * 5, GEMINI_API_KEY="demo", SESSION_LIMIT="2")   # chính + 2 dự phòng đều hết hạn mức
    at.chat_input[0].set_value("câu 1").run()
    assert not at.exception and "hết hạn mức miễn phí" in all_text(at) and "quota" not in all_text(at)
    at.session_state["asked"] = 2
    at.chat_input[0].set_value("câu 2").run()
    assert "hết 2 lượt hỏi" in all_text(at)


def test_server_error_shows_code_and_message_but_retries_first():
    class Overloaded(Exception):
        code, status, message = 503, "UNAVAILABLE", "The model is overloaded. Please try again later."
    agent_mod.time.sleep = lambda s: None                                     # không chờ thật giữa các lần thử
    at = fresh([Overloaded()] * 20, GEMINI_API_KEY="demo")                    # mọi mô hình (chính + dự phòng) đều bận
    at.chat_input[0].set_value("câu hỏi").run()
    body = all_text(at)
    assert not at.exception and "quá tải" in body and "503 UNAVAILABLE" in body and "overloaded" in body


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
