"""Giai đoạn 1 - sửa số liệu OCR bằng ràng buộc kế toán + ràng buộc chéo kỳ.

Đầu vào : statements_long.csv (từ parse_statements)
Đầu ra  : statements_repaired.csv, repair_log.csv, review_queue.csv, repair_summary.txt

Ràng buộc tuyến tính  Σ sign*value = 0  gồm 3 loại:
  EQ    đẳng thức kế toán trong một báo cáo (270 = 100 + 200 ...)
  TWIN  cùng một số liệu xuất hiện ở hai báo cáo (số đầu năm, cùng kỳ năm trước)
  ADD   lũy kế = lũy kế kỳ trước + số quý này (KQKD)
Chỉ tự sửa khi (1) sửa làm giảm số ràng buộc vi phạm, (2) khác số OCR <= 2 ký tự,
(3) là ứng viên tốt nhất duy nhất. Còn lại đưa vào review_queue để soát tay.
Chạy: python -I repair_identities.py --parse-dir DIR --csv statements_long.csv --out OUT
"""
import argparse, sys
from pathlib import Path
import pandas as pd

def load_eq(parse_dir):
    sys.path.insert(0, str(parse_dir))
    import parse_statements as p
    return p.EQ, p.version_of, p.labels_for

def ed(a, b):
    dp = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        prev, dp[0] = dp[0], i
        for j in range(1, len(b) + 1):
            cur = dp[j]
            dp[j] = min(dp[j] + 1, dp[j - 1] + 1, prev + (a[i - 1] != b[j - 1]))
            prev = cur
    return dp[-1]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parse-dir", required=True)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--overrides", default=None, help="CSV: doc,statement,code,col,value_dung,nguon")
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    EQ, version_of, labels_for = load_eq(a.parse_dir)

    df = pd.read_csv(a.csv, dtype={"code": str}, encoding="utf-8-sig")
    ov = (pd.read_csv(a.overrides, dtype={"code": str}, encoding="utf-8-sig")
          if a.overrides and Path(a.overrides).exists() else pd.DataFrame())
    # Override cho ô parser bỏ sót hoàn toàn (unparsed_rows) -> thêm dòng mới, giá trị điền ở dưới.
    have = set(zip(df.doc, df.statement, df.code, df.col))
    meta = df.groupby("doc")[["quarter", "year"]].first()
    extra = [dict(doc=r.doc, quarter=meta.quarter[r.doc], year=meta.year[r.doc], statement=r.statement, code=r.code,
                  label=labels_for(version_of(int(meta.year[r.doc])), r.statement).get(r.code, r.code),
                  col=int(r.col), raw="OVERRIDE")
             for r in ov.itertuples() if (r.doc, r.statement, r.code, int(r.col)) not in have]
    if extra:
        df = pd.concat([df, pd.DataFrame(extra)], ignore_index=True)
    df["key"] = list(zip(df.doc, df.statement, df.code, df.col))
    V, OCR, LAB = {}, {}, {}
    for r in df.itertuples():
        v = None if pd.isna(r.value) else int(round(r.value))
        V[r.key] = v
        LAB[r.key] = str(r.label).strip().lower()
        OCR[r.key] = None if pd.isna(r.value_ocr) else int(round(r.value_ocr))
    PAGE = {r.key: r.page for r in df.itertuples()}
    # Giữ nhãn DERIVED từ parse_statements (số tính từ đẳng thức, không đọc từ PDF).
    status = {r.key: ("DERIVED" if r.status == "DERIVED" else "OCR") for r in df.itertuples()}
    note = {}
    locked = set()

    if not ov.empty:
        for r in ov.itertuples():
            k = (r.doc, r.statement, r.code, int(r.col))
            if k in V:
                V[k] = int(r.value_dung); status[k] = "MANUAL"; note[k] = str(r.nguon); locked.add(k)

    # ---------- dựng ràng buộc
    cons = []
    ncols = df.groupby(["doc", "statement"]).col.max().to_dict()
    year = df.groupby("doc").year.first().to_dict()
    for (doc, st), n in ncols.items():
        for parent, ch in EQ[(version_of(year[doc]), st)]:
            for c in range(1, n + 1):
                # BCTC không in dòng bằng 0 -> mã con vắng mặt coi là 0. Nếu dòng bị OCR bỏ sót
                # thật, ràng buộc sẽ vi phạm và vào review_queue thay vì bị bỏ qua.
                kids = [((doc, st, x, c), s) for x, s in ch if (doc, st, x, c) in V]
                if (doc, st, parent, c) in V and kids:
                    cons.append(("EQ", [((doc, st, parent, c), 1)] + [(k, -s) for k, s in kids]))
    def K(doc, st, code, c): return (doc, st, code, c)
    codes = {st: sorted({k[2] for k in V if k[1] == st}) for st in ("CDKT", "KQKD", "LCTT")}
    def twin(d1, c1, d2, c2, st):
        # Số so sánh trong BCTC 2026 (TT99) đã "phân loại lại" -> không ràng buộc chéo chuẩn mực.
        if d1 not in year or d2 not in year or version_of(year[d1]) != version_of(year[d2]):
            return
        for code in codes[st]:
            k1, k2 = K(d1, st, code, c1), K(d2, st, code, c2)
            if k1 in V and k2 in V and LAB[k1] == LAB[k2]: cons.append(("TWIN", [(k1, 1), (k2, -1)]))
    def add(dt, ct, dp, cp, dq, cq, st):
        for code in codes[st]:
            ks = [K(dt, st, code, ct), K(dp, st, code, cp), K(dq, st, code, cq)]
            if all(k in V for k in ks) and len({LAB[k] for k in ks}) == 1: cons.append(("ADD", [(ks[0], 1), (ks[1], -1), (ks[2], -1)]))
    docs = set(df.doc)
    for st in ("CDKT",):
        for d in ("q1-2025", "q2-2025", "q3-2025", "q4-2025"):
            if d != "q4-2025": twin(d, 2, "q4-2025", 2, st) if False else None
        for d1, d2 in (("q1-2025", "q2-2025"), ("q2-2025", "q3-2025"), ("q3-2025", "q4-2025")):
            twin(d1, 2, d2, 2, st)
        twin("q4-2025", 1, "q1-2026", 2, st); twin("q1-2026", 2, "q2-2026", 2, st)
    for st in ("KQKD", "LCTT"):
        twin("q1-2025", 1, "q1-2026", 2, st)
        twin("q2-2025", 1, "q2-2026", 2, st) if st == "LCTT" else None
    twin("q2-2025", 1, "q2-2026", 2, "KQKD"); twin("q2-2025", 3, "q2-2026", 4, "KQKD")
    twin("q2-2025", 1, "q2-2026", 2, "LCTT")
    add("q2-2025", 3, "q1-2025", 1, "q2-2025", 1, "KQKD"); add("q2-2025", 4, "q1-2025", 2, "q2-2025", 2, "KQKD")
    add("q3-2025", 3, "q2-2025", 3, "q3-2025", 1, "KQKD"); add("q3-2025", 4, "q2-2025", 4, "q3-2025", 2, "KQKD")
    add("q2-2026", 3, "q1-2026", 1, "q2-2026", 1, "KQKD"); add("q2-2026", 4, "q2-2025", 3, "q2-2025", 3, "KQKD") if False else None
    # (q1-2025 c1) = (q1 YTD) ; q2 c3 chính là lũy kế => dùng ADD ở trên
    by_key = {}
    for i, (_, t) in enumerate(cons):
        for k, _ in t: by_key.setdefault(k, []).append(i)

    def unknowns(t): return [k for k, _ in t if V[k] is None]
    def resid(i):
        t = cons[i][1]
        if unknowns(t): return None
        return sum(s * V[k] for k, s in t)
    def nfail(idx): return sum(1 for i in idx if (r := resid(i)) not in (None, 0))

    # Giá trị cùng chỉ tiêu ở các quý khác (cùng chuẩn mực) để loại kết quả sửa vô lý,
    # vd FILL 'Phải trả người bán' = -81.000 tỷ khi các quý khác ~ +4.000 tỷ.
    peers = {}
    for k, v in V.items():
        if v:
            peers.setdefault((version_of(year[k[0]]), k[1], k[2]), []).append(v)
    def plausible(k, nv):
        ps = sorted(peers.get((version_of(year[k[0]]), k[1], k[2]), []))
        if len(ps) < 3 or nv == 0:
            return True
        med = ps[len(ps) // 2]
        return (nv > 0) == (med > 0) and 0.1 <= abs(nv) / abs(med) <= 10

    log = []
    for it in range(400):
        cands = {}
        def viol(idx): return {i for i in idx if (r := resid(i)) not in (None, 0)}
        for i, (typ, t) in enumerate(cons):
            u = unknowns(t)
            if len(u) == 1 and u[0] not in locked:
                k = u[0]; s_ = dict(t)[k]
                nv = -sum(s2 * V[k2] for k2, s2 in t if k2 != k) * s_
                if plausible(k, nv):
                    cands[(k, nv)] = (0, -1, set(), typ, "FILL")
        for i, (typ, t) in enumerate(cons):
            r = resid(i)
            if r in (None, 0): continue
            for k, s_ in t:
                if k in locked or V[k] is None: continue
                nv = V[k] - r * s_
                d = ed(str(abs(nv)), str(abs(OCR[k] if OCR[k] is not None else V[k])))
                if d > 2 or not plausible(k, nv): continue
                vb = viol(by_key[k]); old = V[k]; V[k] = nv; va = viol(by_key[k]); V[k] = old
                if len(va) < len(vb):
                    cands[(k, nv)] = (len(va) - len(vb), d, vb - va, typ, "FIX")
        if not cands: break
        order = sorted(cands.items(), key=lambda x: (x[1][0], x[1][1]))
        pick = None
        for (k, nv), (dl, d, fx, typ, kind) in order:
            rivals = [v for (k2, nv2), v in cands.items() if (k2, nv2) != (k, nv) and v[2] & fx]
            if all((dl, d) < (v[0], v[1]) for v in rivals):
                pick = (dl, d, 0, k, nv, typ, kind); break
        if not pick: break
        top = [pick]
        _, d, _, k, new, typ, kind = top[0]
        log.append((it, *k, V[k], new, d, kind, typ))
        status[k] = "REPAIRED_" + ("FILL" if kind == "FILL" else "IDENTITY"); note[k] = f"{kind} via {typ}; ed={d}"
        V[k] = new

    # ---------- xuất
    df["value_clean"] = [V[k] for k in df.key]
    df["repair_status"] = [status[k] for k in df.key]
    df["repair_note"] = [note.get(k, "") for k in df.key]
    still = {i for i, (_, t) in enumerate(cons) if (r := resid(i)) not in (None, 0)}
    bad_keys = {}
    for i in still:
        for k, _ in cons[i][1]: bad_keys.setdefault(k, []).append(i)
    rq = []
    for i in sorted(still):
        typ, t = cons[i]
        rq.append({"loai": typ, "residual": resid(i),
                   "trang_pdf": ",".join(sorted({f"{k[0]}:tr{PAGE[k]}" for k, _ in t})),
                   "thanh_phan": "; ".join(f"{'+' if s>0 else '-'}{k[0]}/{k[1]}/{k[2]}/c{k[3]}={V[k]}" for k, s in t)})
    pd.DataFrame(rq, columns=["loai", "residual", "trang_pdf", "thanh_phan"]).to_csv(out / "review_queue.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(log, columns=["iter","doc","statement","code","col","old","new","edit_dist","kind","constraint"]).to_csv(out / "repair_log.csv", index=False, encoding="utf-8-sig")
    df.drop(columns=["key"]).to_csv(out / "statements_repaired.csv", index=False, encoding="utf-8-sig")
    n_eq = len(cons); n_fail0 = len(still)
    txt = [f"ràng buộc: {n_eq} (EQ={sum(c[0]=='EQ' for c in cons)}, TWIN={sum(c[0]=='TWIN' for c in cons)}, ADD={sum(c[0]=='ADD' for c in cons)})",
           f"số ô đã sửa: {len(log)}", f"ràng buộc còn vi phạm: {n_fail0}",
           f"ô còn thiếu giá trị: {sum(v is None for v in V.values())}"]
    (out / "repair_summary.txt").write_text("\n".join(txt), encoding="utf-8")
    print("\n".join(txt))
main()
