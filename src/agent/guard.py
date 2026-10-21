"""Kiểm tra bám nguồn: số tiền/tỷ lệ trong câu trả lời có nằm trong kết quả công cụ không.

Mô hình có thể tự tính nhẩm hoặc nhớ nhầm số dù đã được dặn; hàm này bắt các số đó để giao diện cảnh báo.
Chỉ xét số có dấu phân cách hàng nghìn, có phần thập phân, hoặc từ 5 chữ số (bỏ qua năm, mã số, số thứ tự).
Khớp theo độ chính xác người viết dùng: "16.148,7 tỷ" khớp 16.148.657.871.623 VND vì sai lệch < 0,05.
"""
from __future__ import annotations

import re

NUM_RE = re.compile(r"(?<![\w.,])-?\d{1,3}(?:\.\d{3})+(?:,\d+)?|(?<![\w.,])-?\d+,\d+|(?<![\w.,])-?\d{5,}(?![\w])")
SCALES = (1.0, 1e3, 1e6, 1e9, 1e-2, 1e2)         # VND, nghìn, triệu, tỷ; tỷ lệ <-> phần trăm


def parse_vn(token: str) -> tuple[float, int]:
    """'16.148,7' -> (16148.7, 1 chữ số thập phân)."""
    t = token.replace(".", "")
    dec = len(t.split(",")[1]) if "," in t else 0
    return float(t.replace(",", ".")), dec


def numbers_in_text(text: str) -> list[float]:
    return [parse_vn(m.group(0))[0] for m in NUM_RE.finditer(text)]


def numbers_in_result(obj) -> list[float]:
    """Mọi số trong kết quả công cụ: giá trị cấu trúc + số trong `text`."""
    out: list[float] = []

    def walk(x):
        if isinstance(x, bool):
            return
        if isinstance(x, (int, float)):
            out.append(float(x))
        elif isinstance(x, str):
            out.extend(numbers_in_text(x))
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v)
    walk(obj)
    return out


def find_unsupported_numbers(answer: str, tool_results: list) -> list[str]:
    """Trả về các số trong câu trả lời không khớp số nào trong kết quả công cụ (theo mọi đơn vị)."""
    pool = numbers_in_result(tool_results)
    bad = []
    for m in NUM_RE.finditer(answer):
        n, dec = parse_vn(m.group(0))
        tol = 0.5 * 10 ** (-dec) * 1.001
        n_abs = abs(n)
        if any(abs(n_abs - abs(t) / s) <= tol or abs(n_abs - abs(t) * s) <= tol for t in pool for s in SCALES):
            continue
        bad.append(m.group(0))
    return bad
