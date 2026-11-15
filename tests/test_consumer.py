"""Kiểm tra dữ liệu của 11 công ty và các luồng tra cứu qua FastAPI."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb
from fastapi.testclient import TestClient

from api.index import ASK_LIMIT, app
from src.consumer.catalog import COMPANIES, METRICS
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

    comparison = client.post("/api/ask", json={"question": "So sánh doanh thu thuần Q3/2026 của MCM và QNS"}).json()
    assert comparison["answer"] == data["answer"]
    selected = client.post("/api/ask", json={"company": "MCM", "company_period": "FY2025", "question": "Doanh thu thuần?"}).json()
    assert "2.834.874.145.661" in selected["answer"] and len(selected["sources"]) == 1
    cited = client.post("/api/ask", json={"question": "Thuyết minh hàng tồn kho của QNS năm 2025"}).json()
    assert cited["sources"] and all(s["doc"].startswith("QNS · FY2025") for s in cited["sources"])
    missing = client.post("/api/ask", json={"question": "Tổng tài sản Q4/2026 của MCM?"}).json()
    assert not missing["sources"]
    default = client.post("/api/ask", json={"question": "Doanh thu của Mộc Châu Milk?\n(Nếu không nêu kỳ, hiểu là kỳ Q2/2026.)"}).json()
    assert "692.782.561.653" in default["answer"] and "Q3/2026" in default["answer"]
    follow_up = client.post("/api/ask", json={
        "question": "Còn lợi nhuận sau thuế?",
        "history": [{"role": "user", "text": "Doanh thu Q1/2026 của MCM?"}],
    }).json()
    assert "80.118.557.404" in follow_up["answer"] and "Q1/2026" in follow_up["answer"]
    ASK_LIMIT.reset()
    shorthand = client.post("/api/ask", json={"question": "Doanh thu Q3 của QNS?"}).json()
    assert "3.073.222.799.902" in shorthand["answer"]
    annual = client.post("/api/ask", json={"question": "Doanh thu QNS năm 2026?"}).json()
    assert "9.125.345.060.876" in annual["answer"] and "lũy kế" in annual["answer"]
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
    ASK_LIMIT.reset()
    business = client.post("/api/ask", json={
        "question": "Doanh thu và lợi nhuận sau thuế Q2/2026 của KIDO?"
    }).json()
    assert "1.863.834.355.125" in business["answer"] and "9.540.055.382" in business["answer"]
    assert len(business["sources"]) == 1 and business["sources"][0]["page"] == 9
    actual = client.post("/api/ask", json={"question": "Doanh thu quý hai năm 2025 của Đường Quảng Ngãi?"}).json()
    assert "2.955.781.100.115" in actual["answer"]
    assert actual["sources"][0]["page"] == 4
    for code, (name, _) in COMPANIES.items():
        ASK_LIMIT.reset()
        reply = client.post("/api/ask", json={"question": f"Báo cáo tài chính Q2/2025 của {name}?"})
        assert reply.status_code == 200, reply.text
        sources = reply.json()["sources"]
        assert sources and all(s["doc"].startswith(f"{code} · Q2/2025") for s in sources), reply.text
    print("PASS: nhận diện 11 công ty, nguồn của 99 PDF, tra cứu, so sánh, dòng tiền và thuyết minh.")


if __name__ == "__main__":
    main()
