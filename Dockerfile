# API-only image (dashboard still uses Vite locally or a static host + /api proxy).
# Build:  docker build -t kalshibot-api .
# Run:    docker run --rm -p 8765:8765 --env-file .env -v kalshibot-data:/data kalshibot-api
# Mount a volume for /data so SQLITE_PATH=data/bot.sqlite3 persists (default in .env.example).

FROM python:3.12-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN adduser --system --group --uid 10001 appuser

FROM base AS deps
COPY requirements.txt .
RUN pip install --no-cache-dir -U pip && pip install --no-cache-dir -r requirements.txt

FROM base
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin
COPY backend ./backend

RUN mkdir -p /app/data /app/data/logs && chown -R appuser:appuser /app

USER appuser

ENV PYTHONUNBUFFERED=1
ENV KALSHI_BOT_PORT=8765

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${KALSHI_BOT_PORT:-8765}/api/health" || exit 1

CMD ["sh", "-c", "exec uvicorn backend.app.main:app --host 0.0.0.0 --port ${KALSHI_BOT_PORT:-8765}"]
