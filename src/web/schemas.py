"""Kiểu dữ liệu vào của API (kiểm tra bằng pydantic: sai thì FastAPI trả 422)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

MAX_QUESTION_CHARS = 500
BASIS = "^(quy|luy_ke)$"


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
    basis: str = Field(default="quy", pattern=BASIS)


class ChartBody(BaseModel):
    mode: str = Field(pattern="^(series|growth|explain)$")           # xu hướng | so sánh hai kỳ | phân rã biến động
    metrics: list[str] = Field(min_length=1, max_length=3)            # series: tối đa 3 chỉ tiêu; hai chế độ còn lại dùng chỉ tiêu đầu
    period: str | None = Field(default=None, max_length=30)
    kind: str = Field(default="yoy", pattern="^(yoy|qoq)$")
    basis: str = Field(default="quy", pattern=BASIS)


class NotesBody(BaseModel):
    query: str = Field(min_length=2, max_length=200)
    period: str | None = Field(default=None, max_length=30)           # bỏ trống = mọi kỳ
    include_tables: bool = False                                      # False: chỉ văn bản thuyết minh; True: thêm bảng số liệu đã đối chiếu
    k: int = Field(default=8, ge=1, le=12)
