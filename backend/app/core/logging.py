from __future__ import annotations

import logging
import sys
import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from structlog.typing import Processor

from ..settings_env import env

_configured: bool = False


def _log_level() -> int:
    name = (env.log_level or "INFO").upper()
    return getattr(logging, name, logging.INFO)


def _foreign_pre_chain() -> list[Processor]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.ExtraAdder(),
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
    ]


def _console_renderer() -> Processor:
    use_colors = sys.stdout.isatty() and not env.log_json
    return structlog.dev.ConsoleRenderer(colors=use_colors)


def _json_renderer() -> Processor:
    return structlog.processors.JSONRenderer(sort_keys=True)


def configure_logging() -> None:
    """
    structlog + stdlib: existing ``logging.getLogger(__name__)`` call sites stay unchanged; messages
    go through `ProcessorFormatter` (colored console when LOG_JSON is off, one-line JSON when on).
    """
    global _configured
    if _configured:
        return
    _configured = True

    processor: Processor = _json_renderer() if env.log_json else _console_renderer()
    fmt = structlog.stdlib.ProcessorFormatter(
        processor=processor,
        foreign_pre_chain=_foreign_pre_chain(),
    )
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(fmt)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    level = _log_level()
    root.setLevel(level)
    for noisy in ("httpx", "httpcore", "hpack", "h11"):
        logging.getLogger(noisy).setLevel(max(logging.WARNING, level))


def reset_uvicorn_loggers_to_root() -> None:
    """
    Uvicorn attaches its own stream handlers; drop them and propagate to the structlog root handler
    so error/access lines are formatted consistently in production.
    """
    level = _log_level()
    for name in (
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
    ):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.setLevel(level)
        lg.propagate = True
    fl = logging.getLogger("fastapi")
    fl.handlers.clear()
    fl.propagate = True


def clear_logging_config_for_tests() -> None:
    """Test hook: allow a second `configure_logging()` in-process."""
    global _configured
    _configured = False


class RequestContextMiddleware(BaseHTTPMiddleware):
    """
    Binds structlog contextvars: ``request_id`` (from X-Request-Id or a new UUID), ``path``, ``method``.
    Emits `X-Request-Id` on the response. Runs outermost in the ASGI stack (add last in FastAPI).
    """

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        structlog.contextvars.clear_contextvars()
        existing = (request.headers.get("x-request-id") or request.headers.get("X-Request-Id") or "").strip()
        request_id = existing or str(uuid.uuid4())
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            path=str(request.url.path),
            method=request.method,
        )
        try:
            response = await call_next(request)
            response.headers["X-Request-Id"] = request_id
            return response
        finally:
            structlog.contextvars.clear_contextvars()
