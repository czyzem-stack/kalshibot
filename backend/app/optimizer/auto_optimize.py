from __future__ import annotations

import random
from typing import Any

from ..branch_config import (
    BRANCH_LAB_A,
    BRANCH_LAB_B,
    BRANCH_LAB_C,
    BRANCH_LAB_D,
    BRANCH_LAB_E,
    MAX_BALANCE_FRACTION_PER_WINDOW,
    MIN_BALANCE_FRACTION_PER_WINDOW,
    _lab_key_for_branch,
)
from ..persistence import Store


def _trade_branch_matches_lab_row(row_branch: Any, engine_branch: str) -> bool:
    b = str(row_branch or "live").strip().lower()
    if engine_branch == BRANCH_LAB_A:
        return b in ("lab_a", "sim_lab")
    return b == engine_branch


async def maybe_auto_optimize(store: Store, branch: str) -> None:
    """Tiny rule-based tuner per lab paper (not an LLM). Nudges balance fraction from recent settled PnL."""
    br = str(branch or "").strip().lower()
    if br not in (BRANCH_LAB_A, BRANCH_LAB_B, BRANCH_LAB_C, BRANCH_LAB_D, BRANCH_LAB_E):
        return
    cfg = await store.load_config()
    lk = _lab_key_for_branch(br) or "lab_a"
    lab = cfg.get(lk)
    if not isinstance(lab, dict) or not lab.get("auto_optimize"):
        return

    oc = cfg.get("optimizer") if isinstance(cfg.get("optimizer"), dict) else {}
    try:
        min_settled = max(4, int(oc.get("min_trades_for_optimize") or 8))
    except (TypeError, ValueError):
        min_settled = 8

    trades = await store.recent_trades(limit=400)
    settled = [
        t
        for t in trades
        if _trade_branch_matches_lab_row(t.get("branch"), br)
        and t.get("pnl_cents") is not None
        and str(t.get("status") or "").lower() == "settled"
    ]
    if len(settled) < min_settled:
        return

    window = settled[:40]
    pnl = sum(int(t.get("pnl_cents") or 0) for t in window) / max(1, len(window))
    frac = float(lab.get("balance_fraction_per_window") or cfg.get("balance_fraction_per_window") or 0.03)

    step = 0.003
    if pnl > 0:
        frac = min(MAX_BALANCE_FRACTION_PER_WINDOW, frac + step)
    elif pnl < 0:
        frac = max(MIN_BALANCE_FRACTION_PER_WINDOW, frac - step)
    else:
        if random.random() < 0.2:
            frac = min(
                MAX_BALANCE_FRACTION_PER_WINDOW,
                max(MIN_BALANCE_FRACTION_PER_WINDOW, frac + random.uniform(-step, step)),
            )

    lab = dict(lab)
    lab["balance_fraction_per_window"] = round(frac, 4)
    lab["optimizer_note"] = f"mean_pnl_cents={pnl:.1f} -> fraction={frac}"
    cfg = dict(cfg)
    cfg[lk] = lab
    await store.save_config(
        cfg, history_branch="global", history_changed_by="auto_optimize", history_reason="lab_auto_tune"
    )
