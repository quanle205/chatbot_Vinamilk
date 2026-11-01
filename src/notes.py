"""Tìm đoạn thuyết minh/bảng số liệu trong BCTC cho mục "Thuyết minh & nguồn": cùng bộ truy xuất với agent, nhưng trả dữ liệu có cấu trúc, không qua mô hình."""
from __future__ import annotations

from .tools.facts import Period

MAX_CHARS = 2500


def _body(text: str) -> str:
    """Bỏ dòng tiêu đề "[Q2/2026 · mục · trang N]" đầu đoạn (đã tách thành trường riêng)."""
    head, sep, rest = text.partition("\n")
    return rest if sep and head.startswith("[") else text


def search_notes(retriever, query: str, period: str | None = None, include_tables: bool = False, k: int = 8) -> list[dict]:
    """Trả tối đa k đoạn xếp theo độ liên quan. `period` sai dạng thì ném ValueError (thông báo tiếng Việt)."""
    docs = {Period.parse(period).doc} if period else None
    hits = retriever.search(query, k=k if include_tables else k * 3, docs=docs)      # lọc bỏ bảng số liệu sau khi xếp hạng nên lấy dư
    out = []
    for h in hits:
        c = h.chunk
        if not include_tables and c["kind"] != "van_ban":
            continue
        text = _body(c["text"]).strip()
        out.append({"id": c["id"], "doc": c["doc"], "period": f"{c['quarter']}/{c['year']}", "page": c["page"], "section": c["section"],
                    "heading": c["heading"], "kind": c["kind"], "text": text[:MAX_CHARS], "truncated": len(text) > MAX_CHARS})
        if len(out) == k:
            break
    return out
