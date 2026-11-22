"""Đánh giá ("có tốt không", "an toàn không", "hiệu quả không") bằng số: so với chính công ty ở kỳ trước và với các doanh nghiệp còn lại trong dữ liệu.

Quy tắc xác định, không qua mô hình, không phải khuyến nghị đầu tư. "Nhóm" luôn là các doanh nghiệp có số đã đối chiếu cùng kỳ trong dữ liệu
(tối đa 12 công ty hàng tiêu dùng), không phải toàn thị trường; dưới 4 doanh nghiệp thì không xếp hạng.
"""
from __future__ import annotations

from math import ceil
from statistics import median

from src.consumer.growth import asked_growth, asked_why
from src.consumer.insight import RATIOS, _has, pct, points, ratio_of

PROFIT_WORDS = ("sinh loi", "loi nhuan", "lai", "hieu qua", "bien", "kinh doanh", "lam an", "co lai")
LEVERAGE_WORDS = ("no", "thanh toan", "don bay", "vay", "tra no", "an toan", "tai chinh lanh manh", "lanh manh")
GENERAL_WORDS = ("tinh hinh tai chinh", "suc khoe tai chinh", "tai chinh co tot", "tai chinh the nao", "tai chinh ra sao", "danh gia")
EVAL_CUES = ("tot khong", "co tot", "tot hay", "tot chua", "kha quan", "hieu qua khong", "co hieu qua", "kha nang", "an toan", "rui ro",
             "on dinh", "suc khoe", "manh khong", "yeu khong", "danh gia", "nhan xet", "nhu the nao", "the nao", "ra sao", "co on",
             "co cao khong", "co thap khong", "co lanh manh", "co kha")
TREND_WORDS = ("xu huong", "qua cac quy", "cac quy", "theo quy", "dien bien", "qua cac ky")
TOPICS = {"profit": ("bien_gop", "bien_rong"), "leverage": ("no_von", "no_ts"), "general": ("bien_gop", "bien_rong", "no_von", "no_ts")}
SUBJECT = {"profit": "khả năng sinh lời", "leverage": "mức nợ và độ an toàn tài chính", "general": "tình hình tài chính"}
MIN_PEERS = 4                                               # ít hơn: không xếp hạng, chỉ so với kỳ trước
MATERIAL_CHANGE = 0.01                                      # từ 1 điểm phần trăm trở lên mới kết luận "cải thiện" hay "xấu đi"; nhỏ hơn coi là ít thay đổi


def asked_assessment(query: str):
    """"profit" / "leverage" / "general" nếu là câu hỏi đánh giá (có tín hiệu đánh giá và chủ đề); None nếu là câu hỏi số liệu thường."""
    if not _has(query, EVAL_CUES) or asked_growth(query) or asked_why(query) or _has(query, TREND_WORDS):
        return None                                         # "tăng giảm thế nào", "vì sao", "xu hướng thế nào" là câu hỏi tăng trưởng/giải thích/xu hướng
    if _has(query, GENERAL_WORDS):
        return "general"
    profit, leverage = _has(query, PROFIT_WORDS), _has(query, LEVERAGE_WORDS)
    if profit and leverage:
        return "general"
    return "profit" if profit else "leverage" if leverage else None


def _rank(value: float, peers: list, better: str) -> tuple:
    """(thứ hạng 1 = tốt nhất, số bên). Biên: cao hơn là tốt hơn; mức nợ: thấp hơn là tốt hơn."""
    ordered = sorted(peers, reverse=(better == "high"))
    return ordered.index(value) + 1, len(ordered)


def _band(rank: int, n: int) -> str:
    third = ceil(n / 3)
    return "top" if rank <= third else "bottom" if rank > n - third else "middle"


def _line(spec: dict, key: str, value: float, previous, peers: list, kind_label: str) -> tuple:
    """(dòng nhận định, nhóm vị trí hoặc None, chiều thay đổi tốt hơn/xấu hơn hoặc None)."""
    good_when_up = spec["better"] == "high"
    text = f"- **{spec['name']} {pct(value)}**"
    band = trend = None
    if len(peers) >= MIN_PEERS:
        rank, n = _rank(value, peers, spec["better"])
        band = _band(rank, n)
        mid = median(peers)
        if spec["better"] == "high":
            phrase = {"top": "thuộc nhóm cao nhất", "middle": "ở mức trung bình", "bottom": "thuộc nhóm thấp nhất"}[band]
        else:
            phrase = {"top": "thuộc nhóm ít nợ nhất", "middle": "ở mức nợ trung bình", "bottom": "thuộc nhóm nợ nhiều nhất"}[band]
        text += f": {phrase} trong {n} doanh nghiệp (xếp {rank}/{n}, trung vị {pct(mid)})"
    else:
        text += f": chưa đủ doanh nghiệp cùng kỳ để xếp hạng (chỉ {len(peers)} bên có số)"
    if previous is not None:
        delta = value - previous
        if abs(delta) < 0.0005:
            text += f"; gần như không đổi so với {kind_label}"
            trend = "flat"
        else:
            trend = "flat" if abs(delta) < MATERIAL_CHANGE else "better" if (delta > 0) == good_when_up else "worse"
            text += f"; {'tăng' if delta > 0 else 'giảm'} {points(abs(delta)).replace('+', '')} so với {kind_label} ({pct(previous)})"
    return text + ".", band, trend


def assess_text(name: str, period_label: str, kind_label: str, values: dict, previous, peers: dict, topic: str) -> str:
    """Bảng và nhận định cho một doanh nghiệp. peers = {mã tỷ số: [giá trị của các bên cùng kỳ, gồm cả bên được hỏi]}."""
    keys = [k for k in TOPICS[topic] if ratio_of(values, k) is not None]
    rows, lines, bands, trends = [], [], [], []
    for key in keys:
        spec, value = RATIOS[key], ratio_of(values, key)
        prev = ratio_of(previous, key) if previous else None
        line, band, trend = _line(spec, key, value, prev, peers.get(key, []), kind_label)
        lines.append(line)
        bands.append((spec["better"], band))
        trends.append(trend)
        mid = median(peers[key]) if len(peers.get(key, [])) >= MIN_PEERS else None
        rank = f"{_rank(value, peers[key], spec['better'])[0]}/{len(peers[key])}" if mid is not None else "—"
        rows.append(f"| {spec['name']} | {pct(value)} | {pct(prev) if prev is not None else '—'} | "
                    f"{points(value - prev) if prev is not None else '—'} | {pct(mid) if mid is not None else '—'} | {rank} |")
    header = [f"**Đánh giá {SUBJECT[topic]} của {name} · {period_label}**", "",
              f"| Chỉ số | {name} | {kind_label.capitalize()} | Thay đổi | Trung vị nhóm | Xếp hạng (1 = tốt nhất) |", "|---|---:|---:|---:|---:|---:|", *rows,
              "", "**Nhận định**", "", *lines]
    known = [b for _, b in bands if b]
    if known:
        top, bottom = known.count("top"), known.count("bottom")
        level = "cao hơn mặt bằng" if top == len(known) else "thấp hơn mặt bằng" if bottom == len(known) else \
            "nghiêng về phía tốt hơn mặt bằng" if top > bottom else "nghiêng về phía kém hơn mặt bằng" if bottom > top else "quanh mặt bằng"
        change = [t for t in trends if t]
        movement = ""
        if change:
            moving = [t for t in change if t != "flat"]
            movement = (", ít thay đổi so với kỳ trước" if not moving else ", đang cải thiện" if all(t == "better" for t in moving)
                        else ", đang xấu đi" if all(t == "worse" for t in moving) else ", diễn biến trái chiều")
        header += ["", f"**Tóm lại:** {SUBJECT[topic]} của {name} {level} của nhóm doanh nghiệp trong dữ liệu{movement}."]
    return "\n".join(header)


FOOTNOTE = ("Nhận định so với các doanh nghiệp có số đã đối chiếu cùng kỳ trong dữ liệu (tối đa 12 công ty hàng tiêu dùng, không phải toàn thị trường); "
            "đây là đánh giá từ số liệu báo cáo, không phải khuyến nghị đầu tư hay dự báo. Chưa tính ROE, ROA và thanh khoản cho các công ty ngoài Vinamilk "
            "vì thiếu số dư đầu kỳ hoặc tài sản ngắn hạn.")
