# Nhập dữ liệu doanh nghiệp hàng tiêu dùng

Danh mục gồm BBC, BHN, CMF, KDC, MCH, MCM, PAN, QNS, SAB, SBT và VCF. Kho nguồn có 99 PDF, bao phủ bốn quý năm 2025 cho cả 11 công ty. Riêng BBC chưa có báo cáo ba quý đầu năm 2026 trong kho. CMF chưa có bảng kết quả kinh doanh Q3/2026. Báo cáo năm của SBT dùng niên độ kết thúc ngày 30/6.

Gõ tên hoặc mã công ty trực tiếp trong ô chat. Câu hỏi tiếp theo có thể dùng tên và kỳ từ câu hỏi trước. Khi không nêu kỳ, chatbot dùng kỳ mới nhất có báo cáo. Màn hình **Doanh nghiệp** cho phép tra cứu và so sánh cùng kỳ.
Màn hình **Tra cứu số liệu** (chọn nhiều doanh nghiệp) và **Xu hướng & so sánh** dùng `/api/consumer/lookup`, `/api/chart`, `/api/ratios`.

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

## Thử ở màn hình Tra cứu số liệu

Chọn công ty, kỳ và chỉ tiêu, ví dụ: doanh thu thuần Q3/2026 của MCM và QNS; hàng tồn kho của QNS năm 2025; báo cáo Q2/2025 của Cholimex Food.

## Trích số tự động từ PDF quét (9 công ty ngoài MCM và QNS)

MCM và QNS có số đã đối chiếu tay (`facts`). Chín công ty còn lại dùng `src/ingest/consumer_extract.py`, trích số theo **nội dung** thay vì theo tiêu đề trang
(OCR hay đọc sai tiêu đề nên cách cũ bỏ sót cả bảng). Một bảng chỉ được nhận khi các số tự thỏa đẳng thức của báo cáo và chỉ có đúng một bộ số thỏa:

- Cân đối kế toán: tổng tài sản = nợ phải trả + vốn chủ sở hữu (cột cuối kỳ), và bằng tổng nguồn vốn nếu đọc được.
- Kết quả kinh doanh: doanh thu thuần − giá vốn = lợi nhuận gộp; lợi nhuận thuần + lợi nhuận khác = trước thuế; trước thuế − thuế = sau thuế (hoặc 61 + 62 = 60). Báo cáo trải trên hai trang liền nhau được gộp.
- Lưu chuyển tiền tệ: dòng tiền kinh doanh + đầu tư + tài chính = lưu chuyển tiền thuần.
- Loại bảng tính bằng nghìn/triệu đồng và tổng tài sản ngoài khoảng 5×10¹⁰–5×10¹⁴ đồng; nhiều bộ số thỏa cùng lúc (vd báo cáo riêng và hợp nhất trong một file) thì bỏ qua, không đoán.
- Số bị OCR bỏ sót trong một dòng được gán vào đúng cột theo tọa độ; tồn kho chỉ nhận khi 140 = 141 + 149 đủ ba dòng.

Phạm vi (hợp nhất/riêng) lấy từ tiêu đề trang bằng so khớp mờ; không xác định được thì ghi "theo báo cáo".

Độ chính xác đã đo: chạy bộ trích lên MCM và QNS rồi so với số đối chiếu tay: **95 số khớp, 0 sai** (`tests/test_consumer_extract.py`).
Đối chiếu trực tiếp với PDF gốc cho KDC Q3/2026 (6 số: doanh thu, trước thuế, sau thuế, quý và lũy kế 9 tháng): khớp từng chữ số.
Phép kiểm chéo lũy kế = lũy kế kỳ trước + riêng quý khớp 55/78 trường hợp; các trường hợp lệch còn lại do công ty trình bày lại số kỳ trước (như MCM, QNS đã ghi ở `consumer_period_checks.json`) hoặc do báo cáo Q1/2025 của BHN là báo cáo riêng, không do trích sai.

Trang bị OCR hỏng thường là trang xoay ngang. Chạy lại bằng `python -m src.ingest.consumer_ocr --windows-ocr --retry-poor --company <MÃ>` (tự thử xoay 90°/−90°/180°), rồi `python -m src.ingest.build_consumer_db`.

Bố cục đã xử lý thêm (2026-11-22, sau khi phát hiện tổng tài sản KIDO 2025 "chưa có số" dù có trong PDF):
- **Trang in hai trang A5 cạnh nhau** (báo cáo thường niên): cột số của nửa trái nằm ở x < 0,37 của trang, ngoài vùng quy tắc trang đơn giả định. Bộ trích tách trang có khe giữa thành hai trang con (chỉ THÊM ứng viên, không thay trang gốc) rồi áp dụng quy tắc như cũ.
  Kết quả: báo cáo năm KIDO 2025 từ 4 lên 13 chỉ tiêu, tổng tài sản **13.907,2 tỷ** (báo cáo năm đã kiểm toán, đối chiếu ảnh trang PDF), khác 13.980,8 tỷ của báo cáo quý 4 chưa kiểm toán.
- **Chỉ tiêu mở rộng** (`EXTRA_METRICS`): tài sản ngắn hạn, tài sản dài hạn, nợ ngắn hạn, nợ dài hạn, giá vốn hàng bán; chỉ nhận khi đẳng thức tổng phụ đúng (ngắn + dài = tổng; doanh thu − giá vốn = lợi nhuận gộp). Cộng lại bằng đúng tổng đã đối chiếu tay của MCM/QNS (`tests/test_insight.py`).
- **Tổng tài sản = tổng nguồn vốn (440)** khi dòng 270/280 không đọc được; **dòng 10/11/20 bị OCR bỏ sót** được suy ra từ hai dòng còn lại và chỉ nhận khi số suy ra xuất hiện đúng như một ô số trên trang.
- Báo cáo thường niên Masan (MCH) không có cột mã số nên không trích được; câu hỏi "năm 2025" của MCH lấy từ báo cáo quý 4/2025 (lũy kế 12 tháng, số dư cuối năm) và ghi rõ là chưa kiểm toán.
- Có số lũy kế mà không có số riêng quý thì câu trả lời nêu số lũy kế (ghi rõ), không nói "chưa có".

Độ phủ sau khi trích: 5 chỉ số chung (biên gộp, trước thuế, ròng, nợ/vốn chủ, nợ/tổng tài sản) tính được **328/400 (82%)** ô công ty × quý có báo cáo (299/400 trước khi xử lý các bố cục trên, khoảng một phần ba ban đầu); số chỉ tiêu tự động tăng từ 615 lên 1.073 mà không số cũ nào đổi giá trị.
Còn thiếu chủ yếu do trang kết quả kinh doanh hoặc cân đối vẫn bị OCR đọc nhiễu (SAB, QNS 2025, CMF, PAN Q3/2026, BBC Q2/2026 chưa có báo cáo); các ô này hiện "Chưa có số đối chiếu".
Kiểm tra nhất quán: hỏi mọi chỉ tiêu cho 11 công ty ở 3 kỳ (416 câu), câu trả lời khớp cơ sở dữ liệu ở cả 416 câu (có số thì nêu số, không có thì nói chưa có).

## Thử trên chatbot

- Doanh thu thuần riêng Q3/2026 của MCM là bao nhiêu?
- So sánh doanh thu thuần Q3/2026 của MCM và QNS.
- Thuyết minh hàng tồn kho của QNS năm 2025.
- Doanh thu quý hai năm 2025 của Đường Quảng Ngãi.
- Báo cáo tài chính quý 2/2025 của Cholimex Food.
- Báo cáo niên độ 2025–2026 của AgriS.

## Hỏi đáp trên chữ trong PDF (2026-11-22)

Bảng `document_chunks` (18.827 đoạn chữ OCR của 99 PDF) và `data/processed/chunks.jsonl` (Vinamilk) được `src/consumer/docqa.py` dùng để trả lời câu hỏi không phải số liệu:
- **Người** ("chủ tịch Masan là ai", "Hội đồng quản trị gồm những ai"): trích xác định từ dòng chữ có dạng "Ông/Mr Tên Chức danh"; chọn bản đọc rõ nhất (ít chữ lạ như å, ö, ü nhất), cùng độ rõ thì lấy kỳ mới nhất; dòng có ghi bổ nhiệm/miễn nhiệm thì không kết luận "hiện tại", chỉ trích nguyên văn.
- **Câu hỏi khác**: BM25 trên toàn bộ đoạn, rồi chỉ giữ đoạn có các từ khóa có nghĩa (từ hiếm nặng gấp đôi từ thông dụng) nằm trong cùng 3 dòng liền nhau. Đủ ý mới nói "tìm thấy"; khớp một phần thì ghi "chỉ khớp một phần"; dưới 60% thì nói không tìm thấy.
- Câu trả lời luôn kèm đoạn chữ gốc, tài liệu, kỳ, trang và liên kết PDF. Không có bước nào sinh chữ ngoài PDF; hàm `grounded` (tên riêng, số và trích dẫn [n] phải nằm trong đoạn trích) đã có sẵn để bật tóm tắt bằng Gemini sau này, mặc định chưa bật.
- Gợi ý câu hỏi tương tự chỉ gồm chủ đề mà chính câu gợi ý tìm thấy kết quả trong PDF của công ty đó.
- Hạn chế: OCR nhiễu (SAB, BHN, MCM...) làm sai dấu hoặc mất ký tự trong tên; báo cáo hai cột (KIDO) có thể trộn dòng nên chỉ có trích dẫn, không có câu trả lời tóm gọn.
