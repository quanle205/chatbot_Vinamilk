"""Bộ công cụ của agent = công cụ tra số/tính chỉ số (src.tools) + tìm kiếm văn bản (retriever, src.rag)."""
from __future__ import annotations

import json
from pathlib import Path

from ..tools.facts import Period
from ..tools.registry import TOOL_SPECS, call_tool

CHUNKS_PATH = Path(__file__).resolve().parents[2] / "data" / "processed" / "chunks.jsonl"
SNIPPET_CHARS = 1600

SEARCH_SPEC = {
    "name": "search_documents",
    "description": "Tìm đoạn văn bản trong BCTC hợp nhất của Vinamilk (thuyết minh, thông tin chung, và bảng số liệu) "
                   "theo nội dung câu hỏi. Dùng cho câu hỏi diễn giải hoặc chi tiết trong thuyết minh (cơ cấu chi phí, "
                   "các khoản vay, dự phòng, ...). Với số liệu chính của ba báo cáo hãy ưu tiên get_metric. "
                   "Văn bản thuyết minh là OCR nên chữ số có thể sai.",
    "input_schema": {"type": "object", "required": ["query"], "properties": {
        "query": {"type": "string", "description": "Câu cần tìm, viết đủ ý, nên kèm tên chỉ tiêu."},
        "period": {"type": "string", "description": "Giới hạn theo kỳ báo cáo, dạng 'Q1/2026' (tùy chọn)."},
        "k": {"type": "integer", "minimum": 1, "maximum": 8, "default": 5}}},
}


class Toolbox:
    """Gom công cụ và thực thi. Retriever nạp lười để khởi động nhanh và dễ thay khi kiểm thử."""

    def __init__(self, retriever=None):
        self._retriever = retriever

    @property
    def specs(self) -> list[dict]:
        return [*TOOL_SPECS, SEARCH_SPEC]

    @property
    def retriever(self):
        if self._retriever is None:
            from ..rag.retriever import HybridRetriever
            self._retriever = HybridRetriever.from_jsonl(CHUNKS_PATH)         # dựng trong ~6 giây, giữ trong bộ nhớ
        return self._retriever

    def run(self, name: str, args: dict) -> dict:
        if name == "search_documents":
            return self._search(args)
        return call_tool(name, args)

    def _search(self, args: dict) -> dict:
        try:
            query = str(args["query"]).strip()
            if not query:
                raise KeyError("query")
            k = max(1, min(int(args.get("k", 5)), 8))
            docs = {Period.parse(args["period"]).doc} if args.get("period") else None
        except KeyError as e:
            return {"ok": False, "error": f"Thiếu tham số {e}."}
        except (ValueError, TypeError) as e:
            return {"ok": False, "error": str(e)}
        hits = self.retriever.search(query, k=k, docs=docs)
        if not hits:
            return {"ok": False, "error": "Không tìm thấy đoạn văn bản phù hợp."}
        parts, sources = [], []
        for h in hits:
            c = h.chunk
            # Đoạn bảng số liệu giữ nguyên (cắt sẽ làm mất dòng chỉ tiêu cần tra); chỉ cắt văn bản OCR dài.
            long_text = c["kind"] == "van_ban" and len(c["text"]) > SNIPPET_CHARS
            body = c["text"][:SNIPPET_CHARS] + " …" if long_text else c["text"]
            parts.append(f"[{c['id']}] ({'bảng số liệu đã đối chiếu' if c['kind'] == 'bang_so_lieu' else 'văn bản OCR'})\n{body}")
            sources.append({"doc": c["doc"], "statement": c["heading"] or "TM", "page": c["page"], "code": "-",
                            "chunk": c["id"], "kind": c["kind"]})
        return {"ok": True, "text": "\n\n".join(parts), "sources": sources}


def result_for_model(result: dict) -> tuple[str, bool]:
    """Nội dung tool_result gửi cho Claude: chỉ phần `text` (đã chứa số, nguồn, lưu ý); lỗi đánh dấu is_error."""
    if result.get("ok"):
        return result.get("text") or json.dumps(result, ensure_ascii=False, default=str), False
    return "LỖI: " + str(result.get("error", "không rõ")), True
