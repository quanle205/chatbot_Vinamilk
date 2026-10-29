"""Xác định vị trí từng dòng số liệu (theo mã số) trên ảnh trang PDF để vẽ khung đánh dấu khi dẫn chứng.

Chạy: python src/ingest/locate_rows.py [--raw data/raw] [--db data/processed/financials.duckdb] [--out public/pages] [--dpi 150]
Với mỗi trang của ba báo cáo chính: OCR lấy hộp chữ (Tesseract), tìm các từ trùng mã số của dòng trong cột "Mã số" (cột được xác định
bằng vị trí trung vị của các mã tìm thấy), rồi ghi public/pages/<doc>/<trang>.json = {"<mã>": [x, y, rộng, cao]} theo tỷ lệ 0-1 của trang.
Dòng không tìm được thì bỏ qua (giao diện vẫn hiện ảnh trang, chỉ không có khung).
"""
import argparse
import json
import re
import shutil
import statistics
from collections import Counter
import subprocess
import sys
import tempfile
from pathlib import Path

import duckdb
import pytesseract
from PIL import Image


def render(exe: str, pdf: Path, page: int, dpi: int, tmp: Path) -> Image.Image:
    subprocess.run([exe, "-png", "-gray", "-r", str(dpi), "-f", str(page), "-l", str(page), str(pdf), str(tmp / "p")], check=True)
    return Image.open(next(tmp.glob("p-*.png"))).convert("L")


def locate(img: Image.Image, codes: list[str]) -> dict[str, list[float]]:
    W, H = img.size
    d = pytesseract.image_to_data(img, lang="eng", config="--oem 1 --psm 6", output_type=pytesseract.Output.DICT)
    words = []
    for i, t in enumerate(d["text"]):
        t = re.sub(r"[^\w]", "", t or "")
        if t and int(float(d["conf"][i])) >= 0:
            words.append((t, d["left"][i], d["top"][i], d["width"][i], d["height"][i]))
    hits = [w for w in words if w[0] in codes and len(w[0]) <= 3]
    if not hits:
        return {}
    bins = Counter(round((w[1] + w[3] / 2) / W / 0.02) for w in hits)           # cột "Mã số": nơi nhiều mã nhất nằm thẳng hàng dọc
    mode_x = bins.most_common(1)[0][0] * 0.02 * W                                # (công thức như "10 = 01 - 02" làm trung vị bị lệch nên dùng đỉnh)
    col = [w for w in hits if abs(w[1] + w[3] / 2 - mode_x) <= 0.03 * W]
    line_h = statistics.median(w[4] for w in col) if col else 0
    centers = sorted(w[2] + w[4] / 2 for w in col)                              # tâm dọc của các mã trong cột, từ trên xuống
    out = {}
    for code in codes:
        cand = [w for w in col if w[0] == code]
        if len(cand) != 1:                                                       # trùng hoặc không thấy: không đoán
            continue
        _, x, y, w_, h = cand[0]
        c = y + h / 2
        above = [v for v in centers if v < c - 1]
        below = [v for v in centers if v > c + 1]
        up = min((c - above[-1]) / 2, 2.0 * line_h) if above else 1.6 * line_h       # nửa khoảng tới dòng liền trên/dưới (giới hạn 2 dòng chữ)
        down = min((below[0] - c) / 2, 2.0 * line_h) if below else 1.6 * line_h
        top, bottom = max(c - up - 0.15 * h, 0), min(c + down + 0.15 * h, H)
        out[code] = [0.06, round(top / H, 4), 0.88, round((bottom - top) / H, 4)]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--db", default="data/processed/financials.duckdb")
    ap.add_argument("--out", default="public/pages")
    ap.add_argument("--dpi", type=int, default=150)
    a = ap.parse_args()
    exe = shutil.which("pdftoppm")
    if not exe:
        sys.exit("Không tìm thấy pdftoppm (cài poppler).")
    con = duckdb.connect(a.db, read_only=True)
    rows = con.execute("select doc, page, code from statements where page is not null and code is not null group by 1, 2, 3 order by 1, 2, 3").fetchall()
    by_page: dict[tuple, list[str]] = {}
    for doc, page, code in rows:
        by_page.setdefault((doc, int(page)), []).append(str(code))
    found = total = 0
    for (doc, page), codes in by_page.items():
        pdf = Path(a.raw) / f"{doc}.pdf"
        if not pdf.exists():
            continue
        with tempfile.TemporaryDirectory() as tmp:
            img = render(exe, pdf, page, a.dpi, Path(tmp))
        boxes = locate(img, codes)
        found += len(boxes)
        total += len(codes)
        dest = Path(a.out) / doc / f"{page}.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(boxes, ensure_ascii=False), encoding="utf-8")
        print(f"{doc} trang {page}: {len(boxes)}/{len(codes)} dòng")
    print(f"Tổng: tìm được {found}/{total} dòng ({found / max(total, 1):.0%})")


if __name__ == "__main__":
    main()
