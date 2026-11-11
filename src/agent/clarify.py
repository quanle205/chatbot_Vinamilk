"""Hỏi lại khi câu hỏi mơ hồ, trước khi gọi mô hình (xác định, không tốn lượt Gemini, kiểm thử được).

Hai loại mơ hồ được xử lý:
- Chỉ tiêu chung chung ("lợi nhuận", "phải thu", "nợ", "tài sản", "dòng tiền", "vốn") mà không nói rõ loại: mỗi loại là một chỉ tiêu khác nhau,
  trả nhầm loại sẽ ra số sai nên hỏi lại thay vì đoán.
- Có nhắc chỉ tiêu nhưng không nêu kỳ báo cáo, trong khi câu hỏi không phải kiểu nhiều kỳ và hội thoại trước cũng chưa nói kỳ nào.

Kết quả là `Clarification(question, options)`; mỗi lựa chọn mang sẵn câu hỏi đầy đủ để giao diện gửi lại khi người dùng bấm.
Không hỏi lại nếu đã có đủ thông tin; bất kỳ nghi ngờ nào cũng nghiêng về phía để mô hình trả lời.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from ..rag.text import accent_free, find_periods, normalize
from ..tools.metrics import METRICS

PERIOD_LABELS = ["Q2/2026", "Q1/2026", "Q4/2025", "Q3/2025", "Q2/2025", "Q1/2025"]

# Câu hỏi nhiều kỳ / tổng quan / diễn giải thuyết minh: không cần một kỳ cụ thể
_MULTI = re.compile(r"\b(qua cac|cac quy|cac ky|tung quy|tung ky|moi quy|moi ky|xu huong|bien dong|dien bien|theo thoi gian|lich su|"
                    r"tat ca|nhieu ky|6 ky|sau ky|so sanh|tang truong|gan nhat|moi nhat|hien tai|hien nay|tong quan|toan bo)\b")
_NOTES = re.compile(r"\b(gom nhung gi|bao gom|gom co|co nhung|chi tiet|thuyet minh|giai thich|la gi)\b")
_RATIO = re.compile(r"\b(bien loi nhuan|ty suat|ty so|ty le|roe|roa|he so|vong quay|bien)\b")
# Đã có cách xử lý riêng hoặc không thuộc loại hỏi lại: tỷ số (công cụ tự chọn tử/mẫu), "vì sao" (explain_change), dự báo / công ty khác (ngoài phạm vi)
_SKIP = re.compile(r"\b(ty le|ty so|he so|tren|vi sao|tai sao|do dau|du doan|du bao|nutifood|hoa phat|moc chau|doi thu|masan|fpt|th true milk|cong ty khac)\b")
_SHORT_PERIOD = re.compile(r"\bq[1-4]\s*[/-]?\s*\d{2}\b")


@dataclass(frozen=True)
class Clarification:
    question: str
    options: tuple                          # ((nhãn hiển thị, câu hỏi gửi lại), ...)

    def as_dict(self) -> dict:
        return {"question": self.question, "options": [{"label": a, "query": b} for a, b in self.options]}


# Thuật ngữ chung -> (biểu thức bắt thuật ngữ trên văn bản không dấu, từ bổ nghĩa làm câu hỏi đã rõ, các lựa chọn)
_AMBIGUOUS = [
    ("lợi nhuận", r"\bloi nhuan\b",
     r"\b(gop|sau thue|truoc thue|rong|hdkd|hoat dong kinh doanh|thuan|khac|cong ty me|co dong|chua phan phoi|bien|lnst|ebt|"
     r"tang|giam)\b|\bloi nhuan\b.*\b(tang|giam)\b",
     ["Lợi nhuận gộp", "Lợi nhuận kế toán trước thuế", "Lợi nhuận sau thuế"]),
    ("phải thu", r"\bphai thu\b", r"\b(khach hang|ngan han|dai han)\b",
     ["Phải thu khách hàng", "Các khoản phải thu ngắn hạn"]),
    ("nợ", r"\bno\b(?! thue tai chinh)", r"\b(phai tra|ngan han|dai han|vay|thue tai chinh|xau|quy doi)\b",
     ["Nợ phải trả", "Nợ ngắn hạn", "Nợ dài hạn"]),
    ("tài sản", r"\btai san\b", r"\b(tong|ngan han|dai han|co dinh|ty suat|ty le|bien|roa|vong quay|hieu suat)\b",
     ["Tổng tài sản", "Tài sản ngắn hạn", "Tài sản dài hạn"]),
    ("dòng tiền", r"\bdong tien\b", r"\b(kinh doanh|dau tu|tai chinh|hdkd|thuan)\b",
     ["Lưu chuyển tiền thuần từ hoạt động kinh doanh", "Lưu chuyển tiền thuần từ hoạt động đầu tư",
      "Lưu chuyển tiền thuần từ hoạt động tài chính"]),
    ("vốn", r"\bvon\b", r"\b(chu so huu|co phan|dieu le|chu|luu dong|hoa|von hoa|vay|dau tu)\b",
     ["Vốn chủ sở hữu", "Vốn cổ phần"]),
]
_METRIC_NAMES = [(m, [accent_free(normalize(a)) for a in (m.name, *m.aliases)]) for m in METRICS]


def _norm(text: str) -> str:
    return accent_free(unicodedata.normalize("NFC", text).lower())


def _history_users(history) -> str:
    out = []
    for c in history or []:
        if getattr(c, "role", None) == "user":
            out.extend(p.text for p in (c.parts or []) if getattr(p, "text", None))
    return " ".join(out)


def _replace_term(question: str, pattern: str, new: str) -> str:
    """Thay thuật ngữ chung trong câu gốc bằng tên chỉ tiêu cụ thể; không định vị được thì nối vào cuối câu."""
    q = unicodedata.normalize("NFC", question)
    flat = _norm(q)
    if len(flat) == len(q):
        m = re.search(pattern, flat)
        if m:
            return (q[:m.start()] + new + q[m.end():]).strip()
    return f"{q.rstrip(' ?.')} ({new})"


def _mentions_metric(flat: str) -> bool:
    padded = f" {re.sub(r'[^a-z0-9/]+', ' ', flat)} "
    return any(f" {a} " in padded for _, names in _METRIC_NAMES for a in names)


def needs_clarification(question: str, history=None) -> Clarification | None:
    """Câu hỏi này có nên được hỏi lại không? None = đủ rõ, cứ để mô hình trả lời."""
    flat = _norm(question)
    if _NOTES.search(flat) or _SKIP.search(flat):
        return None

    # 1) Chỉ tiêu chung chung
    for term, pattern, qualifier, options in _AMBIGUOUS:
        if re.search(pattern, flat) and not re.search(qualifier, flat) and not _mentions_specific_metric(flat, term):
            return Clarification(f"Bạn muốn xem {term} nào?", tuple((o, _replace_term(question, pattern, o)) for o in options))

    # 2) Có chỉ tiêu nhưng không nói kỳ
    docs, years = find_periods(question)
    docs_prior, years_prior = find_periods(_history_users(history))
    if docs or years or docs_prior or years_prior or _SHORT_PERIOD.search(flat) or _SHORT_PERIOD.search(_norm(_history_users(history))):
        return None
    if _MULTI.search(flat) or not (_mentions_metric(flat) or _RATIO.search(flat)):
        return None
    base = question.strip().rstrip(" ?.")
    options = [(p, f"{base} trong kỳ {p}?") for p in PERIOD_LABELS]
    options.append(("Xu hướng 6 kỳ", f"{base} qua 6 kỳ từ Q1/2025 đến Q2/2026?"))
    return Clarification("Bạn muốn xem ở kỳ báo cáo nào?", tuple(options))


def _mentions_specific_metric(flat: str, term: str) -> bool:
    """Câu đã gọi đúng tên một chỉ tiêu dài hơn thuật ngữ chung (vd "nợ" trong "lợi nhuận sau thuế")? Khi đó không hỏi."""
    padded = f" {re.sub(r'[^a-z0-9/]+', ' ', flat)} "
    key = accent_free(term)
    for _, names in _METRIC_NAMES:
        for a in names:
            if a != key and f" {key} " in f" {a} " and f" {a} " in padded:
                return True
    return False
