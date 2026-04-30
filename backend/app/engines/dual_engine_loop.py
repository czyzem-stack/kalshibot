"""Visible paper / live tick: Live + Lab A–E + child ``lab_child_*`` branches (settle, tick, snapshot, optional auto-optimize).

**Not** the same subsystem as B/C/D/E **child-lab GA** in ``lab_breeding``/``optimizer_claude``—see
``.cursor/rules/architecture-breeding.md``. Charts and Branch performance here reflect per-tick rule matching; breeding
uses replay over history on the optimizer interval.
"""

from __future__ import annotations

import asyncio
from typing import Any
import logging
import time

from .. import state
from ..alert_webhook import post_branch_error_alerts
from ..branch_config import (
    BRANCH_CHILD_LABS,
    BRANCH_LABS,
    BRANCH_LIVE,
    _coerce_engine_running_flag,
    effective_live_engine_running,
    effective_parent_lab_engine_running,
    live_paper_trading_enabled,
)
from ..kalshi_client import KalshiClient
from ..optimizer import maybe_auto_optimize
from ..persistence import _data_log
from .engine import (
    TradingEngine,
    iso,
    maybe_swing_exit_open_sim_trades,
    maybe_timeout_close_open_sim_trades,
    settle_simulated_trades,
    snapshot_equity,
    tick_once,
    utc_now,
)
from ..settings_env import env

logger = logging.getLogger("kalshibot.dual_engine")


def _lab_branch_tick_enabled(br: str, lc: dict[str, Any]) -> bool:
    """
    Must match :func:`merge_branch_config` / :func:`tick_once` — the old ``bool(…)`` on ``engine_running`` treated
    string ``"false"`` and other non-bool values as *on*, so the dual loop could call ``tick_once`` (no merged config)
    and still run ``snapshot_equity``, producing a flat or misleading equity curve.
    """
    if br in BRANCH_CHILD_LABS:
        if not isinstance(lc, dict):
            return True
        return _coerce_engine_running_flag(lc.get("engine_running"), default_if_missing=True)
    if not isinstance(lc, dict):
        return False
    return effective_parent_lab_engine_running(lc, br)


async def dual_engine_loop(engines: dict[str, TradingEngine], stop_event: asyncio.Event) -> None:
    # PHASE 2: never run a tick until lifespan finished pre-warm + WS subscription list seed (see main._app_lifespan).
    await state.startup_complete.wait()
    tick = 0
    prev_engine_alert: dict[str, str | None] = {}
    _last_tick_log_mono: float = 0.0
    while not stop_event.is_set():
        _tick_t0 = time.perf_counter()
        eng_live = engines[BRANCH_LIVE]
        full_cfg = await eng_live.store.load_config()
        cfg = full_cfg
        try:
            # PHASE FINAL: env-backed poll default preserves prior 8s behavior when config omits poll_seconds.
            poll_candidates: list[float] = [float(cfg.get("poll_seconds") or env.default_poll_seconds)]
            branch_order = [BRANCH_LIVE, *BRANCH_LABS, *BRANCH_CHILD_LABS]
            lab_conf: dict[str, dict[str, Any]] = {}
            for br in (*BRANCH_LABS, *BRANCH_CHILD_LABS):
                raw = cfg.get(br) if isinstance(cfg.get(br), dict) else {}
                lab_conf[br] = raw if isinstance(raw, dict) else {}
            for bk, bcfg in lab_conf.items():
                if isinstance(bcfg, dict):
                    poll_candidates.append(float(bcfg.get("poll_seconds") or poll_candidates[0]))
            poll = max(poll_candidates)

            # PHASE 2: settle / swing / timeout per branch in parallel (same error handling as sequential).
            async def _branch_settle_cycle(br: str) -> tuple[str, int, int, int]:
                eng = engines.get(br)
                if not eng:
                    return br, 0, 0, 0
                try:
                    ns = await settle_simulated_trades(eng, full_cfg=full_cfg)
                    nw = await maybe_swing_exit_open_sim_trades(eng, cfg)
                    nt = await maybe_timeout_close_open_sim_trades(eng, full_cfg=full_cfg)
                    return br, ns, nw, nt
                except Exception as e:
                    err = str(e)
                    _data_log(
                        "system",
                        {"event": "dual_engine_settle_swing_error", "branch": br, "error": err[:800], "at": iso(utc_now())},
                    )
                    eng.state.last_error = err[:500]
                    return br, 0, 0, 0

            # ``return_exceptions=True`` — per-branch errors already set ``eng.state.last_error`` in ``_branch_settle_cycle``.
            await asyncio.gather(*[_branch_settle_cycle(br) for br in branch_order], return_exceptions=True)

            if effective_live_engine_running(cfg):
                el = engines[BRANCH_LIVE]
                try:
                    await tick_once(el, full_cfg=full_cfg)
                except Exception as e:
                    err = str(e)
                    _data_log(
                        "system",
                        {"event": "dual_engine_tick_error", "branch": BRANCH_LIVE, "error": err[:800], "at": iso(utc_now())},
                    )
                    el.state.last_error = err[:500]
            # When Live is off, labs used to tick with zero spacing → three parallel-ish series scans + order books
            # in one loop turn, which spikes Kalshi public limits (HTTP 429) and looks like "labs never trade".
            lab_stagger_armed = False
            for br in (*BRANCH_LABS, *BRANCH_CHILD_LABS):
                lc = lab_conf[br] if isinstance(lab_conf.get(br), dict) else {}
                if _lab_branch_tick_enabled(br, lc):
                    # Per-lab fraction nudger when auto_optimize is on — disabled while scheduled optimizer runs.
                    oc0 = cfg.get("optimizer") if isinstance(cfg.get("optimizer"), dict) else {}
                    if tick % 25 == 0 and bool(lc.get("auto_optimize")) and not bool(oc0.get("enabled")):
                        try:
                            await maybe_auto_optimize(eng_live.store, br)
                        except Exception as e:
                            err = str(e)
                            _data_log(
                                "system",
                                {
                                    "event": "dual_engine_auto_optimize_error",
                                    "branch": br,
                                    "error": err[:800],
                                    "at": iso(utc_now()),
                                },
                            )
                            eng_lab = engines.get(br)
                            if eng_lab:
                                eng_lab.state.last_error = err[:500]
                    if lab_stagger_armed:
                        await asyncio.sleep(env.dual_engine_lab_tick_stagger_s)
                    eng_tick = engines.get(br)
                    if eng_tick:
                        try:
                            await tick_once(eng_tick, full_cfg=full_cfg)
                        except Exception as e:
                            err = str(e)
                            _data_log(
                                "system",
                                {
                                    "event": "dual_engine_tick_error",
                                    "branch": br,
                                    "error": err[:800],
                                    "at": iso(utc_now()),
                                },
                            )
                            eng_tick.state.last_error = err[:500]
                    lab_stagger_armed = True

            tick += 1
            snap_period = tick % 5 == 0
            simulate_live = live_paper_trading_enabled(cfg)
            # Live paper: snapshot **every** loop (same as labs) so the equity/MTM chart is not 5× visually stale
            # vs Lab A–D in quiet markets. (Previously gated on every 5th tick or Live settle/swing — looked "frozen".)
            # Live **real** money: still throttle balance/portfolio fetches to every 5 ticks while the engine is on.
            if simulate_live:
                try:
                    await snapshot_equity(eng_live, full_cfg=full_cfg)
                except Exception as e:
                    err = str(e)
                    _data_log(
                        "system",
                        {
                            "event": "dual_engine_snapshot_error",
                            "branch": BRANCH_LIVE,
                            "error": err[:800],
                            "at": iso(utc_now()),
                        },
                    )
                    eng_live.state.last_error = err[:500]
            elif snap_period and effective_live_engine_running(cfg):
                try:
                    await snapshot_equity(eng_live, full_cfg=full_cfg)
                except Exception as e:
                    err = str(e)
                    _data_log(
                        "system",
                        {
                            "event": "dual_engine_snapshot_error",
                            "branch": BRANCH_LIVE,
                            "error": err[:800],
                            "at": iso(utc_now()),
                        },
                    )
                    eng_live.state.last_error = err[:500]

            # Paper lab charts: write one equity row per engine loop while the lab is on (same cadence for A/B/C/D).
            # Previously gated on ``tick % 5`` + settle/swing, so quiet labs (e.g. fewer settlements) updated charts
            # ~5× slower than busy labs despite identical poll rates.
            lab_snap_items: list[tuple[str, Any]] = []
            for br in (*BRANCH_LABS, *BRANCH_CHILD_LABS):
                lc = lab_conf[br] if isinstance(lab_conf.get(br), dict) else {}
                if _lab_branch_tick_enabled(br, lc):
                    eng = engines.get(br)
                    if eng:
                        lab_snap_items.append((br, snapshot_equity(eng, full_cfg=full_cfg)))
            if lab_snap_items:
                results = await asyncio.gather(*[t for _, t in lab_snap_items], return_exceptions=True)
                for (br, _), res in zip(lab_snap_items, results):
                    if isinstance(res, BaseException):
                        err = str(res)
                        _data_log(
                            "system",
                            {
                                "event": "dual_engine_snapshot_error",
                                "branch": br,
                                "error": err[:800],
                                "at": iso(utc_now()),
                            },
                        )
                        eng_snap = engines.get(br)
                        if eng_snap:
                            eng_snap.state.last_error = err[:500]
            # Parent labs (A–E) with engine **off**: still append equity snapshots each loop — same policy as Live paper
            # above (``simulate_live`` snapshots without requiring ``tick_once``). Previously Lab A skipped SQLite rows
            # entirely when toggled off, so equity curves looked empty vs Live or vs trade toasts for other branches.
            for br in BRANCH_LABS:
                lc = lab_conf[br] if isinstance(lab_conf.get(br), dict) else {}
                if _lab_branch_tick_enabled(br, lc):
                    continue
                eng_off = engines.get(br)
                if not eng_off:
                    continue
                try:
                    await snapshot_equity(eng_off, full_cfg=full_cfg)
                except Exception as e:
                    err = str(e)
                    _data_log(
                        "system",
                        {
                            "event": "dual_engine_snapshot_error",
                            "branch": br,
                            "error": err[:800],
                            "at": iso(utc_now()),
                        },
                    )
                    eng_off.state.last_error = err[:500]
            try:
                await post_branch_error_alerts(engines, prev_errors=prev_engine_alert)
            except Exception:
                pass
            # PHASE 2: periodic tick wall-clock log (off when KALSHI_LOG_TICK_INTERVAL_S=0).
            _ival = float(env.kalshi_log_tick_interval_s or 0.0)
            if _ival > 0:
                _now = time.monotonic()
                if _now - _last_tick_log_mono >= _ival:
                    _last_tick_log_mono = _now
                    _h = KalshiClient.orderbook_cache_hits
                    _m = KalshiClient.orderbook_cache_misses
                    _tot = _h + _m
                    _hr = (100.0 * _h / _tot) if _tot else 0.0
                    logger.info(
                        "dual_engine_tick_ms=%.1f tick=%s ws_connected=%s ws_ob_writes=%s ob_cache_hit_pct=%.1f",
                        (time.perf_counter() - _tick_t0) * 1000.0,
                        tick,
                        KalshiClient.ws_connected,
                        KalshiClient.ws_orderbook_cache_writes,
                        _hr,
                    )
        except Exception as e:
            err = str(e)
            _data_log(
                "system",
                {"event": "dual_engine_loop_error", "error": err[:800], "at": iso(utc_now())},
            )
            el = engines.get(BRANCH_LIVE)
            if el:
                el.state.last_error = err[:500]
            try:
                await post_branch_error_alerts(engines, prev_errors=prev_engine_alert)
            except Exception:
                pass

        # Reuse config loaded at loop start — avoids a second SQLite read every poll interval.
        poll_live = float(full_cfg.get("poll_seconds") or env.default_poll_seconds)
        poll_candidates_end: list[float] = [poll_live]
        for lk in (*BRANCH_LABS, *BRANCH_CHILD_LABS):
            blk = full_cfg.get(lk) if isinstance(full_cfg.get(lk), dict) else {}
            poll_candidates_end.append(float((blk or {}).get("poll_seconds") or poll_live))
        poll = max(poll_candidates_end)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll)
        except TimeoutError:
            pass


__all__ = ["dual_engine_loop"]
