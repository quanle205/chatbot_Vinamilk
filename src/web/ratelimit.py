"""Giới hạn số lượt gọi mỗi phút theo địa chỉ IP, đếm trong bộ nhớ.

Hàm serverless không giữ trạng thái giữa các phiên bản nên đây chỉ là lớp bảo vệ cơ bản. IP chỉ dùng làm khóa đếm, không ghi ra đâu.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


class RateLimiter:
    def __init__(self, per_minute: int, message: str):
        self.per_minute, self.message = per_minute, message
        self._hits: dict[str, deque] = defaultdict(deque)

    def check(self, request: Request) -> None:
        ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "?")).split(",")[0].strip()
        q, now = self._hits[ip], time.time()
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.per_minute:
            raise HTTPException(429, self.message)
        q.append(now)

    def reset(self) -> None:
        self._hits.clear()
