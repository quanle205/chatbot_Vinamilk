# duanNLP - Chatbot phân tích BCTC hợp nhất Vinamilk 2025-2026

Chatbot hỏi đáp trên báo cáo tài chính hợp nhất của Vinamilk (quý 1/2025 – quý 2/2026): tra số liệu, tính tỷ số và
tăng trưởng, tìm nội dung thuyết minh. Số liệu lấy từ PDF bằng OCR, đã đối chiếu thủ công; câu trả lời kèm nguồn
(báo cáo, trang PDF) và cảnh báo khi một con số không khớp kết quả công cụ.

| Thư mục | Nội dung |
|---|---|
| data/raw | PDF BCTC hợp nhất q1-2025 ... q2-2026 (không đưa lên git) |
| data/interim | kết quả OCR và parse trung gian (không đưa lên git) |
| data/processed | `financials.duckdb`, `chunks.jsonl`, `overrides.csv` (số đã đối chiếu tay với PDF) |
| src/ingest | pipeline dữ liệu: `preprocess.py` (PDF -> OCR), `parse_statements.py`, `repair_identities.py`, `build_db.py` |
| src/rag | `chunking.py`, BM25 + vector n-gam + RRF (`retriever.py`) |
| src/tools | tra số, tỷ số, tăng trưởng, máy tính (`TOOL_SPECS`, `call_tool`) |
| src/agent | agent Gemini function-calling gọi công cụ + retriever; kiểm tra số bám nguồn (`guard.py`) |
| app | giao diện Streamlit |
| tests, eval | kiểm thử và đo chất lượng truy xuất |

## Chạy chatbot

```
pip install -r requirements.txt
streamlit run app/streamlit_app.py
```

Tab "Tra số trực tiếp" dùng ngay được. Tab "Hỏi đáp" cần khóa Gemini miễn phí (aistudio.google.com/apikey):
đặt biến môi trường `GEMINI_API_KEY` (tùy chọn `GEMINI_MODEL`, mặc định `gemini-3.8-flash`; `SESSION_LIMIT`,
`DAILY_LIMIT` giới hạn số lượt hỏi). Trên Streamlit Community Cloud, đặt trong Settings -> Secrets:

```
GEMINI_API_KEY = "khoa-cua-ban"
```

Không commit khóa lên git.

## Kiểm thử

```
python tests/test_tools.py
python tests/test_agent.py
python tests/test_app.py
python eval/retrieval_check.py
```

Các test không gọi mạng (Gemini được thay bằng client giả); chất lượng câu trả lời thật chưa được đo.

## Chạy lại pipeline dữ liệu

```
pip install -r requirements-pipeline.txt        # cần thêm Tesseract (có gói tiếng Việt) và poppler
python src/ingest/preprocess.py --input data/raw --output data/interim
python src/ingest/parse_statements.py --pages-dir data/interim --output data/interim
python src/ingest/repair_identities.py --parse-dir src/ingest --csv data/interim/statements_long.csv --out data/interim --overrides data/processed/overrides.csv
python src/ingest/build_db.py
python -m src.rag.chunking
```
