from __future__ import annotations

import random

from .branch_config import (
    BRANCH_LAB_A,
    MAX_BALANCE_FRACTION_PER_WINDOW,
    MIN_BALANCE_FRACTION_PER_WINDOW,
)
from .persistence import Store


async def maybe_auto_optimize(store: Store) -> None:
    """Tiny rule-based tuner for Lab A paper only (not an LLM). Nudges balance fraction from recent lab_a PnL."""
    cfg = await store.load_config()
    lab = cfg.get("lab_a")
    if not isinstance(lab, dict) or not lab.get("auto_optimize"):
        return

    oc = cfg.get("optimizer") if isinstance(cfg.get("optimizer"), dict) else {}
    try:
        min_settled = max(6, int(oc.get("min_trades_for_optimize") or 25))
    except (TypeError, ValueError):
        min_settled = 25

    trades = await store.recent_trades(limit=400)
    settled = [
        t
        for t in trades
        if str(t.get("branch") or "live") == BRANCH_LAB_A
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
    cfg["lab_a"] = lab
    await store.save_config(cfg)

