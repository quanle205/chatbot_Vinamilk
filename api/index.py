"""API cho bản triển khai Vercel (hàm serverless). Giao diện là trang tĩnh public/index.html gọi các đường dẫn /api/*.

Hàm serverless không giữ trạng thái giữa các lần gọi, nên lịch sử hội thoại do trình duyệt gửi lên mỗi lượt (chỉ dạng văn bản hỏi-đáp).
Biến môi trường: GEMINI_API_KEY (bắt buộc cho /api/ask), GEMINI_MODEL, SESSION_LIMIT_PER_MINUTE, MAX_HISTORY_TURNS.
"""
import os
import sys
import time
from collections import defaultdict, deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import HTMLResponse  # noqa: E402
from google.genai import types  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from src.agent import AgentConfigError, VinamilkAgent  # noqa: E402
from src.tools.registry import call_tool  # noqa: E402

OFFICIAL_REPORTS_URL = "https://www.vinamilk.com.vn/investor/reports/financial"
OFFICIAL_PDF_URLS = {
    "q1-2026": "https://d8um25gjecm9v.cloudfront.net/cms/20260429_VNM_BCTC_DA_SOAT_XET_Q1_2026_HOP_NHAT_VN_d44326741a.pdf",
    "q2-2026": "https://d8um25gjecm9v.cloudfront.net/cms/20260730_VNM_BCTC_da_soat_xet_Q2_2026_Hop_nhat_76ef2e29c1.pdf",
}
RATE_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "6"))
MAX_HISTORY_TURNS = int(os.environ.get("MAX_HISTORY_TURNS", "6"))
MAX_QUESTION_CHARS = 500

app = FastAPI(title="Chatbot BCTC Vinamilk")
_agent: VinamilkAgent | None = None
_hits: dict[str, deque] = defaultdict(deque)          # IP -> thời điểm các lần hỏi gần đây (chỉ có tác dụng trong một phiên bản hàm đang chạy)


class Turn(BaseModel):
    role: str = Field(pattern="^(user|model)$")
    text: str = Field(max_length=4000)


class AskBody(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    history: list[Turn] = []


class LookupBody(BaseModel):
    metric: str = Field(min_length=1, max_length=100)
    period: str = Field(min_length=1, max_length=30)
    basis: str = Field(default="quy", pattern="^(quy|luy_ke)$")


def get_agent() -> VinamilkAgent:
    global _agent
    if _agent is None:
        _agent = VinamilkAgent(deadline_s=float(os.environ.get("ASK_DEADLINE_S", "45")))
    return _agent


def _rate_limit(request: Request) -> None:
    ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "?")).split(",")[0].strip()
    q, now = _hits[ip], time.time()
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= RATE_PER_MINUTE:
        raise HTTPException(429, "Bạn hỏi hơi nhanh, vui lòng thử lại sau ít phút.")
    q.append(now)


def _source_links(sources: list) -> list[dict]:
    seen, out = set(), []
    for s in sources:
        key = (s.get("doc", ""), s.get("statement", ""), s.get("page"))
        if key in seen:
            continue
        seen.add(key)
        doc = key[0]
        out.append({"doc": doc, "statement": key[1], "page": key[2],
                    "url": OFFICIAL_PDF_URLS.get(doc, OFFICIAL_REPORTS_URL), "is_pdf": doc in OFFICIAL_PDF_URLS})
    return out


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
            "unsupported_numbers": r.unsupported_numbers}


@app.get("/api/diag")
def diag():
    """Thử gọi từng mô hình Gemini một lần (giới hạn thời gian) để biết mô hình nào trả lời được trên máy chủ này. Không trả khóa."""
    from src.agent.agent import make_client
    try:
        client = make_client()
    except AgentConfigError:
        return {"ok": False, "error": "chưa đặt GEMINI_API_KEY"}
    out = []
    for model in get_agent().models:
        t = time.time()
        try:
            r = client.models.generate_content(model=model, contents="Trả lời đúng một từ: xin chào")
            out.append({"model": model, "ok": True, "seconds": round(time.time() - t, 1), "reply": (r.text or "")[:40]})
        except Exception as e:                                               # noqa: BLE001
            out.append({"model": model, "ok": False, "seconds": round(time.time() - t, 1), "code": getattr(e, "code", None),
                        "error": type(e).__name__, "message": str(getattr(e, "message", "") or e)[:160]})
    return {"ok": any(o["ok"] for o in out), "models": out}


@app.post("/api/lookup")
def lookup(body: LookupBody, request: Request):
    _rate_limit(request)
    res = call_tool("get_metric", {"metric": body.metric, "period": body.period, "basis": body.basis})
    return {"ok": res.get("ok", False), "text": res.get("text", "")}


@app.get("/", response_class=HTMLResponse)
def index():
    page = ROOT / "public" / "index.html"
    return page.read_text(encoding="utf-8") if page.exists() else "<h1>Chatbot BCTC Vinamilk</h1>"
