"""
Process-wide singletons for the API (Store, engine instances, background tasks, caches).

``TradingEngine`` instances and the shared ``httpx`` pool are **not** created at import time;
:func:`init_runtime_engines` runs from FastAPI lifespan so startup stays fast and uses one client.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from .branch_config import (
    BRANCH_LAB_A,
    BRANCH_LAB_B,
    BRANCH_LAB_C,
    BRANCH_LAB_D,
    BRANCH_LIVE,
)
from .kalshi_client import KalshiClient, new_shared_http_client
from .persistence import Store
from .settings_env import env

if TYPE_CHECKING:
    from .engines.engine import TradingEngine

logger = logging.getLogger("kalshibot.state")

REPO_ROOT = Path(__file__).resolve().parents[2]

store = Store()

http_client: httpx.AsyncClient | None = None
shared_kalshi: KalshiClient | None = None
engine_live: TradingEngine | None = None
engine_lab_a: TradingEngine | None = None
engine_lab_b: TradingEngine | None = None
engine_lab_c: TradingEngine | None = None
engine_lab_d: TradingEngine | None = None
ENGINES: dict[str, TradingEngine] = {}

stop_event = asyncio.Event()
# PHASE 2: set after pre-warm (and WS ticker seed); dual_engine_loop awaits this so ticks never race ahead of cache fill.
startup_complete = asyncio.Event()
bg_task: asyncio.Task[None] | None = None
optimizer_task: asyncio.Task[None] | None = None
kalshi_ws_task: asyncio.Task[None] | None = None
app_started_at_iso: str | None = None

# Filled on each full dashboard run with Kalshi mark refresh; read by ``GET /api/dashboard/orderbooks``.
DASHBOARD_ORDERBOOK_CACHE: dict[str, Any] = {"t_mono": 0.0, "payload": None}
# PHASE 3: centralize cache TTL in env while preserving default (5.0s).
DASHBOARD_ORDERBOOK_CACHE_TTL_S = float(env.dashboard_orderbook_cache_ttl_s)


def require_kalshi() -> KalshiClient:
    """Process-wide Kalshi client (one ``httpx`` pool). For scripts that skip ASGI, lazily create the pool once."""
    global http_client, shared_kalshi
    if shared_kalshi is not None:
        return shared_kalshi
    http_client = new_shared_http_client()
    shared_kalshi = KalshiClient(http_client=http_client)
    return shared_kalshi


def init_runtime_engines(kalshi: KalshiClient | None = None) -> None:
    """Build five ``TradingEngine`` instances sharing one ``KalshiClient``."""
    from .engine import TradingEngine

    # PHASE 4: prefer process-shared client injection from ``require_kalshi``.
    kc = kalshi if kalshi is not None else require_kalshi()
    el = TradingEngine(store, BRANCH_LIVE, client=kc)
    ea = TradingEngine(store, BRANCH_LAB_A, client=kc)
    eb = TradingEngine(store, BRANCH_LAB_B, client=kc)
    ec = TradingEngine(store, BRANCH_LAB_C, client=kc)
    ed = TradingEngine(store, BRANCH_LAB_D, client=kc)
    global engine_live, engine_lab_a, engine_lab_b, engine_lab_c, engine_lab_d
    engine_live, engine_lab_a, engine_lab_b, engine_lab_c, engine_lab_d = (el, ea, eb, ec, ed)
    # Update in place so importers that bound early to ``ENGINES`` still see engines (if any).
    ENGINES.clear()
    ENGINES.update(
        {
            BRANCH_LIVE: el,
            BRANCH_LAB_A: ea,
            BRANCH_LAB_B: eb,
            BRANCH_LAB_C: ec,
            BRANCH_LAB_D: ed,
        }
    )


def storage_dict() -> dict[str, Any]:
    from .settings_env import env

    logd = Path(env.data_log_dir)
    if not logd.is_absolute():
        logd = REPO_ROOT / logd
    return {
        "sqlite_path": str(Path(store.path).resolve()),
        "data_log_dir": str(logd.resolve()),
        "data_logging_enabled": bool(env.data_logging_enabled),
        "data_log_equity": bool(env.data_log_equity),
        "data_reset_token_configured": bool(getattr(env, "data_reset_token", "") or ""),
    }
