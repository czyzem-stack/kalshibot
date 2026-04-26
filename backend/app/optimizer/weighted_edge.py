"""
Liquidity-scaled edge for sim ranking and fitness replay (same contract as the engine’s mid/ask
geometry, with spread-based liquidity_factor).
"""
from __future__ import annotations

import math
from typing import Any


def calculate_weighted_edge(market: dict[str, Any], rule: dict[str, Any]) -> float:
    """
    Weighted edge = (implied_mid - limit_price) * liquidity_factor

    *liquidity_factor* = max(0.1, 1.0 - spread_width * 0.8) to penalize wide books.

    ``market`` may use the same keys as a Kalshi market row: ``yes_bid_dollars``,
    ``yes_ask_dollars`` (0–1 dollars). If either side is missing, ``spread_width`` is taken from
    ``market["spread_width"]`` (0–1) or a small default of 0.02 so replay still works with only
    implied probability stored on the trade.
    """
    from ..engine import (
        dollars_to_float,
        effective_no_ask,
        implied_no_probability,
        implied_yes_probability,
        has_tradable_yes_ask,
    )

    yb = dollars_to_float(market.get("yes_bid_dollars") if "yes_bid_dollars" in market else market.get("yes_bid"))
    ya = dollars_to_float(market.get("yes_ask_dollars") if "yes_ask_dollars" in market else market.get("yes_ask"))
    sw_raw = market.get("spread_width")
    if yb is not None and ya is not None and ya >= yb:
        spread_width = float(ya) - float(yb)
    elif sw_raw is not None:
        spread_width = _safe_01(float(sw_raw))
    else:
        spread_width = 0.02
    spread_width = max(0.0, min(0.8, float(spread_width)))
    liq = max(0.1, 1.0 - (spread_width * 0.8))
    prob = implied_yes_probability(yb, ya)
    side = str(rule.get("side") or "yes").strip().lower()
    if side != "no":
        if not has_tradable_yes_ask(ya):
            if prob is None or ya is None:
                return 0.0
        if ya is None and prob is not None:
            ya = float(prob)
        if prob is None or ya is None:
            return 0.0
        edge = float(prob) - float(ya)
    else:
        na = effective_no_ask(market, yb, ya)
        p_no = implied_no_probability(yb, ya)
        if na is None or p_no is None or not (0 < float(na) < 1):
            return 0.0
        edge = float(p_no) - float(na)
    return float(edge) * liq


def _safe_01(x: float) -> float:
    if x != x:
        return 0.0
    return max(0.0, min(0.8, x))


def synthetic_orderbook_for_replay(
    prob: float,
    trade: dict[str, Any],
) -> dict[str, Any]:
    """
    Build a 0–1 orderbook for ``calculate_weighted_edge`` when replay only has implied entry prob.

    If ``extra_json`` stores bid/ask snapshot, those win; else we use a tight band around ``prob``.
    """
    ex: dict[str, Any] = {}
    try:
        ex = __import__("json").loads(str(trade.get("extra_json") or "{}"))
    except Exception:
        ex = {}
    yb = ex.get("entry_yes_bid_dollars") or ex.get("yes_bid_dollars")
    ya = ex.get("entry_yes_ask_dollars") or ex.get("yes_ask_dollars")
    m: dict[str, Any] = {
        "yes_bid_dollars": yb,
        "yes_ask_dollars": ya,
    }
    if m["yes_bid_dollars"] is None and m["yes_ask_dollars"] is None and math.isfinite(prob):
        p = max(0.01, min(0.99, float(prob)))
        m["yes_bid_dollars"] = max(0.0, p - 0.015)
        m["yes_ask_dollars"] = min(1.0, p + 0.015)
    return m
