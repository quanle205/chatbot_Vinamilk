"""Kiểm thử hỏi lại khi câu mơ hồ và bằng chứng cho mọi nguồn dẫn. Không gọi mạng. Chạy: python tests/test_clarify.py"""
import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from google.genai import types  # noqa: E402

from src.agent.agent import VinamilkAgent  # noqa: E402
from src.agent.clarify import needs_clarification  # noqa: E402
from src.web.sources import page_excerpt, source_links  # noqa: E402


def queries(q, history=None):
    c = needs_clarification(q, history)
    return c and [o[1] for o in c.options]


def test_generic_metric_asks_which_one_and_options_are_full_questions():
    c = needs_clarification("Lợi nhuận quý 2/2026 là bao nhiêu?")
    assert c and "lợi nhuận" in c.question
    assert [o[0] for o in c.options] == ["Lợi nhuận gộp", "Lợi nhuận kế toán trước thuế", "Lợi nhuận sau thuế"]
    assert c.options[2][1] == "Lợi nhuận sau thuế quý 2/2026 là bao nhiêu?"
    assert needs_clarification("phải thu quý 3/2025").options[0][1].startswith("Phải thu khách hàng")


def test_specific_metric_is_not_questioned():
    for q in ["Lợi nhuận sau thuế Q2/2026", "Nợ ngắn hạn quý 1/2026", "Lợi nhuận gộp Q1/2026", "Biên lợi nhuận gộp quý 2/2026",
              "Tài sản cố định Q1/2026", "Dòng tiền kinh doanh Q1/2026", "Phải thu khách hàng Q2/2025"]:
        assert not needs_clarification(q), q


def test_missing_period_asks_for_period_but_multi_period_and_notes_do_not():
    opts = queries("Doanh thu thuần là bao nhiêu?")
    assert opts and len(opts) == 7 and "Q2/2026" in opts[0] and "6 kỳ" in opts[-1]
    for q in ["Doanh thu thuần quý 2/2026", "Doanh thu thuần năm 2025", "Doanh thu thuần qua các quý", "So sánh doanh thu thuần cùng kỳ",
              "Các khoản vay và nợ thuê tài chính của Vinamilk gồm những gì?", "Xin chào", "Hôm nay thời tiết thế nào?"]:
        assert not needs_clarification(q), q


def test_period_from_earlier_turn_or_selected_period_hint_counts():
    hist = [types.Content(role="user", parts=[types.Part(text="Doanh thu thuần Q2/2026?")]),
            types.Content(role="model", parts=[types.Part(text="18.847,3 tỷ đồng")])]
    assert not needs_clarification("Còn giá vốn hàng bán?", hist)
    assert not needs_clarification("Giá vốn hàng bán là bao nhiêu?\n(Nếu không nêu kỳ, hiểu là kỳ Q1/2026.)")


def test_agent_returns_clarification_without_calling_model_and_keeps_history():
    class Boom:
        models = NS(generate_content=lambda **k: (_ for _ in ()).throw(AssertionError("không được gọi mô hình")))
    a = VinamilkAgent(client=Boom(), clarify=True)
    hist = []
    r = a.ask("Nợ Q1/2026", hist)
    assert r.stop_reason == "CLARIFY" and r.clarify["options"][0]["query"] == "Nợ phải trả Q1/2026" and not r.tool_calls
    assert [c.role for c in hist] == ["user", "model"]
    off = VinamilkAgent(client=Boom())                       # mặc định tắt: các công cụ đo đạc cũ không đổi hành vi
    assert off.clarify is False


def test_every_cited_page_has_evidence_image_or_text():
    srcs = [{"doc": "q2-2025", "statement": "TM", "page": 30, "code": "-"},          # trang thuyết minh: không có ảnh
            {"doc": "q2-2026", "statement": "KQKD", "page": 11, "code": "10", "label": "Doanh thu thuần"}]
    out = source_links(srcs)
    for s in out:
        assert s["image"] or s["excerpt"], s
    assert out[0]["image"] is None and out[0]["excerpt"] and len(out[0]["excerpt"]) <= 1510
    assert out[1]["image"] and out[1]["is_pdf"] and out[1]["url"].endswith("#page=11")
    assert page_excerpt("q2-2025", 9999) is None


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
