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

### Nhóm cần xác nhận
1. **Ảnh mẫu không được đính kèm** trong yêu cầu, chỉ có mô tả chữ; bố cục làm theo mô tả, chưa đối chiếu được với ảnh thật.
2. **Màu nhấn:** chọn đen (xám đậm `#111418`, chế độ tối đảo thành sáng); đổi sang xanh dương đậm chỉ cần sửa `--accent`.
3. **Hàng số liệu:** chỉ còn "6 kỳ báo cáo" vì chưa có API trả số chỉ tiêu, số đoạn thuyết minh, số trang PDF; đếm ở trình duyệt không được. Muốn đủ 4 số cần thêm endpoint thống kê (đụng backend, chưa làm).
4. **Chỉ báo "DuckDB 6 kỳ"** hiện xanh khi `/api/health` trả `ok`, nhưng `/api/health` hiện không kiểm tra riêng DuckDB.
5. **Ghi chú số suy ra/đã sửa OCR** trong thẻ Nguồn chưa hiển thị được: `/api/ask` không trả `notes` (chỉ có `warnings`). Câu trả lời của mô hình thường tự nêu lưu ý này trong văn bản.
6. **Nguồn của câu xu hướng:** `get_series` không trả `sources` cấp cao nên thẻ "Nguồn" trống; nguồn từng kỳ nằm trong cột "Nguồn" của bảng.
7. **Thẻ gợi ý số 6 (khoản vay):** trả lời được nhưng đôi khi mô hình tự cộng vay ngắn hạn và dài hạn (8.454,9 tỷ), con số này bị `guard.py` cảnh báo "không khớp" dù đúng số học. Nên cân nhắc bổ sung chỉ tiêu "tổng nợ vay" hoặc đổi câu.
8. **Mục menu "Sắp có":** Thuyết minh & nguồn, Xu hướng & so sánh, Thống kê (cần thêm API). Có xóa `public/index.old.html` hay không.
9. **Ảnh trang PDF** chỉ hiện khi tệp tĩnh `public/pages` được phục vụ (Vercel làm việc này; chạy `uvicorn api.index:app` thuần thì ảnh trả 404 như trước đây). Để thử cục bộ, có thể mount thêm `/pages` trong một tệp chạy riêng.

## Kiểm thử

| Bộ test | Trước | Sau |
|---|---|---|
| tests/test_tools.py | 10/10 đạt | 13/13 đạt (thêm 3 test `explain_change`) |
| tests/test_agent.py | 23/23 đạt | 25/25 đạt (thêm 2 test: guard với số phân rã, khai báo công cụ/prompt) |
| tests/test_api.py | 8/8 đạt | 16/16 đạt (biểu đồ 6 kỳ, câu một kỳ không biểu đồ, bảng so sánh/phân rã, phản hồi 200/422/429/502, webhook, không lộ khóa/IP) |

Kiểm tra tay (Chrome headless, Gemini thật, máy chủ cục bộ): câu xu hướng 6 quý, so sánh cùng kỳ, câu một kỳ, câu "vì sao lợi nhuận tăng", bấm 👍; giao diện 390 px không tràn ngang; console không có lỗi.

## Điều nhóm nên xác nhận

1. Biểu đồ và bảng chỉ xuất hiện khi mô hình **chọn gọi** `get_series`/`get_growth`/`explain_change`. Mô hình có thể gọi thêm `get_growth` khi hỏi xu hướng nên hiện thêm bảng so sánh; chưa lọc bớt.
2. Phần lưu phản hồi mặc định chỉ ghi log Vercel (log không lưu lâu). Muốn thống kê cần gắn webhook hoặc dịch vụ lưu trữ; chưa chọn dịch vụ nào.
3. Phản hồi có lưu nguyên văn câu hỏi; người dùng có thể gõ thông tin cá nhân vào câu hỏi. Có thể cần dòng thông báo quyền riêng tư.
4. Giao diện chỉ hỗ trợ **đậm**; Markdown khác (`###`, `*nghiêng*`) từ Gemini vẫn hiện nguyên ký tự (đã có từ trước, chưa sửa).
5. Chưa đo chất lượng câu trả lời diễn giải của Gemini; chỉ kiểm tra số liệu và cấu trúc.
