# Thay đổi trên nhánh `feature/chart-explain-feedback`

Tài liệu cho nhóm cập nhật báo cáo (mục 2.4.2, 2.5.4 và Chương 3). Ba tính năng, không đụng vào `data/processed` và không chạy lại pipeline OCR.

## 1. Biểu đồ xu hướng và bảng so sánh kỳ (gợi ý cho mục 2.5.4 – giao diện)

- `src/agent/charts.py` (mới): `build_charts(tool_calls)` dựng khối dữ liệu từ **kết quả công cụ** (không từ câu trả lời của mô hình):
  `get_series` -> khối `series` (có biểu đồ nếu từ 2 kỳ), `get_growth` -> `comparison` (hai kỳ + thay đổi + %), `explain_change` -> `breakdown`.
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
