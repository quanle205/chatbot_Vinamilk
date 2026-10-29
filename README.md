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
| src/train | huấn luyện: bộ phân loại ý định câu hỏi (`train_intent.py`) và tìm lưới tham số truy xuất (`tune_retrieval.py`) |
| api, public | API FastAPI và trang chat tĩnh cho Vercel |
| tests, eval | kiểm thử và đo chất lượng truy xuất |

## Chạy chatbot

```
pip install -r requirements-streamlit.txt
streamlit run app/streamlit_app.py
```

Tab "Tra số trực tiếp" dùng ngay được. Tab "Hỏi đáp" cần khóa Gemini miễn phí (aistudio.google.com/apikey):
đặt biến môi trường `GEMINI_API_KEY` (tùy chọn `GEMINI_MODEL`, mặc định `gemini-3.8-flash`; `SESSION_LIMIT`,
`DAILY_LIMIT` giới hạn số lượt hỏi). Không commit khóa lên git.

## Triển khai trên Render

Tạo **Web Service** từ repo này (hoặc dùng `render.yaml`), gói Free:

| Mục | Giá trị |
|---|---|
| Build Command | `pip install -r requirements-streamlit.txt` |
| Start Command | `streamlit run app/streamlit_app.py --server.port $PORT` |
| Biến môi trường | `GEMINI_API_KEY` = khóa Gemini; `PYTHON_VERSION` = `3.10.11` |

Cấu hình máy chủ (`headless`, địa chỉ 0.0.0.0) nằm trong `.streamlit/config.toml`. Gói Free của Render tự ngủ khi lâu không
có người dùng và khởi động lại khi có yêu cầu mới; bộ đếm `DAILY_LIMIT` nằm trong bộ nhớ nên bị đặt lại mỗi lần khởi động.
Trên Streamlit Community Cloud vẫn chạy được: đặt `GEMINI_API_KEY` trong Settings -> Secrets.

## Triển khai trên Vercel

Vercel không chạy được Streamlit (cần máy chủ chạy liên tục), nên có một bản riêng: API FastAPI ở `api/index.py` và trang chat tĩnh ở
`public/index.html`. Import repo trên Vercel (Framework: Other, không cần đổi Build Command), đặt biến môi trường `GEMINI_API_KEY`.
`vercel.json` giới hạn thời gian chạy 60 giây và chỉ đóng gói `src/` và `data/processed/`. `requirements.txt` cố ý không có streamlit để
hàm không vượt giới hạn dung lượng. Kiểm thử cục bộ: `python tests/test_api.py` (cần `pip install httpx`).
Bộ giới hạn tốc độ (`RATE_LIMIT_PER_MINUTE`) nằm trong bộ nhớ của từng phiên bản hàm nên chỉ là lớp bảo vệ cơ bản.

## Kiểm thử

```
python tests/test_tools.py
python tests/test_agent.py
python tests/test_app.py
python tests/test_api.py
python eval/retrieval_check.py
```

Các test không gọi mạng (Gemini được thay bằng client giả); chất lượng câu trả lời thật chưa được đo.

## Huấn luyện và đo

```
python -m src.train.train_intent       # phân loại ý định: train 1.044 / test 390 câu, độ chính xác ~0,80, quét ngưỡng từ chối
python -m src.train.tune_retrieval     # tìm lưới k1, b, trọng số vector trên 210 câu train / 90 câu test (~4 phút)
```

Bộ phân loại huấn luyện lại dưới 1 giây mỗi lần khởi động ứng dụng (không lưu tệp mô hình) và chỉ dùng để từ chối sớm câu ngoài phạm vi (ngưỡng 0,8).
Tham số BM25 hiện dùng (k1 = 0,9; b = 0,5; trọng số vector 0) là kết quả của bước tìm lưới.

## Chạy lại pipeline dữ liệu

```
pip install -r requirements-pipeline.txt        # cần thêm Tesseract (có gói tiếng Việt) và poppler
python src/ingest/preprocess.py --input data/raw --output data/interim
python src/ingest/parse_statements.py --pages-dir data/interim --output data/interim
python src/ingest/repair_identities.py --parse-dir src/ingest --csv data/interim/statements_long.csv --out data/interim --overrides data/processed/overrides.csv
python src/ingest/build_db.py
python -m src.rag.chunking
python src/ingest/render_pages.py   # ảnh các trang PDF được trích dẫn -> public/pages (dẫn chứng bên cạnh câu trả lời)
python src/ingest/locate_rows.py    # vị trí từng dòng số liệu trên ảnh trang (khung đỏ đánh dấu dòng được trích)
```
