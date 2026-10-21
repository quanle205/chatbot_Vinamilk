"""Agent hỏi đáp BCTC: Claude tool-use (vòng lặp thủ công) gọi công cụ tra số + retriever.

Claude chạy trên Google Cloud Vertex AI (AnthropicVertex): xác thực bằng ADC của Google (trên Cloud Run là
tài khoản dịch vụ gắn với dịch vụ), không cần khóa Anthropic. Client có thể tiêm vào để kiểm thử.

Cấu hình qua biến môi trường:
  ANTHROPIC_VERTEX_PROJECT_ID (hoặc GOOGLE_CLOUD_PROJECT)  ID dự án Google Cloud   [bắt buộc]
  CLOUD_ML_REGION                                          vùng Vertex, mặc định "global"
  VINAMILK_MODEL                                           mặc định claude-opus-5-5
  VINAMILK_EFFORT                                          low|medium|high, mặc định medium
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from .guard import find_unsupported_numbers
from .prompts import SYSTEM_PROMPT
from .toolbox import Toolbox, result_for_model

DEFAULT_MODEL = "claude-opus-5-5"
REFUSAL_TEXT = "Mình không thể trả lời câu hỏi này. Bạn có thể hỏi về số liệu và chỉ số trong BCTC hợp nhất của Vinamilk."


class AgentConfigError(RuntimeError):
    """Thiếu cấu hình để gọi Claude trên Vertex AI."""


def make_client():
    from anthropic import AnthropicVertex
    project = os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project:
        raise AgentConfigError("Chưa đặt ANTHROPIC_VERTEX_PROJECT_ID (ID dự án Google Cloud có bật Claude trên Vertex AI).")
    return AnthropicVertex(project_id=project, region=os.environ.get("CLOUD_ML_REGION", "global"))


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
                 max_steps: int = 8, effort: str | None = None, max_tokens: int = 16000):
        self._client = client
        self.model = model or os.environ.get("VINAMILK_MODEL", DEFAULT_MODEL)
        self.effort = effort or os.environ.get("VINAMILK_EFFORT", "medium")
        self.toolbox = toolbox or Toolbox()
        self.max_steps, self.max_tokens = max_steps, max_tokens

    @property
    def client(self):
        if self._client is None:
            self._client = make_client()
        return self._client

    def ask(self, question: str, messages: list | None = None) -> AgentResult:
        """Hỏi một câu. `messages` là lịch sử hội thoại (được nối thêm tại chỗ); None = hội thoại mới.

        Lịch sử giữ nguyên các khối trả về của Claude (kể cả thinking) và chỉ nối thêm, theo yêu cầu của API.
        Nếu có lỗi giữa chừng, lịch sử được trả về trạng thái trước câu hỏi để có thể hỏi lại.
        """
        history = messages if messages is not None else []
        start = len(history)
        history.append({"role": "user", "content": question})
        res = AgentResult(answer="")
        tool_results: list = []
        try:
            for step in range(1, self.max_steps + 1):
                resp = self.client.messages.create(
                    model=self.model, max_tokens=self.max_tokens, system=SYSTEM_PROMPT,
                    tools=self.toolbox.specs, messages=history, output_config={"effort": self.effort})
                res.steps = step
                res.usage["input_tokens"] += getattr(resp.usage, "input_tokens", 0) or 0
                res.usage["output_tokens"] += getattr(resp.usage, "output_tokens", 0) or 0
                res.stop_reason = resp.stop_reason
                history.append({"role": "assistant", "content": resp.content})

                if resp.stop_reason == "tool_use":
                    results = []
                    for block in (b for b in resp.content if b.type == "tool_use"):
                        out = self.toolbox.run(block.name, dict(block.input))
                        text, is_err = result_for_model(out)
                        results.append({"type": "tool_result", "tool_use_id": block.id, "content": text,
                                        **({"is_error": True} if is_err else {})})
                        res.tool_calls.append(ToolCall(block.name, dict(block.input), not is_err, text, out))
                        tool_results.append(out)
                        for s in out.get("sources", []) if not is_err else []:
                            if s not in res.sources:
                                res.sources.append(s)
                    history.append({"role": "user", "content": results})      # mọi kết quả trong MỘT tin nhắn
                    continue
                if resp.stop_reason == "pause_turn":
                    continue
                break
            else:
                res.warnings.append(f"Đã dùng hết {self.max_steps} bước công cụ nên câu trả lời có thể chưa đầy đủ.")
        except Exception:
            del history[start:]
            raise

        last = history[-1]
        text = "".join(b.text for b in last["content"] if getattr(b, "type", "") == "text") \
            if last["role"] == "assistant" else ""
        if res.stop_reason == "refusal":
            text = text or REFUSAL_TEXT
            res.warnings.append("Yêu cầu bị từ chối bởi bộ lọc an toàn của mô hình.")
        elif res.stop_reason == "max_tokens":
            res.warnings.append("Câu trả lời bị cắt do hết giới hạn độ dài.")
        if not text:
            text = "Mình chưa tạo được câu trả lời. Bạn thử hỏi lại cụ thể hơn (nêu chỉ tiêu và kỳ báo cáo)."
        res.answer = text.strip()
        res.unsupported_numbers = find_unsupported_numbers(res.answer, tool_results)
        return res
