"""Nguồn dẫn chứng cho giao diện: liên kết PDF chính thức, ảnh trang PDF và khung đánh dấu các dòng được trích."""
from __future__ import annotations

import json
from functools import lru_cache

from ..paths import CHUNKS_PATH, PAGES_DIR

EXCERPT_CHARS = 1500

OFFICIAL_REPORTS_URL = "https://www.vinamilk.com.vn/investor/reports/financial"
OFFICIAL_PDF_URLS = {
    "q1-2026": "https://d8um25gjecm9v.cloudfront.net/cms/20260429_VNM_BCTC_DA_SOAT_XET_Q1_2026_HOP_NHAT_VN_d44326741a.pdf",
    "q2-2026": "https://d8um25gjecm9v.cloudfront.net/cms/20260730_VNM_BCTC_da_soat_xet_Q2_2026_Hop_nhat_76ef2e29c1.pdf",
}


def pdf_url(doc: str, page) -> str:
    """PDF chính thức của kỳ (mở đúng trang nhờ #page=N); kỳ chưa có liên kết PDF thì trỏ về trang báo cáo tài chính của Vinamilk."""
    url = OFFICIAL_PDF_URLS.get(doc)
    if url is None:
        return OFFICIAL_REPORTS_URL
    return f"{url}#page={int(page)}" if isinstance(page, int) or str(page).isdigit() else url


def page_image(doc: str, page) -> str | None:
    """Đường dẫn ảnh trang PDF dẫn chứng (public/pages/<doc>/<trang>.webp) nếu có."""
    try:
        n = int(page)
    except (TypeError, ValueError):
        return None
    return f"/pages/{doc}/{n}.webp" if (PAGES_DIR / doc / f"{n}.webp").exists() else None


def row_boxes(doc: str, page) -> dict:
    """Vị trí các dòng số liệu trên ảnh trang ({mã: [x, y, rộng, cao]} theo tỷ lệ 0-1), do src/ingest/locate_rows.py tạo."""
    try:
        f = PAGES_DIR / doc / f"{int(page)}.json"
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except (TypeError, ValueError, OSError):
        return {}


@lru_cache(maxsize=1)
def _page_texts() -> dict:
    """{(doc, trang): [đoạn văn bản]} từ chunks.jsonl: bằng chứng bằng chữ cho trang chưa có ảnh PDF."""
    out: dict = {}
    try:
        with open(CHUNKS_PATH, encoding="utf-8") as f:
            for line in f:
                c = json.loads(line)
                if c.get("page") is not None:
                    out.setdefault((c["doc"], int(c["page"])), []).append(c.get("text", ""))
    except OSError:
        pass
    return out


def page_excerpt(doc: str, page) -> str | None:
    """Trích đoạn văn bản (OCR) của trang PDF được dẫn, dùng làm bằng chứng khi không có ảnh trang."""
    try:
        parts = _page_texts().get((doc, int(page)))
    except (TypeError, ValueError):
        return None
    if not parts:
        return None
    text = "\n\n".join(p.strip() for p in parts if p.strip())
    return text[:EXCERPT_CHARS].rstrip() + (" …" if len(text) > EXCERPT_CHARS else "")


def source_links(sources: list) -> list[dict]:
    """Gộp các dòng số liệu cùng trang thành một nguồn: tên báo cáo, trang, liên kết PDF chính thức, ảnh trang và các dòng được trích."""
    merged: dict[tuple, dict] = {}
    for s in sources:
        key = (s.get("doc", ""), s.get("statement", ""), s.get("page"))
        item = merged.setdefault(key, {"doc": key[0], "statement": key[1], "page": key[2], "rows": [],
                                       "url": pdf_url(key[0], key[2]), "is_pdf": key[0] in OFFICIAL_PDF_URLS,
                                       "image": page_image(key[0], key[2]), "boxes": []})
        if not item["image"] and "excerpt" not in item:
            item["excerpt"] = page_excerpt(key[0], key[2])            # mọi trang dẫn đều có bằng chứng: ảnh trang hoặc trích đoạn chữ
        code, label = s.get("code"), s.get("label")
        if code and code != "-":
            row = f"mã {code}: {label}" if label else f"mã {code}"
            if row not in item["rows"]:
                item["rows"].append(row)
                box = row_boxes(key[0], key[2]).get(str(code))
                if box:
                    item["boxes"].append(box)
    return list(merged.values())


def collect_notes(tool_calls: list) -> list[str]:
    """Các lưu ý của công cụ (số suy ra, số đã phân loại lại, số đã sửa OCR) trong một câu hỏi, bỏ trùng, giữ thứ tự."""
    notes: list[str] = []
    for tc in tool_calls:
        if tc.ok:
            notes += [n for n in tc.result.get("notes", []) if n not in notes]
    return notes
