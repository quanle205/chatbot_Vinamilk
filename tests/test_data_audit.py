"""Kiểm thử kiểm định dữ liệu (eval/data_audit.py): DB phải thỏa mọi đẳng thức và bộ kiểm phải đủ nhạy. Chạy: python tests/test_data_audit.py"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("data_audit", ROOT / "eval" / "data_audit.py")
da = importlib.util.module_from_spec(spec)
spec.loader.exec_module(da)


def run():
    a = da.Audit(0)
    a.run()
    a.full_eq()
    return a


def hard_failures(a):
    return [(g, n, r[1], r[2]) for (g, n), rows in a.results.items() if g != "INFO" for r in rows if not r[0]]


def test_database_satisfies_all_accounting_identities():
    a = run()
    bad = hard_failures(a)
    assert not bad, bad[:5]
    assert sum(len(r) for (g, _), r in a.results.items() if g != "INFO") >= 600           # không thể "đạt" vì chẳng kiểm gì


def test_identities_cover_nearly_every_cell():
    a = run()
    assert len(a.touched) / len(a.f.cells) >= 0.95, f"{len(a.touched)}/{len(a.f.cells)}"


def test_detector_catches_an_injected_ocr_error():
    a = run()
    key = ("q2-2026", "KQKD", "10", "quy_nay")
    assert key in a.f.cells
    orig = a.f.cells[key]["value"]
    a.f.cells[key]["value"] = orig + 1000                              # sai một chữ số hàng nghìn
    try:
        b = da.Audit(0)
        b.f = a.f
        b.run()
        b.full_eq()
        assert hard_failures(b), "đổi số doanh thu thuần mà không đẳng thức nào vỡ"
    finally:
        a.f.cells[key]["value"] = orig


def test_tolerance_zero_is_strict():
    a = da.Audit(0)
    assert a.tol == 0 and da.Audit(5).tol == 5


if __name__ == "__main__":
    fails = 0
    for n, f in sorted(globals().items()):
        if n.startswith("test_") and callable(f):
            try:
                f()
                print("PASS", n)
            except Exception as e:                                       # noqa: BLE001
                fails += 1
                print("FAIL", n, "->", repr(e)[:400])
    sys.exit(1 if fails else 0)
