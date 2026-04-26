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
from .engine import rule_matches
from .optimizer.fitness import composite_fitness_score, is_statistically_better
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
    out.setdefault("model", "claude-sonnet-4-5")
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
    out.setdefault("optimize_rules_with_claude", True)
    out.setdefault("optimizer_cycle_count", 0)
    out.setdefault("claude_proposals_trace", [])
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
) -> dict[str, Any]:
    """
    Replay over the first ``max_considered`` rows of ``settled`` (caller passes query order: typically
    newest-first), then **sorted oldest-first** for cumulative PnL / drawdown. Matched-trade totals are
    order-independent; ordering only affects the equity path inside this window.
    """
    clean_rules = [dict(r) for r in rules if isinstance(r, dict)]
    pool = sorted(settled[:max_considered], key=_trade_sort_key)
    total = 0
    matched = 0
    considered = 0
    per_trade: list[int] = []
    cumulative: list[int] = [0]
    cur = 0
    for t in pool:
        considered += 1
        prob, mins = _entry_prob_mins_for_trade(t, signals_desc)
        if prob is None or mins is None:
            continue
        if not any(rule_matches(prob, mins, r) for r in clean_rules):
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
        total += pnl
        matched += 1
        per_trade.append(pnl)
        cur += pnl
        cumulative.append(cur)
    return {
        "total_pnl_cents": total,
        "matched_n": matched,
        "considered_n": considered,
        "per_trade_pnl_cents_chrono": per_trade,
        "cumulative_equity_cents": cumulative,
    }


def _replay_fitness_bundle(
    settled: list[dict[str, Any]],
    rules: list[dict[str, Any]],
    signals_desc: list[dict[str, Any]],
    *,
    include_fees_in_score: bool,
    max_rows: int = 200,
    branch_trading_cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Replay plus composite fitness (drawdown / vol / Sharpe blend)."""
    d = replay_under_rules_detail(
        settled[:max_rows],
        rules,
        signals_desc,
        include_fees_in_score=include_fees_in_score,
        max_considered=max_rows,
        branch_trading_cfg=branch_trading_cfg,
    )
    fit = composite_fitness_score(
        total_pnl_cents=int(d["total_pnl_cents"]),
        cumulative_equity_cents=d["cumulative_equity_cents"],
        per_trade_pnl_cents=d["per_trade_pnl_cents_chrono"],
    )
    return {**d, **fit}


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
    lab_a = cfg.get("lab_a") if isinstance(cfg.get("lab_a"), dict) else {}
    lab_b = cfg.get("lab_b") if isinstance(cfg.get("lab_b"), dict) else {}
    lab_c = cfg.get("lab_c") if isinstance(cfg.get("lab_c"), dict) else {}
    lab_d = cfg.get("lab_d") if isinstance(cfg.get("lab_d"), dict) else {}
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
        base_fb = _replay_fitness_bundle(
            settled,
            rules_base,
            sig_desc,
            include_fees_in_score=fee_flag,
            max_rows=200,
            branch_trading_cfg=lab_base,
        )
        new_fb = _replay_fitness_bundle(
            settled,
            proposed_rules,
            sig_desc,
            include_fees_in_score=fee_flag,
            max_rows=200,
            branch_trading_cfg=lab_base,
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
        base_fb = _replay_fitness_bundle(
            settled,
            rules_base,
            sig_desc,
            include_fees_in_score=fee_flag,
            max_rows=200,
            branch_trading_cfg=lab_base,
        )
        new_fb = _replay_fitness_bundle(
            settled,
            proposed_rules,
            sig_desc,
            include_fees_in_score=fee_flag,
            max_rows=200,
            branch_trading_cfg=lab_base,
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
    at_iso: str,
) -> dict[str, Any] | None:
    """Rule-based Lab A bet fraction nudge from replay fitness on recent settled window (fallback: mean ¢/trade)."""
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

    lab_base, rules_a = _ensure_lab_rules(cfg, BRANCH_LAB_A)
    try:
        old_f = float(lab_base.get("balance_fraction_per_window") or cfg.get("balance_fraction_per_window") or 0.03)
    except (TypeError, ValueError):
        old_f = 0.03

    window = st_a[:40]
    if len(window) < 4:
        return None
    pnl = sum(int(t.get("pnl_cents") or 0) for t in window) / max(1, len(window))
    sig_desc = _signals_sorted_desc(sg_a)
    fee_flag = bool(oc.get("include_fees_in_score", True))
    fb = _replay_fitness_bundle(
        window,
        rules_a,
        sig_desc,
        include_fees_in_score=fee_flag,
        max_rows=40,
        branch_trading_cfg=lab_base,
    )
    matched_n = int(fb.get("matched_n") or 0)
    fitness_score = float(fb.get("score_dollars") or 0.0)
    drive = fitness_score if matched_n >= 2 else (pnl / 100.0)
    step = 0.003
    style_d = _branch_style(oc, BRANCH_LAB_D)
    if style_d == "wild":
        b_tail = st_b[:24]
        c_tail = st_c[:24]
        b_mean = (sum(int(t.get("pnl_cents") or 0) for t in b_tail) / len(b_tail)) if b_tail else 0.0
        c_mean = (sum(int(t.get("pnl_cents") or 0) for t in c_tail) / len(c_tail)) if c_tail else 0.0
        bc_boost = max(b_mean, c_mean)
        if bc_boost >= 15:
            step = 0.005
        elif bc_boost <= -15:
            step = 0.0045
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
    reason = (
        f"internal pulse: Lab A last-{len(window)} settled fitness {fitness_score:.3f} "
        f"(mean {pnl:.0f}¢/trade, {matched_n} replay-matched)"
    )
    if style_d == "wild":
        reason += " (Lab D wild bias from B/C momentum)"
    hint = (
        f"Next tick uses bet fraction ~{new_f:.2%} of Lab A paper per window (was ~{old_f:.2%}). "
        f"Threshold rules unchanged unless the loss-streak adaptive fires."
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

    base_fb = _replay_fitness_bundle(
        a_tail,
        rules_base,
        sig_a,
        include_fees_in_score=fee_flag,
        max_rows=tail_n,
        branch_trading_cfg=lab_base,
    )
    prop_fb = _replay_fitness_bundle(
        a_tail,
        merged,
        sig_a,
        include_fees_in_score=fee_flag,
        max_rows=tail_n,
        branch_trading_cfg=lab_base,
    )
    meta["score_before"] = float(base_fb["score_dollars"])
    meta["score_after"] = float(prop_fb["score_dollars"])

    def _tail_fb(
        st: list[dict[str, Any]], sg: list[dict[str, Any]], br: str
    ) -> dict[str, Any]:
        stx = [t for t in st if str(t.get("status") or "").lower() == "settled" and t.get("pnl_cents") is not None]
        _, rx = _ensure_lab_rules(cfg, br)
        lk = _lab_key_for_branch(br) or "lab_a"
        lab_sub = cfg.get(lk) if isinstance(cfg.get(lk), dict) else {}
        return _replay_fitness_bundle(
            stx[:tail_n],
            rx,
            _signals_sorted_desc(sg),
            include_fees_in_score=fee_flag,
            max_rows=tail_n,
            branch_trading_cfg=lab_sub,
        )

    fb_b = _tail_fb(st_b, sg_b, BRANCH_LAB_B)
    fb_c = _tail_fb(st_c, sg_c, BRANCH_LAB_C)
    fb_d = _tail_fb(st_d, sg_d, BRANCH_LAB_D)
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
    prof_n = sum(1 for t in st_a_prev if int(t.get("pnl_cents") or 0) > 0)

    # Internal pulse (no Claude): loss-streak threshold tuning, optional win-path easing, Lab A bet fraction nudge.
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
    bi = _internal_lab_a_bet_pulse(
        cfg=cfg, oc=oc, tr_a=tr_a, tr_b=tr_b, tr_c=tr_c, tr_d=tr_d, sg_a=sg_a, at_iso=end_iso
    )
    if bi:
        changes.append(bi)

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

    key = env.anthropic_api_key.strip()
    want_claude = (bool(sched) or bool(force)) and bool(key)
    if not want_claude:
        oc["last_run_at"] = end_iso
        oc["last_status"] = "ok_internal_pulse" if changes else "ok_noop"
        oc["last_error"] = ""
        cfg["optimizer"] = oc
        await store.save_config(
            cfg,
            history_branch="global",
            history_changed_by="optimizer_claude",
            history_reason="ok_internal_pulse" if changes else "ok_noop",
        )
        return {
            "ok": True,
            "adaptive_only": True,
            "internal_only": True,
            "changes_applied": len(changes),
            "bet_fraction_changes": bet_frac_n,
            "window_start": start_iso,
            "window_end": end_iso,
        }

    cfg["optimizer"] = oc
    await store.save_config(
        cfg, history_branch="global", history_changed_by="optimizer_claude", history_reason="pre_claude_checkpoint"
    )
    cfg = await store.load_config()
    oc = _norm_opt_cfg(_opt_cfg(cfg))

    eq_a = await store.equity_series(limit=500, branch=BRANCH_LAB_A)
    eq_b = await store.equity_series(limit=500, branch=BRANCH_LAB_B)
    eq_c = await store.equity_series(limit=500, branch=BRANCH_LAB_C)
    eq_d = await store.equity_series(limit=500, branch=BRANCH_LAB_D)
    metrics = _build_metrics_context(
        cfg=cfg,
        oc=oc,
        tr_a=tr_a,
        tr_b=tr_b,
        tr_c=tr_c,
        tr_d=tr_d,
        sg_a=sg_a,
        sg_b=sg_b,
        sg_c=sg_c,
        sg_d=sg_d,
        eq_a=eq_a,
        eq_b=eq_b,
        eq_c=eq_c,
        eq_d=eq_d,
        end=end,
    )
    payload = _build_payload(
        cfg=cfg,
        trades=[*tr_a, *tr_b, *tr_c, *tr_d],
        signals=[*sg_a, *sg_b, *sg_c, *sg_d],
        metrics=metrics,
        oc=oc,
    )
    la_stats = metrics.get("lab_a") if isinstance(metrics.get("lab_a"), dict) else {}
    regime_hint = json.dumps(
        {
            "primary": la_stats.get("regime"),
            "replay_pnl_cents": la_stats.get("replay_under_current_rules_pnl_cents"),
        },
        default=str,
    )[:1200]
    payload["per_rule_performance_48h_lab_a"] = la_stats.get("per_rule_stats_48h")
    payload["settled_trade_examples_lab_a"] = _settled_trade_examples_for_prompt(st_a_prev, n=5)
    if mutant_run:
        payload["optimizer_mutant_hints"] = _mutant_optimizer_hints(oc)
        logger.info("optimizer_mutant_cycle: hints=%s", payload.get("optimizer_mutant_hints"))
    payload["optimizer_cycle"] = {"count": oc.get("optimizer_cycle_count"), "mutant": mutant_run}

    model = str(oc.get("model") or "claude-sonnet-4-5")
    body = {
        "model": model,
        "max_tokens": 4200,
        "temperature": 0.28 if mutant_run else 0.32,
        "system": _build_claude_system_prompt(mutant_run=mutant_run, regime_hint=regime_hint),
        "messages": [{"role": "user", "content": json.dumps(payload, default=str)}],
    }

    import httpx

    async with httpx.AsyncClient(timeout=90.0) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=body,
        )
        r.raise_for_status()
        out = r.json()

    txt = ""
    for c in out.get("content") or []:
        if isinstance(c, dict) and c.get("type") == "text":
            txt += str(c.get("text") or "")
    txt = txt.strip()
    parsed, raw_meta = parse_claude_optimizer_json(txt)
    rec: dict[str, Any]
    if parsed is not None:
        rec = parsed.model_dump()
    else:
        rec = {"summary": txt[:500], "recommendations": [], "trend_notes": [], "parse_error": raw_meta}
        logger.warning("claude_json_parse_failed: %s", raw_meta)

    rid = await store.insert_optimizer_recommendation(
        created_at=_iso(end),
        window_start=start_iso,
        window_end=end_iso,
        source_branches=[BRANCH_LAB_A, BRANCH_LAB_B, BRANCH_LAB_C, BRANCH_LAB_D],
        summary=str(rec.get("summary") or "")[:2000],
        recommendation_json=rec if isinstance(rec, dict) else {"raw": rec},
        raw_json=out if isinstance(out, dict) else None,
    )

    st_a_settled = [
        t
        for t in tr_a
        if str(t.get("status") or "").lower() == "settled" and t.get("pnl_cents") is not None
    ]
    st_b_settled = [
        t
        for t in tr_b
        if str(t.get("status") or "").lower() == "settled" and t.get("pnl_cents") is not None
    ]
    st_c_settled = [
        t
        for t in tr_c
        if str(t.get("status") or "").lower() == "settled" and t.get("pnl_cents") is not None
    ]
    st_d_settled = [
        t
        for t in tr_d
        if str(t.get("status") or "").lower() == "settled" and t.get("pnl_cents") is not None
    ]

    claude_extra: list[dict[str, Any]] = []
    rule_meta: dict[str, Any] = {}
    if parsed is not None:
        rule_hist, rule_meta = apply_claude_rule_changes(
            cfg=cfg,
            oc=oc,
            parsed=parsed,
            st_a=st_a_settled,
            sg_a=sg_a,
            st_b=st_b_settled,
            sg_b=sg_b,
            st_c=st_c_settled,
            sg_c=sg_c,
            st_d=st_d_settled,
            sg_d=sg_d,
            at_iso=_iso(end),
            mutant_run=mutant_run,
        )
        claude_extra.extend(rule_hist)
        if mutant_run and rule_hist:
            rule_hist[0]["reason"] = (
                f"[mutant exploration] {rule_hist[0].get('reason', '')}"[:500]
            )

    param_hist = _apply_claude_lab_parameter_patch(
        cfg=cfg, oc=oc, parsed=parsed, at_iso=_iso(end)
    ) if parsed is not None else []
    claude_extra.extend(param_hist)

    bet_hist = _apply_claude_bet_recommendations(
        cfg=cfg,
        oc=oc,
        rec=rec if isinstance(rec, dict) else {},
        tr_a=tr_a,
        tr_b=tr_b,
        tr_c=tr_c,
        tr_d=tr_d,
        at_iso=_iso(end),
    )
    claude_extra.extend(bet_hist)

    trace_entry: dict[str, Any] = {
        "at": _iso(end),
        "reasoning": (parsed.reasoning if parsed else "")[:2000],
        "summary": (parsed.summary if parsed else str(rec.get("summary") or ""))[:800],
        "score_before": rule_meta.get("score_before"),
        "score_after": rule_meta.get("score_after"),
        "accepted": bool(rule_meta.get("accepted")),
        "reject_reason": rule_meta.get("reject_reason"),
        "mutant": mutant_run,
        "rule_ops": len(parsed.rule_operations) if parsed else 0,
        "changes_n": len(claude_extra),
    }
    _append_claude_trace(oc, trace_entry)

    if claude_extra:
        hist2 = oc.get("change_history")
        old2 = hist2 if isinstance(hist2, list) else []
        lim2 = max(20, min(500, _safe_int(oc.get("max_history"), 120)))
        oc["change_history"] = [*claude_extra, *old2][:lim2]
        oc["last_change_at"] = _iso(end)
        _merge_pulse_trace(oc, claude_extra)

    oc["last_run_at"] = _iso(end)
    oc["last_status"] = "ok"
    oc["last_error"] = ""
    cfg["optimizer"] = oc
    await store.save_config(
        cfg, history_branch="global", history_changed_by="optimizer_claude", history_reason="claude_run_complete"
    )
    return {
        "ok": True,
        "id": rid,
        "window_start": start_iso,
        "window_end": end_iso,
        "changes_applied": len(changes) + len(claude_extra),
        "bet_fraction_changes": len(bet_hist),
        "mutant_run": mutant_run,
        "claude_rule_accepted": bool(rule_meta.get("accepted")),
    }

