"""Đọc nội dung PDF, dùng OCR cho các trang quét."""
from argparse import ArgumentParser
from base64 import b64encode
from contextlib import ExitStack
import json
from pathlib import Path
import subprocess
from tempfile import NamedTemporaryFile

from src.paths import ROOT
from src.consumer.catalog import COMPANIES

RAW = ROOT / "data/raw/consumer"
INTERIM = ROOT / "data/interim/consumer"


def inputs(pilot_only=False):
    for manifest in ("sources.json", "sources-quarterly.json"):
        for row in json.loads((RAW / manifest).read_text(encoding="utf-8")):
            if row["status"] != "downloaded":
                continue
            if pilot_only and (row["company_code"] not in ("MCM", "QNS") or
                               row.get("period", "").startswith("2025-")):
                continue
            yield row


def save_page(path, tokens):
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                            suffix=".tmp", delete=False) as file:
        json.dump(tokens, file, ensure_ascii=False)
    temporary = Path(file.name)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--company", choices=COMPANIES, action="append")
    parser.add_argument("--pilot-only", action="store_true", help="Chỉ đọc tám báo cáo đã được rà thủ công")
    parser.add_argument("--first-pages", type=int, default=0, help="Chỉ chạy N trang đầu để rà soát bảng")
    parser.add_argument("--model", type=Path, help="Tệp nhận dạng Latin PP-OCRv5")
    parser.add_argument("--windows-ocr", action="store_true", help="Dùng bộ OCR đã cài trên Windows")
    parser.add_argument("--retry-poor", action="store_true", help="Đọc lại trang đã lưu nhưng gần như không có chữ")
    args = parser.parse_args()
    with ExitStack() as resources:
        process(args, resources)


def process(args, resources):
    import pymupdf

    if args.windows_ocr:
        worker = resources.enter_context(subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-NonInteractive",
             "-File", str(Path(__file__).with_name("consumer_windows_ocr.ps1"))],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, encoding="utf-8",
        ))
        resources.callback(worker.stdin.close)
    else:
        worker = None
    engine = None
    for row in inputs(pilot_only=args.pilot_only):
        if args.company and row["company_code"] not in args.company:
            continue
        path = RAW / row["file"]
        folder = INTERIM / path.stem
        folder.mkdir(parents=True, exist_ok=True)
        with pymupdf.open(path) as pdf:
            stop = min(args.first_pages, len(pdf)) if args.first_pages else len(pdf)
            for page in pdf.pages(0, stop):
                out = folder / f"{page.number + 1:03}.json"
                if out.exists() and (not args.retry_poor or
                                     text_quality(json.loads(out.read_text(encoding="utf-8"))) >= 40):
                    continue
                words = page.get_text("words", sort=True)
                if sum(c.isalpha() for word in words for c in word[4]) >= 70:
                    width, height = page.rect.width, page.rect.height
                    tokens = [[x0 / width, y0 / height, x1 / width, y1 / height, text, 1]
                              for x0, y0, x1, y1, text, *_ in words]
                else:
                    landscape = path.stem in ("MCM-2026-Q2", "MCM-2026-Q3") and page.number in (6, 7)
                    scale = min(2.5, 2500 / max(page.rect.width, page.rect.height))
                    matrix = pymupdf.Matrix(scale, scale)
                    if landscape:
                        matrix.prerotate(90)
                    pix = page.get_pixmap(matrix=matrix, alpha=False)
                    if worker:
                        tokens = windows_tokens(worker, pix)
                        if text_quality(tokens) < 40 and (args.retry_poor or len(tokens) > 5):
                            for rotation in (90, -90, 180):
                                rotated = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale).prerotate(rotation),
                                                          alpha=False)
                                alternative = windows_tokens(worker, rotated)
                                if text_quality(alternative) > text_quality(tokens):
                                    tokens = alternative
                                if text_quality(tokens) >= 120:
                                    break
                    else:
                        if engine is None:
                            engine = rapid_engine(args.model)
                        tokens = rapid_tokens(engine, pix)
                save_page(out, tokens)
        print(path.name, len(list(folder.glob("*.json"))), flush=True)


def text_quality(tokens):
    return sum(sum(c.isalpha() for c in token[4]) for token in tokens
               if sum(c.isalpha() for c in token[4]) >= 3)


def windows_tokens(worker, pix):
    worker.stdin.write(b64encode(pix.tobytes("png")).decode("ascii") + "\n")
    worker.stdin.flush()
    payload = worker.stdout.readline()
    if not payload:
        raise RuntimeError("Windows OCR đã dừng")
    tokens = json.loads(payload)
    if isinstance(tokens, dict):
        raise RuntimeError(tokens["error"])
    return tokens


def rapid_engine(model):
    import cv2
    from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR

    cv2.setNumThreads(1)
    config = {
        "Rec.lang_type": LangRec.LATIN, "Rec.ocr_version": OCRVersion.PPOCRV5,
        "Rec.model_type": ModelType.MOBILE, "Global.use_cls": False,
        "Global.log_level": "error", "EngineConfig.onnxruntime.intra_op_num_threads": 1,
        "EngineConfig.onnxruntime.inter_op_num_threads": 1,
    }
    if model:
        config["Rec.model_path"] = str(model)
    return RapidOCR(params=config)


def rapid_tokens(engine, pix):
    import numpy as np

    height, width = pix.height, pix.width
    image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(height, width, 3)
    result = engine(image)
    tokens = []
    if result.boxes is not None:
        for box, text, score in zip(result.boxes, result.txts, result.scores):
            xs, ys = zip(*box)
            tokens.append([float(min(xs) / width), float(min(ys) / height),
                           float(max(xs) / width), float(max(ys) / height), text, float(score)])
    return tokens


if __name__ == "__main__":
    main()
