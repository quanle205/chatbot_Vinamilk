"""Kiểm tra dữ liệu của 11 công ty và các luồng tra cứu qua FastAPI."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb
from fastapi.testclient import TestClient

from api.index import ASK_LIMIT, app
from src.consumer.catalog import COMPANIES, METRICS
from src.consumer import service
from src.consumer.repository import DB_PATH


def main():
    with duckdb.connect(str(DB_PATH), read_only=True) as db:
        assert db.execute("select count(*) from reports").fetchone()[0] == 8
        counts = db.execute("select count(distinct metric) from facts group by company, period").fetchall()
        assert counts == [(len(METRICS),)] * 8
        assert db.execute("select count(*) from (select distinct company, period from notes)").fetchone()[0] == 8
        assert db.execute("select count(*) from documents").fetchone()[0] == 99
        assert db.execute("select count(*) from documents where indexed_pages > 0").fetchone()[0] == 99
        assert db.execute("select count(distinct company) from documents").fetchone()[0] == len(COMPANIES)
        assert db.execute("""select count(*) from
            (select distinct company, period from documents where period like 'Q%/2025')""").fetchone()[0] == 44
    client = TestClient(app)
    payload = {"companies": ["MCM", "QNS"], "period": "Q3/2026", "metric": "doanh_thu_thuan"}
    response = client.post("/api/consumer/lookup", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()
    assert "692.782.561.653" in data["answer"] and "3.073.222.799.902" in data["answer"]
    assert [source["page"] for source in data["sources"]] == [7, 4]
    assert all(source["url"].endswith(f"#page={source['page']}") for source in data["sources"])
    assert "riêng" in data["answer"] and "hợp nhất" in data["answer"]
    assert client.post("/api/consumer/lookup", json={**payload, "companies": ["VNM"], "period": "Q2/2026"}).json()["sources"]
    cashflow = client.post("/api/consumer/lookup", json={**payload, "metric": "dong_tien_kinh_doanh"}).json()
    assert len(cashflow["sources"]) == 4 and "37.215.420.363" in cashflow["answer"]
    profit = client.post("/api/consumer/lookup", json={**payload, "metric": "loi_nhuan_sau_thue"}).json()
    assert "449.769.818.052" in profit["answer"] and any("566.696.672" in n for n in profit["notes"])

    def chat(question, companies, period=None, context=None):          # logic tra cứu doanh nghiệp; trò chuyện không còn gọi tới nó
        return service.answer_question(question, companies, period, context)
    comparison = chat("So sánh doanh thu thuần Q3/2026 của MCM và QNS", ["MCM", "QNS"])
    assert comparison["answer"] == data["answer"]
    selected = chat("Doanh thu thuần?", ["MCM"], "FY2025")
    assert "2.834.874.145.661" in selected["answer"] and len(selected["sources"]) == 1
    cited = chat("Thuyết minh hàng tồn kho của QNS năm 2025", ["QNS"])
    assert cited["sources"] and all(s["doc"].startswith("QNS · FY2025") for s in cited["sources"])
    assert not chat("Tổng tài sản Q4/2026 của MCM?", ["MCM"])["sources"]
    annual = chat("Doanh thu QNS năm 2026?", ["QNS"])
    assert "9.125.345.060.876" in annual["answer"] and "lũy kế" in annual["answer"]
    ASK_LIMIT.reset()
    for q in ["So sánh doanh thu thuần Q3/2026 của MCM và QNS", "Doanh thu quý hai năm 2025 của Đường Quảng Ngãi?",
              "Doanh thu Vinamilk và MCM Q2/2026 chênh bao nhiêu?"]:
        reply = client.post("/api/ask", json={"question": q}).json()      # trò chuyện chỉ có Vinamilk: từ chối, không số liệu, không nguồn
        assert "chỉ trả lời về báo cáo tài chính hợp nhất của Vinamilk" in reply["answer"] and not reply["sources"], q
        assert not any(ch.isdigit() for ch in reply["answer"]), reply["answer"]
    assert client.get("/api/consumer/catalog").json()["companies"] == {
        "VNM": "Vinamilk", **{code: company[0] for code, company in COMPANIES.items()}
    }
    trend = client.post("/api/chart", json={
        "mode": "series", "companies": ["BBC"], "metrics": ["doanh_thu_thuan"]
    }).json()["charts"][0]
    assert len(trend["rows"]) == 4 and any(row["value"] is None for row in trend["rows"])
    compare = client.post("/api/chart", json={
        "mode": "companies", "companies": ["MCM", "QNS"], "period": "Q3/2026", "metrics": ["doanh_thu_thuan"]
    }).json()["charts"][0]
    assert [row["value"] for row in compare["rows"]] == [692782561653, 3073222799902]
    mixed = client.post("/api/chart", json={
        "mode": "companies", "companies": ["VNM", "MCM"], "period": "Q2/2026", "metrics": ["doanh_thu_thuan"]
    }).json()["charts"][0]
    assert all(row["source"]["url"] for row in mixed["rows"])
    multiple = {"companies": ["VNM", "MCM", "QNS"], "period": "Q2/2026"}
    chart = client.post("/api/chart", json={
        **multiple, "mode": "companies", "metrics": ["doanh_thu_thuan"]
    }).json()
    assert len(chart["charts"][0]["rows"]) == 3
    indicators = client.post("/api/ratios", json=multiple).json()
    assert [row["company"] for row in indicators["comparison"]] == multiple["companies"]
    ratios = client.post("/api/ratios", json={"company": "QNS", "period": "Q3/2026"}).json()
    margin = ratios["groups"][0]["items"][0]
    assert margin["value"] > 0 and margin["sources"]
    for code, (name, _) in COMPANIES.items():
        reply = chat(f"Báo cáo tài chính Q2/2025 của {name}?", [code])
        assert reply["sources"] and all(s["doc"].startswith(f"{code} · Q2/2025") for s in reply["sources"]), code
    business = chat("Doanh thu và lợi nhuận sau thuế Q2/2026 của KIDO?", ["KDC"])
    assert "1.863.834.355.125" in business["answer"] and "9.540.055.382" in business["answer"]
    assert len(business["sources"]) == 1 and business["sources"][0]["page"] == 9
    actual = chat("Doanh thu quý hai năm 2025 của Đường Quảng Ngãi?", ["QNS"])
    assert "2.955.781.100.115" in actual["answer"] and actual["sources"][0]["page"] == 4
    print("PASS: nhận diện 11 công ty, nguồn của 99 PDF, tra cứu, so sánh, dòng tiền và thuyết minh.")


if __name__ == "__main__":
    main()
