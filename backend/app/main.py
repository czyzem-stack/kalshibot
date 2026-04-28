from __future__ import annotations

import asyncio
import copy
import csv
import datetime as dt
import hashlib
import io
import json
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from . import state
from .api_models import BotConfigPayload, merge_lab_branch_patch, normalize_rules_list
from .core.logging import (
    RequestContextMiddleware,
    configure_logging,
    reset_uvicorn_loggers_to_root,
)
from .branch_config import (
    BRANCH_CHILD_LABS,
    BRANCH_LAB_A,
    BRANCH_LAB_B,
    BRANCH_LAB_C,
    BRANCH_LAB_D,
    BRANCH_LABS,
    BRANCH_LIVE,
    LAB_BRANCH_OVERLAY_KEYS,
    build_optimizer_radar_payload,
    fleet_visible_paper_start_cents,
    lab_paper_equity_start_cents,
    live_paper_trading_enabled,
    merge_branch_config,
    sync_live_paper_trading_keys,
)
from .engine import (
    TradingEngine,
    compute_open_sim_mark_value_sum_cents,
    dual_engine_loop,
    exclude_subtitle_parts_from_cfg,
    snapshot_equity,
)
from .kalshi_client import KalshiClient, new_shared_http_client, prewarm_open_markets_for_config
from .kalshi_ws import kalshi_ws_task_group_runner
from .kalshi_portfolio import fetch_portfolio_snapshot
from .market_pulse import fetch_market_pulse, market_passes_subtitle_excludes
from .rule_hints import rule_suggestions_from_snapshots
from .persistence import expand_partial_lab_branch
from .optimizer.promotion import lab_a_promotion_report
from .optimizer_claude import pulse_chart_baseline, run_optimizer_once
from .middleware import ApiBearerAuthMiddleware, SecurityHeadersMiddleware
from .routers import health as health_routes
from .routers import optimizer_routes, public_root
from .settings_env import env, kalshi_credentials_report
from .state import (
    DASHBOARD_ORDERBOOK_CACHE,
    DASHBOARD_ORDERBOOK_CACHE_TTL_S,
    init_runtime_engines,
    require_kalshi,
    storage_dict,
    store,
)
from .types_api import (
    AccountResponse,
    DashboardOpenPositionsResponse,
    DashboardOrderbooksResponse,
    DashboardRecentTradesResponse,
    DashboardResponse,
    EngineStatusBlock,
    EngineStatusResponse,
    MarketPulseResponse,
    MarketsPreviewResponse,
)

# structlog: stdlib ``logging.getLogger`` + uvicorn share ``ProcessorFormatter``; dev = colored, LOG_JSON=1 = one line JSON
configure_logging()
# Set once: ``optimizer_loop`` is idle (no scheduled optimizer, no adaptive, no child-lab breeding).
_optimizer_all_idle_logged: bool = False

logger = logging.getLogger("kalshibot.api")

# Must match ``default_bot_config`` / snapshot_equity Live paper fallback so tiles and chart tail
# never disagree when ``paper_balance_cents`` is unset.
_DEFAULT_PAPER_BALANCE_CENTS = 500_000

def _optimizer_change_stable_id(x: dict[str, Any]) -> str:
    """Stable id for slimmed change_history rows so clients do not regenerate different legacy-* ids per poll."""
    rid = x.get("id")
    if rid:
        s = str(rid).strip()
        if s and not s.startswith("legacy-"):
            return s
    parts = "|".join(
        [
            str(x.get("created_at") or ""),
            str(x.get("branch") or x.get("lab_label") or ""),
            str(x.get("style") or ""),
            str(x.get("summary") or "")[:160],
            str(x.get("reason") or "")[:160],
        ]
    )
    h = hashlib.sha256(parts.encode("utf-8", errors="replace")).hexdigest()[:20]
    return f"ch-{h}"


def _engine_status_block(engine: TradingEngine, *, engine_running: bool, simulate_orders: bool, extra: dict[str, Any] | None = None) -> EngineStatusBlock:
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
    # Two “testing” paths (see ``architecture-breeding`` rule, ``dual_engine_loop`` docstring, ``run_optimizer_once``):
    # (1) **Visible paper** — ``dual_engine_loop`` ticks Live + Lab A–D (and child labs) so the dashboard PnL reflects rules.
    # (2) **Child-lab breeding** — B/C/D GA, hard-death, soft cull, adoption: driven by ``optimizer.breeding_enabled`` +
    #   ``run_optimizer_once`` / ``_run_breeding_only_tick``; independent of ``enabled``/``adaptive_enabled``.
    while not stop.is_set():
        try:
            cfg = await store.load_config()
            oc = cfg.get("optimizer") if isinstance(cfg.get("optimizer"), dict) else {}
            enabled = bool(oc.get("enabled"))
            adaptive_on = bool(oc.get("adaptive_enabled", True))
            breeding_on = bool(oc.get("breeding_enabled", True))
            interval_m = max(5, min(24 * 60, int(oc.get("interval_minutes") or 20)))
            if enabled or adaptive_on or breeding_on:
                try:
                    await run_optimizer_once(store, force=False)
                except Exception as e:
                    cur = await store.load_config()
                    oo = cur.get("optimizer") if isinstance(cur.get("optimizer"), dict) else {}
                    oo["last_run_at"] = dt.datetime.now(tz=dt.timezone.utc).isoformat()
                    oo["last_status"] = "error"
                    oo["last_error"] = str(e)[:500]
                    cur["optimizer"] = oo
                    await store.save_config(
                        cur, history_branch="global", history_changed_by="optimizer", history_reason="last_run_error"
                    )
            else:
                global _optimizer_all_idle_logged
                if not _optimizer_all_idle_logged:
                    _optimizer_all_idle_logged = True
                    logger.warning(
                        "optimizer loop idle: enabled=false, adaptive_enabled=false, breeding_enabled=false — "
                        "no Lab A scheduler/adaptive and no child-lab breeding; set at least one flag to true (grep=optimizer_loop_idle)"
                    )
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
        roll_open_committed = int(roll.get("open_committed_cents") or 0)
        ps = max(0, int(paper_start_cents))
        open_rows = await store.open_sim_trades_for_branch(engine.branch)
        # Use the same open rows for premium and marks so book vs MTM cannot drift if SQL rollups lag.
        if open_rows:
            open_committed = sum(int(r.get("amount_cents") or 0) for r in open_rows)
        else:
            open_committed = roll_open_committed
        mark = await compute_open_sim_mark_value_sum_cents(engine, open_rows)
        book_cents = ps + settled_pnl - open_committed
        mtm_cents = book_cents + mark
        out_metrics["current_equity_dollars"] = round(book_cents / 100.0, 4)
        out_metrics["open_sim_committed_dollars"] = round(open_committed / 100.0, 4)
        out_metrics["current_mtm_dollars"] = round(mtm_cents / 100.0, 4)
        psd = ps / 100.0
        if psd > 0:
            out_metrics["return_vs_start_pct"] = round(
                ((book_cents / 100.0) - psd) / psd * 100.0,
                4,
            )
            out_metrics["return_mtm_vs_start_pct"] = round(((mtm_cents / 100.0) - psd) / psd * 100.0, 4)
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
    fleet_paper_start_cents: int | None = None,
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
    if fleet_paper_start_cents is not None:
        fleet_ps = max(0, int(fleet_paper_start_cents)) / 100.0
        if fleet_ps > 0:
            m["committed_pct_of_fleet_start"] = round((committed / fleet_ps) * 100.0, 4)
    if latest_mtm_snap_dollars is not None:
        m["current_mtm_dollars"] = float(latest_mtm_snap_dollars)
        m["return_mtm_vs_start_pct"] = ((latest_mtm_snap_dollars - ps) / ps * 100.0) if ps > 0 else None
    if (
        latest_equity_snap_dollars is not None
        and ps > 0
        and abs(latest_equity_snap_dollars - eq) > 0.02
    ):
        m["equity_snap_vs_calc_diff_dollars"] = round(latest_equity_snap_dollars - eq, 4)


def _trade_extra_dict(t: dict[str, Any]) -> dict[str, Any]:
    raw = t.get("extra_json")
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(str(raw))
    except Exception:
        return {}


def _trade_matches_lab_branch(t: dict[str, Any], branch_key: str) -> bool:
    b = str(t.get("branch") or "live").strip().lower()
    if branch_key == BRANCH_LAB_A:
        return b in ("lab_a", "sim_lab")
    return b == branch_key


def _trade_is_paper_sim_row(t: dict[str, Any]) -> bool:
    mode = str(t.get("mode") or "").strip().lower()
    sim = int(t.get("simulated") or 0)
    return mode == "simulate" or (mode == "" and sim == 1)


def _trade_is_settled_row(t: dict[str, Any]) -> bool:
    if str(t.get("status") or "").strip().lower() != "settled":
        return False
    return t.get("pnl_cents") is not None


def _lab_settled_paper_rows(trades: list[dict[str, Any]], branch_key: str) -> list[dict[str, Any]]:
    """Recent trades are newest-first; keep only settled simulated rows for one lab branch."""
    out: list[dict[str, Any]] = []
    for t in trades:
        if not isinstance(t, dict):
            continue
        if not _trade_matches_lab_branch(t, branch_key):
            continue
        if not _trade_is_paper_sim_row(t) or not _trade_is_settled_row(t):
            continue
        out.append(t)
    return out


def _loss_streak_newest_first(settled_newest_first: list[dict[str, Any]]) -> int:
    streak = 0
    for t in settled_newest_first:
        try:
            pnl = int(t.get("pnl_cents") or 0)
        except (TypeError, ValueError):
            break
        if pnl < 0:
            streak += 1
        else:
            break
    return streak


def _entry_implied_yes_pct(t: dict[str, Any]) -> int | None:
    ex = _trade_extra_dict(t)
    raw = ex.get("entry_implied_yes")
    if raw is None or raw == "":
        return None
    try:
        return int(round(float(raw) * 100.0))
    except (TypeError, ValueError):
        return None


def _first_yes_rule_floor_pct(lab: dict[str, Any], cfg: dict[str, Any]) -> int | None:
    rules = lab.get("rules") if isinstance(lab.get("rules"), list) and lab.get("rules") else cfg.get("rules")
    if not isinstance(rules, list):
        return None
    for r in rules:
        if not isinstance(r, dict):
            continue
        side = str(r.get("side") or "yes").strip().lower()
        if side == "no":
            continue
        lo = r.get("min_prob")
        if lo is None or lo == "":
            continue
        try:
            return int(round(float(lo) * 100.0))
        except (TypeError, ValueError):
            continue
    return None


def _lab_thought_lines(
    *,
    label: str,
    branch_key: str,
    lab: dict[str, Any],
    cfg: dict[str, Any],
    trades: list[dict[str, Any]],
    metrics: dict[str, Any],
    engine_on: bool,
) -> list[str]:
    lines: list[str] = []
    settled_rows = _lab_settled_paper_rows(trades, branch_key)
    settled_n = int(metrics.get("settled_trades") or 0)
    open_n = int(metrics.get("open_sim_trades") or 0)
    ret_pct = metrics.get("return_mtm_vs_start_pct")
    if ret_pct is None:
        ret_pct = metrics.get("return_vs_start_pct")
    try:
        ret_s = f"{float(ret_pct):.1f}%" if ret_pct is not None else "—"
    except (TypeError, ValueError):
        ret_s = "—"
    wr = metrics.get("win_rate_pct")
    try:
        wr_s = f"{float(wr):.0f}% win rate" if wr is not None and settled_n else "win rate n/a"
    except (TypeError, ValueError):
        wr_s = "win rate n/a"

    if not engine_on:
        lines.append(
            f"{label} engine is off — idle; {settled_n} settled in DB, {open_n} open sims; last return vs basis ≈ {ret_s}."
        )
    else:
        lines.append(
            f"{label} scanning — {settled_n} settled, {open_n} open sim, return vs basis ≈ {ret_s} ({wr_s})."
        )

    streak = _loss_streak_newest_first(settled_rows)
    floor_pct = _first_yes_rule_floor_pct(lab if isinstance(lab, dict) else {}, cfg if isinstance(cfg, dict) else {})
    auto_opt = bool(lab.get("auto_optimize")) if isinstance(lab, dict) else False

    if streak >= 1 and settled_rows:
        last_loss = settled_rows[0]
        try:
            last_pnl = int(last_loss.get("pnl_cents") or 0)
        except (TypeError, ValueError):
            last_pnl = 0
        entry_pct = _entry_implied_yes_pct(last_loss) if last_pnl < 0 else None
        if streak >= 2 and entry_pct is not None:
            nudge = min(95, entry_pct + 1) if floor_pct is None else min(95, max(entry_pct + 1, floor_pct + 1))
            if auto_opt:
                lines.append(
                    f"{label} lost {streak} in a row with last entry near {entry_pct}% implied YES — "
                    f"considering whether to tighten bands toward ~{nudge}% floor (auto-optimize may nudge sizing on eligible ticks)."
                )
            else:
                lines.append(
                    f"{label} lost {streak} in a row with last entry near {entry_pct}% implied YES — "
                    f"review YES rule floors (currently ~{floor_pct if floor_pct is not None else 'unset'}%) vs recent entries."
                )
        elif streak >= 2 and entry_pct is None:
            lines.append(
                f"{label} lost {streak} in a row — comparing recent fills to configured YES/NO bands and open risk."
            )
        elif streak >= 1 and entry_pct is not None and last_pnl < 0:
            lines.append(
                f"{label} last settle was a loss near {entry_pct}% implied YES — watching for a second loss before suggesting a floor nudge."
            )
        elif streak == 0 and settled_rows:
            try:
                last_win_pnl = int(settled_rows[0].get("pnl_cents") or 0)
            except (TypeError, ValueError):
                last_win_pnl = 0
            if last_win_pnl >= 0:
                lines.append(f"{label} last settle was flat or green — loss streak reset.")

    note = lab.get("optimizer_note") if isinstance(lab, dict) else None
    if note:
        lines.append(f"{label} optimizer note: {str(note).strip()}")

    if floor_pct is not None and len(lines) < 4:
        lines.append(f"{label} primary YES band floor ≈ {floor_pct}% (from active rules).")

    if settled_n == 0 and len(lines) < 4:
        lines.append(f"{label} no settled paper rows yet — waiting for rules, liquidity, and windows to align.")

    return lines[:4]


def _lab_thought_stream(
    cfg: dict[str, Any],
    trades: list[dict[str, Any]],
    *,
    lab_a: dict[str, Any],
    lab_b: dict[str, Any],
    lab_c: dict[str, Any],
    lab_d: dict[str, Any],
    metrics_lab_a: dict[str, Any],
    metrics_lab_b: dict[str, Any],
    metrics_lab_c: dict[str, Any],
    metrics_lab_d: dict[str, Any],
    lab_a_engine_on: bool,
    lab_b_engine_on: bool,
    lab_c_engine_on: bool,
    lab_d_engine_on: bool,
) -> dict[str, list[str]]:
    la = lab_a if isinstance(lab_a, dict) else {}
    lb = lab_b if isinstance(lab_b, dict) else {}
    lc = lab_c if isinstance(lab_c, dict) else {}
    ld = lab_d if isinstance(lab_d, dict) else {}
    return {
        "lab_a": _lab_thought_lines(
            label="Lab A",
            branch_key=BRANCH_LAB_A,
            lab=la,
            cfg=cfg,
            trades=trades,
            metrics=metrics_lab_a,
            engine_on=lab_a_engine_on,
        ),
        "lab_b": _lab_thought_lines(
            label="Lab B",
            branch_key=BRANCH_LAB_B,
            lab=lb,
            cfg=cfg,
            trades=trades,
            metrics=metrics_lab_b,
            engine_on=lab_b_engine_on,
        ),
        "lab_c": _lab_thought_lines(
            label="Lab C",
            branch_key=BRANCH_LAB_C,
            lab=lc,
            cfg=cfg,
            trades=trades,
            metrics=metrics_lab_c,
            engine_on=lab_c_engine_on,
        ),
        "lab_d": _lab_thought_lines(
            label="Lab D (Wild)",
            branch_key=BRANCH_LAB_D,
            lab=ld,
            cfg=cfg,
            trades=trades,
            metrics=metrics_lab_d,
            engine_on=lab_d_engine_on,
        ),
    }


@asynccontextmanager
async def _app_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    t0 = time.perf_counter()
    prof = bool(env.profile_startup)
    restore_ttl_task: asyncio.Task[None] | None = None
    if prof:
        logger.info("kalshibot_startup_begin")

    def _log_phase(name: str) -> None:
        if prof:
            logger.info("kalshibot_startup phase=%s total_ms=%.1f", name, (time.perf_counter() - t0) * 1000.0)

    reset_uvicorn_loggers_to_root()
    state.stop_event.clear()
    state.startup_complete.clear()
    state.kalshi_ws_task = None
    state.app_started_at_iso = dt.datetime.now(tz=dt.timezone.utc).replace(microsecond=0).isoformat()

    # One shared httpx connection pool (no per-request ``AsyncClient()`` construction).
    state.http_client = new_shared_http_client()
    kc = KalshiClient(http_client=state.http_client)
    state.shared_kalshi = kc
    KalshiClient.apply_cold_start_cache_ttls(
        open_markets=float(env.kalshi_cold_start_cache_ttl_s),
        orderbooks=min(60.0, float(env.kalshi_cold_start_cache_ttl_s)),
        single_market=15.0,
    )
    _log_phase("http_client_and_cold_ttls")

    # PHASE 4: inject the process-shared Kalshi client into every TradingEngine.
    init_runtime_engines(state.require_kalshi())
    _log_phase("trading_engines")

    # Single batched /markets pre-warm so five branches do not each cold-miss the same series.
    try:
        full_cfg = await store.load_config()
        await prewarm_open_markets_for_config(kc, full_cfg, max_concurrent=int(env.prewarm_max_concurrent))
    except Exception as e:
        logger.warning("prewarm_open_markets skipped: %s", e)
    _log_phase("prewarm_open_markets")

    # PHASE 2: strict sequence — engines exist, shared client + cold TTLs, then pre-warm; only then tickers for WS + startup gate.
    try:
        KalshiClient.seed_ws_market_tickers(max_tickers=int(env.kalshi_ws_max_markets))
    except Exception as e:
        logger.warning("seed_ws_market_tickers skipped: %s", e)
    state.startup_complete.set()
    _log_phase("startup_complete")

    async def _restore_cache_ttls_after_delay() -> None:
        try:
            await asyncio.sleep(float(env.startup_restore_ttls_delay_s))
            KalshiClient.apply_steady_state_cache_ttls()
            if prof:
                logger.info("kalshibot_startup steady_state_ttls_restored")
        except asyncio.CancelledError:
            raise
        except Exception:
            pass

    restore_ttl_task = asyncio.create_task(_restore_cache_ttls_after_delay())

    # PHASE 2: background work only after pre-warm and startup_complete (dual_engine_loop also awaits the event).
    state.bg_task = asyncio.create_task(dual_engine_loop(state.ENGINES, state.stop_event))
    state.optimizer_task = asyncio.create_task(_optimizer_loop(state.stop_event))
    if env.kalshi_ws_enabled:
        state.kalshi_ws_task = asyncio.create_task(kalshi_ws_task_group_runner(kc, state.stop_event))
        _log_phase("kalshi_ws_task")
    if prof:
        logger.info("kalshibot_startup_ready total_ms=%.1f", (time.perf_counter() - t0) * 1000.0)
    try:
        yield
    finally:
        if restore_ttl_task is not None:
            restore_ttl_task.cancel()
            try:
                await restore_ttl_task
            except (asyncio.CancelledError, Exception):
                pass
        state.stop_event.set()
        tasks = [t for t in (state.bg_task, state.optimizer_task, state.kalshi_ws_task) if t is not None]
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        state.bg_task = None
        state.optimizer_task = None
        state.kalshi_ws_task = None
        state.app_started_at_iso = None
        if state.http_client is not None:
            await state.http_client.aclose()
        state.http_client = None
        # Close lazy-owned client in ``require_kalshi`` path; shared pool already closed above.
        if state.shared_kalshi is not None and getattr(state.shared_kalshi, "_own_http", False):
            await state.shared_kalshi.aclose()
        state.shared_kalshi = None


app = FastAPI(title="Kalshi Bot", lifespan=_app_lifespan)

app.add_middleware(SecurityHeadersMiddleware)
if env.api_bearer_token:
    app.add_middleware(ApiBearerAuthMiddleware, token=env.api_bearer_token)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Last added = outermost: request_id + structlog context for all HTTP handlers
app.add_middleware(RequestContextMiddleware)

app.include_router(public_root.router)
app.include_router(health_routes.router)
app.include_router(optimizer_routes.router)


@app.post("/api/config/validate-rules")
async def validate_rules_endpoint(body: dict[str, Any]) -> dict[str, Any]:
    """Validate a proposed ``rules`` array with the same ``RuleCfg`` checks as persisted lab/live saves."""
    raw = body.get("rules")
    try:
        norm = normalize_rules_list(raw)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, "count": len(norm), "rules": norm}


async def _seed_equity_snapshots_after_reset(scope: str) -> None:
    """
    ``reset_trading_data`` DELETEs ``equity_snapshots`` for that scope but nothing else writes a new row
    until the next engine tick — charts look frozen at the pre-reset tail. Plant one current snapshot per
    affected branch so book/MTM baselines and intraday history advance immediately.
    """
    s = str(scope or "all").strip().lower()
    if s == "all":
        order = (BRANCH_LIVE, BRANCH_LAB_A, BRANCH_LAB_B, BRANCH_LAB_C, BRANCH_LAB_D)
    elif s == "all_labs":
        # Bulk "all labs" reset also clears **Live** trading history (same action in Settings).
        order = (BRANCH_LIVE, *BRANCH_LABS, *BRANCH_CHILD_LABS)
    elif s in ("both", "lab_both", "a+b"):
        order = (BRANCH_LAB_A, BRANCH_LAB_B)
    else:
        m = {
            "live": BRANCH_LIVE,
            "lab_a": BRANCH_LAB_A,
            "lab_b": BRANCH_LAB_B,
            "lab_c": BRANCH_LAB_C,
            "lab_d": BRANCH_LAB_D,
            **{ck: ck for ck in BRANCH_CHILD_LABS},
        }
        k = m.get(s)
        order = (k,) if k else ()
    for br in order:
        eng = state.ENGINES.get(br)
        if not eng:
            continue
        try:
            await snapshot_equity(eng)
        except Exception as e:
            logger.warning("equity snapshot seed after reset failed branch=%s: %s", br, e)


def _clear_engine_mem_after_reset(branch_scope: str) -> None:
    """Clear in-memory tick snapshots for engines touched by a data reset."""
    if branch_scope == "all":
        keys = list(state.ENGINES.keys())
    else:
        m = {
            "live": BRANCH_LIVE,
            "lab_a": BRANCH_LAB_A,
            "lab_b": BRANCH_LAB_B,
            "lab_c": BRANCH_LAB_C,
            "lab_d": BRANCH_LAB_D,
            **{ck: ck for ck in BRANCH_CHILD_LABS},
        }
        k = m.get(branch_scope)
        keys = [k] if k else []
    for key in keys:
        eng = state.ENGINES.get(key)
        if not eng:
            continue
        eng.state.asset_snapshots = {}
        eng.state.last_tick_trace = None
        eng.state.markets_scanned = 0
        eng.state.last_error = None
        eng._paper_auto_reset_streak_handled = False
        # Critical: DB reset removed rows but dedupe keys lived only in RAM — without this,
        # the engine can skip all signals/trades until the clock window rolls.
        eng._seen_keys.clear()
        eng._last_window_id = None
        eng._tick_count = 0
        eng._study_quarter_wid = None
        eng._study_asset_fired.clear()
        eng._study_cap_logged.clear()
        eng._sim_asset_budget_fired.clear()
        eng._sim_transient_skip_logged.clear()


_MAX_UNIFORM_PAPER_BALANCE_CENTS = 100_000_000


async def _apply_uniform_paper_balance_after_scope_reset(scope: str, cents: int) -> dict[str, Any]:
    """After ``all`` or ``all_labs`` reset, set the same paper bankroll seed on Live and every lab."""
    s = str(scope or "").strip().lower()
    if s not in ("all", "all_labs"):
        return {}
    c = max(0, min(_MAX_UNIFORM_PAPER_BALANCE_CENTS, int(cents)))
    # Single locked read-modify-write in ``Store`` so concurrent optimizer saves cannot be stomped by a
    # stale full-config snapshot (and uniform paper cannot clobber fresh ``optimizer`` JSON).
    return await store.apply_uniform_paper_balance_after_scope_reset(
        c,
        history_branch="global",
        history_changed_by="api:data_reset",
        history_reason="uniform_paper_balance_after_scope_reset",
    )


@app.post("/api/data/reset")
async def data_reset(
    request: Request,
    confirm: str = Query("", description="Must be yes / true / 1 / y"),
    backup: bool = Query(True, description="Copy sqlite + JSONL table dumps before delete"),
    branch: str = Query(
        "all",
        description="all | all_labs (Live + A–D) | live | lab_a | lab_b | lab_c | lab_d — scope of DELETE on signals/trades/equity_snapshots",
    ),
    uniform_paper_balance_cents: int | None = Query(
        None,
        description="When branch is all or all_labs: after reset, set this paper_balance_cents on Live + every lab",
    ),
) -> dict[str, Any]:
    """
    Wipe **signals**, **trades**, and **equity_snapshots** (all rows, or one branch). ``bot_config`` is kept.
    Optional env ``DATA_RESET_TOKEN``: then require header ``X-Reset-Token`` matching it.

    ``branch`` = **all_labs**: deletes trading rows for **Live** and **lab_a–lab_d** (not only labs). When
    ``uniform_paper_balance_cents`` is set, Live paper and each lab's ``paper_balance_cents`` are updated to that
    value after the wipe, using a single locked read-modify-write so ``optimizer`` and the rest of ``bot_config``
    are not clobbered by a stale snapshot.
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
    if br not in ("all", "live", "lab_a", "lab_b", "lab_c", "lab_d", "all_labs"):
        raise HTTPException(
            status_code=400,
            detail="branch must be all, all_labs, live, lab_a, lab_b, lab_c, or lab_d",
        )
    if uniform_paper_balance_cents is not None and br not in ("all", "all_labs"):
        raise HTTPException(
            status_code=400,
            detail="uniform_paper_balance_cents is only allowed when branch is all or all_labs",
        )
    try:
        if br == "all_labs":
            for br2 in ("lab_a", "lab_b", "lab_c", "lab_d"):
                _clear_engine_mem_after_reset(br2)
            out = await store.reset_trading_data(backup=backup, branch="lab_a")
            await store.reset_trading_data(backup=False, branch="lab_b")
            await store.reset_trading_data(backup=False, branch="lab_c")
            await store.reset_trading_data(backup=False, branch="lab_d")
            _clear_engine_mem_after_reset("live")
            await store.reset_trading_data(backup=False, branch="live")
            for br2 in ("lab_a", "lab_b", "lab_c", "lab_d"):
                _clear_engine_mem_after_reset(br2)
            _clear_engine_mem_after_reset("live")
            out = dict(out)
            out["branch"] = "all_labs"
            await _seed_equity_snapshots_after_reset("all_labs")
            if uniform_paper_balance_cents is not None:
                u = await _apply_uniform_paper_balance_after_scope_reset("all_labs", uniform_paper_balance_cents)
                if u:
                    out["uniform_paper_balance"] = u
            return out
        pre_scope = "all" if br == "all" else br
        _clear_engine_mem_after_reset(pre_scope)
        out = await store.reset_trading_data(backup=backup, branch=None if br == "all" else br)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    _clear_engine_mem_after_reset(out.get("branch") or "all")
    await _seed_equity_snapshots_after_reset(str(out.get("branch") or "all"))
    out_final = dict(out)
    scope_ret = str(out_final.get("branch") or "all")
    if uniform_paper_balance_cents is not None and scope_ret in ("all", "all_labs"):
        u = await _apply_uniform_paper_balance_after_scope_reset(scope_ret, uniform_paper_balance_cents)
        if u:
            out_final["uniform_paper_balance"] = u
    return out_final


@app.get("/api/config")
async def get_config() -> dict[str, Any]:
    return await store.load_config()


def _config_live_paper_flag(cfg: dict[str, Any]) -> bool:
    """
    **Protected** key: when ``True``, Live uses paper / simulated order flow. Canonical
    ``live_paper_trading`` is kept in sync with legacy ``simulate``; writes are restricted when
    disabling paper (real orders) on Live.
    """
    return live_paper_trading_enabled(cfg)


def _live_paper_disable_audit_meta(
    request: Request,
    *,
    confirm_query: str,
    request_body: dict[str, Any] | None = None,
    query_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Forensics blob stored in ``config_history.audit_meta`` when Live paper mode is turned off with ``confirm=YES``.

    Does not replace ``config_json`` (full merged config remains the primary snapshot); this object is JSON-only
    metadata for operators and incident review.
    """
    client = getattr(request, "client", None)
    host = getattr(client, "host", None) if client is not None else None
    return {
        "event": "live_paper_trading_disabled_confirm_yes",
        "confirm_token": str(confirm_query or "").strip().upper(),
        "client_host": host,
        "user_agent": (request.headers.get("user-agent") or "")[:2000],
        "x_forwarded_for": (request.headers.get("x-forwarded-for") or "")[:512],
        "x_real_ip": (request.headers.get("x-real-ip") or "")[:128],
        "request_body": request_body,
        "query_params": query_params,
    }


@app.get("/api/config/history")
async def get_config_history(
    limit: int = Query(20, ge=1, le=100),
    include_config: bool = Query(False, description="Include full parsed config objects (large)"),
) -> dict[str, Any]:
    """Return recent ``config_history`` rows (newest first; default last 20)."""
    rows = await store.list_config_history(limit, include_config=include_config)
    return {"count": len(rows), "rows": rows}


@app.put("/api/config")
async def put_config(
    request: Request,
    body: BotConfigPayload,
    confirm: str = Query("", description="Required YES when setting simulate=False (disable Live paper)"),
    config_change_reason: str | None = Query(None, description="Optional short note stored on config_history"),
) -> dict[str, Any]:
    cur = await store.load_config()
    was_paper = _config_live_paper_flag(cur)
    merged = body.merged_into(cur)
    if was_paper and not _config_live_paper_flag(merged):
        if str(confirm).strip().upper() != "YES":
            logger.warning(
                "blocked PUT /api/config: disabling Live paper (simulate->false) without confirm=YES from %s",
                getattr(getattr(request, "client", None), "host", "unknown"),
            )
            raise HTTPException(
                status_code=400,
                detail="Disabling paper trading for Live (simulate=false) requires query confirm=YES (real orders if keys allow).",
            )
        logger.info("PUT /api/config: Live paper trading disabled (simulate=False) with confirm=YES")
    paper_off_audit: dict[str, Any] | None = None
    if was_paper and not _config_live_paper_flag(merged):
        try:
            body_snap = body.model_dump(mode="json")
        except Exception:
            body_snap = {"error": "model_dump_failed"}
        paper_off_audit = _live_paper_disable_audit_meta(
            request,
            confirm_query=confirm,
            request_body=body_snap if isinstance(body_snap, dict) else {"payload": body_snap},
        )
    hist_reason = config_change_reason
    if paper_off_audit is not None:
        hist_reason = hist_reason or "live_paper_trading disabled via PUT /api/config (confirm=YES)"
    await store.save_config(
        merged,
        history_branch="global",
        history_changed_by="api:put_config",
        history_reason=hist_reason,
        history_audit_meta=paper_off_audit,
    )
    return merged


@app.put("/api/config/lab-branches")
async def put_lab_branches(body: dict[str, Any]) -> dict[str, Any]:
    """
    Merge ``lab_a`` / ``lab_b`` / ``lab_c`` / ``lab_d`` without the general ``BotConfigPayload`` shape.

    Optional ``reset_data``: ``none`` | ``lab_a`` | ``lab_b`` | ``lab_c`` | ``lab_d`` | ``both`` (A+B) | ``all_labs`` (Live + A–D; trading rows for Live and all four labs).
    ``backup`` (default true) is passed to the first wipe in a multi-branch reset.
    """
    reset = str(body.get("reset_data") or "none").strip().lower()
    backup = bool(body.get("backup", True))
    if reset == "all_labs":
        for br in ("lab_a", "lab_b", "lab_c", "lab_d"):
            _clear_engine_mem_after_reset(br)
        await store.reset_trading_data(backup=backup, branch="lab_a")
        await store.reset_trading_data(backup=False, branch="lab_b")
        await store.reset_trading_data(backup=False, branch="lab_c")
        await store.reset_trading_data(backup=False, branch="lab_d")
        _clear_engine_mem_after_reset("live")
        await store.reset_trading_data(backup=False, branch="live")
        for br in ("lab_a", "lab_b", "lab_c", "lab_d"):
            _clear_engine_mem_after_reset(br)
        _clear_engine_mem_after_reset("live")
        await _seed_equity_snapshots_after_reset("all_labs")
    elif reset == "both":
        _clear_engine_mem_after_reset("lab_a")
        _clear_engine_mem_after_reset("lab_b")
        await store.reset_trading_data(backup=backup, branch="lab_a")
        await store.reset_trading_data(backup=False, branch="lab_b")
        _clear_engine_mem_after_reset("lab_a")
        _clear_engine_mem_after_reset("lab_b")
        await _seed_equity_snapshots_after_reset("both")
    elif reset == "lab_a":
        _clear_engine_mem_after_reset("lab_a")
        await store.reset_trading_data(backup=backup, branch="lab_a")
        _clear_engine_mem_after_reset("lab_a")
        await _seed_equity_snapshots_after_reset("lab_a")
    elif reset == "lab_b":
        _clear_engine_mem_after_reset("lab_b")
        await store.reset_trading_data(backup=backup, branch="lab_b")
        _clear_engine_mem_after_reset("lab_b")
        await _seed_equity_snapshots_after_reset("lab_b")
    elif reset == "lab_c":
        _clear_engine_mem_after_reset("lab_c")
        await store.reset_trading_data(backup=backup, branch="lab_c")
        _clear_engine_mem_after_reset("lab_c")
        await _seed_equity_snapshots_after_reset("lab_c")
    elif reset == "lab_d":
        _clear_engine_mem_after_reset("lab_d")
        await store.reset_trading_data(backup=backup, branch="lab_d")
        _clear_engine_mem_after_reset("lab_d")
        await _seed_equity_snapshots_after_reset("lab_d")
    elif reset not in ("none", ""):
        raise HTTPException(
            status_code=400,
            detail="reset_data must be none, lab_a, lab_b, lab_c, lab_d, both, or all_labs",
        )

    cfg = await store.load_config()

    def _coerce_rules_in_lab_patch(merged: dict[str, Any]) -> None:
        if "rules" not in merged:
            return
        try:
            merged["rules"] = normalize_rules_list(merged["rules"])
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    la = body.get("lab_a")
    if isinstance(la, dict):
        merged_a = merge_lab_branch_patch(dict(cfg.get("lab_a") or {}), la)
        _coerce_rules_in_lab_patch(merged_a)
        cfg["lab_a"] = expand_partial_lab_branch("lab_a", merged_a)
    lb = body.get("lab_b")
    if isinstance(lb, dict):
        merged_b = merge_lab_branch_patch(dict(cfg.get("lab_b") or {}), lb)
        _coerce_rules_in_lab_patch(merged_b)
        cfg["lab_b"] = expand_partial_lab_branch("lab_b", merged_b)
    lc = body.get("lab_c")
    if isinstance(lc, dict):
        merged_c = merge_lab_branch_patch(dict(cfg.get("lab_c") or {}), lc)
        _coerce_rules_in_lab_patch(merged_c)
        cfg["lab_c"] = expand_partial_lab_branch("lab_c", merged_c)
    ld = body.get("lab_d")
    if isinstance(ld, dict):
        merged_d = merge_lab_branch_patch(dict(cfg.get("lab_d") or {}), ld)
        _coerce_rules_in_lab_patch(merged_d)
        cfg["lab_d"] = expand_partial_lab_branch("lab_d", merged_d)
    await store.save_config(
        cfg,
        history_branch="global",
        history_changed_by="api:put_lab_branches",
        history_reason=str(body.get("reset_data") or "lab_merge")[:200] or None,
    )
    return {"ok": True, "config": await store.load_config()}


@app.post("/api/config/promote-lab-a-to-live")
async def promote_lab_a_to_live(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    """
    Copy Lab A trading overlays (rules, sizing, filters, etc.) onto top-level Live config.

    By default requires settled paper PnL (cents) on Lab A to exceed both Lab B and Lab C.
    When ``simulate`` is false (real Kalshi orders), ``ack_live`` must match the UI confirmation token.
    """
    if not bool(body.get("confirm")):
        raise HTTPException(status_code=400, detail="confirm must be true")
    cfg = await store.load_config()
    simulate = live_paper_trading_enabled(cfg)
    if not simulate:
        if str(body.get("ack_live") or "").strip() != "APPLY_LIVE":
            raise HTTPException(
                status_code=400,
                detail="ack_live must be APPLY_LIVE when simulate is false (real-money Live branch).",
            )
    skip_gate = bool(body.get("skip_pnl_gate"))
    if not skip_gate:
        roll_a = await store.dashboard_branch_trade_rollups(BRANCH_LAB_A, "simulate")
        roll_b = await store.dashboard_branch_trade_rollups(BRANCH_LAB_B, "simulate")
        roll_c = await store.dashboard_branch_trade_rollups(BRANCH_LAB_C, "simulate")
        roll_d = await store.dashboard_branch_trade_rollups(BRANCH_LAB_D, "simulate")
        pa = int(roll_a.get("total_pnl_cents") or 0)
        pb = int(roll_b.get("total_pnl_cents") or 0)
        pc = int(roll_c.get("total_pnl_cents") or 0)
        pd = int(roll_d.get("total_pnl_cents") or 0)
        if not (pa > pb and pa > pc and pa > pd):
            raise HTTPException(
                status_code=400,
                detail="lab_a_settled_pnl_cents_must_exceed_lab_b_and_lab_c_and_lab_d",
            )
        promo = await lab_a_promotion_report(store, cfg)
        if not bool(promo.get("promotion_gates_ok")):
            logger.warning("promotion_blocked report=%s", promo)
            raise HTTPException(
                status_code=400,
                detail="lab_a_must_pass_composite_and_statistical_gates_vs_controls",
            )
    lab_a = cfg.get("lab_a")
    if not isinstance(lab_a, dict):
        raise HTTPException(status_code=400, detail="lab_a_not_configured")
    for k in LAB_BRANCH_OVERLAY_KEYS:
        if k not in lab_a:
            continue
        v = lab_a[k]
        if v is None:
            continue
        if k == "assets" and isinstance(v, dict) and len(v) == 0:
            continue
        cfg[k] = copy.deepcopy(v) if isinstance(v, (dict, list)) else v
    await store.save_config(
        cfg,
        history_branch="global",
        history_changed_by="api:promote_lab_a_to_live",
        history_reason=None,
    )
    return {"ok": True, "config": await store.load_config()}


@app.post("/api/config/labs/add-paper-bankroll")
async def add_labs_paper_bankroll(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    """
    Add the same amount to Lab A / B / C / D ``paper_balance_cents`` (default **10_000** = $100.00 each).

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
    for br_key in ("lab_a", "lab_b", "lab_c", "lab_d"):
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
    await store.save_config(
        cfg,
        history_branch="global",
        history_changed_by="api:add_labs_paper_bankroll",
        history_reason=f"add_cents={add_cents}",
    )
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
async def engine_status() -> EngineStatusResponse:
    cfg = await store.load_config()
    lab_a = cfg.get("lab_a") if isinstance(cfg.get("lab_a"), dict) else {}
    lab_b = cfg.get("lab_b") if isinstance(cfg.get("lab_b"), dict) else {}
    lab_c = cfg.get("lab_c") if isinstance(cfg.get("lab_c"), dict) else {}
    lab_d = cfg.get("lab_d") if isinstance(cfg.get("lab_d"), dict) else {}
    return {
        "live": _engine_status_block(
            state.engine_live,
            engine_running=bool(cfg.get("engine_running")),
            simulate_orders=live_paper_trading_enabled(cfg),
            extra={"simulate": live_paper_trading_enabled(cfg)},
        ),
        "lab_a": _engine_status_block(
            state.engine_lab_a,
            engine_running=bool(lab_a.get("engine_running")),
            simulate_orders=True,
            extra={"auto_optimize": bool(lab_a.get("auto_optimize")), "optimizer_note": lab_a.get("optimizer_note")},
        ),
        "lab_b": _engine_status_block(
            state.engine_lab_b,
            engine_running=bool(lab_b.get("engine_running")),
            simulate_orders=True,
            extra={"auto_optimize": bool(lab_b.get("auto_optimize")), "optimizer_note": lab_b.get("optimizer_note")},
        ),
        "lab_c": _engine_status_block(
            state.engine_lab_c,
            engine_running=bool(lab_c.get("engine_running")),
            simulate_orders=True,
            extra={"auto_optimize": bool(lab_c.get("auto_optimize")), "optimizer_note": lab_c.get("optimizer_note")},
        ),
        "lab_d": _engine_status_block(
            state.engine_lab_d,
            engine_running=bool(lab_d.get("engine_running")),
            simulate_orders=True,
            extra={"auto_optimize": bool(lab_d.get("auto_optimize")), "optimizer_note": lab_d.get("optimizer_note")},
        ),
    }


@app.get("/api/account")
async def account() -> AccountResponse:
    client = require_kalshi()
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
) -> MarketPulseResponse:
    b = str(branch or "live").strip().lower()
    if b == "sim_lab":
        b = BRANCH_LAB_A
    if b not in (BRANCH_LIVE, BRANCH_LAB_A, BRANCH_LAB_B, BRANCH_LAB_C, BRANCH_LAB_D):
        b = BRANCH_LIVE
    # PHASE 3.1: typed contract only; payload remains identical.
    return cast(MarketPulseResponse, await fetch_market_pulse(store, branch=b, include_unpriced=include_unpriced))


@app.get("/api/markets/preview")
async def markets_preview(
    series_ticker: str,
    include_unpriced: bool = Query(False, description="If true, include rows whose YES subtitle matches exclude_* (e.g. TBD)."),
) -> MarketsPreviewResponse:
    client = require_kalshi()
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
    """Merge Kalshi portfolio rows that share the same normalized ticker under this series prefix."""
    by_tick: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for p in kalshi_positions:
        tick_raw = str(p.get("ticker") or p.get("market_ticker") or "").strip()
        tick = tick_raw.upper()
        if not (series_upper and tick.startswith(series_upper)):
            continue
        qty = p.get("position_fp")
        if qty is None:
            qty = p.get("position")
        if tick not in by_tick:
            row: dict[str, Any] = {"ticker": p.get("ticker") or p.get("market_ticker") or tick_raw, "position": qty}
            for k in (
                "average_price_dollars",
                "average_yes_price_dollars",
                "yes_average_price_dollars",
                "average_price",
                "market_exposure_dollars",
                "total_traded_dollars",
            ):
                if p.get(k) is not None and p.get(k) != "":
                    row[k] = p.get(k)
            by_tick[tick] = row
            order.append(tick)
            continue
        agg = by_tick[tick]
        try:
            q0 = float(str(agg.get("position") or "0").replace(",", ""))
            q1 = float(str(qty or "0").replace(",", ""))
            agg["position"] = q0 + q1
        except (TypeError, ValueError):
            agg["position"] = qty
        agg["ticket_count"] = int(agg.get("ticket_count") or 1) + 1
    return [by_tick[k] for k in order[:16]]


def _entry_yes_from_open_sim_trade(t: dict[str, Any]) -> float | None:
    raw = t.get("limit_yes_dollars")
    if raw is None or raw == "":
        return None
    try:
        v = float(str(raw))
    except (TypeError, ValueError):
        return None
    if 0 < v < 1:
        return v
    return None


def _open_sim_rows_for_series(
    series_upper: str, trades: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """
    One row per **normalized** market ticker under this series prefix: duplicate SQLite open rows for the same
    contract are merged (sum ``contracts_fp``, ``ticket_count`` for the holdings tooltip).
    """
    seen_ids: set[int] = set()
    by_tick: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    def _fp_sum(a: Any, b: Any) -> str:
        try:
            x = float(str(a or "0").replace(",", ""))
            y = float(str(b or "0").replace(",", ""))
            s = x + y
            if abs(s - round(s)) < 1e-6:
                return str(int(round(s)))
            return f"{s:.2f}"
        except (TypeError, ValueError):
            return str(a or b or "0")

    for t in trades:
        tid = t.get("id")
        if tid is not None:
            try:
                ii = int(tid)
            except (TypeError, ValueError):
                ii = None
            if ii is not None:
                if ii in seen_ids:
                    continue
                seen_ids.add(ii)
        tick_raw = str(t.get("ticker") or "").strip()
        tick_up = tick_raw.upper()
        if not (series_upper and tick_up.startswith(series_upper)):
            continue
        entry = _entry_yes_from_open_sim_trade(t)
        if tick_up not in by_tick:
            by_tick[tick_up] = {
                "id": t.get("id"),
                "ticker": tick_raw or tick_up,
                "contracts_fp": str(t.get("contracts_fp") or "0"),
                "status": t.get("status"),
                "side": str(t.get("side") or "yes").strip().lower(),
                "entry_yes_dollars": entry,
                "ticket_count": 1,
            }
            order.append(tick_up)
            continue
        agg = by_tick[tick_up]
        agg["contracts_fp"] = _fp_sum(agg.get("contracts_fp"), t.get("contracts_fp"))
        agg["ticket_count"] = int(agg.get("ticket_count") or 1) + 1
    return [by_tick[k] for k in order[:16]]


def _position_by_asset(
    assets_cfg: dict[str, Any],
    kalshi_positions_raw: list[Any],
    sim_open_live: list[dict[str, Any]],
    sim_open_lab_a: list[dict[str, Any]],
    sim_open_lab_b: list[dict[str, Any]],
    sim_open_lab_c: list[dict[str, Any]],
    sim_open_lab_d: list[dict[str, Any]],
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
        lab_d_rows = _open_sim_rows_for_series(st, sim_open_lab_d)
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
            "bot_sim_open_lab_d": lab_d_rows,
        }
    return out


def _sim_open_holdings_asset_count(position_by_asset: dict[str, Any], branch: str) -> int:
    """
    Number of **Holdings asset rows** with any open sim for this branch (one count per configured asset).

    Matches the Sim open column in the table: BTC is 1 row even when the cell lists two market tickers.
    Excludes assets whose sim cell is empty; excludes orphan DB rows outside every ``series_ticker``.
    """
    b = str(branch or "").strip().lower()
    if b in ("", "none"):
        b = BRANCH_LIVE
    if b == "sim_lab":
        b = BRANCH_LAB_A
    n = 0
    for row in position_by_asset.values():
        if not isinstance(row, dict):
            continue
        arr: Any = None
        if b == BRANCH_LIVE:
            arr = row.get("bot_sim_open_live")
        elif b == BRANCH_LAB_A:
            arr = row.get("bot_sim_open_lab_a")
            if (not isinstance(arr, list)) or len(arr) == 0:
                arr = row.get("bot_sim_open_lab")
        elif b == BRANCH_LAB_B:
            arr = row.get("bot_sim_open_lab_b")
        elif b == BRANCH_LAB_C:
            arr = row.get("bot_sim_open_lab_c")
        elif b == BRANCH_LAB_D:
            arr = row.get("bot_sim_open_lab_d")
        else:
            continue
        if isinstance(arr, list) and len(arr) > 0:
            n += 1
    return n


async def _compose_dashboard_base(*, with_marks: bool) -> DashboardResponse:
    """
    Assemble the full dashboard JSON. When ``with_marks`` is False, the same
    ``_refresh_paper_mtm_from_marks`` work runs with a configurable timeout
    (``DASHBOARD_FAST_MTM_GATHER_TIMEOUT_S``, default ~22s) so ``GET /api/dashboard/equity``
    can still update paper MTM between full ~12s refreshes; on timeout, metrics fall back to
    snapshot-based values from ``_enrich_strategy_metrics`` (flat MTM vs book until the next full poll).
    """
    cfg = await store.load_config()
    mode_live = "simulate" if live_paper_trading_enabled(cfg) else "live"
    # I/O in parallel: sequential awaits here plus ~55s MTM easily exceeded the browser 90s budget.
    (
        trades,
        signals,
        snaps_live,
        snaps_lab_a,
        snaps_lab_b,
        snaps_lab_c,
        snaps_lab_d,
        roll_live,
        roll_lab_a,
        roll_lab_b,
        roll_lab_c,
        roll_lab_d,
    ) = await asyncio.gather(
        store.recent_trades(limit=500),
        store.recent_signals(limit=500),
        store.equity_series(limit=2000, branch=BRANCH_LIVE),
        store.equity_series(limit=2000, branch=BRANCH_LAB_A),
        store.equity_series(limit=2000, branch=BRANCH_LAB_B),
        store.equity_series(limit=2000, branch=BRANCH_LAB_C),
        store.equity_series(limit=2000, branch=BRANCH_LAB_D),
        store.dashboard_branch_trade_rollups(BRANCH_LIVE, mode_live),
        store.dashboard_branch_trade_rollups(BRANCH_LAB_A, "simulate"),
        store.dashboard_branch_trade_rollups(BRANCH_LAB_B, "simulate"),
        store.dashboard_branch_trade_rollups(BRANCH_LAB_C, "simulate"),
        store.dashboard_branch_trade_rollups(BRANCH_LAB_D, "simulate"),
    )
    metrics_live = _metrics_from_trade_rollup(roll_live, BRANCH_LIVE)
    metrics_lab_a = _metrics_from_trade_rollup(roll_lab_a, BRANCH_LAB_A)
    metrics_lab_b = _metrics_from_trade_rollup(roll_lab_b, BRANCH_LAB_B)
    metrics_lab_c = _metrics_from_trade_rollup(roll_lab_c, BRANCH_LAB_C)
    metrics_lab_d = _metrics_from_trade_rollup(roll_lab_d, BRANCH_LAB_D)

    not_traded = [s for s in signals if not int(s.get("executed") or 0)]

    lab_a = cfg.get("lab_a") if isinstance(cfg.get("lab_a"), dict) else {}
    lab_b = cfg.get("lab_b") if isinstance(cfg.get("lab_b"), dict) else {}
    lab_c = cfg.get("lab_c") if isinstance(cfg.get("lab_c"), dict) else {}
    lab_d = cfg.get("lab_d") if isinstance(cfg.get("lab_d"), dict) else {}
    live_engine_on = bool(cfg.get("engine_running"))
    lab_a_engine_on = bool(lab_a.get("engine_running")) if isinstance(lab_a, dict) else False
    lab_b_engine_on = bool(lab_b.get("engine_running")) if isinstance(lab_b, dict) else False
    lab_c_engine_on = bool(lab_c.get("engine_running")) if isinstance(lab_c, dict) else False
    lab_d_engine_on = bool(lab_d.get("engine_running")) if isinstance(lab_d, dict) else False
    def _child_lab_polling_on(raw: Any) -> bool:
        slab = raw if isinstance(raw, dict) else {}
        return slab.get("engine_running") is not False

    child_lab_engine_any_on = any(_child_lab_polling_on(cfg.get(ck)) for ck in BRANCH_CHILD_LABS)

    client = require_kalshi()
    public_ok = False
    public_err: str | None = None
    try:
        probe_coro = client.get_public("/markets", {"limit": "1"})
        port_coro = fetch_portfolio_snapshot(client)
        _probe, portfolio = await asyncio.gather(probe_coro, port_coro, return_exceptions=True)
        if isinstance(_probe, Exception):
            public_err = str(_probe)
        else:
            public_ok = True
        if isinstance(portfolio, Exception):
            portfolio = {
                "balance": None,
                "positions": [],
                "orders": [],
                "position_count": 0,
                "resting_order_count": 0,
                "error": f"portfolio: {portfolio}",
            }
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
    simulate_live = live_paper_trading_enabled(cfg)
    order_writes_live = portfolio_read_ok and not simulate_live

    fleet_paper_start = fleet_visible_paper_start_cents(cfg)
    fleet_for_committed = fleet_paper_start if fleet_paper_start > 0 else None

    _enrich_strategy_metrics(
        metrics_live,
        paper_mode=simulate_live,
        paper_start_cents=int(cfg.get("paper_balance_cents") or _DEFAULT_PAPER_BALANCE_CENTS),
        bal_json=bal_json if isinstance(bal_json, dict) else None,
        latest_equity_snap_dollars=_latest_equity_snapshot_dollars(snaps_live),
        latest_mtm_snap_dollars=_latest_mtm_snapshot_dollars(snaps_live),
        fleet_paper_start_cents=fleet_for_committed if simulate_live else None,
    )
    lab_paper_basis_a = lab_paper_equity_start_cents(cfg, BRANCH_LAB_A)
    _enrich_strategy_metrics(
        metrics_lab_a,
        paper_mode=True,
        paper_start_cents=lab_paper_basis_a,
        bal_json=None,
        latest_equity_snap_dollars=_latest_equity_snapshot_dollars(snaps_lab_a),
        latest_mtm_snap_dollars=_latest_mtm_snapshot_dollars(snaps_lab_a),
        fleet_paper_start_cents=fleet_for_committed,
    )
    lab_paper_basis_b = lab_paper_equity_start_cents(cfg, BRANCH_LAB_B)
    _enrich_strategy_metrics(
        metrics_lab_b,
        paper_mode=True,
        paper_start_cents=lab_paper_basis_b,
        bal_json=None,
        latest_equity_snap_dollars=_latest_equity_snapshot_dollars(snaps_lab_b),
        latest_mtm_snap_dollars=_latest_mtm_snapshot_dollars(snaps_lab_b),
        fleet_paper_start_cents=fleet_for_committed,
    )
    _inject_last_snap_mtm_minus_equity(metrics_live, snaps_live)
    _inject_last_snap_mtm_minus_equity(metrics_lab_a, snaps_lab_a)
    _inject_last_snap_mtm_minus_equity(metrics_lab_b, snaps_lab_b)
    lab_paper_basis_c = lab_paper_equity_start_cents(cfg, BRANCH_LAB_C)
    _enrich_strategy_metrics(
        metrics_lab_c,
        paper_mode=True,
        paper_start_cents=lab_paper_basis_c,
        bal_json=None,
        latest_equity_snap_dollars=_latest_equity_snapshot_dollars(snaps_lab_c),
        latest_mtm_snap_dollars=_latest_mtm_snapshot_dollars(snaps_lab_c),
        fleet_paper_start_cents=fleet_for_committed,
    )
    _inject_last_snap_mtm_minus_equity(metrics_lab_c, snaps_lab_c)
    lab_paper_basis_d = lab_paper_equity_start_cents(cfg, BRANCH_LAB_D)
    _enrich_strategy_metrics(
        metrics_lab_d,
        paper_mode=True,
        paper_start_cents=lab_paper_basis_d,
        bal_json=None,
        latest_equity_snap_dollars=_latest_equity_snapshot_dollars(snaps_lab_d),
        latest_mtm_snap_dollars=_latest_mtm_snapshot_dollars(snaps_lab_d),
        fleet_paper_start_cents=fleet_for_committed,
    )
    _inject_last_snap_mtm_minus_equity(metrics_lab_d, snaps_lab_d)

    # Paper MTM on tiles + chart tail: recompute from Kalshi mids. Full dashboard can wait 50s;
    # the fast ``/api/dashboard/equity`` poll (``with_marks=False``) uses a short cap so the UI
    # can refresh chart tails more often than the 12s full round-trip without stalling the client.
    mtm_tasks: list[Any] = []
    if simulate_live:
        mtm_tasks.append(
            _refresh_paper_mtm_from_marks(
                state.engine_live,
                paper_start_cents=int(cfg.get("paper_balance_cents") or _DEFAULT_PAPER_BALANCE_CENTS),
                roll=roll_live,
                out_metrics=metrics_live,
            )
        )
    mtm_tasks.extend(
        [
            _refresh_paper_mtm_from_marks(
                state.engine_lab_a,
                paper_start_cents=lab_paper_basis_a,
                roll=roll_lab_a,
                out_metrics=metrics_lab_a,
            ),
            _refresh_paper_mtm_from_marks(
                state.engine_lab_b,
                paper_start_cents=lab_paper_basis_b,
                roll=roll_lab_b,
                out_metrics=metrics_lab_b,
            ),
            _refresh_paper_mtm_from_marks(
                state.engine_lab_c,
                paper_start_cents=lab_paper_basis_c,
                roll=roll_lab_c,
                out_metrics=metrics_lab_c,
            ),
            _refresh_paper_mtm_from_marks(
                state.engine_lab_d,
                paper_start_cents=lab_paper_basis_d,
                roll=roll_lab_d,
                out_metrics=metrics_lab_d,
            ),
        ]
    )
    # ``/api/dashboard/equity`` can opt out of this batch via env (DASHBOARD_FAST_PAPER_MTM=0) to test or reduce load; full ``/api/dashboard`` always runs it.
    if mtm_tasks and (with_marks or env.dashboard_fast_paper_mtm):
        mtm_timeout = 50.0 if with_marks else float(env.dashboard_fast_mtm_gather_timeout_s)
        try:
            mtm_res = await asyncio.wait_for(
                asyncio.gather(*mtm_tasks, return_exceptions=True),
                timeout=mtm_timeout,
            )
            for idx, r in enumerate(mtm_res or []):
                if isinstance(r, Exception):
                    logger.debug("paper MTM subtask %d failed: %s", idx, r)
        except asyncio.TimeoutError:
            if with_marks:
                logger.warning(
                    "dashboard MTM refresh hit 50s cap — returning partial MTM (open sim marks skipped for slow branch/es)."
                )
            else:
                logger.warning(
                    "dashboard fast MTM refresh hit %.1fs cap — charts may flatline MTM vs book until next full /api/dashboard (raise DASHBOARD_FAST_MTM_GATHER_TIMEOUT_S or reduce open sims).",
                    mtm_timeout,
                )
            # Fast path timeout: leave ``metrics*`` on snapshot-based values from _enrich_strategy_metrics (stale vs live marks).
        except Exception as e:
            logger.warning("dashboard paper MTM batch failed: %s", e)

    eff_live = merge_branch_config(cfg, BRANCH_LIVE) if live_engine_on else None
    eff_lab_a = merge_branch_config(cfg, BRANCH_LAB_A) if lab_a_engine_on else None
    eff_lab_b = merge_branch_config(cfg, BRANCH_LAB_B) if lab_b_engine_on else None
    eff_lab_c = merge_branch_config(cfg, BRANCH_LAB_C) if lab_c_engine_on else None
    eff_lab_d = merge_branch_config(cfg, BRANCH_LAB_D) if lab_d_engine_on else None

    kalshi_pos_list = [p for p in (portfolio.get("positions") or []) if isinstance(p, dict)]
    sim_open_live, sim_open_lab_a, sim_open_lab_b, sim_open_lab_c, sim_open_lab_d = await asyncio.gather(
        store.open_sim_trades_for_branch(BRANCH_LIVE),
        store.open_sim_trades_for_branch(BRANCH_LAB_A),
        store.open_sim_trades_for_branch(BRANCH_LAB_B),
        store.open_sim_trades_for_branch(BRANCH_LAB_C),
        store.open_sim_trades_for_branch(BRANCH_LAB_D),
    )
    assets_cfg = cfg.get("assets") if isinstance(cfg.get("assets"), dict) else {}
    position_by_asset = _position_by_asset(
        assets_cfg, kalshi_pos_list, sim_open_live, sim_open_lab_a, sim_open_lab_b, sim_open_lab_c, sim_open_lab_d
    )

    # Rollups count every SQLite open sim on the branch. Override so ``open_sim_trades`` matches the Holdings
    # table: **one per configured asset row** that has any sim open (not sum of tickers inside a cell).
    metrics_live["open_sim_trades"] = _sim_open_holdings_asset_count(position_by_asset, BRANCH_LIVE)
    metrics_lab_a["open_sim_trades"] = _sim_open_holdings_asset_count(position_by_asset, BRANCH_LAB_A)
    metrics_lab_b["open_sim_trades"] = _sim_open_holdings_asset_count(position_by_asset, BRANCH_LAB_B)
    metrics_lab_c["open_sim_trades"] = _sim_open_holdings_asset_count(position_by_asset, BRANCH_LAB_C)
    metrics_lab_d["open_sim_trades"] = _sim_open_holdings_asset_count(position_by_asset, BRANCH_LAB_D)

    opt_blk = cfg.get("optimizer") if isinstance(cfg.get("optimizer"), dict) else {}
    ch_raw = opt_blk.get("change_history")
    ch_slim: list[dict[str, Any]] = []
    if isinstance(ch_raw, list):
        for x in ch_raw[:50]:
            if not isinstance(x, dict):
                continue
            rid = _optimizer_change_stable_id(x)
            ch_slim.append(
                {
                    "id": rid,
                    "created_at": x.get("created_at"),
                    "lab_label": x.get("lab_label"),
                    "style": x.get("style"),
                    "reason": x.get("reason"),
                    "summary": x.get("summary"),
                    "before": x.get("before"),
                    "after": x.get("after"),
                    "tick_hint": x.get("tick_hint"),
                }
            )
    runs_raw = await store.recent_optimizer_recommendations(limit=40)
    runs_slim: list[dict[str, Any]] = []
    for row in runs_raw:
        if not isinstance(row, dict):
            continue
        rj = row.get("recommendation_json")
        nrec = 0
        if isinstance(rj, dict):
            recs = rj.get("recommendations")
            nrec = len(recs) if isinstance(recs, list) else 0
        runs_slim.append(
            {
                "id": row.get("id"),
                "created_at": row.get("created_at"),
                "window_start": row.get("window_start"),
                "window_end": row.get("window_end"),
                "summary": str(row.get("summary") or "")[:800],
                "n_recommendations": nrec,
            }
        )

    if with_marks:
        DASHBOARD_ORDERBOOK_CACHE["t_mono"] = time.monotonic()
        DASHBOARD_ORDERBOOK_CACHE["payload"] = {
            "as_of_utc": dt.datetime.now(tz=dt.timezone.utc).isoformat(),
            "metrics": {"mode": mode_live, **metrics_live},
            "metrics_lab_a": metrics_lab_a,
            "metrics_lab_b": metrics_lab_b,
            "metrics_lab_c": metrics_lab_c,
            "metrics_lab_d": metrics_lab_d,
        }

    return {
        "config": cfg,
        "storage": storage_dict(),
        "kalshi": {
            "api_base": client.base,
            "env": env.kalshi_env,
            "public_ok": public_ok,
            "public_error": public_err,
            "private_ok": portfolio_read_ok,
            "private_error": private_err,
            "portfolio_notes": portfolio_notes,
            "polling_enabled": live_engine_on
            or lab_a_engine_on
            or lab_b_engine_on
            or lab_c_engine_on
            or lab_d_engine_on
            or child_lab_engine_any_on,
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
                "last_tick_at": state.engine_live.state.last_tick_at,
                "last_error": state.engine_live.state.last_error,
                "markets_scanned": state.engine_live.state.markets_scanned,
                "last_tick_trace": state.engine_live.state.last_tick_trace,
            },
            "lab_a": {
                "engine_running": lab_a_engine_on,
                "simulate_orders": bool(eff_lab_a.get("_simulate_orders")) if eff_lab_a else True,
                "last_tick_at": state.engine_lab_a.state.last_tick_at,
                "last_error": state.engine_lab_a.state.last_error,
                "markets_scanned": state.engine_lab_a.state.markets_scanned,
                "last_tick_trace": state.engine_lab_a.state.last_tick_trace,
            },
            "lab_b": {
                "engine_running": lab_b_engine_on,
                "simulate_orders": bool(eff_lab_b.get("_simulate_orders")) if eff_lab_b else True,
                "last_tick_at": state.engine_lab_b.state.last_tick_at,
                "last_error": state.engine_lab_b.state.last_error,
                "markets_scanned": state.engine_lab_b.state.markets_scanned,
                "last_tick_trace": state.engine_lab_b.state.last_tick_trace,
            },
            "lab_c": {
                "engine_running": lab_c_engine_on,
                "simulate_orders": bool(eff_lab_c.get("_simulate_orders")) if eff_lab_c else True,
                "last_tick_at": state.engine_lab_c.state.last_tick_at,
                "last_error": state.engine_lab_c.state.last_error,
                "markets_scanned": state.engine_lab_c.state.markets_scanned,
                "last_tick_trace": state.engine_lab_c.state.last_tick_trace,
            },
            "lab_d": {
                "engine_running": lab_d_engine_on,
                "simulate_orders": bool(eff_lab_d.get("_simulate_orders")) if eff_lab_d else True,
                "last_tick_at": state.engine_lab_d.state.last_tick_at,
                "last_error": state.engine_lab_d.state.last_error,
                "markets_scanned": state.engine_lab_d.state.markets_scanned,
                "last_tick_trace": state.engine_lab_d.state.last_tick_trace,
            },
        },
        "asset_snapshots": {
            "live": state.engine_live.state.asset_snapshots or {},
            "lab_a": state.engine_lab_a.state.asset_snapshots or {},
            "lab_b": state.engine_lab_b.state.asset_snapshots or {},
            "lab_c": state.engine_lab_c.state.asset_snapshots or {},
            "lab_d": state.engine_lab_d.state.asset_snapshots or {},
        },
        "rule_suggestions": rule_suggestions_from_snapshots(
            state.engine_live.state.asset_snapshots or {},
            state.engine_lab_a.state.asset_snapshots or {},
            state.engine_lab_b.state.asset_snapshots or {},
            state.engine_lab_c.state.asset_snapshots or {},
            state.engine_lab_d.state.asset_snapshots or {},
        ),
        "metrics": {
            "mode": mode_live,
            **metrics_live,
        },
        "metrics_lab_a": metrics_lab_a,
        "metrics_lab_b": metrics_lab_b,
        "metrics_lab_c": metrics_lab_c,
        "metrics_lab_d": metrics_lab_d,
        "equity_snapshots": snaps_live,
        "equity_snapshots_lab_a": snaps_lab_a,
        "equity_snapshots_lab_b": snaps_lab_b,
        "equity_snapshots_lab_c": snaps_lab_c,
        "equity_snapshots_lab_d": snaps_lab_d,
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
        "lab_d_config": lab_d,
        "lab_thoughts": _lab_thought_stream(
            cfg,
            trades,
            lab_a=lab_a if isinstance(lab_a, dict) else {},
            lab_b=lab_b if isinstance(lab_b, dict) else {},
            lab_c=lab_c if isinstance(lab_c, dict) else {},
            lab_d=lab_d if isinstance(lab_d, dict) else {},
            metrics_lab_a=metrics_lab_a,
            metrics_lab_b=metrics_lab_b,
            metrics_lab_c=metrics_lab_c,
            metrics_lab_d=metrics_lab_d,
            lab_a_engine_on=lab_a_engine_on,
            lab_b_engine_on=lab_b_engine_on,
            lab_c_engine_on=lab_c_engine_on,
            lab_d_engine_on=lab_d_engine_on,
        ),
        # OPTIMIZER v0.1 — keep smart core, remove visible settings per user request (no advanced_metrics on dashboard).
        "optimizer_activity": {
            "change_history": ch_slim,
            "runs": runs_slim,
            "pulse_chart_seed": pulse_chart_baseline(cfg, opt_blk),
            "radar": build_optimizer_radar_payload(cfg, opt_blk),
            "pulse_eval_count": int(opt_blk.get("pulse_eval_count") or 0),
            "last_pulse_eval_at": str(opt_blk.get("last_pulse_eval_at") or ""),
            "next_tick_preview": str(opt_blk.get("next_tick_preview") or "")[:900],
            "pulse_trace": [
                {k: p.get(k) for k in ("at", "kind", "message", "change_id")}
                for p in (opt_blk.get("pulse_trace") or [])
                if isinstance(p, dict)
            ][:14],
        },
    }


@app.get("/api/dashboard")
async def dashboard() -> DashboardResponse:
    return await _compose_dashboard_base(with_marks=True)


@app.get("/api/dashboard/equity")
async def dashboard_equity() -> DashboardResponse:
    """
    Same structure as ``/api/dashboard`` but with a 5s cap on the paper mark-refresh pass (vs 50s
    for the full route). ``metrics*`` still get live mids when the gather finishes in time; if not,
    they match snapshot-based values until the next poll or a full ``/api/dashboard`` run.
    """
    return await _compose_dashboard_base(with_marks=False)


@app.get("/api/dashboard/recent_trades")
async def dashboard_recent_trades() -> DashboardRecentTradesResponse:
    """Recent ``signals`` / ``trades`` slices (lighter than a full dashboard round-trip)."""
    trades = await store.recent_trades(limit=500)
    signals = await store.recent_signals(limit=500)
    not_traded = [s for s in signals if not int(s.get("executed") or 0)]
    return {
        "recent_trades": trades[:500],
        "recent_signals": signals[:500],
        "not_traded_signals": not_traded[:200],
    }


@app.get("/api/dashboard/open_positions")
async def dashboard_open_positions() -> DashboardOpenPositionsResponse:
    """
    Account snapshot, Kalshi private positions, and per-branch sim opens used for the Holdings grid.
    """
    cfg = await store.load_config()
    client = require_kalshi()
    portfolio = await fetch_portfolio_snapshot(client)
    kalshi_pos_list = [p for p in (portfolio.get("positions") or []) if isinstance(p, dict)]
    sim_open_live, sim_open_lab_a, sim_open_lab_b, sim_open_lab_c, sim_open_lab_d = await asyncio.gather(
        store.open_sim_trades_for_branch(BRANCH_LIVE),
        store.open_sim_trades_for_branch(BRANCH_LAB_A),
        store.open_sim_trades_for_branch(BRANCH_LAB_B),
        store.open_sim_trades_for_branch(BRANCH_LAB_C),
        store.open_sim_trades_for_branch(BRANCH_LAB_D),
    )
    assets_cfg = cfg.get("assets") if isinstance(cfg.get("assets"), dict) else {}
    position_by_asset = _position_by_asset(
        assets_cfg, kalshi_pos_list, sim_open_live, sim_open_lab_a, sim_open_lab_b, sim_open_lab_c, sim_open_lab_d
    )
    return {
        "account_snapshot": {
            "position_count": int(portfolio.get("position_count") or 0),
            "resting_order_count": int(portfolio.get("resting_order_count") or 0),
            "portfolio_error": portfolio.get("error"),
            "position_by_asset": position_by_asset,
        },
        "remote_balance": portfolio.get("balance"),
    }


@app.get("/api/dashboard/orderbooks")
async def dashboard_orderbooks() -> DashboardOrderbooksResponse:
    """
    Last refreshed paper MTM / mark-derived metrics (cached ~5s from the most recent full dashboard run
    with ``with_marks=True``). Triggers a full mark pass when the cache is stale.
    """
    now = time.monotonic()
    pl = DASHBOARD_ORDERBOOK_CACHE.get("payload")
    t0 = float(DASHBOARD_ORDERBOOK_CACHE.get("t_mono") or 0.0)
    if pl and (now - t0) < DASHBOARD_ORDERBOOK_CACHE_TTL_S:
        return {"cached": True, "cache_age_s": round(now - t0, 3), **pl}
    full = await _compose_dashboard_base(with_marks=True)
    p2 = DASHBOARD_ORDERBOOK_CACHE.get("payload") or {}
    return {"cached": False, **p2, "order_writes_live": (full.get("kalshi") or {}).get("order_writes_live")}


@app.post("/api/engine/toggle")
async def engine_toggle(
    request: Request,
    running: bool | None = Query(None),
    simulate: bool | None = Query(None),
    confirm: str = Query("", description="Required YES when simulate=False (disable Live paper)"),
    sim_lab_running: bool | None = Query(None),
    lab_a_running: bool | None = Query(None),
    lab_b_running: bool | None = Query(None),
    lab_c_running: bool | None = Query(None),
    lab_d_running: bool | None = Query(None),
) -> dict[str, Any]:
    cfg = await store.load_config()
    was_paper = _config_live_paper_flag(cfg)
    if running is not None:
        cfg["engine_running"] = bool(running)
    if simulate is not None:
        v = bool(simulate)
        cfg["live_paper_trading"] = v
        cfg["simulate"] = v
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
    if lab_d_running is not None:
        lab = dict(cfg.get("lab_d") or {})
        lab["engine_running"] = bool(lab_d_running)
        cfg["lab_d"] = lab
    sync_live_paper_trading_keys(cfg)
    if was_paper and not _config_live_paper_flag(cfg):
        if str(confirm).strip().upper() != "YES":
            logger.warning(
                "blocked POST /api/engine/toggle: disabling Live paper without confirm=YES from %s",
                getattr(getattr(request, "client", None), "host", "unknown"),
            )
            raise HTTPException(
                status_code=400,
                detail="Disabling paper trading (simulate=False) requires query confirm=YES.",
            )
        logger.info("POST /api/engine/toggle: Live paper disabled (simulate=False) with confirm=YES")
    paper_off_audit: dict[str, Any] | None = None
    if was_paper and not _config_live_paper_flag(cfg):
        paper_off_audit = _live_paper_disable_audit_meta(
            request,
            confirm_query=confirm,
            query_params={
                k: v
                for k, v in (
                    ("running", running),
                    ("simulate", simulate),
                    ("confirm", confirm),
                    ("sim_lab_running", sim_lab_running),
                    ("lab_a_running", lab_a_running),
                    ("lab_b_running", lab_b_running),
                    ("lab_c_running", lab_c_running),
                    ("lab_d_running", lab_d_running),
                )
                if v is not None
            },
        )
    await store.save_config(
        cfg,
        history_branch="global",
        history_changed_by="api:engine_toggle",
        history_reason="live_paper_trading disabled via POST /api/engine/toggle (confirm=YES)"
        if paper_off_audit
        else None,
        history_audit_meta=paper_off_audit,
    )
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
