"""Kiểm tra dữ liệu của 11 công ty và các luồng tra cứu qua FastAPI."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb
from fastapi.testclient import TestClient

from api.index import ASK_LIMIT, BROWSE_LIMIT, app
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
    BROWSE_LIMIT.reset()
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
    BROWSE_LIMIT.reset()
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
        BROWSE_LIMIT.reset()
        for column in client.post("/api/ratios", json={"companies": list(COMPANIES), "period": period}).json()["comparison"]:
            for item in (i for g in column["groups"] for i in g["items"] if i.get("value") is not None):
                num, den = (raw(column["company"], period, m) for m in definitions[item["name"]])
                assert len(num) == 1 and len(den) == 1, (column["company"], period, item["name"])
                assert abs(num[0] / den[0] - item["value"]) < 1e-9, (column["company"], period, item["name"])
                audited += 1
    assert audited >= 100, audited
    assert client.get("/api/consumer/catalog").json()["companies"] == {
        "VNM": "Vinamilk", **{code: company[0] for code, company in COMPANIES.items()}
    }
    trend = client.post("/api/chart", json={
        "mode": "series", "companies": ["BBC"], "metrics": ["doanh_thu_thuan"]
    }).json()["charts"][0]
    assert len(trend["rows"]) == 4 and all(row["value"] is not None for row in trend["rows"])
    assert abs(sum(row["value"] for row in trend["rows"]) / 1_780_710_120_529 - 1) < 0.02      # 4 quý cộng lại xấp xỉ doanh thu cả năm 2025 trong báo cáo kiểm toán
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
    from src.consumer.service import question_companies
    assert question_companies("tài chính quý 1 năm 2025 của công ty habenco") == ["BHN"]      # gõ sai tên vẫn nhận ra
    assert question_companies("Vinamilk doanh thu quý 2/2025") == []                          # không nhận nhầm công ty khác
    cmp = client.post("/api/ask", json={"question": "so sánh tổng doanh thu quý 1 của công ty Vinamilk với công ty Đường Quảng Ngãi"}).json()
    assert "16.148,7" in cmp["answer"] and "2.763,4" in cmp["answer"] and "gấp 5,8 lần" in cmp["answer"] and "Lãi, lỗ sau thuế" in cmp["answer"]
    assert any(s["doc"].startswith("q1-2026") for s in cmp["sources"]) and any(s["doc"].startswith("QNS") for s in cmp["sources"])
    ASK_LIMIT.reset()
    everyone = client.post("/api/ask", json={"question": "công ty nào doanh thu cao nhất năm 2025"}).json()       # cả danh mục, gồm Vinamilk
    assert "| 1 | Vinamilk | 63.645,9" in everyone["answer"] and "Sabeco" in everyone["answer"] and "Năm 2025" in everyone["answer"]
    others = client.post("/api/ask", json={"question": "so sánh mcm và qns"}).json()                              # không có Vinamilk, không nêu kỳ
    assert "So sánh Q3/2026: Mộc Châu Milk và Đường Quảng Ngãi" in others["answer"] and "692,8" in others["answer"]
    quarters = client.post("/api/ask", json={"question": "doanh thu của mcm qua các quý"}).json()
    assert all(text in quarters["answer"] for text in ("| Q1/2025 | 591,2 |", "| Q3/2026 | 692,8 |")) and quarters["sources"]
    margin = client.post("/api/ask", json={"question": "biên lợi nhuận gộp của Mộc Châu Milk năm 2025"}).json()
    assert "28,1%" in margin["answer"] and margin["sources"]
    assert question_companies("các công ty con của Vinamilk") == []
    ASK_LIMIT.reset()
    # "lãi hơn" là câu hỏi báo cáo, không bị bộ lọc ngoài phạm vi chặn; giá cổ phiếu vẫn bị chặn
    masan = client.post("/api/ask", json={"question": "Masan Consumer và Vinamilk công ty nào lãi hơn năm 2025"}).json()
    assert "So sánh Năm 2025: Vinamilk và Masan Consumer" in masan["answer"], masan["answer"]
    # MCH không có báo cáo năm: số cả năm lấy từ cột lũy kế quý 4/2025, bằng tổng bốn quý
    assert "| Lợi nhuận sau thuế (tỷ đồng) | 9.413,6 | 6.764,1 |" in masan["answer"]
    stock = client.post("/api/ask", json={"question": "giá cổ phiếu SAB hôm nay bao nhiêu"}).json()
    assert "không trả lời về giá cổ phiếu" in stock["answer"]
    # KDC: báo cáo năm chỉ có kết quả kinh doanh; bảng cân đối cuối năm lấy từ báo cáo quý 4
    kido = client.post("/api/ask", json={"question": "KIDO và Vinamilk công ty nào lãi hơn năm 2025"}).json()
    assert "| Tổng tài sản (tỷ đồng) | 53.312,4 | 13.980,8 |" in kido["answer"], kido["answer"]
    # phạm vi không rõ thì không viết "báo cáo theo báo cáo"
    debt = client.post("/api/ask", json={"question": "nợ của Habeco quý 1/2026 là bao nhiêu"}).json()
    assert "báo cáo theo báo cáo" not in debt["answer"] and "1.742,6" in debt["answer"]
    ASK_LIMIT.reset()
    # BHN Q1/2025 chỉ có báo cáo riêng, các quý khác là hợp nhất: bảng theo quý phải cảnh báo
    bhn = client.post("/api/ask", json={"question": "lợi nhuận sau thuế Habeco qua các quý"}).json()
    assert any("Habeco: Q1/2025 là báo cáo riêng" in n for n in bhn["notes"]), bhn["notes"]
    mcm = client.post("/api/ask", json={"question": "lợi nhuận sau thuế Mộc Châu Milk qua các quý"}).json()
    assert not any("không đồng nhất" in n for n in mcm["notes"])                                  # MCM chỉ có báo cáo riêng
    ASK_LIMIT.reset()
    # hỏi về chính bộ dữ liệu: trả danh mục 12 công ty, không qua Gemini, không nói "chỉ có Vinamilk"
    for q in ("có bao nhiêu công ty trong dữ liệu của bạn", "Bạn có dữ liệu của những công ty nào?", "co may cong ty",
              "có những công ty nào trong tập dữ liệu\n(Nếu không nêu kỳ, hiểu là kỳ Q2/2026.)"):     # giao diện nối thêm kỳ mặc định
        cat = client.post("/api/ask", json={"question": q}).json()
        assert "**12 công ty**" in cat["answer"] and "| Sabeco | SAB |" in cat["answer"] and "| Vinamilk | VNM |" in cat["answer"], cat["answer"]
    from src.consumer.service import catalog_question
    assert not catalog_question("những công ty nào lỗ năm 2025") and not catalog_question("các công ty con của Vinamilk")
    from src.agent.agent import REFUSAL_TEXT
    from src.agent.prompts import SYSTEM_PROMPT
    assert "11 công ty" in REFUSAL_TEXT and "12 công ty" in SYSTEM_PROMPT and "không so sánh với công ty khác" not in SYSTEM_PROMPT
    # Xếp hạng theo ĐÚNG tỷ số được hỏi (không phải giá trị tuyệt đối), nêu rõ bên nào thiếu và vì sao
    ASK_LIMIT.reset()
    gross = client.post("/api/ask", json={"question": "Công ty nào có biên lợi nhuận gộp cao nhất quý 2/2025?"}).json()["answer"]
    assert gross.startswith("**Biên lợi nhuận gộp · Q2/2025**") and "xếp từ cao đến thấp" in gross, gross
    rows = [line for line in gross.splitlines() if line.startswith("| ") and "---" not in line][1:]
    assert rows[0].startswith("| 1 | Masan Consumer | **44,1%**") and rows[1].startswith("| 2 | Vinamilk | **42,0%**"), rows[:2]     # Masan > Vinamilk về biên, dù lợi nhuận gộp tuyệt đối nhỏ hơn
    assert "**Chưa có trong bảng:**" in gross and "Sabeco" in gross and "chưa đối chiếu được số cần dùng" in gross
    ASK_LIMIT.reset()
    leverage = client.post("/api/ask", json={"question": "Xếp hạng tỷ lệ nợ trên vốn chủ sở hữu của các công ty quý 1/2026"}).json()["answer"]
    lev_rows = [line for line in leverage.splitlines() if line.startswith("| ") and "---" not in line][1:]
    assert "xếp từ thấp đến cao" in leverage and lev_rows[0].startswith("| 1 | Mộc Châu Milk | **12,2%**") and lev_rows[-1].startswith("| 11 | AgriS | **211,6%**"), lev_rows
    assert "Bibica (chưa có báo cáo kỳ này)" in leverage
    ASK_LIMIT.reset()
    net = client.post("/api/ask", json={"question": "Công ty nào có biên lợi nhuận ròng thấp nhất quý 2/2026?"}).json()["answer"]
    net_rows = [line for line in net.splitlines() if line.startswith("| ") and "---" not in line][1:]
    assert "xếp từ thấp đến cao" in net and net_rows[0].startswith("| 1 | KIDO | **0,5%**"), net_rows[:1]
    ASK_LIMIT.reset()
    wide_ratio = client.post("/api/ask", json={"question": "Vinamilk so với KIDO về biên lợi nhuận gộp quý 2/2026"}).json()["answer"]
    assert "- **Biên lợi nhuận gộp:** Vinamilk 43,5%, KIDO 21,9%. Vinamilk cao hơn KIDO +21,6 điểm %." in wide_ratio
    assert "| Biên lợi nhuận trước thuế | 20,7% | 2,8% |" in wide_ratio and "| Dẫn đầu |" in wide_ratio
    # Chưa có số đã đối chiếu: không in lại chữ OCR thô (số không nhãn cột dễ bị đọc nhầm là số quý), chỉ chỉ trang nguồn
    import re as _re
    for q in ("Doanh thu Sabeco quý 2/2025", "So sánh doanh thu và lợi nhuận sau thuế Q2/2026 của KIDO và Masan Consumer",
              "Tình hình tài chính của Sabeco quý 3/2025"):
        ASK_LIMIT.reset()
        reply = client.post("/api/ask", json={"question": q}).json()
        assert not _re.search(r"\d{1,3}(,\d{3}){3,}", reply["answer"]), reply["answer"]          # số OCR viết bằng dấu phẩy ("12,615,062,955,827")
        assert "Doanh thu thuan" not in reply["answer"] and "thuån" not in reply["answer"], reply["answer"]
    ASK_LIMIT.reset()
    sab = client.post("/api/ask", json={"question": "Doanh thu Sabeco quý 2/2025"}).json()
    assert "Chưa có số đã đối chiếu" in sab["answer"] and "Trang có dòng liên quan" in sab["answer"] and sab["sources"], sab["answer"]
    print("PASS: nhận diện 11 công ty, nguồn của 99 PDF, tra cứu, so sánh, dòng tiền và thuyết minh.")


if __name__ == "__main__":
    main()
