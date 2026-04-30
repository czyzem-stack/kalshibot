from __future__ import annotations

import math
from typing import Any

BRANCH_LIVE = "live"
BRANCH_LAB_A = "lab_a"
BRANCH_LAB_B = "lab_b"
BRANCH_LAB_C = "lab_c"
BRANCH_LAB_D = "lab_d"
BRANCH_LAB_E = "lab_e"
BRANCH_LABS = (BRANCH_LAB_A, BRANCH_LAB_B, BRANCH_LAB_C, BRANCH_LAB_D, BRANCH_LAB_E)
# LABS BREEDING v0.1 IMPROVEMENT — real active children + stronger competitive traits + better toasts.
# Six SQLite-backed child branches (invisible to dashboard UI); each has its own TradingEngine (on unless cleared).
BRANCH_CHILD_1 = "lab_child_1"
BRANCH_CHILD_2 = "lab_child_2"
BRANCH_CHILD_3 = "lab_child_3"
BRANCH_CHILD_4 = "lab_child_4"
BRANCH_CHILD_5 = "lab_child_5"
BRANCH_CHILD_6 = "lab_child_6"
BRANCH_CHILD_LABS = (
    BRANCH_CHILD_1,
    BRANCH_CHILD_2,
    BRANCH_CHILD_3,
    BRANCH_CHILD_4,
    BRANCH_CHILD_5,
    BRANCH_CHILD_6,
)
# All paper lab keys in config JSON (parents + breeding children).
ALL_CFG_LAB_KEYS: tuple[str, ...] = BRANCH_LABS + BRANCH_CHILD_LABS
# Breeding parents only (Lab A is staging / adoption — see ``lab_breeding``).
BRANCH_BREEDERS = (BRANCH_LAB_B, BRANCH_LAB_C, BRANCH_LAB_D, BRANCH_LAB_E)
# One child genome row per slot (each row maps to a real ``lab_child_*`` engine branch).
LAB_BREEDING_MAX_CHILD_SLOTS = 6
LAB_BREEDING_INTERNAL_MAX_SLOTS = 10

# Protected flag: when True, the Live engine uses paper / simulated order flow. Canonical JSON key;
# `simulate` is still written for backward compatibility and mirrors this value.
LIVE_PAPER_TRADING_KEY = "live_paper_trading"


def live_paper_trading_enabled(full_cfg: dict[str, Any]) -> bool:
    """
    Return whether Live is in paper (sim) mode. Prefer ``live_paper_trading``; fall back to legacy ``simulate``.
    """
    if LIVE_PAPER_TRADING_KEY in full_cfg:
        return bool(full_cfg.get(LIVE_PAPER_TRADING_KEY))
    return bool(full_cfg.get("simulate", True))


def sync_live_paper_trading_keys(cfg: dict[str, Any]) -> None:
    """
    Keep ``live_paper_trading`` and legacy ``simulate`` in lockstep whenever either is read or about to be persisted.
    If only one is present, it defines the value; if neither, default to paper (True).
    If both are present, ``live_paper_trading`` wins.
    """
    if LIVE_PAPER_TRADING_KEY in cfg:
        v = bool(cfg[LIVE_PAPER_TRADING_KEY])
    elif "simulate" in cfg:
        v = bool(cfg["simulate"])
    else:
        v = True
    cfg[LIVE_PAPER_TRADING_KEY] = v
    cfg["simulate"] = v


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
    "rules_high_vol",
    "rules_low_vol",
    "rules_event",
    "active_regime",
    "no_bet_when_yes_below_pct",
    "dev_sim_yes_implied_ge_pct",
    "swing_exit_implied_drop_pct",
    "enable_patient_stop_loss",
    "stop_loss_trigger_pct",
    "min_hold_minutes_before_stop",
    "paper_fee_bps",
    "paper_fee_model",
    "kalshi_fee_multiplier",
    # Breeder council tuning (Labs B–E): merged onto branch cfg for engines + UI.
    "council_influence_weight_pct",
    "breeder_personality",
)


def _lab_key_for_branch(branch: str) -> str | None:
    b = str(branch or "").strip().lower()
    if b == BRANCH_LIVE:
        return None
    if b in ALL_CFG_LAB_KEYS:
        return b
    return None


def fleet_visible_paper_start_cents(full_cfg: dict[str, Any]) -> int:
    """
    Sum of paper-equity start bases for **Live** (only when Live is in paper mode) plus **Labs A–E**.

    Used as the dashboard denominator for ``committed_pct_of_fleet_start`` so open premium on one branch
    is shown as a fraction of combined configured paper capital, not only that branch's start.
    """
    sync_live_paper_trading_keys(full_cfg)
    total = 0
    if live_paper_trading_enabled(full_cfg):
        total += lab_paper_equity_start_cents(full_cfg, BRANCH_LIVE)
    for lk in BRANCH_LABS:
        total += lab_paper_equity_start_cents(full_cfg, lk)
    return max(0, total)


def lab_paper_equity_start_cents(full_cfg: dict[str, Any], branch: str) -> int:
    """
    Paper **book / MTM** baseline for a branch — must match the dashboard rollups
    (``_enrich_strategy_metrics`` / ``_refresh_paper_mtm_from_marks``).

    When ``paper_lifetime_basis_cents`` is set on a lab (re-seeds / auto-reset), that cumulative
    basis is used so chart snapshots and the intraday tail do not diverge from tiles.
    Otherwise falls back to per-lab ``paper_balance_cents`` or the global default.
    """
    lab_key = _lab_key_for_branch(branch)
    if lab_key is None:
        try:
            return max(0, int(full_cfg.get("paper_balance_cents") or 500_000))
        except (TypeError, ValueError):
            return 500_000
    lab = full_cfg.get(lab_key) if isinstance(full_cfg.get(lab_key), dict) else {}
    lt = lab.get("paper_lifetime_basis_cents")
    if lt is not None:
        try:
            return max(0, int(lt))
        except (TypeError, ValueError):
            pass
    try:
        return max(
            0,
            int(lab.get("paper_balance_cents") or full_cfg.get("paper_balance_cents") or 500_000),
        )
    except (TypeError, ValueError):
        return 500_000


def pulse_effective_config(full_cfg: dict[str, Any], branch: str) -> dict[str, Any]:
    """Config used for UI pulse / dry-run (does not require engine_running)."""
    if not isinstance(full_cfg, dict):
        from .persistence import default_bot_config

        return dict(default_bot_config())
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


def effective_live_engine_running(full_cfg: dict[str, Any]) -> bool:
    """
    Whether the Live branch should tick.

    A **missing** top-level ``engine_running`` defaults to **on** in paper mode so Kalshi public sim matches breeder
    labs out of the box; it defaults **off** when ``live_paper_trading`` is false (real money) until explicitly enabled.
    """
    if not isinstance(full_cfg, dict):
        return False
    return _coerce_engine_running_flag(
        full_cfg.get("engine_running"),
        default_if_missing=live_paper_trading_enabled(full_cfg),
    )


def effective_parent_lab_engine_running(lab: dict[str, Any] | None, lab_key: str) -> bool:
    """
    Parent lab ``lab_a``…``lab_e`` engines.

    A **missing** ``engine_running`` defaults **on** for every parent lab (matches ``default_bot_config`` breeders + staging).
    Set ``engine_running: false`` explicitly to pause a branch.
    """
    raw = lab.get("engine_running") if isinstance(lab, dict) else None
    default_missing = lab_key in BRANCH_LABS
    return _coerce_engine_running_flag(raw, default_if_missing=default_missing)


def _coerce_engine_running_flag(
    raw: Any,
    *,
    default_if_missing: bool,
) -> bool:
    """
    Config may store a bool, 0/1, or string from clients. A missing key uses ``default_if_missing``
    (Live/parent lab: off; ``lab_child_*`` without key: on — see ``merge_branch_config``).
    """
    if raw is None:
        return default_if_missing
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return raw != 0
    s = str(raw).strip().lower()
    if s in ("", "0", "false", "no", "off", "null", "none"):
        return False
    if s in ("1", "true", "yes", "on"):
        return True
    return bool(s)


def merge_branch_config(full_cfg: dict[str, Any], branch: str) -> dict[str, Any] | None:
    """Build effective config for one engine branch. Returns None if that branch should not run."""
    if not isinstance(full_cfg, dict):
        return None
    if branch == BRANCH_LIVE:
        if not effective_live_engine_running(full_cfg):
            return None
        out = dict(full_cfg)
        out["_branch"] = BRANCH_LIVE
        sim = live_paper_trading_enabled(full_cfg)
        out["_simulate_orders"] = sim
        out["_trade_mode"] = "simulate" if sim else "live"
        apply_patient_stop_loss_defaults_to_merged_cfg(full_cfg, branch, out)
        return out

    lab_key = _lab_key_for_branch(branch)
    if lab_key is not None:
        lab = full_cfg.get(lab_key)
        # Breeding child engines (``lab_child_*``): on by default; only an explicit ``engine_running: false``
        # (e.g. pool eviction / cleared slot) stops the branch. Parent labs still require ``engine_running``.
        if lab_key in BRANCH_CHILD_LABS:
            if not isinstance(lab, dict):
                lab = {}
            if not _coerce_engine_running_flag(
                lab.get("engine_running"), default_if_missing=True
            ):
                return None
        elif not isinstance(lab, dict) or not effective_parent_lab_engine_running(lab, lab_key):
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
        apply_patient_stop_loss_defaults_to_merged_cfg(full_cfg, branch, out)
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


def enable_patient_stop_loss_from_cfg(cfg: dict[str, Any]) -> bool:
    """Paper sim: time + fee-aware drawdown exit. Default on when key missing."""
    raw = cfg.get("enable_patient_stop_loss")
    if raw is None or raw == "":
        return True
    if isinstance(raw, bool):
        return raw
    s = str(raw).strip().lower()
    if s in ("0", "false", "no", "off"):
        return False
    return bool(raw)


def stop_loss_trigger_pct_from_cfg(cfg: dict[str, Any]) -> float:
    """
    Negative percent vs entry premium (e.g. -8.0 = exit when unrealized loss reaches ~8% of stake after sell fees).
    Clamped to [-20, -2].
    """
    raw = cfg.get("stop_loss_trigger_pct")
    if raw is None or raw is False or raw == "":
        return -8.0
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return -8.0
    if v != v:  # NaN
        return -8.0
    if v > 0:
        v = -abs(v)
    return max(-20.0, min(-2.0, v))


def min_hold_minutes_before_stop_from_cfg(cfg: dict[str, Any]) -> int:
    try:
        v = int(cfg.get("min_hold_minutes_before_stop") or 30)
    except (TypeError, ValueError):
        v = 30
    return max(5, min(120, v))


def ensure_patient_stop_loss_on_branch_dict(d: dict[str, Any]) -> None:
    """Mutate a lab or live trading dict in place: normalize and clamp patient stop-loss keys."""
    d["enable_patient_stop_loss"] = enable_patient_stop_loss_from_cfg(d)
    d["stop_loss_trigger_pct"] = stop_loss_trigger_pct_from_cfg(d)
    d["min_hold_minutes_before_stop"] = min_hold_minutes_before_stop_from_cfg(d)


# Per-branch defaults when keys are absent from stored config (A/B testing across labs).
_PATIENT_STOP_DEFAULTS: dict[str, tuple[bool, float, int]] = {
    BRANCH_LIVE: (True, -10.0, 45),
    BRANCH_LAB_A: (True, -6.0, 20),
    BRANCH_LAB_B: (True, -8.0, 30),
    BRANCH_LAB_C: (True, -12.0, 60),
    BRANCH_LAB_D: (True, -7.0, 25),
    BRANCH_LAB_E: (True, -8.5, 28),
}
for _cb in BRANCH_CHILD_LABS:
    _PATIENT_STOP_DEFAULTS[_cb] = (True, -9.0, 22)


def apply_patient_stop_loss_defaults_to_merged_cfg(full_cfg: dict[str, Any], branch: str, out: dict[str, Any]) -> None:
    """
    After ``merge_branch_config`` builds ``out``, fill patient stop-loss keys from the branch lab dict / live root,
    falling back to per-branch defaults (not Live globals on lab rows).
    """
    defs = _PATIENT_STOP_DEFAULTS.get(branch, _PATIENT_STOP_DEFAULTS[BRANCH_LIVE])
    lab_key = _lab_key_for_branch(branch)
    if branch == BRANCH_LIVE:
        src: dict[str, Any] = full_cfg if isinstance(full_cfg, dict) else {}
    else:
        raw = full_cfg.get(lab_key or "") if lab_key else None
        src = raw if isinstance(raw, dict) else {}

    def pick(k: str, default: Any) -> Any:
        if k in src and src[k] is not None and src[k] != "":
            return src[k]
        return default

    out["enable_patient_stop_loss"] = pick("enable_patient_stop_loss", defs[0])
    out["stop_loss_trigger_pct"] = pick("stop_loss_trigger_pct", defs[1])
    out["min_hold_minutes_before_stop"] = pick("min_hold_minutes_before_stop", defs[2])
    ensure_patient_stop_loss_on_branch_dict(out)


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
    {"key": "min_contracts", "label": "Min position size (contracts)", "lo": 1.0, "hi": 100.0},
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
        ("lab_d", BRANCH_LAB_D),
        ("lab_e", BRANCH_LAB_E),
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
