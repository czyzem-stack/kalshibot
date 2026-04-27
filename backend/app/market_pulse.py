from __future__ import annotations

import math
from typing import Any

from .branch_config import _lab_key_for_branch, live_paper_trading_enabled, pulse_effective_config
from .engine import (
    asset_cfg_enabled,
    build_effective_rules,
    dev_sim_yes_bypass_threshold,
    has_yes_book_for_rules,
    consecutive_stake_cents,
    dollars_to_float,
    effective_no_ask,
    enrich_markets_with_orderbooks,
    exclude_subtitle_parts_from_cfg,
    implied_yes_probability,
    minutes_left,
    pick_trade_rule,
    rule_trade_side,
    spent_in_window,
    utc_now,
    window_id_for,
)
from .kalshi_client import KalshiClient
from .persistence import Store


def market_passes_subtitle_excludes(market: dict[str, Any], parts: list[str]) -> bool:
    if not parts:
        return True
    blob = str(market.get("yes_sub_title") or market.get("subtitle") or market.get("title") or "").lower()
    return not any(p in blob for p in parts)


def _bias_from_prob(prob: float) -> str:
    if prob >= 0.58:
        return "YES side high (bullish)"
    if prob <= 0.42:
        return "YES side low (bearish)"
    return "Mid range"


async def fetch_market_pulse(
    store: Store,
    *,
    branch: str,
    include_unpriced: bool,
    client: KalshiClient | None = None,
) -> dict[str, Any]:
    full = await store.load_config()
    eff = pulse_effective_config(full, branch)
    rules = build_effective_rules(eff)
    exclude_parts = exclude_subtitle_parts_from_cfg(eff)
    if include_unpriced:
        exclude_parts = []
    dev_yes_floor = dev_sim_yes_bypass_threshold(eff)
    subtitle_filter = (eff.get("only_yes_subtitle_contains") or "").lower().strip()
    window_minutes = int(eff.get("window_minutes") or 15)
    now = utc_now()
    wid = window_id_for(now, window_minutes)

    lk = _lab_key_for_branch(branch)
    if lk is not None:
        trade_mode = "simulate"
        lab_blk = full.get(lk) if isinstance(full.get(lk), dict) else {}
        paper_cents = int(lab_blk.get("paper_balance_cents") or full.get("paper_balance_cents") or 500_000)
    else:
        trade_mode = "simulate" if live_paper_trading_enabled(full) else "live"
        paper_cents = int(full.get("paper_balance_cents") or 500_000)

    spent = await spent_in_window(store, wid, trade_mode, window_minutes, branch)
    fraction = float(eff.get("balance_fraction_per_window") or 0.03)
    available_cents = max(0, paper_cents - spent)
    next_stake = consecutive_stake_cents(paper_cents, spent, fraction)
    stake_first = consecutive_stake_cents(paper_cents, 0, fraction)
    min_c = int(eff.get("min_contracts") or 1)

    if client is not None:
        cli = client
    else:
        from . import state

        cli = state.require_kalshi()
    rows: list[dict[str, Any]] = []

    assets = eff.get("assets") or {}
    for asset_id, acfg in assets.items():
        if not asset_cfg_enabled(acfg):
            continue
        series = str(acfg.get("series_ticker") or "").strip()
        if not series:
            continue
        label = str(acfg.get("label") or asset_id)
        try:
            data = await cli.get_open_markets_cached(series, limit=80)
        except Exception as e:
            rows.append(
                {
                    "asset_id": str(asset_id),
                    "asset_label": label,
                    "series_ticker": series,
                    "error": str(e),
                }
            )
            continue

        markets_list = list(data.get("markets") or [])
        await enrich_markets_with_orderbooks(cli, markets_list, now, max_fetches=20)

        for m in markets_list:
            if not isinstance(m, dict):
                continue
            ticker = str(m.get("ticker") or "")
            if not ticker:
                continue
            mstatus = str(m.get("status") or "").lower()
            if mstatus and mstatus not in ("active", "open"):
                continue
            yes_sub = str(m.get("yes_sub_title") or m.get("subtitle") or "").lower()
            if subtitle_filter and subtitle_filter not in yes_sub:
                continue
            if any(p and p in yes_sub for p in exclude_parts):
                continue

            close_time = str(m.get("close_time") or "")
            mins = minutes_left(close_time, now)
            if mins is None or mins <= 0:
                continue

            yb = dollars_to_float(m.get("yes_bid_dollars"))
            ya = dollars_to_float(m.get("yes_ask_dollars"))
            prob = implied_yes_probability(yb, ya)
            na = effective_no_ask(m, yb, ya)
            has_yes_rules = has_yes_book_for_rules(yb, ya, prob)
            has_no_book = na is not None and 0 < na < 1
            last_px = m.get("last_price_dollars")
            last_px_s = str(last_px) if last_px not in (None, "") else "—"

            if prob is None or (not has_yes_rules and not has_no_book):
                rows.append(
                    {
                        "asset_id": str(asset_id),
                        "asset_label": label,
                        "ticker": ticker,
                        "yes_title": str(m.get("yes_sub_title") or m.get("subtitle") or "")[:72],
                        "close_time": close_time or None,
                        "last_price_dollars": last_px_s,
                        "yes_mid": None,
                        "yes_prob_pct": None,
                        "bias": "—",
                        "mins_left": round(mins, 1) if mins is not None else None,
                        "rules_hit": [],
                        "instant_trade": "no",
                        "instant_reason": "no_orderbook",
                    }
                )
                continue

            picked = pick_trade_rule(
                prob,
                mins,
                rules,
                has_yes_rules=has_yes_rules,
                has_no_book=has_no_book,
                cfg=eff,
            )
            matched: list[str] = [str(picked.get("name") or "rule")] if picked else []
            if (
                not matched
                and dev_yes_floor is not None
                and trade_mode == "simulate"
                and has_yes_rules
                and prob is not None
                and prob >= dev_yes_floor
            ):
                matched.append(f"DEV ≥{dev_yes_floor * 100:.0f}% implied YES (sim only)")

            if picked is not None:
                if rule_trade_side(picked) == "no" and has_no_book and na is not None:
                    per_c = int(math.ceil(na * 100.0))
                elif has_yes_rules and ya is not None:
                    per_c = int(math.ceil(ya * 100.0))
                else:
                    per_c = int(math.ceil(na * 100.0)) if na is not None else 0
            elif has_yes_rules and ya is not None:
                per_c = int(math.ceil(ya * 100.0))
            else:
                per_c = int(math.ceil(na * 100.0)) if na is not None else 0
            fresh_contracts = int(math.floor(stake_first / per_c)) if per_c > 0 else 0
            window_contracts = int(math.floor(next_stake / per_c)) if per_c > 0 else 0

            instant_trade = "no"
            instant_reason = "no_rule_match"
            if matched:
                if fresh_contracts >= min_c:
                    instant_reason = "theoretical_ok_fresh_budget"
                    if window_contracts >= min_c:
                        instant_trade = "yes"
                    else:
                        instant_trade = "maybe"
                        instant_reason = "rule_ok_but_stake_too_small"
                else:
                    instant_reason = "rule_ok_but_size_lt_min"

            rows.append(
                {
                    "asset_id": str(asset_id),
                    "asset_label": label,
                    "ticker": ticker,
                    "yes_title": str(m.get("yes_sub_title") or m.get("subtitle") or "")[:72],
                    "close_time": close_time or None,
                    "last_price_dollars": last_px_s,
                    "yes_mid": round((yb + ya) / 2.0, 4) if yb is not None and ya is not None else round(float(ya), 4),
                    "yes_prob_pct": int(round(prob * 100.0)),
                    "bias": _bias_from_prob(prob),
                    "mins_left": round(mins, 1),
                    "rules_hit": matched,
                    "instant_trade": instant_trade,
                    "instant_reason": instant_reason,
                    "theory_contracts_fresh": fresh_contracts,
                    "theory_contracts_window": window_contracts,
                }
            )

    rows.sort(key=lambda r: (r.get("asset_id") or "", r.get("mins_left") is None, r.get("mins_left") or 999))

    return {
        "branch": branch,
        "updated_at": now.isoformat(),
        "window_minutes": window_minutes,
        "window_id": wid,
        "paper_bankroll_cents": paper_cents,
        "balance_fraction_per_window": fraction,
        "trade_mode": trade_mode,
        "available_cents": available_cents,
        "next_stake_cap_cents": next_stake,
        "window_budget_cents": next_stake,
        "spent_this_window_cents": spent,
        "remaining_budget_cents": available_cents,
        "rows": rows,
    }
