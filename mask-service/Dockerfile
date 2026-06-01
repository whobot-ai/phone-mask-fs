FROM python:3.12-slim

WORKDIR /app

# 系统依赖（asyncpg 需要 libpq）
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 非root用户运行
RUN useradd -m appuser && chown -R appuser /app
USER appuser

EXPOSE 8080

CMD ["uvicorn", "run:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2"]
