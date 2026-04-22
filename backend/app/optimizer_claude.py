from __future__ import annotations

import datetime as dt
import json
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from .branch_config import BRANCH_LAB_A, BRANCH_LAB_B
from .engine import rule_matches
from .settings_env import env

if TYPE_CHECKING:
    from .persistence import Store


def _utc_now() -> dt.datetime:
    return dt.datetime.now(tz=dt.timezone.utc)


def _iso(v: dt.datetime) -> str:
    return v.astimezone(dt.timezone.utc).isoformat()


def _opt_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    o = cfg.get("optimizer")
    return dict(o) if isinstance(o, dict) else {}


def _norm_opt_cfg(oc: dict[str, Any]) -> dict[str, Any]:
    out = dict(oc or {})
    out.setdefault("enabled", False)
    out.setdefault("interval_minutes", 120)
    out.setdefault("lookback_hours", 72)
    out.setdefault("max_rows_per_table", 5000)
    out.setdefault("model", "claude-sonnet-4-5")
    out.setdefault("adaptive_enabled", True)
    out.setdefault("mode", "duel")  # duel | independent
    out.setdefault("lab_a_enabled", True)
    out.setdefault("lab_b_enabled", True)
    out.setdefault("lab_a_style", "conservative")
    out.setdefault("lab_b_style", "aggressive")
    out.setdefault("loss_streak_trigger", 3)
    out.setdefault("threshold_step_pct", 1)
    out.setdefault("minute_step", 1)
    out.setdefault("max_history", 120)
    out.setdefault("lab_a_yes_floor_pct", 57)
    out.setdefault("lab_b_yes_floor_pct", 55)
    out.setdefault("lab_a_min_minutes_left", 5)
    out.setdefault("lab_b_min_minutes_left", 3)
    out.setdefault("min_trades_for_optimize", 25)
    out.setdefault("min_profitable_trades", 8)
    out.setdefault("max_bet_fraction", 0.12)
    out.setdefault("optimize_bet_size", True)
    out.setdefault("include_fees_in_score", True)
    out.setdefault("regime_lookback_hours", 6)
    out.setdefault("backtest_proposals", True)
    out.setdefault("change_history", [])
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
        return "conservative" if branch == BRANCH_LAB_A else "aggressive"
    if branch == BRANCH_LAB_A:
        return str(oc.get("lab_a_style") or "conservative").strip().lower()
    return str(oc.get("lab_b_style") or "aggressive").strip().lower()


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
) -> tuple[int, int, int]:
    """
    Replay: sum settled PnL for trades whose entry (implied YES, minutes) would match at least one rule.
    Returns (total_pnl_cents, n_matched, n_considered).
    """
    total = 0
    matched = 0
    considered = 0
    clean_rules = [dict(r) for r in rules if isinstance(r, dict)]
    for t in settled[:200]:
        considered += 1
        prob, mins = _entry_prob_mins_for_trade(t, signals_desc)
        if prob is None or mins is None:
            continue
        if not any(rule_matches(prob, mins, r) for r in clean_rules):
            continue
        pnl = int(t.get("pnl_cents") or 0)
        if include_fees_in_score:
            ex: dict[str, Any] = {}
            try:
                ex = json.loads(str(t.get("extra_json") or "{}"))
            except Exception:
                ex = {}
            fees = int(ex.get("entry_fee_cents") or 0) + int(ex.get("settlement_exit_fee_cents") or 0)
            pnl -= fees
        total += pnl
        matched += 1
    return total, matched, considered


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
    sg_a: list[dict[str, Any]],
    sg_b: list[dict[str, Any]],
    eq_a: list[dict[str, Any]],
    eq_b: list[dict[str, Any]],
    end: dt.datetime,
) -> dict[str, Any]:
    include_fees = bool(oc.get("include_fees_in_score", True))
    regime_h = float(oc.get("regime_lookback_hours") or 6)
    sa = _signals_sorted_desc(sg_a)
    sb = _signals_sorted_desc(sg_b)
    st_a = [t for t in tr_a if str(t.get("status") or "").lower() == "settled" and t.get("pnl_cents") is not None]
    st_b = [t for t in tr_b if str(t.get("status") or "").lower() == "settled" and t.get("pnl_cents") is not None]
    _, rules_a = _ensure_lab_rules(cfg, BRANCH_LAB_A)
    _, rules_b = _ensure_lab_rules(cfg, BRANCH_LAB_B)
    rep_a = _replay_pnl_under_rules(st_a, rules_a, sa, include_fees_in_score=include_fees)
    rep_b = _replay_pnl_under_rules(st_b, rules_b, sb, include_fees_in_score=include_fees)
    lab_a = cfg.get("lab_a") if isinstance(cfg.get("lab_a"), dict) else {}
    lab_b = cfg.get("lab_b") if isinstance(cfg.get("lab_b"), dict) else {}
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
        "optimizer_guards": {
            "min_trades_for_optimize": oc.get("min_trades_for_optimize"),
            "min_profitable_trades": oc.get("min_profitable_trades"),
            "max_bet_fraction": oc.get("max_bet_fraction"),
            "optimize_bet_size": oc.get("optimize_bet_size"),
            "backtest_proposals": oc.get("backtest_proposals"),
        },
    }


def _ensure_lab_rules(cfg: dict[str, Any], branch: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    lk = "lab_a" if branch == BRANCH_LAB_A else "lab_b"
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
        else:
            cur_minm = min(cur_minm, minm)
        if cur_maxm < cur_minm:
            cur_maxm = cur_minm
        nr["min_prob"] = round(lo, 4)
        nr["max_prob"] = round(hi, 4)
        nr["min_minutes_left"] = int(cur_minm)
        nr["max_minutes_left"] = int(cur_maxm)
        out.append(nr)
    return out


def _history_item(*, at_iso: str, branch: str, style: str, reason: str, before_floor: int, after_floor: int, before_minm: int, after_minm: int) -> dict[str, Any]:
    lab = "Lab A" if branch == BRANCH_LAB_A else "Lab B"
    return {
        "id": uuid4().hex,
        "created_at": at_iso,
        "branch": branch,
        "lab_label": lab,
        "style": style,
        "reason": reason,
        "summary": f"{lab} {style}: YES floor {before_floor}% -> {after_floor}%, min minutes {before_minm} -> {after_minm}",
        "before": {"yes_floor_pct": before_floor, "min_minutes_left": before_minm},
        "after": {"yes_floor_pct": after_floor, "min_minutes_left": after_minm},
    }


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
    if branch == BRANCH_LAB_A and not bool(oc.get("lab_a_enabled", True)):
        return None
    if branch == BRANCH_LAB_B and not bool(oc.get("lab_b_enabled", True)):
        return None
    settled = [t for t in trades if str(t.get("status") or "").lower() == "settled" and t.get("pnl_cents") is not None]
    min_tr = max(2, _safe_int(oc.get("min_trades_for_optimize"), 25))
    min_prof = max(0, _safe_int(oc.get("min_profitable_trades"), 8))
    if len(settled) < min_tr:
        return None
    profitable_n = sum(1 for t in settled if int(t.get("pnl_cents") or 0) > 0)
    if profitable_n < min_prof:
        return None

    sig_idx = _index_signals_by_ticker(signals)
    floor_key = "lab_a_yes_floor_pct" if branch == BRANCH_LAB_A else "lab_b_yes_floor_pct"
    mins_key = "lab_a_min_minutes_left" if branch == BRANCH_LAB_A else "lab_b_min_minutes_left"
    cur_floor = max(1, min(99, _safe_int(oc.get(floor_key), 57 if branch == BRANCH_LAB_A else 55)))
    cur_mins = max(0, _safe_int(oc.get(mins_key), 5 if branch == BRANCH_LAB_A else 3))
    step_pct = max(1, min(5, _safe_int(oc.get("threshold_step_pct"), 1)))
    step_m = max(1, min(5, _safe_int(oc.get("minute_step"), 1)))
    loss_trigger = max(2, min(12, _safe_int(oc.get("loss_streak_trigger"), 3)))
    style = _branch_style(oc, branch)

    losses_at_threshold = 0
    for t in settled[:80]:
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
        if p >= (cur_floor / 100.0):
            losses_at_threshold += 1

    if losses_at_threshold < loss_trigger:
        return None

    before_floor = cur_floor
    before_mins = cur_mins
    if style == "conservative":
        cur_floor = min(95, cur_floor + step_pct)
        cur_mins = min(30, cur_mins + step_m)
    else:
        cur_floor = max(45, cur_floor - step_pct)
        cur_mins = max(0, cur_mins - step_m)

    if cur_floor == before_floor and cur_mins == before_mins:
        return None

    lab_base, rules_base = _ensure_lab_rules(cfg, branch)
    proposed_rules = _apply_rule_thresholds(
        rules_base, yes_floor_pct=cur_floor, min_minutes_left=cur_mins, style=style
    )
    if bool(oc.get("backtest_proposals", True)):
        sig_desc = _signals_sorted_desc(signals)
        fee_flag = bool(oc.get("include_fees_in_score", True))
        base_pnl, _, _ = _replay_pnl_under_rules(
            settled, rules_base, sig_desc, include_fees_in_score=fee_flag
        )
        new_pnl, _, _ = _replay_pnl_under_rules(
            settled, proposed_rules, sig_desc, include_fees_in_score=fee_flag
        )
        if new_pnl <= base_pnl:
            return None

    lab = dict(lab_base)
    lab["rules"] = proposed_rules
    lk = "lab_a" if branch == BRANCH_LAB_A else "lab_b"
    cfg[lk] = lab
    oc[floor_key] = cur_floor
    oc[mins_key] = cur_mins
    reason = f"{losses_at_threshold} losing settled trades at/above {before_floor}% YES threshold"
    return _history_item(
        at_iso=at_iso,
        branch=branch,
        style=style,
        reason=reason,
        before_floor=before_floor,
        after_floor=cur_floor,
        before_minm=before_mins,
        after_minm=cur_mins,
    )


def _history_bet_item(
    *,
    at_iso: str,
    branch: str,
    reason: str,
    before_f: float,
    after_f: float,
) -> dict[str, Any]:
    lab = "Lab A" if branch == BRANCH_LAB_A else "Lab B"
    return {
        "id": uuid4().hex,
        "created_at": at_iso,
        "branch": branch,
        "lab_label": lab,
        "style": "bet_size",
        "reason": reason,
        "summary": f"{lab}: balance_fraction_per_window {before_f:.4f} -> {after_f:.4f}",
        "before": {"balance_fraction_per_window": before_f},
        "after": {"balance_fraction_per_window": after_f},
    }


def _apply_claude_bet_recommendations(
    *,
    cfg: dict[str, Any],
    oc: dict[str, Any],
    rec: dict[str, Any],
    tr_a: list[dict[str, Any]],
    tr_b: list[dict[str, Any]],
    at_iso: str,
) -> list[dict[str, Any]]:
    """Apply balance_fraction_per_window hints from Claude when optimize_bet_size is on and guards pass."""
    if not bool(oc.get("optimize_bet_size", True)):
        return []
    min_tr = max(2, _safe_int(oc.get("min_trades_for_optimize"), 25))
    min_prof = max(0, _safe_int(oc.get("min_profitable_trades"), 8))
    st_a = [t for t in tr_a if str(t.get("status") or "").lower() == "settled" and t.get("pnl_cents") is not None]
    st_b = [t for t in tr_b if str(t.get("status") or "").lower() == "settled" and t.get("pnl_cents") is not None]
    if len(st_a) + len(st_b) < min_tr:
        return []
    prof = sum(1 for t in st_a if int(t.get("pnl_cents") or 0) > 0) + sum(
        1 for t in st_b if int(t.get("pnl_cents") or 0) > 0
    )
    if prof < min_prof:
        return []
    max_bf = max(0.02, min(0.5, _safe_float(oc.get("max_bet_fraction"), 0.12)))
    out_hist: list[dict[str, Any]] = []
    recs = rec.get("recommendations")
    if not isinstance(recs, list):
        return []
    for item in recs:
        if not isinstance(item, dict):
            continue
        tgt = str(item.get("target") or "").strip().lower()
        field = str(item.get("field") or "").strip().lower()
        if tgt not in ("lab_a", "lab_b") or field != "balance_fraction_per_window":
            continue
        sug = item.get("suggested")
        new_f = _safe_float(sug, -1.0)
        if new_f < 0:
            continue
        new_f = max(0.01, min(max_bf, new_f))
        lab_raw = cfg.get(tgt)
        lab = dict(lab_raw) if isinstance(lab_raw, dict) else {}
        old_f = _safe_float(lab.get("balance_fraction_per_window"), 0.05)
        if abs(new_f - old_f) < 0.0008:
            continue
        lab["balance_fraction_per_window"] = round(new_f, 4)
        cfg[tgt] = lab
        br = BRANCH_LAB_A if tgt == "lab_a" else BRANCH_LAB_B
        out_hist.append(
            _history_bet_item(
                at_iso=at_iso,
                branch=br,
                reason=str(item.get("reason") or "claude_recommendation")[:500],
                before_f=old_f,
                after_f=new_f,
            )
        )
    return out_hist


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
        "branches": [BRANCH_LAB_A, BRANCH_LAB_B],
        "live_branch_forbidden": True,
        "current_config_excerpt": {
            "lab_a": cfg.get("lab_a") or {},
            "lab_b": cfg.get("lab_b") or {},
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
            "max_bet_fraction": oc.get("max_bet_fraction"),
            "optimize_bet_size": oc.get("optimize_bet_size"),
            "include_fees_in_score": oc.get("include_fees_in_score"),
            "min_trades_for_optimize": oc.get("min_trades_for_optimize"),
            "min_profitable_trades": oc.get("min_profitable_trades"),
        },
        "recent_trades": trades,
        "recent_signals": signals,
        "output_schema": {
            "summary": "string",
            "recommendations": [
                {
                    "target": "live|lab_a|lab_b",
                    "field": "string (e.g. balance_fraction_per_window, lab_yes_floor_pct)",
                    "current": "any",
                    "suggested": "any",
                    "reason": "string",
                    "confidence": "low|medium|high",
                }
            ],
            "trend_notes": ["string"],
        },
    }


async def run_optimizer_once(store: Store, *, force: bool = False) -> dict[str, Any]:
    cfg = await store.load_config()
    oc = _norm_opt_cfg(_opt_cfg(cfg))
    if not force and not bool(oc.get("enabled")):
        return {"ok": False, "skipped": True, "reason": "optimizer_disabled"}
    lookback_h = max(1, min(24 * 30, int(oc.get("lookback_hours") or 72)))
    max_rows = max(100, min(10000, int(oc.get("max_rows_per_table") or 5000)))
    end = _utc_now()
    start = end - dt.timedelta(hours=lookback_h)
    start_iso = _iso(start)
    end_iso = _iso(end)

    # Hard guardrail: optimizer reads only lab_a/lab_b rows.
    tr_a = await store.query_table("trades", branch=BRANCH_LAB_A, mode="simulate", start_at=start_iso, end_at=end_iso, limit=max_rows)
    tr_b = await store.query_table("trades", branch=BRANCH_LAB_B, mode="simulate", start_at=start_iso, end_at=end_iso, limit=max_rows)
    sg_a = await store.query_table("signals", branch=BRANCH_LAB_A, mode="simulate", start_at=start_iso, end_at=end_iso, limit=max_rows)
    sg_b = await store.query_table("signals", branch=BRANCH_LAB_B, mode="simulate", start_at=start_iso, end_at=end_iso, limit=max_rows)

    # Adaptive auto-correct loop: adjust per-lab YES floor/time guardrails when losses cluster.
    changes: list[dict[str, Any]] = []
    ca = _apply_adaptive_lab_tuning(
        cfg=cfg, oc=oc, branch=BRANCH_LAB_A, trades=tr_a, signals=sg_a, at_iso=end_iso
    )
    if ca:
        changes.append(ca)
    cb = _apply_adaptive_lab_tuning(
        cfg=cfg, oc=oc, branch=BRANCH_LAB_B, trades=tr_b, signals=sg_b, at_iso=end_iso
    )
    if cb:
        changes.append(cb)
    if changes:
        hist = oc.get("change_history")
        old_hist = hist if isinstance(hist, list) else []
        lim = max(20, min(500, _safe_int(oc.get("max_history"), 120)))
        oc["change_history"] = [*changes, *old_hist][:lim]
        oc["last_change_at"] = end_iso
        cfg["optimizer"] = oc
        await store.save_config(cfg)

    key = env.anthropic_api_key.strip()
    if not key:
        oc["last_run_at"] = end_iso
        oc["last_status"] = "ok_adaptive_only"
        oc["last_error"] = ""
        cfg["optimizer"] = oc
        await store.save_config(cfg)
        return {
            "ok": True,
            "adaptive_only": True,
            "changes_applied": len(changes),
            "bet_fraction_changes": 0,
            "window_start": start_iso,
            "window_end": end_iso,
        }

    eq_a = await store.equity_series(limit=500, branch=BRANCH_LAB_A)
    eq_b = await store.equity_series(limit=500, branch=BRANCH_LAB_B)
    metrics = _build_metrics_context(
        cfg=cfg,
        oc=oc,
        tr_a=tr_a,
        tr_b=tr_b,
        sg_a=sg_a,
        sg_b=sg_b,
        eq_a=eq_a,
        eq_b=eq_b,
        end=end,
    )
    payload = _build_payload(
        cfg=cfg, trades=[*tr_a, *tr_b], signals=[*sg_a, *sg_b], metrics=metrics, oc=oc
    )
    model = str(oc.get("model") or "claude-sonnet-4-5")
    body = {
        "model": model,
        "max_tokens": 2200,
        "temperature": 0.2,
        "system": (
            "You are a quant assistant for simulation only (lab_a / lab_b). Never use live-branch data. "
            "Use performance_metrics: per-rule win rates, replay PnL under current rules, equity slopes, and regime buckets. "
            "When optimize_bet_size is true, you may emit recommendations with "
            "field=balance_fraction_per_window and target lab_a or lab_b; keep suggested values within "
            "0.01 and the given max_bet_fraction. "
            "Return concise JSON only, following the provided output_schema."
        ),
        "messages": [{"role": "user", "content": json.dumps(payload)}],
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
    rec = {"summary": "No summary", "recommendations": [], "trend_notes": []}
    if txt:
        try:
            rec = json.loads(txt)
        except json.JSONDecodeError:
            rec = {"summary": txt[:500], "recommendations": [], "trend_notes": []}
    rid = await store.insert_optimizer_recommendation(
        created_at=_iso(end),
        window_start=start_iso,
        window_end=end_iso,
        source_branches=[BRANCH_LAB_A, BRANCH_LAB_B],
        summary=str(rec.get("summary") or "")[:2000],
        recommendation_json=rec if isinstance(rec, dict) else {"raw": rec},
        raw_json=out if isinstance(out, dict) else None,
    )
    bet_hist = _apply_claude_bet_recommendations(
        cfg=cfg, oc=oc, rec=rec if isinstance(rec, dict) else {}, tr_a=tr_a, tr_b=tr_b, at_iso=_iso(end)
    )
    if bet_hist:
        hist2 = oc.get("change_history")
        old2 = hist2 if isinstance(hist2, list) else []
        lim2 = max(20, min(500, _safe_int(oc.get("max_history"), 120)))
        oc["change_history"] = [*bet_hist, *old2][:lim2]
        oc["last_change_at"] = _iso(end)

    oc["last_run_at"] = _iso(end)
    oc["last_status"] = "ok"
    oc["last_error"] = ""
    cfg["optimizer"] = oc
    await store.save_config(cfg)
    return {
        "ok": True,
        "id": rid,
        "window_start": start_iso,
        "window_end": end_iso,
        "changes_applied": len(changes),
        "bet_fraction_changes": len(bet_hist),
    }

