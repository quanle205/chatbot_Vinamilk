"""Agent hỏi đáp BCTC: Gemini function-calling (vòng lặp thủ công) gọi công cụ tra số + retriever.

Cấu hình qua biến môi trường (trên Streamlit Cloud đặt trong Secrets, xem app/streamlit_app.py):
  GEMINI_API_KEY   khóa tạo miễn phí tại https://aistudio.google.com/apikey   [bắt buộc]
  GEMINI_MODEL     mặc định gemini-3.8-flash; đổi nếu khóa của bạn không có quyền dùng model này
Client có thể tiêm vào (`VinamilkAgent(client=...)`) để kiểm thử mà không gọi mạng.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from google import genai
from google.genai import types

from .guard import find_unsupported_numbers
from .prompts import SYSTEM_PROMPT
from .toolbox import Toolbox, result_for_model

DEFAULT_MODEL = "gemini-3.8-flash"
REFUSAL_TEXT = "Mình không thể trả lời câu hỏi này. Bạn có thể hỏi về số liệu và chỉ số trong BCTC hợp nhất của Vinamilk."
BLOCKED = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION", "IMAGE_SAFETY"}
SCHEMA_KEYS = {"type", "required", "enum", "description", "minimum", "maximum"}


class AgentConfigError(RuntimeError):
    """Thiếu cấu hình để gọi Gemini."""


def make_client():
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise AgentConfigError("Chưa đặt GEMINI_API_KEY (tạo khóa miễn phí tại aistudio.google.com/apikey).")
    return genai.Client(api_key=key)


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
    steps: int = 0
    usage: dict = field(default_factory=lambda: {"input_tokens": 0, "output_tokens": 0})


class VinamilkAgent:
    def __init__(self, client=None, model: str | None = None, toolbox: Toolbox | None = None,
                 max_steps: int = 8, max_tokens: int = 8192):
        self._client = client
        self.model = model or os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
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

    def ask(self, question: str, history: list | None = None) -> AgentResult:
        """Hỏi một câu. `history` là lịch sử hội thoại (được nối thêm tại chỗ); None = hội thoại mới.

        Lịch sử giữ nguyên các `Content` Gemini trả về (kể cả chữ ký suy luận) và chỉ nối thêm.
        Nếu có lỗi giữa chừng, lịch sử được trả về trạng thái trước câu hỏi để có thể hỏi lại.
        """
        contents = history if history is not None else []
        start = len(contents)
        contents.append(types.Content(role="user", parts=[types.Part(text=question)]))
        res = AgentResult(answer="")
        tool_results: list = []
        try:
            for step in range(1, self.max_steps + 1):
                resp = self.client.models.generate_content(model=self.model, contents=contents, config=self.config)
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
        return res
