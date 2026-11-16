"""Kiểm thử bộ trích chỉ tiêu theo nội dung (src/ingest/consumer_extract.py). Chạy: python tests/test_consumer_extract.py

- Phần 1 dùng trang OCR giả lập, luôn chạy được.
- Phần 2 so với số MCM/QNS đã đối chiếu tay; cần data/interim (OCR trung gian, không đưa lên git) nên tự bỏ qua khi không có.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ingest.consumer_extract import extract_document, has_phrase, near, scaled_units, scope_of  # noqa: E402


def box(x, y, text):
    return [x, y, x + 0.02 * max(len(text), 1), y + 0.01, text, 1.0]


def table(rows, header=""):
    """Trang OCR giả: `rows` = [(mã dòng, [các cột số])]; cột mã ở x=0.48, các số ở x=0.62, 0.80, ..."""
    boxes = [box(0.1, 0.05, w) for w in header.split()]
    for i, (code, values) in enumerate(rows):
        y = 0.4 + i * 0.025
        boxes.append(box(0.48, y, code))
        boxes.extend(box(0.62 + 0.18 * j, y, f"{v:,}".replace(",", ".")) for j, v in enumerate(values))
    return boxes


BALANCE = [("100", [500_000_000_000, 450_000_000_000]), ("200", [400_000_000_000, 350_000_000_000]),
           ("270", [900_000_000_000, 801_000_000_000]), ("310", [200_000_000_000, 150_000_000_000]),
           ("300", [300_000_000_000, 250_000_000_000]), ("400", [600_000_000_000, 551_000_000_000]),
           ("440", [900_000_000_000, 801_000_000_000])]


def test_fuzzy_phrase_and_scope():
    assert near("tii", "tai") and near("hcp", "hop") and not near("cat", "tai") and not near("ab", "ac")
    assert has_phrase("bao cao tai chinh cao tinh hinh tii chinh hcp nhat", "tinh hinh tai chinh")
    assert scope_of("bao cao tai chinh hcp nhat quy 2") == "hợp nhất"
    assert scope_of("bao cao tai chinh rieng") == "riêng"
    assert scope_of("bao cao tai chinh") == "theo báo cáo"
    assert scaled_units("don vi tinh: nghin dong") and not scaled_units("don vi tinh: vnd")


def test_balance_sheet_accepted_only_when_identity_holds():
    got = extract_document({1: table(BALANCE, "bao cao tinh hinh tai chinh hop nhat don vi tinh vnd")}, "XXX", "Q2/2026")
    assert got["tong_tai_san", "point"][0] == 900_000_000_000 and got["no_phai_tra", "point"][0] == 300_000_000_000
    assert got["von_chu_so_huu", "point"][0] == 600_000_000_000 and got["tong_tai_san", "point"][2] == "hợp nhất"
    wrong = [("270", [900_000_000_000, 800_000_000_000]), ("300", [300_000_000_000, 250_000_000_000]),
             ("400", [599_000_000_000, 550_000_000_000])]                          # 300 + 599 != 900
    assert not extract_document({1: table(wrong)}, "XXX", "Q2/2026")
    opening_off = BALANCE[:2] + [("270", [900_000_000_000, 800_000_000_000]), ("310", [200_000_000_000, 150_000_000_000]),
                                 ("300", [300_000_000_000, 250_000_000_000]), ("400", [600_000_000_000, 551_000_000_000])]                   # cột cuối kỳ khớp, cột đầu năm lệch: chỉ cột cuối kỳ được dùng
    assert extract_document({1: table(opening_off)}, "XXX", "Q2/2026")["tong_tai_san", "point"][0] == 900_000_000_000
    one_number = table(BALANCE)
    one_number = [b for b in one_number if not (b[4] == "801.000.000.000" and abs(b[1] - 0.45) < 0.01)]      # OCR bỏ mất số đầu năm của dòng 270
    got = extract_document({1: one_number}, "XXX", "Q2/2026")
    assert got["tong_tai_san", "point"][0] == 900_000_000_000 and got["von_chu_so_huu", "point"][0] == 600_000_000_000


def test_thousand_dong_tables_and_implausible_scale_are_rejected():
    assert not extract_document({1: table(BALANCE, "don vi tinh nghin dong")}, "XXX", "Q2/2026")
    tiny = [(code, [v // 1000 for v in values]) for code, values in BALANCE]        # tổng tài sản 900 triệu: sai đơn vị
    assert not extract_document({1: table(tiny)}, "XXX", "Q2/2026")


def test_two_different_valid_statements_are_ambiguous_and_skipped():
    other = [("270", [1_200_000_000_000, 1_000_000_000_000]), ("300", [500_000_000_000, 400_000_000_000]),
             ("400", [700_000_000_000, 600_000_000_000])]
    assert not extract_document({1: table(BALANCE), 2: table(other)}, "XXX", "Q2/2026")      # vd báo cáo riêng + hợp nhất: không đoán


def test_income_statement_columns_and_identity():
    rows = [("10", [1_000_000, 900_000, 2_000_000, 1_800_000]), ("11", [600_000, 540_000, 1_200_000, 1_080_000]),
            ("20", [400_000, 360_000, 800_000, 720_000])]
    scaled = [(code, [v * 1000 for v in values]) for code, values in rows]
    got = extract_document({1: table(scaled)}, "XXX", "Q2/2026")
    assert got["doanh_thu_thuan", "quy"][0] == 1_000_000_000 and got["doanh_thu_thuan", "luy_ke"][0] == 2_000_000_000
    assert got["loi_nhuan_gop", "quy"][0] == 400_000_000 and got["doanh_thu_thuan", "quy"][3] == "KQKD"
    broken = [("10", [1_000_000_000, 900_000_000, 2_000_000_000, 1_800_000_000]), ("11", [600_000_000, 540_000_000, 1_200_000_000, 1_080_000_000]),
              ("20", [399_000_000, 360_000_000, 800_000_000, 720_000_000])]          # 1.000 - 600 != 399
    partial = extract_document({1: table(broken)}, "XXX", "Q2/2026")
    assert ("doanh_thu_thuan", "quy") not in partial and ("loi_nhuan_gop", "quy") not in partial      # cột quý lệch: bỏ cả cột
    assert partial["doanh_thu_thuan", "luy_ke"][0] == 2_000_000_000                                  # cột lũy kế vẫn thỏa đẳng thức nên giữ
    two_columns = [(code, values[:2]) for code, values in scaled]
    assert not extract_document({1: table(two_columns)}, "XXX", "Q2/2026")              # Q2 mà chỉ hai cột: không biết riêng quý hay lũy kế
    assert extract_document({1: table(two_columns)}, "XXX", "Q1/2026")["doanh_thu_thuan", "quy"][0] == 1_000_000_000


def test_extractor_matches_hand_verified_numbers_for_mcm_and_qns():
    import json

    import duckdb

    from src.ingest.consumer_documents import report_period
    from src.ingest.consumer_ocr import INTERIM, inputs
    from src.consumer.repository import DB_PATH

    if not INTERIM.exists():
        print("  (bỏ qua: không có data/interim)")
        return
    with duckdb.connect(str(DB_PATH), read_only=True, config={"threads": 1}) as db:
        truth = {(c, p, m, b): v for c, p, m, b, v in db.execute("select company, period, metric, basis, value from facts").fetchall()}
    compared = 0
    for row in inputs():
        company, period = row["company_code"], report_period(row)
        if company not in ("MCM", "QNS") or (company, period, "tong_tai_san", "point") not in truth:
            continue
        folder = INTERIM / Path(row["file"]).stem
        pages = {int(f.stem): json.loads(f.read_text(encoding="utf-8")) for f in folder.glob("*.json")}
        for (metric, basis), (value, *_rest) in extract_document(pages, company, period).items():
            expected = truth.get((company, period, metric, basis))
            if expected is not None:
                assert value == expected, (company, period, metric, basis, value, expected)
                compared += 1
    assert compared >= 80, compared                      # phủ phần lớn 118 số đã đối chiếu tay và không sai số nào


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
