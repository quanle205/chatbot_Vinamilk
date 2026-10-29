"""Agent hỏi đáp BCTC: Gemini function-calling (vòng lặp thủ công) gọi công cụ tra số + retriever.

Cấu hình qua biến môi trường (Render: Environment; Streamlit Cloud: Secrets, xem app/streamlit_app.py):
  GEMINI_API_KEY   khóa tạo miễn phí tại https://aistudio.google.com/apikey   [bắt buộc]
  GEMINI_MODEL     mặc định gemini-3.8-flash
  GEMINI_FALLBACK_MODELS  danh sách mô hình dự phòng, cách nhau dấu phẩy, dùng khi mô hình chính quá tải/hết hạn mức
Client có thể tiêm vào (`VinamilkAgent(client=...)`) để kiểm thử mà không gọi mạng.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

from google import genai
from google.genai import types

from .guard import find_unsupported_numbers
from .prompts import SYSTEM_PROMPT
from .toolbox import Toolbox, result_for_model

DEFAULT_MODEL = "gemini-3.8-flash"
REFUSAL_TEXT = "Mình không thể trả lời câu hỏi này. Bạn có thể hỏi về số liệu và chỉ số trong BCTC hợp nhất của Vinamilk."
TRANSIENT_CODES = {500, 503, 504}
RETRY_CODES = {500, 503}                    # 504 = mô hình đã chờ quá lâu: thử lại chỉ tốn thêm thời gian, chuyển mô hình luôn
COOLDOWN_S = 300                            # mô hình vừa hỏng/quá tải bị bỏ qua trong khoảng này để các câu sau không phải chờ lại
FALLTHROUGH_CODES = TRANSIENT_CODES | {429, 403, 404}       # đổi sang mô hình dự phòng; 400 (yêu cầu sai) thì không
DEFAULT_FALLBACKS = "gemini-3.6-flash,gemini-3.5-flash-lite"
BLOCKED = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION", "IMAGE_SAFETY"}
SCHEMA_KEYS = {"type", "required", "enum", "description", "minimum", "maximum"}


class AgentConfigError(RuntimeError):
    """Thiếu cấu hình để gọi Gemini."""


def make_client():
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise AgentConfigError("Chưa đặt GEMINI_API_KEY (tạo khóa miễn phí tại aistudio.google.com/apikey).")
    timeout_ms = int(os.environ.get("GEMINI_TIMEOUT_MS", "25000"))                 # không để một cuộc gọi treo vô hạn
    return genai.Client(api_key=key, http_options=types.HttpOptions(timeout=timeout_ms))


def _clean_schema(schema):
    """JSON Schema -> phần Gemini chắc chắn hỗ trợ: bỏ default, additionalProperties và các khóa lạ khác."""
    if not isinstance(schema, dict):
        return schema
    out = {}
    for key, value in schema.items():
        if key == "properties":                       # tên tham số là khóa tự do, không lọc
            out[key] = {name: _clean_schema(sub) for name, sub in value.items()}
        elif key == "items":
            out[key] = _clean_schema(value)
        elif key in SCHEMA_KEYS:
            out[key] = value
    return out


def gemini_tools(specs: list[dict]) -> list:
    return [types.Tool(function_declarations=[
        types.FunctionDeclaration(name=s["name"], description=s["description"],
                                  parameters_json_schema=_clean_schema(s["input_schema"])) for s in specs])]


@dataclass
class ToolCall:
    name: str
    input: dict
    ok: bool
    text: str
    result: dict = field(repr=False, default_factory=dict)


@dataclass
class AgentResult:
    answer: str
    tool_calls: list = field(default_factory=list)
    sources: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    unsupported_numbers: list = field(default_factory=list)
    stop_reason: str = ""
    model: str = ""
    steps: int = 0
    usage: dict = field(default_factory=lambda: {"input_tokens": 0, "output_tokens": 0})


class VinamilkAgent:
    def __init__(self, client=None, model: str | None = None, toolbox: Toolbox | None = None,
                 max_steps: int = 8, max_tokens: int = 8192, retry_delays: tuple = (1.5, 3.0),
                 fallback_models: tuple | None = None, deadline_s: float | None = None, intent_filter: bool = False):
        self._client = client
        self.intent_filter = intent_filter  # True: từ chối sớm câu ngoài phạm vi bằng bộ phân loại đã huấn luyện (src/train), không tốn lượt Gemini
        self.deadline_s = deadline_s        # tổng thời gian tối đa cho một câu hỏi (hàm serverless bị ngắt sau 60 giây)
        self._deadline = None
        self._cooldown: dict[str, float] = {}
        self.retry_delays = retry_delays
        self.model = model or os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
        if fallback_models is None:
            fallback_models = tuple(m.strip() for m in os.environ.get("GEMINI_FALLBACK_MODELS", DEFAULT_FALLBACKS).split(",")
                                    if m.strip())
        self.models = [self.model, *(m for m in fallback_models if m != self.model)]
        self.toolbox = toolbox or Toolbox()
        self.max_steps = max_steps
        self.config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT, tools=gemini_tools(self.toolbox.specs), max_output_tokens=max_tokens,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))   # vòng lặp tự quản lý

    @property
    def client(self):
        if self._client is None:
            self._client = make_client()
        return self._client

    def _generate(self, contents: list, pinned: str | None):
        """Gọi Gemini, trả về (tên mô hình đã trả lời, phản hồi).

        Lỗi tạm thời của máy chủ (500/503/504: quá tải, hết thời gian) được thử lại vài lần; nếu mô hình vẫn lỗi hoặc
        không dùng được với khóa này (429 hết hạn mức, 403/404) thì chuyển sang mô hình dự phòng kế tiếp.
        Khi đã `pinned` (giữa vòng gọi công cụ của một câu hỏi) thì chỉ dùng đúng mô hình đó vì chữ ký suy luận
        trong lượt hiện tại gắn với mô hình đã sinh ra nó.
        """
        first_error = None
        now = time.monotonic()
        ready = [m for m in self.models if self._cooldown.get(m, 0) <= now] or self.models
        for model in ([pinned] if pinned else ready):
            for delay in (*self.retry_delays, None):
                if self._deadline is not None and time.monotonic() > self._deadline:
                    raise first_error or TimeoutError("Hết thời gian chờ mô hình")
                try:
                    return model, self.client.models.generate_content(model=model, contents=contents, config=self.config)
                except Exception as e:                                     # noqa: BLE001 - lỗi khác được ném lại nguyên vẹn
                    code = getattr(e, "code", None)
                    first_error = first_error or e
                    if code in RETRY_CODES and delay is not None:
                        time.sleep(delay)
                        continue
                    if code in FALLTHROUGH_CODES and not pinned:
                        self._cooldown[model] = time.monotonic() + COOLDOWN_S
                        break                                              # sang mô hình dự phòng
                    raise
        raise first_error

    @staticmethod
    def _out_of_scope(question: str) -> bool:
        from ..train.intent import get_classifier               # nạp muộn: scikit-learn chỉ cần khi bật bộ lọc
        return get_classifier().is_out_of_scope(question)

    def ask(self, question: str, history: list | None = None) -> AgentResult:
        """Hỏi một câu. `history` là lịch sử hội thoại (được nối thêm tại chỗ); None = hội thoại mới.

        Trong một câu hỏi, các `Content` Gemini trả về (kể cả chữ ký suy luận) được giữ nguyên để vòng gọi công cụ
        chạy đúng. Khi câu hỏi xong, lịch sử chỉ còn câu hỏi và câu trả lời dạng văn bản: ngắn gọn hơn, và cho phép
        câu sau dùng mô hình khác. Nếu có lỗi giữa chừng, lịch sử trở về trạng thái trước câu hỏi.
        """
        self._deadline = time.monotonic() + self.deadline_s if self.deadline_s else None
        contents = history if history is not None else []
        if self.intent_filter and self._out_of_scope(question):
            contents.append(types.Content(role="user", parts=[types.Part(text=question)]))
            contents.append(types.Content(role="model", parts=[types.Part(text=REFUSAL_TEXT)]))
            return AgentResult(answer=REFUSAL_TEXT, stop_reason="OUT_OF_SCOPE", model="intent-classifier")
        start = len(contents)
        contents.append(types.Content(role="user", parts=[types.Part(text=question)]))
        res = AgentResult(answer="")
        tool_results: list = []
        pinned = None
        try:
            for step in range(1, self.max_steps + 1):
                pinned, resp = self._generate(contents, pinned)
                res.model = pinned
                res.steps = step
                usage = resp.usage_metadata
                res.usage["input_tokens"] += (getattr(usage, "prompt_token_count", 0) or 0)
                res.usage["output_tokens"] += (getattr(usage, "candidates_token_count", 0) or 0)

                cand = resp.candidates[0] if resp.candidates else None
                res.stop_reason = getattr(getattr(cand, "finish_reason", None), "name", "") or "STOP"
                if cand is None or cand.content is None or not cand.content.parts:
                    res.stop_reason = res.stop_reason if cand else "BLOCKED"
                    break
                contents.append(cand.content)

                calls = [p.function_call for p in cand.content.parts if p.function_call]
                if not calls:
                    break
                parts = []
                for fc in calls:
                    args = dict(fc.args or {})
                    out = self.toolbox.run(fc.name, args)
                    text, is_err = result_for_model(out)
                    parts.append(types.Part.from_function_response(
                        name=fc.name, response={"error": text} if is_err else {"output": text}))
                    res.tool_calls.append(ToolCall(fc.name, args, not is_err, text, out))
                    tool_results.append(out)
                    for s in out.get("sources", []) if not is_err else []:
                        if s not in res.sources:
                            res.sources.append(s)
                contents.append(types.Content(role="user", parts=parts))       # mọi kết quả trong MỘT lượt
            else:
                res.warnings.append(f"Đã dùng hết {self.max_steps} bước công cụ nên câu trả lời có thể chưa đầy đủ.")
        except Exception:
            del contents[start:]
            raise

        last = contents[-1]
        text = "".join(p.text for p in last.parts if p.text and not p.thought) if last.role == "model" else ""
        if res.stop_reason in BLOCKED or res.stop_reason == "BLOCKED":
            text = text or REFUSAL_TEXT
            res.warnings.append("Yêu cầu bị từ chối bởi bộ lọc an toàn của mô hình.")
        elif res.stop_reason == "MAX_TOKENS":
            res.warnings.append("Câu trả lời bị cắt do hết giới hạn độ dài.")
        res.answer = text.strip() or "Mình chưa tạo được câu trả lời. Bạn thử hỏi lại cụ thể hơn (nêu chỉ tiêu và kỳ báo cáo)."
        res.unsupported_numbers = find_unsupported_numbers(res.answer, tool_results)
        del contents[start:]                                                    # rút gọn lượt này thành hỏi + đáp dạng văn bản
        contents.append(types.Content(role="user", parts=[types.Part(text=question)]))
        contents.append(types.Content(role="model", parts=[types.Part(text=res.answer)]))
        return res
