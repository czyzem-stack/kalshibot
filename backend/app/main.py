from __future__ import annotations

import asyncio
import csv
import datetime as dt
import io
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse

from .api_models import BotConfigPayload, merge_lab_branch_patch
from .branch_config import BRANCH_LAB_A, BRANCH_LAB_B, BRANCH_LAB_C, BRANCH_LIVE, merge_branch_config
from .engine import TradingEngine, compute_open_sim_mark_value_sum_cents, dual_engine_loop, exclude_subtitle_parts_from_cfg
from .kalshi_client import KalshiClient
from .kalshi_portfolio import fetch_portfolio_snapshot
from .market_pulse import fetch_market_pulse, market_passes_subtitle_excludes
from .rule_hints import rule_suggestions_from_snapshots
from .persistence import Store, expand_partial_lab_branch
from .optimizer_claude import run_optimizer_once
from .settings_env import env, kalshi_credentials_report


store = Store()
engine_live = TradingEngine(store, BRANCH_LIVE)
engine_lab_a = TradingEngine(store, BRANCH_LAB_A)
engine_lab_b = TradingEngine(store, BRANCH_LAB_B)
engine_lab_c = TradingEngine(store, BRANCH_LAB_C)
ENGINES: dict[str, TradingEngine] = {
    BRANCH_LIVE: engine_live,
    BRANCH_LAB_A: engine_lab_a,
    BRANCH_LAB_B: engine_lab_b,
    BRANCH_LAB_C: engine_lab_c,
}
stop_event = asyncio.Event()
_bg_task: asyncio.Task[None] | None = None
_optimizer_task: asyncio.Task[None] | None = None

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _storage_dict() -> dict[str, Any]:
    logd = Path(env.data_log_dir)
    if not logd.is_absolute():
        logd = _REPO_ROOT / logd
    return {
        "sqlite_path": str(Path(store.path).resolve()),
        "data_log_dir": str(logd.resolve()),
        "data_logging_enabled": bool(env.data_logging_enabled),
        "data_log_equity": bool(env.data_log_equity),
        "data_reset_token_configured": bool(getattr(env, "data_reset_token", "") or ""),
    }


def _engine_status_block(engine: TradingEngine, *, engine_running: bool, simulate_orders: bool, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    out = {
        "engine_running": bool(engine_running),
        "simulate_orders": bool(simulate_orders),
        "last_tick_at": engine.state.last_tick_at,
        "last_error": engine.state.last_error,
        "markets_scanned": engine.state.markets_scanned,
        "last_tick_trace": engine.state.last_tick_trace,
        "asset_snapshots": engine.state.asset_snapshots or {},
    }
    if extra:
        out.update(extra)
    return out


async def _optimizer_loop(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            cfg = await store.load_config()
            oc = cfg.get("optimizer") if isinstance(cfg.get("optimizer"), dict) else {}
            enabled = bool(oc.get("enabled"))
            interval_m = max(5, min(24 * 60, int(oc.get("interval_minutes") or 120)))
            if enabled:
                try:
                    await run_optimizer_once(store, force=False)
                except Exception as e:
                    cur = await store.load_config()
                    oo = cur.get("optimizer") if isinstance(cur.get("optimizer"), dict) else {}
                    oo["last_run_at"] = dt.datetime.now(tz=dt.timezone.utc).isoformat()
                    oo["last_status"] = "error"
                    oo["last_error"] = str(e)[:500]
                    cur["optimizer"] = oo
                    await store.save_config(cur)
            try:
                await asyncio.wait_for(stop.wait(), timeout=float(interval_m * 60))
            except TimeoutError:
                pass
        except Exception:
            try:
                await asyncio.wait_for(stop.wait(), timeout=60.0)
            except TimeoutError:
                pass


def _cors_origins() -> list[str]:
    return [o.strip() for o in env.cors_origins.split(",") if o.strip()]


def _metrics_from_trade_rollup(roll: dict[str, Any], branch: str) -> dict[str, Any]:
    """Build dashboard metrics dict from ``Store.dashboard_branch_trade_rollups`` (full table, not recent-N)."""
    total_pnl_cents = int(roll.get("total_pnl_cents") or 0)
    total_fee_cents = int(roll.get("total_fee_cents") or 0)
    settled_n = int(roll.get("settled_n") or 0)
    wins = int(roll.get("wins") or 0)
    losses = int(roll.get("losses") or 0)
    scratches = int(roll.get("scratches") or 0)
    t0s = roll.get("first_settled_ca")
    t1s = roll.get("last_settled_ca")
    hours = 1.0
    if t0s and t1s and settled_n > 0:
        try:
            t0 = dt.datetime.fromisoformat(str(t0s).replace("Z", "+00:00"))
            t1 = dt.datetime.fromisoformat(str(t1s).replace("Z", "+00:00"))
            raw_h = max(0.0, (t1 - t0).total_seconds() / 3600.0)
            # Bursts (first and last settle within seconds) made $/hour explode when dividing by ~0.
            # Use at least one clock hour so Lab A/B and live rollups stay readable after resets.
            hours = max(1.0, raw_h)
        except Exception:
            hours = 1.0
    avg_hourly = (total_pnl_cents / 100.0) / hours
    return {
        "branch": branch,
        "total_pnl_dollars": total_pnl_cents / 100.0,
        "total_kalshi_fees_dollars": total_fee_cents / 100.0,
        "settled_trades": settled_n,
        "wins": wins,
        "losses": losses,
        "scratch_trades": scratches,
        "avg_hourly_pnl_dollars": avg_hourly,
        "open_sim_trades": int(roll.get("open_n") or 0),
        "open_sim_committed_dollars": int(roll.get("open_committed_cents") or 0) / 100.0,
    }


def _latest_equity_snapshot_dollars(snaps: list[dict[str, Any]]) -> float | None:
    if not snaps:
        return None
    row = snaps[-1]
    if not isinstance(row, dict):
        return None
    try:
        return int(row.get("equity_cents") or 0) / 100.0
    except (TypeError, ValueError):
        return None


def _inject_last_snap_mtm_minus_equity(m: dict[str, Any], snaps: list[dict[str, Any]]) -> None:
    """How far the last row's MTM diverges from cost-basis equity on that same snapshot (open marks)."""
    if not snaps:
        return
    row = snaps[-1]
    if not isinstance(row, dict):
        return
    try:
        ec = int(row.get("equity_cents") or 0)
        raw = row.get("mtm_equity_cents")
        if raw is None or raw == "":
            return
        mc = int(raw)
        m["last_snap_mtm_minus_equity_dollars"] = round((mc - ec) / 100.0, 4)
    except (TypeError, ValueError):
        return


def _latest_mtm_snapshot_dollars(snaps: list[dict[str, Any]]) -> float | None:
    """Most recent snapshot row that has ``mtm_equity_cents`` (older rows pre-migration omit it)."""
    for row in reversed(snaps or []):
        if not isinstance(row, dict):
            continue
        raw = row.get("mtm_equity_cents")
        if raw is None or raw == "":
            continue
        try:
            return int(raw) / 100.0
        except (TypeError, ValueError):
            continue
    return None


def _balance_field_to_dollars(raw: Any) -> float | None:
    """Kalshi balance / portfolio_value are typically integer cents."""
    if raw is None or raw == "":
        return None
    try:
        cents = int(float(str(raw)))
    except (TypeError, ValueError):
        return None
    return cents / 100.0


async def _refresh_paper_mtm_from_marks(
    engine: TradingEngine,
    *,
    paper_start_cents: int,
    roll: dict[str, Any],
    out_metrics: dict[str, Any],
) -> None:
    """Recompute mark-to-market from latest Kalshi public mids on each dashboard poll (no new snapshot row)."""
    try:
        settled_pnl = int(roll.get("total_pnl_cents") or 0)
        open_committed = int(roll.get("open_committed_cents") or 0)
        ps = max(0, int(paper_start_cents))
        open_rows = await store.open_sim_trades_for_branch(engine.branch)
        mark = await compute_open_sim_mark_value_sum_cents(engine, open_rows)
        mtm_cents = ps + settled_pnl - open_committed + mark
        out_metrics["current_mtm_dollars"] = round(mtm_cents / 100.0, 4)
        if ps > 0:
            out_metrics["return_mtm_vs_start_pct"] = round(((mtm_cents - ps) / ps) * 100.0, 4)
    except Exception:
        return


def _enrich_strategy_metrics(
    m: dict[str, Any],
    *,
    paper_mode: bool,
    paper_start_cents: int | None,
    bal_json: dict[str, Any] | None,
    latest_equity_snap_dollars: float | None,
    latest_mtm_snap_dollars: float | None = None,
) -> None:
    """Adds win rate, paper equity path, and (for Live real) exchange balance / portfolio value."""
    settled = int(m.get("settled_trades") or 0)
    wins = int(m.get("wins") or 0)
    losses = int(m.get("losses") or 0)
    scratches = int(m.get("scratch_trades") or 0)
    realized = float(m.get("total_pnl_dollars") or 0.0)
    committed = float(m.get("open_sim_committed_dollars") or 0.0)
    decisive = wins + losses

    m["win_rate_pct"] = (100.0 * wins / settled) if settled else None
    m["loss_rate_pct"] = (100.0 * losses / settled) if settled else None
    m["win_rate_decisive_pct"] = (100.0 * wins / decisive) if decisive else None
    m["loss_rate_decisive_pct"] = (100.0 * losses / decisive) if decisive else None
    m["scratch_trades"] = scratches
    m["avg_realized_per_settled_dollars"] = (realized / settled) if settled else None
    m["latest_equity_snapshot_dollars"] = latest_equity_snap_dollars
    m["latest_mtm_snapshot_dollars"] = latest_mtm_snap_dollars

    if not paper_mode:
        if isinstance(bal_json, dict):
            m["exchange_balance_dollars"] = _balance_field_to_dollars(bal_json.get("balance"))
            m["exchange_portfolio_value_dollars"] = _balance_field_to_dollars(bal_json.get("portfolio_value"))
        pv_d = m.get("exchange_portfolio_value_dollars")
        if pv_d is not None:
            m["current_mtm_dollars"] = float(pv_d)
        elif latest_mtm_snap_dollars is not None:
            m["current_mtm_dollars"] = float(latest_mtm_snap_dollars)
        return

    if paper_start_cents is None:
        return
    ps = max(0, int(paper_start_cents)) / 100.0
    eq = ps + realized - committed
    m["paper_start_dollars"] = ps
    m["current_equity_dollars"] = eq
    m["return_vs_start_pct"] = ((eq - ps) / ps * 100.0) if ps > 0 else None
    m["realized_pnl_pct_of_start"] = ((realized / ps) * 100.0) if ps > 0 else None
    m["committed_pct_of_start"] = ((committed / ps) * 100.0) if ps > 0 else None
    if latest_mtm_snap_dollars is not None:
        m["current_mtm_dollars"] = float(latest_mtm_snap_dollars)
        m["return_mtm_vs_start_pct"] = ((latest_mtm_snap_dollars - ps) / ps * 100.0) if ps > 0 else None
    if (
        latest_equity_snap_dollars is not None
        and ps > 0
        and abs(latest_equity_snap_dollars - eq) > 0.02
    ):
        m["equity_snap_vs_calc_diff_dollars"] = round(latest_equity_snap_dollars - eq, 4)


@asynccontextmanager
async def _app_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    global _bg_task, _optimizer_task
    stop_event.clear()
    _bg_task = asyncio.create_task(dual_engine_loop(ENGINES, stop_event))
    _optimizer_task = asyncio.create_task(_optimizer_loop(stop_event))
    try:
        yield
    finally:
        stop_event.set()
        tasks = [t for t in (_bg_task, _optimizer_task) if t is not None]
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        _bg_task = None
        _optimizer_task = None


app = FastAPI(title="Kalshi Bot", lifespan=_app_lifespan)


@app.get("/", response_class=HTMLResponse)
async def root_page() -> str:
    """8765 is the JSON API only; the dashboard runs on the Vite dev server (5173)."""
    return """<!DOCTYPE html>
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
    <li><a href="/docs">Swagger UI (/docs)</a></li>
    <li><a href="/api/health">Health (/api/health)</a></li>
    <li><a href="/api/dashboard">Dashboard JSON (/api/dashboard)</a></li>
  </ul>
  <p><strong>Dashboard UI:</strong> in another terminal run<br />
  <code>cd frontend &amp;&amp; npm run dev</code><br />
  then open <a href="http://localhost:5173">http://localhost:5173</a> (proxies <code>/api</code> here).</p>
</body>
</html>
"""


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/data/storage")
async def data_storage() -> dict[str, Any]:
    """SQLite path, JSONL log directory, and logging flags (for backups / disk records)."""
    return _storage_dict()


def _clear_engine_mem_after_reset(branch_scope: str) -> None:
    """Clear in-memory tick snapshots for engines touched by a data reset."""
    if branch_scope == "all":
        keys = list(ENGINES.keys())
    else:
        m = {"live": BRANCH_LIVE, "lab_a": BRANCH_LAB_A, "lab_b": BRANCH_LAB_B, "lab_c": BRANCH_LAB_C}
        k = m.get(branch_scope)
        keys = [k] if k else []
    for key in keys:
        eng = ENGINES.get(key)
        if not eng:
            continue
        eng.state.asset_snapshots = {}
        eng.state.last_tick_trace = None
        eng.state.markets_scanned = 0
        eng.state.last_error = None
        eng._paper_auto_reset_streak_handled = False


@app.post("/api/data/reset")
async def data_reset(
    request: Request,
    confirm: str = Query("", description="Must be yes / true / 1 / y"),
    backup: bool = Query(True, description="Copy sqlite + JSONL table dumps before delete"),
    branch: str = Query(
        "all",
        description="all | live | lab_a | lab_b | lab_c — scope of DELETE on signals/trades/equity_snapshots",
    ),
) -> dict[str, Any]:
    """
    Wipe **signals**, **trades**, and **equity_snapshots** (all rows, or one branch). ``bot_config`` is kept.
    Optional env ``DATA_RESET_TOKEN``: then require header ``X-Reset-Token`` matching it.
    """
    if str(confirm).lower() not in ("yes", "true", "1", "y"):
        raise HTTPException(
            status_code=400,
            detail="Add query confirm=yes to delete trading tables. Settings in bot_config are not removed.",
        )
    tok = str(getattr(env, "data_reset_token", "") or "").strip()
    if tok and request.headers.get("x-reset-token") != tok:
        raise HTTPException(status_code=403, detail="Set header X-Reset-Token to match DATA_RESET_TOKEN in .env.")
    br = str(branch or "all").strip().lower()
    if br not in ("all", "live", "lab_a", "lab_b", "lab_c"):
        raise HTTPException(status_code=400, detail="branch must be all, live, lab_a, lab_b, or lab_c")
    try:
        out = await store.reset_trading_data(backup=backup, branch=None if br == "all" else br)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    _clear_engine_mem_after_reset(out.get("branch") or "all")
    return out


@app.get("/api/config")
async def get_config() -> dict[str, Any]:
    return await store.load_config()


@app.put("/api/config")
async def put_config(body: BotConfigPayload) -> dict[str, Any]:
    cur = await store.load_config()
    merged = body.merged_into(cur)
    await store.save_config(merged)
    return merged


@app.put("/api/config/lab-branches")
async def put_lab_branches(body: dict[str, Any]) -> dict[str, Any]:
    """
    Merge ``lab_a`` / ``lab_b`` / ``lab_c`` without the general ``BotConfigPayload`` shape.

    Optional ``reset_data``: ``none`` | ``lab_a`` | ``lab_b`` | ``lab_c`` | ``both`` (A+B) | ``all_labs`` (A+B+C).
    ``backup`` (default true) is passed to the first wipe in a multi-branch reset.
    """
    reset = str(body.get("reset_data") or "none").strip().lower()
    backup = bool(body.get("backup", True))
    if reset == "all_labs":
        await store.reset_trading_data(backup=backup, branch="lab_a")
        await store.reset_trading_data(backup=False, branch="lab_b")
        await store.reset_trading_data(backup=False, branch="lab_c")
        for br in ("lab_a", "lab_b", "lab_c"):
            _clear_engine_mem_after_reset(br)
    elif reset == "both":
        await store.reset_trading_data(backup=backup, branch="lab_a")
        await store.reset_trading_data(backup=False, branch="lab_b")
        _clear_engine_mem_after_reset("lab_a")
        _clear_engine_mem_after_reset("lab_b")
    elif reset == "lab_a":
        await store.reset_trading_data(backup=backup, branch="lab_a")
        _clear_engine_mem_after_reset("lab_a")
    elif reset == "lab_b":
        await store.reset_trading_data(backup=backup, branch="lab_b")
        _clear_engine_mem_after_reset("lab_b")
    elif reset == "lab_c":
        await store.reset_trading_data(backup=backup, branch="lab_c")
        _clear_engine_mem_after_reset("lab_c")
    elif reset not in ("none", ""):
        raise HTTPException(
            status_code=400,
            detail="reset_data must be none, lab_a, lab_b, lab_c, both, or all_labs",
        )

    cfg = await store.load_config()
    la = body.get("lab_a")
    if isinstance(la, dict) and la:
        merged_a = merge_lab_branch_patch(dict(cfg.get("lab_a") or {}), la)
        cfg["lab_a"] = expand_partial_lab_branch("lab_a", merged_a)
    lb = body.get("lab_b")
    if isinstance(lb, dict) and lb:
        merged_b = merge_lab_branch_patch(dict(cfg.get("lab_b") or {}), lb)
        cfg["lab_b"] = expand_partial_lab_branch("lab_b", merged_b)
    lc = body.get("lab_c")
    if isinstance(lc, dict) and lc:
        merged_c = merge_lab_branch_patch(dict(cfg.get("lab_c") or {}), lc)
        cfg["lab_c"] = expand_partial_lab_branch("lab_c", merged_c)
    await store.save_config(cfg)
    return {"ok": True, "config": await store.load_config()}


@app.post("/api/config/labs/add-paper-bankroll")
async def add_labs_paper_bankroll(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    """
    Add the same amount to Lab A / B / C ``paper_balance_cents`` (default **10_000** = $100.00 each).

    When ``paper_lifetime_basis_cents`` is set on a lab, it is increased by the same amount so dashboard
    return % and other vs-start KPIs use **prior basis + deposit**. If lifetime basis is unset, KPIs already
    fall back to ``paper_balance_cents`` (also increased). Does **not** change ``optimizer``, rules, engines,
    or SQLite rows.
    """
    raw = body.get("add_cents")
    if raw is None:
        add_cents = 10_000
    else:
        try:
            add_cents = int(raw)
        except (TypeError, ValueError) as e:
            raise HTTPException(status_code=400, detail="add_cents must be an integer") from e
    if add_cents < 0 or add_cents > 100_000_000:
        raise HTTPException(status_code=400, detail="add_cents out of allowed range")
    cfg = await store.load_config()
    updates: list[tuple[str, dict[str, Any], int]] = []
    for br_key in ("lab_a", "lab_b", "lab_c"):
        lab = dict(cfg.get(br_key) or {}) if isinstance(cfg.get(br_key), dict) else {}
        cur = lab.get("paper_balance_cents")
        try:
            cur_i = int(cur) if cur is not None else 0
        except (TypeError, ValueError):
            cur_i = 0
        new_bal = cur_i + add_cents
        if new_bal > 100_000_000:
            raise HTTPException(
                status_code=400,
                detail=f"{br_key}: paper_balance_cents would exceed maximum ({new_bal} > 100000000)",
            )
        lt_raw = lab.get("paper_lifetime_basis_cents")
        if lt_raw is not None:
            try:
                new_lt = int(lt_raw) + add_cents
            except (TypeError, ValueError):
                new_lt = new_bal
            if new_lt > 100_000_000:
                raise HTTPException(
                    status_code=400,
                    detail=f"{br_key}: paper_lifetime_basis_cents would exceed maximum ({new_lt} > 100000000)",
                )
            lab["paper_lifetime_basis_cents"] = new_lt
        updates.append((br_key, lab, new_bal))
    for br_key, lab, new_bal in updates:
        lab["paper_balance_cents"] = new_bal
        cfg[br_key] = expand_partial_lab_branch(br_key, lab)
    await store.save_config(cfg)
    out_lt: dict[str, int | None] = {}
    for br_key, lab, _new_bal in updates:
        v = lab.get("paper_lifetime_basis_cents")
        out_lt[br_key] = int(v) if v is not None else None
    return {
        "ok": True,
        "add_cents": add_cents,
        "paper_balance_cents": {k: n for k, _, n in updates},
        "paper_lifetime_basis_cents": out_lt,
    }


@app.get("/api/engine/status")
async def engine_status() -> dict[str, Any]:
    cfg = await store.load_config()
    lab_a = cfg.get("lab_a") if isinstance(cfg.get("lab_a"), dict) else {}
    lab_b = cfg.get("lab_b") if isinstance(cfg.get("lab_b"), dict) else {}
    lab_c = cfg.get("lab_c") if isinstance(cfg.get("lab_c"), dict) else {}
    return {
        "live": _engine_status_block(
            engine_live,
            engine_running=bool(cfg.get("engine_running")),
            simulate_orders=bool(cfg.get("simulate")),
            extra={"simulate": bool(cfg.get("simulate"))},
        ),
        "lab_a": _engine_status_block(
            engine_lab_a,
            engine_running=bool(lab_a.get("engine_running")),
            simulate_orders=True,
            extra={"auto_optimize": bool(lab_a.get("auto_optimize")), "optimizer_note": lab_a.get("optimizer_note")},
        ),
        "lab_b": _engine_status_block(
            engine_lab_b,
            engine_running=bool(lab_b.get("engine_running")),
            simulate_orders=True,
            extra={"auto_optimize": bool(lab_b.get("auto_optimize")), "optimizer_note": lab_b.get("optimizer_note")},
        ),
        "lab_c": _engine_status_block(
            engine_lab_c,
            engine_running=bool(lab_c.get("engine_running")),
            simulate_orders=True,
            extra={"auto_optimize": bool(lab_c.get("auto_optimize")), "optimizer_note": lab_c.get("optimizer_note")},
        ),
    }


@app.get("/api/account")
async def account() -> dict[str, Any]:
    client = KalshiClient()
    snap = await fetch_portfolio_snapshot(client)
    return {
        "balance": snap["balance"],
        "positions": snap["positions"],
        "orders": snap["orders"],
        "position_count": snap["position_count"],
        "resting_order_count": snap["resting_order_count"],
        "error": snap["error"],
    }


@app.get("/api/markets/pulse")
async def markets_pulse(
    branch: str = Query("live"),
    include_unpriced: bool = Query(False),
) -> dict[str, Any]:
    b = str(branch or "live").strip().lower()
    if b == "sim_lab":
        b = BRANCH_LAB_A
    if b not in (BRANCH_LIVE, BRANCH_LAB_A, BRANCH_LAB_B, BRANCH_LAB_C):
        b = BRANCH_LIVE
    return await fetch_market_pulse(store, branch=b, include_unpriced=include_unpriced)


@app.get("/api/markets/preview")
async def markets_preview(
    series_ticker: str,
    include_unpriced: bool = Query(False, description="If true, include rows whose YES subtitle matches exclude_* (e.g. TBD)."),
) -> dict[str, Any]:
    client = KalshiClient()
    data = await client.get_public(
        "/markets",
        {"series_ticker": series_ticker, "status": "open", "limit": "50"},
    )
    markets = list(data.get("markets") or [])
    if not include_unpriced:
        cfg = await store.load_config()
        parts = exclude_subtitle_parts_from_cfg(cfg)
        markets = [m for m in markets if market_passes_subtitle_excludes(m, parts)]
    return {"series_ticker": series_ticker, "markets": markets}


@app.get("/api/signals")
async def signals(limit: int = 200) -> list[dict[str, Any]]:
    return await store.recent_signals(limit=limit)


@app.get("/api/trades")
async def trades(limit: int = 200) -> list[dict[str, Any]]:
    return await store.recent_trades(limit=limit)


def _position_rows_for_series(series_upper: str, kalshi_positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for p in kalshi_positions:
        tick = str(p.get("ticker") or p.get("market_ticker") or "").upper()
        if series_upper and tick.startswith(series_upper):
            qty = p.get("position_fp")
            if qty is None:
                qty = p.get("position")
            rows.append({"ticker": p.get("ticker") or p.get("market_ticker"), "position": qty})
    return rows[:16]


def _open_sim_rows_for_series(
    series_upper: str, trades: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for t in trades:
        tick = str(t.get("ticker") or "").upper()
        if series_upper and tick.startswith(series_upper):
            rows.append(
                {
                    "ticker": t.get("ticker"),
                    "contracts_fp": t.get("contracts_fp"),
                    "status": t.get("status"),
                }
            )
    return rows[:16]


def _position_by_asset(
    assets_cfg: dict[str, Any],
    kalshi_positions_raw: list[Any],
    sim_open_live: list[dict[str, Any]],
    sim_open_lab_a: list[dict[str, Any]],
    sim_open_lab_b: list[dict[str, Any]],
    sim_open_lab_c: list[dict[str, Any]],
) -> dict[str, Any]:
    kalshi_positions = [p for p in kalshi_positions_raw if isinstance(p, dict)]
    out: dict[str, Any] = {}
    for aid, acfg in (assets_cfg or {}).items():
        if not isinstance(acfg, dict):
            continue
        st = str(acfg.get("series_ticker") or "").strip().upper()
        if not st:
            continue
        lab_a_rows = _open_sim_rows_for_series(st, sim_open_lab_a)
        lab_b_rows = _open_sim_rows_for_series(st, sim_open_lab_b)
        lab_c_rows = _open_sim_rows_for_series(st, sim_open_lab_c)
        out[str(aid)] = {
            "label": str(acfg.get("label") or aid),
            "series_ticker": acfg.get("series_ticker"),
            "kalshi_open": _position_rows_for_series(st, kalshi_positions),
            "bot_sim_open_live": _open_sim_rows_for_series(st, sim_open_live),
            # bot_sim_open_lab = Lab A (historical name); split columns use *_a / *_b / *_c.
            "bot_sim_open_lab": lab_a_rows,
            "bot_sim_open_lab_a": lab_a_rows,
            "bot_sim_open_lab_b": lab_b_rows,
            "bot_sim_open_lab_c": lab_c_rows,
        }
    return out


@app.get("/api/dashboard")
async def dashboard() -> dict[str, Any]:
    cfg = await store.load_config()
    mode_live = "simulate" if cfg.get("simulate") else "live"
    # Pull enough rows for the dashboard to filter by branch in the UI (recent slice was mostly one branch).
    trades = await store.recent_trades(limit=500)
    signals = await store.recent_signals(limit=500)
    snaps_live = await store.equity_series(limit=2000, branch=BRANCH_LIVE)
    snaps_lab_a = await store.equity_series(limit=2000, branch=BRANCH_LAB_A)
    snaps_lab_b = await store.equity_series(limit=2000, branch=BRANCH_LAB_B)
    snaps_lab_c = await store.equity_series(limit=2000, branch=BRANCH_LAB_C)

    roll_live = await store.dashboard_branch_trade_rollups(BRANCH_LIVE, mode_live)
    metrics_live = _metrics_from_trade_rollup(roll_live, BRANCH_LIVE)
    roll_lab_a = await store.dashboard_branch_trade_rollups(BRANCH_LAB_A, "simulate")
    metrics_lab_a = _metrics_from_trade_rollup(roll_lab_a, BRANCH_LAB_A)
    roll_lab_b = await store.dashboard_branch_trade_rollups(BRANCH_LAB_B, "simulate")
    metrics_lab_b = _metrics_from_trade_rollup(roll_lab_b, BRANCH_LAB_B)
    roll_lab_c = await store.dashboard_branch_trade_rollups(BRANCH_LAB_C, "simulate")
    metrics_lab_c = _metrics_from_trade_rollup(roll_lab_c, BRANCH_LAB_C)

    not_traded = [s for s in signals if not int(s.get("executed") or 0)]

    lab_a = cfg.get("lab_a") if isinstance(cfg.get("lab_a"), dict) else {}
    lab_b = cfg.get("lab_b") if isinstance(cfg.get("lab_b"), dict) else {}
    lab_c = cfg.get("lab_c") if isinstance(cfg.get("lab_c"), dict) else {}
    live_engine_on = bool(cfg.get("engine_running"))
    lab_a_engine_on = bool(lab_a.get("engine_running")) if isinstance(lab_a, dict) else False
    lab_b_engine_on = bool(lab_b.get("engine_running")) if isinstance(lab_b, dict) else False
    lab_c_engine_on = bool(lab_c.get("engine_running")) if isinstance(lab_c, dict) else False

    client = KalshiClient()
    public_ok = False
    public_err: str | None = None
    try:
        probe = await client.get_public("/markets", {"limit": "1"})
        public_ok = True
        _ = probe
    except Exception as e:
        public_err = str(e)

    portfolio = await fetch_portfolio_snapshot(client)
    bal_json = portfolio["balance"]
    private_err: str | None = None
    if bal_json is None:
        private_err = str(portfolio.get("error") or "Private API: balance request failed (keys / signing).")
    portfolio_read_ok = bal_json is not None
    portfolio_notes: str | None = None
    if portfolio_read_ok and portfolio.get("error"):
        portfolio_notes = str(portfolio["error"])

    creds = kalshi_credentials_report()
    simulate_live = bool(cfg.get("simulate"))
    order_writes_live = portfolio_read_ok and not simulate_live

    _enrich_strategy_metrics(
        metrics_live,
        paper_mode=simulate_live,
        paper_start_cents=int(cfg.get("paper_balance_cents") or 0),
        bal_json=bal_json if isinstance(bal_json, dict) else None,
        latest_equity_snap_dollars=_latest_equity_snapshot_dollars(snaps_live),
        latest_mtm_snap_dollars=_latest_mtm_snapshot_dollars(snaps_live),
    )
    def _lab_paper_basis_cents(lab: dict[str, Any]) -> int:
        lt = lab.get("paper_lifetime_basis_cents")
        if lt is not None:
            return int(lt)
        return int(lab.get("paper_balance_cents") or cfg.get("paper_balance_cents") or 500_000)

    lab_paper_basis_a = _lab_paper_basis_cents(lab_a if isinstance(lab_a, dict) else {})
    _enrich_strategy_metrics(
        metrics_lab_a,
        paper_mode=True,
        paper_start_cents=lab_paper_basis_a,
        bal_json=None,
        latest_equity_snap_dollars=_latest_equity_snapshot_dollars(snaps_lab_a),
        latest_mtm_snap_dollars=_latest_mtm_snapshot_dollars(snaps_lab_a),
    )
    lab_paper_basis_b = _lab_paper_basis_cents(lab_b if isinstance(lab_b, dict) else {})
    _enrich_strategy_metrics(
        metrics_lab_b,
        paper_mode=True,
        paper_start_cents=lab_paper_basis_b,
        bal_json=None,
        latest_equity_snap_dollars=_latest_equity_snapshot_dollars(snaps_lab_b),
        latest_mtm_snap_dollars=_latest_mtm_snapshot_dollars(snaps_lab_b),
    )
    _inject_last_snap_mtm_minus_equity(metrics_live, snaps_live)
    _inject_last_snap_mtm_minus_equity(metrics_lab_a, snaps_lab_a)
    _inject_last_snap_mtm_minus_equity(metrics_lab_b, snaps_lab_b)
    lab_paper_basis_c = _lab_paper_basis_cents(lab_c if isinstance(lab_c, dict) else {})
    _enrich_strategy_metrics(
        metrics_lab_c,
        paper_mode=True,
        paper_start_cents=lab_paper_basis_c,
        bal_json=None,
        latest_equity_snap_dollars=_latest_equity_snapshot_dollars(snaps_lab_c),
        latest_mtm_snap_dollars=_latest_mtm_snapshot_dollars(snaps_lab_c),
    )
    _inject_last_snap_mtm_minus_equity(metrics_lab_c, snaps_lab_c)

    # Paper MTM on tiles + chart tail: refresh from Kalshi order books every dashboard poll (parallel per branch).
    mtm_tasks: list[Any] = []
    if simulate_live:
        mtm_tasks.append(
            _refresh_paper_mtm_from_marks(
                engine_live,
                paper_start_cents=int(cfg.get("paper_balance_cents") or 0),
                roll=roll_live,
                out_metrics=metrics_live,
            )
        )
    mtm_tasks.extend(
        [
            _refresh_paper_mtm_from_marks(
                engine_lab_a,
                paper_start_cents=lab_paper_basis_a,
                roll=roll_lab_a,
                out_metrics=metrics_lab_a,
            ),
            _refresh_paper_mtm_from_marks(
                engine_lab_b,
                paper_start_cents=lab_paper_basis_b,
                roll=roll_lab_b,
                out_metrics=metrics_lab_b,
            ),
            _refresh_paper_mtm_from_marks(
                engine_lab_c,
                paper_start_cents=lab_paper_basis_c,
                roll=roll_lab_c,
                out_metrics=metrics_lab_c,
            ),
        ]
    )
    if mtm_tasks:
        await asyncio.gather(*mtm_tasks)

    eff_live = merge_branch_config(cfg, BRANCH_LIVE) if live_engine_on else None
    eff_lab_a = merge_branch_config(cfg, BRANCH_LAB_A) if lab_a_engine_on else None
    eff_lab_b = merge_branch_config(cfg, BRANCH_LAB_B) if lab_b_engine_on else None
    eff_lab_c = merge_branch_config(cfg, BRANCH_LAB_C) if lab_c_engine_on else None

    kalshi_pos_list = [p for p in (portfolio.get("positions") or []) if isinstance(p, dict)]
    sim_open_live, sim_open_lab_a, sim_open_lab_b, sim_open_lab_c = await asyncio.gather(
        store.open_sim_trades_for_branch(BRANCH_LIVE),
        store.open_sim_trades_for_branch(BRANCH_LAB_A),
        store.open_sim_trades_for_branch(BRANCH_LAB_B),
        store.open_sim_trades_for_branch(BRANCH_LAB_C),
    )
    assets_cfg = cfg.get("assets") if isinstance(cfg.get("assets"), dict) else {}
    position_by_asset = _position_by_asset(
        assets_cfg, kalshi_pos_list, sim_open_live, sim_open_lab_a, sim_open_lab_b, sim_open_lab_c
    )

    return {
        "config": cfg,
        "storage": _storage_dict(),
        "kalshi": {
            "api_base": client.base,
            "env": env.kalshi_env,
            "public_ok": public_ok,
            "public_error": public_err,
            "private_ok": portfolio_read_ok,
            "private_error": private_err,
            "portfolio_notes": portfolio_notes,
            "polling_enabled": live_engine_on or lab_a_engine_on or lab_b_engine_on or lab_c_engine_on,
            "credentials": creds,
            "simulate_live": simulate_live,
            "portfolio_read_ok": portfolio_read_ok,
            "position_count": int(portfolio.get("position_count") or 0),
            "resting_order_count": int(portfolio.get("resting_order_count") or 0),
            "order_writes_live": order_writes_live,
        },
        "engine": {
            "live": {
                "engine_running": live_engine_on,
                "simulate_orders": bool(eff_live.get("_simulate_orders")) if eff_live else simulate_live,
                "last_tick_at": engine_live.state.last_tick_at,
                "last_error": engine_live.state.last_error,
                "markets_scanned": engine_live.state.markets_scanned,
                "last_tick_trace": engine_live.state.last_tick_trace,
            },
            "lab_a": {
                "engine_running": lab_a_engine_on,
                "simulate_orders": bool(eff_lab_a.get("_simulate_orders")) if eff_lab_a else True,
                "last_tick_at": engine_lab_a.state.last_tick_at,
                "last_error": engine_lab_a.state.last_error,
                "markets_scanned": engine_lab_a.state.markets_scanned,
                "last_tick_trace": engine_lab_a.state.last_tick_trace,
            },
            "lab_b": {
                "engine_running": lab_b_engine_on,
                "simulate_orders": bool(eff_lab_b.get("_simulate_orders")) if eff_lab_b else True,
                "last_tick_at": engine_lab_b.state.last_tick_at,
                "last_error": engine_lab_b.state.last_error,
                "markets_scanned": engine_lab_b.state.markets_scanned,
                "last_tick_trace": engine_lab_b.state.last_tick_trace,
            },
            "lab_c": {
                "engine_running": lab_c_engine_on,
                "simulate_orders": bool(eff_lab_c.get("_simulate_orders")) if eff_lab_c else True,
                "last_tick_at": engine_lab_c.state.last_tick_at,
                "last_error": engine_lab_c.state.last_error,
                "markets_scanned": engine_lab_c.state.markets_scanned,
                "last_tick_trace": engine_lab_c.state.last_tick_trace,
            },
        },
        "asset_snapshots": {
            "live": engine_live.state.asset_snapshots or {},
            "lab_a": engine_lab_a.state.asset_snapshots or {},
            "lab_b": engine_lab_b.state.asset_snapshots or {},
            "lab_c": engine_lab_c.state.asset_snapshots or {},
        },
        "rule_suggestions": rule_suggestions_from_snapshots(
            engine_live.state.asset_snapshots or {},
            engine_lab_a.state.asset_snapshots or {},
            engine_lab_b.state.asset_snapshots or {},
            engine_lab_c.state.asset_snapshots or {},
        ),
        "metrics": {
            "mode": mode_live,
            **metrics_live,
        },
        "metrics_lab_a": metrics_lab_a,
        "metrics_lab_b": metrics_lab_b,
        "metrics_lab_c": metrics_lab_c,
        "equity_snapshots": snaps_live,
        "equity_snapshots_lab_a": snaps_lab_a,
        "equity_snapshots_lab_b": snaps_lab_b,
        "equity_snapshots_lab_c": snaps_lab_c,
        "recent_signals": signals[:500],
        "not_traded_signals": not_traded[:200],
        "recent_trades": trades[:500],
        "remote_balance": bal_json,
        "account_snapshot": {
            "position_count": int(portfolio.get("position_count") or 0),
            "resting_order_count": int(portfolio.get("resting_order_count") or 0),
            "portfolio_error": portfolio.get("error"),
            "position_by_asset": position_by_asset,
        },
        "lab_a_config": lab_a,
        "lab_b_config": lab_b,
        "lab_c_config": lab_c,
    }


@app.post("/api/engine/toggle")
async def engine_toggle(
    running: bool | None = Query(None),
    simulate: bool | None = Query(None),
    sim_lab_running: bool | None = Query(None),
    lab_a_running: bool | None = Query(None),
    lab_b_running: bool | None = Query(None),
    lab_c_running: bool | None = Query(None),
) -> dict[str, Any]:
    cfg = await store.load_config()
    if running is not None:
        cfg["engine_running"] = bool(running)
    if simulate is not None:
        cfg["simulate"] = bool(simulate)
    if sim_lab_running is not None:
        lab = dict(cfg.get("lab_a") or {})
        lab["engine_running"] = bool(sim_lab_running)
        cfg["lab_a"] = lab
    if lab_a_running is not None:
        lab = dict(cfg.get("lab_a") or {})
        lab["engine_running"] = bool(lab_a_running)
        cfg["lab_a"] = lab
    if lab_b_running is not None:
        lab = dict(cfg.get("lab_b") or {})
        lab["engine_running"] = bool(lab_b_running)
        cfg["lab_b"] = lab
    if lab_c_running is not None:
        lab = dict(cfg.get("lab_c") or {})
        lab["engine_running"] = bool(lab_c_running)
        cfg["lab_c"] = lab
    await store.save_config(cfg)
    return {"ok": True, "config": cfg}


@app.get("/api/history/{table}")
async def history_table(
    table: str,
    branch: str | None = Query(None),
    mode: str | None = Query(None),
    ticker: str | None = Query(None),
    start_at: str | None = Query(None),
    end_at: str | None = Query(None),
    limit: int = Query(500, ge=1, le=10000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    t = table.strip().lower()
    if t not in ("trades", "signals", "equity"):
        raise HTTPException(status_code=400, detail="table must be trades|signals|equity")
    tbl = "equity_snapshots" if t == "equity" else t
    try:
        rows = await store.query_table(
            tbl,
            branch=branch,
            mode=mode,
            ticker=ticker,
            start_at=start_at,
            end_at=end_at,
            limit=limit,
            offset=offset,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"table": t, "count": len(rows), "rows": rows}


@app.get("/api/history/export.csv")
async def history_export_csv(
    table: str = Query("trades"),
    branch: str | None = Query(None),
    mode: str | None = Query(None),
    ticker: str | None = Query(None),
    start_at: str | None = Query(None),
    end_at: str | None = Query(None),
    limit: int = Query(5000, ge=1, le=20000),
) -> StreamingResponse:
    t = table.strip().lower()
    if t not in ("trades", "signals", "equity"):
        raise HTTPException(status_code=400, detail="table must be trades|signals|equity")
    tbl = "equity_snapshots" if t == "equity" else t
    try:
        rows = await store.query_table(
            tbl,
            branch=branch,
            mode=mode,
            ticker=ticker,
            start_at=start_at,
            end_at=end_at,
            limit=limit,
            offset=0,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow(r)
    else:
        buf.write("empty\n")
    data = buf.getvalue().encode("utf-8")
    fname = f"{t}_export.csv"
    return StreamingResponse(
        iter([data]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@app.get("/api/optimizer/recommendations")
async def optimizer_recommendations(limit: int = Query(30, ge=1, le=200)) -> dict[str, Any]:
    cfg = await store.load_config()
    rows = await store.recent_optimizer_recommendations(limit=limit)
    return {"config": cfg.get("optimizer") or {}, "rows": rows}


@app.put("/api/optimizer/config")
async def optimizer_config(body: dict[str, Any]) -> dict[str, Any]:
    cfg = await store.load_config()
    cur = cfg.get("optimizer") if isinstance(cfg.get("optimizer"), dict) else {}
    nxt = dict(cur)
    for k in (
        "enabled",
        "interval_minutes",
        "lookback_hours",
        "max_rows_per_table",
        "model",
        "adaptive_enabled",
        "mode",
        "lab_a_enabled",
        "lab_b_enabled",
        "lab_a_style",
        "lab_b_style",
        "loss_streak_trigger",
        "threshold_step_pct",
        "minute_step",
        "max_history",
        "lab_a_yes_floor_pct",
        "lab_b_yes_floor_pct",
        "lab_a_min_minutes_left",
        "lab_b_min_minutes_left",
        "min_trades_for_optimize",
        "min_profitable_trades",
        "regime_lookback_hours",
        "optimize_bet_size",
        "include_fees_in_score",
        "backtest_proposals",
    ):
        if k in body:
            v = body[k]
            if k in (
                "lookback_hours",
                "max_rows_per_table",
                "max_history",
                "min_trades_for_optimize",
                "min_profitable_trades",
            ) and v is not None:
                try:
                    nxt[k] = int(v)
                except (TypeError, ValueError):
                    nxt[k] = v
            elif k == "regime_lookback_hours" and v is not None:
                try:
                    nxt[k] = max(1, min(168, int(float(v))))
                except (TypeError, ValueError):
                    nxt[k] = v
            elif k == "interval_minutes" and v is not None:
                try:
                    nxt[k] = max(5, min(24 * 60, int(float(v))))
                except (TypeError, ValueError):
                    nxt[k] = v
            elif k in ("optimize_bet_size", "include_fees_in_score", "backtest_proposals"):
                nxt[k] = bool(v)
            else:
                nxt[k] = v
    nxt.pop("max_bet_fraction", None)
    cfg["optimizer"] = nxt
    await store.save_config(cfg)
    return {"ok": True, "optimizer": nxt}


@app.post("/api/optimizer/run")
async def optimizer_run() -> dict[str, Any]:
    return await run_optimizer_once(store, force=True)
