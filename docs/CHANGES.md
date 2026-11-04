# Thay đổi trên nhánh `feature/chart-explain-feedback`

Tài liệu cho nhóm cập nhật báo cáo (mục 2.4.2, 2.5.4 và Chương 3). Ba tính năng, không đụng vào `data/processed` và không chạy lại pipeline OCR.

## 1. Biểu đồ xu hướng và bảng so sánh kỳ (gợi ý cho mục 2.5.4 – giao diện)

- `src/agent/charts.py` (mới): `build_charts(tool_calls)` dựng khối dữ liệu từ **kết quả công cụ** (không từ câu trả lời của mô hình):
  `get_series` -> khối `series` (có biểu đồ nếu từ 2 kỳ), `get_growth` -> `comparison` (hai kỳ + thay đổi + %), `explain_change` -> `breakdown`.
  Khối `series` có thêm `summary` (cao nhất, thấp nhất, đầu, cuối, thay đổi, tăng trưởng) do code tính, giao diện hiện thành một dòng nhận xét.
  Bỏ khối trùng, tối đa 3 khối. Mỗi dòng có kỳ, giá trị VND, đơn vị (tỷ đồng, `scale` = 1e9) và nguồn (báo cáo, trang PDF, mã số).
- `api/index.py`: `/api/ask` trả thêm trường `charts` (mảng rỗng khi không có công cụ phù hợp). Các trường cũ giữ nguyên.
- `src/tools/analyst.py`: kết quả `get_growth` thêm `current_label` và `base_label` (nhãn kỳ) để bảng so sánh ghi đúng kỳ.
- `public/index.html`: vẽ cột bằng Chart.js 4.4.7 từ jsDelivr, ghim phiên bản và `integrity` (SRI sha384), nạp trễ khi có biểu đồ đầu tiên; kèm bảng số liệu bên dưới.
  Nếu CDN lỗi thì hiện thông báo và vẫn còn bảng. Số định dạng kiểu Việt Nam (chấm nghìn, phẩy thập phân). Có `aria-label` cho biểu đồ, bảng cuộn ngang trên màn hình nhỏ.

## 2. Công cụ `explain_change` (gợi ý cho mục 2.4.2 – công cụ của agent)

- `src/tools/explain.py` (mới), đăng ký trong `src/tools/registry.py` (`explain_change(metric, period, base="yoy"|"qoq", basis="quy"|"luy_ke")`).
- Hỗ trợ `loi_nhuan_sau_thue` và `doanh_thu_thuan`. Phép phân rã dựa trên đồng nhất thức KQKD:
  LNST = doanh thu thuần − giá vốn + (doanh thu TC − chi phí TC) + lãi liên kết − chi phí bán hàng − chi phí QLDN + hoạt động khác − thuế TNDN (hiện hành + hoãn lại).
  Doanh thu thuần = doanh thu bán hàng − các khoản giảm trừ.
- Mỗi khoản mục có `current`, `base`, `effect` (tác động lên chỉ tiêu; chi phí tăng thì âm) và `share`. Tổng `effect` = chênh lệch; nếu số liệu hai kỳ lệch
  (vd phân loại lại) thì thêm dòng "Khoản khác / chênh lệch phân loại" thay vì che đi. Với dữ liệu hiện có, tất cả kỳ và cơ sở đều khớp tuyệt đối, không phát sinh dòng này.
- Số "cùng kỳ năm trước" lấy từ cột so sánh của báo cáo kỳ hiện tại, giống `get_growth`, nên có thể khác số trong báo cáo gốc của năm trước (đã phân loại lại); kết quả có kèm lưu ý.
- `src/agent/prompts.py`: hướng dẫn dùng `explain_change` cho câu "vì sao/do đâu", dặn không suy đoán nguyên nhân kinh doanh; dặn dùng `get_series`/`get_growth` cho xu hướng.
- `guard.py` không đổi: số trong kết quả công cụ (cả giá trị cấu trúc lẫn `text`, gồm đóng góp, tỷ trọng, phần trăm) đã được coi là hợp lệ; số mô hình tự thêm vẫn bị bắt.

## 3. Phản hồi 👍/👎 (gợi ý cho Chương 3 – kết quả/đánh giá)

- `src/feedback.py` (mới): giao diện `FeedbackStore.save(record)`; `StdoutStore` (mặc định, một dòng `FEEDBACK {json}` trong log) và `WebhookStore`
  (`FEEDBACK_WEBHOOK_URL`, `FEEDBACK_WEBHOOK_TOKEN`, thời gian chờ 3 giây). Gắn dịch vụ khác (vd Vercel Blob) bằng cách thêm một lớp và trả về trong `get_store()`.
- `api/index.py`: `POST /api/feedback` nhận `{question (≤500), answer (≤8000), label ("up"|"down"), timestamp (tùy chọn)}`; 200 khi hợp lệ, 422 khi sai dữ liệu,
  429 khi gửi quá nhanh (bộ đếm riêng, không trừ vào lượt hỏi), 502 khi nơi lưu lỗi (log chỉ ghi tên loại lỗi). Bản ghi không có IP, tiêu đề hay khóa.
- `public/index.html`: nút 👍/👎 dưới mỗi câu trả lời, bấm xong hiện lời cảm ơn; lỗi mạng thì cho bấm lại.

## 4. Thiết kế lại giao diện (nhánh `feature/redesign-ui`) – gợi ý cho mục 2.5.4

- `public/index.html` viết lại theo bố cục hai cột; bản cũ giữ ở `public/index.old.html`. **CSS và JS nằm trong chính `index.html`** (không tách `styles.css`/`app.js`)
  vì `api/index.py` chỉ có route `/` và không được đổi backend; tách tệp thì chạy cục bộ bằng uvicorn sẽ không tải được. Trên Vercel tách được nếu muốn.
- Thanh bên: thương hiệu, "Cuộc trò chuyện mới", 5 mục menu (Trò chuyện, Tra cứu số liệu hoạt động; 3 mục còn lại "Sắp có" vì chưa có API), "GẦN ĐÂY" trong `localStorage`
  (đổi tên, xóa hai bước không dùng `confirm()`), chỉ báo DuckDB/Gemini từ `/api/health`.
- Thanh trên: tiêu đề cuộc trò chuyện (rút gọn từ câu hỏi đầu) và chọn kỳ (Q2/2026 … Q1/2025, Tất cả kỳ). Kỳ chỉ được thêm vào câu hỏi như gợi ý ngữ cảnh
  ("Nếu không nêu kỳ, hiểu là kỳ …"); lịch sử và hiển thị vẫn dùng câu hỏi gốc.
- Hội thoại: markdown an toàn tự dựng bằng DOM (đoạn, danh sách, đậm, nghiêng, mã, bảng; thẻ HTML trong câu trả lời hiện như chữ, không chạy), thẻ "Nguồn" thu gọn
  với ảnh trang PDF có khung đỏ, biểu đồ đường Chart.js 4.4.7 (ghim + SRI) kèm bảng khi có từ 2 kỳ, nút Sao chép, Tạo lại, 👍/👎 (biểu tượng SVG),
  nút Dừng (AbortController), lỗi 429/503/5xx/mất mạng có nút "Thử lại". Enter gửi, Shift+Enter xuống dòng, không gửi khi đang gõ dấu (IME).
- Responsive: dưới 900 px thanh bên thành ngăn kéo (`inert` khi đóng), lưới 1 cột, ô nhập dùng `dvh`; chế độ tối theo `prefers-color-scheme`; tôn trọng `prefers-reduced-motion`.
- Không đổi backend, `guard.py` hay dữ liệu. Chuỗi "Chatbot BCTC Vinamilk" được giữ trong `meta description` để test `test_health_and_static_page` (kiểm tra chuỗi này) vẫn đạt, tiêu đề tab là "Chatbot Phân Tích Tài Chính".

### Kiểm tra giao diện (Chrome headless, Gemini thật, máy chủ cục bộ)
Chạy ở 1440 px (sáng và tối), 768 px và 390 px (sáng): màn hình chào đúng chữ; chọn kỳ cập nhật mô tả và dòng phụ; hỏi bằng thẻ gợi ý nhận trả lời kèm nguồn, mở đúng ảnh trang PDF (q2-2026/11) có 1 khung đỏ;
câu xu hướng vẽ biểu đồ đường đủ 6 kỳ và bảng 6 dòng, câu một kỳ không vẽ; tải lại trang khôi phục hội thoại (cả biểu đồ); đổi tên, mở lại, xóa hai bước; giả lập 429, 503, dừng giữa chừng,
mất mạng (đều có "Thử lại", bấm lại hỏi được thật); câu trả lời dài có bảng, danh sách, mã; thẻ `<script>` và `<img onerror>` trong câu trả lời không chạy; chỉ báo Gemini đỏ khi `gemini_key=false`;
Tra cứu số liệu; không tràn ngang ở 390 và 768 px; console không có lỗi (ngoài lỗi mạng chủ động tạo khi giả lập ngoại tuyến).
Lighthouse (trang chào, máy tính để bàn): Accessibility 100, Best Practices 100, Performance 100.
Cả 6 thẻ gợi ý và một câu ngoài phạm vi được hỏi thật qua API với phần gợi ý kỳ: 6 câu trả lời được, câu ngoài phạm vi vẫn bị từ chối.

### Nhóm cần xác nhận (thiết kế lại)
1. **Ảnh mẫu không được đính kèm** trong yêu cầu thiết kế lại, chỉ có mô tả chữ; bố cục làm theo mô tả, chưa đối chiếu được với ảnh thật.
2. **Màu nhấn:** chọn đen (`#111418`, chế độ tối đảo thành sáng); đổi sang xanh dương đậm chỉ cần sửa biến `--accent` trong `public/css/app.css`.

## 5. Hoàn thiện các mục còn lại (nhánh `feature/redesign-ui`) – gợi ý cho mục 2.4.2, 2.5.4 và Chương 3

Ba mục menu từng để "Sắp có" nay đã chạy thật, cùng hàng số liệu ở màn hình chào. Nguyên tắc chung: **mọi con số lấy từ công cụ/dữ liệu qua API, không qua mô hình**,
dùng lại các khối dựng sẵn (`build_charts`, `source_links`) để Trò chuyện và các mục khác hiển thị giống nhau.

- **Thuyết minh & nguồn** (`POST /api/notes`, `src/notes.py`): cùng `HybridRetriever` với agent (chia sẻ một `Toolbox` để chỉ nạp chỉ mục một lần), lọc theo kỳ đang chọn,
  mặc định chỉ văn bản thuyết minh (tùy chọn gồm bảng số liệu). Mỗi kết quả kèm trang PDF, nhãn "văn bản OCR, cần đối chiếu", liên kết PDF chính thức **mở đúng trang** (`#page=N`) và ảnh trang nếu có.
- **Xu hướng & so sánh** (`POST /api/chart`): gọi thẳng `get_series`/`get_growth`/`explain_change` rồi dựng bằng `build_charts` như câu trả lời của trợ lý (biểu đồ đường, bảng, dòng nhận xét do code tính).
- **Thống kê** (`GET /api/stats`, `src/stats.py`): độ phủ theo kỳ (chuẩn mực TT200/TT99, số chỉ tiêu có số liệu, đoạn thuyết minh, ảnh trang) và ma trận chỉ tiêu × kỳ; đọc từ `Facts` trong bộ nhớ, lưu đệm.
  Cùng nguồn với hàng số liệu ở màn hình chào (6 kỳ · 50 chỉ tiêu · 959 đoạn · 50 trang PDF).
- **Trò chuyện:** thẻ Nguồn nay có "Ghi chú" (số suy ra từ lũy kế, số đã phân loại lại, số đã sửa OCR) từ trường `notes` mới của `/api/ask`; câu hỏi xu hướng nay có nguồn từng kỳ
  (`get_series` trả `sources`/`notes` cấp cao như các công cụ khác); liên kết PDF chính thức mở đúng trang.
- **`/api/health`** trả thêm `periods` (đọc thật DuckDB) nên chấm "DuckDB" xanh chỉ khi dữ liệu mở được. **`/api/lookup`** trả lý do khi không tra được và gợi ý chỉ tiêu gần nhất
  thay vì chuỗi rỗng; thông báo lỗi công cụ không còn bị bọc dấu nháy (`reason()` trong `analyst.py`).

### Tổ chức lại mã cho gọn và đồng nhất
- `api/index.py` chỉ còn định tuyến; logic dùng chung chuyển vào `src/web/` (`ratelimit.py`: `RateLimiter`; `sources.py`; `schemas.py`) và `src/paths.py`. Ba bộ giới hạn tốc độ: hỏi đáp (6/phút), tra cứu/thuyết minh/biểu đồ (30/phút), phản hồi (20/phút).
- Giao diện tách thành `public/index.html` (khung), `public/css/app.css` và các module ES trong `public/js/` (một module một trách nhiệm: `api.js` gọi API và đổi lỗi thành tiếng Việt,
  `charts.js`, `sources.js`, `markdown.js`, `dom.js`, …; mỗi màn hình một tệp trong `views/`). Backend nay phục vụ `public/` (kể cả `/pages/*.webp`) nên chạy cục bộ giống Vercel.
- Test: `test_health_and_static_page` đổi sang kiểm tra khung trang và các tệp `/js`, `/css` (đúng kiểu MIME) thay vì tìm chuỗi `/api/ask` trong HTML, vì mã nay nằm ở `js/chat.js`.

### Kiểm tra
Test: `test_tools` 17/17, `test_agent` 25/25, `test_api` 25/25. Trên Chrome headless với Gemini thật: hàng số liệu từ API; Thuyết minh (tìm theo kỳ, kèm bảng, không có kết quả, quá ngắn, đổi kỳ ở thanh trên);
Xu hướng (3 chỉ tiêu, so sánh, phân rã, tổ hợp không hợp lệ); Thống kê (4 thẻ, 6 dòng kỳ, 50 chỉ tiêu × 6 kỳ); hỏi đáp có ghi chú và biểu đồ, tải lại giữ nguyên; 390 px không tràn ngang ở cả 5 màn hình; console không lỗi.

### Nhóm cần xác nhận (hoàn thiện)
1. **Ảnh trang thuyết minh:** repo chỉ có 50 ảnh trang (chủ yếu ba báo cáo chính); 346 trong 384 trang có đoạn thuyết minh **chưa có ảnh** vì PDF gốc (`data/raw`) không có trên máy dựng. Mục Thuyết minh ghi rõ "chưa có ảnh trang N" và mở PDF chính thức đúng trang cho Q1/Q2/2026;
   bốn kỳ 2025 chưa có liên kết PDF nên trỏ về trang báo cáo của Vinamilk (cần bổ sung `OFFICIAL_PDF_URLS` trong `src/web/sources.py`). Muốn đủ ảnh: chạy `src/ingest/render_pages.py` ở máy có PDF (~30 MB thêm vào git).
2. **Nhãn "959 đoạn thuyết minh"** tính cả 72 đoạn bảng số liệu (tổng chỉ mục = 959); thẻ ở màn hình Thống kê ghi "đoạn văn bản và bảng đã lập chỉ mục".
3. **Biểu đồ trong Trò chuyện** chỉ hiện khi mô hình chọn gọi `get_series`/`get_growth`/`explain_change` (đo 8/8 lần với câu xu hướng qua API, nhưng một lần trong lúc kiểm tra giao diện mô hình không gọi). Mục Xu hướng & so sánh luôn vẽ được vì không qua mô hình.
4. **Thẻ gợi ý số 6 (khoản vay):** đôi khi mô hình tự cộng vay ngắn hạn và dài hạn (8.454,9 tỷ), con số đúng nhưng không do công cụ trả nên `guard.py` cảnh báo "không khớp". Cân nhắc bổ sung chỉ tiêu "tổng nợ vay" hoặc đổi câu.
5. **Lần tìm thuyết minh đầu tiên** sau khi khởi động hàm mất vài giây (dựng chỉ mục BM25); trên Vercel mỗi lần hàm "nguội" bị khởi động lại sẽ chịu độ trễ này.
6. Có xóa `public/index.old.html` hay không.

## Kiểm thử

| Bộ test | Trước | Sau |
|---|---|---|
| tests/test_tools.py | 10/10 đạt | 17/17 đạt (thêm 3 test `explain_change`, 4 test thống kê/thuyết minh/thông báo lỗi) |
| tests/test_agent.py | 23/23 đạt | 25/25 đạt (thêm 2 test: guard với số phân rã, khai báo công cụ/prompt) |
| tests/test_api.py | 8/8 đạt | 25/25 đạt (biểu đồ 6 kỳ, câu một kỳ không biểu đồ, bảng so sánh/phân rã, phản hồi 200/422/429/502, webhook, không lộ khóa/IP) |

Kiểm tra tay (Chrome headless, Gemini thật, máy chủ cục bộ): câu xu hướng 6 quý, so sánh cùng kỳ, câu một kỳ, câu "vì sao lợi nhuận tăng", bấm 👍; giao diện 390 px không tràn ngang; console không có lỗi.

## Điều nhóm nên xác nhận

1. Biểu đồ và bảng chỉ xuất hiện khi mô hình **chọn gọi** `get_series`/`get_growth`/`explain_change`. Mô hình có thể gọi thêm `get_growth` khi hỏi xu hướng nên hiện thêm bảng so sánh; chưa lọc bớt.
2. Phần lưu phản hồi mặc định chỉ ghi log Vercel (log không lưu lâu). Muốn thống kê cần gắn webhook hoặc dịch vụ lưu trữ; chưa chọn dịch vụ nào.
3. Phản hồi có lưu nguyên văn câu hỏi; người dùng có thể gõ thông tin cá nhân vào câu hỏi. Có thể cần dòng thông báo quyền riêng tư.
4. Giao diện chỉ hỗ trợ **đậm**; Markdown khác (`###`, `*nghiêng*`) từ Gemini vẫn hiện nguyên ký tự (đã có từ trước, chưa sửa).
5. Chưa đo chất lượng câu trả lời diễn giải của Gemini; chỉ kiểm tra số liệu và cấu trúc.

## 6. Thanh bên dọc làm lại, đổi tông màu

- Quay lại bố cục dọc (thanh bên + vùng nội dung) nhưng làm gọn: thanh bên thu gọn thành thanh biểu tượng 72 px (nút trên đầu thanh bên, lưu `vnm.rail.v1`; chỉ máy tính, điện thoại vẫn là ngăn kéo),
  chữ nhãn bọc `<span class="t">` nên thu gọn chỉ bằng CSS, không thêm logic.
- Giao diện mới: bảng màu chàm-tím thay màu đen/xanh đậm (mọi màu ở `:root`, có bản tối), nút chính và biểu tượng dùng chung một biến `--grad`, bo góc 14–24 px, bóng mềm,
  tiêu đề gradient, mục đang chọn có vạch màu, ô nhập sáng viền khi focus, bong bóng câu hỏi màu chàm, đường biểu đồ lấy màu `--accent`.
- Màn hình chào thêm 4 ô lối tắt (Tra cứu, Thuyết minh, Xu hướng, Thống kê) để các chức năng chính không chỉ nằm trong menu; câu gợi ý hiện dạng thẻ 2 cột.
- Không đổi backend, API hay dữ liệu. Test `test_api` 25/25, `test_tools` 17/17, `test_agent` 25/25; Chrome thật: 5 màn hình, đổi kỳ, hỏi đáp thật, đổi tên, thu gọn, chế độ tối,
  390 px không tràn ngang, console sạch. Đã thay các ảnh trong `docs/screenshots/`.

## 7. Bỏ mục "Thuyết minh & nguồn"

- Bỏ mục này theo yêu cầu: xóa `POST /api/notes`, `src/notes.py`, `NotesBody`, `public/js/views/notes.js`, màn hình, mục menu, ô lối tắt và `NOTE_EXAMPLES`; bỏ 2 test API và 1 test công cụ (còn api 23, tools 16, agent 25).
- Hỏi đáp vẫn tìm được nội dung thuyết minh (agent dùng `HybridRetriever`), thẻ "Nguồn" vẫn có trang PDF, ảnh trang và ghi chú. Chỉ thay đổi: không còn màn hình tìm thuyết minh riêng.
- Các đoạn ở mục 5 và 2.x nhắc tới mục này là lịch sử, không còn đúng với mã hiện tại.

## 8. Thanh bên kiểu Copilot, thêm "Chỉ số tài chính", bỏ "Thống kê"

- Thanh bên đơn giản: 2 mục bắt buộc (Cuộc trò chuyện mới, Tìm kiếm) và 3 chức năng dùng nhiều nhất (Tra cứu số liệu, Xu hướng & so sánh, Chỉ số tài chính). Bỏ mục "Trò chuyện" (đã có "Cuộc trò chuyện mới"),
  bỏ màn hình "Thống kê" (ít dùng); `/api/stats` giữ lại cho hàng số liệu ở màn hình chào. Đổi lại bảng màu trung tính (nền ấm, nút chính màu mực) thay cho tông chàm-tím.
- **Tìm kiếm** lọc danh sách cuộc trò chuyện theo tiêu đề và nội dung, bỏ dấu để gõ "thuan" vẫn ra "thuần"; Esc đóng; khi thanh bên đang thu gọn thì bấm Tìm kiếm sẽ mở rộng ra. Thuần phía trình duyệt, không gọi máy chủ.
- **Chỉ số tài chính**: `POST /api/ratios` (`src/ratios.py`) gọi `Analyst.ratio` cho 14 tỷ số theo 5 nhóm (Sinh lời, Chi phí, Thanh khoản, Đòn bẩy, Hoạt động) của một kỳ, kèm thay đổi so với
  quý liền trước (lũy kế: cùng kỳ năm trước), đường nhỏ 6 kỳ, số quy năm (ROE, ROA, vòng quay), công thức và nguồn trang PDF. Mũi tên chỉ hướng, không tô xanh/đỏ vì chỉ số tăng không phải lúc nào cũng tốt (vd tỷ lệ chi phí).
- Test: `test_api` 25/25 (thêm 2 test cho `/api/ratios`), `test_tools` 16/16, `test_agent` 25/25. Chrome thật: 5 mục thanh bên, tìm kiếm (có dấu, không dấu, không thấy), thu gọn, Chỉ số tài chính (14 thẻ, đổi kỳ/cách tính),
  hỏi đáp thật, chế độ tối, 390 px không tràn ngang, console sạch.

## 9. Giao diện hiện đại hơn, sửa phông chữ, câu trả lời đúng trọng tâm

- **Phông chữ:** bỏ `Inter` (không được tải nên mỗi máy hiện một kiểu), dùng bộ phông hệ thống hỗ trợ tiếng Việt đầy đủ (`Segoe UI Variable/Segoe UI`, `system-ui`, `Roboto`...). Cỡ chữ gom về một thang 7 bậc (`--fs-xs` ... `--fs-2xl`) thay cho 15 cỡ lẻ;
  tiêu đề bỏ `weight 800`, `letter-spacing` âm và `line-height` 1.15 (làm dấu thanh bị dính/cắt) sang `700`, `1.3`. Chart.js dùng đúng phông của trang. Mũi tên thay đổi của chỉ số dùng biểu tượng SVG thay cho ký tự ▲▼■ (hiện lệch phông tùy máy).
  Số trong câu trả lời và bảng dùng chữ số đều bề rộng (`tabular-nums`).
- **UI/UX:** trợ lý có avatar; tin nhắn mới xuất hiện mượt (chỉ tin cuối, không phát lại cả hội thoại); khung xám "đang tải" thay chữ trơn ở Hỏi đáp và Chỉ số tài chính; bảng có hàng sáng khi rê chuột;
  phím tắt `Ctrl/Cmd+K` mở Tìm kiếm và `/` nhảy vào ô nhập; tôn trọng `prefers-reduced-motion`. Đã sửa lỗi chèn chữ "null" vào cuối câu trả lời do `append(null)` (phát hiện qua ảnh chụp).
- **Câu trả lời:** prompt thêm mục "Cách trình bày": câu đầu trả lời thẳng (số chính, kỳ, đơn vị), không lời dẫn, không số VND đầy đủ nếu không được hỏi, không dòng "Nguồn:", một số liệu 1–2 câu, so sánh một câu, từ ba chỉ tiêu dùng bảng,
  "vì sao" nêu hai khoản đóng góp lớn nhất, thuyết minh chỉ nêu điều văn bản có ghi. `src/agent/answer.py`: `tidy_answer` xóa dòng nguồn mô hình vẫn lỡ viết (chỉ phần trích "trang N", giữ nguyên lưu ý và nội dung),
  `used_sources` chỉ giữ nguồn của công cụ có số xuất hiện trong câu trả lời (câu định tính thì giữ hết) nên thẻ Nguồn không còn kèm 10 trang không liên quan. `guard.py` tách `matches_pool` dùng chung.
- Test: `test_agent` 28/28 (thêm 3), `test_tools` 16/16, `test_api` 25/25. Ví dụ trước/sau (Q2/2026): "Doanh thu thuần ... là 18.847,3 tỷ đồng (chi tiết: 18.847.347.464.988 VND). *Nguồn: ... trang PDF 11, chỉ tiêu mã 10.*" thành
  "Doanh thu thuần quý 2/2026 của Vinamilk là 18.847,3 tỷ đồng."; tổng quan quý 1/2026 là một bảng 6 dòng thay cho danh sách có nguồn lặp từng dòng.
