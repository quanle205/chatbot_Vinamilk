# duanNLP - Chatbot phân tích BCTC hợp nhất Vinamilk 2025-2026

| Thư mục | Nội dung |
|---|---|
| data/raw | PDF BCTC hợp nhất q1-2025 ... q2-2026 |
| data/interim | kết quả OCR (financial_rows.csv, *.jsonl), statements_long.csv |
| data/processed | financials.duckdb, overrides.csv, chunks.jsonl |
| src/ingest | preprocess.py (PDF->OCR), parse_statements.py, repair_identities.py |
| src/rag | chunking, BM25 + vector + RRF (`python -m src.rag.chunking`, `python -m src.rag.build_index`) |
| src/tools | tra số từ DuckDB, tỷ số, tăng trưởng, máy tính (`TOOL_SPECS`, `call_tool`); kiểm thử: `python tests/test_tools.py` |
| src/agent | agent Claude tool-use (Vertex AI) gọi công cụ tra số + retriever; kiểm tra số trong câu trả lời bám nguồn |
| app | giao diện Streamlit (`streamlit run app/streamlit_app.py`) |
| deploy, Dockerfile | triển khai Google Cloud Run (`deploy/cloudrun.ps1`, mặc định chỉ in lệnh) |

## Chạy chatbot

Claude chạy trên Google Cloud Vertex AI, cần dự án GCP đã bật Claude Opus 5.5 trong Model Garden:

```
gcloud auth application-default login
$env:ANTHROPIC_VERTEX_PROJECT_ID = "ten-du-an"      # tùy chọn: CLOUD_ML_REGION (mặc định global), VINAMILK_MODEL
streamlit run app/streamlit_app.py
```

Không có cấu hình Vertex thì tab "Tra số trực tiếp" vẫn dùng được. Kiểm thử (không gọi Claude thật):
`python tests/test_tools.py`, `python tests/test_agent.py`, `python tests/test_app.py`.

Triển khai: Cloud Run (`deploy/cloudrun.ps1`, dùng tài khoản dịch vụ, không cần GitHub) hoặc Streamlit Community Cloud
(cần đẩy repo lên GitHub, đặt `ANTHROPIC_VERTEX_PROJECT_ID` và bảng `[gcp_service_account]` trong Secrets của ứng dụng;
không bao giờ commit file khóa JSON).
| app, eval, notebooks | giao diện, đánh giá, thử nghiệm |

Pipeline: preprocess.py -> parse_statements.py -> repair_identities.py (đọc data/processed/overrides.csv) -> build_db.py (data/processed/financials.duckdb).
