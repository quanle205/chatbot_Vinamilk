"""Dựng tập câu hỏi đánh giá cho 12 công ty (nhánh trả lời bằng quy tắc, chạy offline, không cần Gemini).

Đáp án được tính ĐỘC LẬP từ các bảng DuckDB (facts + document_facts của consumer.duckdb; Vinamilk qua công cụ tra số đã kiểm thử),
không dùng hàm định dạng hay logic của ứng dụng, nên điểm đo được là điểm của chính ứng dụng, không phải của bộ sinh câu.

Hai tập tách biệt, dựng bằng hạt giống và cách diễn đạt khác nhau, không trùng (công ty, kỳ, chỉ tiêu):
  dev  -> eval/golden_companies.jsonl      : dùng để tìm lỗi và sửa
  val  -> eval/validation_companies.jsonl  : chỉ chấm, KHÔNG sửa mã dựa trên nó rồi chấm lại chính nó (nếu cần sửa, dựng tập mới)
Chạy: python eval/build_company_golden.py            (dựng cả hai)    rồi    python eval/company_eval.py --golden eval/golden_companies.jsonl
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import duckdb  # noqa: E402

from src.consumer.catalog import COMPANIES, METRICS  # noqa: E402
from src.tools.registry import call_tool  # noqa: E402

TAKEN: set = set()          # dữ kiện đã dùng (ở dev hay val): hai tập không bao giờ hỏi cùng một dữ kiện
DB = duckdb.connect(str(ROOT / "data/processed/consumer.duckdb"), read_only=True, config={"threads": 1})
QUARTERS = [f"Q{q}/{y}" for y in (2025, 2026) for q in (1, 2, 3, 4) if (y, q) <= (2026, 3)]
NAMES = {code: name for code, (name, _) in COMPANIES.items()} | {"VNM": "Vinamilk"}
FLOW = ("doanh_thu_thuan", "loi_nhuan_gop", "loi_nhuan_sau_thue")
BALANCE = ("tong_tai_san", "no_phai_tra", "von_chu_so_huu")
LABEL = {"doanh_thu_thuan": "doanh thu thuần", "loi_nhuan_gop": "lợi nhuận gộp", "loi_nhuan_sau_thue": "lợi nhuận sau thuế",
         "tong_tai_san": "tổng tài sản", "no_phai_tra": "nợ phải trả", "von_chu_so_huu": "vốn chủ sở hữu"}
RATIO_DEF = {"bien_gop": ("loi_nhuan_gop", "doanh_thu_thuan", "biên lợi nhuận gộp", "Biên lợi nhuận gộp"),
             "bien_rong": ("loi_nhuan_sau_thue", "doanh_thu_thuan", "biên lợi nhuận ròng", "Biên lợi nhuận ròng"),
             "no_von": ("no_phai_tra", "von_chu_so_huu", "tỷ lệ nợ trên vốn chủ sở hữu", "Nợ phải trả / vốn chủ sở hữu")}


# ---------------------------------------------------------------- đọc số độc lập từ DuckDB
def fact(code: str, period: str, metric: str, basis: str):
    """(giá trị, phạm vi) nếu chỉ có đúng một giá trị trong facts + document_facts; không thì None."""
    if code == "VNM":
        res = call_tool("get_metric", {"metric": metric, "period": period, "basis": basis})
        return (res["value"], "hợp nhất") if res.get("ok") and res.get("metric", metric) == metric else None
    rows = DB.execute("""select distinct value, scope from (
            select f.value, r.scope from facts f join reports r using(company, period) where f.company=? and f.period=? and f.metric=? and f.basis=?
            union all select f.value, f.scope from document_facts f join documents d using(id)
                      where d.company=? and d.period=? and f.metric=? and f.basis=?)""", [code, period, metric, basis, code, period, metric, basis]).fetchall()
    return rows[0] if len(rows) == 1 else None


def basis_of(metric: str) -> str:
    return "point" if metric in BALANCE else "quy"


def values_for(code: str, period: str, metrics=("doanh_thu_thuan", "loi_nhuan_gop", "loi_nhuan_truoc_thue", "loi_nhuan_sau_thue", *BALANCE)) -> dict:
    out = {}
    for metric in metrics:
        got = fact(code, period, metric, basis_of(metric))
        if got:
            out[metric] = got[0]
    return out


def ratio(code: str, period: str, key: str):
    num, den = RATIO_DEF[key][:2]
    v = values_for(code, period, (num, den))
    return v[num] / v[den] if num in v and v.get(den, 0) > 0 else None


# ---------------------------------------------------------------- định dạng độc lập (không dùng hàm của ứng dụng)
def dots(x: int) -> str:
    return f"{x:,}".replace(",", ".")


def ty(x: float) -> str:
    return f"{x / 1e9:,.1f}".replace(",", "_").replace(".", ",").replace("_", ".")


def pc(x: float) -> str:
    return f"{x * 100:.1f}%".replace(".", ",")


def spc(x: float) -> str:
    return f"{x * 100:+.1f}%".replace(".", ",")


def case(prefix: str, n: int, category: str, question: str, behavior="answer", contains=(), absent=(), sources=False, any_of=()) -> dict:
    return {"id": f"{prefix}-{category}-{n:02d}", "category": category, "question": question, "behavior": behavior,
            "contains": list(contains), "absent": list(absent), "any_of": list(any_of), "expect_sources": sources}


def qtext(period: str) -> str:
    return f"quý {period[1]}/{period[3:]}"


def build(split: str) -> list[dict]:
    dev = split == "dev"
    rng = random.Random(11 if dev else 29)
    prefix = "dev" if dev else "val"
    cases: list[dict] = []
    used = TAKEN

    def pick(items, k):
        items = list(items)
        rng.shuffle(items)
        return items[:k]

    # ---- tra số: mỗi công ty một chỉ tiêu dòng và một chỉ tiêu số dư ở các quý có số
    n = 0
    for code in COMPANIES:
        for metrics in (FLOW, BALANCE):
            options = [(m, p) for m in metrics for p in QUARTERS if fact(code, p, m, basis_of(m)) and (code, p, m) not in used]
            if not options:
                continue
            metric, period = rng.choice(options)
            used.add((code, period, metric))
            value = fact(code, period, metric, basis_of(metric))[0]
            if value <= 0:
                continue
            name = NAMES[code]
            question = (f"{LABEL[metric].capitalize()} {qtext(period)} của {name}?" if dev
                        else f"{code} {LABEL[metric]} {period} là bao nhiêu")
            n += 1
            cases.append(case(prefix, n, "tra_so", question, contains=[dots(value)], sources=True))

    # ---- tỷ số một công ty
    n = 0
    for code in pick(list(COMPANIES), 9):
        key = rng.choice(list(RATIO_DEF))
        options = [p for p in QUARTERS if ratio(code, p, key) is not None and ("ty_so", code, p, key) not in TAKEN]
        if not options:
            continue
        period = rng.choice(options)
        TAKEN.add(("ty_so", code, period, key))
        value = ratio(code, period, key)
        n += 1
        question = (f"{RATIO_DEF[key][3]} của {NAMES[code]} {qtext(period)}?" if dev else f"{code} {RATIO_DEF[key][2]} {period}")
        cases.append(case(prefix, n, "ty_so", question, contains=[pc(value)], sources=True))

    # ---- xếp hạng theo đúng tỷ số được hỏi
    n = 0
    for key, period in pick([(k, p) for k in RATIO_DEF for p in QUARTERS if ("xep_hang", k, p) not in TAKEN], 40):
        entities = [(c, ratio(c, period, key)) for c in ("VNM", *COMPANIES)]
        entities = [(c, r) for c, r in entities if r is not None]
        if len(entities) < 6 or n >= 6:
            continue
        TAKEN.add(("xep_hang", key, period))
        ascending = key == "no_von"
        ordered = sorted(entities, key=lambda e: e[1], reverse=not ascending)
        first, last = ordered[0], ordered[-1]
        n += 1
        if key == "no_von":
            question = (f"Xếp hạng tỷ lệ nợ trên vốn chủ sở hữu của các công ty {qtext(period)}" if dev
                        else f"công ty nào có tỷ lệ nợ trên vốn chủ sở hữu thấp nhất {period}")
        else:
            question = (f"Công ty nào có {RATIO_DEF[key][2]} cao nhất {qtext(period)}?" if dev
                        else f"Xếp hạng {RATIO_DEF[key][2]} của các công ty {period}")
        cases.append(case(prefix, n, "xep_hang", question,
                          contains=[f"| 1 | {NAMES[first[0]]} | **{pc(first[1])}**", f"| {len(ordered)} | {NAMES[last[0]]} | **{pc(last[1])}**"], sources=True))

    # ---- tăng trưởng so với cùng kỳ
    n = 0
    for code in pick(list(COMPANIES), 11):
        for metric in pick(["doanh_thu_thuan", "loi_nhuan_sau_thue"], 1):
            options = []
            for period in QUARTERS:
                q, y = int(period[1]), int(period[3:])
                base = f"Q{q}/{y - 1}"
                cur_f, base_f = fact(code, period, metric, "quy"), fact(code, base, metric, "quy")
                if cur_f and base_f and cur_f[1] == base_f[1] and base_f[0] > 0 and ("tang_truong", code, metric, period) not in TAKEN:
                    options.append((period, base, cur_f[0], base_f[0]))
            if not options or n >= 7:
                continue
            period, base, cur, prev = rng.choice(options)
            TAKEN.add(("tang_truong", code, metric, period))
            n += 1
            question = (f"{LABEL[metric].capitalize()} {qtext(period)} của {NAMES[code]} tăng giảm bao nhiêu phần trăm so với cùng kỳ?" if dev
                        else f"tăng trưởng {LABEL[metric]} {code} {period} so với cùng kỳ năm trước")
            cases.append(case(prefix, n, "tang_truong", question, contains=[spc((cur - prev) / prev), f"{ty(prev)} → {ty(cur)}"], sources=True))

    # ---- vì sao lợi nhuận đổi (cầu nối): tổng thay đổi phải đúng bằng chênh lệch lợi nhuận sau thuế
    n = 0
    for code in pick(["VNM", *COMPANIES], 12):
        options = []
        for period in QUARTERS:
            q, y = int(period[1]), int(period[3:])
            base = f"Q{q}/{y - 1}"
            a, b = values_for(code, period), values_for(code, base)
            need = ("doanh_thu_thuan", "loi_nhuan_gop", "loi_nhuan_truoc_thue", "loi_nhuan_sau_thue")
            sa, sb = fact(code, period, "doanh_thu_thuan", "quy"), fact(code, base, "doanh_thu_thuan", "quy")
            if (all(k in a and k in b for k in need) and sa and sb and sa[1] == sb[1] and a["doanh_thu_thuan"] > 0 and b["doanh_thu_thuan"] > 0
                    and ("vi_sao", code, period) not in TAKEN):
                options.append((period, a["loi_nhuan_sau_thue"] - b["loi_nhuan_sau_thue"]))
        if not options or n >= 5:
            continue
        period, change = rng.choice(options)
        TAKEN.add(("vi_sao", code, period))
        n += 1
        signed = f"{change / 1e9:+,.1f}".replace(",", "_").replace(".", ",").replace("_", ".")
        question = (f"Vì sao lợi nhuận sau thuế {qtext(period)} của {NAMES[code]} thay đổi so với cùng kỳ năm trước?" if dev
                    else f"{NAMES[code]} lợi nhuận {period} {'tăng' if change > 0 else 'giảm'} do đâu so với cùng kỳ")
        cases.append(case(prefix, n, "vi_sao", question, contains=[f"Tổng thay đổi lợi nhuận sau thuế** | **{signed}**", "không cho biết nguyên nhân kinh doanh"], sources=True))

    # ---- đánh giá (trả lời bằng số, không từ chối, không hỏi lại)
    n = 0
    for code in pick(["VNM", *COMPANIES], 12):
        options = [p for p in QUARTERS if ratio(code, p, "bien_gop") is not None and ratio(code, p, "bien_rong") is not None
                   and ("danh_gia", code, p) not in TAKEN]
        if not options or n >= 5:
            continue
        period = rng.choice(options)
        TAKEN.add(("danh_gia", code, period))
        n += 1
        question = (f"{NAMES[code]} có hiệu quả sinh lời tốt không {qtext(period)}?" if dev else f"{code} sinh lời có ổn không trong {period}")
        cases.append(case(prefix, n, "danh_gia", question, contains=[f"**Đánh giá khả năng sinh lời của {NAMES[code]} · ", "**Tóm lại:**",
                                                                     f"| Biên lợi nhuận gộp | {pc(ratio(code, period, 'bien_gop'))}"],
                          absent=["chỉ trả lời về số liệu", "Bạn muốn xem"], sources=True))

    # ---- so sánh hai bên (có Vinamilk): cả hai giá trị phải xuất hiện
    n = 0
    for code in pick(list(COMPANIES), 8):
        options = [p for p in QUARTERS if "doanh_thu_thuan" in values_for(code, p, ("doanh_thu_thuan",)) and "doanh_thu_thuan" in values_for("VNM", p, ("doanh_thu_thuan",))
                   and ratio(code, p, "bien_gop") is not None and ratio("VNM", p, "bien_gop") is not None and ("so_sanh", code, p) not in TAKEN]
        if not options or n >= 4:
            continue
        period = rng.choice(options)
        TAKEN.add(("so_sanh", code, period))
        n += 1
        a, b = ratio("VNM", period, "bien_gop"), ratio(code, period, "bien_gop")
        question = (f"Vinamilk so với {NAMES[code]} về biên lợi nhuận gộp {qtext(period)}" if dev else f"so sánh biên lợi nhuận gộp {period} của Vinamilk và {code}")
        cases.append(case(prefix, n, "so_sanh", question, contains=[pc(a), pc(b)], sources=True))

    # ---- xu hướng qua các quý: hai quý bất kỳ có số phải xuất hiện, kèm biểu đồ
    n = 0
    for code in pick([c for c in COMPANIES if ("xu_huong", c) not in TAKEN], 6):
        have = [(p, fact(code, p, "doanh_thu_thuan", "quy")) for p in QUARTERS]
        have = [(p, f[0]) for p, f in have if f]
        if len(have) < 3 or n >= 3:
            continue
        TAKEN.add(("xu_huong", code))
        n += 1
        chosen = pick(have, 2)
        question = f"Doanh thu của {NAMES[code]} qua các quý" if dev else f"{code} doanh thu theo từng quý"
        cases.append(case(prefix, n, "xu_huong", question, contains=[f"| {p} | " for p, _ in chosen] + [ty(v) for _, v in chosen], sources=True))

    # ---- thiếu số: nói rõ chưa có, không in chữ OCR thô
    n = 0
    gaps = [(c, p) for c in COMPANIES for p in QUARTERS if not fact(c, p, "doanh_thu_thuan", "quy") and ("thieu_so", c, p) not in TAKEN]
    for code, period in pick(gaps, 4):
        TAKEN.add(("thieu_so", code, period))
        n += 1
        cases.append(case(prefix, n, "thieu_so", f"Doanh thu {qtext(period)} của {NAMES[code]}" if dev else f"{code} doanh thu {period}",
                          behavior="no_data", contains=["Chưa có"]))

    # ---- ngoài phạm vi: phải từ chối
    refuse = ["Giá cổ phiếu KDC hôm nay là bao nhiêu?", "Có nên mua cổ phiếu SAB không?", "Dự báo doanh thu KIDO năm 2027", "Hôm nay thời tiết Hà Nội thế nào?"] if dev else \
             ["Cổ phiếu Masan Consumer có tốt không?", "Nên đầu tư vào Habeco không", "Giá mục tiêu của QNS?", "Viết giúp tôi bài thơ về mùa xuân"]
    for i, question in enumerate(refuse, 1):
        cases.append(case(prefix, i, "ngoai_pham_vi", question, behavior="refuse", any_of=["chỉ trả lời", "không thể trả lời"], absent=["tỷ đồng"]))

    # ---- (chỉ dev, viết sau khi người dùng báo lỗi) số năm 2025, chỉ tiêu mở rộng, khoản mục chưa có số
    if dev:
        n = 0
        for code in COMPANIES:
            if code in ("SBT", "MCH"):                                          # SBT: năm tài chính kết thúc 30/6; MCH: báo cáo năm không có bảng có mã, xử lý riêng bên dưới
                continue
            got = fact(code, "FY2025", "tong_tai_san", "point")
            if got and got[0] > 0:
                n += 1
                cases.append(case(prefix, n, "nam_2025", f"Tổng tài sản năm 2025 của {NAMES[code]}", contains=[dots(got[0])], absent=["Chưa có"], sources=True))
        q4 = fact("MCH", "Q4/2025", "doanh_thu_thuan", "luy_ke")
        if q4:
            cases.append(case(prefix, n + 1, "nam_2025", "Doanh thu thuần năm 2025 của Masan Consumer",
                              contains=[dots(q4[0]), "Số lấy từ báo cáo Q4/2025 vì báo cáo năm chưa có dòng này"], sources=True))
        n = 0
        for code in pick(list(COMPANIES), 11):
            options = [(m, p) for m in ("tai_san_ngan_han", "no_ngan_han", "gia_von") for p in QUARTERS
                       if fact(code, p, m, "point" if m != "gia_von" else "quy") and ("chi_tieu_mo_rong", code, p, m) not in TAKEN]
            if not options or n >= 8:
                continue
            metric, period = rng.choice(options)
            TAKEN.add(("chi_tieu_mo_rong", code, period, metric))
            value = fact(code, period, metric, "point" if metric != "gia_von" else "quy")[0]
            n += 1
            name = {"tai_san_ngan_han": "Tài sản ngắn hạn", "no_ngan_han": "Nợ ngắn hạn", "gia_von": "Giá vốn hàng bán"}[metric]
            cases.append(case(prefix, n, "chi_tieu_mo_rong", f"{name} {qtext(period)} của {NAMES[code]}", contains=[dots(value)], absent=["Tóm tắt"], sources=True))
        for i, item in enumerate(("Chi phí bán hàng năm 2025 của KIDO", "Phải thu khách hàng quý 2/2026 của Sabeco", "Khấu hao quý 1/2026 của Masan Consumer"), 1):
            cases.append(case(prefix, i, "khoan_muc", item, contains=["chưa có số đã đối chiếu của khoản mục này"], absent=["Tóm tắt"], sources=True))

    # ---- câu hỏi về chính bộ dữ liệu
    cases.append(case(prefix, 1, "danh_muc", "Có bao nhiêu công ty trong dữ liệu của bạn?" if dev else "Dữ liệu gồm những công ty nào?", contains=["12 công ty", "Sabeco"]))

    # ---- Vinamilk (nhánh xác định): kỳ ngoài dữ liệu tức thì, đánh giá, vì sao
    cases.append(case(prefix, 1, "vinamilk", "Doanh thu quý 3/2026 của Vinamilk là bao nhiêu?" if dev else "Lợi nhuận Vinamilk năm 2024",
                      behavior="no_data", contains=["Chưa có báo cáo", "Q1/2025 đến Q2/2026"]))
    cases.append(case(prefix, 2, "vinamilk", "Vinamilk có khả năng thanh toán nợ tốt không?" if dev else "Nợ của Vinamilk có an toàn không?",
                      contains=["**Đánh giá mức nợ và độ an toàn tài chính của Vinamilk", "hệ số thanh toán hiện hành"], absent=["Bạn muốn xem nợ nào"], sources=True))
    return cases


def main():
    dev, val = build("dev"), build("val")
    overlap = {c["question"] for c in dev} & {c["question"] for c in val}
    assert not overlap, overlap
    for name, rows in (("golden_companies", dev), ("validation_companies", val)):
        out = ROOT / "eval" / f"{name}.jsonl"
        out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
        counts = {}
        for r in rows:
            counts[r["category"]] = counts.get(r["category"], 0) + 1
        print(f"{out.name}: {len(rows)} câu", counts)


if __name__ == "__main__":
    main()
