"""Giai đoạn 1 - nạp kết quả OCR/parse/repair vào DuckDB.

Đầu vào : statements_repaired.csv, review_queue.csv, repair_log.csv (từ repair_identities)
          q*-*.jsonl (văn bản OCR theo trang, từ preprocess)
Đầu ra  : financials.duckdb gồm
  statements   mỗi dòng = 1 chỉ tiêu x 1 cột số liệu, value = value_clean, có cột ky (ý nghĩa cột)
  pages        văn bản OCR theo trang (dùng cho chunking/RAG)
  review_queue ràng buộc còn vi phạm, repair_log các ô đã tự sửa
  v_chi_tieu   view gọn để tra số: doc, statement, code, label, ky, value
Chạy: python src/ingest/build_db.py --interim data/interim --db data/processed/financials.duckdb
"""
import argparse, json
from pathlib import Path
import duckdb
import pandas as pd

# Ý nghĩa cột theo báo cáo và số cột (KQKD quý 2-4 có thêm 2 cột lũy kế).
KY = {
    "CDKT": ["cuoi_ky", "dau_nam"],
    "LCTT": ["luy_ke_nay", "luy_ke_cung_ky"],
    "KQKD": ["quy_nay", "quy_cung_ky", "luy_ke_nay", "luy_ke_cung_ky"],
}

def ky_of(statement, col, quarter, n_cols):
    names = KY.get(statement, [])
    if statement == "KQKD" and quarter == "Q4" and n_cols == 2:
        names = KY["LCTT"]  # BCTC quý 4 chỉ trình bày số cả năm
    return names[col - 1] if 0 < col <= len(names) else f"cot_{col}"

def read_csv(path):
    return pd.read_csv(path, dtype={"code": str}, encoding="utf-8-sig") if path.exists() and path.stat().st_size > 3 else pd.DataFrame()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interim", default="data/interim")
    ap.add_argument("--db", default="data/processed/financials.duckdb")
    a = ap.parse_args()
    interim, db = Path(a.interim), Path(a.db)
    db.parent.mkdir(parents=True, exist_ok=True)

    st = read_csv(interim / "statements_repaired.csv")
    if st.empty:
        raise SystemExit(f"Thiếu {interim / 'statements_repaired.csv'}; chạy repair_identities.py trước.")
    n_cols = st.groupby(["doc", "statement"]).col.transform("max")
    st["ky"] = [ky_of(s, int(c), q, int(n)) for s, c, q, n in zip(st.statement, st.col, st.quarter, n_cols)]
    st["value"] = st.value_clean
    pages = pd.DataFrame([json.loads(line) for f in sorted(interim.glob("q*-*.jsonl"))
                          for line in f.read_text(encoding="utf-8").splitlines() if line.strip()])
    rq, log = read_csv(interim / "review_queue.csv"), read_csv(interim / "repair_log.csv")

    if db.exists():
        db.unlink()
    con = duckdb.connect(str(db))
    for name, df in (("statements", st), ("pages", pages), ("review_queue", rq), ("repair_log", log)):
        if df.empty and not len(df.columns):
            continue
        con.register("df_tmp", df)
        con.execute(f"CREATE TABLE {name} AS SELECT * FROM df_tmp")
        con.unregister("df_tmp")
    con.execute("""CREATE VIEW v_chi_tieu AS
        SELECT doc, quarter, year, statement, code, label, ky, col, value, repair_status, page
        FROM statements ORDER BY year, quarter, statement, code, col""")
    for t in ("statements", "pages", "review_queue", "repair_log"):
        print(f"{t}: {con.execute(f'SELECT count(*) FROM {t}').fetchone()[0]} dòng")
    con.close()
    print(f"Xong -> {db}")

if __name__ == "__main__":
    main()
