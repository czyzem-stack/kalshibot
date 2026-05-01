"""Minimal HTML when the API is opened in a browser (Vite dev server hosts the real UI)."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["meta"])

_ROOT_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Kalshi Bot API</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 42rem; margin: 2rem auto; padding: 0 1rem;
           background: #0b1020; color: #e8ecff; line-height: 1.5; }
    a { color: #6ee7ff; }
    code { background: #121a33; padding: 0.1rem 0.35rem; border-radius: 4px; }
  </style>
</head>
<body>
  <h1>Kalshi Bot API</h1>
  <p>This port serves the <strong>backend API</strong> (JSON), not the React dashboard.</p>
  <ul>
    <li><a href="/docs">Swagger UI</a></li>
    <li><a href="/api/health">Health</a></li>
    <li><a href="/api/dashboard">Dashboard JSON</a></li>
  </ul>
  <p>Dashboard: <code>cd frontend && npm run dev</code> → <a href="http://localhost:5173">http://localhost:5173</a></p>
</body>
</html>
"""


@router.get("/", response_class=HTMLResponse)
async def root_page() -> str:
    return _ROOT_HTML
