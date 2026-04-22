from __future__ import annotations

from typing import Any

BRANCH_LIVE = "live"
BRANCH_LAB_A = "lab_a"
BRANCH_LAB_B = "lab_b"
# Backward-compatible alias used by older frontend/API clients.
BRANCH_SIM_LAB = BRANCH_LAB_A
BRANCH_LABS = (BRANCH_LAB_A, BRANCH_LAB_B)

SIM_LAB_OVERLAY_KEYS = (
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
    if branch in (BRANCH_LAB_A, BRANCH_SIM_LAB):
        return "lab_a"
    if branch == BRANCH_LAB_B:
        return "lab_b"
    return None


def pulse_effective_config(full_cfg: dict[str, Any], branch: str) -> dict[str, Any]:
    """Config used for UI pulse / dry-run (does not require engine_running)."""
    lab_key = _lab_key_for_branch(branch)
    if lab_key is None:
        return dict(full_cfg)
    raw_lab = full_cfg.get(lab_key)
    lab: dict[str, Any] = raw_lab if isinstance(raw_lab, dict) else {}
    out = dict(full_cfg)
    for k in SIM_LAB_OVERLAY_KEYS:
        if k not in lab:
            continue
        v = lab[k]
        if v is None:
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
        for k in SIM_LAB_OVERLAY_KEYS:
            if k not in lab:
                continue
            v = lab[k]
            if v is None:
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
    a paper swing exit. 0 = disabled. Sim lab may override via sim_lab.swing_exit_implied_drop_pct.
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
    Sim lab may override via sim_lab.paper_fee_bps.
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
