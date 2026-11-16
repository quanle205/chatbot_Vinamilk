# Nhập dữ liệu doanh nghiệp hàng tiêu dùng

Danh mục gồm BBC, BHN, CMF, KDC, MCH, MCM, PAN, QNS, SAB, SBT và VCF. Kho nguồn có 99 PDF, bao phủ bốn quý năm 2025 cho cả 11 công ty. Riêng BBC chưa có báo cáo ba quý đầu năm 2026 trong kho. CMF chưa có bảng kết quả kinh doanh Q3/2026. Báo cáo năm của SBT dùng niên độ kết thúc ngày 30/6.

Phần Trò chuyện chỉ trả lời về Vinamilk. Dữ liệu 11 công ty được tra cứu và so sánh cùng kỳ ở màn hình **Doanh nghiệp** (`/api/consumer/lookup`, `/api/chart`, `/api/ratios`).

Với chỉ tiêu đã đối chiếu, chatbot trả về giá trị có đơn vị và nguồn từng trang. Với các tài liệu khác, chatbot tìm dòng hoặc đoạn văn có liên quan trong nội dung đã đọc. Nội dung OCR cần kiểm tra lại ở PDF, đặc biệt khi báo cáo có nhiều cột hoặc dùng đơn vị nghìn đồng. Nếu trang chưa có văn bản hoặc không tìm được dòng phù hợp, chatbot vẫn trả link báo cáo đúng công ty và kỳ.

- `data/raw/consumer/`: PDF gốc theo công ty, kèm `sources.json` và `sources-quarterly.json`. Trường `file` là đường dẫn tương đối tính từ thư mục này.
- `src/ingest/consumer_ocr.py`: OCR và lưu hình học của từng đoạn trên trang trong `data/interim/consumer/`.
- `src/ingest/consumer_tables.py`: cấu hình vị trí ba bảng cho tám báo cáo đã rà thủ công.
- `src/ingest/consumer_documents.py` và `consumer_statements.py`: lập chỉ mục nội dung 99 PDF. Chỉ ghi giá trị số khi xác định được cột, đơn vị và đối chiếu được đẳng thức của báo cáo.
- `src/ingest/build_consumer_db.py`: kiểm tra đẳng thức kế toán, tạo dữ liệu tra cứu và các đoạn thuyết minh. `consumer_period_checks.json` ghi chênh lệch đã rà giữa cột riêng quý và hiệu hai báo cáo lũy kế công bố khác đợt.
- `data/processed/consumer.duckdb`: danh mục và chỉ mục PDF, chỉ tiêu đối chiếu, thuyết minh và ghi chú. Backend đọc tệp này, bao gồm khi triển khai Vercel.
- `src/consumer/`: danh mục, bộ truy xuất BM25 theo công ty và kỳ, định dạng trả lời có nguồn.

Khi triển khai chỉ cần dữ liệu đã xử lý và thư viện trong `requirements.txt`. Giữ PDF và OCR trung gian trên máy nhập liệu.

## Dựng lại dữ liệu

Từ thư mục gốc repo, sau khi có PDF và hai danh mục nguồn:

```powershell
python -m pip install -r requirements.txt -r requirements-consumer-ingest.txt
python -m src.ingest.consumer_ocr
python -m src.ingest.build_consumer_db
python tests/test_consumer.py
```

Lần chạy OCR đầu tiên cần tải mô hình Latin PP-OCRv5. Có thể dùng mô hình đã tải bằng `--model đường-dẫn.onnx`. OCR bỏ qua các trang đã có tệp trung gian. Khi thay PDF cùng tên, tạo lại kết quả trung gian của tài liệu đó trước khi dựng DB.

Có thể dùng `--company` để chạy từng doanh nghiệp hoặc `--first-pages` để xử lý trước các trang đầu. Sau khi OCR thêm trang, chạy lại bước dựng DuckDB để cập nhật chỉ mục.

Trên Windows, có thể thay lệnh OCR mặc định bằng hai lệnh sau. Lệnh đầu dùng RapidOCR cho tám báo cáo trong cấu hình đối chiếu gốc. Lệnh sau đọc các trang còn lại bằng bộ OCR đã cài trên Windows.

```powershell
python -m src.ingest.consumer_ocr --pilot-only
python -m src.ingest.consumer_ocr --windows-ocr
```

Số dư dùng giá trị cuối kỳ. Kết quả kinh doanh lấy đúng cột riêng quý hoặc lũy kế công bố. Dòng tiền riêng Q2 và Q3 lấy hiệu lũy kế, với nguồn cho hai kỳ. Số trong các đoạn thuyết minh là văn bản OCR, có thể còn lỗi nhận dạng.

## Thử ở màn hình Doanh nghiệp

Chọn công ty, kỳ và chỉ tiêu, ví dụ: doanh thu thuần Q3/2026 của MCM và QNS; hàng tồn kho của QNS năm 2025; báo cáo Q2/2025 của Cholimex Food.
