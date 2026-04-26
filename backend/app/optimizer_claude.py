from __future__ import annotations

import datetime as dt
import json
import logging
import random
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from .api_models import normalize_rules_list
from .branch_config import (
    BRANCH_LAB_A,
    BRANCH_LAB_B,
    BRANCH_LAB_C,
    BRANCH_LAB_D,
    MAX_BALANCE_FRACTION_PER_WINDOW,
    MIN_BALANCE_FRACTION_PER_WINDOW,
    _lab_key_for_branch,
    clamp_balance_fraction_per_window,
    enable_patient_stop_loss_from_cfg,
    min_hold_minutes_before_stop_from_cfg,
    stop_loss_trigger_pct_from_cfg,
)
from .engine import _calculate_net_unrealized_pct_after_fees, rule_matches
from .optimizer.fitness import composite_fitness_score, is_statistically_better
from .optimizer.weighted_edge import calculate_weighted_edge, synthetic_orderbook_for_replay
from .optimizer.schemas import ClaudeOptimizerResponse, parse_claude_optimizer_json
from .settings_env import env

if TYPE_CHECKING:
    from .persistence import Store

logger = logging.getLogger("kalshibot.optimizer")

# After Claude rule deltas, reject if list grows beyond this (API ``normalize_rules_list`` allows up to 48).
MAX_LAB_A_RULES_AFTER_CLAUDE_DELTAS = 30


def _utc_now() -> dt.datetime:
    return dt.datetime.now(tz=dt.timezone.utc)


def _iso(v: dt.datetime) -> str:
    return v.astimezone(dt.timezone.utc).isoformat()


def _opt_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    o = cfg.get("optimizer")
    return dict(o) if isinstance(o, dict) else {}


def _norm_opt_cfg(oc: dict[str, Any]) -> dict[str, Any]:
    out = dict(oc or {})
    out.pop("max_bet_fraction", None)
    out.setdefault("enabled", False)
    out.setdefault("interval_minutes", 20)
    out.setdefault("lookback_hours", 48)
    out.setdefault("max_rows_per_table", 5000)
    out.setdefault("model", "internal")
    out.setdefault("adaptive_enabled", True)
    out.setdefault("mode", "duel")  # duel | independent
    out.setdefault("lab_a_enabled", True)
    out.setdefault("lab_b_enabled", True)
    out.setdefault("lab_c_enabled", True)
    out.setdefault("lab_d_enabled", True)
    out.setdefault("lab_a_style", "blend")
    out.setdefault("lab_b_style", "conservative")
    out.setdefault("lab_c_style", "aggressive")
    out.setdefault("lab_d_style", "wild")
    out.setdefault("loss_streak_trigger", 1)
    out.setdefault("threshold_step_pct", 2)
    out.setdefault("minute_step", 2)
    out.setdefault("max_history", 120)
    out.setdefault("lab_a_yes_floor_pct", 57)
    out.setdefault("lab_b_yes_floor_pct", 55)
    out.setdefault("lab_a_min_minutes_left", 5)
    out.setdefault("lab_b_min_minutes_left", 3)
    out.setdefault("min_trades_for_optimize", 8)
    out.setdefault("min_profitable_trades", 2)
    out.setdefault("optimize_bet_size", True)
    out.setdefault("include_fees_in_score", True)
    out.setdefault("regime_lookback_hours", 4)
    out.setdefault("backtest_proposals", True)
    out.setdefault("change_history", [])
    out.setdefault("pulse_trace", [])
    out.setdefault("next_tick_preview", "")
    out.setdefault("pulse_eval_count", 0)
    out.setdefault("last_pulse_eval_at", "")
    out.setdefault("optimize_internal_mutations", True)
    out.setdefault("mutation_aggressiveness", 0.75)
    out.setdefault("enable_auto_revert", True)
    out.setdefault("optimizer_auto_revert_last_at", "")
    out.setdefault("optimizer_last_auto_revert_fitness", 0.0)
    out.setdefault("optimizer_last_auto_revert_history_id", 0)
    out.setdefault("optimizer_cycle_count", 0)
    out.setdefault("internal_optimizer_trace", [])
    out.setdefault("last_mutation_at", "")
    out.setdefault("best_fitness_score_7d", 0.0)
    out.setdefault("enable_regime_rules", True)
    out.setdefault("radical_exploration_enabled", True)
    out.setdefault("optimizer_consecutive_low_acceptance_cycles", 0)
    out.setdefault("enable_paper_loser_detection", True)
    out.setdefault("paper_loser_cycles_threshold", 4)
    out.setdefault("paper_winner_fitness_min", 0.0)  # replay score_dollars must exceed this
    out.setdefault("paper_loser_neg_equity_trace_min", 5)  # consecutive neg $/h rows in internal trace
    out.setdefault("paper_loser_stop_rate_pct", 45.0)
    out.setdefault("regime_paper_loser_pin_hours", 4.0)
    out.setdefault("optimizer_consecutive_paper_loser_cycles", 0)
    out.setdefault("regime_paper_loser_pinned", "")
    out.setdefault("regime_paper_loser_pinned_until", "")
    out.setdefault("paper_loser_radical_next", False)
    out.setdefault("last_paper_loser_swap_at", "")
    # Regime-level EWMA of composite ``score_dollars`` and observation counts; decayed every optimizer tick
    # so older telemetry fades (meta-learning, no user tuning).
    out.setdefault(
        "regime_performance_meta",
        {
            "high_vol": {"ewma_fitness": 0.0, "observations": 0},
            "low_vol": {"ewma_fitness": 0.0, "observations": 0},
            "event_risk": {"ewma_fitness": 0.0, "observations": 0},
        },
    )
    out.setdefault("regime_ewma_decay_per_cycle", 0.996)
    out.setdefault("regime_ewma_alpha", 0.12)
    out.setdefault("regime_negative_fitness_streaks", {"high_vol": 0, "low_vol": 0, "event_risk": 0})
    out.setdefault("prune_streak_regime_min_cycles", 30)
    # Counters for the 24-optimizer-cycle automatic threshold tuner (all backend-only; no API/UI)
    out.setdefault("last_autotune_at_optimizer_cycle", 0)
    out.setdefault("autotune_window_paper_loser_swaps", 0)
    out.setdefault("autotune_window_paper_loser_risk_events", 0)
    out.setdefault("mutation_aggressiveness_autotune_baseline", None)  # if None, use mutation_aggressiveness
    # Patient stop-loss is modeled on each ``lab_*`` / Live trading dict (``enable_patient_stop_loss``,
    # ``stop_loss_trigger_pct``, ``min_hold_minutes_before_stop``). ``replay_under_rules_detail`` accepts
    # ``branch_trading_cfg`` to clamp replay PnL vs. those stops when evaluating fitness.
    return out


def _safe_float(v: Any, d: float) -> float:
    try:
        x = float(v)
        if x != x:  # NaN
            return d
        return x
    except Exception:
        return d


def _safe_int(v: Any, d: int) -> int:
    try:
        return int(v)
    except Exception:
        return d


def _branch_style(oc: dict[str, Any], branch: str) -> str:
    mode = str(oc.get("mode") or "duel").strip().lower()
    if mode == "duel":
        if branch == BRANCH_LAB_B:
            return "conservative"
        if branch == BRANCH_LAB_C:
            return "aggressive"
        if branch == BRANCH_LAB_D:
            return "wild"
        return "blend"
    if branch == BRANCH_LAB_A:
        return str(oc.get("lab_a_style") or "blend").strip().lower()
    if branch == BRANCH_LAB_B:
        return str(oc.get("lab_b_style") or "conservative").strip().lower()
    if branch == BRANCH_LAB_C:
        return str(oc.get("lab_c_style") or "aggressive").strip().lower()
    return str(oc.get("lab_d_style") or "wild").strip().lower()


def _index_signals_by_ticker(signals: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for s in signals:
        t = str(s.get("ticker") or "").strip()
        if not t:
            continue
        out[t] = s
    return out


def _parse_iso_dt(raw: Any) -> dt.datetime | None:
    if not raw:
        return None
    try:
        return dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except Exception:
        return None


def _signals_sorted_desc(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(signals, key=lambda s: int(s.get("id") or 0), reverse=True)


def _entry_prob_mins_for_trade(
    t: dict[str, Any], signals_desc: list[dict[str, Any]]
) -> tuple[float | None, float | None]:
    ex: dict[str, Any] = {}
    try:
        ex = json.loads(str(t.get("extra_json") or "{}"))
    except Exception:
        ex = {}
    prob: float | None = None
    if ex.get("entry_implied_yes") is not None:
        prob = _safe_float(ex.get("entry_implied_yes"), -1.0)
        if prob < 0:
            prob = None
    tick = str(t.get("ticker") or "")
    t_created = str(t.get("created_at") or "")
    mins_m: float | None = None
    for s in signals_desc:
        if str(s.get("ticker") or "") != tick:
            continue
        sc = str(s.get("created_at") or "")
        if sc and t_created and sc > t_created:
            continue
        if prob is None and s.get("implied_prob") is not None:
            prob = _safe_float(s.get("implied_prob"), -1.0)
            if prob < 0:
                prob = None
        if s.get("minutes_left") is not None:
            mins_m = _safe_float(s.get("minutes_left"), -1.0)
            if mins_m < 0:
                mins_m = None
        break
    return prob, mins_m


def _replay_pnl_under_rules(
    settled: list[dict[str, Any]],
    rules: list[dict[str, Any]],
    signals_desc: list[dict[str, Any]],
    *,
    include_fees_in_score: bool,
    branch_trading_cfg: dict[str, Any] | None = None,
) -> tuple[int, int, int]:
    """
    Replay: sum settled PnL for trades whose entry (implied YES, minutes) would match at least one rule.
    Returns (total_pnl_cents, n_matched, n_considered).
    """
    d = replay_under_rules_detail(
        settled[:200],
        rules,
        signals_desc,
        include_fees_in_score=include_fees_in_score,
        max_considered=200,
        branch_trading_cfg=branch_trading_cfg,
    )
    return int(d["total_pnl_cents"]), int(d["matched_n"]), int(d["considered_n"])


def _trade_sort_key(t: dict[str, Any]) -> tuple[int, float, int]:
    """
    Stable chronological order for replay.

    Uses the same row shape as ``Store.query_table`` trades (``id``, ``created_at`` ISO, ``pnl_cents``,
    ``extra_json``, ``status``) for both simulate and live branches. When ``created_at`` is missing,
    ``id`` is used as a monotonic proxy so ordering stays deterministic.
    """
    ca = _parse_iso_dt(t.get("created_at"))
    tid = int(t.get("id") or 0)
    if ca is not None:
        return (0, ca.timestamp(), tid)
    return (1, float(tid), tid)


def replay_under_rules_detail(
    settled: list[dict[str, Any]],
    rules: list[dict[str, Any]],
    signals_desc: list[dict[str, Any]],
    *,
    include_fees_in_score: bool,
    max_considered: int = 500,
    branch_trading_cfg: dict[str, Any] | None = None,
    open_positions: list[dict[str, Any]] | None = None,
    full_cfg: dict[str, Any] | None = None,
    branch: str = BRANCH_LAB_A,
    replay_end_time: dt.datetime | None = None,
) -> dict[str, Any]:
    """
    Replay over the first ``max_considered`` rows of ``settled`` (caller passes query order: typically
    newest-first), then **sorted oldest-first** for cumulative PnL / drawdown. Matched-trade totals are
    order-independent; ordering only affects the equity path inside this window.

    When a row matches, realized PnL (after optional fee deduction, patient stop clamp) is rescaled
    with the same **liquidity-aware** idea as the live sim ranker: ``calculate_weighted_edge`` plus
    spread width, so wide books don’t get full credit in fitness.
    """
    from .engine import dollars_to_float

    def _scale_pnl_cents(m_rule: dict[str, Any] | None, trow: dict[str, Any], prob0: float, pnl0: int) -> int:
        if m_rule is None:
            return pnl0
        synth = synthetic_orderbook_for_replay(prob0, trow)
        we = float(calculate_weighted_edge(synth, m_rule))
        yb = dollars_to_float(synth.get("yes_bid_dollars"))
        ya = dollars_to_float(synth.get("yes_ask_dollars"))
        if yb is not None and ya is not None and float(ya) >= float(yb):
            sw = min(0.5, max(0.0, float(ya) - float(yb)))
        else:
            sw = 0.02
        liq = max(0.15, 1.0 - sw * 0.8)
        wboost = 1.0 + 0.12 * (we if we > 0.0 else 0.0)
        wboost = max(0.45, min(1.4, wboost))
        return int(round(float(pnl0) * liq * wboost))

    clean_rules = [dict(r) for r in rules if isinstance(r, dict)]
    pool = sorted(settled[:max_considered], key=_trade_sort_key)
    total = 0
    matched = 0
    considered = 0
    per_trade: list[int] = []
    cumulative: list[int] = [0]
    cur = 0
    total_pnl_from_stops_cents = 0
    n_stop_hits = 0
    n_open_sim_stops = 0
    for t in pool:
        considered += 1
        prob, mins = _entry_prob_mins_for_trade(t, signals_desc)
        if prob is None or mins is None:
            continue
        m_first = next((r for r in clean_rules if rule_matches(prob, mins, r)), None)
        if m_first is None:
            continue
        pnl = int(t.get("pnl_cents") or 0)
        ex: dict[str, Any] = {}
        try:
            ex = json.loads(str(t.get("extra_json") or "{}"))
        except Exception:
            ex = {}
        if include_fees_in_score:
            fees = int(ex.get("entry_fee_cents") or 0) + int(ex.get("settlement_exit_fee_cents") or 0)
            pnl -= fees
        if branch_trading_cfg is not None and enable_patient_stop_loss_from_cfg(branch_trading_cfg):
            thr = float(stop_loss_trigger_pct_from_cfg(branch_trading_cfg))
            min_hold = int(min_hold_minutes_before_stop_from_cfg(branch_trading_cfg))
            entry_prem = int(ex.get("entry_premium_cents") or 0)
            if entry_prem <= 0:
                ac = int(t.get("amount_cents") or 0)
                entry_prem = max(0, ac - int(ex.get("entry_fee_cents") or 0))
            ca_o = _parse_iso_dt(t.get("created_at"))
            ca_s = _parse_iso_dt(t.get("settled_at"))
            if entry_prem > 0 and ca_o is not None and ca_s is not None and thr < 0:
                held_m = (ca_s - ca_o).total_seconds() / 60.0
                if held_m >= float(min_hold):
                    stop_cents = int(round(float(entry_prem) * thr / 100.0))
                    if pnl < stop_cents:
                        pnl = max(pnl, stop_cents)
        is_stop_exit = bool(ex.get("patient_stop_loss")) or str(t.get("result") or "").lower() == "patient_stop_loss"
        pnl = _scale_pnl_cents(m_first, t, float(prob), pnl)
        if is_stop_exit:
            n_stop_hits += 1
            total_pnl_from_stops_cents += pnl
        total += pnl
        matched += 1
        per_trade.append(pnl)
        cur += pnl
        cumulative.append(cur)
    # Simulate future patient stop-loss on open positions (mark-to-exit PnL% vs threshold, like the live handler).
    if (
        open_positions
        and full_cfg is not None
        and branch_trading_cfg is not None
        and enable_patient_stop_loss_from_cfg(branch_trading_cfg)
        and replay_end_time is not None
    ):
        thr_p = float(stop_loss_trigger_pct_from_cfg(branch_trading_cfg))
        min_hold_p = int(min_hold_minutes_before_stop_from_cfg(branch_trading_cfg))
        for pos in open_positions:
            if int(pos.get("simulated") or 0) != 1:
                continue
            prob_o, mins_o = _entry_prob_mins_for_trade(pos, signals_desc)
            if prob_o is None or mins_o is None:
                continue
            m_op = next((r for r in clean_rules if rule_matches(prob_o, mins_o, r)), None)
            if m_op is None:
                continue
            ca0 = _parse_iso_dt(pos.get("created_at"))
            if ca0 is None:
                continue
            held_m = (replay_end_time - ca0).total_seconds() / 60.0
            if held_m < float(min_hold_p):
                continue
            net_pct = _calculate_net_unrealized_pct_after_fees(
                pos, float(prob_o), full_cfg=full_cfg, branch=branch
            )
            if not (net_pct <= thr_p):
                continue
            cost = int(pos.get("amount_cents") or 0)
            if cost <= 0:
                continue
            pnl = int(round(float(cost) * (float(net_pct) / 100.0)))
            pnl = _scale_pnl_cents(m_op, pos, float(prob_o), pnl)
            total += pnl
            n_stop_hits += 1
            n_open_sim_stops += 1
            total_pnl_from_stops_cents += pnl
            per_trade.append(pnl)
            cur += pnl
            cumulative.append(cur)
    n_per = len(per_trade)
    stop_loss_trigger_rate = (100.0 * float(n_stop_hits) / float(max(1, n_per))) if n_per else 0.0
    return {
        "total_pnl_cents": total,
        "matched_n": matched,
        "considered_n": considered,
        "per_trade_pnl_cents_chrono": per_trade,
        "cumulative_equity_cents": cumulative,
        "total_pnl_from_stops_cents": int(total_pnl_from_stops_cents),
        "stop_loss_trigger_rate": float(stop_loss_trigger_rate),
        "stop_loss_exits_n": int(n_stop_hits),
        "open_simulated_stop_exits_n": int(n_open_sim_stops),
    }


def _replay_fitness_bundle(
    settled: list[dict[str, Any]],
    rules: list[dict[str, Any]],
    signals_desc: list[dict[str, Any]],
    *,
    include_fees_in_score: bool,
    max_rows: int = 200,
    branch_trading_cfg: dict[str, Any] | None = None,
    open_positions: list[dict[str, Any]] | None = None,
    full_cfg: dict[str, Any] | None = None,
    branch: str = BRANCH_LAB_A,
    replay_end_time: dt.datetime | None = None,
) -> dict[str, Any]:
    """Replay plus composite fitness (drawdown / vol / Sharpe blend)."""
    d = replay_under_rules_detail(
        settled[:max_rows],
        rules,
        signals_desc,
        include_fees_in_score=include_fees_in_score,
        max_considered=max_rows,
        branch_trading_cfg=branch_trading_cfg,
        open_positions=open_positions,
        full_cfg=full_cfg,
        branch=branch,
        replay_end_time=replay_end_time,
    )
    fit = composite_fitness_score(
        total_pnl_cents=int(d["total_pnl_cents"]),
        cumulative_equity_cents=d["cumulative_equity_cents"],
        per_trade_pnl_cents=d["per_trade_pnl_cents_chrono"],
    )
    return {**d, **fit}


def _open_sim_rows(trades: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not trades:
        return []
    return [t for t in trades if str(t.get("status") or "").lower() in ("open", "resting")]


def _replay_open_kw(
    cfg: dict[str, Any], *, at_iso: str, branch: str, trades: list[dict[str, Any]] | None
) -> dict[str, Any]:
    op = _open_sim_rows(trades)
    return {
        "open_positions": op or None,
        "full_cfg": cfg,
        "branch": branch,
        "replay_end_time": _parse_iso_dt(at_iso) or _utc_now(),
    }


def _per_rule_stats_48h(
    settled: list[dict[str, Any]], *, end: dt.datetime
) -> dict[str, Any]:
    cutoff = end - dt.timedelta(hours=48)
    buckets: dict[str, dict[str, Any]] = {}
    for t in settled:
        ca = _parse_iso_dt(t.get("created_at"))
        if ca is None or ca < cutoff:
            continue
        ex: dict[str, Any] = {}
        try:
            ex = json.loads(str(t.get("extra_json") or "{}"))
        except Exception:
            ex = {}
        name = str(ex.get("rule") or "unknown")
        pnl = int(t.get("pnl_cents") or 0)
        b = buckets.setdefault(name, {"n": 0, "wins": 0, "pnl_cents": 0})
        b["n"] += 1
        b["pnl_cents"] += pnl
        if pnl > 0:
            b["wins"] += 1
    out: dict[str, Any] = {}
    for k, v in buckets.items():
        n = int(v["n"] or 0)
        wins = int(v["wins"] or 0)
        out[k] = {
            "trades": n,
            "win_rate": (wins / n) if n else 0.0,
            "avg_pnl_cents": (int(v["pnl_cents"] or 0) / n) if n else 0.0,
        }
    return out


def _equity_slope_dollars_per_hour(snaps: list[dict[str, Any]]) -> float | None:
    if len(snaps) < 3:
        return None
    pts: list[tuple[dt.datetime, float]] = []
    for s in snaps[-120:]:
        ts = _parse_iso_dt(s.get("created_at"))
        if ts is None:
            continue
        try:
            eq = int(s.get("equity_cents") or 0) / 100.0
        except (TypeError, ValueError):
            continue
        pts.append((ts, eq))
    if len(pts) < 3:
        return None
    t0, e0 = pts[0]
    t1, e1 = pts[-1]
    hours = max(1e-6, (t1 - t0).total_seconds() / 3600.0)
    return (e1 - e0) / hours


def _fitness_score_trend_from_trace(trace_rows: list[dict[str, Any]], *, max_rows: int = 20) -> float | None:
    """
    Approximate score slope per cycle from the most recent trace entries.

    Positive means improving recent composite fitness; negative means deterioration.
    """
    vals: list[float] = []
    rows = trace_rows[: max(2, max_rows)]
    for row in reversed(rows):
        try:
            v = float(row.get("score") if row.get("score") is not None else row.get("score_after"))
        except (TypeError, ValueError):
            continue
        if v == v:
            vals.append(v)
    if len(vals) < 2:
        return None
    return (vals[-1] - vals[0]) / float(max(1, len(vals) - 1))


def _append_internal_trace(oc: dict[str, Any], entry: dict[str, Any]) -> None:
    """Keep the internal optimizer trace bounded (newest first)."""
    rows = oc.get("internal_optimizer_trace")
    prev = rows if isinstance(rows, list) else []
    out = [entry, *prev][:20]
    oc["internal_optimizer_trace"] = out


def _trace_positive_equity_slope_streak(oc: dict[str, Any]) -> int:
    """Count consecutive trace rows (newest first) with equity_slope_dph > 0."""
    rows = oc.get("internal_optimizer_trace")
    lst = rows if isinstance(rows, list) else []
    n = 0
    for row in lst:
        raw = row.get("equity_slope_dph")
        if raw is None:
            break
        try:
            v = float(raw)
        except (TypeError, ValueError):
            break
        if v > 0:
            n += 1
        else:
            break
    return n


def _trace_negative_equity_slope_streak(oc: dict[str, Any]) -> int:
    """Count consecutive trace rows (newest first) with equity_slope_dph < 0 (missing breaks the run)."""
    rows = oc.get("internal_optimizer_trace")
    lst = rows if isinstance(rows, list) else []
    n = 0
    for row in lst:
        raw = row.get("equity_slope_dph")
        if raw is None:
            break
        try:
            v = float(raw)
        except (TypeError, ValueError):
            break
        if v < 0:
            n += 1
        else:
            break
    return n


# Order for a forced "full strategy swap" when paper replay looks good but real outcomes are poor.
PAPER_LOSER_REGIME_ORDER = ("high_vol", "low_vol", "event_risk")


def _is_paper_winner_but_real_loser(oc: dict[str, Any], replay_result: dict[str, Any]) -> bool:
    """
    Detect divergence: composite replay / paper fitness (``score_dollars``) looks good, but Lab A
    is suffering — either a long run of **negative** equity $/h in the internal trace (paper
    "live" path), or an excessive patient stop-loss rate in the replay window.

    Must be called *after* the current ``internal_optimizer_trace`` row (with ``equity_slope_dph``)
    is appended so the negative-slope streak reflects the latest tick.
    """
    if not bool(oc.get("enable_paper_loser_detection", True)):
        return False
    th = _safe_float(oc.get("paper_winner_fitness_min", 0.0), 0.0)
    try:
        score = float(replay_result.get("score_dollars", 0.0))
    except (TypeError, ValueError):
        return False
    if not (float(score) > th):
        return False
    neg_n = max(1, int(oc.get("paper_loser_neg_equity_trace_min", 5) or 5))
    try:
        slr = float(replay_result.get("stop_loss_trigger_rate", 0.0))
    except (TypeError, ValueError):
        slr = 0.0
    if slr > _safe_float(oc.get("paper_loser_stop_rate_pct", 45.0), 45.0):
        return True
    if _trace_negative_equity_slope_streak(oc) >= neg_n:
        return True
    return False


def _rules_json_fingerprint(rules: list[dict[str, Any]] | None) -> str:
    if not isinstance(rules, list):
        return ""
    try:
        return json.dumps([dict(x) for x in rules if isinstance(x, dict)], sort_keys=True)[:3000]
    except Exception:
        return ""


def _norm_regime_perf_meta(oc: dict[str, Any]) -> dict[str, Any]:
    m = oc.get("regime_performance_meta")
    if not isinstance(m, dict):
        m = {}
    out: dict[str, Any] = {}
    for k in PAPER_LOSER_REGIME_ORDER:
        sub = m.get(k) if isinstance(m.get(k), dict) else {}
        out[k] = {
            "ewma_fitness": _safe_float(sub.get("ewma_fitness"), 0.0),
            "observations": max(0, int(sub.get("observations", 0) or 0)),
        }
    return out


def _norm_streaks(oc: dict[str, Any]) -> dict[str, int]:
    st = oc.get("regime_negative_fitness_streaks")
    if not isinstance(st, dict):
        st = {}
    return {k: max(0, int(st.get(k) or 0) if k in st else 0) for k in PAPER_LOSER_REGIME_ORDER}


def _regime_update_meta_and_streaks(
    oc: dict[str, Any], *, active_regime: str, score_dollars: float
) -> None:
    """
    Exponential meta-learning: decay every tick (older beliefs fade), then nudge the active
    regime's EWMA with the current replay composite. Negative-score streaks drive self-cleanup.
    """
    dcy = max(0.5, min(0.9999, _safe_float(oc.get("regime_ewma_decay_per_cycle", 0.996), 0.996)))
    a = max(0.02, min(0.4, _safe_float(oc.get("regime_ewma_alpha", 0.12), 0.12)))
    m = _norm_regime_perf_meta(oc)
    for k in PAPER_LOSER_REGIME_ORDER:
        m[k]["ewma_fitness"] = float(m[k].get("ewma_fitness", 0.0) or 0.0) * dcy
    ar = (active_regime or "low_vol").strip().lower()
    if ar not in PAPER_LOSER_REGIME_ORDER:
        ar = "low_vol"
    e0 = _safe_float(m[ar].get("ewma_fitness"), 0.0)
    s = _safe_float(score_dollars, 0.0)
    m[ar]["ewma_fitness"] = (1.0 - a) * e0 + a * s
    m[ar]["observations"] = int(m[ar].get("observations", 0) or 0) + 1
    oc["regime_performance_meta"] = m
    st2 = _norm_streaks(oc)
    if s < 0.0:
        st2[ar] = st2.get(ar, 0) + 1
    else:
        st2[ar] = 0
    oc["regime_negative_fitness_streaks"] = st2


def _regime_preferred_from_meta(oc: dict[str, Any], cycled: str) -> str:
    """
    Combine stepped rotation (``cycled``) with EMA+volume-weighted preference. Strong meta signal can
    override a weak cycled hand-off.
    """
    m = _norm_regime_perf_meta(oc)
    cycled = cycled if cycled in PAPER_LOSER_REGIME_ORDER else "low_vol"

    def w(k: str) -> float:
        return float(m[k].get("ewma_fitness", 0.0) or 0.0) * (1.0 + 0.01 * min(200, int(m[k].get("observations", 0) or 0)))

    by = {k: w(k) for k in PAPER_LOSER_REGIME_ORDER}
    best = max(PAPER_LOSER_REGIME_ORDER, key=lambda k: by.get(k, -1e9))
    if by.get(best, 0) > by.get(cycled, 0) + 0.2:
        return str(best)
    return str(cycled)


async def _load_top_distinct_history_rules(
    store: "Store | None", *, limit: int, current_fingerprint: str, take: int = 2
) -> list[tuple[str, list[dict[str, Any]]]]:
    if store is None:
        return []
    out: list[tuple[str, list[dict[str, Any]]]] = []
    try:
        rows = await store.list_config_history(max(8, int(limit) or 24), include_config=True)
    except (TypeError, OSError):
        return []
    for row in rows:
        conf = row.get("config")
        if not isinstance(conf, dict):
            continue
        la = conf.get("lab_a")
        if not isinstance(la, dict):
            continue
        hr = la.get("rules")
        if not isinstance(hr, list) or not hr:
            continue
        dlist = [dict(x) for x in hr if isinstance(x, dict)]
        if not dlist:
            continue
        fp = _rules_json_fingerprint(dlist)
        if not fp or (current_fingerprint and fp == current_fingerprint):
            continue
        if not any(s == fp for s, _ in out):
            out.append((fp, dlist))
        if len(out) >= take:
            break
    return out


def _interleave_blended_rules(
    nxt: str, la0: dict[str, Any], hist: list[tuple[str, list[dict[str, Any]]]], max_rules: int = 22
) -> list[dict[str, Any]]:
    """
    Merge the target regime's family with up to two historical configs' ``lab_a.rules`` in round-robin
    order (keeps the head of each, dedupes by name); caps list size for the API.
    """
    nxtk = _regime_to_rules_list_key(nxt)
    base = [dict(x) for x in (la0.get(nxtk) or la0.get("rules") or []) if isinstance(x, dict)]
    if not base:
        base = [dict(x) for x in (la0.get("rules") or []) if isinstance(x, dict)]
    per_hist = [[dict(x) for x in lst if isinstance(x, dict)][:8] for _fp, lst in hist]
    if not per_hist and not base:
        return []
    parts: list[list[dict[str, Any]]] = [*(per_hist or []), base[:8]]
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    max_tries = 40
    t = 0
    i = 0
    while len(merged) < max_rules and t < max_tries:
        t += 1
        any_added = False
        for p in parts:
            if not p:
                continue
            r = p[i] if i < len(p) else None
            if r is None:
                continue
            nm = str(r.get("name") or f"rule-{len(merged)}")
            if nm in seen:
                continue
            seen.add(nm)
            merged.append(dict(r))
            any_added = True
        if not any_added:
            break
        i += 1
    if not merged and base:
        return [json.loads(json.dumps(x)) for x in base[: max_rules]]
    for b in base:
        if len(merged) >= max_rules:
            break
        nmb = str(b.get("name") or f"b{len(merged)}")
        if nmb in seen:
            continue
        seen.add(nmb)
        merged.append(dict(b))
    return merged[:max_rules]


def _auto_tune_internal_thresholds(oc: dict[str, Any]) -> None:
    """
    Every ``auto_tune_interval_cycles`` (24), nudge heuristics: many paper-loser *swaps* in the window
    => tighten; strong risk with no action => loosen; low acceptance nudges up mutation base.
    """
    sw = int(oc.get("autotune_window_paper_loser_swaps", 0) or 0)
    rsk = int(oc.get("autotune_window_paper_loser_risk_events", 0) or 0)
    cyc = int(oc.get("optimizer_cycle_count", 0) or 0)
    pthr = int(oc.get("paper_loser_cycles_threshold", 4) or 4)
    pls = _safe_float(oc.get("paper_loser_stop_rate_pct", 45.0), 45.0)
    if oc.get("mutation_aggressiveness_autotune_baseline") is None:
        oc["mutation_aggressiveness_autotune_baseline"] = _safe_float(
            oc.get("mutation_aggressiveness", 0.75), 0.75
        )
    base = _safe_float(oc.get("mutation_aggressiveness_autotune_baseline"), 0.75)
    acc = _safe_float(oc.get("acceptance_rate_pct", 50.0), 50.0)
    ch: list[str] = []
    pthr0 = pthr
    if sw >= 2:
        pthr = min(8, pthr + 1)
    elif rsk >= 14 and sw == 0:
        pthr = max(2, pthr - 1)
    if pthr != pthr0:
        ch.append(f"paper_loser_cycles_threshold {pthr0}→{pthr} (swaps_24c={sw} risk_24c={rsk})")
    pls0 = pls
    if sw >= 3:
        pls = min(60.0, pls + 1.0)
    elif sw == 0 and cyc > 0:
        pls = max(32.0, pls - 0.4)
    if pls != pls0:
        ch.append(f"paper_loser_stop_rate_pct {pls0:.1f}→{pls:.1f} (swap_window={sw})")
    nb = base
    if acc < 28.0:
        nb = min(0.95, base + 0.04)
    elif acc > 72.0:
        nb = max(0.4, base - 0.02)
    if abs(nb - base) > 0.0005:
        ch.append(f"mutation_aggressiveness {base:.3f}→{nb:.3f} (acceptance={acc:.0f}%)")
        oc["mutation_aggressiveness_autotune_baseline"] = round(nb, 4)
        oc["mutation_aggressiveness"] = round(nb, 4)
    if pthr != pthr0:
        oc["paper_loser_cycles_threshold"] = pthr
    if pls != pls0:
        oc["paper_loser_stop_rate_pct"] = round(float(pls), 2)
    if ch:
        logger.info("AUTO-THRESHOLD (cycle=%d): %s", cyc, " | ".join(ch))
    else:
        logger.info(
            "AUTO-THRESHOLD (cycle=%d): no change (swaps_24c=%d risk_24c=%s acc=%.0f%%)",
            cyc,
            sw,
            rsk,
            acc,
        )


def _prune_failing_regime_families(cfg: dict[str, Any], oc: dict[str, Any]) -> list[str]:
    """
    If a family accrues ``prune_streak_regime_min_cycles`` consecutive *negative* composite
    replays while active, drop that regime's stored ruleset and re-seed from the active ``rules``.
    """
    la0 = dict(cfg.get("lab_a") or {}) if isinstance(cfg.get("lab_a"), dict) else {}
    mnc = max(3, int(oc.get("prune_streak_regime_min_cycles", 30) or 30))
    st2 = _norm_streaks(oc)
    pruned: list[str] = []
    base = [json.loads(json.dumps(x)) for x in (la0.get("rules") or []) if isinstance(x, dict)]
    for k in PAPER_LOSER_REGIME_ORDER:
        if st2.get(k, 0) < mnc:
            continue
        rkk = _regime_to_rules_list_key(k)
        if base:
            la0[rkk] = [json.loads(json.dumps(x)) for x in base[:8]]
        pruned.append(f"{k}:{mnc}neg")
        st2[k] = 0
    if pruned:
        oc["regime_negative_fitness_streaks"] = st2
        cfg["lab_a"] = la0
        logger.info("regime self-cleanup (prune stored families): %s", ", ".join(pruned))
    return pruned


def _append_radical_fresh_rules(
    rules_base: list[dict[str, Any]], rng: random.Random, *, cyc: int, deep: bool, max_rules: int
) -> None:
    """1–2 lightweight exploratory YES rules in deep-stuck (radical) mode only."""
    if not deep or not rules_base or len(rules_base) >= max_rules:
        return
    nadd = 2 if rng.random() < 0.2 else 1
    nadd = min(nadd, max(0, max_rules - len(rules_base) - 1))
    for j in range(nadd):
        seed0 = next((r for r in rules_base if str(r.get("side") or "yes").lower() != "no"), None) or rules_base[0]
        nbr = dict(seed0) if isinstance(seed0, dict) else {}
        nbr["name"] = f"auto-radical-{rng.randint(1000, 9999)}-c{cyc}"[:58]
        nbr["min_prob"] = round(max(0.02, min(0.5, 0.35 + rng.uniform(-0.1, 0.1))), 4)
        nbr["max_prob"] = round(max(0.51, min(0.98, 0.62 + rng.uniform(-0.1, 0.1))), 4)
        nbr["min_minutes_left"] = int(max(0, 3 + rng.randint(0, 4)))
        nbr["max_minutes_left"] = int(max(12, 40 + rng.randint(0, 20)))
        rules_base.append(nbr)


async def _apply_paper_loser_strategy_swap(
    store: "Store | None",
    cfg: dict[str, Any],
    oc: dict[str, Any],
    *,
    at_iso: str,
    repeated_cycles: int,
) -> dict[str, Any]:
    """
    After ``paper_loser_cycles_threshold`` consecutive *paper-winner but real-loser* ticks, force a
    new direction: (1) blend the stepped regime, meta-learned best regime, and the top 2 *distinct*
    history ``lab_a`` rules, (2) one-shot radical mutation, (3) short regime pin. Fully autonomous
    (no user toggles in frontends).
    """
    base_meta: dict[str, Any] = {"swapped": False, "repeated_cycles": int(repeated_cycles)}
    pthr = max(1, int(oc.get("paper_loser_cycles_threshold", 4) or 4))
    if repeated_cycles < pthr:
        return base_meta
    _lab, base_rules = _ensure_lab_rules(cfg, BRANCH_LAB_A)
    if not base_rules:
        return {**base_meta, "reject_reason": "no_rules"}
    la_raw = cfg.get("lab_a")
    if isinstance(la_raw, dict):
        la0 = {**_lab, **la_raw}
    else:
        la0 = {**_lab}
    for fld in ("rules_high_vol", "rules_low_vol", "rules_event"):
        cr = la0.get(fld)
        if not isinstance(cr, list) or len(cr) == 0:
            la0[fld] = [json.loads(json.dumps(x)) for x in base_rules]
    cur = str(la0.get("active_regime") or "low_vol").strip().lower()
    if cur not in PAPER_LOSER_REGIME_ORDER:
        cur = "low_vol"
    cycled = PAPER_LOSER_REGIME_ORDER[(PAPER_LOSER_REGIME_ORDER.index(cur) + 1) % len(PAPER_LOSER_REGIME_ORDER)]
    nxt = _regime_preferred_from_meta(oc, cycled)
    cur_rules_sig = _rules_json_fingerprint(
        [dict(x) for x in (la0.get("rules") if isinstance(la0.get("rules"), list) else []) if isinstance(x, dict)]
    )
    h_two = await _load_top_distinct_history_rules(
        store, limit=32, current_fingerprint=cur_rules_sig, take=2
    )
    blended = _interleave_blended_rules(nxt, la0, h_two, max_rules=22)
    if not blended:
        rk0 = _regime_to_rules_list_key(nxt)
        blended = [json.loads(json.dumps(x)) for x in (la0.get(rk0) or base_rules) if isinstance(x, dict)]
    try:
        blended = normalize_rules_list(blended)[: int(MAX_LAB_A_RULES_AFTER_CLAUDE_DELTAS) - 2]
    except Exception as ex:
        logger.info("paper_loser: normalize_rules_list for blend: %s", ex)
    nlist2 = [json.loads(json.dumps(x)) for x in blended if isinstance(x, dict)]
    rkf = _regime_to_rules_list_key(nxt)
    la0["active_regime"] = nxt
    la0["rules"] = nlist2
    la0[rkf] = nlist2
    at_dt = _parse_iso_dt(at_iso) or _utc_now()
    pin_h = max(0.5, _safe_float(oc.get("regime_paper_loser_pin_hours", 4.0), 4.0))
    oc["regime_paper_loser_pinned"] = nxt
    oc["regime_paper_loser_pinned_until"] = _iso(at_dt + dt.timedelta(hours=pin_h))
    oc["paper_loser_radical_next"] = True
    oc["optimizer_consecutive_paper_loser_cycles"] = 0
    oc["last_paper_loser_swap_at"] = at_iso
    cfg["lab_a"] = la0
    oc["last_paper_loser_meta_nudge_regime"] = nxt
    logger.warning(
        "Paper-winner but real-loser detected for %d cycles — forcing full strategy swap to new regime: %s "
        "(cycled=%s, blended_historical=%d)",
        int(repeated_cycles),
        nxt,
        cycled,
        len(h_two),
    )
    return {
        "swapped": True,
        "repeated_cycles": int(repeated_cycles),
        "new_regime": nxt,
        "cycled_regime": cycled,
        "history_dists": len(h_two),
        "blended_rules": len(nlist2),
        "history_applied": bool(len(h_two) > 0),
    }


def _auto_revert_cooldown_ok(oc: dict[str, Any], *, now: dt.datetime) -> bool:
    """At most one auto-revert every 4 hours (wall clock from ``optimizer_auto_revert_last_at``)."""
    prev = _parse_iso_dt(str(oc.get("optimizer_auto_revert_last_at") or "").strip())
    if prev is None:
        return True
    return (now - prev) >= dt.timedelta(hours=4)


def _auto_revert_stuck_triggers(
    *,
    red_streak: int,
    acceptance_pct: float,
    oc: dict[str, Any],
) -> dict[str, Any]:
    """
    Stuck heuristics for auto-revert (no side effects). Used from ``_maybe_auto_revert_if_stuck`` only
    *after* this cycle's internal trace row (with ``equity_slope_dph``) is appended and acceptance is
    recalculated — same policy is summarized in the docstring for ``_check_optimizer_health``:

    - ``red_streak >= 15`` — consecutive *red* health cycles (low acceptance on internal mutants), or
    - ``acceptance_rate_pct < 20`` and ``_trace_negative_equity_slope_streak`` ≥ 8 (chronic Lab A equity decay).
    """
    neg = _trace_negative_equity_slope_streak(oc)
    stuck_red = red_streak >= 15
    stuck_acc_slope = float(acceptance_pct) < 20.0 and neg >= 8
    return {
        "stuck_red_15": stuck_red,
        "stuck_low_acceptance_neg_slope": stuck_acc_slope,
        "negative_equity_slope_streak": neg,
    }


def _recalculate_acceptance_rate(oc: dict[str, Any]) -> None:
    tr_rows = oc.get("internal_optimizer_trace")
    tr_list = tr_rows if isinstance(tr_rows, list) else []
    accepted_n = sum(1 for r in tr_list if bool(r.get("accepted")))
    total_n = len(tr_list)
    oc["acceptance_rate_pct"] = round((accepted_n * 100.0 / total_n), 2) if total_n > 0 else 0.0


async def _maybe_auto_revert_if_stuck(
    store: Store,
    *,
    cfg: dict[str, Any],
    oc: dict[str, Any],
    tr_a: list[dict[str, Any]],
    sg_a: list[dict[str, Any]],
    at_iso: str,
    red_streak: int,
    acceptance_pct: float,
) -> dict[str, Any]:
    """
    When the internal optimizer is stuck, restore ``lab_a`` from the best ``config_history`` snapshot.

    Eligibility (any) — see ``_auto_revert_stuck_triggers`` (must stay in sync):
      - ``red_streak >= 15`` consecutive red-health cycles, or
      - ``acceptance_pct < 20`` and Lab A ``equity_slope_dph < 0`` for 8+ consecutive trace rows.

    Picks the snapshot in the last 30 days whose ``lab_a`` yields the highest
    **composite** replay score (``_replay_fitness_bundle`` / ``score_dollars`` ===
    ``composite_fitness_score`` output) on recent settled trades. Respects ``enable_auto_revert``
    (default True) and a **4-hour** cooldown between reverts.
    """
    meta: dict[str, Any] = {"reverted": False, "best_score": None, "reason": ""}
    now = _parse_iso_dt(at_iso) or _utc_now()
    if not bool(oc.get("enable_auto_revert", True)):
        meta["reason"] = "disabled"
        return meta
    if not _auto_revert_cooldown_ok(oc, now=now):
        meta["reason"] = "cooldown"
        return meta

    trig = _auto_revert_stuck_triggers(red_streak=red_streak, acceptance_pct=acceptance_pct, oc=oc)
    stuck_red = bool(trig["stuck_red_15"])
    stuck_slope = bool(trig["stuck_low_acceptance_neg_slope"])
    neg_streak = int(trig.get("negative_equity_slope_streak") or 0)
    if not (stuck_red or stuck_slope):
        meta["reason"] = "thresholds_not_met"
        return meta

    hist = await store.list_config_history(500, include_config=True)
    cutoff = now - dt.timedelta(days=30)
    st_settled = [t for t in tr_a if str(t.get("status") or "").lower() == "settled" and t.get("pnl_cents") is not None]
    tail_n = min(200, max(8, len(st_settled)))
    window = st_settled[:tail_n]
    if len(window) < 8:
        meta["reason"] = "insufficient_settled_for_replay_scoring"
        return meta

    sig_desc = _signals_sorted_desc(sg_a)
    fee_flag = bool(oc.get("include_fees_in_score", True))
    best_lab: dict[str, Any] | None = None
    best_score = float("-inf")
    best_hid: int | None = None

    for row in hist:
        ts = _parse_iso_dt(row.get("timestamp"))
        if ts is None or ts < cutoff:
            continue
        cand = row.get("config")
        if not isinstance(cand, dict):
            continue
        lab_snap = cand.get("lab_a")
        if not isinstance(lab_snap, dict):
            continue
        rules_try = lab_snap.get("rules")
        if not isinstance(rules_try, list) or len(rules_try) == 0:
            continue
        cfg_try = dict(cfg)
        cfg_try["lab_a"] = json.loads(json.dumps(lab_snap))
        lab_x, rules_x = _ensure_lab_rules(cfg_try, BRANCH_LAB_A)
        try:
            rk = _replay_open_kw(cfg_try, at_iso=at_iso, branch=BRANCH_LAB_A, trades=tr_a)
            fb = _replay_fitness_bundle(
                window,
                rules_x,
                sig_desc,
                include_fees_in_score=fee_flag,
                max_rows=tail_n,
                branch_trading_cfg=lab_x,
                **rk,
            )
            # score_dollars is composite_fitness_score() blended PnL / drawdown / vol / Sharpe (see optimizer.fitness)
            sc = float(fb.get("score_dollars") or 0.0)
        except Exception as ex:
            logger.debug("auto_revert_skip_history_row: %s", ex)
            continue
        if sc > best_score:
            best_score = sc
            best_lab = json.loads(json.dumps(lab_snap))
            try:
                best_hid = int(row.get("id") or 0)
            except (TypeError, ValueError):
                best_hid = None

    if best_lab is None or best_score == float("-inf"):
        meta["reason"] = "no_eligible_history"
        logger.info("auto_revert: stuck criteria met but no eligible config_history row with replayable Lab A.")
        return meta

    cfg["lab_a"] = best_lab
    oc["optimizer_red_streak_cycles"] = 0
    oc["optimizer_auto_revert_last_at"] = at_iso
    oc["optimizer_last_auto_revert_fitness"] = round(float(best_score), 6)
    oc["optimizer_last_auto_revert_history_id"] = int(best_hid or 0)
    oc["optimizer_suggested_action"] = (
        "Auto-revert triggered — Lab A restored from best config_history snapshot (replay fitness on recent settles)."
    )
    oc["last_status"] = "ok_auto_revert_stuck"
    reason_tag = "stuck_red_15" if stuck_red else "stuck_low_acceptance_slope"

    if stuck_red:
        logger.warning(
            "Optimizer stuck for %d cycles — auto-reverted Lab A to best historical config (fitness: %.4f, history_id=%s)",
            int(red_streak),
            float(best_score),
            str(best_hid),
        )
    else:
        logger.warning(
            "Optimizer stuck (acceptance<20% and %d negative Lab A $/h slope rows) — auto-reverted Lab A to best historical config (fitness: %.4f, history_id=%s)",
            neg_streak,
            float(best_score),
            str(best_hid),
        )

    _append_internal_trace(
        oc,
        {
            "at": at_iso,
            "cycle": int(oc.get("optimizer_cycle_count") or 0),
            "score": round(float(best_score), 6),
            "score_before": None,
            "score_after": round(float(best_score), 6),
            "accepted": False,
            "reject_reason": "auto-revert-stuck",
            "mutant": False,
            "changes_n": 0,
            "auto_revert": True,
            "auto_revert_reason": reason_tag,
            "history_id": best_hid,
            "total_pnl_from_stops_cents": 0,
            "total_pnl_from_stops_dollars": 0.0,
            "stop_loss_trigger_rate_pct": 0.0,
            "stop_loss_exits_n": 0,
            "open_simulated_stop_exits_n": 0,
            "equity_slope_dph": None,
        },
    )
    _recalculate_acceptance_rate(oc)
    eff_sc, mtier = _compute_mutation_scale(oc)
    oc["mutation_tier"] = mtier
    oc["effective_mutation_scale"] = round(eff_sc, 4)
    health2 = _check_optimizer_health(oc)
    oc["optimizer_health_color"] = str(health2["health_color"])
    meta["reverted"] = True
    meta["best_score"] = float(best_score)
    meta["reason"] = reason_tag
    return meta


def _compute_mutation_scale(oc: dict[str, Any]) -> tuple[float, str]:
    """
    Effective internal-mutation scale (0.06–1.75) from acceptance tier × user mutation_aggressiveness (0–1).

    Returns (effective_scale, tier_label) where tier_label is light | medium | strong.
    """
    acc = _safe_float(oc.get("acceptance_rate_pct"), 50.0)
    user_mag = max(0.0, min(1.0, _safe_float(oc.get("mutation_aggressiveness"), 0.75)))
    if acc > 60.0:
        tier = "light"
        tier_mult = 0.68
    elif acc >= 30.0:
        tier = "medium"
        tier_mult = 1.0
    else:
        tier = "strong"
        tier_mult = 1.38
    eff = max(0.06, min(1.75, tier_mult * (0.45 + 0.55 * user_mag)))
    return eff, tier


def _check_optimizer_health(oc: dict[str, Any]) -> dict[str, Any]:
    """
    Lightweight self-check for dashboards and logging.

    ``mutation_aggressiveness`` is the configured 0–1 dial; acceptance tiers still modulate
    effective perturbation size inside ``_compute_mutation_scale``.

    **Auto-revert (stuck) policy** is *not* evaluated in this function (ordering: red-streak and
    acceptance for this tick are applied after the trace write). It runs in
    ``_maybe_auto_revert_if_stuck`` via ``_auto_revert_stuck_triggers``: auto-revert may trigger when
    ``red_streak_cycles >= 15`` OR (``acceptance < 20`` and 8+ consecutive negative Lab A equity slopes
    in ``internal_optimizer_trace``), subject to ``enable_auto_revert`` and a 4h cooldown. Best config
    is selected from ``config_history`` in the last 30 days by highest replay ``score_dollars`` (i.e.
    ``composite_fitness_score``'s main score) on recent settles.

    **Paper-winner / real-loser** (when ``enable_paper_loser_detection``) can elevate concern when replay
    fitness is strong but the Lab A equity path or stop-loss rate disagrees; ``paper_loser_risk_last`` and
    ``optimizer_consecutive_paper_loser_cycles`` reflect the latest tick (swap clears the counter).
    """
    acc = round(_safe_float(oc.get("acceptance_rate_pct"), 0.0), 2)
    user_mag = round(max(0.0, min(1.0, _safe_float(oc.get("mutation_aggressiveness"), 0.75))), 4)
    pthr = max(1, int(oc.get("paper_loser_cycles_threshold", 4) or 4))
    pwc = int(oc.get("optimizer_consecutive_paper_loser_cycles", 0) or 0)
    pwl = bool(oc.get("paper_loser_risk_last"))
    pin = str(oc.get("regime_paper_loser_pinned") or "").strip().lower()
    pin_ex = str(oc.get("regime_paper_loser_pinned_until") or "")
    if acc > 60.0:
        color = "green"
        action = "Continue; acceptance is healthy — keep monitoring trace and replay PnL."
    elif acc >= 30.0:
        color = "yellow"
        action = (
            "Mixed acceptance — watch the internal trace; you may raise mutation_aggressiveness slightly "
            "or review min-trade gates if progress stalls."
        )
    else:
        color = "red"
        action = (
            "Low acceptance — replay/stat gates are rejecting most mutants. Review Lab A paper context, "
            "threshold gates, or consider a manual config reset."
        )
    if pwl and bool(oc.get("enable_paper_loser_detection", True)):
        if pwc >= 1 and pwc < pthr:
            action = f"{action} (paper-loser watch: {pwc}/{pthr} consecutive divergent cycles)"
        if color == "green" and pwc > 0:
            color = "yellow"
    if pin in ("high_vol", "low_vol", "event_risk") and pin_ex:
        action = f"{action} (post paper-loser swap: regime pin active until {pin_ex})"
    return {
        "health_color": color,
        "acceptance_rate_pct": acc,
        "mutation_aggressiveness": user_mag,
        "suggested_action": action,
        "paper_loser_risk_last": pwl,
        "paper_loser_consecutive_cycles": pwc,
        "paper_loser_pinned_regime": pin,
        "paper_loser_pinned_until": pin_ex,
    }


def _regime_volatility(signals: list[dict[str, Any]], *, hours: float, end: dt.datetime) -> dict[str, Any]:
    cutoff = end - dt.timedelta(hours=max(0.5, hours))
    vals: list[float] = []
    for s in signals:
        ca = _parse_iso_dt(s.get("created_at"))
        if ca is None or ca < cutoff:
            continue
        if s.get("implied_prob") is None:
            continue
        vals.append(_safe_float(s.get("implied_prob"), 0.5))
    if len(vals) < 5:
        return {"n": len(vals), "stdev_implied_yes": None, "bucket": "unknown"}
    mean = sum(vals) / len(vals)
    var = sum((x - mean) ** 2 for x in vals) / max(1, len(vals) - 1)
    stdev = var**0.5
    bucket = "mid"
    if stdev >= 0.12:
        bucket = "high_vol"
    elif stdev <= 0.06:
        bucket = "low_vol"
    return {"n": len(vals), "stdev_implied_yes": stdev, "bucket": bucket}


def _trading_regime_key_from_context(
    oc: dict[str, Any], sg_a: list[dict[str, Any]], st_a: list[dict[str, Any]], at_iso: str
) -> str:
    """``high_vol`` | ``low_vol`` | ``event_risk`` — which Lab A family should be active (internal optimizer)."""
    end = _parse_iso_dt(at_iso) or _utc_now()
    slr = _safe_float(oc.get("replay_stop_loss_trigger_rate_pct", 0.0), 0.0)
    if slr >= 35.0:
        return "event_risk"
    mins: list[float] = []
    for s in _signals_sorted_desc(sg_a)[:60]:
        ml = s.get("minutes_left")
        if ml is not None:
            try:
                mins.append(float(ml))
            except (TypeError, ValueError):
                pass
    if mins and min(mins) < 60.0:
        return "event_risk"
    h = max(0.5, float(oc.get("regime_lookback_hours", 4) or 4.0))
    rvol = _regime_volatility(sg_a, hours=h, end=end)
    b = str(rvol.get("bucket") or "unknown")
    if b == "high_vol":
        return "high_vol"
    if b == "low_vol":
        return "low_vol"
    return "low_vol"


def _regime_to_rules_list_key(reg: str) -> str:
    r = (reg or "low_vol").strip().lower()
    if r == "high_vol":
        return "rules_high_vol"
    if r == "event_risk":
        return "rules_event"
    return "rules_low_vol"


def _sync_regime_rule_families_to_lab_a(
    cfg: dict[str, Any],
    oc: dict[str, Any],
    sg_a: list[dict[str, Any]],
    st_a: list[dict[str, Any]],
    at_iso: str,
) -> bool:
    """
    Maintain ``rules_high_vol`` / ``rules_low_vol`` / ``rules_event`` on Lab A and set ``rules`` to the
    list for the current regime. First run seed those families from the merged ``rules`` list.
    """
    if not bool(oc.get("enable_regime_rules", True)):
        return False
    at_dt = _parse_iso_dt(at_iso) or _utc_now()
    pin_raw = str(oc.get("regime_paper_loser_pinned") or "").strip().lower()
    pin_until = _parse_iso_dt(str(oc.get("regime_paper_loser_pinned_until") or "").strip())
    if (
        pin_raw in ("high_vol", "low_vol", "event_risk")
        and pin_until is not None
        and at_dt < pin_until
    ):
        new_reg = pin_raw
    else:
        if pin_until is not None and at_dt >= pin_until:
            oc["regime_paper_loser_pinned"] = ""
            oc["regime_paper_loser_pinned_until"] = ""
        new_reg = _trading_regime_key_from_context(oc, sg_a, st_a, at_iso)
    _lab, base_rules = _ensure_lab_rules(cfg, BRANCH_LAB_A)
    if not base_rules:
        return False
    la_raw = cfg.get("lab_a")
    if isinstance(la_raw, dict):
        la0 = {**_lab, **la_raw}
    else:
        la0 = {**_lab}
    for fld in ("rules_high_vol", "rules_low_vol", "rules_event"):
        cr = la0.get(fld)
        if not isinstance(cr, list) or len(cr) == 0:
            la0[fld] = [json.loads(json.dumps(x)) for x in base_rules]
    rk = _regime_to_rules_list_key(new_reg)
    nlist: list[dict[str, Any]] = la0.get(rk) if isinstance(la0.get(rk), list) else []
    if not nlist:
        nlist = [json.loads(json.dumps(x)) for x in base_rules]
    nlist = [dict(r) for r in nlist if isinstance(r, dict)]
    if not nlist:
        nlist = [json.loads(json.dumps(x)) for x in base_rules]
    prev = str(la0.get("active_regime") or "")
    la0["active_regime"] = new_reg
    la0["rules"] = nlist
    cfg["lab_a"] = la0
    if prev and prev != new_reg:
        logger.info("Lab A regime: %s -> %s; active ruleset %s (%d rules)", prev, new_reg, rk, len(nlist))
    return bool(prev) and prev != new_reg


def _radical_exploration_active(oc: dict[str, Any]) -> bool:
    if not bool(oc.get("radical_exploration_enabled", True)):
        return False
    rs = int(oc.get("optimizer_red_streak_cycles", 0) or 0)
    lo = int(oc.get("optimizer_consecutive_low_acceptance_cycles", 0) or 0)
    acc = _safe_float(oc.get("acceptance_rate_pct", 100.0), 100.0)
    if rs >= 20:
        return True
    if lo >= 4 and acc < 15.0:
        return True
    return False


def _build_metrics_context(
    *,
    cfg: dict[str, Any],
    oc: dict[str, Any],
    tr_a: list[dict[str, Any]],
    tr_b: list[dict[str, Any]],
    tr_c: list[dict[str, Any]],
    tr_d: list[dict[str, Any]],
    sg_a: list[dict[str, Any]],
    sg_b: list[dict[str, Any]],
    sg_c: list[dict[str, Any]],
    sg_d: list[dict[str, Any]],
    eq_a: list[dict[str, Any]],
    eq_b: list[dict[str, Any]],
    eq_c: list[dict[str, Any]],
    eq_d: list[dict[str, Any]],
    end: dt.datetime,
) -> dict[str, Any]:
    include_fees = bool(oc.get("include_fees_in_score", True))
    regime_h = float(oc.get("regime_lookback_hours") or 4)
    sa = _signals_sorted_desc(sg_a)
    sb = _signals_sorted_desc(sg_b)
    sc = _signals_sorted_desc(sg_c)
    sd = _signals_sorted_desc(sg_d)
    st_a = [t for t in tr_a if str(t.get("status") or "").lower() == "settled" and t.get("pnl_cents") is not None]
    st_b = [t for t in tr_b if str(t.get("status") or "").lower() == "settled" and t.get("pnl_cents") is not None]
    st_c = [t for t in tr_c if str(t.get("status") or "").lower() == "settled" and t.get("pnl_cents") is not None]
    st_d = [t for t in tr_d if str(t.get("status") or "").lower() == "settled" and t.get("pnl_cents") is not None]
    lab_a = cfg.get("lab_a") if isinstance(cfg.get("lab_a"), dict) else {}
    lab_b = cfg.get("lab_b") if isinstance(cfg.get("lab_b"), dict) else {}
    lab_c = cfg.get("lab_c") if isinstance(cfg.get("lab_c"), dict) else {}
    lab_d = cfg.get("lab_d") if isinstance(cfg.get("lab_d"), dict) else {}
    _, rules_a = _ensure_lab_rules(cfg, BRANCH_LAB_A)
    _, rules_b = _ensure_lab_rules(cfg, BRANCH_LAB_B)
    _, rules_c = _ensure_lab_rules(cfg, BRANCH_LAB_C)
    _, rules_d = _ensure_lab_rules(cfg, BRANCH_LAB_D)
    rep_a = _replay_pnl_under_rules(
        st_a, rules_a, sa, include_fees_in_score=include_fees, branch_trading_cfg=lab_a
    )
    rep_b = _replay_pnl_under_rules(
        st_b, rules_b, sb, include_fees_in_score=include_fees, branch_trading_cfg=lab_b
    )
    rep_c = _replay_pnl_under_rules(
        st_c, rules_c, sc, include_fees_in_score=include_fees, branch_trading_cfg=lab_c
    )
    rep_d = _replay_pnl_under_rules(
        st_d, rules_d, sd, include_fees_in_score=include_fees, branch_trading_cfg=lab_d
    )
    def _pf_var(rows: list[dict[str, Any]]) -> dict[str, Any]:
        gross_win = sum(int(t.get("pnl_cents") or 0) for t in rows if int(t.get("pnl_cents") or 0) > 0)
        gross_loss = abs(sum(int(t.get("pnl_cents") or 0) for t in rows if int(t.get("pnl_cents") or 0) < 0))
        pf = (gross_win / gross_loss) if gross_loss > 0 else None
        pc = [int(t.get("pnl_cents") or 0) for t in rows]
        if len(pc) < 2:
            var = None
        else:
            m = sum(pc) / len(pc)
            var = sum((x - m) ** 2 for x in pc) / max(1, len(pc) - 1)
        return {"profit_factor": pf, "pnl_variance_cents_sq": var}

    return {
        "objective_metrics": {
            "hint": "Maximize risk-adjusted edge: favor higher profit_factor × win_rate with lower PnL variance across settled trades.",
            "include_fees_in_score": include_fees,
        },
        "lab_a": {
            "settled_trades": len(st_a),
            "profitable_trades": sum(1 for t in st_a if int(t.get("pnl_cents") or 0) > 0),
            "balance_fraction_per_window": lab_a.get("balance_fraction_per_window"),
            "window_minutes": lab_a.get("window_minutes"),
            "replay_under_current_rules_pnl_cents": rep_a[0],
            "replay_matched_trades": rep_a[1],
            "per_rule_stats_48h": _per_rule_stats_48h(st_a, end=end),
            "profit_factor_and_variance": _pf_var(st_a),
            "equity_slope_dollars_per_hour": _equity_slope_dollars_per_hour(eq_a),
            "regime_primary_hours": regime_h,
            "regime": _regime_volatility(sg_a, hours=regime_h, end=end),
            "regime_last_4h": _regime_volatility(sg_a, hours=4.0, end=end),
            "regime_last_24h": _regime_volatility(sg_a, hours=24.0, end=end),
        },
        "lab_b": {
            "settled_trades": len(st_b),
            "profitable_trades": sum(1 for t in st_b if int(t.get("pnl_cents") or 0) > 0),
            "balance_fraction_per_window": lab_b.get("balance_fraction_per_window"),
            "window_minutes": lab_b.get("window_minutes"),
            "replay_under_current_rules_pnl_cents": rep_b[0],
            "replay_matched_trades": rep_b[1],
            "per_rule_stats_48h": _per_rule_stats_48h(st_b, end=end),
            "profit_factor_and_variance": _pf_var(st_b),
            "equity_slope_dollars_per_hour": _equity_slope_dollars_per_hour(eq_b),
            "regime_primary_hours": regime_h,
            "regime": _regime_volatility(sg_b, hours=regime_h, end=end),
            "regime_last_4h": _regime_volatility(sg_b, hours=4.0, end=end),
            "regime_last_24h": _regime_volatility(sg_b, hours=24.0, end=end),
        },
        "lab_c": {
            "settled_trades": len(st_c),
            "profitable_trades": sum(1 for t in st_c if int(t.get("pnl_cents") or 0) > 0),
            "balance_fraction_per_window": lab_c.get("balance_fraction_per_window"),
            "window_minutes": lab_c.get("window_minutes"),
            "replay_under_current_rules_pnl_cents": rep_c[0],
            "replay_matched_trades": rep_c[1],
            "per_rule_stats_48h": _per_rule_stats_48h(st_c, end=end),
            "profit_factor_and_variance": _pf_var(st_c),
            "equity_slope_dollars_per_hour": _equity_slope_dollars_per_hour(eq_c),
            "regime_primary_hours": regime_h,
            "regime": _regime_volatility(sg_c, hours=regime_h, end=end),
            "regime_last_4h": _regime_volatility(sg_c, hours=4.0, end=end),
            "regime_last_24h": _regime_volatility(sg_c, hours=24.0, end=end),
        },
        "lab_d": {
            "settled_trades": len(st_d),
            "profitable_trades": sum(1 for t in st_d if int(t.get("pnl_cents") or 0) > 0),
            "balance_fraction_per_window": lab_d.get("balance_fraction_per_window"),
            "window_minutes": lab_d.get("window_minutes"),
            "replay_under_current_rules_pnl_cents": rep_d[0],
            "replay_matched_trades": rep_d[1],
            "per_rule_stats_48h": _per_rule_stats_48h(st_d, end=end),
            "profit_factor_and_variance": _pf_var(st_d),
            "equity_slope_dollars_per_hour": _equity_slope_dollars_per_hour(eq_d),
            "regime_primary_hours": regime_h,
            "regime": _regime_volatility(sg_d, hours=regime_h, end=end),
            "regime_last_4h": _regime_volatility(sg_d, hours=4.0, end=end),
            "regime_last_24h": _regime_volatility(sg_d, hours=24.0, end=end),
        },
        "optimizer_guards": {
            "min_trades_for_optimize": oc.get("min_trades_for_optimize"),
            "min_profitable_trades": oc.get("min_profitable_trades"),
            "optimize_bet_size": oc.get("optimize_bet_size"),
            "backtest_proposals": oc.get("backtest_proposals"),
        },
    }


def _ensure_lab_rules(cfg: dict[str, Any], branch: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    lk = _lab_key_for_branch(branch) or "lab_a"
    lab = cfg.get(lk)
    if not isinstance(lab, dict):
        lab = {}
    rules = lab.get("rules")
    if not isinstance(rules, list) or not rules:
        base = cfg.get("rules")
        rules = [dict(r) for r in base] if isinstance(base, list) else []
    return dict(lab), [dict(r) for r in rules if isinstance(r, dict)]


def _apply_rule_thresholds(rules: list[dict[str, Any]], *, yes_floor_pct: int, min_minutes_left: int, style: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    floor = max(1, min(99, int(yes_floor_pct))) / 100.0
    minm = max(0, int(min_minutes_left))
    for r in rules:
        side = str(r.get("side") or "yes").strip().lower()
        if side == "no":
            out.append(dict(r))
            continue
        nr = dict(r)
        lo = _safe_float(nr.get("min_prob"), 0.0)
        hi = _safe_float(nr.get("max_prob"), max(lo, floor))
        lo = max(lo, floor)
        if hi < lo:
            hi = lo
        cur_minm = _safe_int(nr.get("min_minutes_left"), minm)
        cur_maxm = _safe_int(nr.get("max_minutes_left"), max(cur_minm, minm))
        if style == "conservative":
            cur_minm = max(cur_minm, minm)
        elif style == "aggressive":
            cur_minm = min(cur_minm, minm)
        else:
            # blend: interpolate between current and conservative tightening
            cur_minm = int(round((cur_minm + max(cur_minm, minm)) / 2.0))
        if cur_maxm < cur_minm:
            cur_maxm = cur_minm
        nr["min_prob"] = round(lo, 4)
        nr["max_prob"] = round(hi, 4)
        nr["min_minutes_left"] = int(cur_minm)
        nr["max_minutes_left"] = int(cur_maxm)
        out.append(nr)
    return out


def _history_item(
    *,
    at_iso: str,
    branch: str,
    style: str,
    reason: str,
    before_floor: int,
    after_floor: int,
    before_minm: int,
    after_minm: int,
    before_extra: dict[str, Any] | None = None,
    after_extra: dict[str, Any] | None = None,
    tick_hint: str | None = None,
) -> dict[str, Any]:
    if branch == BRANCH_LAB_A:
        lab = "Lab A"
    elif branch == BRANCH_LAB_B:
        lab = "Lab B"
    elif branch == BRANCH_LAB_C:
        lab = "Lab C"
    else:
        lab = "Lab D"
    before: dict[str, Any] = {"yes_floor_pct": before_floor, "min_minutes_left": before_minm}
    after: dict[str, Any] = {"yes_floor_pct": after_floor, "min_minutes_left": after_minm}
    if before_extra:
        before.update(before_extra)
    if after_extra:
        after.update(after_extra)
    out: dict[str, Any] = {
        "id": uuid4().hex,
        "created_at": at_iso,
        "branch": branch,
        "lab_label": lab,
        "style": style,
        "reason": reason,
        "summary": f"{lab} {style}: YES floor {before_floor}% -> {after_floor}%, min minutes {before_minm} -> {after_minm}",
        "before": before,
        "after": after,
    }
    if tick_hint:
        out["tick_hint"] = tick_hint
    return out


def _count_losses_at_or_above_yes_floor(
    settled: list[dict[str, Any]],
    sig_idx: dict[str, dict[str, Any]],
    *,
    yes_floor_pct: int,
    max_rows: int = 80,
) -> int:
    """Count recent losing settled trades whose entry implied YES was at/above the configured floor (0–100)."""
    thr = max(1, min(99, int(yes_floor_pct))) / 100.0
    losses_at_threshold = 0
    for t in settled[:max_rows]:
        pnl = _safe_int(t.get("pnl_cents"), 0)
        if pnl >= 0:
            continue
        ex: dict[str, Any]
        try:
            ex = json.loads(str(t.get("extra_json") or "{}"))
        except Exception:
            ex = {}
        p = _safe_float(ex.get("entry_implied_yes"), -1.0)
        if p < 0:
            s = sig_idx.get(str(t.get("ticker") or ""))
            p = _safe_float((s or {}).get("implied_prob"), -1.0)
        if p >= thr:
            losses_at_threshold += 1
    return losses_at_threshold


def _merge_pulse_trace(oc: dict[str, Any], changes: list[dict[str, Any]]) -> None:
    pt = oc.get("pulse_trace")
    old_pt = pt if isinstance(pt, list) else []
    new_rows: list[dict[str, Any]] = []
    for ch in changes:
        new_rows.append(
            {
                "at": ch.get("created_at"),
                "kind": str(ch.get("style") or "change"),
                "message": str(ch.get("summary") or ch.get("reason") or "")[:400],
                "change_id": ch.get("id"),
            }
        )
    oc["pulse_trace"] = [*new_rows, *old_pt][:40]


def _optimizer_pulse_bc_enrichment(cfg: dict[str, Any], oc: dict[str, Any]) -> dict[str, Any]:
    """Extra ``after`` keys so the dashboard pulse chart can plot Lab B/C/D reference floors and bet fractions."""
    def gfrac(lk: str) -> float:
        lab = cfg.get(lk) if isinstance(cfg.get(lk), dict) else {}
        try:
            return float(lab.get("balance_fraction_per_window") or cfg.get("balance_fraction_per_window") or 0.03)
        except (TypeError, ValueError):
            return 0.03

    return {
        "lab_b_yes_floor_pct": max(1, min(99, _safe_int(oc.get("lab_b_yes_floor_pct"), 55))),
        "lab_c_yes_floor_pct": max(1, min(99, _safe_int(oc.get("lab_c_yes_floor_pct"), 52))),
        "lab_d_yes_floor_pct": max(1, min(99, _safe_int(oc.get("lab_d_yes_floor_pct"), 50))),
        "lab_b_balance_fraction": round(gfrac("lab_b"), 4),
        "lab_c_balance_fraction": round(gfrac("lab_c"), 4),
        "lab_d_balance_fraction": round(gfrac("lab_d"), 4),
    }


def pulse_chart_baseline(cfg: dict[str, Any], oc: dict[str, Any]) -> dict[str, Any]:
    """Current Lab A YES floor + bet fraction and Lab B/C/D reference values (same keys as pulse change_history ``after``)."""
    lab_a = cfg.get("lab_a") if isinstance(cfg.get("lab_a"), dict) else {}
    try:
        bf_a = float(lab_a.get("balance_fraction_per_window") or cfg.get("balance_fraction_per_window") or 0.03)
    except (TypeError, ValueError):
        bf_a = 0.03
    bc = _optimizer_pulse_bc_enrichment(cfg, oc)
    return {
        "yes_floor_pct": max(1, min(99, _safe_int(oc.get("lab_a_yes_floor_pct"), 57))),
        "balance_fraction_per_window": round(bf_a, 4),
        **bc,
        "loss_streak_trigger": max(1, min(12, _safe_int(oc.get("loss_streak_trigger"), 3))),
        "threshold_step_pct": max(1, min(5, _safe_int(oc.get("threshold_step_pct"), 2))),
        "minute_step": max(1, min(5, _safe_int(oc.get("minute_step"), 2))),
        "lab_a_min_minutes_left": max(0, min(30, _safe_int(oc.get("lab_a_min_minutes_left"), 5))),
    }


def _settled_lab_n(trades: list[dict[str, Any]]) -> int:
    return len(
        [
            t
            for t in trades
            if str(t.get("status") or "").lower() == "settled" and t.get("pnl_cents") is not None
        ]
    )


def _set_next_tick_preview(
    oc: dict[str, Any],
    cfg: dict[str, Any],
    *,
    lab_settled_n: int,
    profitable_n: int,
    tr_b: list[dict[str, Any]],
    tr_c: list[dict[str, Any]],
    tr_d: list[dict[str, Any]],
) -> None:
    lab = cfg.get("lab_a") if isinstance(cfg.get("lab_a"), dict) else {}
    floor = max(1, min(99, _safe_int(oc.get("lab_a_yes_floor_pct"), 57)))
    trig = max(1, min(12, _safe_int(oc.get("loss_streak_trigger"), 3)))
    try:
        frac = float(lab.get("balance_fraction_per_window") or cfg.get("balance_fraction_per_window") or 0.03)
    except (TypeError, ValueError):
        frac = 0.03
    sched = bool(oc.get("enabled"))
    adapt = bool(oc.get("adaptive_enabled", True))
    nb = _settled_lab_n(tr_b)
    nc = _settled_lab_n(tr_c)
    nd = _settled_lab_n(tr_d)
    b_on = bool(oc.get("lab_b_enabled", True))
    c_on = bool(oc.get("lab_c_enabled", True))
    d_on = bool(oc.get("lab_d_enabled", True))
    b_style = str(oc.get("lab_b_style") or "conservative").strip()
    c_style = str(oc.get("lab_c_style") or "aggressive").strip()
    d_style = str(oc.get("lab_d_style") or "wild").strip()
    base = (
        f"Next tick: Lab A has {lab_settled_n} settled (≥{profitable_n} wins in guard window). "
        f"Internal pulse watches up to {trig} losses entered near ≥{floor}% implied YES—tighten rules when replay-PnL improves. "
        f"Bet fraction is ~{frac:.2%}/window. Adaptive={'on' if adapt else 'off'}, Claude scheduler={'on' if sched else 'off'}. "
        f"B/C/D same lookback (reference arms; pulse does not persist their rules/bets): "
        f"B {'on' if b_on else 'off'} ({b_style}, {nb} settled), C {'on' if c_on else 'off'} ({c_style}, {nc} settled), "
        f"D {'on' if d_on else 'off'} ({d_style}, {nd} settled). Claude sees all four labs; adaptive writes Lab A only."
    )
    oc["next_tick_preview"] = base[:900]


def _apply_adaptive_lab_tuning(
    *,
    cfg: dict[str, Any],
    oc: dict[str, Any],
    branch: str,
    trades: list[dict[str, Any]],
    signals: list[dict[str, Any]],
    at_iso: str,
) -> dict[str, Any] | None:
    if not bool(oc.get("adaptive_enabled", True)):
        return None
    # Staging only: adaptive rule/threshold tuning persists on Lab A; B/C stay fixed reference arms.
    if branch != BRANCH_LAB_A or not bool(oc.get("lab_a_enabled", True)):
        return None
    settled = [t for t in trades if str(t.get("status") or "").lower() == "settled" and t.get("pnl_cents") is not None]
    min_tr = max(2, _safe_int(oc.get("min_trades_for_optimize"), 8))
    min_prof = max(0, _safe_int(oc.get("min_profitable_trades"), 2))
    if len(settled) < min_tr:
        return None
    profitable_n = sum(1 for t in settled if int(t.get("pnl_cents") or 0) > 0)
    if profitable_n < min_prof:
        return None

    sig_idx = _index_signals_by_ticker(signals)
    floor_key = "lab_a_yes_floor_pct"
    mins_key = "lab_a_min_minutes_left"
    cur_floor = max(1, min(99, _safe_int(oc.get(floor_key), 57)))
    cur_mins = max(0, _safe_int(oc.get(mins_key), 5))
    step_pct = max(1, min(5, _safe_int(oc.get("threshold_step_pct"), 1)))
    step_m = max(1, min(5, _safe_int(oc.get("minute_step"), 1)))
    loss_trigger = max(1, min(12, _safe_int(oc.get("loss_streak_trigger"), 1)))
    style = _branch_style(oc, branch)

    losses_at_threshold = _count_losses_at_or_above_yes_floor(settled, sig_idx, yes_floor_pct=cur_floor)

    if losses_at_threshold < loss_trigger:
        return None

    before_floor = cur_floor
    before_mins = cur_mins
    lab_base0, _rules0 = _ensure_lab_rules(cfg, branch)
    try:
        bf0 = float(lab_base0.get("balance_fraction_per_window") or cfg.get("balance_fraction_per_window") or 0.03)
    except (TypeError, ValueError):
        bf0 = 0.03
    if style == "conservative":
        cur_floor = min(95, cur_floor + step_pct)
        cur_mins = min(30, cur_mins + step_m)
    elif style == "aggressive":
        cur_floor = max(45, cur_floor - step_pct)
        cur_mins = max(0, cur_mins - step_m)
    else:
        half_p = max(1, int(round(step_pct / 2)))
        half_m = max(1, int(round(step_m / 2)))
        cur_floor = min(95, cur_floor + half_p)
        cur_mins = min(30, cur_mins + half_m)

    if cur_floor == before_floor and cur_mins == before_mins:
        return None

    lab_base, rules_base = _ensure_lab_rules(cfg, branch)
    proposed_rules = _apply_rule_thresholds(
        rules_base, yes_floor_pct=cur_floor, min_minutes_left=cur_mins, style=style
    )
    if bool(oc.get("backtest_proposals", True)):
        sig_desc = _signals_sorted_desc(signals)
        fee_flag = bool(oc.get("include_fees_in_score", True))
        rok = _replay_open_kw(cfg, at_iso=at_iso, branch=branch, trades=trades)
        base_fb = _replay_fitness_bundle(
            settled,
            rules_base,
            sig_desc,
            include_fees_in_score=fee_flag,
            max_rows=200,
            branch_trading_cfg=lab_base,
            **rok,
        )
        new_fb = _replay_fitness_bundle(
            settled,
            proposed_rules,
            sig_desc,
            include_fees_in_score=fee_flag,
            max_rows=200,
            branch_trading_cfg=lab_base,
            **rok,
        )
        if float(new_fb["score_dollars"]) <= float(base_fb["score_dollars"]) and not bool(
            oc.get("adaptive_skip_backtest_gate", False)
        ):
            logger.info(
                "adaptive_lab_tuning_rejected: fitness did not improve (score %.4f -> %.4f)",
                float(base_fb["score_dollars"]),
                float(new_fb["score_dollars"]),
            )
            return None

    lab = dict(lab_base)
    lab["rules"] = proposed_rules
    lk = _lab_key_for_branch(branch) or "lab_a"
    cfg[lk] = lab
    oc[floor_key] = cur_floor
    oc[mins_key] = cur_mins
    reason = f"{losses_at_threshold} losing settled trades at/above {before_floor}% YES threshold"
    try:
        bf1 = float(lab.get("balance_fraction_per_window") or cfg.get("balance_fraction_per_window") or 0.03)
    except (TypeError, ValueError):
        bf1 = bf0
    hint = (
        f"Loss streak vs {before_floor}% floor: rules tighten to YES floor {cur_floor}% and ≥{cur_mins}m left "
        f"(backtest gate passed). Bet fraction unchanged at ~{bf1:.2%} unless a separate pulse moves it."
    )
    bc = _optimizer_pulse_bc_enrichment(cfg, oc)
    return _history_item(
        at_iso=at_iso,
        branch=branch,
        style=style,
        reason=reason,
        before_floor=before_floor,
        after_floor=cur_floor,
        before_minm=before_mins,
        after_minm=cur_mins,
        before_extra={"balance_fraction_per_window": round(bf0, 4)},
        after_extra={**bc, "balance_fraction_per_window": round(bf1, 4)},
        tick_hint=hint[:500],
    )


def _apply_adaptive_win_relax_lab_a(
    *,
    cfg: dict[str, Any],
    oc: dict[str, Any],
    trades: list[dict[str, Any]],
    signals: list[dict[str, Any]],
    at_iso: str,
) -> dict[str, Any] | None:
    """When there are no threshold-tagged losses but short-run Lab A PnL is positive, ease YES floor if replay improves."""
    if not bool(oc.get("adaptive_enabled", True)):
        return None
    if not bool(oc.get("lab_a_enabled", True)):
        return None
    settled = [t for t in trades if str(t.get("status") or "").lower() == "settled" and t.get("pnl_cents") is not None]
    min_tr = max(2, _safe_int(oc.get("min_trades_for_optimize"), 8))
    min_prof = max(0, _safe_int(oc.get("min_profitable_trades"), 2))
    if len(settled) < min_tr:
        return None
    profitable_n = sum(1 for t in settled if int(t.get("pnl_cents") or 0) > 0)
    if profitable_n < min_prof:
        return None

    sig_idx = _index_signals_by_ticker(signals)
    floor_key = "lab_a_yes_floor_pct"
    mins_key = "lab_a_min_minutes_left"
    cur_floor = max(1, min(99, _safe_int(oc.get(floor_key), 57)))
    cur_mins = max(0, _safe_int(oc.get(mins_key), 5))
    step_pct = max(1, min(5, _safe_int(oc.get("threshold_step_pct"), 1)))
    step_m = max(1, min(5, _safe_int(oc.get("minute_step"), 1)))
    loss_trigger = max(1, min(12, _safe_int(oc.get("loss_streak_trigger"), 1)))
    style = _branch_style(oc, BRANCH_LAB_A)

    losses_at_threshold = _count_losses_at_or_above_yes_floor(settled, sig_idx, yes_floor_pct=cur_floor)
    if losses_at_threshold > 0:
        return None

    tail = settled[:18]
    if len(tail) < 8:
        return None
    mean_pnl = sum(int(t.get("pnl_cents") or 0) for t in tail) / max(1, len(tail))
    if mean_pnl <= 0:
        return None

    before_floor = cur_floor
    before_mins = cur_mins
    lab_base, rules_base = _ensure_lab_rules(cfg, BRANCH_LAB_A)
    try:
        bf0 = float(lab_base.get("balance_fraction_per_window") or cfg.get("balance_fraction_per_window") or 0.03)
    except (TypeError, ValueError):
        bf0 = 0.03

    if style == "conservative":
        return None
    if style == "aggressive":
        cur_floor = max(45, cur_floor - step_pct)
        cur_mins = max(0, cur_mins - step_m)
    else:
        half_p = max(1, int(round(step_pct / 2)))
        half_m = max(1, int(round(step_m / 2)))
        cur_floor = max(45, cur_floor - half_p)
        cur_mins = max(0, cur_mins - half_m)

    if cur_floor == before_floor and cur_mins == before_mins:
        return None

    proposed_rules = _apply_rule_thresholds(
        rules_base, yes_floor_pct=cur_floor, min_minutes_left=cur_mins, style=style
    )
    if bool(oc.get("backtest_proposals", True)):
        sig_desc = _signals_sorted_desc(signals)
        fee_flag = bool(oc.get("include_fees_in_score", True))
        rok = _replay_open_kw(cfg, at_iso=at_iso, branch=BRANCH_LAB_A, trades=trades)
        base_fb = _replay_fitness_bundle(
            settled,
            rules_base,
            sig_desc,
            include_fees_in_score=fee_flag,
            max_rows=200,
            branch_trading_cfg=lab_base,
            **rok,
        )
        new_fb = _replay_fitness_bundle(
            settled,
            proposed_rules,
            sig_desc,
            include_fees_in_score=fee_flag,
            max_rows=200,
            branch_trading_cfg=lab_base,
            **rok,
        )
        if float(new_fb["score_dollars"]) <= float(base_fb["score_dollars"]) and not bool(
            oc.get("adaptive_skip_backtest_gate", False)
        ):
            logger.info(
                "adaptive_win_relax_rejected: fitness did not improve (score %.4f -> %.4f)",
                float(base_fb["score_dollars"]),
                float(new_fb["score_dollars"]),
            )
            return None

    lab = dict(lab_base)
    lab["rules"] = proposed_rules
    cfg["lab_a"] = lab
    oc[floor_key] = cur_floor
    oc[mins_key] = cur_mins
    try:
        bf1 = float(lab.get("balance_fraction_per_window") or cfg.get("balance_fraction_per_window") or 0.03)
    except (TypeError, ValueError):
        bf1 = bf0
    reason = (
        f"Win momentum (mean {mean_pnl:.0f}¢/trade over last {len(tail)}); no ≥{loss_trigger} losses at {before_floor}% floor"
    )
    hint = (
        f"Regime shift (win path): eased YES floor {before_floor}%→{cur_floor}% after positive short-run PnL; "
        f"next tick still watches for {loss_trigger} losses at the new floor before tightening again."
    )
    bc = _optimizer_pulse_bc_enrichment(cfg, oc)
    return _history_item(
        at_iso=at_iso,
        branch=BRANCH_LAB_A,
        style="win_relax",
        reason=reason,
        before_floor=before_floor,
        after_floor=cur_floor,
        before_minm=before_mins,
        after_minm=cur_mins,
        before_extra={"balance_fraction_per_window": round(bf0, 4)},
        after_extra={**bc, "balance_fraction_per_window": round(bf1, 4)},
        tick_hint=hint[:500],
    )


def _internal_lab_a_bet_pulse(
    *,
    cfg: dict[str, Any],
    oc: dict[str, Any],
    tr_a: list[dict[str, Any]],
    tr_b: list[dict[str, Any]],
    tr_c: list[dict[str, Any]],
    tr_d: list[dict[str, Any]],
    sg_a: list[dict[str, Any]],
    eq_a: list[dict[str, Any]],
    at_iso: str,
) -> dict[str, Any] | None:
    """
    Proactive Lab A fraction pulse driven by:
    - replay composite fitness on recent settled rows,
    - recent fitness trend from internal trace,
    - equity slope ($/hour),
    - regime volatility bucket (high-vol shrinks adjustments).
    """
    if not bool(oc.get("optimize_bet_size", True)):
        return None
    min_tr = max(2, _safe_int(oc.get("min_trades_for_optimize"), 8))
    min_prof = max(0, _safe_int(oc.get("min_profitable_trades"), 2))
    st_a = [t for t in tr_a if str(t.get("status") or "").lower() == "settled" and t.get("pnl_cents") is not None]
    st_b = [t for t in tr_b if str(t.get("status") or "").lower() == "settled" and t.get("pnl_cents") is not None]
    st_c = [t for t in tr_c if str(t.get("status") or "").lower() == "settled" and t.get("pnl_cents") is not None]
    st_d = [t for t in tr_d if str(t.get("status") or "").lower() == "settled" and t.get("pnl_cents") is not None]
    if len(st_a) + len(st_b) + len(st_c) + len(st_d) < min_tr:
        return None
    prof = (
        sum(1 for t in st_a if int(t.get("pnl_cents") or 0) > 0)
        + sum(1 for t in st_b if int(t.get("pnl_cents") or 0) > 0)
        + sum(1 for t in st_c if int(t.get("pnl_cents") or 0) > 0)
        + sum(1 for t in st_d if int(t.get("pnl_cents") or 0) > 0)
    )
    if prof < min_prof:
        return None

    _sync_regime_rule_families_to_lab_a(cfg, oc, sg_a, st_a, at_iso)
    lab_base, rules_a = _ensure_lab_rules(cfg, BRANCH_LAB_A)
    try:
        old_f = float(lab_base.get("balance_fraction_per_window") or cfg.get("balance_fraction_per_window") or 0.03)
    except (TypeError, ValueError):
        old_f = 0.03

    window = st_a[:48]
    if len(window) < 4:
        return None
    pnl = sum(int(t.get("pnl_cents") or 0) for t in window) / max(1, len(window))
    sig_desc = _signals_sorted_desc(sg_a)
    fee_flag = bool(oc.get("include_fees_in_score", True))
    rok = _replay_open_kw(cfg, at_iso=at_iso, branch=BRANCH_LAB_A, trades=tr_a)
    fb = _replay_fitness_bundle(
        window,
        rules_a,
        sig_desc,
        include_fees_in_score=fee_flag,
        max_rows=40,
        branch_trading_cfg=lab_base,
        **rok,
    )
    matched_n = int(fb.get("matched_n") or 0)
    fitness_score = float(fb.get("score_dollars") or 0.0)
    sl_rate = float(fb.get("stop_loss_trigger_rate") or 0.0)
    regime_h = max(1.0, float(oc.get("regime_lookback_hours") or 4))
    regime = _regime_volatility(sg_a, hours=regime_h, end=_parse_iso_dt(at_iso) or _utc_now())
    regime_bucket = str(regime.get("bucket") or "unknown")
    # High-vol cuts aggressiveness; low-vol allows slightly larger nudges.
    regime_mult = 0.65 if regime_bucket == "high_vol" else 1.15 if regime_bucket == "low_vol" else 1.0
    eq_slope = _equity_slope_dollars_per_hour(eq_a) or 0.0
    trace_rows = oc.get("internal_optimizer_trace")
    trace_list = trace_rows if isinstance(trace_rows, list) else []
    fitness_slope = _fitness_score_trend_from_trace(trace_list, max_rows=20) or 0.0
    eq_slope_streak = _trace_positive_equity_slope_streak(oc)
    momentum_ok = eq_slope_streak >= 3
    base_drive = fitness_score if matched_n >= 2 else (pnl / 100.0)
    drive = base_drive + (eq_slope * 0.05) + (fitness_slope * 3.0)
    # Dynamic pulse size grows with trend confidence but stays capped by global min/max fractions.
    mag = min(1.6, max(0.35, abs(drive) / 6.0))
    step = 0.0022 * regime_mult * mag
    if sl_rate > 40.0:
        if drive < 0:
            step *= 1.55
        elif drive > 0:
            step *= 0.55
    elif momentum_ok and drive > 0:
        step *= 1.08
    if drive > 0:
        new_f = min(MAX_BALANCE_FRACTION_PER_WINDOW, old_f + step)
    elif drive < 0:
        new_f = max(MIN_BALANCE_FRACTION_PER_WINDOW, old_f - step)
    else:
        return None
    new_f = round(float(new_f), 4)
    if abs(new_f - old_f) < 0.0004:
        return None

    lab = dict(lab_base)
    lab["balance_fraction_per_window"] = new_f
    lab["optimizer_note"] = (
        f"internal_pulse score={fitness_score:.3f} matched={matched_n} mean_pnl_cents={pnl:.1f} -> fraction={new_f}"
    )
    cfg["lab_a"] = lab
    mom_note = f"momentum_streak={eq_slope_streak} (need≥3 for +8% step on increases)" if not momentum_ok else "momentum_ok≥3 +8% step on increases"
    sl_note = f"stop_loss_rate={sl_rate:.1f}% (>40% tightens shrink / damps adds)" if sl_rate > 40.0 else f"stop_loss_rate={sl_rate:.1f}%"
    reason = (
        f"internal pulse: fitness={fitness_score:.3f}, trend={fitness_slope:+.3f}/cycle, "
        f"equity_slope={eq_slope:+.2f}$/h, {mom_note}, {sl_note}, regime={regime_bucket}, mean={pnl:.0f}¢, matched={matched_n}"
    )
    logger.info(
        "internal_lab_a_bet_pulse regime: drive=%.4f step=%.5f old_f=%.4f new_f=%.4f regime=%s sl_rate=%.1f%% eq_slope_streak=%s momentum=%s",
        drive,
        step,
        old_f,
        new_f,
        regime_bucket,
        sl_rate,
        eq_slope_streak,
        momentum_ok,
    )
    hint = (
        f"Next tick uses bet fraction ~{new_f:.2%} of Lab A paper per window (was ~{old_f:.2%}). "
        f"Pulse scales with replay fitness, equity slope, and trace momentum; stop-loss-heavy replay (>40%) "
        f"shrinks increases and deepens decreases; high-vol regime reduces base step."
    )
    bc = _optimizer_pulse_bc_enrichment(cfg, oc)
    item = _history_bet_item(
        at_iso=at_iso,
        branch=BRANCH_LAB_A,
        reason=reason,
        before_f=old_f,
        after_f=new_f,
        after_extra={
            **bc,
            "yes_floor_pct": max(1, min(99, _safe_int(oc.get("lab_a_yes_floor_pct"), 57))),
        },
    )
    item["tick_hint"] = hint[:500]
    return item


def _history_bet_item(
    *,
    at_iso: str,
    branch: str,
    reason: str,
    before_f: float,
    after_f: float,
    after_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    lab = "Lab A" if branch == BRANCH_LAB_A else "Lab B" if branch == BRANCH_LAB_B else "Lab C"
    after: dict[str, Any] = {"balance_fraction_per_window": after_f}
    if after_extra:
        after.update(after_extra)
    return {
        "id": uuid4().hex,
        "created_at": at_iso,
        "branch": branch,
        "lab_label": lab,
        "style": "bet_size",
        "reason": reason,
        "summary": f"{lab}: balance_fraction_per_window {before_f:.4f} -> {after_f:.4f}",
        "before": {"balance_fraction_per_window": before_f},
        "after": after,
    }


def _internal_mutate_rules_and_params(
    *,
    cfg: dict[str, Any],
    oc: dict[str, Any],
    st_a: list[dict[str, Any]],
    st_b: list[dict[str, Any]],
    st_c: list[dict[str, Any]],
    st_d: list[dict[str, Any]],
    sg_a: list[dict[str, Any]],
    sg_b: list[dict[str, Any]],
    sg_c: list[dict[str, Any]],
    sg_d: list[dict[str, Any]],
    at_iso: str,
    tr_a: list[dict[str, Any]] | None = None,
    tr_b: list[dict[str, Any]] | None = None,
    tr_c: list[dict[str, Any]] | None = None,
    tr_d: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """
    Internal mutant cycle: deterministic + random perturbations to Lab A rules/sizing.

    Applies only when replay fitness improves and statistical gate vs B/C/D passes.
    Returns ``(history_row_or_none, meta)``.
    """
    meta: dict[str, Any] = {"accepted": False, "mutant_run": True, "reject_reason": ""}
    if not bool(oc.get("optimize_internal_mutations", True)):
        meta["reject_reason"] = "mutations_disabled"
        return None, meta
    if len(st_a) < max(8, int(oc.get("min_trades_for_optimize") or 8)):
        meta["reject_reason"] = "insufficient_lab_a_settled"
        return None, meta
    _sync_regime_rule_families_to_lab_a(cfg, oc, sg_a, st_a, at_iso)
    lab_a, rules_base = _ensure_lab_rules(cfg, BRANCH_LAB_A)
    if not rules_base:
        meta["reject_reason"] = "no_rules"
        return None, meta
    sig_a = _signals_sorted_desc(sg_a)
    fee_flag = bool(oc.get("include_fees_in_score", True))
    tail_n = 120
    rk_a = _replay_open_kw(cfg, at_iso=at_iso, branch=BRANCH_LAB_A, trades=tr_a)
    base_fb = _replay_fitness_bundle(
        st_a[:tail_n],
        rules_base,
        sig_a,
        include_fees_in_score=fee_flag,
        max_rows=tail_n,
        branch_trading_cfg=lab_a,
        **rk_a,
    )
    meta["score_before"] = float(base_fb["score_dollars"])
    eff, tier_label = _compute_mutation_scale(oc)
    was_plr = bool(oc.get("paper_loser_radical_next", False))
    rad0 = _radical_exploration_active(oc) or was_plr
    if rad0:
        eff = min(1.75, eff * 2.0)
    if was_plr:
        oc["paper_loser_radical_next"] = False
        logger.warning("Paper-loser strategy swap: one-shot radical exploration scale (forced).")
    elif rad0:
        logger.warning(
            "RADICAL EXPLORATION triggered — deep stuck state (red_streak=%d, low_acc_cycles=%d, acc=%.1f%%)",
            int(oc.get("optimizer_red_streak_cycles", 0) or 0),
            int(oc.get("optimizer_consecutive_low_acceptance_cycles", 0) or 0),
            _safe_float(oc.get("acceptance_rate_pct", 0.0), 0.0),
        )
    meta["mutation_tier"] = tier_label
    meta["radical"] = bool(rad0)
    meta["effective_mutation_scale"] = round(eff, 4)
    cyc = max(1, _safe_int(oc.get("optimizer_cycle_count"), 1))
    rng = random.Random(cyc * 997 + len(st_a) * 17 + len(sg_a))
    drift = max(-0.03, min(0.03, float(base_fb["sharpe_approx"]) * 0.01 * min(1.25, eff)))
    span = max(1, min(4, int(round(eff * (1.4 if rad0 else 1.0)))))
    prob_span = 0.015 * eff
    mutated_rules: list[dict[str, Any]] = []
    for i, r in enumerate(rules_base):
        nr = dict(r)
        side = str(nr.get("side") or "yes").strip().lower()
        if side == "no":
            mutated_rules.append(nr)
            continue
        jitter_prob = rng.uniform(-prob_span, prob_span) + drift
        jitter_mins = rng.randint(-span, span)
        lo = max(0.01, min(0.99, _safe_float(nr.get("min_prob"), 0.0) + jitter_prob))
        hi = max(lo + 0.005, min(0.995, _safe_float(nr.get("max_prob"), 1.0) + jitter_prob))
        minm = max(0, min(60, _safe_int(nr.get("min_minutes_left"), 0) + jitter_mins))
        maxm = max(minm, min(120, _safe_int(nr.get("max_minutes_left"), 60) + jitter_mins))
        nr["min_prob"] = round(lo, 4)
        nr["max_prob"] = round(hi, 4)
        nr["min_minutes_left"] = int(minm)
        nr["max_minutes_left"] = int(maxm)
        if i == 0:
            nr["name"] = f"{str(nr.get('name') or 'rule')[:48]} · m{cyc}"
        mutated_rules.append(nr)
    if rad0 and len(mutated_rules) < 24 and rng.random() < 0.3:
        seed0 = next((r for r in rules_base if str(r.get("side") or "yes").lower() != "no"), None) or (rules_base[0] if rules_base else None)
        if seed0 and isinstance(seed0, dict):
            nbr = dict(seed0)
            nbr["name"] = f"radical-explore-{rng.randint(0, 9999)}-m{cyc}"[:56]
            lo0 = _safe_float(nbr.get("min_prob"), 0.5) - 0.04
            hi0 = _safe_float(nbr.get("max_prob"), 0.6) + 0.04
            nbr["min_prob"] = round(max(0.01, min(0.99, lo0)), 4)
            nbr["max_prob"] = round(max(nbr["min_prob"] + 0.01, min(0.99, hi0)), 4)
            mutated_rules.append(nbr)
    deepx = (int(oc.get("optimizer_red_streak_cycles", 0) or 0) >= 20) or (
        int(oc.get("optimizer_consecutive_low_acceptance_cycles", 0) or 0) >= 4
        and _safe_float(oc.get("acceptance_rate_pct", 100.0), 100.0) < 15.0
    )
    if rad0 and not was_plr and deepx and len(mutated_rules) < (MAX_LAB_A_RULES_AFTER_CLAUDE_DELTAS - 1):
        _append_radical_fresh_rules(
            mutated_rules, rng, cyc=cyc, deep=True, max_rules=MAX_LAB_A_RULES_AFTER_CLAUDE_DELTAS
        )
    try:
        mutated_rules = normalize_rules_list(mutated_rules)
    except Exception as e:
        meta["reject_reason"] = f"normalize_failed:{e}"
        return None, meta
    old_f = clamp_balance_fraction_per_window(
        _safe_float(lab_a.get("balance_fraction_per_window"), _safe_float(cfg.get("balance_fraction_per_window"), 0.03))
    )
    frac_span = 0.0035 * eff * (1.6 if rad0 else 1.0)
    frac_step = rng.uniform(-frac_span, frac_span) + drift * 0.35 * min(1.2, eff)
    new_f = clamp_balance_fraction_per_window(old_f + frac_step)
    mut_lab = dict(lab_a)
    mut_lab["balance_fraction_per_window"] = round(new_f, 4)
    rk_m = _replay_open_kw(cfg, at_iso=at_iso, branch=BRANCH_LAB_A, trades=tr_a)
    prop_fb = _replay_fitness_bundle(
        st_a[:tail_n],
        mutated_rules,
        sig_a,
        include_fees_in_score=fee_flag,
        max_rows=tail_n,
        branch_trading_cfg=mut_lab,
        **rk_m,
    )
    meta["score_after"] = float(prop_fb["score_dollars"])
    if meta["score_after"] <= meta["score_before"]:
        meta["reject_reason"] = "fitness_not_improved"
        return None, meta
    def _tail_fb(
        st: list[dict[str, Any]], sg: list[dict[str, Any]], br: str, tr_all: list[dict[str, Any]] | None
    ) -> dict[str, Any]:
        _, r = _ensure_lab_rules(cfg, br)
        lk = _lab_key_for_branch(br) or "lab_a"
        lb = cfg.get(lk) if isinstance(cfg.get(lk), dict) else {}
        rko = _replay_open_kw(cfg, at_iso=at_iso, branch=br, trades=tr_all)
        return _replay_fitness_bundle(
            st[:tail_n],
            r,
            _signals_sorted_desc(sg),
            include_fees_in_score=fee_flag,
            max_rows=tail_n,
            branch_trading_cfg=lb,
            **rko,
        )
    fb_b = _tail_fb(st_b, sg_b, BRANCH_LAB_B, tr_b)
    fb_c = _tail_fb(st_c, sg_c, BRANCH_LAB_C, tr_c)
    fb_d = _tail_fb(st_d, sg_d, BRANCH_LAB_D, tr_d)
    a_d = [x / 100.0 for x in prop_fb["per_trade_pnl_cents_chrono"]]
    ctrl_d = (
        [x / 100.0 for x in fb_b["per_trade_pnl_cents_chrono"]]
        + [x / 100.0 for x in fb_c["per_trade_pnl_cents_chrono"]]
        + [x / 100.0 for x in fb_d["per_trade_pnl_cents_chrono"]]
    )
    ctrl_scores = [float(fb_b["score_dollars"]), float(fb_c["score_dollars"]), float(fb_d["score_dollars"])]
    stat_ok, stat_detail = is_statistically_better(a_d, ctrl_d, lab_a_score=meta["score_after"], control_scores=ctrl_scores)
    meta["statistical_detail"] = stat_detail
    if not stat_ok:
        meta["reject_reason"] = "statistical_gate_failed"
        return None, meta
    mut_lab["rules"] = mutated_rules
    rlk2 = _regime_to_rules_list_key(
        str(
            (mut_lab.get("active_regime") or (cfg.get("lab_a") or {}).get("active_regime") or "low_vol")
        )
    )
    mut_lab[rlk2] = mutated_rules
    mut_lab["optimizer_note"] = f"internal_mutation cycle={cyc} score={meta['score_before']:.3f}->{meta['score_after']:.3f}"
    cfg["lab_a"] = mut_lab
    oc["last_mutation_at"] = at_iso
    meta["accepted"] = True
    logger.info(
        "internal_mutation accepted: tier=%s effective_scale=%.4f score %.4f->%.4f rules=%s",
        tier_label,
        eff,
        float(meta["score_before"]),
        float(meta["score_after"]),
        len(mutated_rules),
    )
    meta["reject_reason"] = ""
    row = {
        "id": uuid4().hex,
        "created_at": at_iso,
        "branch": BRANCH_LAB_A,
        "lab_label": "Lab A",
        "style": "internal_mutation",
        "reason": "mutant cycle accepted via replay + statistical gates",
        "summary": (
            f"Lab A mutant cycle: score {meta['score_before']:.3f}->{meta['score_after']:.3f}, "
            f"fraction {old_f:.4f}->{new_f:.4f}, rules={len(mutated_rules)}"
        )[:400],
        "before": {"score": meta["score_before"], "balance_fraction_per_window": old_f, "rules_count": len(rules_base)},
        "after": {"score": meta["score_after"], "balance_fraction_per_window": round(new_f, 4), "rules_count": len(mutated_rules)},
    }
    return row, meta


def _apply_claude_bet_recommendations(
    *,
    cfg: dict[str, Any],
    oc: dict[str, Any],
    rec: dict[str, Any],
    tr_a: list[dict[str, Any]],
    tr_b: list[dict[str, Any]],
    tr_c: list[dict[str, Any]],
    tr_d: list[dict[str, Any]],
    at_iso: str,
) -> list[dict[str, Any]]:
    """Apply balance_fraction hints for Lab A staging only; B/C/D are read-only in the model output."""
    if not bool(oc.get("optimize_bet_size", True)):
        return []
    min_tr = max(2, _safe_int(oc.get("min_trades_for_optimize"), 8))
    min_prof = max(0, _safe_int(oc.get("min_profitable_trades"), 2))
    st_a = [t for t in tr_a if str(t.get("status") or "").lower() == "settled" and t.get("pnl_cents") is not None]
    st_b = [t for t in tr_b if str(t.get("status") or "").lower() == "settled" and t.get("pnl_cents") is not None]
    st_c = [t for t in tr_c if str(t.get("status") or "").lower() == "settled" and t.get("pnl_cents") is not None]
    st_d = [t for t in tr_d if str(t.get("status") or "").lower() == "settled" and t.get("pnl_cents") is not None]
    if len(st_a) + len(st_b) + len(st_c) + len(st_d) < min_tr:
        return []
    prof = (
        sum(1 for t in st_a if int(t.get("pnl_cents") or 0) > 0)
        + sum(1 for t in st_b if int(t.get("pnl_cents") or 0) > 0)
        + sum(1 for t in st_c if int(t.get("pnl_cents") or 0) > 0)
        + sum(1 for t in st_d if int(t.get("pnl_cents") or 0) > 0)
    )
    if prof < min_prof:
        return []
    out_hist: list[dict[str, Any]] = []
    recs = rec.get("recommendations")
    if not isinstance(recs, list):
        return []
    for item in recs:
        if not isinstance(item, dict):
            continue
        tgt = str(item.get("target") or "").strip().lower()
        field = str(item.get("field") or "").strip().lower()
        if field != "balance_fraction_per_window":
            continue
        if tgt != "lab_a":
            continue
        sug = item.get("suggested")
        new_f = _safe_float(sug, -1.0)
        if new_f < 0:
            continue
        new_f = clamp_balance_fraction_per_window(new_f)
        lab_raw = cfg.get("lab_a")
        lab = dict(lab_raw) if isinstance(lab_raw, dict) else {}
        old_f = _safe_float(lab.get("balance_fraction_per_window"), 0.05)
        if abs(new_f - old_f) < 0.0004:
            continue
        lab["balance_fraction_per_window"] = round(new_f, 4)
        cfg["lab_a"] = lab
        br = BRANCH_LAB_A
        bc = _optimizer_pulse_bc_enrichment(cfg, oc)
        out_hist.append(
            _history_bet_item(
                at_iso=at_iso,
                branch=br,
                reason=str(item.get("reason") or "claude_recommendation")[:500],
                before_f=old_f,
                after_f=new_f,
                after_extra={
                    **bc,
                    "yes_floor_pct": max(1, min(99, _safe_int(oc.get("lab_a_yes_floor_pct"), 57))),
                },
            )
        )
    return out_hist


def _apply_claude_lab_parameter_patch(
    *,
    cfg: dict[str, Any],
    oc: dict[str, Any],
    parsed: ClaudeOptimizerResponse,
    at_iso: str,
) -> list[dict[str, Any]]:
    """Apply optional Lab A scalar patch from Claude (window / bet fraction)."""
    patch = parsed.lab_parameter_patch
    if patch is None:
        return []
    out_hist: list[dict[str, Any]] = []
    lab_raw = cfg.get("lab_a")
    lab = dict(lab_raw) if isinstance(lab_raw, dict) else {}
    if patch.balance_fraction_per_window is not None:
        new_f = clamp_balance_fraction_per_window(float(patch.balance_fraction_per_window))
        try:
            old_f = float(lab.get("balance_fraction_per_window") or cfg.get("balance_fraction_per_window") or 0.03)
        except (TypeError, ValueError):
            old_f = 0.03
        if abs(new_f - old_f) >= 0.0004:
            lab["balance_fraction_per_window"] = round(new_f, 4)
            bc = _optimizer_pulse_bc_enrichment(cfg, oc)
            out_hist.append(
                _history_bet_item(
                    at_iso=at_iso,
                    branch=BRANCH_LAB_A,
                    reason="claude_lab_parameter_patch.balance_fraction_per_window",
                    before_f=old_f,
                    after_f=new_f,
                    after_extra={
                        **bc,
                        "yes_floor_pct": max(1, min(99, _safe_int(oc.get("lab_a_yes_floor_pct"), 57))),
                    },
                )
            )
    if patch.window_minutes is not None:
        try:
            wm = int(patch.window_minutes)
        except (TypeError, ValueError):
            wm = None
        if wm is not None:
            wm = max(1, min(1440, wm))
            try:
                old_w = int(lab.get("window_minutes") or cfg.get("window_minutes") or 15)
            except (TypeError, ValueError):
                old_w = 15
            if wm != old_w:
                lab["window_minutes"] = wm
                out_hist.append(
                    {
                        "id": uuid4().hex,
                        "created_at": at_iso,
                        "branch": BRANCH_LAB_A,
                        "lab_label": "Lab A",
                        "style": "claude_window",
                        "reason": "claude_lab_parameter_patch.window_minutes",
                        "summary": f"Lab A: window_minutes {old_w} -> {wm}",
                        "before": {"window_minutes": old_w},
                        "after": {"window_minutes": wm},
                    }
                )
    if out_hist:
        cfg["lab_a"] = lab
    return out_hist


def _settled_trade_examples_for_prompt(st_a: list[dict[str, Any]], *, n: int = 5) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for t in st_a[: max(1, n)]:
        ex: dict[str, Any] = {}
        try:
            ex = json.loads(str(t.get("extra_json") or "{}"))
        except Exception:
            ex = {}
        out.append(
            {
                "ticker": t.get("ticker"),
                "pnl_cents": t.get("pnl_cents"),
                "rule": ex.get("rule"),
                "entry_implied_yes": ex.get("entry_implied_yes"),
                "created_at": t.get("created_at"),
            }
        )
    return out


def _mutant_optimizer_hints(oc: dict[str, Any]) -> dict[str, Any]:
    """Non-persisted jitter for exploration payload (mutant cycles)."""
    jf = random.randint(-2, 2)
    jm = random.randint(-1, 1)
    base_f = max(45, min(95, _safe_int(oc.get("lab_a_yes_floor_pct"), 57)))
    base_m = max(0, min(30, _safe_int(oc.get("lab_a_min_minutes_left"), 5)))
    return {
        "lab_a_yes_floor_pct_hint": max(45, min(95, base_f + jf)),
        "lab_a_min_minutes_left_hint": max(0, min(30, base_m + jm)),
        "noise_note": "hints_only_not_persisted",
    }


def _merge_rule_operations_from_claude(
    base_rules: list[dict[str, Any]], ops: list[Any]
) -> list[dict[str, Any]]:
    """
    Apply Claude ``rule_operations`` in a safe order: **all deletes first**, then patches/modifies, then adds.

    Processing in API order could delete a name that was just added in the same batch; deletes-first avoids that.
    """
    out: list[dict[str, Any]] = [dict(r) for r in base_rules if isinstance(r, dict)]
    deletes: list[Any] = []
    patches: list[Any] = []
    adds: list[Any] = []
    for raw in ops:
        op = str(getattr(raw, "op", "") or "").strip().lower()
        if op == "delete":
            deletes.append(raw)
        elif op in ("patch", "modify"):
            patches.append(raw)
        elif op == "add":
            adds.append(raw)

    for raw in deletes:
        name = str(getattr(raw, "rule_name", "") or "").strip()
        if name:
            out = [r for r in out if str(r.get("name") or "").strip() != name]
    for raw in patches:
        name = str(getattr(raw, "rule_name", "") or "").strip()
        payload = getattr(raw, "rule", None)
        if not isinstance(payload, dict):
            payload = {}
        if not name:
            continue
        for i, r in enumerate(out):
            if str(r.get("name") or "").strip() != name:
                continue
            merged = dict(r)
            for k, v in payload.items():
                merged[k] = v
            out[i] = merged
            break
    for raw in adds:
        payload = getattr(raw, "rule", None)
        if isinstance(payload, dict) and payload:
            out.append(dict(payload))
    return out


def apply_claude_rule_changes(
    *,
    cfg: dict[str, Any],
    oc: dict[str, Any],
    parsed: ClaudeOptimizerResponse,
    st_a: list[dict[str, Any]],
    sg_a: list[dict[str, Any]],
    st_b: list[dict[str, Any]],
    sg_b: list[dict[str, Any]],
    st_c: list[dict[str, Any]],
    sg_c: list[dict[str, Any]],
    st_d: list[dict[str, Any]],
    sg_d: list[dict[str, Any]],
    at_iso: str,
    mutant_run: bool,
    tr_a: list[dict[str, Any]] | None = None,
    tr_b: list[dict[str, Any]] | None = None,
    tr_c: list[dict[str, Any]] | None = None,
    tr_d: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Merge Claude ``rule_operations`` into Lab A after replay + statistical gate vs B/C/D tails.

    Returns ``(history_rows, meta)`` where meta includes accept/reject diagnostics for logging and UI trace.
    """
    meta: dict[str, Any] = {"accepted": False, "mutant_run": mutant_run}
    if not bool(oc.get("optimize_rules_with_claude", True)):
        meta["reject_reason"] = "optimize_rules_with_claude_disabled"
        logger.info("claude_rules_skipped: %s", meta["reject_reason"])
        return [], meta
    if not parsed.rule_operations:
        meta["reject_reason"] = "no_rule_operations"
        return [], meta

    lab_base, rules_base = _ensure_lab_rules(cfg, BRANCH_LAB_A)
    merged = _merge_rule_operations_from_claude(rules_base, parsed.rule_operations)
    if len(merged) > MAX_LAB_A_RULES_AFTER_CLAUDE_DELTAS:
        meta["reject_reason"] = f"rule_count_exceeds_cap_{MAX_LAB_A_RULES_AFTER_CLAUDE_DELTAS}"
        logger.info(
            "claude_rules_rejected: %s (len=%s)",
            meta["reject_reason"],
            len(merged),
        )
        return [], meta
    try:
        merged = normalize_rules_list(merged)
    except Exception as e:
        meta["reject_reason"] = f"normalize_failed:{e}"
        logger.warning("claude_rules_rejected: %s", meta["reject_reason"])
        return [], meta

    sig_a = _signals_sorted_desc(sg_a)
    fee_flag = bool(oc.get("include_fees_in_score", True))
    tail_n = max(40, min(160, _safe_int(oc.get("min_trades_for_optimize"), 8) * 5))
    a_tail = st_a[:tail_n]
    rk_cl = _replay_open_kw(cfg, at_iso=at_iso, branch=BRANCH_LAB_A, trades=tr_a)

    base_fb = _replay_fitness_bundle(
        a_tail,
        rules_base,
        sig_a,
        include_fees_in_score=fee_flag,
        max_rows=tail_n,
        branch_trading_cfg=lab_base,
        **rk_cl,
    )
    prop_fb = _replay_fitness_bundle(
        a_tail,
        merged,
        sig_a,
        include_fees_in_score=fee_flag,
        max_rows=tail_n,
        branch_trading_cfg=lab_base,
        **rk_cl,
    )
    meta["score_before"] = float(base_fb["score_dollars"])
    meta["score_after"] = float(prop_fb["score_dollars"])

    def _tail_fb(
        st: list[dict[str, Any]], sg: list[dict[str, Any]], br: str, tr_all: list[dict[str, Any]] | None
    ) -> dict[str, Any]:
        stx = [t for t in st if str(t.get("status") or "").lower() == "settled" and t.get("pnl_cents") is not None]
        _, rx = _ensure_lab_rules(cfg, br)
        lk = _lab_key_for_branch(br) or "lab_a"
        lab_sub = cfg.get(lk) if isinstance(cfg.get(lk), dict) else {}
        rko = _replay_open_kw(cfg, at_iso=at_iso, branch=br, trades=tr_all)
        return _replay_fitness_bundle(
            stx[:tail_n],
            rx,
            _signals_sorted_desc(sg),
            include_fees_in_score=fee_flag,
            max_rows=tail_n,
            branch_trading_cfg=lab_sub,
            **rko,
        )

    fb_b = _tail_fb(st_b, sg_b, BRANCH_LAB_B, tr_b)
    fb_c = _tail_fb(st_c, sg_c, BRANCH_LAB_C, tr_c)
    fb_d = _tail_fb(st_d, sg_d, BRANCH_LAB_D, tr_d)
    a_dollars = [x / 100.0 for x in prop_fb["per_trade_pnl_cents_chrono"]]
    ctrl_pool: list[float] = (
        [x / 100.0 for x in fb_b["per_trade_pnl_cents_chrono"]]
        + [x / 100.0 for x in fb_c["per_trade_pnl_cents_chrono"]]
        + [x / 100.0 for x in fb_d["per_trade_pnl_cents_chrono"]]
    )
    scores_bcd = [float(fb_b["score_dollars"]), float(fb_c["score_dollars"]), float(fb_d["score_dollars"])]
    stat_ok, stat_detail = is_statistically_better(
        a_dollars,
        ctrl_pool,
        lab_a_score=float(prop_fb["score_dollars"]),
        control_scores=scores_bcd,
    )
    meta["statistical_detail"] = stat_detail

    if bool(oc.get("backtest_proposals", True)):
        if float(prop_fb["score_dollars"]) <= float(base_fb["score_dollars"]):
            meta["reject_reason"] = "fitness_not_improved_vs_baseline_rules"
            logger.info(
                "claude_rules_rejected: %s (%.4f -> %.4f)",
                meta["reject_reason"],
                float(base_fb["score_dollars"]),
                float(prop_fb["score_dollars"]),
            )
            return [], meta
        if not stat_ok:
            meta["reject_reason"] = "statistical_gate_failed_vs_controls"
            logger.info("claude_rules_rejected: %s detail=%s", meta["reject_reason"], stat_detail)
            return [], meta

    lab = dict(lab_base)
    lab["rules"] = [dict(r) for r in merged]
    cfg["lab_a"] = lab
    meta["accepted"] = True
    meta["reject_reason"] = None
    reason = parsed.reasoning[:500] if parsed.reasoning else "claude_rule_operations"
    hist = {
        "id": uuid4().hex,
        "created_at": at_iso,
        "branch": BRANCH_LAB_A,
        "lab_label": "Lab A",
        "style": "claude_rules",
        "reason": reason,
        "summary": (
            f"Claude rules: score {meta['score_before']:.3f}→{meta['score_after']:.3f} "
            f"ops={len(parsed.rule_operations)} mutant={mutant_run}"
        )[:400],
        "before": {"rules_count": len(rules_base), "score": meta["score_before"]},
        "after": {"rules_count": len(merged), "score": meta["score_after"]},
    }
    logger.info(
        "claude_rules_accepted: score %.4f -> %.4f ops=%s",
        meta["score_before"],
        meta["score_after"],
        len(parsed.rule_operations),
    )
    return [hist], meta


def _append_claude_trace(oc: dict[str, Any], entry: dict[str, Any]) -> None:
    cur = oc.get("claude_proposals_trace")
    rows = cur if isinstance(cur, list) else []
    oc["claude_proposals_trace"] = [entry, *rows][:10]


def _build_claude_system_prompt(*, mutant_run: bool, regime_hint: str) -> str:
    diversity = (
        "Every few runs, deliberately explore a **new rule family** (e.g. NO-side convexity, late-window YES snipes, "
        "paired bands) rather than only nudging thresholds on the current template."
    )
    mutant = (
        "**MUTANT CYCLE:** small random jitter was applied to Lab A reference thresholds in the payload — treat this as "
        "exploration pressure: propose a bolder but still fee-aware rule change."
        if mutant_run
        else ""
    )
    return (
        "You are a senior Kalshi **binary contract** strategist for **paper labs only** (lab_a staging, lab_b conservative, "
        "lab_c aggressive, lab_d wild). Never reference or tune the **live** branch.\n"
        "Domain facts you must respect:\n"
        "- **Fees:** Kalshi quadratic fee schedule eats edge on tight markets; size down when expected edge < fees.\n"
        "- **Time decay:** minutes_left interacts with spread and liquidity; very late markets can gap on settlement.\n"
        "- **Liquidity:** thin YES books imply wider effective prices; NO-side needs explicit NO ask / mirror bid logic.\n"
        "- **Event / headline risk:** correlated series move together — avoid stacking identical macro exposures across tickers.\n"
        "- **Correlation traps:** multiple rules hitting the same outcome type can over-concentrate; diversify bands.\n"
        f"- **Regime snapshot:** {regime_hint}\n"
        f"{diversity}\n{mutant}\n"
        "Output **only** a single JSON object matching the user payload `output_schema` (no markdown fences). "
        "You may emit `rule_operations` (add/patch/delete) for **lab_a only**, `lab_parameter_patch` for Lab A scalars, "
        "and `recommendations` with field=`balance_fraction_per_window` and target=`lab_a` for sizing. "
        "Keep `balance_fraction_per_window` within [0.0001, 1.0]. Prefer concrete numbers over prose."
    )


def _build_payload(
    *,
    cfg: dict[str, Any],
    trades: list[dict[str, Any]],
    signals: list[dict[str, Any]],
    metrics: dict[str, Any],
    oc: dict[str, Any],
) -> dict[str, Any]:
    return {
        "objective": (
            "Simulation-only quant: maximize risk-adjusted edge. Prefer higher profit factor × win rate with "
            "lower variance of per-trade outcomes; respect regime volatility and fee drag when include_fees_in_score is true."
        ),
        "branches": [BRANCH_LAB_A, BRANCH_LAB_B, BRANCH_LAB_C, BRANCH_LAB_D],
        "live_branch_forbidden": True,
        "persisted_tuning_target": "lab_a_only",
        "current_config_excerpt": {
            "lab_a": cfg.get("lab_a") or {},
            "lab_b": cfg.get("lab_b") or {},
            "lab_c": cfg.get("lab_c") or {},
            "lab_d": cfg.get("lab_d") or {},
            "shared": {
                "rules": cfg.get("rules") or [],
                "balance_fraction_per_window": cfg.get("balance_fraction_per_window"),
                "window_minutes": cfg.get("window_minutes"),
                "paper_fee_model": cfg.get("paper_fee_model"),
                "paper_fee_bps": cfg.get("paper_fee_bps"),
            },
        },
        "performance_metrics": metrics,
        "optimizer_controls": {
            "optimize_bet_size": oc.get("optimize_bet_size"),
            "include_fees_in_score": oc.get("include_fees_in_score"),
            "min_trades_for_optimize": oc.get("min_trades_for_optimize"),
            "min_profitable_trades": oc.get("min_profitable_trades"),
            "balance_fraction_bounds": {"min": 0.0001, "max": 1.0},
        },
        "recent_trades": trades,
        "recent_signals": signals,
        "output_schema": {
            "reasoning": "short string — why you are changing rules or sizing",
            "summary": "string",
            "rule_operations": [
                {
                    "op": "add | patch | modify | delete",
                    "rule_name": "existing rule name for patch/modify/delete",
                    "rule": "object: full rule for add; partial fields for patch/modify",
                }
            ],
            "lab_parameter_patch": {
                "balance_fraction_per_window": "optional float lab_a only",
                "window_minutes": "optional int lab_a only",
            },
            "recommendations": [
                {
                    "target": "lab_a",
                    "field": "balance_fraction_per_window",
                    "current": "any",
                    "suggested": "any",
                    "reason": "string",
                    "confidence": "low|medium|high",
                }
            ],
            "trend_notes": ["string"],
            "propose_new_rule_family": "boolean — set true when exploring a structurally new banding idea",
        },
    }


async def run_optimizer_once(store: Store, *, force: bool = False) -> dict[str, Any]:
    cfg = await store.load_config()
    oc = _norm_opt_cfg(_opt_cfg(cfg))
    sched = bool(oc.get("enabled"))
    adaptive_on = bool(oc.get("adaptive_enabled", True))
    if not force and not sched and not adaptive_on:
        return {"ok": False, "skipped": True, "reason": "optimizer_disabled"}
    lookback_h = max(1, min(24 * 30, int(oc.get("lookback_hours") or 48)))
    max_rows = max(100, min(10000, int(oc.get("max_rows_per_table") or 5000)))
    end = _utc_now()
    start = end - dt.timedelta(hours=lookback_h)
    start_iso = _iso(start)
    end_iso = _iso(end)
    # Monotonic tick for dashboard "second hand" (each optimizer evaluation, including no-op pulses).
    try:
        oc["pulse_eval_count"] = int(oc.get("pulse_eval_count") or 0) + 1
    except (TypeError, ValueError):
        oc["pulse_eval_count"] = 1
    oc["last_pulse_eval_at"] = end_iso
    try:
        oc["optimizer_cycle_count"] = int(oc.get("optimizer_cycle_count") or 0) + 1
    except (TypeError, ValueError):
        oc["optimizer_cycle_count"] = 1
    mutant_run = int(oc.get("optimizer_cycle_count") or 0) % 8 == 0
    oc["last_mutant_cycle"] = bool(mutant_run)

    # Paper labs only (no live rows).
    tr_a = await store.query_table("trades", branch=BRANCH_LAB_A, mode="simulate", start_at=start_iso, end_at=end_iso, limit=max_rows)
    tr_b = await store.query_table("trades", branch=BRANCH_LAB_B, mode="simulate", start_at=start_iso, end_at=end_iso, limit=max_rows)
    tr_c = await store.query_table("trades", branch=BRANCH_LAB_C, mode="simulate", start_at=start_iso, end_at=end_iso, limit=max_rows)
    tr_d = await store.query_table("trades", branch=BRANCH_LAB_D, mode="simulate", start_at=start_iso, end_at=end_iso, limit=max_rows)
    sg_a = await store.query_table("signals", branch=BRANCH_LAB_A, mode="simulate", start_at=start_iso, end_at=end_iso, limit=max_rows)
    sg_b = await store.query_table("signals", branch=BRANCH_LAB_B, mode="simulate", start_at=start_iso, end_at=end_iso, limit=max_rows)
    sg_c = await store.query_table("signals", branch=BRANCH_LAB_C, mode="simulate", start_at=start_iso, end_at=end_iso, limit=max_rows)
    sg_d = await store.query_table("signals", branch=BRANCH_LAB_D, mode="simulate", start_at=start_iso, end_at=end_iso, limit=max_rows)

    st_a_prev = [t for t in tr_a if str(t.get("status") or "").lower() == "settled" and t.get("pnl_cents") is not None]
    _sync_regime_rule_families_to_lab_a(cfg, oc, sg_a, st_a_prev, end_iso)
    prof_n = sum(1 for t in st_a_prev if int(t.get("pnl_cents") or 0) > 0)

    # Internal pulse (loss-streak threshold tuning, optional win-path easing, Lab A bet fraction nudge).
    changes: list[dict[str, Any]] = []
    if adaptive_on:
        ca = _apply_adaptive_lab_tuning(
            cfg=cfg, oc=oc, branch=BRANCH_LAB_A, trades=tr_a, signals=sg_a, at_iso=end_iso
        )
        if ca:
            changes.append(ca)
    if adaptive_on and not changes:
        cw = _apply_adaptive_win_relax_lab_a(cfg=cfg, oc=oc, trades=tr_a, signals=sg_a, at_iso=end_iso)
        if cw:
            changes.append(cw)
    eq_a = await store.equity_series(limit=500, branch=BRANCH_LAB_A)
    bi = _internal_lab_a_bet_pulse(
        cfg=cfg, oc=oc, tr_a=tr_a, tr_b=tr_b, tr_c=tr_c, tr_d=tr_d, sg_a=sg_a, eq_a=eq_a, at_iso=end_iso
    )
    if bi:
        changes.append(bi)
    mutation_meta: dict[str, Any] = {"accepted": False, "mutant_run": mutant_run, "reject_reason": ""}
    if mutant_run:
        st_a = [t for t in tr_a if str(t.get("status") or "").lower() == "settled" and t.get("pnl_cents") is not None]
        st_b = [t for t in tr_b if str(t.get("status") or "").lower() == "settled" and t.get("pnl_cents") is not None]
        st_c = [t for t in tr_c if str(t.get("status") or "").lower() == "settled" and t.get("pnl_cents") is not None]
        st_d = [t for t in tr_d if str(t.get("status") or "").lower() == "settled" and t.get("pnl_cents") is not None]
        mut_row, mutation_meta = _internal_mutate_rules_and_params(
            cfg=cfg,
            oc=oc,
            st_a=st_a,
            st_b=st_b,
            st_c=st_c,
            st_d=st_d,
            sg_a=sg_a,
            sg_b=sg_b,
            sg_c=sg_c,
            sg_d=sg_d,
            at_iso=end_iso,
            tr_a=tr_a,
            tr_b=tr_b,
            tr_c=tr_c,
            tr_d=tr_d,
        )
        if mut_row:
            changes.append(mut_row)

    _set_next_tick_preview(
        oc,
        cfg,
        lab_settled_n=len(st_a_prev),
        profitable_n=prof_n,
        tr_b=tr_b,
        tr_c=tr_c,
        tr_d=tr_d,
    )
    if changes:
        hist = oc.get("change_history")
        old_hist = hist if isinstance(hist, list) else []
        lim = max(20, min(500, _safe_int(oc.get("max_history"), 120)))
        oc["change_history"] = [*changes, *old_hist][:lim]
        oc["last_change_at"] = end_iso
        _merge_pulse_trace(oc, changes)
    bet_frac_n = sum(1 for c in changes if str(c.get("style") or "") == "bet_size")
    lab_tr, rules_tr = _ensure_lab_rules(cfg, BRANCH_LAB_A)
    st_tr = [t for t in tr_a if str(t.get("status") or "").lower() == "settled" and t.get("pnl_cents") is not None]
    rb_lab = _replay_fitness_bundle(
        st_tr[:200],
        rules_tr,
        _signals_sorted_desc(sg_a),
        include_fees_in_score=bool(oc.get("include_fees_in_score", True)),
        max_rows=200,
        branch_trading_cfg=lab_tr,
        **_replay_open_kw(cfg, at_iso=end_iso, branch=BRANCH_LAB_A, trades=tr_a),
    )
    sl_rate = float(rb_lab.get("stop_loss_trigger_rate") or 0.0)
    sl_cents = int(rb_lab.get("total_pnl_from_stops_cents") or 0)
    sl_n = int(rb_lab.get("stop_loss_exits_n") or 0)
    oc["replay_stop_loss_trigger_rate_pct"] = round(sl_rate, 2)
    oc["replay_total_pnl_from_stops_dollars"] = round(sl_cents / 100.0, 4)
    ar_now = str(lab_tr.get("active_regime") or "low_vol")
    # Meta-learning: decay + EWMA of composite score per (logical) Lab A regime; also streaks for cleanup.
    _regime_update_meta_and_streaks(
        oc, active_regime=ar_now, score_dollars=_safe_float(rb_lab.get("score_dollars"), 0.0)
    )
    _prune_failing_regime_families(cfg, oc)
    eq_dph = _equity_slope_dollars_per_hour(eq_a)
    trace_entry: dict[str, Any] = {
        "at": end_iso,
        "cycle": int(oc.get("optimizer_cycle_count") or 0),
        "score": mutation_meta.get("score_after")
        if mutation_meta.get("score_after") is not None
        else mutation_meta.get("score_before"),
        "score_before": mutation_meta.get("score_before"),
        "score_after": mutation_meta.get("score_after"),
        "accepted": bool(mutation_meta.get("accepted")),
        "reject_reason": str(mutation_meta.get("reject_reason") or ""),
        "mutant": bool(mutant_run),
        "changes_n": len(changes),
        "total_pnl_from_stops_cents": sl_cents,
        "total_pnl_from_stops_dollars": round(sl_cents / 100.0, 4),
        "stop_loss_trigger_rate_pct": sl_rate,
        "stop_loss_exits_n": sl_n,
        "open_simulated_stop_exits_n": int(rb_lab.get("open_simulated_stop_exits_n") or 0),
        "equity_slope_dph": (round(float(eq_dph), 6) if eq_dph is not None else None),
    }
    _append_internal_trace(oc, trace_entry)
    tr_rows = oc.get("internal_optimizer_trace")
    tr_list = tr_rows if isinstance(tr_rows, list) else []
    accepted_n = sum(1 for r in tr_list if bool(r.get("accepted")))
    total_n = len(tr_list)
    oc["acceptance_rate_pct"] = round((accepted_n * 100.0 / total_n), 2) if total_n > 0 else 0.0
    _ap0 = _safe_float(oc.get("acceptance_rate_pct", 0.0), 0.0)
    if _ap0 < 15.0:
        oc["optimizer_consecutive_low_acceptance_cycles"] = int(oc.get("optimizer_consecutive_low_acceptance_cycles", 0) or 0) + 1
    else:
        oc["optimizer_consecutive_low_acceptance_cycles"] = 0
    plr_t = bool(oc.get("enable_paper_loser_detection", True))
    pl = _is_paper_winner_but_real_loser(oc, rb_lab) if plr_t else False
    oc["paper_loser_risk_last"] = bool(pl)
    pwc = int(oc.get("optimizer_consecutive_paper_loser_cycles", 0) or 0)
    pthr0 = max(1, int(oc.get("paper_loser_cycles_threshold", 4) or 4))
    if pl:
        pwc += 1
    else:
        pwc = 0
    oc["optimizer_consecutive_paper_loser_cycles"] = pwc
    swap_pl: dict[str, Any] = {"swapped": False}
    if plr_t and pwc >= pthr0:
        swap_pl = await _apply_paper_loser_strategy_swap(
            store, cfg, oc, at_iso=end_iso, repeated_cycles=pwc
        )
        if swap_pl.get("swapped"):
            ph = oc.get("change_history")
            ph0 = ph if isinstance(ph, list) else []
            hlim = max(20, min(500, _safe_int(oc.get("max_history"), 120)))
            ch_row: dict[str, Any] = {
                "id": uuid4().hex,
                "created_at": end_iso,
                "branch": BRANCH_LAB_A,
                "lab_label": "Lab A",
                "style": "paper_loser_full_swap",
                "reason": "paper_winner_real_loser",
                "summary": (
                    f"regime -> {swap_pl.get('new_regime')} history={bool(swap_pl.get('history_applied'))} "
                    f"after {pthr0} consecutive paper/replay–live divergent cycles"
                ),
            }
            oc["change_history"] = [ch_row, *ph0][:hlim]
    if plr_t and pl:
        oc["autotune_window_paper_loser_risk_events"] = int(
            oc.get("autotune_window_paper_loser_risk_events", 0) or 0
        ) + 1
    if bool(swap_pl.get("swapped")):
        oc["autotune_window_paper_loser_swaps"] = int(oc.get("autotune_window_paper_loser_swaps", 0) or 0) + 1
    eff_sc, mtier = _compute_mutation_scale(oc)
    oc["mutation_tier"] = mtier
    oc["effective_mutation_scale"] = round(eff_sc, 4)
    health = _check_optimizer_health(oc)
    oc["optimizer_health_color"] = str(health["health_color"])
    oc["optimizer_suggested_action"] = str(health["suggested_action"])
    stk = _safe_int(oc.get("optimizer_red_streak_cycles"), 0)
    if str(health["health_color"]) == "red":
        stk += 1
    else:
        stk = 0
    oc["optimizer_red_streak_cycles"] = stk
    if stk == 13:
        logger.warning(
            "Optimizer stuck — consider manual reset (red acceptance health for 13+ consecutive optimizer cycles)."
        )
    revert_meta = await _maybe_auto_revert_if_stuck(
        store,
        cfg=cfg,
        oc=oc,
        tr_a=tr_a,
        sg_a=sg_a,
        at_iso=end_iso,
        red_streak=stk,
        acceptance_pct=float(oc.get("acceptance_rate_pct") or 0.0),
    )
    oc["last_run_at"] = end_iso
    if not bool(revert_meta.get("reverted")):
        if bool(swap_pl.get("swapped")):
            oc["last_status"] = "ok_paper_loser_full_swap"
        else:
            oc["last_status"] = "ok_internal_mutation" if mutation_meta.get("accepted") else (
                "ok_internal_pulse" if changes else "ok_noop"
            )
    oc["last_error"] = ""
    if mutation_meta.get("score_after") is not None:
        try:
            best = float(oc.get("best_fitness_score_7d") or 0.0)
            new_best = max(best, float(mutation_meta["score_after"]))
            oc["best_fitness_score_7d"] = round(new_best, 6)
        except (TypeError, ValueError):
            pass
    cyc_end = int(oc.get("optimizer_cycle_count", 0) or 0)
    lastat = int(oc.get("last_autotune_at_optimizer_cycle", 0) or 0)
    if cyc_end >= 24 and cyc_end % 24 == 0 and cyc_end != lastat:
        _auto_tune_internal_thresholds(oc)
        oc["autotune_window_paper_loser_risk_events"] = 0
        oc["autotune_window_paper_loser_swaps"] = 0
        oc["last_autotune_at_optimizer_cycle"] = cyc_end
    cfg["optimizer"] = oc
    await store.save_config(
        cfg,
        history_branch="global",
        history_changed_by="optimizer_internal",
        history_reason=oc["last_status"],
    )
    return {
        "ok": True,
        "adaptive_only": True,
        "internal_only": True,
        "window_start": start_iso,
        "window_end": end_iso,
        "changes_applied": len(changes),
        "bet_fraction_changes": bet_frac_n,
        "mutant_run": mutant_run,
        "mutation_accepted": bool(mutation_meta.get("accepted")),
        "auto_reverted": bool(revert_meta.get("reverted")),
        "paper_loser_swap": swap_pl,
    }


async def force_internal_mutation_once(store: Store) -> dict[str, Any]:
    """
    Force-run one internal mutant cycle immediately (no scheduler gate).

    Calls ``_internal_mutate_rules_and_params`` directly, persists trace/status, and returns
    accept/reject diagnostics with score delta.
    """
    cfg = await store.load_config()
    oc = _norm_opt_cfg(_opt_cfg(cfg))
    end = _utc_now()
    end_iso = _iso(end)
    lookback_h = max(1, min(24 * 30, int(oc.get("lookback_hours") or 48)))
    max_rows = max(100, min(10000, int(oc.get("max_rows_per_table") or 5000)))
    start = end - dt.timedelta(hours=lookback_h)
    start_iso = _iso(start)
    try:
        oc["optimizer_cycle_count"] = int(oc.get("optimizer_cycle_count") or 0) + 1
    except (TypeError, ValueError):
        oc["optimizer_cycle_count"] = 1

    tr_a = await store.query_table("trades", branch=BRANCH_LAB_A, mode="simulate", start_at=start_iso, end_at=end_iso, limit=max_rows)
    tr_b = await store.query_table("trades", branch=BRANCH_LAB_B, mode="simulate", start_at=start_iso, end_at=end_iso, limit=max_rows)
    tr_c = await store.query_table("trades", branch=BRANCH_LAB_C, mode="simulate", start_at=start_iso, end_at=end_iso, limit=max_rows)
    tr_d = await store.query_table("trades", branch=BRANCH_LAB_D, mode="simulate", start_at=start_iso, end_at=end_iso, limit=max_rows)
    sg_a = await store.query_table("signals", branch=BRANCH_LAB_A, mode="simulate", start_at=start_iso, end_at=end_iso, limit=max_rows)
    sg_b = await store.query_table("signals", branch=BRANCH_LAB_B, mode="simulate", start_at=start_iso, end_at=end_iso, limit=max_rows)
    sg_c = await store.query_table("signals", branch=BRANCH_LAB_C, mode="simulate", start_at=start_iso, end_at=end_iso, limit=max_rows)
    sg_d = await store.query_table("signals", branch=BRANCH_LAB_D, mode="simulate", start_at=start_iso, end_at=end_iso, limit=max_rows)
    st_a = [t for t in tr_a if str(t.get("status") or "").lower() == "settled" and t.get("pnl_cents") is not None]
    st_b = [t for t in tr_b if str(t.get("status") or "").lower() == "settled" and t.get("pnl_cents") is not None]
    st_c = [t for t in tr_c if str(t.get("status") or "").lower() == "settled" and t.get("pnl_cents") is not None]
    st_d = [t for t in tr_d if str(t.get("status") or "").lower() == "settled" and t.get("pnl_cents") is not None]

    row, meta = _internal_mutate_rules_and_params(
        cfg=cfg,
        oc=oc,
        st_a=st_a,
        st_b=st_b,
        st_c=st_c,
        st_d=st_d,
        sg_a=sg_a,
        sg_b=sg_b,
        sg_c=sg_c,
        sg_d=sg_d,
        at_iso=end_iso,
        tr_a=tr_a,
        tr_b=tr_b,
        tr_c=tr_c,
        tr_d=tr_d,
    )
    if row:
        hist = oc.get("change_history")
        prev = hist if isinstance(hist, list) else []
        lim = max(20, min(500, _safe_int(oc.get("max_history"), 120)))
        oc["change_history"] = [row, *prev][:lim]
        oc["last_change_at"] = end_iso
        _merge_pulse_trace(oc, [row])

    eq_a_force = await store.equity_series(limit=500, branch=BRANCH_LAB_A)
    lab_tr, rules_tr = _ensure_lab_rules(cfg, BRANCH_LAB_A)
    rb_lab = _replay_fitness_bundle(
        st_a[:200],
        rules_tr,
        _signals_sorted_desc(sg_a),
        include_fees_in_score=bool(oc.get("include_fees_in_score", True)),
        max_rows=200,
        branch_trading_cfg=lab_tr,
        **_replay_open_kw(cfg, at_iso=end_iso, branch=BRANCH_LAB_A, trades=tr_a),
    )
    sl_rate = float(rb_lab.get("stop_loss_trigger_rate") or 0.0)
    sl_cents = int(rb_lab.get("total_pnl_from_stops_cents") or 0)
    sl_n = int(rb_lab.get("stop_loss_exits_n") or 0)
    oc["replay_stop_loss_trigger_rate_pct"] = round(sl_rate, 2)
    oc["replay_total_pnl_from_stops_dollars"] = round(sl_cents / 100.0, 4)
    eq_dph_f = _equity_slope_dollars_per_hour(eq_a_force)
    trace_entry = {
        "at": end_iso,
        "cycle": int(oc.get("optimizer_cycle_count") or 0),
        "score": meta.get("score_after") if meta.get("score_after") is not None else meta.get("score_before"),
        "score_before": meta.get("score_before"),
        "score_after": meta.get("score_after"),
        "accepted": bool(meta.get("accepted")),
        "reject_reason": str(meta.get("reject_reason") or ""),
        "mutant": True,
        "changes_n": 1 if row else 0,
        "forced": True,
        "total_pnl_from_stops_cents": sl_cents,
        "total_pnl_from_stops_dollars": round(sl_cents / 100.0, 4),
        "stop_loss_trigger_rate_pct": sl_rate,
        "stop_loss_exits_n": sl_n,
        "open_simulated_stop_exits_n": int(rb_lab.get("open_simulated_stop_exits_n") or 0),
        "equity_slope_dph": (round(float(eq_dph_f), 6) if eq_dph_f is not None else None),
    }
    _append_internal_trace(oc, trace_entry)
    tr_rows = oc.get("internal_optimizer_trace")
    tr_list = tr_rows if isinstance(tr_rows, list) else []
    accepted_n = sum(1 for r in tr_list if bool(r.get("accepted")))
    oc["acceptance_rate_pct"] = round((accepted_n * 100.0 / len(tr_list)), 2) if tr_list else 0.0
    eff_sc_f, mtier_f = _compute_mutation_scale(oc)
    oc["mutation_tier"] = mtier_f
    oc["effective_mutation_scale"] = round(eff_sc_f, 4)
    health_f = _check_optimizer_health(oc)
    oc["optimizer_health_color"] = str(health_f["health_color"])
    oc["optimizer_suggested_action"] = str(health_f["suggested_action"])
    stk_f = _safe_int(oc.get("optimizer_red_streak_cycles"), 0)
    if str(health_f["health_color"]) == "red":
        stk_f += 1
    else:
        stk_f = 0
    oc["optimizer_red_streak_cycles"] = stk_f
    if stk_f == 13:
        logger.warning(
            "Optimizer stuck — consider manual reset (red acceptance health for 13+ consecutive optimizer cycles)."
        )
    oc["last_run_at"] = end_iso
    oc["last_pulse_eval_at"] = end_iso
    oc["last_status"] = "forced_internal_mutation_accepted" if meta.get("accepted") else "forced_internal_mutation_rejected"
    oc["last_error"] = ""
    if meta.get("score_after") is not None:
        try:
            best = float(oc.get("best_fitness_score_7d") or 0.0)
            oc["best_fitness_score_7d"] = round(max(best, float(meta["score_after"])), 6)
        except (TypeError, ValueError):
            pass
    cfg["optimizer"] = oc
    await store.save_config(
        cfg,
        history_branch="global",
        history_changed_by="optimizer_internal_forced",
        history_reason=oc["last_status"],
    )
    logger.info(
        "forced internal mutation: accepted=%s reason=%s score_before=%s score_after=%s",
        bool(meta.get("accepted")),
        str(meta.get("reject_reason") or ""),
        meta.get("score_before"),
        meta.get("score_after"),
    )
    score_before = meta.get("score_before")
    score_after = meta.get("score_after")
    delta = None
    try:
        if score_before is not None and score_after is not None:
            delta = float(score_after) - float(score_before)
    except (TypeError, ValueError):
        delta = None
    return {
        "ok": True,
        "forced": True,
        "accepted": bool(meta.get("accepted")),
        "reason": str(meta.get("reject_reason") or ("accepted" if bool(meta.get("accepted")) else "")),
        "score_before": score_before,
        "score_after": score_after,
        "new_fitness": score_after,
        "fitness_delta": delta,
        "change_applied": bool(row is not None),
        "cycle": int(oc.get("optimizer_cycle_count") or 0),
        "at": end_iso,
    }

