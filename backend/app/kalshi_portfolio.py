from __future__ import annotations

import asyncio
from typing import Any

from .kalshi_client import KalshiClient


async def fetch_portfolio_snapshot(client: KalshiClient) -> dict[str, Any]:
    """
    Authenticated read: balance, positions, resting orders.
    Used by /api/dashboard and /api/account.
    """
    balance: dict[str, Any] | None = None
    positions: list[Any] = []
    orders: list[Any] = []
    errors: list[str] = []

    # Run three independent private reads in parallel; behavior/output shape remains identical.
    bal_r, pos_r, ord_r = await asyncio.gather(
        client.get_private("/portfolio/balance"),
        client.get_private("/portfolio/positions", {"limit": "200"}),
        client.get_private("/portfolio/orders", {"status": "resting", "limit": "200"}),
        return_exceptions=True,
    )

    if isinstance(bal_r, Exception):
        errors.append(f"balance: {bal_r}")
    elif isinstance(bal_r, dict):
        balance = bal_r

    if isinstance(pos_r, Exception):
        errors.append(f"positions: {pos_r}")
    else:
        pos = pos_r
        if isinstance(pos, dict):
            raw = pos.get("market_positions") or pos.get("positions")
            if isinstance(raw, list):
                positions = list(raw)
            # Event-level aggregates (some exposure only appears here; series prefix still matches e.g. KXDOGE15M-…)
            evs = pos.get("event_positions")
            if isinstance(evs, list):
                for ep in evs:
                    if not isinstance(ep, dict):
                        continue
                    et = ep.get("event_ticker")
                    if not et:
                        continue
                    positions.append(
                        {
                            "ticker": str(et),
                            "position_fp": ep.get("total_cost_shares_fp"),
                            "market_exposure_dollars": ep.get("event_exposure_dollars"),
                            "_kalshi_event_position": True,
                        }
                    )
        elif isinstance(pos, list):
            positions = pos

    if isinstance(ord_r, Exception):
        errors.append(f"orders: {ord_r}")
    else:
        ord_data = ord_r
        if isinstance(ord_data, dict):
            raw_o = ord_data.get("orders")
            if isinstance(raw_o, list):
                orders = raw_o
        elif isinstance(ord_data, list):
            orders = ord_data

    return {
        "balance": balance,
        "positions": positions,
        "orders": orders,
        "position_count": len(positions),
        "resting_order_count": len(orders),
        "error": "; ".join(errors) if errors else None,
    }
