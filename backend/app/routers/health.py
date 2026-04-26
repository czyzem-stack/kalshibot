"""Liveness, deep health, and storage metadata (no heavy I/O in basic health)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter

from ..settings_env import env
from .. import state

router = APIRouter(tags=["meta"])


@router.get("/api/health")
async def health() -> dict[str, Any]:
    """Liveness plus cheap runtime flags for monitors (no DB or Kalshi I/O)."""
    eng = state.bg_task is not None and not state.bg_task.done()
    opt = state.optimizer_task is not None and not state.optimizer_task.done()
    return {
        "status": "ok",
        "started_at": state.app_started_at_iso,
        "dual_engine_loop_running": eng,
        "optimizer_loop_running": opt,
    }


@router.get("/api/health/deep")
async def health_deep() -> dict[str, Any]:
    """Read-only: SQLite file size, engine last_error strings, webhook flag. Avoids Kalshi calls."""
    sp = Path(state.store.path)
    sqlite_bytes: int | None = None
    try:
        if sp.is_file():
            sqlite_bytes = int(sp.stat().st_size)
    except OSError:
        sqlite_bytes = None
    eng = state.bg_task is not None and not state.bg_task.done()
    opt = state.optimizer_task is not None and not state.optimizer_task.done()
    errs: dict[str, str | None] = {}
    for br, engn in state.ENGINES.items():
        errs[br] = getattr(getattr(engn, "state", None), "last_error", None)
    return {
        "status": "ok",
        "started_at": state.app_started_at_iso,
        "sqlite_path": str(sp.resolve()),
        "sqlite_bytes": sqlite_bytes,
        "dual_engine_loop_running": eng,
        "optimizer_loop_running": opt,
        "engine_last_errors": {k: v for k, v in errs.items() if v},
        "alert_webhook_configured": bool(env.alert_webhook_url.strip()),
    }


@router.get("/api/data/storage")
async def data_storage() -> dict[str, Any]:
    """SQLite path, JSONL log directory, and logging flags (backups / disk)."""
    return state.storage_dict()
