FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

ENV PYTHONPATH=/app

EXPOSE 8000

# Migrations run inside the app lifespan (background). Do not block uvicorn on ensure_schema — a large DB
# can take minutes and would leave :8000 closed (no /health). Optional: set AI_BIZ_OS_SCHEMA_ALREADY_APPLIED=1
# if you run ensure_schema in an init container before starting this process.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
