"""Máy tính an toàn cho các phép tính ngoài danh mục tỷ số: duyệt cây cú pháp, chỉ cho phép số học."""
from __future__ import annotations

import ast
import math
import operator

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv}
_UN = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {"abs": abs, "round": round, "min": min, "max": max, "sqrt": math.sqrt, "sum": lambda *a: sum(a)}
MAX_POW = 12


def calculate(expression: str, variables: dict | None = None) -> float:
    """Tính biểu thức số học, vd '(16148.7 - 12957.5) / 12957.5 * 100'. Số viết dạng 1.234,5 KHÔNG được hỗ trợ."""
    if len(expression) > 300:
        raise ValueError("Biểu thức quá dài.")
    names = {k: float(v) for k, v in (variables or {}).items()}
    tree = ast.parse(expression.strip().replace("^", "**"), mode="eval")

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _BIN:
            a, b = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Pow) and abs(b) > MAX_POW:
                raise ValueError("Số mũ quá lớn.")
            return _BIN[type(n.op)](a, b)
        if isinstance(n, ast.UnaryOp) and type(n.op) in _UN:
            return _UN[type(n.op)](ev(n.operand))
        if isinstance(n, ast.Name) and n.id in names:
            return names[n.id]
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FUNCS and not n.keywords:
            return _FUNCS[n.func.id](*[ev(a) for a in n.args])
        raise ValueError("Biểu thức chứa thành phần không được phép (chỉ cho số, + - * / ** %, ngoặc, abs/round/min/max/sqrt).")

    out = ev(tree)
    if isinstance(out, float) and (math.isnan(out) or math.isinf(out)):
        raise ValueError("Kết quả không xác định (chia cho 0?).")
    return out
