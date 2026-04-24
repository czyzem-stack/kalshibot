from __future__ import annotations

import math
from typing import Any

BRANCH_LIVE = "live"
BRANCH_LAB_A = "lab_a"
BRANCH_LAB_B = "lab_b"
BRANCH_LAB_C = "lab_c"
BRANCH_LABS = (BRANCH_LAB_A, BRANCH_LAB_B, BRANCH_LAB_C)

# Same bounds as ``BotConfigPayload.balance_fraction_per_window`` (API / dashboard).
MIN_BALANCE_FRACTION_PER_WINDOW = 0.0001
MAX_BALANCE_FRACTION_PER_WINDOW = 1.0


def clamp_balance_fraction_per_window(raw: Any) -> float:
    try:
        v = float(raw)
    except (TypeError, ValueError):
        v = 0.03
    if v != v:  # NaN
        v = 0.03
    return max(MIN_BALANCE_FRACTION_PER_WINDOW, min(MAX_BALANCE_FRACTION_PER_WINDOW, v))


LAB_BRANCH_OVERLAY_KEYS = (
    "balance_fraction_per_window",
    "window_minutes",
    "poll_seconds",
    "only_yes_subtitle_contains",
    "exclude_yes_subtitle_contains",
    "min_contracts",
    "paper_balance_cents",
    "assets",
    "rules",
    "no_bet_when_yes_below_pct",
    "dev_sim_yes_implied_ge_pct",
    "swing_exit_implied_drop_pct",
    "paper_fee_bps",
    "paper_fee_model",
    "kalshi_fee_multiplier",
)


def _lab_key_for_branch(branch: str) -> str | None:
    if branch == BRANCH_LAB_A:
        return "lab_a"
    if branch == BRANCH_LAB_B:
        return "lab_b"
    if branch == BRANCH_LAB_C:
        return "lab_c"
    return None


def pulse_effective_config(full_cfg: dict[str, Any], branch: str) -> dict[str, Any]:
    """Config used for UI pulse / dry-run (does not require engine_running)."""
    lab_key = _lab_key_for_branch(branch)
    if lab_key is None:
        return dict(full_cfg)
    raw_lab = full_cfg.get(lab_key)
    lab: dict[str, Any] = raw_lab if isinstance(raw_lab, dict) else {}
    out = dict(full_cfg)
    for k in LAB_BRANCH_OVERLAY_KEYS:
        if k not in lab:
            continue
        v = lab[k]
        if v is None:
            continue
        # Empty per-lab ``assets`` must not wipe the global asset universe (would scan 0 markets).
        if k == "assets" and isinstance(v, dict) and len(v) == 0:
            continue
        out[k] = v
    return out


def merge_branch_config(full_cfg: dict[str, Any], branch: str) -> dict[str, Any] | None:
    """Build effective config for one engine branch. Returns None if that branch should not run."""
    if branch == BRANCH_LIVE:
        if not full_cfg.get("engine_running"):
            return None
        out = dict(full_cfg)
        out["_branch"] = BRANCH_LIVE
        sim = bool(full_cfg.get("simulate"))
        out["_simulate_orders"] = sim
        out["_trade_mode"] = "simulate" if sim else "live"
        return out

    lab_key = _lab_key_for_branch(branch)
    if lab_key is not None:
        lab = full_cfg.get(lab_key)
        if not isinstance(lab, dict) or not lab.get("engine_running"):
            return None
        out = dict(full_cfg)
        for k in LAB_BRANCH_OVERLAY_KEYS:
            if k not in lab:
                continue
            v = lab[k]
            if v is None:
                continue
            if k == "assets" and isinstance(v, dict) and len(v) == 0:
                continue
            out[k] = v
        out["_branch"] = branch
        out["_simulate_orders"] = True
        out["_trade_mode"] = "simulate"
        return out

    return None


def effective_swing_exit_implied_drop_pct(full_cfg: dict[str, Any], branch: str) -> float:
    """
    Minimum adverse move in implied YES (percentage points, e.g. 50.0 = 0.50 probability) to trigger
    a paper swing exit. 0 = disabled. Lab branches may override via ``lab_* .swing_exit_implied_drop_pct``.
    """
    lab_key = _lab_key_for_branch(branch)
    raw_swing = full_cfg.get(lab_key) if lab_key else None
    lab: dict[str, Any] = raw_swing if isinstance(raw_swing, dict) else {}
    if lab_key is not None and lab.get("swing_exit_implied_drop_pct") is not None:
        raw = lab.get("swing_exit_implied_drop_pct")
    else:
        raw = full_cfg.get("swing_exit_implied_drop_pct")
    if raw is None or raw is False:
        return 0.0
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return 0.0
    if v <= 0:
        return 0.0
    return max(0.0, min(95.0, v))


def effective_trading_cfg_for_fees(full_cfg: dict[str, Any], branch: str) -> dict[str, Any]:
    """Branch-merged config when the engine runs that branch; otherwise pulse-style overlay (for settlement)."""
    merged = merge_branch_config(full_cfg, branch)
    if merged is not None:
        return merged
    return pulse_effective_config(full_cfg, branch)


def normalize_paper_fee_model(raw: Any) -> str:
    """
    ``kalshi_taker`` / ``kalshi_maker`` — Kalshi quadratic schedule (see fee schedule PDF).
    ``bps`` — legacy ``paper_fee_bps`` on premium / proceeds.
    ``none`` — no modeled fees.
    """
    if raw is None or raw is False:
        return "bps"
    s = str(raw).strip().lower().replace("-", "_")
    if not s:
        return "bps"
    if s in ("off", "no", "false", "0"):
        return "none"
    if s in ("kalshi", "kalshi_taker", "taker"):
        return "kalshi_taker"
    if s in ("kalshi_maker", "maker"):
        return "kalshi_maker"
    if s in ("bps", "legacy", "flat_bps"):
        return "bps"
    if s == "none":
        return "none"
    return "bps"


def paper_fee_model_from_cfg(cfg: dict[str, Any]) -> str:
    return normalize_paper_fee_model(cfg.get("paper_fee_model"))


def paper_fee_bps_from_cfg(cfg: dict[str, Any]) -> float:
    """Parsed bps from an already branch-merged config dict (used in ``handle_market``)."""
    raw = cfg.get("paper_fee_bps")
    if raw is None or raw is False:
        return 0.0
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return 0.0
    if v <= 0:
        return 0.0
    return max(0.0, min(500.0, v))


def kalshi_fee_multiplier_from_cfg(cfg: dict[str, Any]) -> float:
    raw = cfg.get("kalshi_fee_multiplier")
    if raw is None or raw is False:
        return 1.0
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return 1.0
    return max(0.0, min(10.0, v))


def effective_paper_fee_bps(full_cfg: dict[str, Any], branch: str) -> float:
    """
    Paper fee rate in basis points applied to each simulated execution notional.
    Example: 20 bps = 0.20%.
    Lab branches may override via ``lab_* .paper_fee_bps``.
    """
    return paper_fee_bps_from_cfg(effective_trading_cfg_for_fees(full_cfg, branch))


def resolve_paper_fee_model(extra: dict[str, Any], full_cfg: dict[str, Any], branch: str) -> str:
    """
    Prefer ``paper_fee_model`` stored on the trade at entry.

    Older SQLite rows pre-date this field and used the flat ``paper_fee_bps`` model only.
    """
    if extra.get("paper_fee_model") is not None:
        return normalize_paper_fee_model(extra.get("paper_fee_model"))
    return "bps"


def resolve_kalshi_fee_multiplier(extra: dict[str, Any], full_cfg: dict[str, Any], branch: str) -> float:
    if extra.get("kalshi_fee_multiplier") is not None:
        try:
            return max(0.0, min(10.0, float(extra["kalshi_fee_multiplier"])))
        except (TypeError, ValueError):
            pass
    return kalshi_fee_multiplier_from_cfg(effective_trading_cfg_for_fees(full_cfg, branch))


# --- Dashboard optimizer radar (per-branch overlays + focus spokes) ---

RADAR_AXIS_DEF: list[dict[str, Any]] = [
    {"key": "bet_frac", "label": "Bet / window", "lo": 0.0, "hi": 0.22},
    {"key": "window_min", "label": "Window (min)", "lo": 5.0, "hi": 120.0},
    {"key": "poll_sec", "label": "Poll (s)", "lo": 3.0, "hi": 120.0},
    {"key": "yes_floor", "label": "YES floor (rules)", "lo": 35.0, "hi": 95.0},
    {"key": "rule_min_m", "label": "Rule min min left", "lo": 0.0, "hi": 30.0},
    {"key": "min_contracts", "label": "Min contracts", "lo": 1.0, "hi": 100.0},
    {"key": "no_bet_cut", "label": "NO-bet below %", "lo": 0.0, "hi": 80.0},
    {"key": "dev_yes_pct", "label": "Dev sim YES %", "lo": 0.0, "hi": 95.0},
    {"key": "swing_drop", "label": "Swing exit %", "lo": 0.0, "hi": 60.0},
    {"key": "fee_bps", "label": "Paper fee bps", "lo": 0.0, "hi": 100.0},
    {"key": "fee_mult", "label": "Fee multiplier", "lo": 0.5, "hi": 2.5},
    {"key": "bank_log", "label": "Bankroll (log10 ¢)", "lo": 4.0, "hi": 7.2},
    {"key": "opt_loss", "label": "Loss streak #", "lo": 1.0, "hi": 12.0},
    {"key": "opt_thresh", "label": "Threshold step %", "lo": 1.0, "hi": 5.0},
    {"key": "opt_minute_step", "label": "Minute step", "lo": 1.0, "hi": 5.0},
    {"key": "opt_min_tr", "label": "Min trades to tune", "lo": 2.0, "hi": 80.0},
    {"key": "opt_regime_h", "label": "Regime lookback h", "lo": 1.0, "hi": 72.0},
]

RADAR_AXIS_KEYS: tuple[str, ...] = tuple(str(d["key"]) for d in RADAR_AXIS_DEF)


def _safe_float_radar(raw: Any, default: float) -> float:
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return default
    if v != v:  # NaN
        return default
    return v


def _safe_int_radar(raw: Any, default: int) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _trading_radar_raw_from_merged(m: dict[str, Any]) -> dict[str, float]:
    rules = m.get("rules") if isinstance(m.get("rules"), list) else []
    yes_hi = 0.0
    tight_min_m = 99.0
    for r in rules:
        if not isinstance(r, dict):
            continue
        if str(r.get("side") or "").lower() == "no":
            continue
        mp = _safe_float_radar(r.get("min_prob"), 0.0)
        if mp <= 0:
            continue
        yes_hi = max(yes_hi, mp * 100.0)
        mm = _safe_float_radar(r.get("min_minutes_left"), 0.0)
        tight_min_m = min(tight_min_m, mm)
    if tight_min_m >= 98.0:
        tight_min_m = 0.0
    bf = _safe_float_radar(m.get("balance_fraction_per_window"), 0.03)
    wm = _safe_float_radar(m.get("window_minutes"), 12.0)
    poll = _safe_float_radar(m.get("poll_seconds"), 8.0)
    mc = _safe_float_radar(m.get("min_contracts"), 1.0)
    raw_nb = m.get("no_bet_when_yes_below_pct")
    nb = _safe_float_radar(raw_nb, 0.0) if raw_nb not in (None, "", False) else 0.0
    raw_dev = m.get("dev_sim_yes_implied_ge_pct")
    dev = _safe_float_radar(raw_dev, 0.0) if raw_dev not in (None, "", False) else 0.0
    sw = _safe_float_radar(m.get("swing_exit_implied_drop_pct"), 0.0)
    bps = _safe_float_radar(m.get("paper_fee_bps"), 0.0)
    km = _safe_float_radar(m.get("kalshi_fee_multiplier"), 1.0)
    try:
        pbc = int(m.get("paper_balance_cents") or 0)
    except (TypeError, ValueError):
        pbc = 0

    bank_log = math.log10(max(1, pbc))
    return {
        "bet_frac": bf,
        "window_min": wm,
        "poll_sec": poll,
        "yes_floor": yes_hi,
        "rule_min_m": tight_min_m,
        "min_contracts": mc,
        "no_bet_cut": nb,
        "dev_yes_pct": dev,
        "swing_drop": sw,
        "fee_bps": bps,
        "fee_mult": km,
        "bank_log": bank_log,
    }


def _optimizer_radar_scalars(opt: dict[str, Any]) -> dict[str, float]:
    return {
        "opt_loss": float(max(1, min(12, _safe_int_radar(opt.get("loss_streak_trigger"), 3)))),
        "opt_thresh": float(max(1, min(5, _safe_int_radar(opt.get("threshold_step_pct"), 2)))),
        "opt_minute_step": float(max(1, min(5, _safe_int_radar(opt.get("minute_step"), 2)))),
        "opt_min_tr": float(max(2, min(80, _safe_int_radar(opt.get("min_trades_for_optimize"), 8)))),
        "opt_regime_h": float(max(1, min(72, _safe_int_radar(opt.get("regime_lookback_hours"), 4)))),
    }


def branch_radar_profile(full_cfg: dict[str, Any], branch: str, opt: dict[str, Any] | None) -> dict[str, float]:
    """Numeric snapshot for one branch + shared optimizer slider scalars (same on every branch)."""
    oc = opt if isinstance(opt, dict) else {}
    if branch == BRANCH_LIVE:
        merged = dict(full_cfg)
    else:
        merged = pulse_effective_config(full_cfg, branch)
    tr = _trading_radar_raw_from_merged(merged)
    tr.update(_optimizer_radar_scalars(oc))
    return tr


def _norm_axis(lo: float, hi: float, v: float) -> float:
    if hi <= lo:
        return 0.0
    return max(0.0, min(100.0, (float(v) - lo) / (hi - lo) * 100.0))


def radar_norm_profile(raw: dict[str, float]) -> dict[str, float]:
    out: dict[str, float] = {}
    for ax in RADAR_AXIS_DEF:
        k = str(ax["key"])
        lo = float(ax["lo"])
        hi = float(ax["hi"])
        out[k] = _norm_axis(lo, hi, float(raw.get(k) or 0.0))
    return out


def radar_focus_from_history(
    change_history: list[Any],
    *,
    pulse_trace: list[Any] | None = None,
    n_recent: int = 20,
) -> dict[str, float]:
    """0–1 weights per axis: recent optimizer / pulse edits bias which spoke the UI highlights."""
    from collections import defaultdict

    scores: dict[str, float] = defaultdict(float)
    slice_h = change_history[-n_recent:] if len(change_history) > n_recent else list(change_history)
    w = 1.0
    for h in reversed(slice_h):
        if not isinstance(h, dict):
            continue
        bef = h.get("before") if isinstance(h.get("before"), dict) else {}
        aft = h.get("after") if isinstance(h.get("after"), dict) else {}

        def changed(kb: str) -> bool:
            return bef.get(kb) != aft.get(kb) and (aft.get(kb) is not None or bef.get(kb) is not None)

        if changed("yes_floor_pct"):
            scores["yes_floor"] += w
        if changed("min_minutes_left"):
            scores["rule_min_m"] += w
        if changed("balance_fraction_per_window"):
            scores["bet_frac"] += w
        if changed("lab_b_yes_floor_pct") or changed("lab_c_yes_floor_pct"):
            scores["yes_floor"] += w * 0.55
        if changed("lab_b_balance_fraction") or changed("lab_c_balance_fraction"):
            scores["bet_frac"] += w * 0.55
        if changed("threshold_step_pct"):
            scores["opt_thresh"] += w * 1.1
        if changed("minute_step"):
            scores["opt_minute_step"] += w * 1.1
        if changed("loss_streak_trigger"):
            scores["opt_loss"] += w * 1.1
        if changed("min_trades_for_optimize"):
            scores["opt_min_tr"] += w * 0.9
        if changed("regime_lookback_hours"):
            scores["opt_regime_h"] += w * 0.9
        w *= 0.88

    blob = ""
    if isinstance(pulse_trace, list):
        for p in pulse_trace[:8]:
            if isinstance(p, dict):
                blob += " " + str(p.get("message") or "").lower()
    if "floor" in blob or "threshold" in blob or "yes" in blob:
        scores["yes_floor"] += 0.4
    if "fraction" in blob or "bet" in blob or "balance" in blob:
        scores["bet_frac"] += 0.4
    if "minute" in blob or "min " in blob:
        scores["rule_min_m"] += 0.35
    if "loss" in blob or "streak" in blob:
        scores["opt_loss"] += 0.45
    if "regime" in blob:
        scores["opt_regime_h"] += 0.35

    mx = max(scores.values()) if scores else 0.0
    if mx <= 0:
        return {k: 0.0 for k in RADAR_AXIS_KEYS}
    return {k: min(1.0, float(scores.get(k, 0.0)) / mx) for k in RADAR_AXIS_KEYS}


def build_optimizer_radar_payload(full_cfg: dict[str, Any], opt_blk: dict[str, Any]) -> dict[str, Any]:
    """Dashboard ``optimizer_activity.radar``: per-branch normalized polygons + raw + focus."""
    opt = opt_blk if isinstance(opt_blk, dict) else {}
    ch = opt.get("change_history") if isinstance(opt.get("change_history"), list) else []
    pt = opt.get("pulse_trace") if isinstance(opt.get("pulse_trace"), list) else []
    profiles_raw: dict[str, dict[str, float]] = {}
    profiles_norm: dict[str, dict[str, float]] = {}
    for slug, br in (
        ("live", BRANCH_LIVE),
        ("lab_a", BRANCH_LAB_A),
        ("lab_b", BRANCH_LAB_B),
        ("lab_c", BRANCH_LAB_C),
    ):
        raw = branch_radar_profile(full_cfg, br, opt)
        profiles_raw[slug] = raw
        profiles_norm[slug] = radar_norm_profile(raw)
    focus = radar_focus_from_history(ch, pulse_trace=pt)
    return {
        "axes": [{"key": d["key"], "label": d["label"], "lo": d["lo"], "hi": d["hi"]} for d in RADAR_AXIS_DEF],
        "profiles_raw": profiles_raw,
        "profiles_norm": profiles_norm,
        "axis_focus": focus,
    }
