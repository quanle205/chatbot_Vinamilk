"""Lưu phản hồi 👍/👎 của người dùng cho từng câu trả lời.

Vercel không giữ trạng thái và không có đĩa ghi lâu dài, nên phần lưu trữ nằm sau giao diện `FeedbackStore`:
  - mặc định (không đặt biến môi trường): ghi một dòng JSON ra stdout, xem trong Vercel Logs;
  - FEEDBACK_WEBHOOK_URL: gửi bản ghi (POST JSON) tới dịch vụ bên ngoài (Vercel Function khác, Google Apps Script, Zapier, Supabase Edge...),
    kèm FEEDBACK_WEBHOOK_TOKEN (tùy chọn) trong tiêu đề Authorization: Bearer.
Muốn gắn dịch vụ khác (vd Vercel Blob): viết thêm một lớp có phương thức `save(record)` rồi trả về trong `get_store()`.

Bản ghi chỉ gồm: câu hỏi, câu trả lời, nhãn, thời điểm. Không có IP, tiêu đề yêu cầu hay khóa API.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from abc import ABC, abstractmethod
from datetime import datetime, timezone

WEBHOOK_TIMEOUT_S = 3.0           # hàm serverless có hạn 60 giây; không để dịch vụ lưu trữ chậm kéo theo người dùng


class FeedbackStore(ABC):
    @abstractmethod
    def save(self, record: dict) -> None:
        """Lưu một bản ghi {question, answer, label, timestamp}. Ném ngoại lệ nếu không lưu được."""


class StdoutStore(FeedbackStore):
    def __init__(self, stream=None):
        self.stream = stream

    def save(self, record: dict) -> None:
        print("FEEDBACK " + json.dumps(record, ensure_ascii=False), file=self.stream or sys.stdout, flush=True)


class WebhookStore(FeedbackStore):
    def __init__(self, url: str, token: str | None = None, timeout: float = WEBHOOK_TIMEOUT_S):
        if not url.startswith(("https://", "http://")):
            raise ValueError("FEEDBACK_WEBHOOK_URL phải bắt đầu bằng https:// hoặc http://")
        self.url, self.token, self.timeout = url, token, timeout

    def save(self, record: dict) -> None:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(self.url, json.dumps(record, ensure_ascii=False).encode("utf-8"), headers, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout):                # noqa: S310 - URL do chủ dự án đặt qua biến môi trường
            pass


def get_store() -> FeedbackStore:
    url = os.environ.get("FEEDBACK_WEBHOOK_URL", "").strip()
    return WebhookStore(url, os.environ.get("FEEDBACK_WEBHOOK_TOKEN") or None) if url else StdoutStore()


def make_record(question: str, answer: str, label: str, timestamp: datetime | None = None) -> dict:
    ts = (timestamp or datetime.now(timezone.utc))
    ts = ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)
    return {"question": question, "answer": answer, "label": label, "timestamp": ts.isoformat(timespec="seconds")}
