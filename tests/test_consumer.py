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
    many = client.post("/api/consumer/lookup", json={"companies": ["VNM", "MCM", "QNS", "KDC"], "period": "Q2/2026", "metric": "doanh_thu_thuan"})
    assert many.status_code == 200, many.text
    text = many.json()["answer"]
    assert all(name in text for name in ("Vinamilk", "Mộc Châu Milk", "Đường Quảng Ngãi", "KIDO")), text      # nhiều hơn hai doanh nghiệp, có cả Vinamilk
    assert "18.847.347.464.988" in text and "1.863.834.355.125" in text and len(many.json()["sources"]) >= 3
    many_peers = client.post("/api/consumer/lookup", json={"companies": ["MCM", "QNS", "KDC"], "period": "Q2/2026", "metric": "doanh_thu_thuan"}).json()
    assert "KIDO" in many_peers["answer"] and "1.863.834.355.125" in many_peers["answer"]
    assert client.post("/api/consumer/lookup", json={"companies": ["VNM"], "period": "Q2/2026", "metric": "doanh_thu_thuan"}).json()["sources"]
    assert client.post("/api/consumer/lookup", json={"companies": ["XXX"], "period": "Q2/2026", "metric": "doanh_thu_thuan"}).status_code == 422
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
    every = list(COMPANIES) + ["VNM"]
    trend_all = client.post("/api/chart", json={"mode": "series", "companies": every, "metrics": ["doanh_thu_thuan", "loi_nhuan_sau_thue"]})
    assert trend_all.status_code == 200, trend_all.text
    blocks = trend_all.json()["charts"]
    assert len(blocks) == 2 and all(b["kind"] == "matrix" and b["chart"] and len(b["rows"]) == 12 for b in blocks)      # mỗi chỉ tiêu một biểu đồ, đủ 12 doanh nghiệp
    assert blocks[0]["columns"] == ["Q1/2025", "Q2/2025", "Q3/2025", "Q4/2025", "Q1/2026", "Q2/2026", "Q3/2026"]
    assert all(len(r["cells"]) == 7 for r in blocks[0]["rows"])
    vnm = next(r for r in blocks[0]["rows"] if r["label"].endswith("(VNM)"))
    assert vnm["cells"][5]["value"] == 18847347464988 and vnm["cells"][6]["value"] is None and vnm["sources"]
    growth_all = client.post("/api/chart", json={"mode": "growth", "companies": every, "metrics": ["doanh_thu_thuan"], "period": "Q2/2026", "kind": "yoy"}).json()["charts"][0]
    assert growth_all["growth"] and len(growth_all["rows"]) == 12 and growth_all["columns"] == ["Q2/2025", "Q2/2026"]
    assert sum(r.get("growth") is not None for r in growth_all["rows"]) >= 2
    wide = client.post("/api/chart", json={"mode": "companies", "companies": every, "metrics": ["doanh_thu_thuan"], "period": "Q2/2026"}).json()["charts"][0]
    assert len(wide["rows"]) == 12 and sum(r["value"] is not None for r in wide["rows"]) >= 4      # thiếu kỳ thì hiện "Chưa có số", không chặn cả bảng
    assert client.post("/api/chart", json={"mode": "series", "companies": ["VNM"], "metrics": ["Doanh thu thuần"]}).json()["charts"][0]["kind"] == "series"
    # Chỉ số nhiều doanh nghiệp: thiếu kỳ ở một doanh nghiệp không làm hỏng cả bảng; mỗi số ghi phạm vi
    mixed_ratios = client.post("/api/ratios", json={"companies": every, "period": "Q2/2026"})
    assert mixed_ratios.status_code == 200, mixed_ratios.text
    columns = {c["company"]: c for c in mixed_ratios.json()["comparison"]}
    assert len(columns) == 12 and "Bibica" in columns["BBC"]["error"] and not columns["BBC"]["groups"]
    assert sum(len(g["items"]) for g in columns["VNM"]["groups"]) == 15 and all(i["scope"] == "hợp nhất" for g in columns["VNM"]["groups"] for i in g["items"])
    assert client.post("/api/ratios", json={"companies": ["BBC", "BBC"], "period": "Q2/2026"}).status_code == 422
    assert client.post("/api/ratios", json={"companies": ["BBC", "VNM"], "period": "Q3/2026"}).status_code == 422      # cả hai đều thiếu kỳ -> báo lỗi
    # Đối chiếu độc lập: tự tính lại tỷ số của các công ty từ bảng DuckDB, phải khớp từng chữ số
    definitions = {"Biên lợi nhuận gộp": ("loi_nhuan_gop", "doanh_thu_thuan"), "Biên lợi nhuận trước thuế": ("loi_nhuan_truoc_thue", "doanh_thu_thuan"), "Biên lợi nhuận ròng": ("loi_nhuan_sau_thue", "doanh_thu_thuan"),
                   "Hệ số nợ trên vốn chủ sở hữu": ("no_phai_tra", "von_chu_so_huu"), "Hệ số nợ trên tổng tài sản": ("no_phai_tra", "tong_tai_san")}
    def raw(code, period, metric):
        with duckdb.connect(str(DB_PATH), read_only=True, config={"threads": 1}) as db:
            return [r[0] for r in db.execute("""select distinct value from (
                select f.value from facts f where f.company=? and f.period=? and f.metric=? and f.basis in ('quy','point','annual')
                union all select f.value from document_facts f join documents d using(id)
                where d.company=? and d.period=? and f.metric=? and f.basis in ('quy','point','annual'))""",
                [code, period, metric, code, period, metric]).fetchall()]
    audited = 0
    for period in ("Q1/2025", "Q2/2025", "Q3/2025", "Q4/2025", "Q1/2026", "Q2/2026", "Q3/2026", "FY2025"):
        for column in client.post("/api/ratios", json={"companies": list(COMPANIES), "period": period}).json()["comparison"]:
            for item in (i for g in column["groups"] for i in g["items"] if i.get("value") is not None):
                num, den = (raw(column["company"], period, m) for m in definitions[item["name"]])
                assert len(num) == 1 and len(den) == 1, (column["company"], period, item["name"])
                assert abs(num[0] / den[0] - item["value"]) < 1e-9, (column["company"], period, item["name"])
                audited += 1
    assert audited >= 100, audited
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
