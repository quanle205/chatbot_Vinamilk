"""Kiểm thử phân tích cho các công ty: tỷ số, tăng trưởng, cầu nối lợi nhuận, đánh giá. Không gọi mạng. Chạy: python tests/test_insight.py"""
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from api.index import ASK_LIMIT, BROWSE_LIMIT, app  # noqa: E402
from src.consumer import growth, insight  # noqa: E402
from src.consumer.repository import DB_PATH  # noqa: E402

client = TestClient(app)


def ask(question, **extra):
    ASK_LIMIT.reset()
    BROWSE_LIMIT.reset()
    return client.post("/api/ask", json={"question": question, **extra}).json()


def test_asked_ratios_distinguishes_margin_leverage_and_generic_words():
    assert insight.asked_ratios("cong ty nao co bien loi nhuan gop cao nhat") == ["bien_gop"]
    assert insight.asked_ratios("xep hang ty le no tren von chu so huu") == ["no_von"]
    assert insight.asked_ratios("ty le no tren tong tai san cua kido") == ["no_ts"]          # chứa "ty le no" nhưng không phải nợ trên vốn chủ
    assert insight.asked_ratios("bien loi nhuan cua kido") == ["bien_gop", "bien_rong"]      # không nói gộp hay ròng: hiện cả hai
    assert insight.asked_ratios("doanh thu cua kido") == []


def test_bridge_parts_always_sum_to_the_exact_profit_change():
    rng = random.Random(7)
    for _ in range(300):
        dt0, dt1 = rng.randint(10**11, 10**13), rng.randint(10**11, 10**13)
        gp0, gp1 = int(dt0 * rng.uniform(0.1, 0.6)), int(dt1 * rng.uniform(0.1, 0.6))
        pt0, pt1 = gp0 - rng.randint(0, gp0), gp1 - rng.randint(0, gp1)
        np0, np1 = int(pt0 * rng.uniform(0.5, 1)), int(pt1 * rng.uniform(0.5, 1))
        base = {"doanh_thu_thuan": dt0, "loi_nhuan_gop": gp0, "loi_nhuan_truoc_thue": pt0, "loi_nhuan_sau_thue": np0}
        cur = {"doanh_thu_thuan": dt1, "loi_nhuan_gop": gp1, "loi_nhuan_truoc_thue": pt1, "loi_nhuan_sau_thue": np1}
        for level in growth.PROFIT_LEVELS:
            parts = growth.bridge_parts(base, cur, level)
            assert abs(sum(v for _, v in parts) - (cur[level] - base[level])) < 1e-3 * max(1, abs(cur[level] - base[level])) + 1, level


def test_bridge_falls_back_to_the_deepest_level_with_data():
    base = {"doanh_thu_thuan": 1000, "loi_nhuan_gop": 300}
    cur = {"doanh_thu_thuan": 1200, "loi_nhuan_gop": 330}                                    # thiếu lợi nhuận trước thuế và sau thuế
    text, level = growth.bridge_text("X", "Q1", "Q2", base, cur, "loi_nhuan_sau_thue")
    assert level == "loi_nhuan_gop" and "Chỉ phân rã được đến lợi nhuận gộp" in text
    assert growth.bridge_text("X", "Q1", "Q2", {"doanh_thu_thuan": 1}, {"doanh_thu_thuan": 2}, "loi_nhuan_gop") == ("", None)


def test_growth_percentage_matches_independent_calculation_from_duckdb():
    with duckdb.connect(str(DB_PATH), read_only=True, config={"threads": 1}) as db:
        def revenue(period):
            return db.execute("""select distinct f.value from document_facts f join documents d using(id)
                                 where d.company='MCH' and d.period=? and f.metric='doanh_thu_thuan' and f.basis='quy'""", [period]).fetchall()
        a, b = revenue("Q1/2025"), revenue("Q1/2026")
    assert len(a) == 1 and len(b) == 1
    expected = f"{(b[0][0] - a[0][0]) / a[0][0] * 100:+.1f}%".replace(".", ",")
    reply = ask("Doanh thu của Masan Consumer quý 1/2026 tăng bao nhiêu phần trăm so với cùng kỳ?")
    assert expected in reply["answer"] and "cùng kỳ năm trước" in reply["answer"], reply["answer"]
    assert reply["sources"] and re.search(r"Q1/2025: [\d.,]+ → [\d.,]+ tỷ đồng", reply["answer"])


def test_growth_refuses_to_compare_separate_with_consolidated_statements():
    answer = ask("Công ty nào tăng trưởng doanh thu cao nhất quý 1/2026?")["answer"]
    habeco = next(line for line in answer.splitlines() if line.startswith("| Habeco"))
    assert habeco.endswith("| — |"), habeco                                                  # Habeco Q1/2025 là báo cáo riêng, Q1/2026 không phải
    assert "Không so sánh được: Habeco" in answer
    mcm = next(line for line in answer.splitlines() if line.startswith("| Mộc Châu Milk"))   # MCM chỉ có báo cáo riêng ở mọi kỳ: so sánh được
    assert mcm.endswith("+25,4% |"), mcm


def test_why_answer_is_an_arithmetic_bridge_with_honest_limits():
    reply = ask("Vì sao lợi nhuận KIDO quý 2/2026 thay đổi so với quý trước?")
    answer = reply["answer"]
    assert "Tổng thay đổi lợi nhuận sau thuế** | **-22,5** | giảm" in answer and "Biên lợi nhuận gộp thay đổi (18,7% → 21,9%)" in answer, answer
    assert any("không cho biết nguyên nhân kinh doanh" in n for n in reply["notes"])
    fallback = ask("Lợi nhuận sau thuế quý 3/2026 của Mộc Châu Milk giảm do đâu?")
    assert any("Chưa có số Q3/2025 nên so với quý liền trước (Q2/2026)" in n for n in fallback["notes"]), fallback["notes"]
    revenue = ask("Vì sao doanh thu KIDO quý 2/2026 giảm?")
    assert any("không giải thích được nguyên nhân" in n for n in revenue["notes"])             # doanh thu: chỉ nêu mức thay đổi, không bịa nguyên nhân
    assert "so với cùng kỳ" in revenue["answer"]


def test_series_answer_carries_a_chart_without_repeating_the_table():
    reply = ask("Doanh thu của Habeco và Sabeco qua các quý")
    assert reply["charts"] and all(block.get("no_table") for block in reply["charts"])
    assert "| Q4/2025 | 2.203,1 | 6.836,6 |" in reply["answer"]
    habeco = next(row for block in reply["charts"] for row in block["rows"] if row["label"].endswith("(BHN)"))
    by_period = {cell["period"]: cell["value"] for cell in habeco["cells"]}
    assert by_period["Q1/2025"] is None and by_period["Q2/2025"] is not None, by_period    # Q1/2025 là báo cáo riêng: không vẽ nối với các quý hợp nhất


def test_assessment_questions_are_answered_with_numbers_not_refused_or_asked_back():
    from src.agent.clarify import needs_clarification
    from src.consumer import assess
    assert assess.asked_assessment("kido co hieu qua sinh loi tot khong") == "profit"
    assert assess.asked_assessment("vinamilk co kha nang thanh toan no tot khong") == "leverage"
    assert assess.asked_assessment("tinh hinh tai chinh cua sabeco the nao") == "general"
    assert assess.asked_assessment("no cua habeco quy 1 2026 la bao nhieu") is None         # câu hỏi số liệu thường không bị coi là đánh giá
    assert needs_clarification("Vinamilk có khả năng thanh toán nợ tốt không?") is None      # lỗi cũ: bị hỏi lại "Bạn muốn xem nợ nào?"
    assert needs_clarification("Nợ Q1/2026") is not None                                      # câu thật sự mơ hồ vẫn được hỏi lại
    kido = ask("KIDO có hiệu quả sinh lời tốt không?")["answer"]
    assert kido.startswith("**Đánh giá khả năng sinh lời của KIDO ·") and "Xếp hạng (1 = tốt nhất)" in kido and "**Tóm lại:**" in kido, kido
    assert "chỉ trả lời về số liệu" not in kido                                              # lỗi cũ: bị từ chối như tư vấn đầu tư
    reply = ask("Vinamilk có khả năng thanh toán nợ tốt không?")
    assert reply["answer"].startswith("**Đánh giá mức nợ và độ an toàn tài chính của Vinamilk") and "hệ số thanh toán hiện hành 1,91 lần" in reply["answer"], reply["answer"]
    assert any("không phải khuyến nghị đầu tư" in n for n in reply["notes"]) and reply["sources"]
    for question in ("Có nên mua cổ phiếu KIDO không?", "Cổ phiếu KIDO có tốt không?"):
        assert "chỉ trả lời về số liệu" in ask(question)["answer"], question                   # tư vấn đầu tư vẫn bị từ chối
    assert "tối đa 3 doanh nghiệp" in ask("Vinamilk, KIDO, Masan Consumer và Sabeco có khả năng thanh toán nợ tốt không?")["answer"]


def test_assessment_ratios_match_independent_calculation_from_duckdb():
    with duckdb.connect(str(DB_PATH), read_only=True, config={"threads": 1}) as db:
        def one(metric, basis):
            rows = db.execute("""select distinct f.value from document_facts f join documents d using(id)
                                 where d.company='KDC' and d.period='Q3/2026' and f.metric=? and f.basis=?""", [metric, basis]).fetchall()
            assert len(rows) == 1
            return rows[0][0]
        margin = one("loi_nhuan_gop", "quy") / one("doanh_thu_thuan", "quy")
    assert f"| Biên lợi nhuận gộp | {margin * 100:.1f}%".replace(".", ",") in ask("KIDO có hiệu quả sinh lời tốt không?")["answer"]


def test_company_summary_gets_a_short_assessment():
    answer = ask("Tình hình tài chính của Sabeco quý 2/2026")["answer"]
    assert answer.startswith("**Tóm tắt báo cáo Q2/2026 · Sabeco (SAB)**") and "**Đánh giá tình hình tài chính của Sabeco · Q2/2026**" in answer


def test_small_changes_are_not_called_improving_or_worsening():
    from src.consumer.assess import assess_text
    values = {"doanh_thu_thuan": 1000, "loi_nhuan_gop": 300, "loi_nhuan_sau_thue": 100}
    previous = {"doanh_thu_thuan": 1000, "loi_nhuan_gop": 295, "loi_nhuan_sau_thue": 98}      # biên gộp +0,5 điểm, biên ròng +0,2 điểm
    peers = {"bien_gop": [0.2, 0.25, 0.3, 0.35, 0.4], "bien_rong": [0.05, 0.08, 0.1, 0.12, 0.15]}
    text = assess_text("X", "Q2", "cùng kỳ", values, previous, peers, "profit")
    assert "ít thay đổi so với kỳ trước" in text and "đang xấu đi" not in text and "đang cải thiện" not in text


def test_growth_why_and_trend_questions_are_not_mistaken_for_assessment():
    from src.consumer import assess
    for query in ("loi nhuan sau thue q2 2026 tang giam the nao so voi cung ky", "vi sao loi nhuan kido the nao",
                  "loi nhuan vinamilk co xu huong the nao", "doanh thu tang bao nhieu phan tram"):
        assert assess.asked_assessment(query) is None, query
    ASK_LIMIT.reset()
    response = client.post("/api/ask", json={"question": "Lợi nhuận sau thuế Q2/2026 tăng giảm thế nào so với cùng kỳ?"})
    assert response.status_code == 503                                                       # chuyển cho trợ lý (môi trường test không có khóa), không bị trả bảng đánh giá


def test_vinamilk_why_uses_the_deterministic_profit_bridge():
    reply = ask("Vì sao lợi nhuận sau thuế quý 2/2026 thay đổi so với quý 1/2026?")           # không cần khóa Gemini
    answer = reply["answer"]
    assert answer.startswith("**Lợi nhuận sau thuế Q2/2026 của Vinamilk** tăng 726,2 tỷ đồng so với Q1/2026"), answer
    assert "Tổng thay đổi lợi nhuận sau thuế** | **+726,2** | tăng" in answer and "Thuế thu nhập doanh nghiệp" in answer
    parts = re.findall(r"\| (?:Doanh thu|Biên|Chi phí|Thuế)[^|]*\| ([+-][\d.,]+) \|", answer)
    to_float = lambda text: float(text.replace(".", "").replace(",", "."))      # noqa: E731
    assert len(parts) == 4 and abs(sum(map(to_float, parts)) - 726.2) < 0.25, parts           # các khoản mục cộng lại bằng chênh lệch (sai số do làm tròn từng dòng)
    assert reply["sources"] and any("không cho biết nguyên nhân kinh doanh" in n for n in reply["notes"])


def test_vinamilk_question_about_a_period_without_data_is_answered_instantly_without_gemini():
    import os
    assert not os.environ.get("GEMINI_API_KEY")                                              # môi trường test không có khóa: nếu gọi Gemini sẽ là 503
    for question in ("Doanh thu quý 3/2026 của Vinamilk là bao nhiêu?", "Lợi nhuận Vinamilk năm 2024", "Vinamilk quý 1/2024 thế nào?"):
        ASK_LIMIT.reset()
        response = client.post("/api/ask", json={"question": question})
        assert response.status_code == 200, (question, response.status_code)
        assert "Chưa có báo cáo" in response.json()["answer"] and "Q1/2025 đến Q2/2026" in response.json()["answer"], response.json()["answer"]
    for question in ("Doanh thu Vinamilk quý 2/2026 và quý 3/2026", "Doanh thu Vinamilk năm 2025"):
        ASK_LIMIT.reset()                                                                    # có ít nhất một kỳ có dữ liệu: không chặn, để trợ lý trả lời
        assert client.post("/api/ask", json={"question": question}).status_code == 503


def test_year_2025_lookups_use_the_audited_annual_report_and_answer_only_what_was_asked():
    total = ask("Tổng tài sản năm 2025 của KIDO")                                           # lỗi cũ: "Chưa có số đã đối chiếu" dù PDF có
    assert "13.907.212.327.484" in total["answer"] and "Chưa có" not in total["answer"] and "trang 84" in total["answer"], total["answer"]
    current = ask("Tài sản ngắn hạn năm 2025 của KIDO")                                     # lỗi cũ: bảng tóm tắt lan man không có chỉ tiêu được hỏi
    assert current["answer"].startswith("**Tài sản ngắn hạn · Năm 2025**") and "6.674.909.250.681" in current["answer"], current["answer"]
    assert "Tóm tắt" not in current["answer"] and "Đánh giá" not in current["answer"] and current["sources"]
    debt = ask("Nợ ngắn hạn và nợ dài hạn của Sabeco quý 2/2026")["answer"]
    assert "**Nợ ngắn hạn · Q2/2026**" in debt and "**Nợ dài hạn · Q2/2026**" in debt and "**Nợ phải trả" not in debt      # không bị đổi nhầm thành "Nợ phải trả"
    mch = ask("Doanh thu thuần năm 2025 của Masan Consumer")                                 # báo cáo thường niên MCH không có bảng có mã: lấy từ báo cáo quý 4, nói rõ
    assert "Số lấy từ báo cáo Q4/2025 vì báo cáo năm chưa có dòng này" in mch["answer"] and any("chưa kiểm toán" in n for n in mch["notes"]), mch


def test_cumulative_figure_is_offered_when_only_the_cumulative_column_was_read():
    with duckdb.connect(str(DB_PATH), read_only=True, config={"threads": 1}) as db:
        rows = db.execute("""select distinct f.basis, f.value from document_facts f join documents d using(id)
                             where d.company='PAN' and d.period='Q4/2025' and f.metric='loi_nhuan_truoc_thue'""").fetchall()
    assert [b for b, _ in rows] == ["luy_ke"], rows                                            # điều kiện của ca này: chỉ có lũy kế, không có riêng quý
    reply = ask("Lợi nhuận trước thuế quý 4/2025 của Tập đoàn PAN")
    value = f"{rows[0][1]:,}".replace(",", ".")
    assert "Chưa có số riêng quý đã đối chiếu. Số lũy kế đến hết Q4/2025" in reply["answer"] and value in reply["answer"], reply["answer"]
    assert reply["sources"]


def test_line_item_without_data_is_answered_directly_not_with_an_off_topic_summary():
    reply = ask("Chi phí bán hàng năm 2025 của KIDO")
    answer = reply["answer"]
    assert answer.startswith("**Chi phí bán hàng · Năm 2025** — chưa có số đã đối chiếu của khoản mục này cho KIDO."), answer
    assert "Hiện tra cứu được:" in answer and "tài sản ngắn hạn" in answer and "Tóm tắt" not in answer and reply["sources"]
    assert not re.search(r"\d{1,3}(?:[.,]\d{3}){3,}", answer)                                  # không in lại số/chữ OCR chưa đối chiếu
    generic = ask("Tình hình tài chính của KIDO năm 2025")["answer"]                         # câu chung chung vẫn được tóm tắt như cũ
    assert generic.startswith("**Tóm tắt báo cáo Năm 2025 · KIDO (KDC)**")


def test_extra_metrics_add_up_to_the_hand_verified_totals_for_mcm_and_qns():
    """Chỉ tiêu mở rộng (trích tự động) phải cộng đúng ra tổng đã đối chiếu tay của MCM/QNS: tài sản ngắn + dài hạn = tổng tài sản; nợ ngắn + dài hạn = nợ phải trả."""
    with duckdb.connect(str(DB_PATH), read_only=True, config={"threads": 1}) as db:
        verified = {(c, p, m): v for c, p, m, v in db.execute("select company, period, metric, value from facts where basis='point'").fetchall()}
        extra = {(c, p, m): v for c, p, m, v in db.execute("""select d.company, d.period, f.metric, f.value from document_facts f join documents d using(id)
                                                              where f.basis='point' and f.metric in ('tai_san_ngan_han','tai_san_dai_han','no_ngan_han','no_dai_han')""").fetchall()}
    checked = 0
    for (company, period), total in {(c, p): verified[c, p, "tong_tai_san"] for c, p, m in verified if m == "tong_tai_san"}.items():
        if (company, period, "tai_san_ngan_han") in extra:
            assert extra[company, period, "tai_san_ngan_han"] + extra[company, period, "tai_san_dai_han"] == total, (company, period)
            assert extra[company, period, "no_ngan_han"] + extra[company, period, "no_dai_han"] == verified[company, period, "no_phai_tra"], (company, period)
            checked += 1
    assert checked >= 6, checked                                                             # hầu hết 8 báo cáo MCM/QNS đã đối chiếu tay có đủ chỉ tiêu mở rộng
    for (company, period, metric), value in extra.items():                                    # và với mọi công ty: tổng phụ không vượt tổng
        assert value > 0, (company, period, metric)


def test_lookup_screen_offers_the_extra_metrics():
    catalog = client.get("/api/consumer/catalog").json()["metrics"]
    assert catalog["tai_san_ngan_han"] == "Tài sản ngắn hạn" and catalog["gia_von"] == "Giá vốn hàng bán" and "doanh_thu_thuan" in catalog
    BROWSE_LIMIT.reset()
    reply = client.post("/api/consumer/lookup", json={"companies": ["KDC", "VNM"], "period": "Q2/2026", "metric": "tai_san_ngan_han"})
    assert reply.status_code == 200 and "Tài sản ngắn hạn" in reply.json()["answer"] and reply.json()["sources"], reply.text


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
