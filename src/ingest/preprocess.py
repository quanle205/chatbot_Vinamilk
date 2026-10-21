"""Tiền xử lý BCTC Vinamilk (PDF scan) cho dự án RAG.

Pipeline: PDF -> ảnh -> làm sạch ảnh -> OCR -> làm sạch text -> JSONL/CSV.

Cài đặt:
  Ubuntu/Debian: sudo apt install tesseract-ocr tesseract-ocr-vie poppler-utils
  Python:        pip install pytesseract pillow numpy pandas

Ví dụ:
  python preprocess_vinamilk_v2.py --input ./datavinamilk --output ./data_clean

Lưu ý: trích xuất số từ OCR là heuristic. Luôn đối chiếu các số liệu quan trọng
với PDF gốc trước khi dùng làm dữ liệu tài chính/RAG.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
import pytesseract
from PIL import Image


# Chấp nhận q1-2025, Q4-2026... Không tự đoán tên file sai định dạng.
DOC_RE = re.compile(r"^(q[1-4])-(\d{4})$", re.IGNORECASE)


def parse_doc_name(pdf: Path) -> tuple[str, int]:
    match = DOC_RE.fullmatch(pdf.stem)
    if not match:
        raise ValueError(
            f"Tên file '{pdf.name}' không đúng định dạng q1-2025.pdf (q1..q4-YYYY)."
        )
    return match.group(1).upper(), int(match.group(2))


def render_pages(pdf: Path, outdir: Path, dpi: int = 300) -> list[Path]:
    """Render PDF bằng pdftoppm; sắp xếp trang theo số, không theo chuỗi."""
    if not pdf.is_file():
        raise FileNotFoundError(f"Không tìm thấy PDF: {pdf}")
    if not 100 <= dpi <= 600:
        raise ValueError("DPI phải nằm trong khoảng 100..600.")
    outdir.mkdir(parents=True, exist_ok=True)
    prefix = outdir / "page"
    subprocess.run(
        ["pdftoppm", "-r", str(dpi), "-png", str(pdf), str(prefix)],
        check=True,
        capture_output=True,
        text=True,
    )
    pages = list(outdir.glob("page-*.png"))
    pages.sort(key=lambda p: int(re.search(r"-(\d+)\.png$", p.name).group(1)))
    if not pages:
        raise RuntimeError(f"Không render được trang nào từ {pdf.name}.")
    return pages


def clean_image(img: Image.Image, remove_color_marks: bool = True) -> Image.Image:
    """Nhị phân hóa ảnh; có thể tắt lọc màu để tránh xóa nội dung in màu."""
    rgb = np.asarray(img.convert("RGB"), dtype=np.int16)
    gray = rgb.mean(axis=2)
    if remove_color_marks:
        r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
        is_red = (r - g > 40) & (r - b > 40)
        is_blue = (b - r > 40) & (b - g > 20)
        gray[is_red | is_blue] = 255
    binary = np.where(gray < 160, 0, 255).astype(np.uint8)
    return Image.fromarray(binary)


def ocr_page(img: Image.Image, lang: str = "vie+eng", psm: int = 6) -> str:
    if psm not in {3, 4, 6, 11, 12}:
        raise ValueError("PSM không được hỗ trợ; chọn một trong 3, 4, 6, 11, 12.")
    return pytesseract.image_to_string(
        img, lang=lang,
        config=f"--oem 1 --psm {psm} -c preserve_interword_spaces=1",
    )


BOILERPLATE = [
    r"Mẫu B 0\d[ab]? ?[–-] ?DN",
    r"\(Ban hành theo Thông tư số.*",
    r"ngày 22 tháng 12 năm 2014 của Bộ Tài chính\)",
    r"Các thuyết minh đính kèm là bộ phận hợp thành.*",
    r"Công ty Cổ phần Sữa Việt Nam\s*$",
]


def repair_numbers(text: str) -> str:
    """Sửa một số lỗi OCR phổ biến, tránh đổi dấu phẩy hàng loạt.

    Các sửa đổi chỉ mang tính heuristic; trường hợp mơ hồ được giữ nguyên để
    người dùng có thể kiểm tra từ trường raw trong CSV.
    """
    out = []
    for line in text.splitlines():
        line = re.sub(r"(?<=\d)[,.]\s*[,.](?=\d)", ".", line)  # 9,.260 -> 9.260
        line = re.sub(r"(?<=\d)\.\s+(?=\d{3}(?:\D|$))", ".", line)  # 650. 768 -> 650.768
        # Chỉ sửa dấu phẩy ngăn nghìn khi theo sau là nhóm 3 chữ số và
        # tiếp theo là dấu chấm nhóm nghìn hoặc ranh giới token.
        line = re.sub(r"(?<=\d),(?=\d{3}(?:\.\d{3})+(?:\D|$))", ".", line)
        line = re.sub(r"[—–]+(?=\d)", " ", line)
        out.append(line)
    return "\n".join(out)


def clean_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text).replace("\u00a0", " ")
    lines = []
    for line in text.splitlines():
        line = line.rstrip()
        if not line.strip() or re.fullmatch(r"\s*\d{1,2}\s*", line):
            continue
        if any(re.search(pattern, line, re.IGNORECASE) for pattern in BOILERPLATE):
            continue
        lines.append(re.sub(r"[ \t]{3,}", "   ", line))
    return repair_numbers("\n".join(lines))


# Nhận diện token số theo kiểu báo cáo tài chính Việt Nam.
# Quan trọng: quantifier phải greedy để 45.886.078.014.025 là MỘT token,
# không bị tách thành 45, 886, 078...
NUM_RE = re.compile(
    r"(?<![\w])(?:\(\s*-?\s*\d[\d.,]*(?:\s*)\)|-?\d[\d.,]*%?|-)(?!\w)"
)

FORMULA_RE = re.compile(r"[({]\s*\d{1,3}[ab]?\s*=[^)}]*[)}]")

DATE_LINE_RE = re.compile(
    r"\b(?:ngày|date)\s*\d{1,2}\s*(?:tháng\s*\d{1,2}\s*)?(?:năm\s*\d{4}|\d{4})\b",
    re.IGNORECASE,
)


def parse_vn_number(token: str) -> int | float | None:
    """Đọc số tiền VN: 45.886.078.014.025 -> int; (26.168...) -> số âm.

    Dấu chấm được coi là phân cách hàng nghìn nếu có nhiều nhóm 3 chữ số.
    Dấu phẩy cuối cùng được coi là dấu thập phân theo quy ước VN.
    """
    token = token.strip().replace(" ", "")
    if not token or token == "-":
        return None
    negative = token.startswith("(") and token.endswith(")")
    if negative:
        token = token[1:-1]
    if token.endswith("%"):
        token = token[:-1]
    if token.startswith("-"):
        negative = True
        token = token[1:]
    if not token or not re.fullmatch(r"\d[\d.,]*", token):
        return None

    # Với số VN có dấu phẩy, dấu phẩy cuối là thập phân; chấm là hàng nghìn.
    if "," in token:
        last_comma = token.rfind(",")
        integer_part = token[:last_comma].replace(".", "").replace(",", "")
        decimal_part = re.sub(r"[.,]", "", token[last_comma + 1:])
        if not integer_part:
            integer_part = "0"
        try:
            value: int | float = float(f"{integer_part}.{decimal_part or '0'}")
        except ValueError:
            return None
    else:
        # Một dấu chấm với phần sau không phải nhóm 3 chữ số thường là
        # dấu thập phân OCR (ví dụ 2025.0), không phải phân cách hàng nghìn.
        if token.count(".") == 1 and len(token.rsplit(".", 1)[1]) in {1, 2}:
            try:
                value = float(token)
            except ValueError:
                return None
        else:
            digits = token.replace(".", "")
            try:
                value = int(digits)
            except ValueError:
                return None
    return -value if negative else value


def _digits_only(token: str) -> str:
    """Trả về chữ số trong token để ước lượng độ dài số, không tự sửa OCR."""
    return re.sub(r"\D", "", token)


def extract_rows(text: str, doc: str, page: int) -> list[dict]:
    """Trích xuất thận trọng; chỉ điền value_1/value_2 khi có đúng 2 token tiền dài.

    Đây không phải bộ đọc bảng hoàn chỉnh. Dòng có nhiều số dài hoặc token lỗi OCR
    sẽ được đánh dấu CAN_KIEM_TRA và không tự chọn bừa hai số đầu.
    """
    rows = []
    financial_label_re = re.compile(
        r"doanh thu|lợi nhuận|tài sản|nợ phải trả|vốn chủ sở hữu|chi phí|giá vốn|"
        r"lưu chuyển|thu nhập|tiền và tương đương tiền|phải thu|hàng tồn kho|"
        r"khấu hao|lãi vay|thuế|cổ tức|lợi ích cổ đông",
        re.IGNORECASE,
    )

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        # Bỏ dòng ngày tháng/đầu trang nếu không phải một chỉ tiêu tài chính.
        if (DATE_LINE_RE.search(stripped) or re.search(r"\bdate\b", stripped, re.IGNORECASE)) and not financial_label_re.search(stripped):
            continue

        # Mã số thường đứng đầu dòng (01, 02, 21...). Bỏ mã khỏi phần nhãn trước
        # khi tìm token số, tránh làm nhãn rỗng và tránh coi mã là số tiền.
        code_match = re.match(r"^\s*(\d{1,3}[ab]?)\s+(.+)$", stripped, re.IGNORECASE)
        ma_so = code_match.group(1) if code_match else None
        body = code_match.group(2).strip() if code_match else stripped

        # Che công thức trong nhãn, vd "(60 = 50 - 51 - 52)" hoặc "{30 = 20 + ...}",
        # để số trong công thức không bị coi là số đầu tiên (làm nhãn rỗng, mất dòng).
        masked = FORMULA_RE.sub(lambda m: "#" * len(m.group(0)), body)
        matches = list(NUM_RE.finditer(masked))
        tokens = [m.group(0) for m in matches if m.group(0) != "-"]
        if not tokens:
            continue

        first_pos = matches[0].start()
        label = re.sub(r"\s+", " ", body[:first_pos]).strip(" .:-")
        # Nếu dòng bắt đầu bằng số nhưng không bắt được mã, không nhận dòng chỉ số.
        if len(label) < 3:
            continue

        # Chỉ token có ít nhất 8 chữ số được coi là ứng viên số tiền. Số nhỏ như
        # mã, số trang, ngày/tháng và tỷ lệ thường không đủ điều kiện này.
        candidates = [tok for tok in tokens if len(_digits_only(tok)) >= 8 and parse_vn_number(tok) is not None]
        # Dòng có ký tự lạ xen trong một chuỗi số dài có thể là OCR hỏng.
        suspicious_ocr = bool(re.search(r"\d[§IlO|][\d.]{2,}|\d[./][\d./]{2,}[A-Za-z§|]", body))

        value_1 = value_2 = None
        is_percent_1 = is_percent_2 = False
        if len(candidates) == 2 and not suspicious_ocr:
            value_1 = parse_vn_number(candidates[0])
            value_2 = parse_vn_number(candidates[1])
            is_percent_1 = candidates[0].endswith("%")
            is_percent_2 = candidates[1].endswith("%")
            extraction_status = "2_SO_DAI_CAN_DOI_CHIEU"
        elif len(candidates) > 2 or suspicious_ocr:
            extraction_status = "CAN_KIEM_TRA_NHIEU_SO_HOAC_OCR_LOI"
        else:
            extraction_status = "THIEU_2_SO_DAI"

        rows.append({
            "doc": doc,
            "page": page,
            "label": label,
            "ma_so": ma_so,
            "value_1": value_1,
            "value_2": value_2,
            "is_percent_1": is_percent_1,
            "is_percent_2": is_percent_2,
            "raw": stripped,
            "numeric_tokens": json.dumps(tokens, ensure_ascii=False),
            "money_candidates": json.dumps(candidates, ensure_ascii=False),
            "extraction_status": extraction_status,
        })
    return rows


def validate_balance_sheet(rows: list[dict]) -> list[str]:
    """Kiểm tra sơ bộ; bỏ qua mã trùng/không duy nhất thay vì chọn tùy tiện."""
    messages = []
    grouped: dict[str, dict[str, list[float]]] = {}
    for row in rows:
        code, value = row.get("ma_so"), row.get("value_1")
        if code and value is not None:
            grouped.setdefault(row["doc"], {}).setdefault(str(code), []).append(float(value))

    for doc, codes in sorted(grouped.items()):
        def get_unique(code: str) -> float | None:
            values = codes.get(code, [])
            if len(values) != 1:
                if len(values) > 1:
                    messages.append(f"{doc}: mã {code} xuất hiện {len(values)} lần; bỏ qua kiểm tra mã này.")
                return None
            return values[0]

        for total, parts in (("270", ("100", "200")), ("440", ("300", "400"))):
            total_value = get_unique(total)
            part_values = [get_unique(code) for code in parts]
            if total_value is None or any(value is None for value in part_values):
                continue
            difference = total_value - sum(part_values)
            status = "OK" if abs(difference) < 1 else "LỆCH, cần kiểm tra OCR/PDF"
            messages.append(
                f"{doc}: {total} = {'+'.join(parts)} -> {status} (chênh lệch: {difference:g})"
            )
    return messages


SECTIONS = [
    (r"BÁO CÁO TÌNH HÌNH TÀI CHÍNH|Báo cáo tình hình tài chính", "can_doi_ke_toan"),
    (r"KẾT QUẢ HOẠT ĐỘNG KINH DOANH|kết quả hoạt động kinh doanh riêng cho", "ket_qua_kinh_doanh"),
    (r"LƯU CHUYỂN TIỀN TỆ|lưu chuyển tiền tệ riêng cho", "luu_chuyen_tien_te"),
    (r"Thuyết minh báo cáo tài chính", "thuyet_minh"),
]


def classify(text: str) -> str:
    head = "\n".join(text.splitlines()[:6])
    for pattern, name in SECTIONS:
        if re.search(pattern, head, re.IGNORECASE):
            return name
    return "khac"


def process(pdf: Path, outdir: Path, lang: str, dpi: int = 300,
            remove_color_marks: bool = True, psm: int = 6) -> list[dict]:
    quarter, year = parse_doc_name(pdf)
    doc = pdf.stem
    records, rows = [], []
    with tempfile.TemporaryDirectory(prefix="vinamilk_ocr_") as tmp:
        for page_number, image_path in enumerate(render_pages(pdf, Path(tmp), dpi), start=1):
            try:
                with Image.open(image_path) as source:
                    image = clean_image(source, remove_color_marks=remove_color_marks)
                raw = ocr_page(image, lang=lang, psm=psm)
            except Exception as exc:
                print(f"  LỖI {doc} trang {page_number}: {exc}")
                continue
            text = clean_text(raw)
            if len(text.strip()) < 10:
                print(f"  CẢNH BÁO {doc} trang {page_number}: OCR quá ít văn bản")
                continue
            records.append({
                "doc": doc, "quarter": quarter, "year": year,
                "page": page_number, "section": classify(text), "text": text,
            })
            rows.extend(extract_rows(text, doc, page_number))
            print(f"  {doc} trang {page_number}: {len(text)} ký tự")

    jsonl_path = outdir / f"{doc}.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"  Đã lưu {jsonl_path} ({len(records)} trang OCR thành công)")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Tiền xử lý BCTC Vinamilk cho RAG")
    parser.add_argument("--input", default="./pdfs", help="Thư mục chứa PDF")
    parser.add_argument("--output", default="./data_clean", help="Thư mục đầu ra")
    parser.add_argument("--lang", default="vie+eng", help="Ngôn ngữ Tesseract, ví dụ vie+eng")
    parser.add_argument("--dpi", type=int, default=300, help="DPI render PDF (100..600)")
    parser.add_argument("--psm", type=int, default=6, choices=[3, 4, 6, 11, 12], help="Tesseract page segmentation mode")
    parser.add_argument("--keep-color", action="store_true", help="Không xóa dấu đỏ/chữ xanh khi làm sạch ảnh")
    args = parser.parse_args()

    input_dir = Path(args.input)
    outdir = Path(args.output)
    if not input_dir.is_dir():
        parser.error(f"Thư mục input không tồn tại: {input_dir}")
    pdfs = sorted(input_dir.glob("*.pdf"))
    if not pdfs:
        parser.error(f"Không tìm thấy file .pdf trong {input_dir}")
    if not 100 <= args.dpi <= 600:
        parser.error("--dpi phải nằm trong khoảng 100..600")
    outdir.mkdir(parents=True, exist_ok=True)

    try:
        # Báo lỗi phụ thuộc môi trường sớm, tránh xử lý dở dang nhiều file.
        pytesseract.get_tesseract_version()
        available_languages = set(pytesseract.get_languages(config=""))
        missing = set(args.lang.split("+")) - available_languages
        if missing:
            parser.error(f"Tesseract thiếu ngôn ngữ: {', '.join(sorted(missing))}. Đã cài: {', '.join(sorted(available_languages))}")
    except pytesseract.TesseractNotFoundError:
        parser.error("Không tìm thấy Tesseract. Hãy cài tesseract-ocr và thêm vào PATH.")

    all_rows = []
    failures = []
    for pdf in pdfs:
        print(f"Xử lý {pdf.name}")
        try:
            all_rows.extend(process(pdf, outdir, args.lang, args.dpi,
                                    remove_color_marks=not args.keep_color, psm=args.psm))
        except (ValueError, FileNotFoundError, subprocess.CalledProcessError, RuntimeError) as exc:
            failures.append((pdf.name, str(exc)))
            print(f"  THẤT BẠI {pdf.name}: {exc}")

    csv_path = outdir / "financial_rows.csv"
    pd.DataFrame(all_rows, columns=[
        "doc", "page", "label", "ma_so", "value_1", "value_2",
        "is_percent_1", "is_percent_2", "raw", "numeric_tokens",
        "money_candidates", "extraction_status",
    ]).to_csv(csv_path, index=False, encoding="utf-8-sig")
    print("\nKiểm tra sơ bộ bảng cân đối:")
    messages = validate_balance_sheet(all_rows)
    print("\n".join(messages) if messages else "Không đủ dữ liệu duy nhất để kiểm tra.")
    print(f"\nCSV: {csv_path}")
    print("Lưu ý: các dòng có extraction_status khác 2_SO_DAI_CAN_DOI_CHIEU cần kiểm tra PDF gốc.")
    print(f"Số dòng dữ liệu: {len(all_rows)} | PDF thành công: {len(pdfs) - len(failures)}/{len(pdfs)}")
    if failures:
        print("Các file lỗi:")
        for filename, reason in failures:
            print(f"  - {filename}: {reason}")
        return 1
    print(f"Xong -> {outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
