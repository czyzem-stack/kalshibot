"""Five-branch polling loop: Live + Labs A–D (settle, tick, snapshot, optional auto-optimize)."""

from __future__ import annotations

import asyncio
from typing import Any

from ..alert_webhook import post_branch_error_alerts
from ..branch_config import (
    BRANCH_LAB_A,
    BRANCH_LAB_B,
    BRANCH_LAB_C,
    BRANCH_LAB_D,
    BRANCH_LIVE,
    live_paper_trading_enabled,
)
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


async def dual_engine_loop(engines: dict[str, TradingEngine], stop_event: Any) -> None:
    tick = 0
    prev_engine_alert: dict[str, str | None] = {}
    while not stop_event.is_set():
        eng_live = engines[BRANCH_LIVE]
        full_cfg = await eng_live.store.load_config()
        cfg = full_cfg
        try:
            poll_candidates: list[float] = [float(cfg.get("poll_seconds") or 8)]
            branch_order = [BRANCH_LIVE, BRANCH_LAB_A, BRANCH_LAB_B, BRANCH_LAB_C, BRANCH_LAB_D]
            lab_conf = {
                BRANCH_LAB_A: cfg.get("lab_a") if isinstance(cfg.get("lab_a"), dict) else {},
                BRANCH_LAB_B: cfg.get("lab_b") if isinstance(cfg.get("lab_b"), dict) else {},
                BRANCH_LAB_C: cfg.get("lab_c") if isinstance(cfg.get("lab_c"), dict) else {},
                BRANCH_LAB_D: cfg.get("lab_d") if isinstance(cfg.get("lab_d"), dict) else {},
            }
            for bk, bcfg in lab_conf.items():
                if isinstance(bcfg, dict):
                    poll_candidates.append(float(bcfg.get("poll_seconds") or poll_candidates[0]))
            poll = max(poll_candidates)

            n_settled: dict[str, int] = {}
            n_swing: dict[str, int] = {}
            n_timeout: dict[str, int] = {}
            for br in branch_order:
                eng = engines.get(br)
                if not eng:
                    continue
                try:
                    n_settled[br] = await settle_simulated_trades(eng, full_cfg=full_cfg)
                    n_swing[br] = await maybe_swing_exit_open_sim_trades(eng, cfg)
                    n_timeout[br] = await maybe_timeout_close_open_sim_trades(eng, full_cfg=full_cfg)
                except Exception as e:
                    err = str(e)
                    _data_log(
                        "system",
                        {"event": "dual_engine_settle_swing_error", "branch": br, "error": err[:800], "at": iso(utc_now())},
                    )
                    eng.state.last_error = err[:500]

            if cfg.get("engine_running"):
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
            for br in (BRANCH_LAB_A, BRANCH_LAB_B, BRANCH_LAB_C, BRANCH_LAB_D):
                lc = lab_conf[br] if isinstance(lab_conf.get(br), dict) else {}
                if lc.get("engine_running"):
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
                        await asyncio.sleep(0.45)
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
            # Paper equity is derived from SQLite only — snapshot often so the chart matches settled/open counts.
            # Live real mode still snapshots only every 5 ticks while the engine runs (balance API).
            if simulate_live:
                if (
                    snap_period
                    or n_settled.get(BRANCH_LIVE, 0) > 0
                    or n_swing.get(BRANCH_LIVE, 0) > 0
                    or n_timeout.get(BRANCH_LIVE, 0) > 0
                ):
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
            elif snap_period and cfg.get("engine_running"):
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
            for br in (BRANCH_LAB_A, BRANCH_LAB_B, BRANCH_LAB_C, BRANCH_LAB_D):
                lc = lab_conf[br] if isinstance(lab_conf.get(br), dict) else {}
                if lc.get("engine_running"):
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
            try:
                await post_branch_error_alerts(engines, prev_errors=prev_engine_alert)
            except Exception:
                pass
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
        poll_live = float(full_cfg.get("poll_seconds") or 8)
        poll_lab_a = float(((full_cfg.get("lab_a") or {}) if isinstance(full_cfg.get("lab_a"), dict) else {}).get("poll_seconds") or poll_live)
        poll_lab_b = float(((full_cfg.get("lab_b") or {}) if isinstance(full_cfg.get("lab_b"), dict) else {}).get("poll_seconds") or poll_live)
        poll_lab_c = float(((full_cfg.get("lab_c") or {}) if isinstance(full_cfg.get("lab_c"), dict) else {}).get("poll_seconds") or poll_live)
        poll_lab_d = float(((full_cfg.get("lab_d") or {}) if isinstance(full_cfg.get("lab_d"), dict) else {}).get("poll_seconds") or poll_live)
        poll = max(poll_live, poll_lab_a, poll_lab_b, poll_lab_c, poll_lab_d)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll)
        except TimeoutError:
            pass


__all__ = ["dual_engine_loop"]
