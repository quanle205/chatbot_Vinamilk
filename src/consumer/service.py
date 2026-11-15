"""Trả lời các câu hỏi có cấu trúc bằng số đã đối chiếu hoặc trích đoạn nguồn."""
import re

from src.consumer import repository
from src.consumer.catalog import COMPANIES, METRICS, PERIODS, fold
from src.rag.text import ROMAN, find_periods, fmt_vnd

QUARTER_WITHOUT_YEAR = re.compile(r"\b(?:q|quy)\s*([1-4]|iv|iii|ii|i)\b")
QUARTER_WORDS = {"mot": 1, "hai": 2, "ba": 3, "bon": 4, "tu": 4}


def matches(query, aliases):
    return any(re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", query) for alias in aliases)


def question_companies(question):
    query = fold(question)
    return [code for code, (_, aliases) in COMPANIES.items() if matches(query, (code.lower(), *aliases))]


def question_metrics(query):
    return {metric for metric, (label, aliases) in METRICS.items()
            if matches(query, (fold(label), *aliases))}


def inherited_question(question, history):
    query = fold(question)
    if matches(query, ("vinamilk", "vnm")) or not (
        question_metrics(query) or matches(query, ("thuyet minh",))
    ):
        return None
    for previous in reversed(history):
        if matches(fold(previous), ("vinamilk", "vnm")):
            return None
        if question_companies(previous):
            return previous
    return None


def requested_periods(question):
    query = re.sub(r"\bquy\s+(mot|hai|ba|bon|tu)\b",
                   lambda match: f"quy {QUARTER_WORDS[match[1]]}", fold(question))
    docs, years = find_periods(query)
    fiscal_year = re.search(r"\bnien do\s+(20\d{2})\s*[-–/]\s*(20\d{2})\b", query)
    if fiscal_year:
        return [f"FY{fiscal_year[1]}-{fiscal_year[2]}"]
    if docs:
        periods = [doc[:2].upper() + "/" + doc[3:] for doc in sorted(docs)]
        return periods + [f"FY{year}" for year in sorted(years)
                          if not any(period.endswith(f"/{year}") for period in periods)]
    quarters = [ROMAN.get(q) or int(q) for q in QUARTER_WITHOUT_YEAR.findall(query)]
    if quarters:
        latest_year = max(p.split("/")[1] for p in PERIODS if "/" in p)
        return [f"Q{q}/{year}" for year in (sorted(years) or [latest_year]) for q in dict.fromkeys(quarters)]
    return [f"FY{year}" for year in sorted(years)]


def result(answer, sources=None, notes=None):
    return {"answer": answer, "sources": sources or [], "notes": notes or [], "warnings": [],
            "unsupported_numbers": [], "charts": [], "clarify": None}


def lookup(companies, metric, period, basis="quy"):
    previous_period = f"Q{int(period[1]) - 1}{period[2:]}" if period[:2] in {"Q2", "Q3", "Q4"} else None
    derived = previous_period and basis == "quy" and metric.startswith("dong_tien_")
    rows = repository.facts(companies, period, metric, "luy_ke" if derived else basis)
    previous = {r[0]: r[1:] for r in repository.facts(companies, previous_period, metric, "luy_ke")} if derived else {}
    found = {row[0]: row[1:] for row in rows}
    label = METRICS[metric][0]
    timing = PERIODS[period]
    if period.startswith("Q") and metric not in {"tong_tai_san", "no_phai_tra", "von_chu_so_huu", "hang_ton_kho"}:
        timing += " (lũy kế)" if basis == "luy_ke" else " (riêng quý)"
    lines = [f"**{label} · {timing}**", ""]
    sources = []
    scopes = set()
    values = {}
    period_notes = []
    used_difference = False
    for code in companies:
        can_derive = (code in found and code in previous
                      and found[code][4] == previous[code][4]
                      and found[code][4] in {"riêng", "hợp nhất"} and code != "SBT")
        if code not in found or (derived and not can_derive):
            lines.append(f"- **{COMPANIES[code][0]} ({code}):** Chưa có số đã đối chiếu cho lựa chọn này.")
            aliases = (fold(label),)
            if metric == "tong_tai_san":
                aliases += ("tong cong tai san",)
            if metric == "loi_nhuan_truoc_thue":
                aliases += ("loi nhuan ke toan truoc thue",)
            if metric.startswith("dong_tien_"):
                aliases += (fold(label).replace("luu chuyen tien", "tien"),)
            statement = ("LCTT" if metric.startswith("dong_tien_") else
                         "CDKT" if metric in {"tong_tai_san", "no_phai_tra", "von_chu_so_huu", "hang_ton_kho"}
                         else "KQKD")
            excerpts = repository.excerpts(code, period, label, aliases, statement)
            for item in excerpts:
                lines.extend(("", item["text"], ""))
                sources.append(item["source"])
            if excerpts:
                period_notes.append("Các dòng trích từ PDF giữ nguyên cột và đơn vị gốc. Có thể có lỗi OCR. Mở trang nguồn để xác nhận số và kỳ.")
            else:
                sources.extend(report_sources(code, period))
            continue
        value, statement, page, url, scope, difference = found[code]
        if derived:
            base, base_statement, base_page, base_url, base_scope, _ = previous[code]
            value -= base
            used_difference = True
            sources.append(repository.source(code, previous_period, base_scope, base_page, base_url, base_statement))
        values[code] = value
        lines.append(f"- **{COMPANIES[code][0]} ({code}):** {fmt_vnd(value)} đồng ({scope}).")
        sources.append(repository.source(code, period, scope, page, url, statement))
        if scope in {"riêng", "hợp nhất"}:
            scopes.add(scope)
        if difference and basis == "quy":
            period_notes.append(f"{code}: số riêng quý công bố lệch {fmt_vnd(abs(difference))} đồng so với chênh lệch hai cột lũy kế. Kết quả dùng số riêng quý trên báo cáo.")
    if len(companies) == 2 and len(values) == 2:
        left, right = companies
        difference = values[left] - values[right]
        lines.append(f"\nChênh lệch {left} trừ {right}: **{fmt_vnd(difference)} đồng**.")
    notes = ["Hai báo cáo có phạm vi khác nhau. Xem phạm vi ghi bên cạnh từng số."] if len(scopes) > 1 else []
    if used_difference:
        notes.append("Dòng tiền riêng quý được tính bằng lũy kế đến cuối quý trừ lũy kế đến cuối quý trước.")
    notes.extend(dict.fromkeys(period_notes))
    return result("\n".join(lines), sources, notes)


def report_sources(company, period):
    return [repository.source(company, p, "PDF", 1, url, section)
            for p, url, section in repository.documents(company, period)]


def latest_period(companies):
    available = [{row[0] for row in repository.documents(code)} for code in companies]
    shared = set.intersection(*available)
    return next(p for p in reversed(PERIODS) if p in (shared or set.union(*available)))


def answer_question(question, companies, selected_period=None, context=None):
    # The UI appends Vinamilk's default period to legacy chat requests.
    question = question.split("\n(Nếu không nêu kỳ,", 1)[0]
    query = fold(question)
    periods = requested_periods(question)
    if companies == ["SBT"]:
        # AgriS công bố báo cáo năm theo niên độ kết thúc ngày 30/6.
        fiscal_periods = {"FY2025": "FY2024-2025", "FY2026": "FY2025-2026"}
        periods = [fiscal_periods.get(period, period) for period in periods]
    if not periods:
        inherited = requested_periods(context) if context else []
        periods = [selected_period or next((p for p in reversed(inherited) if p in PERIODS), None)
                   or latest_period(companies)]
    if matches(query, ("vinamilk", "vnm")):
        return result("Bạn có thể tra cứu Vinamilk ở màn hình Tra cứu số liệu. Hỏi riêng các doanh nghiệp khác trong ô chat.")
    if ("MCM" in companies and matches(query, ("bao cao hop nhat", "bctc hop nhat"))) or (
        "QNS" in companies and matches(query, ("bao cao rieng", "bctc rieng", "rieng le"))
    ):
        return result("Bộ dữ liệu có báo cáo riêng của MCM và báo cáo hợp nhất của QNS. Hãy chọn phạm vi phù hợp với nguồn hiện có.")
    answers = []
    missing = []
    for period in periods:
        if period in PERIODS:
            answers.append(answer_for_period(query, companies, period))
        else:
            missing.append(period.replace("FY", "năm "))
            if period.startswith("FY"):
                available = [p for p in PERIODS if p.endswith(f"/{period[2:]}")]
                if available:
                    answers.append(answer_for_period(f"{query} luy ke", companies, available[-1]))
    if missing:
        answers.append(result(f"Chưa có báo cáo cho {', '.join(missing)}."))
    return result("\n\n".join(a["answer"] for a in answers),
                  [s for a in answers for s in a["sources"]],
                  list(dict.fromkeys(n for a in answers for n in a["notes"])))


def answer_for_period(query, companies, period):
    if not any(repository.documents(code, period) for code in companies):
        return result(f"Chưa có báo cáo cho {PERIODS[period]} của {', '.join(companies)}.")
    if matches(query, ("thuyet minh",)):
        topic = re.sub(r"\b(?:q|quy)\s*([1-4]|iv|iii|ii|i)\b|\b20\d{2}\b", " ", query)
        for alias in ("thuyet minh", "cho toi", "cho biet", "bao cao tai chinh", "nam", "ve", "cua",
                      *(a for code, (_, names) in COMPANIES.items() for a in (code.lower(), *names))):
            topic = re.sub(rf"\b{re.escape(alias)}\b", " ", topic)
        excerpts = [item for code in companies for item in
                    (repository.notes(code, period, topic) or repository.excerpts(code, period, topic))]
        if not excerpts:
            return result("Chưa tìm được đoạn thuyết minh phù hợp.",
                          [s for code in companies for s in report_sources(code, period)])
        answer = "\n\n".join(f"**{item['source']['doc']} · trang {item['source']['page']}**\n\n{item['text']}" for item in excerpts)
        return result(answer, [item["source"] for item in excerpts], ["Trích đoạn OCR. Đối chiếu báo cáo gốc nếu cần dùng số liệu."])
    metrics = question_metrics(query)
    if not metrics:
        sources = [s for code in companies for s in report_sources(code, period)]
        return result(f"**Báo cáo {PERIODS[period]} · {', '.join(companies)}**\n\n"
                      "Mở nguồn bên dưới hoặc hỏi về một chỉ tiêu tài chính hay khoản mục thuyết minh.", sources)
    if matches(query, ("bien loi nhuan", "ty le", "tang truong", "bao nhieu phan tram", "vi sao", "tai sao",
                       "cong ty me", "co dong thieu so", "co dong khong kiem soat", "du bao", "du doan")) or "%" in query:
        return result("Luồng này hỗ trợ tra số tuyệt đối và so sánh hai doanh nghiệp cùng kỳ. Bạn có thể hỏi giá trị của một chỉ tiêu cụ thể.")
    basis = "luy_ke" if matches(query, ("luy ke", "6 thang", "9 thang")) else "quy"
    replies = [lookup(companies, metric, period, basis) for metric in METRICS if metric in metrics]
    sources = {s["url"]: s for reply in replies for s in reply["sources"]}
    notes = list(dict.fromkeys(n for reply in replies for n in reply["notes"]))
    return result("\n\n".join(reply["answer"] for reply in replies), list(sources.values()), notes)
