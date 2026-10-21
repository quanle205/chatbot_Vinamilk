"""Danh mục chỉ tiêu tài chính: tên chuẩn -> mã số trong báo cáo, theo từng chuẩn mực kế toán.

BCTC 2025 theo TT200 (202/2014/TT-BTC), BCTC 2026 theo TT99 (43/2026/TT-BTC); hai chuẩn mực đánh lại
một số mã (vd tổng tài sản 270 -> 280, vay ngắn hạn 320 -> 321), nên tra theo tên chỉ tiêu chứ không theo mã.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..rag.text import accent_free, normalize


@dataclass(frozen=True)
class Metric:
    key: str
    name: str                       # tên tiếng Việt hiển thị
    statement: str                  # CDKT | KQKD | LCTT
    codes: dict                     # {"TT200": mã, "TT99": mã}
    kind: str                       # flow (phát sinh trong kỳ) | balance (số dư tại thời điểm)
    aliases: tuple = field(default=())


def _m(key, name, st, code, kind, aliases=(), code99=None):
    return Metric(key, name, st, {"TT200": code, "TT99": code99 or code}, kind, tuple(aliases))


METRICS = [
    # ---- Báo cáo kết quả hoạt động kinh doanh (flow)
    _m("doanh_thu_ban_hang", "Doanh thu bán hàng và cung cấp dịch vụ", "KQKD", "01", "flow", ["doanh thu gộp", "doanh thu bán hàng"]),
    _m("giam_tru_doanh_thu", "Các khoản giảm trừ doanh thu", "KQKD", "02", "flow", ["giảm trừ doanh thu"]),
    _m("doanh_thu_thuan", "Doanh thu thuần", "KQKD", "10", "flow", ["doanh thu thuần", "doanh thu", "doanh số", "net revenue", "bán hàng sau giảm trừ"]),
    _m("gia_von", "Giá vốn hàng bán", "KQKD", "11", "flow", ["giá vốn", "giá vốn hàng bán", "cogs"]),
    _m("loi_nhuan_gop", "Lợi nhuận gộp", "KQKD", "20", "flow", ["lợi nhuận gộp", "lãi gộp"]),
    _m("doanh_thu_tai_chinh", "Doanh thu hoạt động tài chính", "KQKD", "21", "flow", ["doanh thu tài chính", "thu nhập tài chính"], code99="22"),
    _m("chi_phi_tai_chinh", "Chi phí tài chính", "KQKD", "22", "flow", ["chi phí tài chính"], code99="23"),
    _m("chi_phi_lai_vay", "Chi phí lãi vay", "KQKD", "23", "flow", ["chi phí lãi vay", "lãi vay", "chi phí đi vay"], code99="24"),
    _m("lai_lien_ket", "Lãi chia từ công ty liên kết, liên doanh", "KQKD", "24", "flow", ["lãi công ty liên kết", "lãi liên doanh", "lãi chia từ công ty liên kết"], code99="27"),
    _m("chi_phi_ban_hang", "Chi phí bán hàng", "KQKD", "25", "flow", ["chi phí bán hàng"]),
    _m("chi_phi_qldn", "Chi phí quản lý doanh nghiệp", "KQKD", "26", "flow", ["chi phí quản lý", "chi phí quản lý doanh nghiệp", "chi phí qldn"]),
    _m("loi_nhuan_hdkd", "Lợi nhuận thuần từ hoạt động kinh doanh", "KQKD", "30", "flow", ["lợi nhuận hoạt động kinh doanh", "lợi nhuận thuần từ hoạt động kinh doanh", "lợi nhuận từ hđkd"]),
    _m("thu_nhap_khac", "Thu nhập khác", "KQKD", "31", "flow", ["thu nhập khác"]),
    _m("chi_phi_khac", "Chi phí khác", "KQKD", "32", "flow", ["chi phí khác"]),
    _m("loi_nhuan_khac", "Kết quả từ hoạt động khác", "KQKD", "40", "flow", ["lợi nhuận khác", "kết quả hoạt động khác"]),
    _m("loi_nhuan_truoc_thue", "Lợi nhuận kế toán trước thuế", "KQKD", "50", "flow", ["lợi nhuận trước thuế", "lãi trước thuế", "ebt", "lợi nhuận kế toán trước thuế"]),
    _m("thue_tndn_hien_hanh", "Chi phí thuế TNDN hiện hành", "KQKD", "51", "flow", ["thuế thu nhập doanh nghiệp hiện hành", "thuế tndn hiện hành", "thuế tndn"]),
    _m("thue_tndn_hoan_lai", "Chi phí thuế TNDN hoãn lại", "KQKD", "52", "flow", ["thuế hoãn lại", "thuế tndn hoãn lại"]),
    _m("loi_nhuan_sau_thue", "Lợi nhuận sau thuế", "KQKD", "60", "flow", ["lợi nhuận sau thuế", "lãi ròng", "lợi nhuận ròng", "lnst", "net income", "lãi sau thuế"]),
    _m("lnst_chu_so_huu", "LNST của chủ sở hữu công ty mẹ", "KQKD", "61", "flow", ["lợi nhuận sau thuế của công ty mẹ", "lnst công ty mẹ", "lợi nhuận của cổ đông công ty mẹ", "lợi nhuận chủ sở hữu"]),
    _m("lnst_co_dong_thieu_so", "LNST của cổ đông không kiểm soát", "KQKD", "62", "flow", ["lợi nhuận cổ đông thiểu số", "lợi nhuận cổ đông không kiểm soát"]),
    # ---- Bảng cân đối kế toán (balance)
    _m("tien", "Tiền và các khoản tương đương tiền", "CDKT", "110", "balance", ["tiền mặt", "tiền và tương đương tiền", "tiền và các khoản tương đương tiền", "lượng tiền"]),
    _m("dau_tu_ngan_han", "Các khoản đầu tư tài chính ngắn hạn", "CDKT", "120", "balance", ["đầu tư tài chính ngắn hạn", "đầu tư ngắn hạn"]),
    _m("phai_thu_ngan_han", "Các khoản phải thu ngắn hạn", "CDKT", "130", "balance", ["phải thu ngắn hạn", "khoản phải thu"]),
    _m("phai_thu_khach_hang", "Phải thu khách hàng", "CDKT", "131", "balance", ["phải thu khách hàng"]),
    _m("hang_ton_kho", "Hàng tồn kho", "CDKT", "140", "balance", ["hàng tồn kho", "tồn kho"]),
    _m("tai_san_ngan_han", "Tài sản ngắn hạn", "CDKT", "100", "balance", ["tài sản ngắn hạn"]),
    _m("tai_san_dai_han", "Tài sản dài hạn", "CDKT", "200", "balance", ["tài sản dài hạn"]),
    _m("tai_san_co_dinh", "Tài sản cố định", "CDKT", "220", "balance", ["tài sản cố định", "tscđ"]),
    _m("tong_tai_san", "Tổng tài sản", "CDKT", "270", "balance", ["tổng tài sản", "quy mô tài sản"], code99="280"),
    _m("no_phai_tra", "Nợ phải trả", "CDKT", "300", "balance", ["nợ phải trả", "tổng nợ", "tổng nợ phải trả"]),
    _m("no_ngan_han", "Nợ ngắn hạn", "CDKT", "310", "balance", ["nợ ngắn hạn"]),
    _m("no_dai_han", "Nợ dài hạn", "CDKT", "330", "balance", ["nợ dài hạn"]),
    _m("phai_tra_nguoi_ban", "Phải trả người bán", "CDKT", "311", "balance", ["phải trả người bán", "phải trả nhà cung cấp"]),
    _m("vay_ngan_han", "Vay ngắn hạn", "CDKT", "320", "balance", ["vay ngắn hạn", "nợ vay ngắn hạn", "vay ngân hàng ngắn hạn"], code99="321"),
    _m("vay_dai_han", "Vay dài hạn", "CDKT", "338", "balance", ["vay dài hạn", "nợ vay dài hạn"], code99="339"),
    _m("von_chu_so_huu", "Vốn chủ sở hữu", "CDKT", "400", "balance", ["vốn chủ sở hữu", "vốn chủ", "equity"]),
    _m("von_co_phan", "Vốn cổ phần", "CDKT", "411", "balance", ["vốn cổ phần", "vốn điều lệ"]),
    _m("lnst_chua_phan_phoi", "Lợi nhuận sau thuế chưa phân phối", "CDKT", "421", "balance", ["lợi nhuận chưa phân phối", "lnst chưa phân phối"], code99="420"),
    _m("loi_ich_co_dong_khong_kiem_soat", "Lợi ích cổ đông không kiểm soát", "CDKT", "429", "balance", ["cổ đông không kiểm soát", "cổ đông thiểu số", "lợi ích cổ đông không kiểm soát"]),
    _m("tong_nguon_von", "Tổng nguồn vốn", "CDKT", "440", "balance", ["tổng nguồn vốn"]),
    # ---- Báo cáo lưu chuyển tiền tệ (flow; chỉ có số lũy kế từ đầu năm trong báo cáo)
    _m("khau_hao", "Khấu hao và phân bổ", "LCTT", "02", "flow", ["khấu hao", "khấu hao và phân bổ", "depreciation"]),
    _m("luu_chuyen_hdkd", "Lưu chuyển tiền thuần từ hoạt động kinh doanh", "LCTT", "20", "flow", ["dòng tiền kinh doanh", "lưu chuyển tiền từ hoạt động kinh doanh", "dòng tiền từ hoạt động kinh doanh", "cfo"]),
    _m("chi_mua_tscd", "Tiền chi mua tài sản cố định", "LCTT", "21", "flow", ["chi đầu tư tài sản cố định", "tiền chi mua tài sản cố định", "capex", "mua sắm tài sản cố định"]),
    _m("luu_chuyen_dau_tu", "Lưu chuyển tiền thuần từ hoạt động đầu tư", "LCTT", "30", "flow", ["dòng tiền đầu tư", "lưu chuyển tiền từ hoạt động đầu tư"]),
    _m("thu_di_vay", "Tiền thu từ đi vay", "LCTT", "33", "flow", ["tiền thu từ đi vay", "thu từ vay"]),
    _m("tra_no_goc_vay", "Tiền chi trả nợ gốc vay", "LCTT", "34", "flow", ["trả nợ gốc vay", "trả nợ vay"]),
    _m("chi_tra_co_tuc", "Tiền chi trả cổ tức", "LCTT", "36", "flow", ["chi trả cổ tức", "trả cổ tức", "cổ tức đã trả"]),
    _m("luu_chuyen_tai_chinh", "Lưu chuyển tiền thuần từ hoạt động tài chính", "LCTT", "40", "flow", ["dòng tiền tài chính", "lưu chuyển tiền từ hoạt động tài chính"]),
    _m("luu_chuyen_tien_thuan", "Lưu chuyển tiền thuần trong kỳ", "LCTT", "50", "flow", ["lưu chuyển tiền thuần trong kỳ", "biến động tiền thuần"]),
]

BY_KEY = {m.key: m for m in METRICS}
_NORM_ALIASES = [(m, [accent_free(normalize(a)) for a in (m.name, *m.aliases)]) for m in METRICS]


def get_metric(key_or_name: str) -> Metric:
    if key_or_name in BY_KEY:
        return BY_KEY[key_or_name]
    hits = find_metrics(key_or_name, limit=1)
    if not hits:
        raise KeyError(f"Không có chỉ tiêu '{key_or_name}'. Dùng search_metrics để tìm tên chỉ tiêu.")
    return hits[0]


def find_metrics(text: str, limit: int = 5) -> list[Metric]:
    """Tìm chỉ tiêu theo cách gọi trong câu hỏi: ưu tiên alias dài nhất xuất hiện trong văn bản."""
    from difflib import SequenceMatcher
    q = accent_free(normalize(text)).replace("_", " ")
    scored = []
    for m, names in _NORM_ALIASES:
        best = 0.0
        for a in names:
            if a in q or a == q:
                best = max(best, 1.0 + len(a) / 100)         # khớp trọn alias; alias dài thắng alias ngắn
            elif len(q) >= 8 and q in a:
                best = max(best, 0.95)                       # câu hỏi là phần của tên chuẩn
            else:
                best = max(best, SequenceMatcher(None, a, q).ratio() * 0.9)
        if best >= 0.62:
            scored.append((best, m))
    scored.sort(key=lambda x: -x[0])
    return [m for _, m in scored[:limit]]
