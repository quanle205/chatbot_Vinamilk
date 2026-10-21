# Ảnh chạy giao diện chatbot trên Cloud Run. Build: gcloud run deploy --source . (xem deploy/cloudrun.ps1)
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8080
WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY app ./app
COPY data/processed/financials.duckdb data/processed/chunks.jsonl ./data/processed/
# Dựng chỉ mục truy xuất ngay trong ảnh (không copy retriever.pkl) để tránh lệch phiên bản scikit-learn khi nạp pickle.
RUN python -m src.rag.build_index

RUN useradd --create-home app && chown -R app /srv
USER app
EXPOSE 8080
CMD ["sh", "-c", "streamlit run app/streamlit_app.py --server.port=${PORT} --server.address=0.0.0.0 --server.headless=true --browser.gatherUsageStats=false"]
