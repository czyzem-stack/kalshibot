from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

# Paths that never require a bearer when KALSHI_API_BEARER_TOKEN is set.
# CORS preflight (OPTIONS) is always allowed for any path.
_PUBLIC_PATHS: frozenset[str] = frozenset(
    {
        "/",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/favicon.ico",
    }
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Lightweight hardening: no CSP here (varies with deployment); block sniffing, reduce MIME risk."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        resp = await call_next(request)
        path = request.url.path
        if path.startswith("/api/dashboard"):
            resp.headers["Cache-Control"] = "no-store"
        # Do not set CSP (would break /docs and arbitrary dashboard hosts); HSTS belongs on reverse proxy.
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        return resp


class ApiBearerAuthMiddleware(BaseHTTPMiddleware):
    """If ``token`` is non-empty, require ``Authorization: Bearer <token>`` for /api (except public health + docs)."""

    def __init__(self, app: ASGIApp, *, token: str) -> None:
        super().__init__(app)
        self._token = token.strip()

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not self._token:
            return await call_next(request)
        if request.method == "OPTIONS":
            return await call_next(request)
        path = request.url.path
        if path in _PUBLIC_PATHS or path.startswith("/api/health"):
            return await call_next(request)
        if path.startswith("/api"):
            auth = (request.headers.get("authorization") or "").strip()
            expected = f"Bearer {self._token}"
            if auth != expected:
                return JSONResponse(
                    status_code=401,
                    content={
                        "detail": "Unauthorized — set Authorization: Bearer <KALSHI_API_BEARER_TOKEN>."
                    },
                )
        return await call_next(request)
