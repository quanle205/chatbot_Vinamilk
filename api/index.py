"""API cho bản triển khai Vercel (hàm serverless). Giao diện là trang tĩnh public/ gọi các đường dẫn /api/*.

Hàm serverless không giữ trạng thái giữa các lần gọi, nên lịch sử hội thoại do trình duyệt gửi lên mỗi lượt (chỉ dạng văn bản hỏi-đáp).
Đường dẫn:  /api/ask (hỏi đáp, qua Gemini)  /api/lookup  /api/chart  /api/notes  /api/stats (đọc thẳng dữ liệu, không qua mô hình)
            /api/feedback  /api/health
Biến môi trường: GEMINI_API_KEY (bắt buộc cho /api/ask), GEMINI_MODEL, MAX_HISTORY_TURNS, ASK_DEADLINE_S;
giới hạn mỗi phút: RATE_LIMIT_PER_MINUTE (hỏi đáp), BROWSE_LIMIT_PER_MINUTE (tra cứu/biểu đồ/thuyết minh), FEEDBACK_LIMIT_PER_MINUTE;
phản hồi: FEEDBACK_WEBHOOK_URL, FEEDBACK_WEBHOOK_TOKEN (xem src/feedback.py).
"""
import mimetypes
import os
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import HTMLResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from google.genai import types  # noqa: E402

from src.agent import AgentConfigError, VinamilkAgent  # noqa: E402
from src.agent.charts import build_charts  # noqa: E402
from src.agent.toolbox import Toolbox  # noqa: E402
from src.feedback import get_store, make_record  # noqa: E402
from src.notes import search_notes  # noqa: E402
from src.stats import coverage  # noqa: E402
from src.tools.registry import analyst, call_tool  # noqa: E402
from src.web.ratelimit import RateLimiter  # noqa: E402
from src.web.schemas import AskBody, ChartBody, FeedbackBody, LookupBody, NotesBody  # noqa: E402
from src.web.sources import OFFICIAL_PDF_URLS, OFFICIAL_REPORTS_URL, collect_notes, source_links  # noqa: E402

mimetypes.add_type("application/javascript", ".js")       # Windows đôi khi gán .js là text/plain, làm trình duyệt từ chối nạp module
mimetypes.add_type("text/css", ".css")

MAX_HISTORY_TURNS = int(os.environ.get("MAX_HISTORY_TURNS", "6"))
ASK_LIMIT = RateLimiter(int(os.environ.get("RATE_LIMIT_PER_MINUTE", "6")), "Bạn hỏi hơi nhanh, vui lòng thử lại sau ít phút.")
BROWSE_LIMIT = RateLimiter(int(os.environ.get("BROWSE_LIMIT_PER_MINUTE", "30")), "Bạn thao tác hơi nhanh, vui lòng thử lại sau ít phút.")
FEEDBACK_LIMIT = RateLimiter(int(os.environ.get("FEEDBACK_LIMIT_PER_MINUTE", "20")), "Bạn gửi phản hồi hơi nhanh, vui lòng thử lại sau ít phút.")
LIMITERS = (ASK_LIMIT, BROWSE_LIMIT, FEEDBACK_LIMIT)

app = FastAPI(title="Chatbot BCTC Vinamilk")
_agent: VinamilkAgent | None = None
_toolbox: Toolbox | None = None


def get_toolbox() -> Toolbox:
    """Một bộ công cụ dùng chung cho hỏi đáp và mục Thuyết minh, để bộ truy xuất (dựng ~6 giây) chỉ nạp một lần mỗi tiến trình."""
    global _toolbox
    if _toolbox is None:
        _toolbox = Toolbox()
    return _toolbox


def get_agent() -> VinamilkAgent:
    global _agent
    if _agent is None:
        _agent = VinamilkAgent(toolbox=get_toolbox(), deadline_s=float(os.environ.get("ASK_DEADLINE_S", "45")), intent_filter=True)
    return _agent


@app.get("/api/health")
def health():
    try:
        periods = len(analyst().f.periods())                 # đọc thật DuckDB; lỗi thì giao diện báo đỏ
    except Exception:                                        # noqa: BLE001
        periods = None
    return {"ok": True, "gemini_key": bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")), "periods": periods}


@app.get("/api/stats")
def stats():
    data = coverage()
    periods = [{**p, "pdf_url": OFFICIAL_PDF_URLS.get(p["doc"])} for p in data["periods"]]
    return {**data, "periods": periods, "official_url": OFFICIAL_REPORTS_URL}


@app.post("/api/ask")
def ask(body: AskBody, request: Request):
    ASK_LIMIT.check(request)
    contents = [types.Content(role=t.role, parts=[types.Part(text=t.text)]) for t in body.history[-2 * MAX_HISTORY_TURNS:]]
    try:
        r = get_agent().ask(body.question, contents)
    except AgentConfigError:
        raise HTTPException(503, "Trợ lý chưa sẵn sàng. Bạn vẫn có thể dùng mục Tra cứu số liệu.")
    except Exception as e:                                                   # noqa: BLE001 - không lộ chi tiết kỹ thuật ra ngoài
        code = getattr(e, "code", None)
        if code == 429:
            raise HTTPException(429, "Trợ lý đang tạm hết lượt sử dụng. Bạn thử lại sau hoặc dùng mục Tra cứu số liệu.")
        raise HTTPException(502, "Trợ lý đang bận hoặc gặp sự cố tạm thời. Bạn thử lại sau ít phút nhé.")
    return {"answer": r.answer, "sources": source_links(r.sources), "notes": collect_notes(r.tool_calls), "warnings": r.warnings,
            "unsupported_numbers": r.unsupported_numbers, "charts": build_charts(r.tool_calls)}


@app.post("/api/lookup")
def lookup(body: LookupBody, request: Request):
    BROWSE_LIMIT.check(request)
    res = call_tool("get_metric", {"metric": body.metric, "period": body.period, "basis": body.basis})
    if res.get("ok"):
        return {"ok": True, "text": res["text"]}
    return {"ok": False, "text": _lookup_failure(body.metric, res.get("error", ""))}


def _lookup_failure(metric: str, error: str) -> str:
    """Lý do tra không ra, viết cho người dùng: chỉ tiêu lạ thì gợi ý các chỉ tiêu gần nhất (công cụ search_metrics) thay vì nhắc tên công cụ."""
    if not error.startswith("Không có chỉ tiêu"):
        return error
    names = [m["name"] for m in call_tool("search_metrics", {"text": metric})["matches"]]
    return f"Không tìm thấy chỉ tiêu '{metric}'." + (f" Có thể bạn muốn tra: {', '.join(names)}." if names else " Hãy chọn một chỉ tiêu trong gợi ý của ô nhập.")


@app.post("/api/chart")
def chart(body: ChartBody, request: Request):
    """Biểu đồ/bảng cho mục Xu hướng & so sánh: gọi thẳng công cụ (không qua Gemini) rồi dựng bằng cùng build_charts như khi hỏi đáp."""
    BROWSE_LIMIT.check(request)
    if body.mode != "series" and not body.period:
        raise HTTPException(422, "Chế độ này cần chọn kỳ báo cáo.")
    calls = []
    for metric in (body.metrics if body.mode == "series" else body.metrics[:1]):
        if body.mode == "series":
            name, args = "get_series", {"metric": metric, "basis": body.basis}
        elif body.mode == "growth":
            name, args = "get_growth", {"metric": metric, "period": body.period, "kind": body.kind, "basis": body.basis}
        else:
            name, args = "explain_change", {"metric": metric, "period": body.period, "base": body.kind, "basis": body.basis}
        res = call_tool(name, args)
        if not res.get("ok"):
            raise HTTPException(400, res.get("error") or "Không dựng được biểu đồ cho lựa chọn này.")
        calls.append(SimpleNamespace(name=name, ok=True, result=res))
    return {"charts": build_charts(calls)}


@app.post("/api/notes")
def notes(body: NotesBody, request: Request):
    """Tìm đoạn thuyết minh theo nội dung, kèm nguồn (trang PDF, ảnh trang) cho mục Thuyết minh & nguồn."""
    BROWSE_LIMIT.check(request)
    try:
        hits = search_notes(get_toolbox().retriever, body.query, body.period, body.include_tables, body.k)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"results": [{**h, "source": source_links([{"doc": h["doc"], "statement": h["heading"], "page": h["page"], "code": "-"}])[0]} for h in hits]}


@app.post("/api/feedback")
def feedback(body: FeedbackBody, request: Request):
    FEEDBACK_LIMIT.check(request)
    try:
        get_store().save(make_record(body.question, body.answer, body.label, body.timestamp))
    except Exception as e:                                                   # noqa: BLE001 - chỉ ghi loại lỗi, không ghi nội dung/URL/khóa
        print(f"FEEDBACK_ERROR {type(e).__name__}", file=sys.stderr, flush=True)
        raise HTTPException(502, "Chưa lưu được phản hồi, bạn thử lại sau nhé.")
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def index():
    page = ROOT / "public" / "index.html"
    return page.read_text(encoding="utf-8") if page.exists() else "<h1>Chatbot BCTC Vinamilk</h1>"


# Tệp tĩnh (css, js, ảnh trang PDF). Trên Vercel thư mục public/ do CDN phục vụ; mount này để chạy cục bộ giống bản triển khai.
# Đặt cuối cùng để các đường dẫn /api/* và / ở trên được ưu tiên.
app.mount("/", StaticFiles(directory=ROOT / "public", check_dir=False), name="static")
