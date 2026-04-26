"""
Process-wide singletons for the API (Store, engine instances, background tasks, caches).

Routers and ``main`` import from here so tests can swap ``app.state.store`` without import cycles.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from .branch_config import (
    BRANCH_LAB_A,
    BRANCH_LAB_B,
    BRANCH_LAB_C,
    BRANCH_LAB_D,
    BRANCH_LIVE,
)
from .engine import TradingEngine
from .persistence import Store

REPO_ROOT = Path(__file__).resolve().parents[2]

store = Store()
engine_live = TradingEngine(store, BRANCH_LIVE)
engine_lab_a = TradingEngine(store, BRANCH_LAB_A)
engine_lab_b = TradingEngine(store, BRANCH_LAB_B)
engine_lab_c = TradingEngine(store, BRANCH_LAB_C)
engine_lab_d = TradingEngine(store, BRANCH_LAB_D)
ENGINES: dict[str, TradingEngine] = {
    BRANCH_LIVE: engine_live,
    BRANCH_LAB_A: engine_lab_a,
    BRANCH_LAB_B: engine_lab_b,
    BRANCH_LAB_C: engine_lab_c,
    BRANCH_LAB_D: engine_lab_d,
}

stop_event = asyncio.Event()
bg_task: asyncio.Task[None] | None = None
optimizer_task: asyncio.Task[None] | None = None
app_started_at_iso: str | None = None

# Filled on each full dashboard run with Kalshi mark refresh; read by ``GET /api/dashboard/orderbooks``.
DASHBOARD_ORDERBOOK_CACHE: dict[str, Any] = {"t_mono": 0.0, "payload": None}
DASHBOARD_ORDERBOOK_CACHE_TTL_S = 5.0


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
