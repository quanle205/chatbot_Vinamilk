# duanNLP - Chatbot phân tích BCTC hợp nhất Vinamilk 2025-2026

Chatbot hỏi đáp trên báo cáo tài chính hợp nhất của Vinamilk (quý 1/2025 – quý 2/2026): tra số liệu, tính tỷ số và
tăng trưởng, vẽ xu hướng. Số liệu lấy từ PDF bằng OCR, đã đối chiếu thủ công; câu trả lời kèm nguồn
(báo cáo, trang PDF) và cảnh báo khi một con số không khớp kết quả công cụ.

| Thư mục | Nội dung |
|---|---|
| data/raw | PDF BCTC hợp nhất q1-2025 ... q2-2026 (không đưa lên git) |
| data/interim | kết quả OCR và parse trung gian (không đưa lên git) |
| data/processed | `financials.duckdb`, `chunks.jsonl`, `overrides.csv` (số đã đối chiếu tay với PDF) |
| src/ingest | pipeline dữ liệu: `preprocess.py` (PDF -> OCR), `parse_statements.py`, `repair_identities.py`, `build_db.py` |
| src/rag | `chunking.py`, BM25 + vector n-gam + RRF (`retriever.py`) |
| src/tools | tra số, tỷ số, tăng trưởng, chuỗi kỳ, phân rã biến động (`explain.py`), máy tính (`TOOL_SPECS`, `call_tool`) |
| src/ratios.py, src/stats.py | bảng chỉ số tài chính (mục Chỉ số tài chính) và số đếm độ phủ dữ liệu (hàng số liệu ở màn hình chào), đều không qua mô hình |
| src/web | lớp web dùng chung: giới hạn tốc độ, liên kết nguồn (PDF chính thức, ảnh trang), kiểu dữ liệu vào |
| src/agent | agent Gemini function-calling gọi công cụ + retriever; kiểm tra số bám nguồn (`guard.py`); dựng dữ liệu biểu đồ/bảng từ kết quả công cụ (`charts.py`) |
| src/feedback.py | lưu phản hồi 👍/👎 qua giao diện `FeedbackStore` (mặc định ghi log, tùy chọn webhook) |
| src/train | huấn luyện: bộ phân loại ý định câu hỏi (`train_intent.py`) và tìm lưới tham số truy xuất (`tune_retrieval.py`) |
| api, public | API FastAPI (`api/index.py`, chỉ còn định tuyến) và giao diện tĩnh: `public/index.html` (khung), `public/css/app.css`, `public/js/` (module ES), ảnh trang PDF dẫn chứng (`public/pages`) |
| tests, eval | kiểm thử và đo chất lượng truy xuất |

## Tính năng

- **Hỏi đáp có dẫn chứng:** câu trả lời kèm nguồn (báo cáo, trang PDF, ảnh trang có khung đánh dấu dòng) và cảnh báo số không khớp.
- **Biểu đồ xu hướng và bảng so sánh kỳ:** khi câu hỏi dẫn tới `get_series` (xu hướng nhiều kỳ) hoặc `get_growth` (so sánh hai kỳ),
  `/api/ask` trả thêm trường `charts` (kỳ, giá trị VND, đơn vị, nguồn) dựng từ kết quả công cụ, không từ lời mô hình.
  Giao diện vẽ đường bằng Chart.js 4.4.7 (đóng gói trong `public/js/vendor`, kiểm tra SRI, nạp khi cần) kèm bảng số liệu; câu hỏi một kỳ không có biểu đồ.
- **Giải thích biến động (`explain_change`):** phân rã chênh lệch lợi nhuận sau thuế hoặc doanh thu thuần giữa hai kỳ (so với cùng kỳ
  năm trước hoặc quý liền trước) theo các khoản mục báo cáo KQKD; tổng đóng góp bằng đúng chênh lệch. Mô hình chỉ diễn giải, không suy đoán nguyên nhân kinh doanh.
- **Phản hồi 👍/👎:** nút dưới mỗi câu trả lời gửi `POST /api/feedback` với `{question, answer, label: "up"|"down", timestamp?}`.
  Không lưu IP hay dữ liệu cá nhân. Mặc định mỗi phản hồi là một dòng `FEEDBACK {...}` trong Vercel Logs; đặt `FEEDBACK_WEBHOOK_URL`
  (và tùy chọn `FEEDBACK_WEBHOOK_TOKEN`) để gửi sang dịch vụ lưu trữ riêng; `FEEDBACK_LIMIT_PER_MINUTE` (mặc định 20) giới hạn tốc độ gửi.

## Giao diện

Giao diện tĩnh (HTML + CSS + module ES thuần, không bước build), thanh bên đơn giản kiểu Copilot: **Cuộc trò chuyện mới** và **Tìm kiếm** (lọc các cuộc trò chuyện đã lưu, gõ không dấu vẫn tìm được),
cùng ba chức năng hay dùng nhất: **Tra cứu số liệu**, **Xu hướng & so sánh**, **Chỉ số tài chính**; bên dưới là danh sách "Cuộc trò chuyện" (đổi tên/xóa, lưu trong `localStorage`) và hai chấm DuckDB/Gemini
từ `/api/health`. Thanh bên thu gọn được thành thanh biểu tượng (nhớ lựa chọn). Vùng nội dung có chọn kỳ báo cáo, màn hình chào với 3 lối tắt chức năng, 6 câu gợi ý và hàng số liệu thật.
Phím tắt: `Ctrl/Cmd+K` tìm kiếm, `/` vào ô nhập. Tông xanh chàm, điểm nhấn xanh ngọc/tím; nút Sáng/Tối ở cuối thanh bên trái nhớ lựa chọn. Khi chưa chọn, giao diện theo hệ thống. Thanh bên thành ngăn kéo dưới 900 px. Biểu đồ đổi màu cùng giao diện.

| ![Giao diện cũ](docs/screenshots/truoc-giao-dien-cu.png) | ![Màn hình chào](docs/screenshots/sau-man-hinh-chao-sang.png) | ![Chế độ tối](docs/screenshots/sau-man-hinh-chao-toi.png) |

| Chỉ số tài chính | Tìm kiếm cuộc trò chuyện |
|---|---|
| ![Chỉ số](docs/screenshots/sau-chi-so-tai-chinh.png) | ![Tìm kiếm](docs/screenshots/sau-tim-kiem.png) |

| Trả lời kèm nguồn | Xu hướng & so sánh |
|---|---|
| ![Hỏi đáp](docs/screenshots/sau-tra-loi-co-nguon-sang.png) | ![Xu hướng](docs/screenshots/sau-xu-huong-so-sanh.png) |

| Điện thoại | Ngăn kéo | Thanh bên thu gọn |
|---|---|---|
| ![Điện thoại](docs/screenshots/sau-dien-thoai-man-hinh-chao.png) | ![Ngăn kéo](docs/screenshots/sau-dien-thoai-ngan-keo.png) | ![Thu gọn](docs/screenshots/sau-thanh-ben-thu-gon.png) |

## Chạy chatbot

### Thành viên nhóm: chạy cùng phiên bản

Bản giao diện hiện tại ở nhánh `main`. Dùng Python 3.13 và các phiên bản thư viện trong `requirements.txt`.

```powershell
git clone --branch main https://github.com/quanle205/chatbot_Vinamilk.git
cd chatbot_Vinamilk
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .streamlit/secrets.example.toml .streamlit/secrets.toml
# Mở secrets.toml, thay PASTE_YOUR_OWN_KEY_HERE bằng key của bạn.
.\chay.bat
```

Nếu đã có repo: chuyển sang `main`, chạy `git pull --ff-only origin main` và cài lại `requirements.txt` trong môi trường ảo. Nếu có thay đổi chưa lưu, commit hoặc stash trước khi chuyển nhánh. Dữ liệu DuckDB, các đoạn truy xuất và ảnh dẫn chứng đã có trong repo; không cần chạy OCR lại.

### Thành viên nhóm: triển khai Vercel

1. Import repository này vào Vercel (hoặc fork nếu tài khoản không được phép import).
2. Chọn nhánh triển khai **main**. Trong Settings → Git, đặt **Production Branch** là `main`; nhánh mặc định khác có thể chứa giao diện cũ.
3. Root Directory là thư mục gốc repo. Framework Preset: **Other**. Giữ Build Command và Output Directory ở mặc định, không nhập `public` làm Root Directory.
4. Trong Environment Variables, thêm `GEMINI_API_KEY` bằng key riêng, không có dấu ngoặc kép; áp dụng cho Production và Preview nếu dùng.
5. Nếu cần chọn mô hình, thêm `GEMINI_MODEL` và `GEMINI_FALLBACK_MODELS` (danh sách phân cách bằng dấu phẩy) theo các tên khả dụng với key. Mặc định hiện tại xem `src/agent/agent.py`; key mới không bảo đảm có quyền dùng mọi mô hình.
6. Deploy. Sau khi sửa key hoặc biến môi trường, **Redeploy** để áp dụng. `secrets.toml` không được đưa lên GitHub và không được Vercel đọc.
7. Mở `/api/health`: cần `ok: true`, `periods: 6`, `gemini_key: true`. Trường `gemini_key` chỉ kiểm tra có cấu hình key, không xác minh key hợp lệ. Thử thêm một câu hỏi để kiểm tra Gemini.

Mã nguồn, dữ liệu và giao diện sẽ giống nhau khi dùng cùng commit. Lịch sử trò chuyện, chế độ sáng/tối được lưu riêng trong từng trình duyệt; câu trả lời AI còn phụ thuộc key, mô hình và hạn mức.

Kiểm tra UI tự động: cài Playwright trong môi trường kiểm thử, có Microsoft Edge, chạy server rồi `node tests/ui_smoke.cjs` (mặc định `http://127.0.0.1:8017`, đổi bằng `UI_TEST_URL`). Test dùng API dữ liệu thật và phản hồi Gemini giả lập.

Triển khai trên Vercel: import repo, Framework **Other** (không đổi Build Command), đặt biến môi trường `GEMINI_API_KEY`
(khóa Gemini miễn phí tại aistudio.google.com/apikey; tùy chọn `GEMINI_MODEL`, mặc định `gemini-3.8-flash`). Không commit khóa lên git.
`vercel.json` giới hạn thời gian chạy 60 giây và chỉ đóng gói `src/`, `data/processed/` và `public/pages/`.
Các bộ giới hạn tốc độ (xem bên dưới) nằm trong bộ nhớ của từng phiên bản hàm nên chỉ là lớp bảo vệ cơ bản.

Chạy trên máy (Windows): `.\chay.bat` (hoặc `powershell -File .\chay.ps1`). Script tự nạp khóa Gemini từ biến môi trường, `.env` hoặc `.streamlit\secrets.toml` (đều nằm trong `.gitignore`), cài thư viện nếu thiếu, chạy server và mở http://localhost:8000; đổi cổng bằng `-Port 8001`. Chạy tay:

```
pip install -r requirements.txt uvicorn
set GEMINI_API_KEY=khoa-cua-ban
python -m uvicorn api.index:app --port 8000
```

Không có khóa thì mục Trò chuyện báo "chưa sẵn sàng", các mục Tra cứu, Xu hướng, Chỉ số tài chính vẫn dùng được. Giới hạn mỗi phút theo IP: `RATE_LIMIT_PER_MINUTE` (hỏi đáp, mặc định 6), `BROWSE_LIMIT_PER_MINUTE` (tra cứu, thuyết minh, biểu đồ; mặc định 30), `FEEDBACK_LIMIT_PER_MINUTE` (mặc định 20).

## Kiểm thử

```
python tests/test_tools.py
python tests/test_agent.py
python tests/test_api.py           # cần pip install httpx
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
## Cách chạy code khi tải từ github xuống hãy chạy theo code sau: 
git clone https://github.com/quanle205/chatbot_Vinamilk.git
cd chatbot_Vinamilk
git checkout feature/redesign-ui
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
## lấy key trên Gemini key rồi dán vào secrets.toml
```
