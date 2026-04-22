from __future__ import annotations

import asyncio
import datetime as dt
import json
import math
import re
import uuid
from dataclasses import dataclass
from typing import Any

from dateutil import parser as dateparser

from .branch_config import (
    BRANCH_LAB_A,
    BRANCH_LAB_B,
    BRANCH_LIVE,
    BRANCH_SIM_LAB,
    effective_paper_fee_bps,
    effective_swing_exit_implied_drop_pct,
    kalshi_fee_multiplier_from_cfg,
    merge_branch_config,
    paper_fee_bps_from_cfg,
    paper_fee_model_from_cfg,
    resolve_kalshi_fee_multiplier,
    resolve_paper_fee_model,
)
from .kalshi_fees import kalshi_buy_debit_cents, kalshi_sell_credit_cents, kalshi_settlement_credit_cents
from .kalshi_client import KalshiClient
from .optimizer import maybe_auto_optimize
from .persistence import Store, _data_log


def utc_now() -> dt.datetime:
    return dt.datetime.now(tz=dt.timezone.utc)


def _trade_row_matches_branch(row_branch: Any, target_branch: str) -> bool:
    """True if a SQLite trade/signal row belongs to the engine's logical branch (lab_a includes legacy sim_lab)."""
    b = str(row_branch or "live").strip().lower()
    t = str(target_branch or "live").strip().lower()
    if t in (BRANCH_LAB_A, BRANCH_SIM_LAB, "lab_a"):
        return b in ("lab_a", "sim_lab")
    return b == t


def iso(dtobj: dt.datetime) -> str:
    return dtobj.astimezone(dt.timezone.utc).isoformat()


def window_id_for(now: dt.datetime, window_minutes: int) -> str:
    epoch = int(now.timestamp())
    step = max(1, int(window_minutes)) * 60
    return str(epoch // step)


def dollars_to_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(str(v))
    except Exception:
        return None


def implied_yes_probability(yes_bid: float | None, yes_ask: float | None) -> float | None:
    if yes_bid is not None and yes_ask is not None:
        return max(0.0, min(1.0, (yes_bid + yes_ask) / 2.0))
    if yes_ask is not None:
        return max(0.0, min(1.0, yes_ask))
    if yes_bid is not None:
        return max(0.0, min(1.0, yes_bid))
    return None


def minutes_left(close_time_iso: str, now: dt.datetime) -> float | None:
    try:
        close = dateparser.isoparse(close_time_iso)
        if close.tzinfo is None:
            close = close.replace(tzinfo=dt.timezone.utc)
        return (close - now).total_seconds() / 60.0
    except Exception:
        return None


def has_tradable_yes_ask(ya: float | None) -> bool:
    """YES limit buy at the ask is viable (Kalshi binary: ask must be strictly below $1)."""
    return ya is not None and 0 < ya < 1


def has_yes_book_for_rules(yb: float | None, ya: float | None, prob: float | None) -> bool:
    """
    Enough YES bid/ask to evaluate YES-side rules and implied mid.
    Listings often show yes_ask_dollars == 1.0 at the ceiling; implied mid from bid+ask is still meaningful.
    """
    if prob is None or yb is None or ya is None:
        return False
    try:
        fb, fa = float(yb), float(ya)
    except (TypeError, ValueError):
        return False
    if not (0 < fb < 1) or not (0 < fa <= 1.0):
        return False
    return fb <= fa + 1e-9


def market_list_row_has_good_book(m: dict[str, Any]) -> bool:
    yb = dollars_to_float(m.get("yes_bid_dollars"))
    ya = dollars_to_float(m.get("yes_ask_dollars"))
    prob = implied_yes_probability(yb, ya)
    return has_yes_book_for_rules(yb, ya, prob) and has_tradable_yes_ask(ya)


def orderbook_json_to_yes_bid_ask(data: Any) -> tuple[float | None, float | None]:
    """Best YES bid / implied YES ask from Kalshi orderbook_fp (bids only; ask = 1 − best NO bid)."""
    if not isinstance(data, dict):
        return None, None
    ob = data.get("orderbook_fp")
    if not isinstance(ob, dict):
        return None, None
    yes = ob.get("yes_dollars") or []
    no = ob.get("no_dollars") or []
    yb: float | None = None
    ya: float | None = None
    if isinstance(yes, list) and yes:
        last = yes[-1]
        if isinstance(last, (list, tuple)) and len(last) >= 1:
            yb = dollars_to_float(last[0])
    if isinstance(no, list) and no:
        lastn = no[-1]
        if isinstance(lastn, (list, tuple)) and len(lastn) >= 1:
            nb = dollars_to_float(lastn[0])
            if nb is not None:
                ya = 1.0 - nb
    return yb, ya


async def enrich_markets_with_orderbooks(
    client: KalshiClient,
    markets: list[Any],
    now: dt.datetime,
    *,
    max_fetches: int = 12,
) -> int:
    """
    PATCH /markets list rows: when yes_bid/yes_ask are missing or not a tradable spread, try GET orderbook.
    Demo alt series often stay empty; production sometimes benefits when list fields lag.
    """
    scored: list[tuple[float, dict[str, Any]]] = []
    for m in markets:
        if not isinstance(m, dict):
            continue
        if market_list_row_has_good_book(m):
            continue
        ticker = str(m.get("ticker") or "").strip()
        if not ticker:
            continue
        close_time = str(m.get("close_time") or "")
        mins = minutes_left(close_time, now)
        if mins is None or mins <= 0:
            continue
        scored.append((mins, m))
    # Prefer orderbook fetches on contracts with more time left (demo list rows near expiry are often empty/TBD).
    scored.sort(key=lambda x: x[0], reverse=True)
    targets: list[tuple[str, dict[str, Any]]] = []
    seen: set[str] = set()
    for _mins, m in scored:
        if len(targets) >= max_fetches:
            break
        t = str(m.get("ticker") or "").strip()
        if not t or t in seen:
            continue
        seen.add(t)
        targets.append((t, m))

    async def _apply(pair: tuple[str, dict[str, Any]]) -> bool:
        t, m = pair
        try:
            raw = await client.get_market_orderbook_cached(t)
        except Exception:
            return False
        ob_yb, ob_ya = orderbook_json_to_yes_bid_ask(raw)
        if ob_yb is None and ob_ya is None:
            return False
        if ob_yb is not None:
            m["yes_bid_dollars"] = str(ob_yb)
        if ob_ya is not None:
            m["yes_ask_dollars"] = str(ob_ya)
        return market_list_row_has_good_book(m)

    if not targets:
        return 0
    results = await asyncio.gather(*[_apply(p) for p in targets])
    return sum(1 for r in results if r)


def consecutive_stake_cents(balance_cents: int, spent_cents: int, fraction: float) -> int:
    """
    Per-trade stake: ceil(available_dollars * fraction) in whole dollars, capped by available cash.
    available = balance_cents - spent_cents (typically spent this budget window).
    Example: $100 @ 3% -> $3; after spending $3, $97 @ 3% -> ceil(2.91) = $3; later -> $2 bets.
    """
    available = max(0, int(balance_cents) - int(spent_cents))
    if available <= 0 or fraction <= 0:
        return 0
    avail_d = available / 100.0
    stake_dollars = max(1, int(math.ceil(avail_d * fraction - 1e-12)))
    return min(available, stake_dollars * 100)


def asset_cfg_enabled(acfg: Any) -> bool:
    """Whether an asset row should be scanned. Missing ``enabled`` defaults to True (partial asset dicts stay on)."""
    if not isinstance(acfg, dict):
        return False
    if "enabled" not in acfg:
        return True
    return bool(acfg["enabled"])


def exclude_subtitle_parts_from_cfg(cfg: dict[str, Any]) -> list[str]:
    """Comma-separated lowercase substrings; empty / missing = off. Use e.g. 'tbd' only if you want to skip those rows."""
    raw = cfg.get("exclude_yes_subtitle_contains")
    if raw is None:
        raw = ""
    else:
        raw = str(raw).lower()
    return [p.strip() for p in raw.split(",") if p.strip()]


def dev_sim_yes_bypass_threshold(cfg: dict[str, Any]) -> float | None:
    """
    Implied YES probability (0–1) at/above which the dev sim bypass can match, or None if off.
    Legacy: dev_sim_yes_implied_ge_70 True → 0.70.
    """
    raw = cfg.get("dev_sim_yes_implied_ge_pct")
    if raw is not None and raw is not False:
        try:
            t = float(raw) / 100.0
            if 0.01 <= t <= 0.99:
                return t
        except (TypeError, ValueError):
            pass
    if bool(cfg.get("dev_sim_yes_implied_ge_70")):
        return 0.70
    return None


def _dev_sim_high_yes_rule(floor: float) -> dict[str, Any]:
    return {
        "name": f"DEV ≥{floor * 100:.0f}% implied YES (sim only)",
        "min_prob": floor,
        "max_prob": 1.0,
        "min_minutes_left": 0.0,
        "max_minutes_left": 1.0e9,
    }


def build_effective_rules(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Config rules plus optional synthetic NO rule when implied YES is below a threshold (buys NO; evaluated last).
    """
    rules = [dict(r) for r in (cfg.get("rules") or []) if isinstance(r, dict)]
    raw = cfg.get("no_bet_when_yes_below_pct")
    if raw is None or raw is False:
        return rules
    try:
        pct = float(raw)
    except (TypeError, ValueError):
        return rules
    thr = pct / 100.0
    if not (0 < thr <= 0.95):
        return rules
    no_min = max(0.01, min(0.99, 1.0 - thr))
    rules.append(
        {
            "name": f"Auto NO when implied YES < {pct:g}%",
            "side": "no",
            "min_prob": round(no_min, 4),
            "max_prob": 0.999,
            "min_minutes_left": 0.0,
            "max_minutes_left": 1.0e9,
        }
    )
    return rules


def rule_trade_side(rule: dict[str, Any]) -> str:
    s = str(rule.get("side") or rule.get("bet_side") or "yes").strip().lower()
    return "no" if s == "no" else "yes"


def implied_no_probability(yes_bid: float | None, yes_ask: float | None) -> float | None:
    py = implied_yes_probability(yes_bid, yes_ask)
    if py is None:
        return None
    return max(0.0, min(1.0, 1.0 - py))


def effective_no_ask(market: dict[str, Any], yes_bid: float | None) -> float | None:
    """Best NO ask in dollars: API field, else reciprocal of YES bid (Kalshi binary symmetry)."""
    na = dollars_to_float(market.get("no_ask_dollars"))
    if na is not None and 0 < na < 1:
        return na
    if yes_bid is not None and 0 < yes_bid < 1:
        return 1.0 - yes_bid
    return None


def rule_matches(
    prob_yes: float | None, mins: float | None, rule: dict[str, Any]
) -> bool:
    """min_prob/max_prob apply to implied YES unless rule.side is \"no\" (then implied NO = 1 − YES mid)."""
    if prob_yes is None or mins is None:
        return False
    p = (1.0 - prob_yes) if rule_trade_side(rule) == "no" else prob_yes
    if p < float(rule["min_prob"]) or p > float(rule["max_prob"]):
        return False
    if mins < float(rule["min_minutes_left"]) or mins > float(rule["max_minutes_left"]):
        return False
    return True


@dataclass
class EngineState:
    last_tick_at: str | None = None
    last_error: str | None = None
    markets_scanned: int = 0
    last_tick_trace: list[str] | None = None
    # Per asset_id: headline market from last tick (for dashboard; not persisted).
    asset_snapshots: dict[str, dict[str, Any]] | None = None


class TradingEngine:
    def __init__(self, store: Store, branch: str = BRANCH_LIVE) -> None:
        self.store = store
        self.branch = branch
        self.client = KalshiClient()
        self.state = EngineState()
        self._seen_keys: set[str] = set()
        self._last_window_id: str | None = None
        self._tick_count: int = 0
        # One automatic branch wipe per error streak when lab auto-reset is enabled.
        self._paper_auto_reset_streak_handled: bool = False


def _is_lab_branch(branch: str) -> bool:
    return branch in (BRANCH_SIM_LAB, BRANCH_LAB_A, BRANCH_LAB_B)


async def tick_once(engine: TradingEngine) -> None:
    now = utc_now()
    engine.state.last_tick_at = iso(now)
    engine.state.last_error = None

    full_cfg = await engine.store.load_config()
    cfg = merge_branch_config(full_cfg, engine.branch)
    if not cfg:
        return

    window_minutes = int(cfg.get("window_minutes") or 15)
    wid = window_id_for(now, window_minutes)
    if engine._last_window_id != wid:
        engine._seen_keys.clear()
        engine._last_window_id = wid

    trade_mode = str(cfg.get("_trade_mode") or "simulate")
    branch = str(cfg.get("_branch") or "live")

    balance_cents = 0
    if _is_lab_branch(branch):
        lab_key = "lab_a" if branch in (BRANCH_SIM_LAB, BRANCH_LAB_A) else "lab_b"
        lab = full_cfg.get(lab_key) or {}
        balance_cents = int(lab.get("paper_balance_cents") or full_cfg.get("paper_balance_cents") or 500_000)
    elif trade_mode == "simulate" or bool(cfg.get("_simulate_orders")):
        # Live branch paper sim: stake against configured bankroll only (not exchange balance).
        balance_cents = int(cfg.get("paper_balance_cents") or full_cfg.get("paper_balance_cents") or 500_000)
    else:
        try:
            bal = await engine.client.get_private("/portfolio/balance")
            balance_cents = int(bal.get("balance") or 0)
        except Exception as e:
            engine.state.last_error = f"balance: {e}"
            balance_cents = 0

    assets = cfg.get("assets") or {}
    rules = build_effective_rules(cfg)
    subtitle_filter = (cfg.get("only_yes_subtitle_contains") or "").lower().strip()
    exclude_substrings = exclude_subtitle_parts_from_cfg(cfg)

    trace: list[str] = []
    trace.append(
        f"tick {iso(now)} | branch={branch} | trade_mode={trade_mode} | "
        f"balance_cents={balance_cents} | window={wid} | simulate_orders={bool(cfg.get('_simulate_orders'))}"
    )

    snapshots: dict[str, dict[str, Any]] = {}
    scanned = 0
    for asset_id, acfg in assets.items():
        aid = str(asset_id)
        if not asset_cfg_enabled(acfg):
            trace.append(f"asset {asset_id}: disabled, skip")
            snapshots[aid] = {"ok": False, "reason": "disabled", "note": "Asset toggle is off."}
            continue
        series = str(acfg.get("series_ticker") or "").strip()
        if not series:
            trace.append(f"asset {asset_id}: no series_ticker, skip")
            snapshots[aid] = {"ok": False, "reason": "no_series", "note": "Set series_ticker in config."}
            continue
        try:
            data = await engine.client.get_open_markets_cached(series, limit=100)
        except Exception as e:
            engine.state.last_error = f"markets {series}: {e}"
            trace.append(f"asset {asset_id} series={series}: FETCH ERROR {e}")
            snapshots[aid] = {"ok": False, "reason": "fetch_error", "note": str(e)[:240]}
            continue
        markets = list(data.get("markets") or [])
        scanned += len(markets)
        trace.append(f"asset {asset_id} series={series}: fetched {len(markets)} open markets")
        ob_n = await enrich_markets_with_orderbooks(engine.client, markets, now, max_fetches=20)
        if ob_n:
            trace.append(f"asset {asset_id} series={series}: orderbook backfill improved {ob_n} row(s)")
        dev_floor = dev_sim_yes_bypass_threshold(cfg)
        sim_orders = bool(cfg.get("_simulate_orders"))
        pre_snap = pick_asset_snapshot(
            markets,
            rules,
            subtitle_filter,
            exclude_substrings,
            now,
            dev_sim_yes_floor=dev_floor,
            simulate_orders=sim_orders,
        )
        await maybe_backfill_headline_orderbook(
            engine.client,
            markets,
            pre_snap,
            trace,
            asset_id=str(asset_id),
            series=series,
        )
        no_rule = 0
        for m in markets:
            kind = await handle_market(
                engine,
                cfg=cfg,
                trade_mode=trade_mode,
                branch=branch,
                window_id=wid,
                asset_id=str(asset_id),
                market=m,
                rules=rules,
                subtitle_filter=subtitle_filter,
                exclude_substrings=exclude_substrings,
                balance_cents=balance_cents,
                trace=trace,
            )
            if kind == "no_rule":
                no_rule += 1
        if no_rule:
            trace.append(f"asset {asset_id}: {no_rule} market(s) had book+time but no rule matched")
        snapshots[aid] = pick_asset_snapshot(
            markets,
            rules,
            subtitle_filter,
            exclude_substrings,
            now,
            dev_sim_yes_floor=dev_floor,
            simulate_orders=sim_orders,
        )

    engine.state.markets_scanned = scanned
    engine.state.asset_snapshots = snapshots
    engine.state.last_tick_trace = trace[-150:]

    await _maybe_auto_reset_lab_paper_on_tick_failure(engine, full_cfg)


async def _maybe_auto_reset_lab_paper_on_tick_failure(
    engine: TradingEngine, full_cfg: dict[str, Any]
) -> None:
    """
    When ``auto_reset_paper_on_tick_failure`` is on for a lab, wipe that branch's SQLite trading
    rows (once per bad streak) if the tick ended with ``last_error`` **or** derived paper equity
    (seed + settled PnL − open commit) is ≤ 0, so the next tick starts from ``paper_balance_cents``.
    """
    br_engine = engine.branch
    if not _is_lab_branch(br_engine):
        if not engine.state.last_error:
            engine._paper_auto_reset_streak_handled = False
        return

    lab_key = "lab_a" if br_engine in (BRANCH_SIM_LAB, BRANCH_LAB_A) else "lab_b"
    lab = full_cfg.get(lab_key) if isinstance(full_cfg.get(lab_key), dict) else {}
    if not bool(lab.get("auto_reset_paper_on_tick_failure")):
        if not engine.state.last_error:
            engine._paper_auto_reset_streak_handled = False
        return

    err = engine.state.last_error
    bust = False
    equity_cents: int | None = None
    if not err:
        roll = await engine.store.dashboard_branch_trade_rollups(br_engine, "simulate")
        settled_pnl = int(roll.get("total_pnl_cents") or 0)
        open_committed = int(roll.get("open_committed_cents") or 0)
        paper = int(lab.get("paper_balance_cents") or full_cfg.get("paper_balance_cents") or 500_000)
        equity_cents = paper + settled_pnl - open_committed
        bust = equity_cents <= 0

    should_wipe = (bool(err) or bust) and not engine._paper_auto_reset_streak_handled
    if should_wipe:
        rb = BRANCH_LAB_A if br_engine in (BRANCH_SIM_LAB, BRANCH_LAB_A) else BRANCH_LAB_B
        await engine.store.reset_trading_data(backup=False, branch=rb)
        await engine.store.bump_lab_paper_lifetime_basis(rb)
        engine._paper_auto_reset_streak_handled = True
        payload: dict[str, Any] = {
            "event": "auto_reset_lab_paper",
            "branch": rb,
            "at": iso(utc_now()),
        }
        if err:
            payload["reason"] = "tick_error"
            payload["after_tick_error"] = str(err)[:500]
        else:
            payload["reason"] = "non_positive_equity"
            payload["equity_cents"] = equity_cents
        _data_log("system", payload)
        engine.state.last_error = None
        engine._seen_keys.clear()
    elif not err and not bust:
        engine._paper_auto_reset_streak_handled = False


async def spent_in_window(
    store: Store,
    window_id: str,
    trade_mode: str,
    window_minutes: int,
    branch: str,
) -> int:
    trades = await store.recent_trades(limit=3000)
    total = 0
    for t in trades:
        if not _trade_row_matches_branch(t.get("branch"), branch):
            continue
        tm = str(t.get("mode") or "")
        if tm != trade_mode:
            if not (trade_mode == "simulate" and tm == "" and int(t.get("simulated") or 0) == 1):
                continue
        created = str(t.get("created_at") or "")
        if not created:
            continue
        try:
            tt = dateparser.isoparse(created)
            if tt.tzinfo is None:
                tt = tt.replace(tzinfo=dt.timezone.utc)
        except Exception:
            continue
        if window_id_for(tt, window_minutes) != window_id:
            continue
        if str(t.get("status") or "") in ("canceled",):
            continue
        total += int(t.get("amount_cents") or 0)
    return total


def _trace_append(trace: list[str], msg: str, cap: int = 140) -> None:
    if len(trace) >= cap:
        return
    trace.append(msg)


def target_hint_from_title(title: str) -> str | None:
    if not title:
        return None
    m = re.search(r"target\s*price\s*[:\s]*\$?\s*([\d,]+(?:\.\d+)?)", title, re.I)
    if m:
        return f"Target ~${m.group(1)}"
    m2 = re.search(r"\$[\d,]+(?:\.\d+)?\b", title)
    if m2:
        return m2.group(0).strip()
    return None


def market_display_fields(m: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    lp = m.get("last_price_dollars")
    if lp is not None and str(lp).strip() != "":
        out["last_price_dollars"] = str(lp).strip()
    for k in (
        "floor_strike_dollars",
        "cap_strike_dollars",
        "previous_yes_bid_dollars",
        "previous_yes_ask_dollars",
    ):
        v = m.get(k)
        if v is not None and str(v).strip() != "":
            out[k] = str(v).strip()
    title = str(m.get("yes_sub_title") or m.get("subtitle") or "")
    th = target_hint_from_title(title)
    if th:
        out["target_hint"] = th
    if title:
        out["yes_title_full"] = title[:200]
    return out


def pick_asset_snapshot(
    markets: list[Any],
    rules: list[dict[str, Any]],
    subtitle_filter: str,
    exclude_substrings: list[str],
    now: dt.datetime,
    *,
    dev_sim_yes_floor: float | None = None,
    simulate_orders: bool = False,
) -> dict[str, Any]:
    """
    Pick one market to show odds. Same filters as trading first; if nothing survives (common when every row is
    “TBD” and exclude_yes_subtitle_contains skips tbd), fall back to ignoring exclude list for display only.
    """

    def collect(*, apply_exclude: bool, require_orderbook: bool) -> list[tuple[tuple[int, float, int], dict[str, Any]]]:
        out: list[tuple[tuple[int, float, int], dict[str, Any]]] = []
        for m in markets:
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
            if apply_exclude and any(ex and ex in yes_sub for ex in exclude_substrings):
                continue
            close_time = str(m.get("close_time") or "")
            mins = minutes_left(close_time, now)
            if mins is None or mins <= 0:
                continue
            yb = dollars_to_float(m.get("yes_bid_dollars"))
            ya = dollars_to_float(m.get("yes_ask_dollars"))
            prob = implied_yes_probability(yb, ya)
            na = effective_no_ask(m, yb)
            has_yes_rules = has_yes_book_for_rules(yb, ya, prob)
            has_no_book = na is not None and 0 < na < 1
            has_priced_book = has_yes_rules or has_no_book
            if require_orderbook and not has_priced_book:
                continue
            matched_names: list[str] = []
            if prob is not None:
                for r in rules:
                    if not isinstance(r, dict) or not rule_matches(prob, mins, r):
                        continue
                    if rule_trade_side(r) == "no" and not has_no_book:
                        continue
                    if rule_trade_side(r) != "no" and not has_yes_rules:
                        continue
                    matched_names.append(str(r.get("name") or "rule"))
                if (
                    not matched_names
                    and dev_sim_yes_floor is not None
                    and simulate_orders
                    and prob is not None
                    and prob >= dev_sim_yes_floor
                    and has_yes_rules
                ):
                    matched_names.append(str(_dev_sim_high_yes_rule(dev_sim_yes_floor)["name"]))
            # Prefer headline rows with a book, then more rule matches, then more time left (near-expiry rows
            # usually fall outside minute windows and show "Rules matched: NONE" misleadingly).
            sort_key = (
                0 if has_priced_book else 1,
                -len(matched_names),
                -float(mins),
            )
            title = str(m.get("yes_sub_title") or m.get("subtitle") or "")[:80]
            snap = {
                "ticker": ticker,
                "yes_title": title,
                "minutes_left": round(mins, 2),
                "close_time": close_time or None,
                "yes_bid": yb,
                "yes_ask": ya,
                "no_ask": na,
                "implied_prob": prob,
                "implied_no_prob": implied_no_probability(yb, ya) if has_yes_rules or has_no_book else None,
                "has_orderbook": has_priced_book,
                "rules_matched": matched_names,
                "ok": True,
                **market_display_fields(m),
            }
            out.append((sort_key, snap))
        return out

    # Prefer real bid/ask when possible so we do not surface 0/0 placeholder rows ahead of priced lines.
    candidates: list[tuple[tuple[int, float, int], dict[str, Any]]] = []
    relaxed_excludes = False

    def take(*, apply_exclude: bool, require_orderbook: bool) -> bool:
        nonlocal candidates, relaxed_excludes
        c = collect(apply_exclude=apply_exclude, require_orderbook=require_orderbook)
        if not c:
            return False
        candidates = c
        relaxed_excludes = not apply_exclude
        return True

    if not take(apply_exclude=True, require_orderbook=True):
        if not take(apply_exclude=True, require_orderbook=False):
            if not take(apply_exclude=False, require_orderbook=True):
                take(apply_exclude=False, require_orderbook=False)
    if not candidates:
        n = len([x for x in markets if isinstance(x, dict)])
        return {
            "ok": False,
            "reason": "no_contracts",
            "note": (
                "No open rows with time left after filters (or Kalshi returned no markets). "
                f"Raw open rows in response: {n}."
            ),
        }
    candidates.sort(key=lambda x: x[0])
    best = dict(candidates[0][1])
    if relaxed_excludes:
        best["snapshot_relaxed_excludes"] = True
    return best


async def maybe_backfill_headline_orderbook(
    client: KalshiClient,
    markets: list[Any],
    pre_snap: dict[str, Any],
    trace: list[str],
    *,
    asset_id: str,
    series: str,
) -> bool:
    """
    Bulk ``enrich_markets_with_orderbooks`` is capped; the UI headline row can still be a contract that never
    received a fetch (e.g. many open rows in one series). One extra orderbook GET for the picked ticker aligns
    Live/Sim dashboards with the contract users focus on.
    """
    if not pre_snap.get("ok") or pre_snap.get("has_orderbook"):
        return False
    ticker = str(pre_snap.get("ticker") or "").strip()
    if not ticker:
        return False
    m0: dict[str, Any] | None = None
    for m in markets:
        if isinstance(m, dict) and str(m.get("ticker") or "").strip() == ticker:
            m0 = m
            break
    if m0 is None:
        return False
    yb = dollars_to_float(m0.get("yes_bid_dollars"))
    ya = dollars_to_float(m0.get("yes_ask_dollars"))
    prob = implied_yes_probability(yb, ya)
    if has_yes_book_for_rules(yb, ya, prob):
        return False
    try:
        raw = await client.get_market_orderbook_cached(ticker)
    except Exception as e:
        trace.append(
            f"asset {asset_id} series={series}: headline orderbook fetch {ticker[:40]}… err {str(e)[:120]}"
        )
        return False
    ob_yb, ob_ya = orderbook_json_to_yes_bid_ask(raw)
    if ob_yb is None and ob_ya is None:
        return False
    if ob_yb is not None:
        m0["yes_bid_dollars"] = str(ob_yb)
    if ob_ya is not None:
        m0["yes_ask_dollars"] = str(ob_ya)
    trace.append(f"asset {asset_id} series={series}: headline orderbook backfill for {ticker}")
    return True


async def handle_market(
    engine: TradingEngine,
    *,
    cfg: dict[str, Any],
    trade_mode: str,
    branch: str,
    window_id: str,
    asset_id: str,
    market: dict[str, Any],
    rules: list[dict[str, Any]],
    subtitle_filter: str,
    exclude_substrings: list[str],
    balance_cents: int,
    trace: list[str],
) -> str | None:
    now = utc_now()
    ticker = str(market.get("ticker") or "")
    if not ticker:
        return None

    mstatus = str(market.get("status") or "").lower()
    if mstatus and mstatus not in ("active", "open"):
        return None

    yes_sub = str(market.get("yes_sub_title") or market.get("subtitle") or "").lower()
    if subtitle_filter and subtitle_filter not in yes_sub:
        return None
    for ex in exclude_substrings:
        if ex and ex in yes_sub:
            return None

    close_time = str(market.get("close_time") or "")
    mins = minutes_left(close_time, now)
    if mins is None or mins <= 0:
        return None

    yb = dollars_to_float(market.get("yes_bid_dollars"))
    ya = dollars_to_float(market.get("yes_ask_dollars"))
    prob = implied_yes_probability(yb, ya)
    na = effective_no_ask(market, yb)
    has_yes_rules = has_yes_book_for_rules(yb, ya, prob)
    has_no_book = na is not None and 0 < na < 1
    if prob is None or (not has_yes_rules and not has_no_book):
        return None

    matched_rule = None
    for r in rules:
        if not isinstance(r, dict) or not rule_matches(prob, mins, r):
            continue
        if rule_trade_side(r) == "no" and not has_no_book:
            continue
        if rule_trade_side(r) != "no" and not has_yes_rules:
            continue
        matched_rule = r
        break
    if not matched_rule:
        dev_floor = dev_sim_yes_bypass_threshold(cfg)
        if dev_floor is not None and bool(cfg.get("_simulate_orders")):
            dev_rule = _dev_sim_high_yes_rule(dev_floor)
            if has_yes_rules and rule_matches(prob, mins, dev_rule):
                matched_rule = dict(dev_rule)
                _trace_append(
                    trace,
                    f"  {asset_id} {ticker[:40]}… DEV bypass: implied YES {prob:.2f} ≥ {dev_floor:.2f} (simulated orders only)",
                )
        if not matched_rule:
            return "no_rule"

    trade_side = rule_trade_side(matched_rule)
    # YES ask capped at $1 is common on Kalshi; paper/sim may still record a fill. Real-money: skip (no edge at ask=1).
    if trade_side == "yes" and not has_tradable_yes_ask(ya) and not bool(cfg.get("_simulate_orders")):
        await log_signal(
            engine,
            window_id=window_id,
            asset_id=asset_id,
            ticker=ticker,
            side="yes",
            implied_prob=prob,
            minutes_left=mins,
            rule_name=str(matched_rule.get("name") or ""),
            executed=False,
            skip_reason="yes_ask_at_ceiling",
            mode=trade_mode,
            branch=branch,
            extra={
                "yes_bid": yb,
                "yes_ask": ya,
                "note": "YES ask is $1 — skipped real limit post; use simulate/paper or wait for ask < $1.",
            },
        )
        return None

    limit_px = float(na) if trade_side == "no" else float(ya or 0.0)
    p_no = implied_no_probability(yb, ya)

    dedupe_key = f"{window_id}:{ticker}:{matched_rule.get('name')}:{trade_side}"
    if dedupe_key in engine._seen_keys:
        _trace_append(
            trace,
            f"  {asset_id} {ticker[:40]}… dedupe (already acted this window for “{matched_rule.get('name')}” {trade_side})",
        )
        return None

    window_minutes = int(cfg.get("window_minutes") or 15)
    spent = await spent_in_window(engine.store, window_id, trade_mode, window_minutes, branch)
    fraction = float(cfg.get("balance_fraction_per_window") or 0.03)
    stake_cents = consecutive_stake_cents(balance_cents, spent, fraction)
    open_committed_cents = await engine.store.open_committed_cents_for_branch_mode(branch, trade_mode)
    free_cash_cents = max(0, int(balance_cents) - int(open_committed_cents))
    stake_cents = min(stake_cents, free_cash_cents)

    per_contract_cents = int(math.ceil(limit_px * 100.0))
    if per_contract_cents <= 0:
        await log_signal(
            engine,
            window_id=window_id,
            asset_id=asset_id,
            ticker=ticker,
            side=trade_side,
            implied_prob=prob,
            minutes_left=mins,
            rule_name=str(matched_rule.get("name") or ""),
            executed=False,
            skip_reason="invalid_price",
            mode=trade_mode,
            branch=branch,
            extra={"yes_ask": ya, "no_ask": na, "limit_px": limit_px},
        )
        engine._seen_keys.add(dedupe_key)
        _trace_append(
            trace,
            f"  {asset_id} {ticker[:40]}… rule matched but invalid price ({trade_side} ask={limit_px})",
        )
        return None

    max_contracts = stake_cents / per_contract_cents if per_contract_cents else 0
    min_c = int(cfg.get("min_contracts") or 1)
    fee_model = paper_fee_model_from_cfg(cfg)
    fee_mult = kalshi_fee_multiplier_from_cfg(cfg)
    kalshi_maker = fee_model == "kalshi_maker"
    available_cents = free_cash_cents
    if fee_model in ("kalshi_taker", "kalshi_maker"):
        contracts = int(math.floor(max_contracts))
        while contracts >= min_c:
            debit, _kb = kalshi_buy_debit_cents(
                float(contracts), limit_px, maker=kalshi_maker, fee_multiplier=fee_mult
            )
            if debit <= stake_cents and debit <= available_cents:
                break
            contracts -= 1
    else:
        contracts = int(math.floor(max_contracts))
    if contracts < min_c:
        await log_signal(
            engine,
            window_id=window_id,
            asset_id=asset_id,
            ticker=ticker,
            side=trade_side,
            implied_prob=prob,
            minutes_left=mins,
            rule_name=str(matched_rule.get("name") or ""),
            executed=False,
            skip_reason="over_budget_or_too_small",
            mode=trade_mode,
            branch=branch,
            extra={
                "stake_cents": stake_cents,
                "available_cents": available_cents,
                "open_committed_cents": open_committed_cents,
                "per_contract_cents": per_contract_cents,
                "side": trade_side,
            },
        )
        engine._seen_keys.add(dedupe_key)
        _trace_append(
            trace,
            f"  {asset_id} {ticker[:40]}… rule “{matched_rule.get('name')}” {trade_side} "
            f"yes={prob:.2f} no={(f'{p_no:.2f}' if p_no is not None else '—')} mins={mins:.1f} "
            f"but size 0 (stake¢={stake_cents} free¢={available_cents} open¢={open_committed_cents} need≥{min_c} @ {per_contract_cents}¢)",
        )
        return None

    amount_cents = contracts * per_contract_cents
    contracts_fp = f"{contracts:.2f}"

    simulate = bool(cfg.get("_simulate_orders"))
    if simulate:
        if fee_model in ("kalshi_taker", "kalshi_maker"):
            gross_amount_cents, _kb = kalshi_buy_debit_cents(
                float(contracts), limit_px, maker=kalshi_maker, fee_multiplier=fee_mult
            )
            entry_fee_cents = max(0, int(gross_amount_cents - int(amount_cents)))
            fee_bps = 0.0
        elif fee_model == "none":
            gross_amount_cents = int(amount_cents)
            entry_fee_cents = 0
            fee_bps = 0.0
        else:
            fee_bps = paper_fee_bps_from_cfg(cfg)
            entry_fee_cents = fee_cents_for_notional(amount_cents, fee_bps)
            gross_amount_cents = int(amount_cents + entry_fee_cents)
        await log_signal(
            engine,
            window_id=window_id,
            asset_id=asset_id,
            ticker=ticker,
            side=trade_side,
            implied_prob=prob,
            minutes_left=mins,
            rule_name=str(matched_rule.get("name") or ""),
            executed=True,
            skip_reason=None,
            mode=trade_mode,
            branch=branch,
            extra={
                "contracts": contracts_fp,
                "amount_cents": gross_amount_cents,
                "entry_premium_cents": amount_cents,
                "entry_fee_cents": entry_fee_cents,
                "paper_fee_bps": fee_bps,
                "paper_fee_model": fee_model,
                "kalshi_fee_multiplier": fee_mult,
                "implied_no": p_no,
                "yes_ask": ya,
                "no_ask": na,
            },
        )
        await engine.store.insert_trade(
            {
                "created_at": iso(now),
                "mode": trade_mode,
                "ticker": ticker,
                "side": trade_side,
                "contracts_fp": contracts_fp,
                "limit_yes_dollars": f"{limit_px:.4f}",
                "amount_cents": gross_amount_cents,
                "simulated": True,
                "order_id": None,
                "client_order_id": str(uuid.uuid4()),
                "status": "open",
                "result": None,
                "pnl_cents": None,
                "settled_at": None,
                "extra_json": json.dumps(
                    {
                        "yes_ask": ya,
                        "no_ask": na,
                        "rule": matched_rule.get("name"),
                        "limit_side": trade_side,
                        "entry_implied_yes": prob,
                        "entry_premium_cents": amount_cents,
                        "entry_fee_cents": entry_fee_cents,
                        "paper_fee_bps": fee_bps,
                        "paper_fee_model": fee_model,
                        "kalshi_fee_multiplier": fee_mult,
                    }
                ),
                "branch": branch,
            }
        )
        engine._seen_keys.add(dedupe_key)
        _trace_append(
            trace,
            f"  SIM {branch} {asset_id} {ticker[:36]}… BUY {contracts_fp} {trade_side.upper()} @≈{limit_px:.3f} "
            f"rule=“{matched_rule.get('name')}” yes={prob:.2f} mins={mins:.1f} "
            f"cost¢={gross_amount_cents} (prem¢={amount_cents} fee¢={entry_fee_cents}, stake_cap¢={stake_cents} avail¢={available_cents})",
        )
        return None

    cid = str(uuid.uuid4())
    body: dict[str, Any] = {
        "ticker": ticker,
        "action": "buy",
        "side": trade_side,
        "type": "limit",
        "count_fp": contracts_fp,
        "time_in_force": "immediate_or_cancel",
        "client_order_id": cid,
    }
    if trade_side == "no":
        body["no_price_dollars"] = f"{limit_px:.4f}"
    else:
        body["yes_price_dollars"] = f"{limit_px:.4f}"
    status, payload = await engine.client.post_private("/portfolio/orders", body)
    ok = status == 201
    order = payload.get("order") if isinstance(payload, dict) else None
    await log_signal(
        engine,
        window_id=window_id,
        asset_id=asset_id,
        ticker=ticker,
        side=trade_side,
        implied_prob=prob,
        minutes_left=mins,
        rule_name=str(matched_rule.get("name") or ""),
        executed=ok,
        skip_reason=None if ok else f"order_http_{status}",
        mode=trade_mode,
        branch=branch,
        extra={"payload": payload, "implied_no": p_no},
    )
    if ok and isinstance(order, dict):
        filled = float(str(order.get("fill_count_fp") or "0"))
        if filled <= 0:
            filled = float(contracts_fp)
        fill_cents = int(math.ceil(filled * per_contract_cents))
        await engine.store.insert_trade(
            {
                "created_at": iso(now),
                "mode": trade_mode,
                "ticker": ticker,
                "side": trade_side,
                "contracts_fp": f"{filled:.2f}",
                "limit_yes_dollars": f"{limit_px:.4f}",
                "amount_cents": fill_cents,
                "simulated": False,
                "order_id": str(order.get("order_id") or ""),
                "client_order_id": cid,
                "status": str(order.get("status") or "open"),
                "result": None,
                "pnl_cents": None,
                "settled_at": None,
                "extra_json": json.dumps(
                    {"raw_status": status, "limit_side": trade_side, "entry_implied_yes": prob}
                ),
                "branch": branch,
            }
        )
        engine._seen_keys.add(dedupe_key)
        _trace_append(
            trace,
            f"  LIVE ORDER OK {asset_id} {ticker[:36]}… {contracts_fp} {trade_side.upper()} @ {limit_px:.3f} http={status}",
        )
    else:
        engine._seen_keys.add(dedupe_key)
        _trace_append(
            trace,
            f"  LIVE ORDER FAIL {asset_id} {ticker[:36]}… http={status} ok={ok}",
        )
    return None


async def log_signal(
    engine: TradingEngine,
    *,
    window_id: str,
    asset_id: str,
    ticker: str,
    side: str,
    implied_prob: float | None,
    minutes_left: float | None,
    rule_name: str,
    executed: bool,
    skip_reason: str | None,
    mode: str,
    branch: str,
    extra: dict[str, Any] | None,
) -> None:
    await engine.store.insert_signal(
        {
            "created_at": iso(utc_now()),
            "window_id": window_id,
            "asset_id": asset_id,
            "ticker": ticker,
            "side": side,
            "implied_prob": implied_prob,
            "minutes_left": minutes_left,
            "rule_name": rule_name,
            "executed": executed,
            "skip_reason": skip_reason,
            "mode": mode,
            "extra_json": json.dumps(extra or {}),
            "branch": branch,
        }
    )


def market_dict_from_public_response(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    m = data.get("market")
    if isinstance(m, dict):
        return m
    if "ticker" in data or "yes_bid_dollars" in data:
        return data
    return {}


def exit_bid_for_side_close(
    m: dict[str, Any],
    side: str,
    yb: float | None,
    ya: float | None,
) -> float | None:
    """Synthetic exit: sell YES at YES bid; sell NO at NO bid or 1 − YES ask."""
    if side == "yes":
        return dollars_to_float(m.get("yes_bid_dollars")) or yb
    nb = dollars_to_float(m.get("no_bid_dollars"))
    if nb is not None and nb > 0:
        return nb
    if ya is not None and 0 < ya <= 1:
        return 1.0 - ya
    return None


def _engine_trace_note(engine: TradingEngine, msg: str) -> None:
    prev = list(engine.state.last_tick_trace or [])
    prev.append(msg)
    engine.state.last_tick_trace = prev[-150:]


def fee_cents_for_notional(notional_cents: int, fee_bps: float) -> int:
    if notional_cents <= 0 or fee_bps <= 0:
        return 0
    return int(math.ceil((float(notional_cents) * float(fee_bps)) / 10000.0 - 1e-12))


async def maybe_swing_exit_open_sim_trades(engine: TradingEngine, full_cfg: dict[str, Any]) -> int:
    """
    Paper sim only: close open rows when implied YES has moved against the entry by at least
    ``swing_exit_implied_drop_pct`` percentage points (e.g. 50 ⇒ 0.50 drop for a YES long).
    Exit notional at bid; PnL = proceeds − premium paid.
    """
    branch = engine.branch
    thr = effective_swing_exit_implied_drop_pct(full_cfg, branch)
    fee_bps_now = effective_paper_fee_bps(full_cfg, branch)
    if thr <= 0:
        return 0
    if branch == BRANCH_LIVE and not bool(full_cfg.get("simulate")):
        return 0

    open_rows = await engine.store.open_sim_trades_for_branch(branch)
    if not open_rows:
        return 0
    closed_n = 0
    now = utc_now()

    for t in open_rows:
        if int(t.get("simulated") or 0) != 1:
            continue
        tid = int(t["id"])
        ticker = str(t.get("ticker") or "").strip()
        if not ticker:
            continue
        side = str(t.get("side") or "yes").strip().lower()
        if side not in ("yes", "no"):
            continue
        try:
            raw_ex = json.loads(str(t.get("extra_json") or "{}"))
            extra = dict(raw_ex) if isinstance(raw_ex, dict) else {}
        except json.JSONDecodeError:
            extra = {}
        entry = extra.get("entry_implied_yes")
        if entry is None:
            continue
        try:
            entry_f = float(entry)
        except (TypeError, ValueError):
            continue

        try:
            data = await engine.client.get_public(f"/markets/{ticker}")
        except Exception as e:
            _engine_trace_note(engine, f"swing {branch}: {ticker[:28]}… fetch err {str(e)[:80]}")
            continue

        m = market_dict_from_public_response(data)
        st = str(m.get("status") or "").strip().lower()
        if st in ("finalized", "closed", "determined", "settled", "settlement", "complete", "inactive"):
            continue

        yb = dollars_to_float(m.get("yes_bid_dollars"))
        ya = dollars_to_float(m.get("yes_ask_dollars"))
        prob = implied_yes_probability(yb, ya)
        if prob is None:
            continue
        if not has_yes_book_for_rules(yb, ya, prob):
            continue

        adverse = (entry_f - prob) if side == "yes" else (prob - entry_f)
        if adverse < thr / 100.0:
            continue

        exit_px = exit_bid_for_side_close(m, side, yb, ya)
        if exit_px is None or exit_px <= 0:
            _engine_trace_note(engine, f"swing {branch}: {ticker[:28]}… skip exit (no bid)")
            continue

        try:
            contracts = float(str(t.get("contracts_fp") or "0"))
        except (TypeError, ValueError):
            contracts = 0.0
        if contracts <= 0:
            continue
        cost = int(t.get("amount_cents") or 0)
        proceeds_cents = int(round(contracts * exit_px * 100.0))
        fee_model = resolve_paper_fee_model(extra, full_cfg, branch)
        fee_mult = resolve_kalshi_fee_multiplier(extra, full_cfg, branch)
        kalshi_maker = fee_model == "kalshi_maker"
        if fee_model in ("kalshi_taker", "kalshi_maker"):
            net_proceeds_cents, _kb = kalshi_sell_credit_cents(
                contracts, exit_px, maker=kalshi_maker, fee_multiplier=fee_mult
            )
            exit_fee_cents = max(0, proceeds_cents - net_proceeds_cents)
            fee_bps_used = float(extra.get("paper_fee_bps", 0.0))
        elif fee_model == "none":
            net_proceeds_cents = proceeds_cents
            exit_fee_cents = 0
            fee_bps_used = 0.0
        else:
            fee_bps_used = fee_bps_now
            try:
                fee_bps_used = float(extra.get("paper_fee_bps", fee_bps_now))
            except (TypeError, ValueError):
                fee_bps_used = fee_bps_now
            exit_fee_cents = fee_cents_for_notional(proceeds_cents, fee_bps_used)
            net_proceeds_cents = max(0, proceeds_cents - exit_fee_cents)
        pnl = net_proceeds_cents - cost

        extra.update(
            {
                "swing_exit": True,
                "swing_entry_implied_yes": entry_f,
                "swing_exit_implied_yes": prob,
                "swing_exit_bid": exit_px,
                "swing_adverse_prob": adverse,
                "paper_fee_model": fee_model,
                "paper_fee_bps": fee_bps_used,
                "swing_exit_fee_cents": exit_fee_cents,
                "swing_exit_gross_proceeds_cents": proceeds_cents,
                "swing_exit_net_proceeds_cents": net_proceeds_cents,
            }
        )
        await engine.store.update_trade_sim_early_close(
            tid,
            pnl_cents=int(pnl),
            settled_at=iso(now),
            result="swing_exit",
            extra_json=json.dumps(extra),
        )
        closed_n += 1
        _engine_trace_note(
            engine,
            f"swing {branch} {ticker[:36]}… closed {side.upper()} adverse={adverse:.2f} "
            f"entry_yes={entry_f:.2f} now={prob:.2f} exit≈{exit_px:.3f} pnl¢={pnl}",
        )

    return closed_n


async def settle_simulated_trades(engine: TradingEngine) -> int:
    """Mark simulated open rows settled when Kalshi market is finalized. Returns count updated this pass."""
    open_trades = await engine.store.open_sim_trades_for_branch(engine.branch)
    if not open_trades:
        return 0
    now = utc_now()
    settled_n = 0
    full_cfg = await engine.store.load_config()
    fee_bps_now = effective_paper_fee_bps(full_cfg, engine.branch)
    for t in open_trades:
        ticker = str(t.get("ticker") or "")
        if not ticker:
            continue
        try:
            data = await engine.client.get_public(f"/markets/{ticker}")
        except Exception:
            continue
        m = market_dict_from_public_response(data)
        status = str(m.get("status") or "").strip().lower()
        if status not in (
            "finalized",
            "closed",
            "determined",
            "settled",
            "settlement",
            "complete",
            "inactive",
        ):
            continue
        result = str(m.get("result") or "").strip().lower()
        if result not in ("yes", "no"):
            continue
        side = str(t.get("side") or "yes")
        contracts = float(str(t.get("contracts_fp") or "0"))
        amount = int(t.get("amount_cents") or 0)
        payout_per = 1.0 if (side == "yes" and result == "yes") or (side == "no" and result == "no") else 0.0
        try:
            raw_ex = json.loads(str(t.get("extra_json") or "{}"))
            ex = dict(raw_ex) if isinstance(raw_ex, dict) else {}
        except json.JSONDecodeError:
            ex = {}
        fee_model = resolve_paper_fee_model(ex, full_cfg, engine.branch)
        if fee_model in ("kalshi_taker", "kalshi_maker"):
            if payout_per <= 0:
                net_payout_cents = 0
                exit_fee_cents = 0
            else:
                net_payout_cents, sd = kalshi_settlement_credit_cents(contracts, payout_per)
                ex["kalshi_settlement"] = sd
                exit_fee_cents = max(0, int(round(contracts * payout_per * 100.0)) - net_payout_cents)
            fee_bps_used = float(ex.get("paper_fee_bps", 0.0))
            pnl = net_payout_cents - amount
        elif fee_model == "none":
            payout_cents = int(round(contracts * payout_per * 100.0))
            net_payout_cents = payout_cents
            exit_fee_cents = 0
            fee_bps_used = 0.0
            pnl = net_payout_cents - amount
        else:
            payout_cents = int(round(contracts * payout_per * 100.0))
            fee_bps_used = fee_bps_now
            try:
                fee_bps_used = float(ex.get("paper_fee_bps", fee_bps_now))
            except (TypeError, ValueError):
                fee_bps_used = fee_bps_now
            exit_fee_cents = fee_cents_for_notional(payout_cents, fee_bps_used)
            net_payout_cents = max(0, payout_cents - exit_fee_cents)
            pnl = net_payout_cents - amount
        ex["settlement_exit_fee_cents"] = exit_fee_cents
        ex["settlement_net_payout_cents"] = net_payout_cents
        ex["paper_fee_model"] = fee_model
        await engine.store.update_trade_settlement(int(t["id"]), result, int(pnl), iso(now), extra_json=json.dumps(ex))
        settled_n += 1
    return settled_n


async def snapshot_equity(engine: TradingEngine) -> None:
    full_cfg = await engine.store.load_config()
    branch = engine.branch

    if branch == BRANCH_LIVE:
        trade_mode_filter = "simulate" if full_cfg.get("simulate") else "live"
    else:
        trade_mode_filter = "simulate"

    roll = await engine.store.dashboard_branch_trade_rollups(branch, trade_mode_filter)
    settled_pnl = int(roll.get("total_pnl_cents") or 0)
    open_committed = int(roll.get("open_committed_cents") or 0)

    if _is_lab_branch(branch) or (branch == BRANCH_LIVE and full_cfg.get("simulate")):
        if _is_lab_branch(branch):
            lab_key = "lab_a" if branch in (BRANCH_SIM_LAB, BRANCH_LAB_A) else "lab_b"
            lab = full_cfg.get(lab_key) or {}
            paper = int(lab.get("paper_balance_cents") or full_cfg.get("paper_balance_cents") or 500_000)
        else:
            paper = int(full_cfg.get("paper_balance_cents") or 500_000)
        equity = paper + settled_pnl - open_committed
        mode = "simulate"
    else:
        try:
            bal = await engine.client.get_private("/portfolio/balance")
            equity = int(bal.get("balance") or 0)
        except Exception:
            equity = 0
        mode = "live"

    await engine.store.insert_equity_snapshot(iso(utc_now()), mode, equity, "auto", branch=branch)


async def dual_engine_loop(engines: dict[str, TradingEngine], stop_event: Any) -> None:
    import asyncio

    tick = 0
    while not stop_event.is_set():
        try:
            eng_live = engines[BRANCH_LIVE]
            cfg = await eng_live.store.load_config()
            poll_candidates: list[float] = [float(cfg.get("poll_seconds") or 8)]
            branch_order = [BRANCH_LIVE, BRANCH_LAB_A, BRANCH_LAB_B]
            lab_conf = {
                BRANCH_LAB_A: cfg.get("lab_a") if isinstance(cfg.get("lab_a"), dict) else {},
                BRANCH_LAB_B: cfg.get("lab_b") if isinstance(cfg.get("lab_b"), dict) else {},
            }
            for bk, bcfg in lab_conf.items():
                if isinstance(bcfg, dict):
                    poll_candidates.append(float(bcfg.get("poll_seconds") or poll_candidates[0]))
            poll = max(poll_candidates)

            n_settled: dict[str, int] = {}
            n_swing: dict[str, int] = {}
            for br in branch_order:
                eng = engines.get(br)
                if not eng:
                    continue
                n_settled[br] = await settle_simulated_trades(eng)
                n_swing[br] = await maybe_swing_exit_open_sim_trades(eng, cfg)

            if cfg.get("engine_running"):
                await tick_once(engines[BRANCH_LIVE])
            for br in (BRANCH_LAB_A, BRANCH_LAB_B):
                lc = lab_conf[br] if isinstance(lab_conf.get(br), dict) else {}
                if lc.get("engine_running"):
                    # Legacy Lab A fraction nudger — do not run while main optimizer is enabled (avoids fighting Claude/adaptive).
                    oc0 = cfg.get("optimizer") if isinstance(cfg.get("optimizer"), dict) else {}
                    if tick % 25 == 0 and bool(lc.get("auto_optimize")) and not bool(oc0.get("enabled")):
                        await maybe_auto_optimize(eng_live.store)
                    if cfg.get("engine_running"):
                        await asyncio.sleep(0.4)
                    await tick_once(engines[br])

            tick += 1
            snap_period = tick % 5 == 0
            simulate_live = bool(cfg.get("simulate"))
            # Paper equity is derived from SQLite only — snapshot often so the chart matches settled/open counts.
            # Live real mode still snapshots only every 5 ticks while the engine runs (balance API).
            if simulate_live:
                if snap_period or n_settled.get(BRANCH_LIVE, 0) > 0 or n_swing.get(BRANCH_LIVE, 0) > 0:
                    await snapshot_equity(eng_live)
            elif snap_period and cfg.get("engine_running"):
                await snapshot_equity(eng_live)

            for br in (BRANCH_LAB_A, BRANCH_LAB_B):
                lc = lab_conf[br] if isinstance(lab_conf.get(br), dict) else {}
                if n_settled.get(br, 0) > 0 or n_swing.get(br, 0) > 0 or (snap_period and lc.get("engine_running")):
                    await snapshot_equity(engines[br])
        except Exception as e:
            err = str(e)
            _data_log(
                "system",
                {"event": "dual_engine_loop_error", "error": err[:800], "at": iso(utc_now())},
            )
            for eng in engines.values():
                eng.state.last_error = err

        cfg = await engines[BRANCH_LIVE].store.load_config()
        poll_live = float(cfg.get("poll_seconds") or 8)
        poll_lab_a = float(((cfg.get("lab_a") or {}) if isinstance(cfg.get("lab_a"), dict) else {}).get("poll_seconds") or poll_live)
        poll_lab_b = float(((cfg.get("lab_b") or {}) if isinstance(cfg.get("lab_b"), dict) else {}).get("poll_seconds") or poll_live)
        poll = max(poll_live, poll_lab_a, poll_lab_b)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll)
        except TimeoutError:
            pass


