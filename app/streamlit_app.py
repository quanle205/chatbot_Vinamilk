"""Giao diện chatbot BCTC hợp nhất Vinamilk. Chạy: streamlit run app/streamlit_app.py

Cấu hình qua biến môi trường (xem src/agent/agent.py): ANTHROPIC_VERTEX_PROJECT_ID, CLOUD_ML_REGION, VINAMILK_MODEL.
Giới hạn chi phí cho bản public: SESSION_LIMIT (lượt hỏi/phiên, mặc định 15) và DAILY_LIMIT (lượt/ngày toàn dịch vụ, mặc định 300).
"""
import datetime
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

st.set_page_config(page_title="Chatbot BCTC Vinamilk", page_icon="📊", layout="wide")


def load_secrets_into_env():
    """Streamlit Community Cloud: đọc cấu hình Google từ st.secrets (không có ADC như trên Cloud Run).

    Cần: ANTHROPIC_VERTEX_PROJECT_ID (+ CLOUD_ML_REGION tùy chọn) và bảng [gcp_service_account] chứa JSON khóa
    của tài khoản dịch vụ có vai trò Vertex AI User. Trên Cloud Run/máy local, không có secrets thì bỏ qua.
    """
    try:
        secrets = dict(st.secrets)
    except Exception:                                                        # noqa: BLE001 - không có file secrets
        return
    for k in ("ANTHROPIC_VERTEX_PROJECT_ID", "CLOUD_ML_REGION", "VINAMILK_MODEL", "SESSION_LIMIT", "DAILY_LIMIT"):
        if k in secrets and k not in os.environ:
            os.environ[k] = str(secrets[k])
    if "gcp_service_account" in secrets and "GOOGLE_APPLICATION_CREDENTIALS" not in os.environ:
        import json
        import tempfile
        path = Path(tempfile.gettempdir()) / "gcp_sa.json"
        path.write_text(json.dumps(dict(secrets["gcp_service_account"])), encoding="utf-8")
        os.chmod(path, 0o600)
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(path)


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
    return VinamilkAgent()


def render_meta(m: dict):
    if m.get("warnings") or m.get("unsupported"):
        if m.get("unsupported"):
            st.warning("Các số sau trong câu trả lời **không khớp** kết quả công cụ, hãy kiểm tra lại: "
                       + ", ".join(m["unsupported"]))
        for w in m.get("warnings", []):
            st.warning(w)
    if m.get("tool_calls"):
        with st.expander(f"Công cụ đã dùng và nguồn ({len(m['tool_calls'])} lần gọi)"):
            for t in m["tool_calls"]:
                st.markdown(f"**{t['name']}** `{t['input']}` — {'✅' if t['ok'] else '❌'}")
                st.caption(t["text"][:700])
            srcs = sorted({(s["doc"], s["statement"], s["page"]) for s in m.get("sources", [])})
            if srcs:
                st.markdown("**Nguồn:** " + "; ".join(f"{d} · {st_} · trang PDF {p}" for d, st_, p in srcs))


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
                meta = {"tool_calls": [{"name": t.name, "input": t.input, "ok": t.ok, "text": t.text} for t in r.tool_calls],
                        "sources": r.sources, "warnings": r.warnings, "unsupported": r.unsupported_numbers}
            except AgentConfigError as e:
                msg, meta = ("Tính năng hỏi đáp bằng AI chưa được bật trên bản này (chưa cấu hình kết nối Claude). "
                             f"Bạn vẫn có thể dùng tab *Tra số trực tiếp*.\n\n*Chi tiết cho quản trị viên: {e}*"), {}
            except Exception as e:                                           # noqa: BLE001 - không lộ stack trace ra giao diện
                msg, meta = f"Không gọi được mô hình ({type(e).__name__}). Vui lòng thử lại sau.", {}
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
    if st.button("Xóa hội thoại"):
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
