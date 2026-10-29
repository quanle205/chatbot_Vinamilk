"""Xuất ảnh các trang PDF được trích dẫn (ba báo cáo chính) để hiển thị làm dẫn chứng bên cạnh câu trả lời.

Chạy: python src/ingest/render_pages.py [--raw data/raw] [--db data/processed/financials.duckdb] [--out public/pages] [--dpi 110]
Mỗi trang được lưu thành public/pages/<doc>/<trang>.webp (ảnh xám, ~70 KB). Cần poppler (pdftoppm) như bước OCR; PDF gốc không đưa lên git
nên bước này chạy ở máy có data/raw, còn ảnh kết quả được đưa lên git để Vercel và Streamlit phục vụ.
"""
import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import duckdb
from PIL import Image


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--db", default="data/processed/financials.duckdb")
    ap.add_argument("--out", default="public/pages")
    ap.add_argument("--dpi", type=int, default=110)
    ap.add_argument("--quality", type=int, default=35)
    a = ap.parse_args()
    exe = shutil.which("pdftoppm")
    if not exe:
        sys.exit("Không tìm thấy pdftoppm (cài poppler).")
    con = duckdb.connect(a.db, read_only=True)
    pages = con.execute("select distinct doc, page from statements where page is not null order by 1, 2").fetchall()
    total = 0
    for doc, page in pages:
        page = int(page)
        pdf = Path(a.raw) / f"{doc}.pdf"
        out = Path(a.out) / doc / f"{page}.webp"
        if not pdf.exists() or out.exists():
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run([exe, "-jpeg", "-gray", "-r", str(a.dpi), "-f", str(page), "-l", str(page), str(pdf), str(Path(tmp) / "p")],
                           check=True)
            img = Image.open(next(Path(tmp).glob("p-*.jpg")))
            img.save(out, "WEBP", quality=a.quality, method=6)
        total += out.stat().st_size
    print(f"{len(pages)} trang, đã ghi {total / 2**20:.1f} MB vào {a.out}")


if __name__ == "__main__":
    main()
