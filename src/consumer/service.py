"""Trả lời các câu hỏi có cấu trúc bằng số đã đối chiếu hoặc trích đoạn nguồn."""
import re
from difflib import SequenceMatcher

from src.consumer import assess, growth, insight, repository
from src.consumer.catalog import COMPANIES, METRICS, PERIODS, fold
from src.rag.text import ROMAN, find_periods, fmt_ty, fmt_vnd

QUARTER_WITHOUT_YEAR = re.compile(r"\b(?:q|quy)\s*([1-4]|iv|iii|ii|i)\b")
QUARTER_WORDS = {"mot": 1, "hai": 2, "ba": 3, "bon": 4, "tu": 4}


def matches(query, aliases):
    return any(re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", query) for alias in aliases)


def fuzzy_companies(query):
    """Tên công ty gõ sai một hai chữ ("habenco" thay vì "habeco"): so từng cụm từ của câu hỏi với tên gọi dài từ 5 ký tự."""
    words = query.split()
    found = []
    for code, (_, aliases) in COMPANIES.items():
        for alias in (a for a in aliases if len(a) >= 5):
            n = len(alias.split())
            if any(abs(len(chunk) - len(alias)) <= 2 and SequenceMatcher(None, chunk, alias).ratio() >= 0.88
                   for chunk in (" ".join(words[i:i + n]) for i in range(len(words) - n + 1))):
                found.append(code)
                break
    return found


ALL_WORDS = ("tat ca cac cong ty", "tat ca cong ty", "cac cong ty", "nhung cong ty", "cong ty nao", "moi cong ty",
             "tat ca cac doanh nghiep", "tat ca doanh nghiep", "cac doanh nghiep", "nhung doanh nghiep", "doanh nghiep nao",
             "tat ca cac ma", "cac ma co phieu", "toan nganh", "ca nganh", "trong nganh", "trong danh muc")
COMPARE_WORDS = ("so sanh", "so voi", "xep hang", "cao nhat", "thap nhat", "lon nhat", "nho nhat", "nhieu nhat", "it nhat",
                 "cao hon", "thap hon", "lon hon", "nho hon", "hon kem", "doi chieu")
SERIES_WORDS = ("qua cac quy", "cac quy", "theo quy", "tung quy", "theo tung quy", "qua cac ky", "cac ky", "dien bien", "xu huong")
RATIO_WORDS = ("bien loi nhuan", "bien lai", "bien gop", "bien rong", "ty suat loi nhuan", "ty le no", "he so no", "no tren von", "don bay")
VNM_WORDS = ("vinamilk", "vnm")


def asks_all(query):
    """Câu hỏi nói về cả danh mục ("tất cả các công ty", "công ty nào cao nhất"), không tính "các công ty con" của một doanh nghiệp."""
    return matches(query, ALL_WORDS) and not matches(query, ("cong ty con", "cong ty lien ket", "cong ty me"))


def vinamilk_assessment(question):
    """Chủ đề ("profit"/"leverage"/"general") nếu đây là câu đánh giá về Vinamilk (không nêu công ty khác, không hỏi giá cổ phiếu), ngược lại None."""
    query = fold(question)
    if matches(query, OFF_TOPIC_WORDS):
        return None
    return assess.asked_assessment(query)


def question_companies(question):
    query = fold(question)
    exact = [code for code, (_, aliases) in COMPANIES.items() if matches(query, (code.lower(), *aliases))]
    return exact or fuzzy_companies(query) or (list(COMPANIES) if asks_all(query) else [])


OFF_TOPIC_WORDS = ("gia co phieu", "thi gia", "gia muc tieu", "von hoa", "nen mua", "nen ban", "co nen dau tu", "nen dau tu",
                   "tu van dau tu", "khuyen nghi", "chung khoan hom nay", "co phieu nao")
REPORT_WORDS = ("lai", "lo", "loi nhuan", "doanh thu", "tai chinh", "bao cao", "bctc", "tai san", "von", "no", "dong tien",
                "hang ton kho", "chi phi", "tom tat", "tinh hinh", "ket qua kinh doanh")


def out_of_scope(question, follow_up=False):
    """Câu hỏi về công ty trong danh mục nhưng nằm ngoài báo cáo tài chính (giá cổ phiếu, tư vấn đầu tư).

    Từ khóa ngoài phạm vi luôn bị từ chối. Câu có dấu hiệu hỏi báo cáo (chỉ tiêu, kỳ, so sánh, lãi lỗ...) hoặc là câu hỏi
    nối tiếp thì đi thẳng vào tra cứu; còn lại mới hỏi bộ phân loại ý định."""
    query = fold(question)
    if matches(query, OFF_TOPIC_WORDS):
        return True
    if assess.asked_assessment(query):
        return False
    if follow_up or question_metrics(query) or requested_periods(question) or matches(
            query, (*REPORT_WORDS, *COMPARE_WORDS, *SERIES_WORDS, *RATIO_WORDS, "thuyet minh")):
        return False
    from src.agent.agent import VinamilkAgent
    return VinamilkAgent._out_of_scope(question)


CATALOG_QUESTION = re.compile(
    r"\b(bao nhieu|may|nhung|cac|danh sach|liet ke)\s+(cong ty|doanh nghiep|ma)\b(?!\s+con)"
    r"|\b(cong ty|doanh nghiep|ma) nao\b.*\b(du lieu|danh muc|ho tro|tra cuu|hoi duoc|co the hoi)\b"
    r"|\b(du lieu|danh muc)\b.*\b(gom|co|bao gom)\b.*\b(cong ty|doanh nghiep|ma|nhung gi|gi)\b"
    r"|\bban (co|biet) (du lieu|thong tin) (gi|ve gi|cua ai|nhung gi)\b"
    r"|\bpham vi du lieu\b")


def catalog_question(question):
    """Câu hỏi về chính bộ dữ liệu ("có bao nhiêu công ty trong dữ liệu của bạn", "những công ty nào"), không hỏi số liệu."""
    question = question.split("\n(Nếu không nêu kỳ,", 1)[0]          # giao diện nối thêm kỳ mặc định; đó không phải kỳ người dùng hỏi
    query = fold(question)
    if (question_metrics(query) or requested_periods(question) or matches(query, COMPARE_WORDS + SERIES_WORDS + RATIO_WORDS)
            or matches(query, ("cong ty con", "cong ty lien ket", "lai", "lo", "loi nhuan", "doanh thu", "no", "tai san", "von", "dong tien"))):
        return False
    return bool(CATALOG_QUESTION.search(query))


def catalog_answer():
    """Danh mục 12 công ty: Vinamilk (trợ lý Gemini, 6 kỳ đã đối chiếu) và 11 công ty hàng tiêu dùng (tra cứu theo quy tắc)."""
    vnm_periods = list(VNM_QUARTERS)
    lines = [f"Dữ liệu hiện có báo cáo tài chính của **{len(COMPANIES) + 1} công ty**: Vinamilk và {len(COMPANIES)} công ty hàng tiêu dùng khác.", "",
             "| # | Công ty | Mã | Các kỳ có báo cáo |", "|---:|---|---|---|",
             f"| 1 | Vinamilk | VNM | {vnm_periods[0]} đến {vnm_periods[-1]} (báo cáo hợp nhất, {len(vnm_periods)} kỳ) |"]
    for i, (code, (name, _)) in enumerate(sorted(COMPANIES.items(), key=lambda kv: kv[1][0]), 2):
        have = {row[0] for row in repository.documents(code)}
        quarters = [p for p in PERIODS if p in have and p.startswith("Q")]
        years = [PERIODS[p] for p in PERIODS if p in have and p.startswith("FY")]
        text = f"{quarters[0]} đến {quarters[-1]}" if len(quarters) > 1 else (quarters[0] if quarters else "")
        if years:
            text += ("; " if text else "") + ", ".join(years)
        lines.append(f"| {i} | {name} | {code} | {text} |")
    lines += ["", "Bạn có thể hỏi số liệu của từng công ty (ví dụ \"doanh thu của KIDO quý 2/2026\"), xem theo quý "
              "(\"lợi nhuận Sabeco qua các quý\") hoặc so sánh (\"so sánh Vinamilk với Masan Consumer năm 2025\")."]
    notes = ["Vinamilk có số liệu đã đối chiếu đầy đủ cho cả 6 kỳ; số của 11 công ty còn lại được trích tự động từ PDF và chỉ nhận khi thỏa "
             "đẳng thức kế toán, nên một số kỳ hoặc chỉ tiêu có thể chưa có."]
    return result("\n".join(lines), [], notes)


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


def scope_text(scope):
    """"báo cáo hợp nhất", "báo cáo riêng"; khi báo cáo không ghi rõ phạm vi thì nói vậy thay vì "báo cáo theo báo cáo"."""
    return f"báo cáo {scope}" if scope in {"riêng", "hợp nhất"} else "phạm vi theo báo cáo gốc"


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
            pages = sorted({item["source"]["page"] for item in excerpts})
            if pages:                                      # không in chữ OCR chưa đối chiếu (dễ bị đọc nhầm là số quý): chỉ chỉ trang để người dùng mở PDF xem
                lines[-1] += f" Trang có dòng liên quan: {', '.join(map(str, pages))} của báo cáo gốc (mở phần Nguồn để xác nhận đúng kỳ và đúng cột)."
                sources.extend(item["source"] for item in excerpts)
                period_notes.append("Số chưa đối chiếu được nên không hiển thị lại chữ OCR; mở trang nguồn để xem số trên báo cáo gốc.")
            else:
                lines[-1] += " Mở báo cáo gốc ở phần Nguồn."
                sources.extend(report_sources(code, period))
            continue
        value, statement, page, url, scope, difference = found[code]
        if derived:
            base, base_statement, base_page, base_url, base_scope, _ = previous[code]
            value -= base
            used_difference = True
            sources.append(repository.source(code, previous_period, base_scope, base_page, base_url, base_statement))
        values[code] = value
        lines.append(f"- **{COMPANIES[code][0]} ({code}):** {fmt_ty(value)} tỷ đồng ({fmt_vnd(value)} đồng), {scope_text(scope)}. "
                     f"Nguồn: {STATEMENT_NAMES.get(statement, statement)}, trang {page}.")
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


SUMMARY_METRICS = ("doanh_thu_thuan", "loi_nhuan_gop", "loi_nhuan_sau_thue", "tong_tai_san", "no_phai_tra", "von_chu_so_huu")
STATEMENT_NAMES = {"KQKD": "Báo cáo kết quả kinh doanh", "CDKT": "Bảng cân đối kế toán", "LCTT": "Báo cáo lưu chuyển tiền tệ"}


def summary(companies, period):
    """Câu hỏi chung ("quý 2 năm 2025 của MCM"): bảng các chỉ tiêu chính đã đối chiếu, mỗi số kèm báo cáo và trang PDF làm minh chứng."""
    rows = repository.fact_rows(companies, [period], list(SUMMARY_METRICS), "quy")
    lines, sources, notes = [], {}, []
    for code in companies:
        mine = {metric: (value, statement, page, url, scope) for c, _, metric, value, statement, page, url, scope, _ in rows if c == code}
        name = f"{COMPANIES[code][0]} ({code})"
        if not mine:                                       # chưa có số đối chiếu: chỉ chỉ trang chứa dòng tương ứng, không in chữ OCR chưa đối chiếu
            lines += [f"**{name} · {PERIODS[period]}** — chưa có số đã đối chiếu cho kỳ này.", ""]
            found = False
            for metric, statement, extra in (("doanh_thu_thuan", "KQKD", ()), ("loi_nhuan_sau_thue", "KQKD", ()), ("tong_tai_san", "CDKT", ("tong cong tai san",))):
                label = METRICS[metric][0]
                items = repository.excerpts(code, period, label, (fold(label), *extra), statement)
                if items:
                    lines.append(f"- {label}: trang có dòng liên quan {', '.join(str(p) for p in sorted({i['source']['page'] for i in items}))} (mở phần Nguồn để xác nhận).")
                    sources.update({i["source"]["url"]: i["source"] for i in items})
                    found = True
            if found:
                lines += ["", "Các số trên chưa đối chiếu được nên không hiển thị lại chữ OCR; bấm vào Nguồn để mở đúng trang báo cáo gốc."]
            else:
                lines.append("Chưa tìm được dòng số liệu phù hợp. Mở báo cáo gốc ở phần Nguồn.")
                sources.update({s["url"]: s for s in report_sources(code, period)})
            lines.append("")
            continue
        scope = next(iter(mine.values()))[4]
        lines += [f"**Tóm tắt báo cáo {PERIODS[period]} · {name}** ({scope_text(scope)})", "",
                  "| Chỉ tiêu | Giá trị (tỷ đồng) | Minh chứng |", "|---|---:|---|"]
        for metric in SUMMARY_METRICS:
            if metric in mine:
                value, statement, page, url, scope = mine[metric]
                lines.append(f"| {METRICS[metric][0]} | {fmt_ty(value)} | {STATEMENT_NAMES.get(statement, statement)}, trang {page} |")
                s = repository.source(code, period, scope, page, url, statement)
                sources[s["url"]] = s
        lines.append("")
    if any(row[2] in SUMMARY_METRICS for row in rows):
        notes.append("Số trong bảng lấy từ báo cáo PDF của công ty, đã đối chiếu đẳng thức kế toán; bấm vào Nguồn để mở đúng trang. "
                     "Hỏi riêng từng chỉ tiêu (ví dụ dòng tiền kinh doanh, hàng tồn kho) hoặc \"thuyết minh về …\" để xem thêm.")
    return result("\n".join(lines).strip(), list(sources.values()), list(dict.fromkeys(notes)))


COMPARE_METRICS = ("doanh_thu_thuan", "loi_nhuan_gop", "loi_nhuan_truoc_thue", "loi_nhuan_sau_thue", "tong_tai_san", "no_phai_tra", "von_chu_so_huu")
VNM_QUARTERS = ("Q1/2025", "Q2/2025", "Q3/2025", "Q4/2025", "Q1/2026", "Q2/2026")
VNM_METRICS = {"dong_tien_kinh_doanh": "luu_chuyen_hdkd", "dong_tien_dau_tu": "luu_chuyen_dau_tu", "dong_tien_tai_chinh": "luu_chuyen_tai_chinh"}
POINT_METRICS = {"tong_tai_san", "no_phai_tra", "von_chu_so_huu", "hang_ton_kho"}
WIDE_LIMIT = 4                                             # tới 4 bên: mỗi bên một cột; nhiều hơn: mỗi công ty một dòng, xếp hạng


def _pct(x):
    return f"{x * 100:.1f}%".replace(".", ",")


def _times(a, b):
    return f"{a / b:.1f}".replace(".", ",") if b else "—"


def entity_name(code):
    return "Vinamilk" if code == "VNM" else COMPANIES[code][0]


def vinamilk_values(period, metrics=COMPARE_METRICS, basis="quy"):
    """Số Vinamilk (financials.duckdb) cho một kỳ của danh mục công ty; FY2025 là số lũy kế cả năm (quý 4/2025)."""
    from src.tools.registry import call_tool
    from src.web.sources import source_links
    if period == "FY2025":
        view = ("Q4/2025", "luy_ke")
    elif period in VNM_QUARTERS:
        view = (period, basis)
    else:
        return {}, []
    values, sources = {}, []
    for metric in metrics:
        key = VNM_METRICS.get(metric, metric)
        res = call_tool("get_metric", {"metric": key, "period": view[0], "basis": view[1]})
        if res.get("ok") and res.get("metric", key) == key and isinstance(res.get("value"), (int, float)):
            values[metric] = res["value"]
            sources.extend(res.get("sources") or [])
    return values, source_links(sources)


def company_values(code, period, metrics=COMPARE_METRICS, basis="quy"):
    rows = repository.fact_rows([code], [period], list(metrics), basis)
    if re.fullmatch(r"FY20\d{2}", period) and code != "SBT":      # SBT: năm tài chính kết thúc 30/6, quý 4 không phải cuối năm
        # Số cả năm thiếu trong báo cáo năm (hoặc chưa có báo cáo năm): lấy cột lũy kế và số cuối kỳ của báo cáo quý 4 cùng năm.
        have = {row[2] for row in rows}
        rows += [row for row in repository.fact_rows([code], [f"Q4/{period[2:]}"], [m for m in metrics if m not in have], "luy_ke")]
    values = {metric: value for _, _, metric, value, *_ in rows}
    sources = [repository.source(code, p, scope, page, url, statement) for _, p, _, _, statement, page, url, scope, _ in rows]
    scopes = [row[7] for row in rows]
    return values, sources, max(set(scopes), key=scopes.count) if scopes else None


def entity_values(code, period, metrics, basis="quy"):
    if code == "VNM":
        values, sources = vinamilk_values(period, metrics, basis)
        return values, sources, "hợp nhất" if values else None
    return company_values(code, period, metrics, basis)


def _ratios(v):
    return {key: value for key in insight.RATIOS if (value := insight.ratio_of(v, key)) is not None}


def compare(question, companies, with_vinamilk, basis="quy"):
    """So sánh các doanh nghiệp (có thể gồm Vinamilk) theo kỳ chung: bảng số, tỷ số và nhận xét ai lãi hơn, ai lớn hơn.

    Tới 4 bên thì mỗi bên một cột; nhiều hơn thì mỗi công ty một dòng, xếp theo chỉ tiêu được hỏi."""
    query = fold(question)
    codes = (["VNM"] if with_vinamilk else []) + list(companies)
    asked_metrics = [m for m in METRICS if m in question_metrics(query)]
    asked_ratios = insight.asked_ratios(query)                  # "biên lợi nhuận gộp cao nhất" xếp theo tỷ số, không theo lợi nhuận gộp tuyệt đối
    wide = len(codes) <= WIDE_LIMIT
    metrics = list(dict.fromkeys([*COMPARE_METRICS, *asked_metrics] if wide else [*asked_metrics, *COMPARE_METRICS]))
    key = asked_metrics[0] if asked_metrics else "loi_nhuan_sau_thue" if matches(query, ("loi nhuan", "lai", "lo")) else "doanh_thu_thuan"
    label = insight.RATIOS[asked_ratios[0]]["name"] if asked_ratios else METRICS[key][0]

    def usable(values):
        return insight.ratio_of(values, asked_ratios[0]) is not None if asked_ratios else key in values

    requested = requested_periods(question)
    asked = [p for p in requested if p in PERIODS][:2]
    if requested and not asked:
        return result(f"Chưa có báo cáo cho {', '.join(p.replace('FY', 'năm ') for p in requested)}.")
    data = {}

    def load(period):
        if period not in data:
            data[period] = {code: entity_values(code, period, metrics, basis) for code in codes}
        return data[period]

    def have(period):
        return [code for code in codes if usable(load(period)[code][0])]

    if asked:
        chosen = asked
    else:                                                  # không nêu kỳ: lấy kỳ có nhiều bên có số nhất, ưu tiên kỳ mới hơn
        order = list(reversed(PERIODS))
        best_period = max(order, key=lambda p: (len(have(p)), -order.index(p)))
        chosen = [best_period] if len(have(best_period)) >= 2 else []
    if not chosen:
        return result(f"Chưa có kỳ nào mà ít nhất hai bên cùng có số {label.lower()} đã đối chiếu, nên chưa so sánh được. "
                      "Bạn thử nêu rõ kỳ, ví dụ năm 2025 hoặc Q1/2026.")
    texts, sources, notes = [], {}, []
    for period in chosen:
        entities, missing, missing_codes = [], [], []      # (tên, số liệu, phạm vi)
        for code in codes:
            values, srcs, scope = load(period)[code]
            if usable(values):
                entities.append((entity_name(code), values, scope))
                for s in srcs:
                    sources[(s.get("doc"), s.get("page"))] = s
            else:
                missing.append(entity_name(code))
                missing_codes.append(code)
                if code != "VNM":
                    for s in report_sources(code, period)[:1]:
                        sources[(s["doc"], s["page"])] = s
        if missing:
            notes.append(f"Chưa có số đã đối chiếu cho {PERIODS[period]}: {', '.join(missing)}. Mở báo cáo gốc ở phần Nguồn để xem.")
        if len(entities) < 2:
            only = ""
            if entities and asked_ratios:
                only = f" Hiện chỉ có {entities[0][0]}: {label.lower()} {insight.pct(insight.ratio_of(entities[0][1], asked_ratios[0]))}."
            elif entities:
                only = f" Hiện chỉ có {entities[0][0]}: {label.lower()} {fmt_ty(entities[0][1][key])} tỷ đồng."
            texts.append(f"**{PERIODS[period]}**: chưa đủ hai bên có số đã đối chiếu để so sánh.{only}")
            continue
        if asked_ratios and not wide:
            text = insight.ratio_ranking(PERIODS[period], entities, asked_ratios, query)
        elif wide:
            text = _comparison_text(period, entities, metrics, asked_ratios)
        else:
            text = _ranking_text(period, entities, metrics, key, query)
        if missing_codes:
            text += "\n\n" + insight.missing_line(missing_codes, period, entity_name)
        texts.append(text)
        if len({scope for _, _, scope in entities}) > 1:
            notes.append("Phạm vi báo cáo khác nhau (hợp nhất, riêng lẻ hoặc theo báo cáo), nên so sánh chỉ mang tính tham khảo.")
    if not asked:
        notes.append(f"Câu hỏi không nêu kỳ nên dùng {PERIODS[chosen[0]]}, kỳ có nhiều doanh nghiệp có số đã đối chiếu nhất.")
    return result("\n\n".join(texts), list(sources.values()), list(dict.fromkeys(notes)))


def _ranking_text(period, entities, metrics, key, query):
    """Nhiều doanh nghiệp: mỗi công ty một dòng, xếp theo chỉ tiêu được hỏi."""
    columns = [m for m in dict.fromkeys([key, *metrics]) if m != "loi_nhuan_truoc_thue" or m == key][:6]
    lowest_first = matches(query, ("thap nhat", "nho nhat", "it nhat"))
    ranked = sorted(entities, key=lambda e: e[1][key], reverse=not lowest_first)
    label = METRICS[key][0]
    lines = [f"**So sánh {len(ranked)} doanh nghiệp · {PERIODS[period]}** (tỷ đồng, xếp theo {label.lower()} {'tăng' if lowest_first else 'giảm'} dần)", "",
             "| # | Doanh nghiệp | " + " | ".join(METRICS[m][0] for m in columns) + " | Biên LN ròng |",
             "|---:|---|" + "---:|" * (len(columns) + 1)]
    for i, (name, v, _) in enumerate(ranked, 1):
        r = _ratios(v)
        lines.append(f"| {i} | {name} | " + " | ".join(fmt_ty(v[m]) if m in v else "—" for m in columns)
                     + f" | {_pct(r['bien_rong']) if 'bien_rong' in r else '—'} |")
    by_value = sorted(entities, key=lambda e: e[1][key])
    low, high = by_value[0], by_value[-1]
    notes = ["", "**Nhận xét**", "",
             f"- **{label} cao nhất:** {high[0]} ({fmt_ty(high[1][key])} tỷ đồng); **thấp nhất:** {low[0]} ({fmt_ty(low[1][key])} tỷ đồng)."]
    profits = [(n, v["loi_nhuan_sau_thue"]) for n, v, _ in entities if "loi_nhuan_sau_thue" in v]
    if len(profits) > 1 and key != "loi_nhuan_sau_thue":
        top = max(profits, key=lambda x: x[1])
        notes.append(f"- **Lợi nhuận sau thuế cao nhất:** {top[0]} ({fmt_ty(top[1])} tỷ đồng).")
    losses = [n for n, p in profits if p < 0]
    if losses:
        notes.append(f"- **Đang lỗ sau thuế:** {', '.join(losses)}.")
    margins = [(n, _ratios(v)["bien_rong"]) for n, v, _ in entities if "bien_rong" in _ratios(v)]
    if len(margins) > 1:
        top = max(margins, key=lambda x: x[1])
        notes.append(f"- **Biên lợi nhuận ròng cao nhất:** {top[0]} ({_pct(top[1])}).")
    return "\n".join(lines + notes)


def series(companies, with_vinamilk, metrics, basis="quy"):
    """Một chỉ tiêu qua các quý: mỗi quý một dòng, mỗi doanh nghiệp một cột."""
    codes = (["VNM"] if with_vinamilk else []) + list(companies)
    quarters = [p for p in PERIODS if p.startswith("Q")]
    texts, sources, empty, mixed = [], {}, [], {}
    shown_codes, off_scope = [], set()                         # off_scope: (mã, kỳ) là báo cáo riêng trong chuỗi chủ yếu hợp nhất, không vẽ lên biểu đồ
    for metric in metrics:
        table = {p: {code: entity_values(code, p, [metric], basis) for code in codes} for p in quarters}
        shown = [code for code in codes if any(metric in table[p][code][0] for p in quarters)]
        for code in shown:
            scopes = {p: table[p][code][2] for p in quarters if metric in table[p][code][0]}
            separate = [p for p, s in scopes.items() if s == "riêng"]
            # Công ty có báo cáo hợp nhất nhưng vài quý số lấy từ báo cáo riêng (BHN Q1/2025): không cộng, so sánh trực tiếp được.
            if separate and len(separate) < len(scopes) and code != "VNM" and repository.has_consolidated(code):
                mixed[code] = f"{entity_name(code)}: {', '.join(separate)} là báo cáo riêng"
                off_scope.update((code, p) for p in separate)
        shown_codes += [code for code in shown if code not in shown_codes]
        empty += [entity_name(code) for code in codes if code not in shown]
        if not shown:
            continue
        timing = "" if metric in POINT_METRICS else " (lũy kế)" if basis == "luy_ke" else " (riêng quý)"
        lines = [f"**{METRICS[metric][0]}{timing} qua các quý** (tỷ đồng)", "",
                 "| Kỳ | " + " | ".join(entity_name(c) for c in shown) + " |", "|---|" + "---:|" * len(shown)]
        for p in quarters:
            if not any(metric in table[p][c][0] for c in shown):
                continue
            lines.append(f"| {p} | " + " | ".join(fmt_ty(table[p][c][0][metric]) if metric in table[p][c][0] else "—" for c in shown) + " |")
            for c in shown:
                for s in table[p][c][1]:
                    sources[(s.get("doc"), s.get("page"))] = s
        texts.append("\n".join(lines))
    notes = ["Kỳ không có trong bảng hoặc ô có dấu — là kỳ chưa có số đã đối chiếu."] if texts else []
    if mixed:
        notes.append("Phạm vi báo cáo không đồng nhất giữa các quý (" + "; ".join(mixed.values())
                     + ", các quý còn lại không phải báo cáo riêng), nên không cộng hay so sánh trực tiếp các quý này.")
    if empty:
        notes.append(f"Chưa có số đã đối chiếu theo quý của: {', '.join(dict.fromkeys(empty))}.")
    if not texts:
        return result("Chưa có số đã đối chiếu theo quý cho lựa chọn này.", [], notes)
    reply = result("\n\n".join(texts), list(sources.values()), notes)
    reply["charts"] = _series_charts(shown_codes or codes, list(metrics), basis, off_scope)
    return reply


def _series_charts(codes, metrics, basis, off_scope=()):
    """Biểu đồ xu hướng cho khung chat (cùng khối dữ liệu với màn hình Phân tích); bảng đã có trong câu trả lời nên không in lại.

    Điểm thuộc `off_scope` (báo cáo riêng lẫn trong chuỗi hợp nhất, vd Habeco Q1/2025) bị bỏ khỏi đường vẽ để không tạo bước nhảy giả."""
    try:
        from src.consumer import analytics
        from src.tools.registry import analyst
        blocks = analytics.chart(list(codes), [m for m in metrics if m in METRICS], "series", None, basis, "yoy", analyst())
    except Exception:                                           # noqa: BLE001 - biểu đồ chỉ là phần thêm, không được làm hỏng câu trả lời
        return []
    for block in blocks:
        block["no_table"] = True
        for row in block.get("rows", []):
            for code in {c for c, _ in off_scope}:
                if str(row.get("label", "")).endswith(f"({code})"):
                    for cell in row.get("cells", []):
                        if (code, cell.get("period")) in off_scope:
                            cell["value"] = None
    return blocks


def ratio_answer(companies, period, basis="quy"):
    """Biên lợi nhuận và mức nợ của từng doanh nghiệp, tính từ số đã đối chiếu; ghi rõ số dùng để tính."""
    lines = [f"**Chỉ số tài chính · {PERIODS[period]}**", "",
             "| Doanh nghiệp | Biên lợi nhuận gộp | Biên lợi nhuận ròng | Nợ phải trả / vốn chủ sở hữu |", "|---|---:|---:|---:|"]
    used, sources, missing = [], {}, []
    for code in companies:
        values, srcs, _ = company_values(code, period, COMPARE_METRICS, basis)
        r = _ratios(values)
        if not r:
            missing.append(COMPANIES[code][0])
            for s in report_sources(code, period)[:1]:
                sources[(s["doc"], s["page"])] = s
            continue
        lines.append(f"| {COMPANIES[code][0]} ({code}) | " + " | ".join(_pct(r[k]) if k in r else "—" for k in ("bien_gop", "bien_rong", "no_von")) + " |")
        used.append(f"- **{COMPANIES[code][0]}** (tỷ đồng): " + "; ".join(
            f"{METRICS[m][0].lower()} {fmt_ty(values[m])}" for m in ("doanh_thu_thuan", "loi_nhuan_gop", "loi_nhuan_sau_thue", "no_phai_tra", "von_chu_so_huu") if m in values) + ".")
        for s in srcs:
            sources[(s["doc"], s["page"])] = s
    if not used:
        return result(f"Chưa đủ số đã đối chiếu của {', '.join(missing)} cho {PERIODS[period]} để tính biên lợi nhuận hay mức nợ. Mở báo cáo gốc ở phần Nguồn để xem.",
                      list(sources.values()))
    notes = ["Biên lợi nhuận gộp = lợi nhuận gộp / doanh thu thuần; biên lợi nhuận ròng = lợi nhuận sau thuế / doanh thu thuần."]
    if missing:
        notes.append(f"Chưa đủ số đã đối chiếu để tính cho {PERIODS[period]}: {', '.join(missing)}.")
    return result("\n".join([*lines, "", "**Số dùng để tính**", "", *used]), list(sources.values()), notes)


def _comparison_text(period, entities, metrics=COMPARE_METRICS, asked_ratios=()):
    names = [n for n, _, _ in entities]
    label = {m: METRICS[m][0] for m in metrics}
    ratios = {name: _ratios(v) for name, v, _ in entities}

    def best(getter, highest=True):
        have = [(n, getter(n)) for n in names if getter(n) is not None]
        return (max if highest else min)(have, key=lambda x: x[1]) if len(have) > 1 else None

    lines = [f"**So sánh {PERIODS[period]}: {', '.join(names[:-1])} và {names[-1]}**", "",
             "| Chỉ tiêu | " + " | ".join(names) + " | Dẫn đầu |", "|---|" + "---:|" * len(names) + "---|"]
    for m in metrics:
        top = best(lambda n, m=m: dict((e[0], e[1]) for e in entities)[n].get(m))
        cells = [fmt_ty(v[m]) if m in v else "—" for _, v, _ in entities]
        lines.append(f"| {label[m]} (tỷ đồng) | " + " | ".join(cells) + f" | {top[0] if top else '—'} |")
    for key, spec in insight.RATIOS.items():
        highest = spec["better"] == "high"
        top = best(lambda n, k=key: ratios[n].get(k), highest)
        if not any(key in ratios[n] for n in names):
            continue
        cells = [_pct(ratios[n][key]) if key in ratios[n] else "—" for n in names]
        lines.append(f"| {spec['name']} | " + " | ".join(cells) + f" | {top[0] + ('' if highest else ' (nợ thấp nhất)') if top else '—'} |")

    values = {n: v for n, v, _ in entities}
    notes = ["", "**Nhận xét**", "", *insight.focus_lines(entities, list(asked_ratios))]
    top = best(lambda n: values[n].get("doanh_thu_thuan"))
    if top:
        others = sorted(((n, values[n]["doanh_thu_thuan"]) for n in names if n != top[0] and values[n].get("doanh_thu_thuan")), key=lambda x: -x[1])
        notes.append(f"- **Doanh thu:** {top[0]} cao nhất với {fmt_ty(top[1])} tỷ đồng, " +
                     "; ".join(f"gấp {_times(top[1], v)} lần {n} ({fmt_ty(v)} tỷ đồng)" for n, v in others) + ".")
    profits = [(n, values[n]["loi_nhuan_sau_thue"]) for n in names if "loi_nhuan_sau_thue" in values[n]]
    if profits:
        status = "; ".join(f"{n} {'lãi' if p > 0 else 'lỗ' if p < 0 else 'hòa vốn'} {fmt_ty(abs(p))} tỷ đồng" for n, p in profits)
        notes.append(f"- **Lãi, lỗ sau thuế:** {status}.")
        if len(profits) > 1:
            top_p = max(profits, key=lambda x: x[1])
            notes.append(f"- **Lợi nhuận sau thuế cao nhất:** {top_p[0]}.")
    top_m = best(lambda n: ratios[n].get("bien_rong"))
    if top_m:
        notes.append(f"- **Hiệu quả:** biên lợi nhuận ròng cao nhất là {top_m[0]} ({_pct(top_m[1])}); doanh thu lớn hơn chưa chắc lãi trên mỗi đồng doanh thu cao hơn.")
    top_a = best(lambda n: values[n].get("tong_tai_san"))
    if top_a:
        notes.append(f"- **Quy mô tài sản:** {top_a[0]} lớn nhất ({fmt_ty(top_a[1])} tỷ đồng).")
    low_d = best(lambda n: ratios[n].get("no_von"), highest=False)
    if low_d:
        notes.append(f"- **Mức nợ:** {low_d[0]} có tỷ lệ nợ trên vốn chủ thấp nhất ({_pct(low_d[1])}).")
    return "\n".join(lines + notes)


def _quarters():
    return [p for p in reversed(PERIODS) if p.startswith("Q")]


def _comparison_periods(query, requested, codes, metrics, basis):
    """(kỳ gốc, kỳ hiện tại, cách so sánh, ghi chú, hàm nạp số) cho câu hỏi tăng trưởng / vì sao."""
    cache = {}

    def values(code, period):
        if (code, period) not in cache:
            cache[code, period] = entity_values(code, period, metrics, basis)
        return cache[code, period]

    def both(base, cur):
        return sum(1 for code in codes if any(m in values(code, base)[0] and m in values(code, cur)[0] for m in metrics))

    def best_current():
        scored = [(both(growth.last_year(p), p), -i, p) for i, p in enumerate(_quarters()) if growth.last_year(p) in PERIODS]
        scored = [x for x in scored if x[0] > 0]
        return max(scored)[2] if scored else None

    base, cur, kind, guessed = growth.pick_periods(query, requested, best_current)
    notes = []
    if cur is None or base not in PERIODS or cur not in PERIODS:
        return base, cur, kind, notes, values
    if guessed and kind == "yoy" and both(base, cur) == 0:
        alt = growth.prev_quarter(cur)                          # không nói rõ cách so sánh mà cùng kỳ năm trước chưa có số: thử quý liền trước
        if alt in PERIODS and both(alt, cur) > 0:
            notes.append(f"Chưa có số {base} nên so với quý liền trước ({alt}).")
            return alt, cur, "qoq", notes, values
    if guessed and kind == "yoy":
        notes.append('Câu hỏi không nêu cách so sánh nên mặc định so với cùng kỳ năm trước; hỏi "so với quý trước" để đổi.')
    return base, cur, kind, notes, values


def _same_scope(code, a, b):
    """Hai kỳ so sánh được khi cùng phạm vi. Báo cáo riêng không so với báo cáo hợp nhất hay báo cáo không ghi rõ phạm vi (vd Habeco Q1/2025 riêng),
    trừ công ty không có báo cáo hợp nhất nào (vd Mộc Châu Milk): khi đó mọi kỳ đều là báo cáo riêng."""
    if a == b or "riêng" not in (a, b):
        return True
    return code != "VNM" and not repository.has_consolidated(code)


def growth_answer(question, companies, with_vinamilk, basis="quy"):
    """Tăng giảm (tuyệt đối và %) của chỉ tiêu giữa hai kỳ, cho một hay nhiều doanh nghiệp (kể cả Vinamilk)."""
    query = fold(question)
    codes = (["VNM"] if with_vinamilk else []) + list(companies)
    metrics = [m for m in METRICS if m in question_metrics(query)] or list(growth.DEFAULT_METRICS)
    requested = requested_periods(question)
    if requested and all(p.startswith("FY") for p in requested):
        return result("Tăng trưởng cả năm chưa tính được vì báo cáo năm trong dữ liệu chỉ có số của năm hiện tại. "
                      'Bạn hỏi theo quý, ví dụ "doanh thu của KIDO quý 2/2026 so với cùng kỳ năm trước".')
    base, cur, kind, notes, values = _comparison_periods(query, requested, codes, metrics, basis)
    if cur is None or base not in PERIODS or cur not in PERIODS:
        gone = base if base and base not in PERIODS else cur
        return result(f"Chưa có số của {gone or 'kỳ được hỏi'} để so sánh. Các công ty có quý từ Q1/2025 đến Q3/2026 (tùy công ty); "
                      "bạn thử nêu quý có số, ví dụ Q2/2026 so với cùng kỳ năm trước.")
    texts, sources, lacking = [], {}, {}
    for metric in metrics:
        rows = []
        for code in codes:
            vb, sb, scb = values(code, base)
            vc, sc, scc = values(code, cur)
            if metric in vb and metric in vc:
                rows.append((entity_name(code), vb[metric], vc[metric], _same_scope(code, scb, scc)))
                for src in (*sb, *sc):
                    sources[(src.get("doc"), src.get("page"))] = src
            else:
                lacking.setdefault(code, []).append(PERIODS[base] if metric not in vb else PERIODS[cur])
        if not rows:
            continue
        rows.sort(key=lambda r: (r[3], ((r[2] - r[1]) / r[1]) if r[1] > 0 else float("-inf")), reverse=True)      # so sánh được trước, rồi theo % giảm dần
        texts.append(growth.growth_text(metric, PERIODS[base], PERIODS[cur], rows, kind))
        if any(not r[3] for r in rows):
            notes.append("Một số doanh nghiệp có hai kỳ khác phạm vi báo cáo (hợp nhất/riêng) nên không tính phần trăm.")
    if not texts:
        return result(f"Chưa có số đã đối chiếu của {PERIODS[base]} và {PERIODS[cur]} cho các doanh nghiệp được hỏi, nên chưa tính được tăng trưởng.",
                      [s for code in codes if code != "VNM" for s in report_sources(code, cur)[:1]], notes)
    if lacking:
        texts.append("**Chưa so sánh được:** " + "; ".join(f"{entity_name(code)} (thiếu số {', '.join(dict.fromkeys(ps))})" for code, ps in lacking.items()) + ".")
    return result("\n\n".join(texts), list(sources.values()), list(dict.fromkeys(notes)))


def why_answer(question, companies, with_vinamilk, basis="quy"):
    """"Vì sao lợi nhuận đổi": cầu nối lợi nhuận giữa hai kỳ (doanh thu, biên gộp, chi phí khác, thuế), tổng đúng bằng chênh lệch."""
    query = fold(question)
    codes = (["VNM"] if with_vinamilk else []) + list(companies)
    asked = question_metrics(query)
    profit_question = bool(asked & {"loi_nhuan_gop", "loi_nhuan_truoc_thue", "loi_nhuan_sau_thue"}) or matches(query, ("loi nhuan", "lai", "lo"))
    if not profit_question:                                     # chỉ hỏi vì sao doanh thu/tài sản đổi: dữ liệu không có sản lượng, giá nên chỉ nêu mức thay đổi
        reply = growth_answer(question, companies, with_vinamilk, basis)
        reply["notes"] = [*reply["notes"], "Dữ liệu báo cáo không có sản lượng, giá bán hay cơ cấu sản phẩm nên không giải thích được nguyên nhân thay đổi này; chỉ nêu mức thay đổi."]
        return reply
    if len(codes) > 3:
        return result('Phân tích "vì sao" làm cho tối đa 3 doanh nghiệp mỗi lần. Bạn nêu cụ thể 1-3 công ty, ví dụ "vì sao lợi nhuận KIDO quý 2/2026 giảm".')
    target = "loi_nhuan_gop" if "loi_nhuan_gop" in asked else "loi_nhuan_truoc_thue" if "loi_nhuan_truoc_thue" in asked else "loi_nhuan_sau_thue"
    metrics = ["doanh_thu_thuan", "loi_nhuan_gop", "loi_nhuan_truoc_thue", "loi_nhuan_sau_thue"]
    requested = requested_periods(question)
    if requested and all(p.startswith("FY") for p in requested):
        return result('Phân tích theo năm chưa làm được vì báo cáo năm chỉ có số của năm hiện tại. Bạn hỏi theo quý, ví dụ "vì sao lợi nhuận KIDO quý 2/2026 thay đổi".')
    base, cur, kind, notes, values = _comparison_periods(query, requested, codes, metrics, basis)
    if cur is None or base not in PERIODS or cur not in PERIODS:
        return result("Chưa có hai kỳ có số để so sánh (cần ít nhất doanh thu, lợi nhuận gộp và lợi nhuận). Bạn thử nêu quý có số, ví dụ Q2/2026.")
    texts, sources, lacking = [], {}, []
    for code in codes:
        vb, sb, scb = values(code, base)
        vc, sc, scc = values(code, cur)
        if not _same_scope(code, scb, scc):
            lacking.append(f"{entity_name(code)} ({PERIODS[base]} và {PERIODS[cur]} khác phạm vi báo cáo)")
            continue
        text, level = growth.bridge_text(entity_name(code), PERIODS[base], PERIODS[cur], vb, vc, target)
        if level is None:
            lacking.append(f"{entity_name(code)} (thiếu số {PERIODS[base]} hoặc {PERIODS[cur]})")
            continue
        texts.append(text)
        for src in (*sb, *sc):
            sources[(src.get("doc"), src.get("page"))] = src
    if not texts:
        return result(f"Chưa đủ số đã đối chiếu của {PERIODS[base]} và {PERIODS[cur]} (cần doanh thu và lợi nhuận gộp ở cả hai kỳ) để phân tích cho {', '.join(lacking)}.", [], notes)
    if lacking:
        texts.append(f"**Chưa phân tích được:** {', '.join(lacking)}.")
    notes.append("Đây là phân rã số học từ báo cáo kết quả kinh doanh (tổng các khoản mục bằng đúng chênh lệch); dữ liệu không cho biết nguyên nhân kinh doanh như giá nguyên liệu hay chiến dịch bán hàng.")
    return result("\n\n".join(texts), list(sources.values()), list(dict.fromkeys(notes)))


def assessment_for(codes, period, topic, basis="quy"):
    """Đánh giá (tỷ số, so với kỳ trước và nhóm doanh nghiệp) cho `codes` ở một kỳ: (danh sách văn bản, nguồn, ghi chú)."""
    keys = assess.TOPICS[topic]
    metrics = list(COMPARE_METRICS)
    cache = {}

    def values(code, p):
        if (code, p) not in cache:
            cache[code, p] = entity_values(code, p, metrics, basis)
        return cache[code, p]

    everyone = ["VNM", *COMPANIES]
    peers = {k: [r for c in everyone if (r := insight.ratio_of(values(c, period)[0], k)) is not None] for k in keys}
    scopes = {values(c, period)[2] for c in everyone if values(c, period)[0] and any(insight.ratio_of(values(c, period)[0], k) is not None for k in keys)}
    base = growth.last_year(period) if growth.quarter_key(period) else None
    kind_label = "cùng kỳ năm trước"
    texts, sources, notes = [], {}, []
    for code in codes:
        cur, srcs, scope = values(code, period)
        previous = None
        if base in PERIODS:
            pv, psrcs, pscope = values(code, base)
            if pv and _same_scope(code, pscope, scope):
                previous = pv
                for src in psrcs:
                    sources[(src.get("doc"), src.get("page"))] = src
        texts.append(assess.assess_text(entity_name(code), PERIODS[period], kind_label, cur, previous, peers, topic))
        for src in srcs:
            sources[(src.get("doc"), src.get("page"))] = src
        if code == "VNM" and topic in ("leverage", "general") and period in VNM_QUARTERS:
            extra = _vinamilk_liquidity(period)
            if extra:
                texts[-1] += "\n\n" + extra
    if len({s for s in scopes if s}) > 1:
        notes.append("Phạm vi báo cáo của các doanh nghiệp trong nhóm khác nhau (hợp nhất, riêng lẻ hoặc theo báo cáo), nên so sánh chỉ mang tính tham khảo.")
    notes.append(assess.FOOTNOTE)
    return texts, sources, notes


def _vinamilk_liquidity(period):
    """Thanh khoản và khả năng trả lãi của Vinamilk (chỉ Vinamilk có đủ số liệu để tính): một dòng ngắn."""
    from src.tools.registry import call_tool
    parts = []
    for key, label in (("thanh_toan_hien_hanh", "hệ số thanh toán hiện hành"), ("thanh_toan_nhanh", "hệ số thanh toán nhanh"), ("kha_nang_tra_lai", "khả năng thanh toán lãi vay")):
        res = call_tool("get_ratio", {"ratio": key, "period": period})
        if res.get("ok") and isinstance(res.get("value"), (int, float)):
            text = f"{label} {res['value']:.2f}".replace(".", ",") + " lần"
            if key == "thanh_toan_hien_hanh":
                text += f" (tài sản ngắn hạn gấp {res['value']:.2f} lần nợ ngắn hạn)".replace(".", ",")
            parts.append(text)
    return ("- **Riêng Vinamilk** (chỉ Vinamilk có đủ số liệu để tính): " + "; ".join(parts) + ".") if parts else ""


def assess_answer(question, companies, with_vinamilk, topic, basis="quy"):
    """Trả lời câu đánh giá ("sinh lời tốt không", "nợ có an toàn không") bằng số: so với kỳ trước và với nhóm doanh nghiệp trong dữ liệu."""
    codes = (["VNM"] if with_vinamilk else []) + list(companies)
    if not codes:
        return result("Bạn cho mình biết công ty cần đánh giá (Vinamilk hoặc một trong 11 công ty hàng tiêu dùng) và có thể nêu kỳ, ví dụ \"KIDO quý 2/2026\".")
    if len(codes) > 3:
        return result("Mình đánh giá tối đa 3 doanh nghiệp mỗi lần. Để so sánh nhiều công ty, bạn hỏi \"công ty nào có biên lợi nhuận gộp cao nhất\" hoặc \"xếp hạng tỷ lệ nợ trên vốn chủ\".")
    keys = assess.TOPICS[topic]
    requested = [p for p in requested_periods(question) if p in PERIODS]
    usable = {}

    def ok(code, period):
        if (code, period) not in usable:
            usable[code, period] = any(insight.ratio_of(entity_values(code, period, COMPARE_METRICS, basis)[0], k) is not None for k in keys)
        return usable[code, period]

    if requested:
        period = requested[0]
        if not all(ok(code, period) for code in codes):
            lacking = [entity_name(c) for c in codes if not ok(c, period)]
            latest = next((p for p in reversed(PERIODS) if all(ok(c, p) for c in codes)), None)
            hint = f" Kỳ gần nhất có số của cả hai bên: {PERIODS[latest]}." if latest else ""
            return result(f"Chưa có số đã đối chiếu của {', '.join(lacking)} cho {PERIODS[period]} để đánh giá.{hint}",
                          [s for c in codes if c != "VNM" for s in report_sources(c, period)[:1]])
    else:
        period = next((p for p in reversed(PERIODS) if all(ok(c, p) for c in codes)), None)
        if period is None:
            return result("Chưa có kỳ nào mà các doanh nghiệp được hỏi cùng có đủ số đã đối chiếu để đánh giá.")
    texts, sources, notes = assessment_for(codes, period, topic, basis)
    if not requested:
        notes.insert(0, f"Câu hỏi không nêu kỳ nên dùng {PERIODS[period]}, kỳ gần nhất có số của {'doanh nghiệp được hỏi' if len(codes) == 1 else 'các doanh nghiệp được hỏi'}.")
    return result("\n\n".join(texts), list(sources.values()), notes)


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
    question = re.sub(r"(?i)\bnợ\b(?!\s+(?:phải|xấu|vay))", "nợ phải trả", question)      # "nợ" đứng riêng: bỏ dấu sẽ thành "no", nên đổi trước khi fold
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
    with_vinamilk = matches(query, VNM_WORDS) or asks_all(query)
    basis = "luy_ke" if matches(query, ("luy ke", "6 thang", "9 thang")) else "quy"
    if matches(query, SERIES_WORDS) and not requested_periods(question) and not matches(query, ("thuyet minh",)):
        return series(companies, with_vinamilk, [m for m in METRICS if m in question_metrics(query)] or ["doanh_thu_thuan", "loi_nhuan_sau_thue"], basis)
    if not matches(query, ("thuyet minh",)):
        if growth.asked_why(query):
            return why_answer(question, companies, with_vinamilk, basis)
        if growth.asked_growth(query):
            return growth_answer(question, companies, with_vinamilk, basis)
    topic = assess.asked_assessment(query)
    if topic and not matches(query, COMPARE_WORDS + ("thuyet minh",)) and not asks_all(query):
        return assess_answer(question, companies, with_vinamilk, topic, basis)
    comparing = len(companies) + with_vinamilk >= 2 and matches(query, COMPARE_WORDS)
    no_period = not requested_periods(question) and not selected_period       # không nêu kỳ: để bảng so sánh tự chọn kỳ cả hai bên cùng có số
    if with_vinamilk or len(companies) > 2 or (comparing and (no_period or not question_metrics(query))):
        return compare(question, companies, with_vinamilk, basis)
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


def missing_report_text(companies, period):
    """Kỳ được hỏi chưa có báo cáo: nói rõ mỗi công ty hiện có những kỳ nào và gợi ý hỏi kỳ gần nhất."""
    lines = [f"Chưa có báo cáo {PERIODS[period]} của {', '.join(companies)} trong bộ dữ liệu."]
    for code in companies:
        have = {row[0] for row in repository.documents(code)}
        quarters = [p for p in PERIODS if p in have and p.startswith("Q")]
        years = [PERIODS[p] for p in PERIODS if p in have and p.startswith("FY")]
        if quarters:
            text = f"{quarters[0]} đến {quarters[-1]}" if len(quarters) > 1 else quarters[0]
            lines.append(f"- **{COMPANIES[code][0]} ({code}):** hiện có {text}" + (f" và báo cáo {', '.join(years)}" if years else "")
                         + f". Bạn có thể hỏi lại với {quarters[-1]}.")
        elif years:
            lines.append(f"- **{COMPANIES[code][0]} ({code}):** hiện chỉ có báo cáo {', '.join(years)}.")
    return "\n".join(lines)


def answer_for_period(query, companies, period):
    if not any(repository.documents(code, period) for code in companies):
        return result(missing_report_text(companies, period))
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
    if not metrics and not matches(query, RATIO_WORDS):
        reply = summary(companies, period)
        if len(companies) == 1 and "| Chỉ tiêu |" in reply["answer"]:               # tóm tắt một công ty: thêm nhận định so với kỳ trước và nhóm doanh nghiệp
            texts, sources, notes = assessment_for(companies, period, "general", "quy")
            reply["answer"] += "\n\n" + texts[0]
            reply["sources"] = [*reply["sources"], *sources.values()]
            reply["notes"] = list(dict.fromkeys([*reply["notes"], *notes]))
        return reply
    basis = "luy_ke" if matches(query, ("luy ke", "6 thang", "9 thang")) else "quy"
    if matches(query, RATIO_WORDS):
        return ratio_answer(companies, period, basis)
    if matches(query, ("ty le", "cong ty me", "co dong thieu so", "co dong khong kiem soat", "du bao", "du doan")):
        return result("Với các doanh nghiệp ngoài Vinamilk, mình tra được số của từng chỉ tiêu, biên lợi nhuận, mức nợ, tăng trưởng giữa hai kỳ, "
                      "phân rã vì sao lợi nhuận đổi, số qua các quý và so sánh giữa các doanh nghiệp. Lợi nhuận của cổ đông công ty mẹ hay cổ đông không kiểm soát "
                      "và dự báo thì chưa hỗ trợ. Bạn có thể hỏi, ví dụ: " + '"doanh thu của KIDO qua các quý" hoặc "vì sao lợi nhuận KIDO quý 2/2026 thay đổi".')
    replies = [lookup(companies, metric, period, basis) for metric in METRICS if metric in metrics]
    sources = {s["url"]: s for reply in replies for s in reply["sources"]}
    notes = list(dict.fromkeys(n for reply in replies for n in reply["notes"]))
    return result("\n\n".join(reply["answer"] for reply in replies), list(sources.values()), notes)
