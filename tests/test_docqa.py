"""Hỏi đáp trên toàn bộ chữ trong PDF của 12 công ty: có trích dẫn, không bịa, không tìm thấy thì gợi ý câu hỏi tương tự.

Chạy: python tests/test_docqa.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

import api.index as api  # noqa: E402
from src.consumer import docqa, service  # noqa: E402
from src.consumer.catalog import COMPANIES, METRICS, PERIODS, fold  # noqa: E402

client = TestClient(api.app)
api.gemini_ready = lambda: False                          # các test mặc định không gọi Gemini thật (kể cả khi máy có khóa); test Gemini bên dưới tự bật bằng client giả


def ask(question):
    api.ASK_LIMIT.reset()
    response = client.post("/api/ask", json={"question": question})
    assert response.status_code == 200, response.text
    return response.json()


def test_chairman_of_masan_is_answered_from_the_pdf_with_a_citation():
    reply = ask("Chủ tịch của Masan là ai?")
    assert "Danny Le" in reply["answer"] and "Chủ tịch" in reply["answer"], reply["answer"]
    assert reply["sources"] and all("Danny Le" in s["excerpt"] for s in reply["sources"]), reply["sources"]
    assert not reply["answer"].startswith("Mình chỉ trả lời")


def test_board_and_chairman_of_other_companies():
    assert "Koh Poh Tiong" in ask("Chủ tịch hội đồng quản trị Sabeco là ai")["answer"]
    assert "Nguyễn Hạnh Phúc" in ask("Chủ tịch Vinamilk là ai")["answer"]
    board = ask("Hội đồng quản trị của Vinacafé gồm những ai?")
    assert "Pham" in board["answer"] and "Chủ tịch" in board["answer"], board["answer"]


def test_every_named_person_appears_in_the_cited_text():
    """Không bịa: tên trong câu trả lời in đậm phải nằm nguyên trong chữ của đoạn PDF được dẫn."""
    for code in ["VNM", *COMPANIES]:
        reply = docqa.answer(code, f"Chủ tịch hội đồng quản trị {docqa.entity_name(code)} là ai")
        if not reply["found"] or not reply["text"].startswith("**Chủ tịch"):
            continue                                                    # không kết luận được tên thì chỉ trích dẫn, không có gì để kiểm
        name = reply["text"].split(": ", 1)[1].split("**", 1)[0]
        evidence = fold(" ".join(s["excerpt"] for s in reply["sources"]))
        assert all(word in evidence for word in fold(name).split()), (code, name)


def test_question_without_answer_in_the_pdf_says_so_and_suggests_answerable_questions():
    reply = ask("Hôm nay trời thế nào KIDO")
    assert "không tìm thấy" in reply["answer"].lower() and reply["sources"] == []
    assert reply["suggestions"], reply
    for tip in reply["suggestions"]:
        follow = ask(tip["query"])
        assert follow["sources"], tip                                   # mọi câu gợi ý đều có kết quả thật từ PDF
    odd = ask("Masan có bán xe máy không?")
    assert odd["sources"] == [] and "không tìm thấy" in odd["answer"].lower(), odd["answer"][:200]


def test_suggestions_exist_and_work_for_every_company():
    for code in ["VNM", *COMPANIES]:
        tips = docqa.suggestions(code, "câu hỏi lạ")
        assert tips, code
        for tip in tips:
            assert docqa.answer(code, tip["query"])["found"], (code, tip)


def test_company_questions_are_not_refused_or_deflected_to_vinamilk():
    for question in ("Chủ tịch của Masan là ai?", "Trụ sở chính của Habeco ở đâu", "Công ty kiểm toán của Sabeco là ai"):
        assert service.out_of_scope(question) is False, question
        text = ask(question)["answer"]
        assert "chỉ trực tiếp xử lý" not in text and not text.startswith("Mình chỉ trả lời"), text
    assert service.out_of_scope("Giá cổ phiếu Masan hôm nay") is True


def test_a_named_company_in_a_which_company_question_is_not_turned_into_a_12_company_table():
    reply = ask("Công ty kiểm toán của Vinamilk là công ty nào")
    assert "So sánh 12 doanh nghiệp" not in reply["answer"] and "KPMG" in reply["answer"].upper(), reply["answer"][:200]


def test_numeric_questions_still_use_the_verified_tables():
    reply = ask("Doanh thu thuần của Masan quý 2/2026")
    assert "7.165,0 tỷ đồng" in reply["answer"], reply["answer"]


def test_missing_figure_offers_similar_questions_that_have_numbers():
    found = None
    for code in COMPANIES:
        for metric in METRICS:
            have = [p for p in PERIODS if p.startswith("Q") and service.repository.facts([code], p, metric, "quy")]
            lack = [p for p in PERIODS if p.startswith("Q") and p not in have]
            if have and lack:
                found = (code, metric, lack[0])
                break
        if found:
            break
    assert found, "bộ dữ liệu phải có ít nhất một ô còn thiếu để kiểm tra"
    code, metric, period = found
    reply = ask(f"{METRICS[metric][0]} {PERIODS[period]} của {COMPANIES[code][0]}")
    assert "Chưa có số" in reply["answer"] and reply["suggestions"], reply
    for tip in reply["suggestions"]:
        assert "tỷ đồng (" in ask(tip["query"])["answer"], tip


def test_chart_accepts_every_metric_the_catalog_offers():
    catalog = client.get("/api/consumer/catalog").json()
    for metric in catalog["metrics"]:
        for mode, extra in (("series", {}), ("companies", {"period": "Q2/2026"})):
            api.BROWSE_LIMIT.reset()
            response = client.post("/api/chart", json={"mode": mode, "metrics": [metric], "companies": ["MCM", "KDC"], "basis": "quy", **extra})
            assert response.status_code == 200, (metric, mode, response.text)


class _Http(Exception):
    def __init__(self, code):
        super().__init__(f"{code}")
        self.code = code


class _FakeGemini:
    def __init__(self, script):
        self.script, self.models, self.calls = list(script), self, []

    def generate_content(self, **kw):
        self.calls.append(kw["model"])
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _fake_agent(script, models=("a", "b")):
    from src.agent.agent import VinamilkAgent
    return VinamilkAgent(client=_FakeGemini(script), model=models[0], fallback_models=models[1:], retry_delays=(0, 0), toolbox=api.get_toolbox())


def _reply(*parts):
    from types import SimpleNamespace as NS
    from google.genai import types
    return NS(candidates=[NS(content=types.Content(role="model", parts=list(parts)), finish_reason=NS(name="STOP"))],
              usage_metadata=NS(prompt_token_count=10, candidates_token_count=5))


def test_gemini_takes_over_weak_company_answers_and_reads_the_company_tools():
    from google.genai import types
    call = types.Part.from_function_call(name="search_company_documents", args={"company": "KDC", "query": "địa chỉ trụ sở chính"})
    agent = _fake_agent([_reply(call), _reply(types.Part(text="KIDO đặt trụ sở chính tại Thành phố Hồ Chí Minh (theo đoạn trích [1])."))])
    saved = (api._agent, api.gemini_ready)
    api._agent, api.gemini_ready = agent, lambda: True
    try:
        reply = ask("KIDO có nhà máy ở nước ngoài không, kể tên các nước")        # câu lạ: nhánh quy tắc chỉ khớp một phần hoặc không tìm thấy
    finally:
        api._agent, api.gemini_ready = saved
    assert reply["answer"].startswith("KIDO đặt trụ sở"), reply["answer"]
    assert reply["sources"] and all("ready" not in s and s.get("excerpt") for s in reply["sources"]), reply["sources"]


def test_gemini_out_of_quota_on_every_model_still_returns_the_rule_based_answer():
    agent = _fake_agent([_Http(429), _Http(429)])
    saved = (api._agent, api.gemini_ready)
    api._agent, api.gemini_ready = agent, lambda: True
    try:
        reply = ask("Hôm nay trời thế nào KIDO")
    finally:
        api._agent, api.gemini_ready = saved
    assert "không tìm thấy" in reply["answer"].lower() and reply["suggestions"]
    assert agent.client.calls == ["a", "b"]                                       # đã thử cả hai mô hình trước khi bỏ cuộc


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS", name)
            except Exception as error:  # noqa: BLE001
                failed += 1
                print("FAIL", name, repr(error)[:300])
    sys.exit(1 if failed else 0)
