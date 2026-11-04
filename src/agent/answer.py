"""Chỉnh câu trả lời cho đúng trọng tâm: bỏ phần giao diện đã hiển thị, giữ lại các nguồn thật sự được dùng.

Hai việc đều xác định (không gọi mô hình):
- `tidy_answer`: bỏ dòng "Nguồn: ..., trang N" mà mô hình hay viết ở cuối; thẻ Nguồn của giao diện đã có báo cáo, trang PDF và mã số.
- `used_sources`: chỉ giữ nguồn của lệnh gọi công cụ có số xuất hiện trong câu trả lời (câu hỏi định tính thì giữ tất cả).
"""
from __future__ import annotations

import re

from .guard import NUM_RE, matches_pool, numbers_in_result, parse_vn

# "(Nguồn: ..., trang PDF 11, mã 10)" hoặc "*(Báo cáo ..., trang 11)*" ở cuối dòng: nguồn viết kèm trong ngoặc
_TRAILING_CITE = re.compile(r"\s*[*_]*\((?:[^()\n]*\b(?:nguồn|báo cáo|bctc)\b[^()\n]*)?\btrang(?: PDF)?\s*\d[^()\n]*\)[*_]*[.\s]*$", re.I)
# Dòng chỉ là lời dẫn nguồn: "*Nguồn: Báo cáo ..., trang 11.*"
_CITE_LINE = re.compile(r"^[\s*_>(\-•]*nguồn\s*[:：][^\n]*\btrang\b[^\n]*$", re.I)


def tidy_answer(text: str) -> str:
    out = []
    for line in text.split("\n"):
        if _CITE_LINE.match(line):
            continue
        cleaned = _TRAILING_CITE.sub("", line) if "trang" in line.lower() else line
        if cleaned != line and line.rstrip("*_ ").endswith(".") and not cleaned.endswith((".", ":")):
            cleaned += "."                                                    # giữ dấu chấm câu của câu đã bỏ phần nguồn
        out.append(cleaned)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def used_sources(answer: str, tool_calls: list) -> list:
    """Nguồn (đã gộp, không trùng) của các công cụ có số khớp câu trả lời; không có số nào khớp thì giữ toàn bộ."""
    nums = [parse_vn(m.group(0)) for m in NUM_RE.finditer(answer)]
    kept, every = [], []
    for call in tool_calls:
        if not call.ok:
            continue
        sources = call.result.get("sources", [])
        every.extend(s for s in sources if s not in every)
        pool = numbers_in_result(call.result)
        if nums and any(matches_pool(n, dec, pool) for n, dec in nums):
            kept.extend(s for s in sources if s not in kept)
    return kept or every
