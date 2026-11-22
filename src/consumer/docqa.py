"""Hỏi đáp trên TOÀN BỘ chữ trong PDF của 12 công ty (không chỉ số liệu tài chính), có trích dẫn và không bịa.

Nguyên tắc: mọi thông tin trong câu trả lời phải nằm trong một đoạn văn bản của PDF, và đoạn đó được dẫn kèm tài liệu + trang.
Ba tầng, từ chắc chắn đến linh hoạt:

1. Trích xuất xác định cho câu hỏi về người ("chủ tịch là ai", "Hội đồng quản trị gồm những ai"): chỉ lấy tên và chức danh có trong chữ PDF.
2. Trích dẫn nguyên văn các dòng liên quan nhất (không sinh thêm chữ) cho mọi câu hỏi khác.
3. (Tùy chọn) Gemini tóm tắt từ chính các đoạn trích; kết quả bị loại nếu có tên riêng hoặc con số không nằm trong đoạn trích hay thiếu trích dẫn,
   khi đó chỉ giữ tầng 2.

Không tìm thấy thì nói rõ và gợi ý các câu hỏi tương tự mà PDF của công ty đó có thể trả lời (đã dò trước trong dữ liệu).
"""
from __future__ import annotations

import json
import re
import unicodedata
from difflib import SequenceMatcher
from dataclasses import dataclass
from functools import lru_cache

from src.consumer import repository
from src.consumer.catalog import COMPANIES, fold
from src.paths import CHUNKS_PATH
from src.rag.bm25 import BM25
from src.rag.text import accent_free

MAX_PASSAGES = 5
MAX_EXCERPT = 1400
MIN_COVERAGE = 0.6                                         # tỷ lệ từ khóa có nghĩa của câu hỏi phải nằm gần nhau (trong 3 dòng liền nhau) để đoạn được coi là liên quan
STRONG = 0.99                                              # đủ mọi từ khóa có nghĩa trong cùng một cửa sổ: mới được nói "tìm thấy"
RARE = 0.35                                                # từ xuất hiện ở quá 35% đoạn của công ty là từ thông dụng, không dùng để xét liên quan

STOPWORDS = set("""la ai gi cua nao co khong the bao nhieu o dau cho biet toi minh ban hay nhung cac mot duoc va trong nay do hien tai vui long
nhu sao tai giup xin hoi cong ty doanh nghiep tap doan tong ve voi cung nam quy ky thi ma va hoac neu khi nao tu den den cho de
ra sao nhin chung hoi da dang se hay la nhung gom gom nhung can vui tim cho xem noi bao gom the nao cac ten tên""".split())

# Câu hỏi về chữ trong PDF (người, thông tin công ty, hoạt động) chứ không phải số liệu tài chính
PEOPLE = ("chu tich", "tong giam doc", "giam doc", "hoi dong quan tri", "hdqt", "ban kiem soat", "ban giam doc", "ban tong giam doc", "nguoi dai dien",
          "ke toan truong", "thanh vien hoi dong", "lanh dao", "ban dieu hanh", "ceo", "cfo", "chairman", "board of directors", "founder", "nguoi sang lap", "ai la")
PROFILE = ("tru so", "dia chi", "thanh lap", "ma so thue", "giay chung nhan", "von dieu le", "nganh nghe", "linh vuc", "san pham", "thuong hieu", "nhan vien",
           "lao dong", "co dong lon", "co dong", "cong ty con", "cong ty lien ket", "lich su", "chien luoc", "tam nhin", "su menh", "thong diep", "kiem toan",
           "website", "dien thoai", "email", "nha may", "chi nhanh", "hoat dong chinh", "kinh doanh nhung gi", "ra doi", "giai thuong", "chung nhan", "dai ly",
           "nha phan phoi", "xuat khau", "thi phan", "doi thu", "gioi thieu", "tong quan ve cong ty", "co cau to chuc", "co cau co dong", "so huu")

SYNONYMS = {
    "chu tich": ("chairman", "chu tich hdqt", "chu tich hoi dong quan tri"),
    "hoi dong quan tri": ("board of directors", "hdqt", "thanh vien hoi dong quan tri"),
    "tong giam doc": ("ceo", "chief executive officer", "general director", "tong giam doc"),
    "giam doc tai chinh": ("cfo", "chief financial officer"),
    "ke toan truong": ("chief accountant",),
    "ban kiem soat": ("audit committee", "supervisory board", "ban kiem soat"),
    "kiem toan": ("auditor", "auditors", "cong ty kiem toan"),
    "tru so": ("dia chi", "address", "head office", "registered office"),
    "dia chi": ("address", "tru so chinh"),
    "von dieu le": ("charter capital", "share capital", "von cp"),
    "thanh lap": ("established", "incorporated", "giay chung nhan dang ky doanh nghiep", "dang ky doanh nghiep"),
    "nguoi dai dien": ("legal representative", "nguoi dai dien theo phap luat"),
    "nhan vien": ("employees", "lao dong", "headcount"),
    "san pham": ("products", "thuong hieu"),
    "nganh nghe": ("principal activities", "linh vuc hoat dong", "hoat dong chinh"),
    "linh vuc": ("principal activities", "nganh nghe kinh doanh"),
    "co dong": ("shareholders", "co dong lon"),
    "cong ty con": ("subsidiaries", "cong ty lien ket"),
    "chien luoc": ("strategy", "dinh huong"),
}
# Chủ đề dùng để gợi ý: (nhãn, từ khóa có thể xuất hiện trong PDF, mẫu câu hỏi). Gợi ý chỉ nêu chủ đề mà PDF của công ty đó THẬT SỰ có chữ liên quan.
TOPICS = (
    ("Hội đồng quản trị và Chủ tịch", ("chu tich", "hoi dong quan tri", "board of directors", "chairman"), "Hội đồng quản trị của {name} gồm những ai?"),
    ("Ban Tổng giám đốc", ("tong giam doc", "ban giam doc", "chief executive", "ban dieu hanh"), "Ban Tổng giám đốc của {name} gồm những ai?"),
    ("Công ty kiểm toán", ("cong ty kiem toan", "auditor", "kiem toan vien"), "Công ty kiểm toán của {name} là công ty nào?"),
    ("Địa chỉ trụ sở", ("tru so", "dia chi", "registered office", "head office"), "Trụ sở chính của {name} ở đâu?"),
    ("Vốn điều lệ và cổ đông", ("von dieu le", "charter capital", "co dong lon", "shareholders"), "Vốn điều lệ và cổ đông của {name} thế nào?"),
    ("Ngành nghề kinh doanh", ("nganh nghe", "principal activities", "hoat dong chinh", "linh vuc hoat dong"), "Lĩnh vực hoạt động của {name} là gì?"),
    ("Công ty con và liên kết", ("cong ty con", "subsidiaries", "cong ty lien ket"), "{name} có những công ty con nào?"),
    ("Chiến lược và thông điệp lãnh đạo", ("chien luoc", "thong diep", "tam nhin", "strategy"), "Chiến lược của {name} là gì?"),
    ("Các khoản vay", ("vay ngan han", "vay dai han", "borrowings"), "Các khoản vay của {name} gồm những gì?"),
)
# Họ chủ đề: khi câu hỏi thuộc một họ mà PDF không có, gợi ý trước các chủ đề cùng họ
FAMILIES = {
    "nguoi": ("chu tich", "tong giam doc", "giam doc", "hoi dong quan tri", "hdqt", "ban kiem soat", "nguoi dai dien", "ke toan truong", "lanh dao", "ceo", "cfo"),
    "ho_so": ("tru so", "dia chi", "thanh lap", "ma so thue", "von dieu le", "nganh nghe", "linh vuc", "website", "dien thoai", "email"),
    "hoat_dong": ("san pham", "thuong hieu", "nha may", "chi nhanh", "thi phan", "chien luoc", "doi thu", "xuat khau", "nhan vien", "ban", "san xuat",
                  "kinh doanh", "cung cap", "mat hang", "nganh hang", "khach hang"),
}
FAMILY_TOPICS = {"nguoi": (0, 1, 2), "ho_so": (3, 4, 5), "hoat_dong": (5, 7, 6)}
TITLES = r"(?:Mr|Ms|Mrs|Dr|Ông|Ong|Bà|Ba)\.?"


@dataclass(frozen=True)
class Passage:
    company: str
    doc: str                 # mã tài liệu (tên tệp PDF hoặc q1-2025 cho Vinamilk)
    period: str
    page: int
    text: str
    url: str
    section: str
    score: float = 0.0
    coverage: float = 0.0


def entity_name(code: str) -> str:
    return "Vinamilk" if code == "VNM" else COMPANIES[code][0]


def has_phrase(folded: str, phrases) -> bool:
    return any(re.search(rf"(?<!\w){re.escape(p)}(?!\w)", folded) for p in phrases)


def is_document_question(query: str) -> bool:
    """Câu hỏi (đã bỏ dấu, chữ thường) về chữ trong PDF: người, thông tin công ty, hoạt động; không phải số liệu tài chính."""
    return has_phrase(query, PEOPLE) or has_phrase(query, PROFILE)


# ------------------------------------------------------------------ kho đoạn văn
def _period_of(doc: str) -> str:
    match = re.fullmatch(r"q([1-4])-(20\d\d)", doc)
    return f"Q{match[1]}/{match[2]}" if match else doc


@lru_cache(maxsize=16)
def corpus(code: str):
    """(danh sách đoạn, chỉ mục BM25, văn bản đã bỏ dấu của từng đoạn) cho toàn bộ PDF của một công ty."""
    passages: list[Passage] = []
    if code == "VNM":
        from src.web.sources import pdf_url
        with open(CHUNKS_PATH, encoding="utf-8") as f:
            for line in f:
                c = json.loads(line)
                if c.get("kind") != "van_ban" or c.get("page") is None:
                    continue
                passages.append(Passage("VNM", c["doc"], _period_of(c["doc"]), int(c["page"]), c["text"], pdf_url(c["doc"], c["page"]),
                                        c.get("heading") or "Báo cáo tài chính"))
    else:
        with repository.open_db() as db:
            rows = db.execute("""select d.id, d.period, c.page, c.content, d.url, d.statement from document_chunks c join documents d using(id)
                                 where d.company=? order by d.period, c.page, c.ordinal""", [code]).fetchall()
        passages = [Passage(code, doc, period, int(page), text, url, statement) for doc, period, page, text, url, statement in rows]
    folded = [fold(p.text) for p in passages]
    return passages, (BM25([p.text for p in passages]) if passages else None), folded


PERIOD_ORDER = {p: i for i, p in enumerate(("Q1/2025", "Q2/2025", "Q3/2025", "Q4/2025", "FY2025", "Q1/2026", "Q2/2026", "Q3/2026"))}


VI_LETTERS = set("àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ")
VI_LETTERS |= {c.upper() for c in VI_LETTERS}


def noise(text: str) -> float:
    """Tỷ lệ chữ cái lạ (å, ö, ü, ä...) mà tiếng Việt/Anh không dùng: dấu hiệu OCR đọc nhiễu; 0 là sạch."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if ord(c) > 127 and c not in VI_LETTERS) / len(letters)


def strip_marks(text: str) -> str:
    """Bỏ dấu từng ký tự (độ dài giữ nguyên, nên vị trí khớp với văn bản gốc); chữ OCR nhiễu như "Chü" vẫn đọc được thành "Chu"."""
    return "".join("d" if c == "đ" else "D" if c == "Đ" else unicodedata.normalize("NFD", c)[0] for c in text)


# ------------------------------------------------------------------ phân tích câu hỏi
def focus_terms(question: str, code: str) -> list[str]:
    """Từ khóa của câu hỏi: bỏ từ chức năng, tên công ty và kỳ báo cáo."""
    q = fold(question)
    names = {w for alias in (COMPANIES[code][1] if code != "VNM" else ("vinamilk", "vnm")) for w in alias.split()} | {code.lower()}
    q = re.sub(r"\b(?:q|quy)\s*[1-4]\b|\b20\d\d\b|\b\d+\b", " ", q)
    return [w for w in re.findall(r"\w+", q) if w not in STOPWORDS and w not in names and len(w) >= 2]


def expand(question: str, terms: list[str]) -> str:
    q = fold(question)
    extra = [s for phrase, syns in SYNONYMS.items() if has_phrase(q, (phrase,)) for s in syns]
    return " ".join([*terms, *extra])


def must_phrases(question: str) -> list[str]:
    """Cụm từ khóa then chốt của câu hỏi (vd "chu tich") cùng từ đồng nghĩa: đoạn trả lời phải chứa ít nhất một trong số đó."""
    q = fold(question)
    out = []
    for phrase, syns in SYNONYMS.items():
        if has_phrase(q, (phrase,)):
            out += [phrase, *syns]
    return out


def requested_years(question: str) -> set[str]:
    return set(re.findall(r"\b(20\d\d)\b", fold(question)))


@lru_cache(maxsize=16)
def document_frequency(code: str) -> dict:
    """Tỷ lệ đoạn của công ty chứa từng từ (đã bỏ dấu): để biết từ nào thông dụng, từ nào có nghĩa phân biệt."""
    folded = corpus(code)[2]
    counts: dict[str, int] = {}
    for text in folded:
        for word in set(re.findall(r"\w+", text)):
            counts[word] = counts.get(word, 0) + 1
    total = max(1, len(folded))
    return {word: n / total for word, n in counts.items()}


def term_weights(code: str, terms: list[str]) -> dict[str, int]:
    """Trọng số từ khóa: từ hiếm trong tài liệu (có nghĩa phân biệt, vd "website") nặng 2, từ thông dụng ("bán", "máy") nặng 1."""
    freq = document_frequency(code)
    return {t: (2 if freq.get(t, 0) <= RARE else 1) for t in dict.fromkeys(terms)}


def window_coverage(text: str, weights: dict[str, int], size: int = 3) -> float:
    """Độ khớp của đoạn với câu hỏi trong cửa sổ `size` dòng liền nhau tốt nhất.

    1.0 khi đủ mọi từ hiếm và ít nhất 2/3 tổng trọng số nằm gần nhau ("nhắc đủ ý"); thiếu từ hiếm thì chỉ tính 0,9 lần tỷ lệ trọng số, nên không bao giờ đạt "tìm thấy"."""
    lines = [l for l in text.splitlines() if l.strip()] or [text]
    total, rare = sum(weights.values()), {t for t, w in weights.items() if w == 2}
    best = 0.0
    for i in range(max(1, len(lines) - size + 1)):
        window = " ".join(lines[i:i + size])
        present = {t for t in weights if re.search(rf"(?<!\w){re.escape(t)}(?!\w)", window)}
        fraction = sum(weights[t] for t in present) / total
        best = max(best, 1.0 if rare <= present and fraction >= 2 / 3 else fraction * 0.9)
    return best


def search(code: str, question: str, limit: int = MAX_PASSAGES) -> list[Passage]:
    """Các đoạn PDF liên quan nhất, đã lọc theo độ phủ từ khóa; rỗng nếu PDF không có chữ nào đủ liên quan."""
    passages, index, folded = corpus(code)
    terms = focus_terms(question, code)
    if index is None or not terms:
        return []
    musts = must_phrases(question)
    scores = index.scores(expand(question, terms))
    years = requested_years(question)
    weights = term_weights(code, terms)
    ranked = []
    for i in sorted(range(len(passages)), key=lambda i: -scores[i])[:80]:
        if scores[i] <= 0:
            break
        p, text = passages[i], folded[i]
        if years and not any(p.period.endswith(y) for y in years):
            continue
        if musts and not has_phrase(text, musts):
            continue                                       # câu hỏi nêu rõ chủ đề (vd chủ tịch) mà đoạn không nhắc đến thì bỏ
        coverage = window_coverage(text, weights)
        if coverage < MIN_COVERAGE:
            continue
        recency = PERIOD_ORDER.get(p.period, 0) / max(PERIOD_ORDER.values())
        clean = 1 - min(0.85, 4 * noise(p.text))                    # trang OCR nhiễu bị đẩy xuống: ưu tiên trang đọc rõ để trích dẫn đáng tin
        ranked.append((scores[i] * (1 + 0.25 * coverage) * clean * (1 + (0.1 * recency if not years else 0)), i, coverage))
    out, seen = [], set()
    for score, i, coverage in sorted(ranked, reverse=True):
        key = (passages[i].doc, passages[i].page)
        if key in seen:
            continue
        seen.add(key)
        p = passages[i]
        out.append(Passage(p.company, p.doc, p.period, p.page, p.text, p.url, p.section, round(float(score), 2), round(coverage, 2)))
        if len(out) >= limit:
            break
    return out


# ------------------------------------------------------------------ tầng 1: trích xuất người (xác định)
TITLES = r"(?:Mr|Ms|Mrs|Dr|Ong|Ba)"
ROLE_WORDS = (r"(?i:Vice[- ]Chairman|Chairman|Chairwoman|Member|Chief Executive Officer|General Director|Pho Chu tich|Chu tich|Thanh vien|"
              r"Pho Tong Giam doc|Tong Giam doc)")
NAME = r"[A-Z][A-Za-z'.-]*(?:\s+[A-Z][A-Za-z'.-]*){1,4}?"
NAME_THEN_ROLE = re.compile(rf"\b({TITLES})\s+({NAME})\s+({ROLE_WORDS})\b")
ROLE_LABELS = {"chairman": "Chủ tịch", "chairwoman": "Chủ tịch", "chu tich": "Chủ tịch", "vice chairman": "Phó Chủ tịch", "pho chu tich": "Phó Chủ tịch",
               "member": "Thành viên", "thanh vien": "Thành viên", "chief executive officer": "Tổng Giám đốc", "general director": "Tổng Giám đốc",
               "tong giam doc": "Tổng Giám đốc", "pho tong giam doc": "Phó Tổng Giám đốc"}
CHAIR = {"chairman", "chairwoman", "chu tich"}
CEO = {"chief executive officer", "general director", "tong giam doc"}


@dataclass(frozen=True)
class Person:
    name: str
    role: str                # đã chuẩn hóa: chữ thường, không dấu
    passage: Passage
    line: str
    noise: float


def people_in(passage: Passage) -> list[Person]:
    """Người và chức danh viết liền nhau trong chữ PDF ("Mr Danny Le Chairman", "Ông Nguyễn Văn A Chủ tịch"); tên lấy đúng chữ gốc của dòng."""
    out = []
    for raw in passage.text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        plain = strip_marks(line)
        for m in NAME_THEN_ROLE.finditer(plain):
            name = line[m.start(2):m.end(2)]
            if name.split()[-1].lower() in {"vice", "pho"}:
                continue
            out.append(Person(name, re.sub(r"[- ]+", " ", m.group(3).lower().replace("-", " ")), passage, line, noise(line)))
    return out


def asked_role(question: str):
    """"chairman", "ceo" hoặc "board" nếu câu hỏi là về người giữ chức danh đó; None nếu không."""
    q = fold(question)
    if has_phrase(q, ("chu tich", "chairman")) and not has_phrase(q, ("pho chu tich",)):
        return "chairman"
    if has_phrase(q, ("tong giam doc", "ceo", "chief executive")):
        return "ceo"
    if has_phrase(q, ("hoi dong quan tri", "hdqt", "board of directors", "thanh vien hoi dong", "ban lanh dao")):
        return "board"
    return None


def same_name(a: str, b: str) -> bool:
    return SequenceMatcher(None, accent_free(a.lower()), accent_free(b.lower())).ratio() >= 0.8


def role_answer(code: str, question: str, passages: list[Passage]):
    """(văn bản trả lời, đoạn dẫn chứng) nếu trích được người/chức danh đúng câu hỏi từ chữ PDF; None nếu không.

    Chọn bản đọc rõ nhất (ít nhiễu OCR nhất), cùng độ rõ thì lấy kỳ mới nhất."""
    role = asked_role(question)
    if role is None:
        return None
    found = [p for passage in passages for p in people_in(passage)]
    if role == "chairman":
        found = [p for p in found if p.role in CHAIR]
    elif role == "ceo":
        found = [p for p in found if p.role in CEO]
    if not found:
        return None
    def rank(p):
        return (round(p.noise, 2), -PERIOD_ORDER.get(p.passage.period, 0))
    best = min(found, key=rank)
    if re.search(r"(?i)nhim|nhiem|appoint|resign|dismiss|from \d", strip_marks(best.line)):
        return None                                                  # dòng ghi bổ nhiệm/miễn nhiệm: không kết luận "hiện tại", chỉ trích nguyên văn
    variants = [p.name for p in found if same_name(p.name, best.name) and p.noise <= 0.03]
    if variants:                                                     # tên lặp lại ở nhiều kỳ/tài liệu: lấy cách viết phổ biến nhất để giảm lỗi OCR
        best = Person(max(set(variants), key=variants.count), best.role, best.passage, best.line, best.noise)
    label = {"chairman": "Chủ tịch Hội đồng quản trị", "ceo": "Tổng Giám đốc", "board": "Hội đồng quản trị"}[role]
    if role == "board":
        chosen = [p for p in found if p.passage is best.passage]
        text = f"**{label} của {entity_name(code)}** theo báo cáo {best.passage.period}: " + "; ".join(f"{p.name} ({ROLE_LABELS.get(p.role, p.role)})" for p in chosen) + "."
        evidence = [best.passage]
    else:
        names = [best.name]
        text = f"**{label} của {entity_name(code)}: {best.name}** (theo báo cáo {best.passage.period})."
        evidence = [best.passage]
        others = {}
        for p in found:
            if p.passage.period != best.passage.period and not same_name(p.name, best.name) and p.noise <= 0.02:
                others[p.passage.period] = p.name
        if others:
            text += " Các kỳ khác ghi: " + ", ".join(f"{n} ({per})" for per, n in sorted(others.items())) + "."
    return text, evidence


# ------------------------------------------------------------------ tầng 2: trích dẫn nguyên văn
def best_lines(passage: Passage, terms: list[str], limit: int = 7) -> str:
    """Các dòng của đoạn có nhiều từ khóa nhất (kèm một dòng liền kề để giữ danh sách), giữ nguyên chữ PDF và thứ tự."""
    lines = [re.sub(r"\s+", " ", l).strip() for l in passage.text.splitlines() if l.strip()]
    if len(lines) <= limit:
        return "\n".join(lines)
    longest = [t for t in terms if len(t) >= 3] or terms
    score = [sum(1 for t in longest if t in fold(l)) for l in lines]
    keep = set()
    for i in sorted(range(len(lines)), key=lambda i: -score[i])[:max(2, limit // 2)]:
        if score[i] > 0:
            keep.update({i - 1, i, i + 1})
    chosen = sorted(i for i in keep if 0 <= i < len(lines))[:limit]
    return "\n".join(lines[i] for i in chosen) or "\n".join(lines[:limit])


def quote_block(passages: list[Passage], terms: list[str], limit: int = 3) -> str:
    out = []
    for p in passages[:limit]:
        quoted = "\n".join(f"> {line}" for line in best_lines(p, terms).splitlines())
        out.append(f"{quoted}\n> — *{entity_name(p.company)} · {p.period} · trang {p.page}*")
    return "\n\n".join(out)


def source_of(p: Passage) -> dict:
    """Nguồn dẫn chứng cho giao diện: tài liệu, trang, liên kết PDF và chính đoạn chữ làm bằng chứng."""
    excerpt = re.sub(r"[ \t]+", " ", p.text).strip()
    if len(excerpt) > MAX_EXCERPT:
        excerpt = excerpt[:MAX_EXCERPT].rstrip() + " …"
    if p.company == "VNM":
        return {"doc": p.doc, "statement": p.section, "page": p.page, "url": p.url, "is_pdf": p.url.endswith(f"#page={p.page}"), "excerpt": excerpt}
    return {**repository.source(p.company, p.period, "PDF", p.page, p.url, p.section), "excerpt": excerpt}


# ------------------------------------------------------------------ gợi ý câu hỏi tương tự
@lru_cache(maxsize=16)
def available_topics(code: str) -> tuple:
    """Chỉ số các chủ đề trong TOPICS mà chính câu hỏi gợi ý của chủ đề đó TÌM THẤY chữ trả lời trong PDF của công ty
    (đã chạy thật trên dữ liệu, nên mọi câu gợi ý đều bấm vào là có kết quả)."""
    name = entity_name(code)
    return tuple(i for i, (_, _, query) in enumerate(TOPICS) if search(code, query.format(name=name), limit=1))


def suggestions(code: str, question: str, limit: int = 4) -> list[dict]:
    """Câu hỏi tương tự về nội dung mà PDF của công ty CÓ thể trả lời: cùng họ chủ đề với câu hỏi trước, rồi các chủ đề khác có sẵn."""
    q = fold(question)
    have = list(available_topics(code))
    family = next((f for f, words in FAMILIES.items() if has_phrase(q, words)), None)
    order = [i for i in FAMILY_TOPICS.get(family, ()) if i in have] + [i for i in have if i not in FAMILY_TOPICS.get(family, ())]
    name = entity_name(code)
    return [{"label": TOPICS[i][0], "query": TOPICS[i][2].format(name=name)} for i in order[:limit]]


# ------------------------------------------------------------------ tầng 3: Gemini tóm tắt có kiểm tra
SYSTEM = ("Bạn trả lời câu hỏi CHỈ dựa vào các đoạn trích đánh số được cung cấp (chữ OCR từ PDF báo cáo của công ty). "
          "Không dùng kiến thức bên ngoài, không suy đoán. Nếu các đoạn trích không có câu trả lời, chỉ viết đúng câu: Không tìm thấy trong các đoạn trích. "
          "Mỗi dữ kiện phải kèm số đoạn trích trong ngoặc vuông, ví dụ [1]. Giữ nguyên tên riêng và con số như trong đoạn trích, không sửa chính tả tên người. "
          "Trả lời ngắn gọn bằng tiếng Việt (giữ nguyên thuật ngữ tiếng Anh nếu đoạn trích bằng tiếng Anh).")
NOT_FOUND = "không tìm thấy trong các đoạn trích"
COMMON = set("""ong ba mr ms mrs dr cong ty tap doan hoi dong quan tri chu tich tong giam doc ban kiem soat bao cao tai chinh theo the nam quy trang
vietnam viet nam ha noi ho chi minh co phan tnhh nhan vien khong tim thay trong cac doan trich board directors chairman member annual report""".split())


def build_prompt(question: str, passages: list[Passage]) -> str:
    blocks = [f"[{i}] ({entity_name(p.company)} · {p.period} · trang {p.page})\n{re.sub(r'[ \\t]+', ' ', p.text).strip()[:MAX_EXCERPT]}" for i, p in enumerate(passages, 1)]
    return f"Câu hỏi: {question}\n\nCác đoạn trích:\n\n" + "\n\n".join(blocks)


def tokens(text: str) -> set[str]:
    return set(re.findall(r"\w+", accent_free(text.lower())))


def near_token(word: str, vocabulary: set[str]) -> bool:
    """`word` có trong từ vựng, hoặc chỉ khác một ký tự (OCR đọc lệch một chữ)?"""
    if word in vocabulary:
        return True
    return len(word) >= 5 and any(abs(len(v) - len(word)) <= 1 and sum(a != b for a, b in zip(v, word)) + abs(len(v) - len(word)) <= 1 for v in vocabulary)


def grounded(answer: str, passages: list[Passage]) -> tuple[bool, str]:
    """Câu trả lời do mô hình sinh có bám đúng các đoạn trích không? (ok, lý do khi không đạt).

    Phải: có trích dẫn [n] hợp lệ; mọi số có từ 2 chữ số trở lên xuất hiện trong đoạn trích; mọi tên riêng (từ viết hoa không phải từ thông dụng)
    xuất hiện trong đoạn trích (cho phép OCR lệch một ký tự). Không đạt thì bỏ câu trả lời sinh, chỉ giữ trích dẫn nguyên văn."""
    if not answer.strip():
        return False, "rỗng"
    cites = [int(n) for n in re.findall(r"\[(\d+)\]", answer)]
    if not cites or any(n < 1 or n > len(passages) for n in cites):
        return False, "thiếu hoặc sai trích dẫn"
    context = " ".join(p.text for p in passages)
    vocabulary = tokens(context)
    digits = re.sub(r"\D", "", context)
    body = re.sub(r"\[\d+\]", " ", answer)
    for number in re.findall(r"\d[\d.,]*\d|\d", body):
        plain = re.sub(r"\D", "", number)
        if len(plain) >= 2 and plain not in digits:
            return False, f"số {number} không có trong đoạn trích"
    for sentence in re.split(r"(?<=[.!?])\s+|\n", body):
        words = re.findall(r"[A-ZÀ-Ỹ][\wÀ-ỹ'’-]+", sentence)
        for k, word in enumerate(words):
            token = accent_free(word.lower())
            if token in COMMON or len(token) < 3 or token.isdigit():
                continue
            if sentence.strip().startswith(word) and k == 0 and token in vocabulary | COMMON:
                continue
            if not near_token(token, vocabulary):
                return False, f"tên/từ {word} không có trong đoạn trích"
    return True, ""


# ------------------------------------------------------------------ trả lời
def answer(code: str, question: str, llm=None) -> dict:
    """Trả lời một câu hỏi về chữ trong PDF của `code`: {"text", "sources", "notes", "suggestions", "found"}.

    `llm(system, prompt) -> str` (tùy chọn) dùng để tóm tắt từ các đoạn trích; câu trả lời của nó phải qua `grounded`."""
    role_asked = asked_role(question)
    passages = search(code, question, limit=60 if role_asked else MAX_PASSAGES)
    name = entity_name(code)
    notes = []
    if not passages:
        text = (f"Mình không tìm thấy thông tin này trong các báo cáo/PDF của {name} mà mình đã đọc"
                f" ({len({p.doc for p in corpus(code)[0]})} tài liệu). Có thể báo cáo không đề cập hoặc chữ OCR của trang đó quá nhiễu nên không đọc được; "
                "mình không suy đoán ngoài tài liệu.")
        tips = suggestions(code, question)
        if tips:
            text += "\n\nBạn có thể thử các câu hỏi tương tự mà PDF của " + name + " có nội dung:"
        return {"text": text, "sources": [], "notes": notes, "suggestions": tips, "found": False}
    terms = focus_terms(question, code)
    direct = role_answer(code, question, passages)
    passages = passages[:MAX_PASSAGES]
    if direct:
        text, evidence = direct
        text += "\n\n" + quote_block(evidence, terms, limit=2)
        notes.append("Tên và chức danh trích đúng từ chữ trong PDF (văn bản OCR); mở Nguồn để đối chiếu.")
        return {"text": text, "sources": [source_of(p) for p in evidence[:3]], "notes": notes, "suggestions": [], "found": True}
    summary = ""
    if llm is not None:
        try:
            generated = llm(SYSTEM, build_prompt(question, passages))
        except Exception:                                               # noqa: BLE001 - mô hình lỗi/quá tải: vẫn có trích dẫn nguyên văn
            generated = ""
        ok, why = grounded(generated or "", passages)
        if ok and NOT_FOUND not in generated.lower():
            summary = generated.strip()
        elif generated:
            notes.append("Phần tóm tắt tự động bị bỏ vì không bám sát đoạn trích; chỉ hiển thị trích dẫn nguyên văn từ PDF.")
    strong = passages[0].coverage >= STRONG
    if not strong:
        notes.append("Các đoạn này chỉ khớp một phần câu hỏi của bạn; hãy đọc trích dẫn để xem có đúng ý không.")
    head = (summary + "\n\n**Trích từ PDF:**\n\n" if summary else
            f"**Thông tin tìm thấy trong báo cáo của {name}** (trích nguyên văn từ PDF):\n\n" if strong else
            f"**Các đoạn gần nhất trong báo cáo của {name}** (chỉ khớp một phần câu hỏi, có thể chưa đúng ý bạn):\n\n")
    text = head + quote_block(passages, terms)
    notes.append("Chữ trích từ PDF là văn bản OCR, có thể sai dấu hoặc ký tự; mở Nguồn để đối chiếu với trang gốc.")
    return {"text": text, "sources": [source_of(p) for p in passages[:MAX_PASSAGES]], "notes": notes, "suggestions": [], "found": True}
