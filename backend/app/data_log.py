"""Append-only JSONL logs under ``DATA_LOG_DIR`` (default ``data/logs``)."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_repo_root = Path(__file__).resolve().parents[2]
_lock = threading.Lock()


def _resolved_log_dir() -> Path:
    from .settings_env import env

    raw = (
        getattr(env, "data_log_dir", None) or str(_repo_root / "data" / "logs")
    ).strip()
    p = Path(raw)
    if not p.is_absolute():
        p = _repo_root / p
    return p


def append_event(stream: str, record: dict[str, Any]) -> None:
    """
    Append one JSON object per line to ``<log_dir>/<stream>/YYYY-MM-DD.jsonl``.
    Streams: ``signals``, ``trades``, ``equity``, ``system``. Never raises to callers.
    """
    try:
        from .settings_env import env

        if not getattr(env, "data_logging_enabled", True):
            return
        if not stream or not isinstance(record, dict):
            return
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = _resolved_log_dir() / stream / f"{day}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, separators=(",", ":"), default=str) + "\n"
        with _lock:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line)
    except Exception:
        return


def maybe_log_equity(record: dict[str, Any]) -> None:
    from .settings_env import env

    if not getattr(env, "data_log_equity", False):
        return
    append_event("equity", record)
