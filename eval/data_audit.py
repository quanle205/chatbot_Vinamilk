"""Kiểm định dữ liệu: các đẳng thức kế toán và kiểm tra chéo giữa các báo cáo trên số liệu trong DuckDB.

Golden set đo agent so với DB; script này đo CHÍNH DB (nguồn gốc rủi ro: OCR sai thì mọi tầng sau đều sai mà không ai biết).
Mỗi đẳng thức nối nhiều ô số liệu độc lập, nên một chữ số OCR sai gần như chắc chắn làm vỡ ít nhất một đẳng thức.
Số liệu BCTC tính bằng đồng, các tổng phải khớp tuyệt đối (dung sai mặc định 0).

Nhóm:
  CDKT  bảng cân đối: tài sản = ngắn hạn + dài hạn; tài sản = nguồn vốn; nguồn vốn = nợ + vốn chủ; nợ = ngắn hạn + dài hạn
  KQKD  doanh thu thuần, lợi nhuận gộp, lợi nhuận trước/sau thuế, phân bổ cho cổ đông
  LCTT  lưu chuyển tiền thuần = kinh doanh + đầu tư + tài chính
  CHEO  kiểm tra chéo: số đầu năm 1/1/2025 phải như nhau ở mọi báo cáo 2025; quý 1 + quý 2 = lũy kế 6 tháng...
  INFO  chênh lệch được kỳ vọng do phân loại lại TT99 (chỉ thông báo, không tính là lỗi)
Chạy: python eval/data_audit.py [--tol 0] [--verbose]      Thoát mã 1 nếu có đẳng thức cứng bị vỡ.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.tools.facts import DataUnavailable, Facts, Period  # noqa: E402
from src.tools.metrics import get_metric  # noqa: E402

M = get_metric


class Audit:
    def __init__(self, tol: int = 0):
        self.f = Facts()
        self.tol = tol
        self.periods = self.f.periods()
        self.touched: set = set()
        self.results: dict[str, list] = {}        # tên -> [(đạt, mô tả, chênh lệch, trạng thái các ô)]

    # ---- lấy giá trị, ghi lại ô đã chạm tới
    def _take(self, v):
        for s in v.sources:
            self.touched.add((s["doc"], s["statement"], s["code"], s["ky"]))
        return v.value, [s["status"] for s in v.sources]

    def bal(self, key, p):
        return self._take(self.f.balance(M(key), p))

    def opn(self, key, p):
        return self._take(self.f.opening(M(key), p, "luy_ke"))

    def flow(self, key, p, basis):
        return self._take(self.f.flow(M(key), p, basis))

    def check(self, group, name, where, lhs, rhs):
        """lhs, rhs: (giá trị, [trạng thái ô]) đã cộng/trừ sẵn. Ghi lại một lần kiểm."""
        diff = lhs[0] - rhs[0]
        self.results.setdefault((group, name), []).append((abs(diff) <= self.tol, where, diff, sorted(set(lhs[1] + rhs[1]))))

    @staticmethod
    def add(*parts):                                          # (giá trị, trạng thái) có dấu: phần tử dạng (+1|-1, (v, st))
        total, st = 0, []
        for sign, (v, s) in parts:
            total += sign * v
            st += s
        return total, st

    def run(self):
        P = self.periods
        for p in P:
            w = str(p)
            # ---- CDKT (số dư cuối kỳ)
            try:
                ta, tsnh, tsdh = self.bal("tong_tai_san", p), self.bal("tai_san_ngan_han", p), self.bal("tai_san_dai_han", p)
                nv, no, vcsh = self.bal("tong_nguon_von", p), self.bal("no_phai_tra", p), self.bal("von_chu_so_huu", p)
                nnh, ndh = self.bal("no_ngan_han", p), self.bal("no_dai_han", p)
                self.check("CDKT", "tổng tài sản = ngắn hạn + dài hạn", w, ta, self.add((1, tsnh), (1, tsdh)))
                self.check("CDKT", "tổng tài sản = tổng nguồn vốn", w, ta, nv)
                self.check("CDKT", "tổng nguồn vốn = nợ phải trả + vốn chủ sở hữu", w, nv, self.add((1, no), (1, vcsh)))
                self.check("CDKT", "nợ phải trả = nợ ngắn hạn + nợ dài hạn", w, no, self.add((1, nnh), (1, ndh)))
            except DataUnavailable as e:
                self.results.setdefault(("CDKT", "thiếu dữ liệu"), []).append((False, w, 0, [str(e)[:60]]))
            # ---- KQKD và LCTT, theo quý và lũy kế
            for basis in ("quy", "luy_ke"):
                if basis == "luy_ke" and p.quarter == 1:
                    continue                                   # trùng với quý
                w2 = f"{p} {'quý' if basis == 'quy' else 'lũy kế'}"
                try:
                    g = lambda k, b=basis, pp=p: self.flow(k, pp, b)         # noqa: E731
                    dt, dtbh, gt, gv, gop = g("doanh_thu_thuan"), g("doanh_thu_ban_hang"), g("giam_tru_doanh_thu"), g("gia_von"), g("loi_nhuan_gop")
                    self.check("KQKD", "doanh thu thuần = bán hàng − giảm trừ", w2, dt, self.add((1, dtbh), (-1, gt)))
                    self.check("KQKD", "lợi nhuận gộp = doanh thu thuần − giá vốn", w2, gop, self.add((1, dt), (-1, gv)))
                    lnst, lntt, th, thl = g("loi_nhuan_sau_thue"), g("loi_nhuan_truoc_thue"), g("thue_tndn_hien_hanh"), g("thue_tndn_hoan_lai")
                    self.check("KQKD", "LNST = LNTT − thuế hiện hành − thuế hoãn lại", w2, lnst, self.add((1, lntt), (-1, th), (-1, thl)))
                    self.check("KQKD", "LNST = LNST chủ sở hữu + cổ đông thiểu số", w2, lnst,
                               self.add((1, g("lnst_chu_so_huu")), (1, g("lnst_co_dong_thieu_so"))))
                    hd, lk = g("loi_nhuan_hdkd"), g("loi_nhuan_khac")
                    self.check("KQKD", "LNTT = lợi nhuận HĐKD + lợi nhuận khác", w2, lntt, self.add((1, hd), (1, lk)))
                    self.check("KQKD", "lợi nhuận khác = thu nhập khác − chi phí khác", w2, lk, self.add((1, g("thu_nhap_khac")), (-1, g("chi_phi_khac"))))
                    self.check("KQKD", "lợi nhuận HĐKD = gộp + DT tài chính − CP tài chính + liên kết − bán hàng − QLDN", w2, hd,
                               self.add((1, gop), (1, g("doanh_thu_tai_chinh")), (-1, g("chi_phi_tai_chinh")), (1, g("lai_lien_ket")),
                                        (-1, g("chi_phi_ban_hang")), (-1, g("chi_phi_qldn"))))
                except DataUnavailable as e:
                    self.results.setdefault(("KQKD", "thiếu dữ liệu"), []).append((False, w2, 0, [str(e)[:60]]))
                try:
                    g = lambda k, b=basis, pp=p: self.flow(k, pp, b)         # noqa: E731
                    self.check("LCTT", "lưu chuyển tiền thuần = kinh doanh + đầu tư + tài chính", w2, g("luu_chuyen_tien_thuan"),
                               self.add((1, g("luu_chuyen_hdkd")), (1, g("luu_chuyen_dau_tu")), (1, g("luu_chuyen_tai_chinh"))))
                except DataUnavailable as e:
                    self.results.setdefault(("LCTT", "thiếu dữ liệu"), []).append((False, w2, 0, [str(e)[:60]]))
        self.cross()

    def cross(self):
        # số dư 1/1/2025 (cột đầu năm) phải như nhau trong báo cáo Q1, Q2, Q3, Q4 năm 2025
        keys = ("tong_tai_san", "tai_san_ngan_han", "no_phai_tra", "von_chu_so_huu", "hang_ton_kho", "tien")
        for key in keys:
            vals = {}
            for q in (1, 2, 3, 4):
                try:
                    vals[q] = self.opn(key, Period(2025, q))
                except DataUnavailable:
                    pass
            base = vals.get(1)
            for q, v in vals.items():
                if base and q != 1:
                    self.check("CHEO", "số 1/1/2025 như nhau ở mọi báo cáo 2025", f"{key} Q1 vs Q{q}", base, v)
        # quý 1 + quý 2 = lũy kế 6 tháng; lũy kế 6 tháng + quý 3 = lũy kế 9 tháng (hai cột in riêng trong PDF, độc lập nhau)
        for key in ("doanh_thu_thuan", "loi_nhuan_gop", "loi_nhuan_sau_thue", "chi_phi_ban_hang", "chi_phi_qldn", "gia_von"):
            for y in (2025, 2026):
                try:
                    q1, q2 = self.flow(key, Period(y, 1), "quy"), self.flow(key, Period(y, 2), "quy")
                    self.check("CHEO", "quý 1 + quý 2 = lũy kế 6 tháng", f"{key} {y}", self.add((1, q1), (1, q2)), self.flow(key, Period(y, 2), "luy_ke"))
                except DataUnavailable:
                    pass
            try:
                c2, q3 = self.flow(key, Period(2025, 2), "luy_ke"), self.flow(key, Period(2025, 3), "quy")
                self.check("CHEO", "lũy kế 6 tháng + quý 3 = lũy kế 9 tháng", f"{key} 2025", self.add((1, c2), (1, q3)), self.flow(key, Period(2025, 3), "luy_ke"))
            except DataUnavailable:
                pass
        # INFO: cuối năm 2025 so với đầu năm 2026 (khác nhau do phân loại lại theo TT99, không phải lỗi)
        for key in ("tong_tai_san", "no_phai_tra", "von_chu_so_huu", "hang_ton_kho", "tai_san_ngan_han"):
            try:
                self.check("INFO", "cuối 2025 so với đầu 2026 (kỳ vọng lệch do TT99)", key, self.bal(key, Period(2025, 4)), self.opn(key, Period(2026, 1)))
            except DataUnavailable:
                pass

    def full_eq(self):
        """Áp toàn bộ ràng buộc EQ của pipeline (cả dòng con: 111+112=110...) lên DB cuối cùng; mã con vắng mặt coi là 0."""
        sys.path.insert(0, str(ROOT / "src" / "ingest"))
        import parse_statements as ps                                    # noqa: PLC0415 - chỉ cần khi kiểm định
        cells = self.f.cells
        keys = {(d, st, ky) for (d, st, _c, ky) in cells}
        from src.tools.facts import version_of                            # noqa: PLC0415
        for doc, st, ky in sorted(keys):
            for parent, kids in ps.EQ.get((version_of(doc), st), []):
                pc = cells.get((doc, st, parent, ky))
                present = [(k, sg) for k, sg in kids if (doc, st, k, ky) in cells]
                if pc is None or not present:
                    continue
                total = sum(sg * cells[(doc, st, k, ky)]["value"] for k, sg in present)
                for k, _ in present:
                    self.touched.add((doc, st, k, ky))
                self.touched.add((doc, st, parent, ky))
                st_all = [pc["status"]] + [cells[(doc, st, k, ky)]["status"] for k, _ in present]
                self.results.setdefault(("EQ", f"{st}: ràng buộc dòng tổng/dòng con của pipeline"), []).append(
                    (abs(pc["value"] - total) <= self.tol, f"{doc} {st} {parent}={'+'.join(k for k, _ in present)} [{ky}]", pc["value"] - total, sorted(set(st_all))))

    def sensitivity(self, trials: int = 300, seed: int = 5):
        """Chèn lỗi OCR giả (đổi một chữ số) vào từng ô được phủ rồi chạy lại: bộ kiểm có bắt được không?"""
        import random                                                     # noqa: PLC0415
        rng = random.Random(seed)
        pool = sorted(k for k in self.touched if k in self.f.cells)
        picked = rng.sample(pool, min(trials, len(pool)))
        caught = 0
        for k in picked:
            c = self.f.cells[k]
            orig = c["value"]
            s_ = str(abs(orig))
            i = rng.randrange(len(s_))
            d = str((int(s_[i]) + rng.randint(1, 9)) % 10)
            mutated = int(s_[:i] + d + s_[i + 1:]) * (1 if orig >= 0 else -1)
            if mutated == orig:
                continue
            c["value"] = mutated
            try:
                a = Audit(self.tol)
                a.f = self.f
                a.run()
                a.full_eq()
                if any(not ok for (g, _), rows in a.results.items() if g != "INFO" for ok, *_ in rows):
                    caught += 1
            finally:
                c["value"] = orig
        return caught, len(picked)

    def sample_uncovered(self, n: int, path: Path, seed: int = 11):
        """Mẫu ngẫu nhiên các ô OCR chưa được ràng buộc nào phủ: danh sách để người đối chiếu với PDF (đo tỷ lệ sai OCR thật)."""
        import csv, random                                                # noqa: PLC0415,E401
        rng = random.Random(seed)
        pool = [c for k, c in self.f.cells.items() if k not in self.touched and c["status"] == "OCR"]
        pick = rng.sample(pool, min(n, len(pool)))
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["doc", "statement", "code", "label", "ky", "value_in_db", "pdf_page", "pdf_value_checked", "match(Y/N)"])
            for c in sorted(pick, key=lambda c: (c["doc"], c["page"] or 0)):
                w.writerow([c["doc"], c["statement"], c["code"], c["label"], c["ky"], c["value"], c["page"], "", ""])
        return len(pool), len(pick)

    # ---- báo cáo
    def report(self, verbose: bool) -> int:
        hard_fail = 0
        print("===== KIỂM ĐỊNH DỮ LIỆU =====")
        groups = {}
        for (grp, name), rows in self.results.items():
            groups.setdefault(grp, []).append((name, rows))
        for grp in ("CDKT", "KQKD", "LCTT", "CHEO", "EQ", "INFO"):
            for name, rows in groups.get(grp, []):
                n, ok = len(rows), sum(r[0] for r in rows)
                tag = "" if grp == "INFO" else ("  OK" if ok == n else "  VỠ")
                print(f"[{grp}] {ok:3d}/{n:<3d}{tag}  {name}")
                bad = [r for r in rows if not r[0]]
                if grp != "INFO":
                    hard_fail += len(bad)
                for r in (bad if grp != "INFO" else (rows if verbose else [])) if (bad or verbose) else []:
                    print(f"           {r[1]:<28s} chênh lệch {r[2]:>20,d} | trạng thái ô: {', '.join(r[3])}")
        all_cells = len(self.f.cells)
        st = Counter(c["status"] for c in self.f.cells.values())
        print(f"\nTổng số ô số liệu: {all_cells}; theo trạng thái: {dict(st)}")
        print(f"Ô được ít nhất một đẳng thức chạm tới: {len(self.touched)}/{all_cells} = {len(self.touched) / all_cells:.0%}")
        by_st = Counter(self.f.cells[k]["status"] for k in self.touched if k in self.f.cells)
        for s, tot in st.items():
            print(f"   {s:<14s} phủ {by_st.get(s, 0)}/{tot} = {by_st.get(s, 0) / tot:.0%}")
        total = sum(len(r) for (g, _), r in self.results.items() if g != "INFO")
        print(f"\nĐẲNG THỨC CỨNG: {total - hard_fail}/{total} đạt, {hard_fail} vỡ (dung sai {self.tol} đồng)")
        return hard_fail


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tol", type=int, default=0, help="dung sai cho phép (đồng)")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--sensitivity", type=int, default=0, metavar="N", help="chèn N lỗi một chữ số giả để đo độ nhạy của bộ kiểm")
    ap.add_argument("--sample", type=int, default=0, metavar="N", help="xuất N ô OCR chưa được phủ ra eval/reports/ocr_sample.csv để đối chiếu PDF")
    a = ap.parse_args()
    au = Audit(a.tol)
    au.run()
    au.full_eq()
    code = 1 if au.report(a.verbose) else 0
    if a.sensitivity:
        caught, n = au.sensitivity(a.sensitivity)
        print(f"Độ nhạy: chèn lỗi một chữ số vào {n} ô được phủ -> bắt được {caught}/{n} = {caught / n:.1%}")
    if a.sample:
        out = ROOT / "eval" / "reports" / "ocr_sample.csv"
        out.parent.mkdir(exist_ok=True)
        pool, k = au.sample_uncovered(a.sample, out)
        print(f"Đã xuất {k} ô trong {pool} ô OCR chưa được phủ: {out} (điền cột pdf_value_checked / match rồi báo lại tỷ lệ sai)")
    sys.exit(code)


if __name__ == "__main__":
    main()
