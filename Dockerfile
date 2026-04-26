# API-only image (dashboard still uses Vite locally or a static host + /api proxy).
# Build:  docker build -t kalshibot-api .
# Run:    docker run --rm -p 8765:8765 --env-file .env -v kalshibot-data:/data kalshibot-api
# Mount a volume for /data so SQLITE_PATH=data/bot.sqlite3 persists (default in .env.example).

FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -U pip && pip install --no-cache-dir -r requirements.txt

COPY backend ./backend

ENV PYTHONUNBUFFERED=1
ENV KALSHI_BOT_PORT=8765

EXPOSE 8765

CMD ["sh", "-c", "exec uvicorn backend.app.main:app --host 0.0.0.0 --port ${KALSHI_BOT_PORT:-8765}"]
