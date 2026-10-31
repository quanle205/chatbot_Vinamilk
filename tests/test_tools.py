"""Kiểm thử công cụ tra số/tính chỉ số. Chạy: python tests/test_tools.py  (hoặc pytest tests)

Số mốc lấy trực tiếp từ PDF gốc (đọc bằng mắt trên ảnh trang), không lấy từ DuckDB, để bắt lỗi ánh xạ mã
giữa TT200 (2025) và TT99 (2026) và lỗi suy ra số quý.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.tools.analyst import Analyst  # noqa: E402
from src.tools.calc import calculate  # noqa: E402
from src.tools.facts import Facts  # noqa: E402
from src.tools.metrics import find_metrics, get_metric  # noqa: E402
from src.tools.registry import TOOL_SPECS, call_tool  # noqa: E402

A = Analyst(Facts())
PERIODS = A.f.periods()


def val(metric, period, basis="quy"):
    r = A.metric(metric, period, basis)
    assert r["ok"], r
    return r["value"]


def test_numbers_from_pdf():
    assert val("doanh_thu_thuan", "Q1/2026") == 16_148_657_871_623            # q1-2026.pdf tr.11
    assert val("loi_nhuan_sau_thue", "Q1/2026") == 2_458_221_002_532
    assert val("doanh_thu_thuan", "Q2/2025") == 16_724_597_479_554            # q2-2025.pdf tr.10
    assert val("tong_tai_san", "Q4/2025") == 53_312_370_717_301               # mã 270
    assert val("tong_tai_san", "Q1/2026") == 55_429_011_127_169               # mã 280 (TT99)
    assert val("tong_tai_san", "Q2/2026") == 57_451_803_693_875
    assert val("vay_ngan_han", "Q1/2025") == 10_060_066_017_395               # mã 320 (TT200)
    assert val("vay_ngan_han", "Q1/2026") == 10_334_848_158_086               # mã 321 (TT99)
    assert val("lai_lien_ket", "Q1/2026") == 48_459_806_269                   # mã 27 (TT99) vs mã 24 (TT200)
    assert val("lai_lien_ket", "Q1/2025") == 16_189_054_400


def test_q4_and_cashflow_are_derived_by_subtraction():
    r = A.metric("doanh_thu_thuan", "Q4/2025")
    assert r["value"] == 63_645_886_756_227 - 46_612_334_350_273 and any("suy ra" in n for n in r["notes"])
    assert val("doanh_thu_thuan", "Q4/2025", "luy_ke") == 63_645_886_756_227   # số cả năm in sẵn
    r = A.metric("luu_chuyen_hdkd", "Q2/2026")                                  # LCTT chỉ có lũy kế
    assert r["value"] == 3_473_788_102_329 - 269_326_997_516 and any("suy ra" in n for n in r["notes"])
    assert val("luu_chuyen_hdkd", "Q1/2026") == 269_326_997_516


def test_quarters_add_up_to_cumulative():
    for y in (2025, 2026):
        for m in ("doanh_thu_thuan", "gia_von", "loi_nhuan_sau_thue", "chi_phi_ban_hang"):
            q1, q2 = val(m, f"Q1/{y}"), val(m, f"Q2/{y}")
            assert q1 + q2 == val(m, f"Q2/{y}", "luy_ke"), (m, y)
    for m in ("doanh_thu_thuan", "loi_nhuan_sau_thue"):
        assert sum(val(m, f"Q{q}/2025") for q in (1, 2, 3, 4)) == val(m, "Q4/2025", "luy_ke")


def test_accounting_identities_hold_for_every_period():
    for p in PERIODS:
        s = str(p)
        assert val("doanh_thu_thuan", s) - val("gia_von", s) == val("loi_nhuan_gop", s), s
        assert val("loi_nhuan_truoc_thue", s) - val("thue_tndn_hien_hanh", s) - val("thue_tndn_hoan_lai", s) \
            == val("loi_nhuan_sau_thue", s), s
        assert val("tong_tai_san", s) == val("tong_nguon_von", s) == val("no_phai_tra", s) + val("von_chu_so_huu", s), s
        for basis in ("quy", "luy_ke"):                                         # LCTT: 20+30+40 = 50
            assert (val("luu_chuyen_hdkd", s, basis) + val("luu_chuyen_dau_tu", s, basis)
                    + val("luu_chuyen_tai_chinh", s, basis)) == val("luu_chuyen_tien_thuan", s, basis), (s, basis)


def test_growth_matches_press_figure():
    g = A.growth("doanh_thu_thuan", "Q1/2026", "yoy")
    assert g["ok"] and abs(g["growth"] - 0.24628) < 1e-4                       # báo chí: tăng 24,6%
    assert any("phân loại lại" in n for n in g["notes"])
    g = A.growth("tong_tai_san", "Q2/2026", "ytd")
    assert g["ok"] and g["base"] == 53_312_370_717_301 and g["current"] == 57_451_803_693_875
    g = A.growth("doanh_thu_thuan", "Q2/2026", "qoq")
    assert g["ok"] and g["base"] == 16_148_657_871_623
    g = A.growth("tong_tai_san", "Q1/2026", "yoy")                              # so với 31/3/2025 (báo cáo khác)
    assert g["ok"] and g["base"] == 55_013_790_227_766


def test_ratios():
    r = A.ratio("biên lợi nhuận gộp", "Q1/2026")
    assert abs(r["value"] - 6_895_926_044_077 / 16_148_657_871_623) < 1e-12
    r = A.ratio("bien_loi_nhuan_rong", "Q1/2026")
    assert abs(r["value"] - 2_458_221_002_532 / 16_148_657_871_623) < 1e-12
    r = A.ratio("thanh toan hien hanh", "Q1/2026")
    assert abs(r["value"] - 38_757_016_956_726 / 18_456_942_372_620) < 1e-12 and "tại ngày 31/3/2026" in r["text"]
    r = A.ratio("tỷ lệ nợ trên vốn chủ", "Q4/2025")
    assert abs(r["value"] - 18_829_355_431_194 / 34_483_015_286_107) < 1e-12
    # ROE tính độc lập từ ô DuckDB: LNST mẹ / VCSH mẹ bình quân
    c = A.f.cells
    lnst = c[("q1-2026", "KQKD", "61", "quy_nay")]["value"]
    eq_open = c[("q1-2026", "CDKT", "400", "dau_nam")]["value"] - c[("q1-2026", "CDKT", "429", "dau_nam")]["value"]
    eq_close = c[("q1-2026", "CDKT", "400", "cuoi_ky")]["value"] - c[("q1-2026", "CDKT", "429", "cuoi_ky")]["value"]
    r = A.ratio("roe", "Q1/2026")
    assert abs(r["value"] - lnst / ((eq_open + eq_close) / 2)) < 1e-12 and abs(r["annualized"] - 4 * r["value"]) < 1e-12
    r = A.ratio("roe", "Q4/2025", "luy_ke")                                      # cả năm: không quy năm thêm
    assert r["ok"] and "annualized" not in r
    r = A.ratio("vong quay ton kho", "Q2/2026")
    assert r["ok"] and r["unit"] == "lần" and r["annualized"] > r["value"]


def test_metric_lookup_by_natural_language():
    assert get_metric("lãi ròng").key == "loi_nhuan_sau_thue"
    assert get_metric("Doanh thu thuần").key == "doanh_thu_thuan"
    assert get_metric("tổng tài sản").key == "tong_tai_san"
    assert get_metric("vay ngân hàng ngắn hạn").key == "vay_ngan_han"
    assert find_metrics("xyz abc không liên quan") == []
    # chỉ tiêu con/gần giống không được ánh xạ nhầm sang chỉ tiêu tổng
    assert all(m.key != "chi_phi_ban_hang" for m in find_metrics("chi phí quảng cáo", 1))
    assert all(m.key != "loi_nhuan_hdkd" for m in find_metrics("ebit", 1))


def test_errors_are_values_not_exceptions():
    assert not A.metric("doanh_thu_thuan", "Q3/2026")["ok"]                    # chưa có báo cáo
    assert not A.metric("khong_co_chi_tieu_nay", "Q1/2026")["ok"]
    assert not A.metric("doanh_thu_thuan", "hôm qua")["ok"]
    assert not A.growth("tong_tai_san", "Q1/2025", "yoy")["ok"]                # không có số dư 31/3/2024
    assert not A.growth("doanh_thu_thuan", "Q1/2026", "ytd")["ok"]             # ytd chỉ cho số dư
    assert not call_tool("get_metric", {"metric": "doanh thu"})["ok"]          # thiếu period
    assert not call_tool("khong_co", {})["ok"]


def test_calculator_is_safe():
    assert abs(calculate("(16148.7 - 12957.5) / 12957.5 * 100") - 24.6282) < 1e-3
    assert calculate("2 ^ 3") == 8 and calculate("max(1, 2, 3) + sqrt(16)") == 7
    for bad in ("__import__('os').system('echo x')", "open('x')", "().__class__", "2 ** 1000", "1/0", "a + 1", "[1][0]"):
        try:
            calculate(bad)
        except (ValueError, ZeroDivisionError, SyntaxError):
            continue
        raise AssertionError(f"biểu thức nguy hiểm không bị chặn: {bad}")


def test_tool_specs_are_valid_and_dispatchable():
    names = [t["name"] for t in TOOL_SPECS]
    assert len(names) == len(set(names))
    for t in TOOL_SPECS:
        assert t["input_schema"]["type"] == "object" and t["description"]
        assert set(t["input_schema"]["required"]) <= set(t["input_schema"]["properties"])
    assert call_tool("get_metric", {"metric": "tổng tài sản", "period": "Q2/2026"})["value"] == 57_451_803_693_875
    assert call_tool("search_metrics", {"text": "lãi ròng"})["matches"][0]["key"] == "loi_nhuan_sau_thue"


def test_explain_change_contributions_sum_to_exact_difference():
    """Mọi kỳ, cả hai cơ sở so sánh và hai chỉ tiêu: tổng đóng góp = chênh lệch (sai số tối đa 1 đồng)."""
    checked = 0
    for metric in ("loi_nhuan_sau_thue", "doanh_thu_thuan"):
        for p in PERIODS:
            for base, basis in (("yoy", "quy"), ("yoy", "luy_ke"), ("qoq", "quy")):
                r = call_tool("explain_change", {"metric": metric, "period": str(p), "base": base, "basis": basis})
                if not r["ok"]:                                     # Q1/2025 không có quý liền trước
                    assert base == "qoq" and str(p) == "Q1/2025", (metric, p, base, r)
                    continue
                assert abs(sum(i["effect"] for i in r["items"]) - r["change"]) <= 1, (metric, p, base, basis)
                assert r["change"] == r["current"] - r["base"]
                assert not any(i["key"] == "khac" for i in r["items"]), "số liệu hiện có khớp đồng nhất thức, không cần dòng 'khác'"
                checked += 1
    assert checked >= 30


def test_explain_change_matches_pdf_landmarks_and_signs():
    r = call_tool("explain_change", {"metric": "lợi nhuận sau thuế", "period": "Q1/2026", "base": "yoy"})
    assert r["ok"] and r["current"] == 2_458_221_002_532 == val("loi_nhuan_sau_thue", "Q1/2026")            # q1-2026.pdf tr.11
    assert r["base"] == val("loi_nhuan_sau_thue", "Q1/2025") and r["current_label"] == "quý 1/2026"
    by = {i["key"]: i for i in r["items"]}
    assert by["doanh_thu"]["current"] == 16_148_657_871_623 and by["doanh_thu"]["effect"] == by["doanh_thu"]["current"] - by["doanh_thu"]["base"]
    g = call_tool("get_growth", {"metric": "giá vốn", "period": "Q1/2026", "kind": "yoy"})                 # cùng cột "cùng kỳ" (đã phân loại lại) như get_growth
    assert by["gia_von"]["effect"] == -(g["current"] - g["base"]) and by["gia_von"]["effect"] < 0         # chi phí tăng -> làm giảm lợi nhuận
    assert by["thue_tndn"]["current"] == -(val("thue_tndn_hien_hanh", "Q1/2026") + val("thue_tndn_hoan_lai", "Q1/2026"))
    assert r["sources"] and "Tổng các đóng góp bằng đúng chênh lệch" in r["text"] and "trang PDF" in r["text"]
    rev = call_tool("explain_change", {"metric": "doanh thu", "period": "Q1/2026"})
    assert rev["ok"] and rev["name"] == "doanh thu thuần" and [i["key"] for i in rev["items"]] == ["doanh_thu_gop", "giam_tru"]
    g = call_tool("get_growth", {"metric": "giảm trừ doanh thu", "period": "Q1/2026", "kind": "yoy"})
    assert rev["items"][1]["effect"] == -(g["current"] - g["base"])


def test_explain_change_rejects_bad_requests_as_values():
    for args in ({"metric": "tổng tài sản", "period": "Q1/2026"},                      # chỉ tiêu không hỗ trợ
                 {"metric": "lợi nhuận sau thuế", "period": "Q1/2025", "base": "qoq"},     # không có quý trước
                 {"metric": "lợi nhuận sau thuế", "period": "Q2/2026", "base": "qoq", "basis": "luy_ke"},
                 {"metric": "lợi nhuận sau thuế", "period": "Q9/2030"},
                 {"metric": "lợi nhuận sau thuế", "period": "Q1/2026", "base": "xyz"}):
        r = call_tool("explain_change", args)
        assert r["ok"] is False and r["error"], args
    assert call_tool("explain_change", {"period": "Q1/2026"})["ok"] is False                 # thiếu tham số


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
