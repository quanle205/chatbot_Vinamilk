"""Kiểu dữ liệu vào của API (kiểm tra bằng pydantic: sai thì FastAPI trả 422)."""
from __future__ import annotations

from datetime import datetime
import re

from pydantic import BaseModel, Field
from src.consumer.catalog import COMPANIES, PERIODS

MAX_QUESTION_CHARS = 500
BASIS = "^(quy|luy_ke)$"


class Turn(BaseModel):
    role: str = Field(pattern="^(user|model)$")
    text: str = Field(max_length=4000)


class AskBody(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    history: list[Turn] = []
    company: str | None = Field(default=None, pattern="^(" + "|".join(map(re.escape, COMPANIES)) + ")$")
    company_period: str | None = Field(default=None, pattern="^(" + "|".join(map(re.escape, PERIODS)) + ")$")


class ConsumerLookupBody(BaseModel):
    companies: list[str] = Field(min_length=1, max_length=2)
    period: str = Field(max_length=12)
    metric: str = Field(max_length=50)
    basis: str = Field(default="quy", pattern=BASIS)


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
    mode: str = Field(pattern="^(series|growth|explain|companies)$")
    metrics: list[str] = Field(min_length=1, max_length=3)            # series: tối đa 3 chỉ tiêu; hai chế độ còn lại dùng chỉ tiêu đầu
    period: str | None = Field(default=None, max_length=30)
    kind: str = Field(default="yoy", pattern="^(yoy|qoq)$")
    basis: str = Field(default="quy", pattern=BASIS)
    companies: list[str] = Field(default_factory=list, max_length=12)


class RatiosBody(BaseModel):
    period: str = Field(min_length=1, max_length=30)
    basis: str = Field(default="quy", pattern=BASIS)
    company: str = "VNM"
    companies: list[str] = Field(default_factory=list, max_length=12)
