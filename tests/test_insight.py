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
