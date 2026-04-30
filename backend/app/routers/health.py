"""Liveness, deep health, and storage metadata (no heavy I/O in basic health)."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from ..kalshi_client import KalshiClient
from ..settings_env import env
from .. import state
from ..types_api import DataStorageResponse, HealthDeepResponse, HealthResponse, HealthStartupResponse

router = APIRouter(tags=["meta"])


@router.get("/api/health")
async def health() -> HealthResponse:
    """Liveness plus cheap runtime flags for monitors (no DB or Kalshi I/O)."""
    eng = state.bg_task is not None and not state.bg_task.done()
    opt = state.optimizer_task is not None and not state.optimizer_task.done()
    return HealthResponse(
        status="ok",
        started_at=state.app_started_at_iso,
        dual_engine_loop_running=eng,
        optimizer_loop_running=opt,
    )


@router.get("/api/health/startup")
async def health_startup() -> HealthStartupResponse:
    """PHASE 2: cheap flags for dashboard / probes — pre-warm gate, optional Kalshi WS, orderbook cache telemetry."""
    ws_t = state.kalshi_ws_task
    # PHASE FINAL: return TypedDict contract; payload shape unchanged.
    return HealthStartupResponse(
        startup_complete=state.startup_complete.is_set(),
        prewarm_complete=bool(KalshiClient.prewarm_complete),
        kalshi_ws_enabled=bool(env.kalshi_ws_enabled),
        kalshi_ws_task_running=ws_t is not None and not ws_t.done(),
        ws_connected=bool(KalshiClient.ws_connected),
        ws_messages=int(KalshiClient.ws_messages),
        ws_orderbook_cache_writes=int(KalshiClient.ws_orderbook_cache_writes),
        ws_subscribe_tickers=int(len(KalshiClient.ws_subscribe_tickers)),
        ws_last_error=KalshiClient.ws_last_error,
        orderbook_cache_hits=int(KalshiClient.orderbook_cache_hits),
        orderbook_cache_misses=int(KalshiClient.orderbook_cache_misses),
    )


@router.get("/api/health/deep")
async def health_deep() -> HealthDeepResponse:
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
    # PHASE FINAL.1: TypedDict contract only; payload shape unchanged.
    prof = str(getattr(env, "kalshibot_data_profile", "") or "").strip()
    return HealthDeepResponse(
        status="ok",
        started_at=state.app_started_at_iso,
        sqlite_path=str(sp.resolve()),
        sqlite_bytes=sqlite_bytes,
        data_profile=prof,
        dual_engine_loop_running=eng,
        optimizer_loop_running=opt,
        engine_last_errors={k: v for k, v in errs.items() if v},
        alert_webhook_configured=bool(env.alert_webhook_url.strip()),
    )


@router.get("/api/data/storage")
async def data_storage() -> DataStorageResponse:
    """SQLite path, JSONL log directory, and logging flags (backups / disk)."""
    # PHASE FINAL.1: TypedDict contract only; payload shape unchanged.
    return DataStorageResponse(**state.storage_dict())
