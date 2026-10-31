"""API cho bản triển khai Vercel (hàm serverless). Giao diện là trang tĩnh public/index.html gọi các đường dẫn /api/*.

Hàm serverless không giữ trạng thái giữa các lần gọi, nên lịch sử hội thoại do trình duyệt gửi lên mỗi lượt (chỉ dạng văn bản hỏi-đáp).
Biến môi trường: GEMINI_API_KEY (bắt buộc cho /api/ask), GEMINI_MODEL, SESSION_LIMIT_PER_MINUTE, MAX_HISTORY_TURNS.
"""
import json
import os
import sys
import time
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import HTMLResponse  # noqa: E402
from google.genai import types  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from src.agent import AgentConfigError, VinamilkAgent  # noqa: E402
from src.agent.charts import build_charts  # noqa: E402
from src.feedback import get_store, make_record  # noqa: E402
from src.tools.registry import call_tool  # noqa: E402

OFFICIAL_REPORTS_URL = "https://www.vinamilk.com.vn/investor/reports/financial"
OFFICIAL_PDF_URLS = {
    "q1-2026": "https://d8um25gjecm9v.cloudfront.net/cms/20260429_VNM_BCTC_DA_SOAT_XET_Q1_2026_HOP_NHAT_VN_d44326741a.pdf",
    "q2-2026": "https://d8um25gjecm9v.cloudfront.net/cms/20260730_VNM_BCTC_da_soat_xet_Q2_2026_Hop_nhat_76ef2e29c1.pdf",
}
RATE_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "6"))
FEEDBACK_PER_MINUTE = int(os.environ.get("FEEDBACK_LIMIT_PER_MINUTE", "20"))
MAX_HISTORY_TURNS = int(os.environ.get("MAX_HISTORY_TURNS", "6"))
MAX_QUESTION_CHARS = 500

app = FastAPI(title="Chatbot BCTC Vinamilk")
_agent: VinamilkAgent | None = None
_hits: dict[str, deque] = defaultdict(deque)          # IP -> thời điểm các lần hỏi gần đây (chỉ có tác dụng trong một phiên bản hàm đang chạy)
_fb_hits: dict[str, deque] = defaultdict(deque)       # như trên, nhưng riêng cho phản hồi để không trừ vào lượt hỏi


class Turn(BaseModel):
    role: str = Field(pattern="^(user|model)$")
    text: str = Field(max_length=4000)


class AskBody(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    history: list[Turn] = []


class FeedbackBody(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    answer: str = Field(min_length=1, max_length=8000)
    label: str = Field(pattern="^(up|down)$")
    timestamp: datetime | None = None                  # thời điểm phía trình duyệt; bỏ trống thì dùng giờ máy chủ


class LookupBody(BaseModel):
    metric: str = Field(min_length=1, max_length=100)
    period: str = Field(min_length=1, max_length=30)
    basis: str = Field(default="quy", pattern="^(quy|luy_ke)$")


def get_agent() -> VinamilkAgent:
    global _agent
    if _agent is None:
        _agent = VinamilkAgent(deadline_s=float(os.environ.get("ASK_DEADLINE_S", "45")), intent_filter=True)
    return _agent


def _rate_limit(request: Request, hits: dict | None = None, limit: int | None = None, msg: str = "Bạn hỏi hơi nhanh, vui lòng thử lại sau ít phút.") -> None:
    hits = _hits if hits is None else hits
    ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "?")).split(",")[0].strip()
    q, now = hits[ip], time.time()                       # IP chỉ dùng làm khóa đếm trong bộ nhớ, không ghi ra đâu cả
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= (RATE_PER_MINUTE if limit is None else limit):
        raise HTTPException(429, msg)
    q.append(now)


def _page_image(doc: str, page) -> str | None:
    """Đường dẫn ảnh trang PDF dẫn chứng (public/pages/<doc>/<trang>.webp) nếu có."""
    try:
        n = int(page)
    except (TypeError, ValueError):
        return None
    return f"/pages/{doc}/{n}.webp" if (ROOT / "public" / "pages" / doc / f"{n}.webp").exists() else None


def _row_boxes(doc: str, page) -> dict:
    """Vị trí các dòng số liệu trên ảnh trang ({mã: [x, y, rộng, cao]} theo tỷ lệ 0-1), do src/ingest/locate_rows.py tạo."""
    try:
        f = ROOT / "public" / "pages" / doc / f"{int(page)}.json"
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except (TypeError, ValueError, OSError):
        return {}


def _source_links(sources: list) -> list[dict]:
    """Gộp các dòng số liệu cùng trang thành một nguồn: tên báo cáo, trang, liên kết PDF chính thức, ảnh trang và các dòng được trích."""
    merged: dict[tuple, dict] = {}
    for s in sources:
        key = (s.get("doc", ""), s.get("statement", ""), s.get("page"))
        item = merged.setdefault(key, {"doc": key[0], "statement": key[1], "page": key[2], "rows": [],
                                       "url": OFFICIAL_PDF_URLS.get(key[0], OFFICIAL_REPORTS_URL), "is_pdf": key[0] in OFFICIAL_PDF_URLS,
                                       "image": _page_image(key[0], key[2]), "boxes": []})
        code, label = s.get("code"), s.get("label")
        if code and code != "-":
            row = f"mã {code}: {label}" if label else f"mã {code}"
            if row not in item["rows"]:
                item["rows"].append(row)
                box = _row_boxes(key[0], key[2]).get(str(code))
                if box:
                    item["boxes"].append(box)
    return list(merged.values())


@app.get("/api/health")
def health():
    return {"ok": True, "gemini_key": bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))}


@app.post("/api/ask")
def ask(body: AskBody, request: Request):
    _rate_limit(request)
    contents = [types.Content(role=t.role, parts=[types.Part(text=t.text)]) for t in body.history[-2 * MAX_HISTORY_TURNS:]]
    try:
        r = get_agent().ask(body.question, contents)
    except AgentConfigError:
        raise HTTPException(503, "Trợ lý chưa sẵn sàng. Bạn vẫn có thể dùng Tra số trực tiếp.")
    except Exception as e:                                                   # noqa: BLE001 - không lộ chi tiết kỹ thuật ra ngoài
        code = getattr(e, "code", None)
        if code == 429:
            raise HTTPException(429, "Trợ lý đang tạm hết lượt sử dụng. Bạn thử lại sau hoặc dùng Tra số trực tiếp.")
        raise HTTPException(502, "Trợ lý đang bận hoặc gặp sự cố tạm thời. Bạn thử lại sau ít phút nhé.")
    return {"answer": r.answer, "sources": _source_links(r.sources), "warnings": r.warnings,
            "unsupported_numbers": r.unsupported_numbers, "charts": build_charts(r.tool_calls)}


@app.post("/api/feedback")
def feedback(body: FeedbackBody, request: Request):
    _rate_limit(request, _fb_hits, FEEDBACK_PER_MINUTE, "Bạn gửi phản hồi hơi nhanh, vui lòng thử lại sau ít phút.")
    try:
        get_store().save(make_record(body.question, body.answer, body.label, body.timestamp))
    except Exception as e:                                                   # noqa: BLE001 - chỉ ghi loại lỗi, không ghi nội dung/URL/khóa
        print(f"FEEDBACK_ERROR {type(e).__name__}", file=sys.stderr, flush=True)
        raise HTTPException(502, "Chưa lưu được phản hồi, bạn thử lại sau nhé.")
    return {"ok": True}


@app.post("/api/lookup")
def lookup(body: LookupBody, request: Request):
    _rate_limit(request)
    res = call_tool("get_metric", {"metric": body.metric, "period": body.period, "basis": body.basis})
    return {"ok": res.get("ok", False), "text": res.get("text", "")}


@app.get("/", response_class=HTMLResponse)
def index():
    page = ROOT / "public" / "index.html"
    return page.read_text(encoding="utf-8") if page.exists() else "<h1>Chatbot BCTC Vinamilk</h1>"
