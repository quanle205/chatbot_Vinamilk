"""Tên doanh nghiệp và chỉ tiêu dùng chung cho nhập liệu và tra cứu."""
from src.rag.text import accent_free, normalize

COMPANIES = {
    "MCM": ("Mộc Châu Milk", ("moc chau milk", "moc chau", "mc milk")),
    "QNS": ("Đường Quảng Ngãi", ("duong quang ngai", "quang ngai")),
    "BBC": ("Bibica", ("bibica",)),
    "BHN": ("Habeco", ("habeco", "bia ha noi")),
    "CMF": ("Cholimex Food", ("cholimex food", "cholimex")),
    "KDC": ("KIDO", ("kido",)),
    "MCH": ("Masan Consumer", ("masan consumer", "hang tieu dung masan", "masan")),
    "PAN": ("Tập đoàn PAN", ("tap doan pan", "pan group", "the pan group")),
    "SAB": ("Sabeco", ("sabeco", "bia sai gon")),
    "SBT": ("AgriS", ("agris", "thanh thanh cong bien hoa", "ttc agris", "ttc sugar", "ttc bien hoa")),
    "VCF": ("Vinacafé Biên Hòa", ("vinacafe bien hoa", "vinacafe")),
}
METRICS = {
    "doanh_thu_thuan": ("Doanh thu thuần", ("doanh thu",)),
    "loi_nhuan_gop": ("Lợi nhuận gộp", ("lai gop",)),
    "loi_nhuan_truoc_thue": ("Lợi nhuận trước thuế", ("loi nhuan ke toan truoc thue", "lntt")),
    "loi_nhuan_sau_thue": ("Lợi nhuận sau thuế", ("lnst", "lai rong", "loi nhuan rong", "lai sau thue")),
    "tong_tai_san": ("Tổng tài sản", ("tong cong tai san",)),
    "no_phai_tra": ("Nợ phải trả", ()),
    "von_chu_so_huu": ("Vốn chủ sở hữu", ("von chu",)),
    "hang_ton_kho": ("Hàng tồn kho", ("ton kho",)),
    "dong_tien_kinh_doanh": ("Lưu chuyển tiền thuần từ hoạt động kinh doanh", ("dong tien kinh doanh", "luu chuyen tien thuan tu hoat dong kinh doanh")),
    "dong_tien_dau_tu": ("Lưu chuyển tiền thuần từ hoạt động đầu tư", ("dong tien dau tu",)),
    "dong_tien_tai_chinh": ("Lưu chuyển tiền thuần từ hoạt động tài chính", ("dong tien tai chinh",)),
}
PERIODS = {
    "FY2025": "Năm 2025",
    "FY2024-2025": "Niên độ 2024–2025",
    "FY2025-2026": "Niên độ 2025–2026",
    "Q1/2025": "Q1/2025",
    "Q2/2025": "Q2/2025",
    "Q3/2025": "Q3/2025",
    "Q4/2025": "Q4/2025",
    "Q1/2026": "Q1/2026",
    "Q2/2026": "Q2/2026",
    "Q3/2026": "Q3/2026",
}


def fold(text):
    return accent_free(normalize(text))
