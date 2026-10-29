"""Giao diện chatbot BCTC hợp nhất Vinamilk. Chạy: streamlit run app/streamlit_app.py

Cấu hình qua biến môi trường hoặc Streamlit Secrets: GEMINI_API_KEY, GEMINI_MODEL (xem src/agent/agent.py).
Giới hạn lượt hỏi cho bản public: SESSION_LIMIT (lượt/phiên, mặc định 15) và DAILY_LIMIT (lượt/ngày toàn dịch vụ, mặc định 300).
"""
import datetime
import json
import logging
import os
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from src.agent import AgentConfigError, VinamilkAgent  # noqa: E402
from src.tools.metrics import METRICS  # noqa: E402
from src.tools.registry import analyst, call_tool  # noqa: E402

EXAMPLES = ["Doanh thu thuần quý 1/2026 là bao nhiêu và tăng bao nhiêu so với cùng kỳ?",
            "Biên lợi nhuận gộp quý 2/2026 so với quý 2/2025?",
            "Tổng tài sản và nợ phải trả tại 30/6/2026?",
            "ROE 6 tháng đầu năm 2026 là bao nhiêu?",
            "Dòng tiền từ hoạt động kinh doanh quý 4/2025?"]
OFFICIAL_REPORTS_URL = "https://www.vinamilk.com.vn/investor/reports/financial"
PAGES_DIR = Path(__file__).resolve().parents[1] / "public" / "pages"     # ảnh trang PDF dẫn chứng (src/ingest/render_pages.py)
OFFICIAL_PDF_URLS = {
    "q1-2026": "https://d8um25gjecm9v.cloudfront.net/cms/20260429_VNM_BCTC_DA_SOAT_XET_Q1_2026_HOP_NHAT_VN_d44326741a.pdf",
    "q2-2026": "https://d8um25gjecm9v.cloudfront.net/cms/20260730_VNM_BCTC_da_soat_xet_Q2_2026_Hop_nhat_76ef2e29c1.pdf",
}

st.set_page_config(page_title="Chatbot BCTC Vinamilk", page_icon="📊", layout="wide")


def load_secrets_into_env():
    """Streamlit Cloud: đưa cấu hình trong Settings -> Secrets vào biến môi trường (nếu có). Trên Render dùng sẵn biến môi trường."""
    try:
        secrets = dict(st.secrets)
    except Exception:                                                        # noqa: BLE001 - chạy local, không có file secrets
        return
    for k in ("GEMINI_API_KEY", "GEMINI_MODEL", "SESSION_LIMIT", "DAILY_LIMIT"):
        if k in secrets and k not in os.environ:
            os.environ[k] = str(secrets[k])


load_secrets_into_env()
SESSION_LIMIT = int(os.environ.get("SESSION_LIMIT", "15"))
DAILY_LIMIT = int(os.environ.get("DAILY_LIMIT", "300"))


@st.cache_resource
def daily_counter() -> dict:
    return {"day": None, "n": 0, "lock": threading.Lock()}


def take_daily_slot() -> bool:
    c = daily_counter()
    with c["lock"]:
        today = datetime.date.today().isoformat()
        if c["day"] != today:
            c["day"], c["n"] = today, 0
        if c["n"] >= DAILY_LIMIT:
            return False
        c["n"] += 1
        return True


@st.cache_resource
def get_agent() -> VinamilkAgent:
    return VinamilkAgent(intent_filter=True)


def friendly_error(e: Exception) -> str:
    """Ghi lỗi ở backend, chỉ trả hướng dẫn thân thiện ra giao diện."""
    code = getattr(e, "code", None)
    logging.getLogger("chatbot").exception("Lỗi gọi Gemini")
    if isinstance(code, int) and code >= 500:
        return "Trợ lý đang bận hoặc gặp sự cố tạm thời. Bạn thử lại sau ít phút nhé."
    if code == 429:
        return "Trợ lý đang tạm hết lượt sử dụng. Bạn thử lại sau hoặc dùng Tra số trực tiếp nhé."
    if code in (400, 401, 403):
        return "Trợ lý hiện chưa thể xử lý yêu cầu. Bạn thử lại sau nhé."
    if code == 404:
        return "Trợ lý hiện chưa sẵn sàng. Bạn thử lại sau hoặc dùng Tra số trực tiếp nhé."
    return "Đã có sự cố khi xử lý yêu cầu. Bạn thử lại sau nhé."


@st.cache_data(show_spinner=False)
def page_with_highlights(path: str, boxes: tuple):
    """Ảnh trang PDF với khung đỏ quanh các dòng được trích (boxes: tỷ lệ x, y, rộng, cao)."""
    from PIL import Image, ImageDraw
    img = Image.open(path).convert("RGB")
    over = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    W, H = img.size
    for x, y, w, h in boxes:
        rect = [x * W, y * H, (x + w) * W, (y + h) * H]
        d.rectangle(rect, fill=(225, 29, 72, 35), outline=(225, 29, 72, 255), width=3)
    return Image.alpha_composite(img.convert("RGBA"), over).convert("RGB")


def render_meta(m: dict):
    if m.get("warnings") or m.get("unsupported"):
        if m.get("unsupported"):
            st.warning("Các số sau trong câu trả lời **không khớp** kết quả công cụ, hãy kiểm tra lại: "
                       + ", ".join(m["unsupported"]))
        for w in m.get("warnings", []):
            st.warning(w)
    source_map = {}
    for source in m.get("sources", []):
        citation = (source.get("doc", "Tài liệu"), source.get("statement", ""), source.get("page"))
        source_map[citation] = source.get("url") or source.get("link") or source.get("pdf_url")
    if source_map:
        st.markdown("**Nguồn tham khảo**")
        for (doc, statement, page), url in sorted(
            source_map.items(),
            key=lambda item: (item[0][0], item[0][1], item[0][2] is None, item[0][2] or 0),
        ):
            citation = f"{doc} · {statement} · trang PDF {page if page is not None else 'không rõ'}"
            url = url or OFFICIAL_PDF_URLS.get(doc) or OFFICIAL_REPORTS_URL
            link_label = "Mở PDF" if doc in OFFICIAL_PDF_URLS else "Mở trang báo cáo Vinamilk"
            st.markdown(f"- {citation} · [{link_label}]({url})")
        shown = set()
        for source in m.get("sources", []):
            doc, page = source.get("doc"), source.get("page")
            try:
                img = PAGES_DIR / str(doc) / f"{int(page)}.webp"
            except (TypeError, ValueError):
                continue
            if img.exists() and img not in shown:
                shown.add(img)
                rows = [f"mã {x['code']}" for x in m["sources"] if x.get("doc") == doc and x.get("page") == page and x.get("code") not in (None, "-")]
                with st.expander(f"Xem trang PDF dẫn chứng: {doc} · trang {int(page)}" + (f" ({', '.join(rows)})" if rows else "")):
                    codes = [x.get("code") for x in m["sources"] if x.get("doc") == doc and x.get("page") == page and x.get("code") not in (None, "-")]
                    row_boxes = json.loads(img.with_suffix(".json").read_text(encoding="utf-8")) if img.with_suffix(".json").exists() else {}
                    boxes = tuple(tuple(row_boxes[str(c)]) for c in dict.fromkeys(codes) if str(c) in row_boxes)
                    st.image(page_with_highlights(str(img), boxes) if boxes else str(img), use_container_width=True)


def chat_tab():
    st.session_state.setdefault("ui", [])
    st.session_state.setdefault("api", [])
    st.session_state.setdefault("asked", 0)
    for turn in st.session_state.ui:
        with st.chat_message(turn["role"]):
            st.markdown(turn["content"])
            if turn["role"] == "assistant":
                render_meta(turn["meta"])

    question = st.chat_input("Hỏi về số liệu, tỷ số hoặc nội dung thuyết minh của BCTC Vinamilk…")
    question = question or st.session_state.pop("pending_example", None)
    if not question:
        return
    with st.chat_message("user"):
        st.markdown(question)
    st.session_state.ui.append({"role": "user", "content": question})
    with st.chat_message("assistant"):
        if st.session_state.asked >= SESSION_LIMIT:
            msg = f"Bạn đã dùng hết {SESSION_LIMIT} lượt hỏi của phiên này. Hãy tải lại trang để bắt đầu phiên mới."
            meta = {}
        elif not take_daily_slot():
            msg, meta = "Dịch vụ đã đạt giới hạn lượt hỏi trong ngày. Bạn vẫn có thể dùng tab *Tra số trực tiếp*.", {}
        else:
            try:
                with st.spinner("Đang tra cứu số liệu…"):
                    r = get_agent().ask(question, st.session_state.api)
                st.session_state.asked += 1
                msg = r.answer
                meta = {"sources": r.sources, "warnings": r.warnings,
                    "unsupported": r.unsupported_numbers}
            except AgentConfigError as e:
                logging.getLogger("chatbot").warning("Trợ lý AI chưa sẵn sàng: %s", e)
                msg, meta = "Trợ lý chưa sẵn sàng. Bạn vẫn có thể dùng Tra số trực tiếp.", {}
            except Exception as e:                                           # noqa: BLE001 - không lộ stack trace ra giao diện
                msg, meta = friendly_error(e), {}
        st.markdown(msg)
        render_meta(meta)
    st.session_state.ui.append({"role": "assistant", "content": msg, "meta": meta})


def lookup_tab():
    st.caption("Tra trực tiếp từ số liệu đã đối chiếu với PDF, không qua mô hình ngôn ngữ.")
    a = analyst()
    periods = [str(p) for p in a.f.periods()]
    c1, c2, c3 = st.columns(3)
    kind = c1.radio("Loại", ["Chỉ tiêu", "Tỷ số", "Tăng trưởng"], horizontal=True)
    period = c2.selectbox("Kỳ", periods, index=len(periods) - 1)
    basis = c3.radio("Cơ sở (chỉ tiêu phát sinh)", ["quy", "luy_ke"], horizontal=True,
                     format_func=lambda x: {"quy": "Riêng quý", "luy_ke": "Lũy kế từ đầu năm"}[x])
    if kind == "Tỷ số":
        key = st.selectbox("Tỷ số", list(a.ratios), format_func=lambda k: a.ratios[k].name)
        res = call_tool("get_ratio", {"ratio": key, "period": period, "basis": basis})
    else:
        keys = [m.key for m in METRICS]
        key = st.selectbox("Chỉ tiêu", keys, index=keys.index("doanh_thu_thuan"),
                           format_func=lambda k: next(m.name for m in METRICS if m.key == k))
        if kind == "Chỉ tiêu":
            res = call_tool("get_metric", {"metric": key, "period": period, "basis": basis})
        else:
            g = st.radio("So với", ["yoy", "qoq", "ytd"], horizontal=True,
                         format_func=lambda x: {"yoy": "Cùng kỳ năm trước", "qoq": "Quý trước", "ytd": "Đầu năm (số dư)"}[x])
            res = call_tool("get_growth", {"metric": key, "period": period, "kind": g, "basis": basis})
    (st.success if res["ok"] else st.error)(res.get("text") or res.get("error"))
    if kind == "Chỉ tiêu":
        s = call_tool("get_series", {"metric": key, "basis": basis})
        if s["ok"]:
            # Nhãn "2025-Q1" để Streamlit xếp trục theo thời gian (nhãn "Q1/2025" bị xếp theo chữ cái: Q1/2025, Q1/2026, Q2/2025...)
            def label(period: str) -> str:
                q, y = period.split("/")
                return f"{y}-{q}"
            st.line_chart({label(r["period"]): r["value"] / 1e9 for r in s["rows"]}, y_label="tỷ đồng")


with st.sidebar:
    st.header("Chatbot BCTC Vinamilk")
    st.caption("BCTC hợp nhất quý 1/2025 – quý 2/2026. Số liệu được đối chiếu với PDF; câu trả lời kèm nguồn.")
    st.markdown("**Thử hỏi:**")
    for q in EXAMPLES:
        if st.button(q, use_container_width=True):
            st.session_state["pending_example"] = q
    if st.button("Cuộc trò chuyện mới", key="new_conversation"):
        for k in ("ui", "api", "asked"):
            st.session_state.pop(k, None)
        st.rerun()
    st.divider()
    st.caption("Đây là công cụ tra cứu số liệu, không phải tư vấn đầu tư và không dự báo. "
               "Đối chiếu số quan trọng với báo cáo gốc.")

tab_chat, tab_lookup = st.tabs(["Hỏi đáp", "Tra số trực tiếp"])
with tab_chat:
    chat_tab()
with tab_lookup:
    lookup_tab()
