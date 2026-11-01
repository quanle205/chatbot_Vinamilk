"""Đường dẫn dùng chung cho dữ liệu đã xử lý và ảnh trang PDF dẫn chứng."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
CHUNKS_PATH = PROCESSED / "chunks.jsonl"
PAGES_DIR = ROOT / "public" / "pages"          # <doc>/<trang>.webp (ảnh) và <doc>/<trang>.json (khung các dòng số liệu)
PERIOD_DOCS = ("q1-2025", "q2-2025", "q3-2025", "q4-2025", "q1-2026", "q2-2026")
