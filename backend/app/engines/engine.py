from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import math
import re
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from dateutil import parser as dateparser

from ..branch_config import (
    BRANCH_LAB_A,
    BRANCH_LAB_B,
    BRANCH_LAB_C,
    BRANCH_LAB_D,
    BRANCH_LAB_E,
    BRANCH_LIVE,
    _lab_key_for_branch,
    lab_paper_equity_start_cents,
    effective_paper_fee_bps,
    effective_swing_exit_implied_drop_pct,
    kalshi_fee_multiplier_from_cfg,
    live_paper_trading_enabled,
    merge_branch_config,
    min_hold_minutes_before_stop_from_cfg,
    paper_fee_bps_from_cfg,
    paper_fee_model_from_cfg,
    resolve_kalshi_fee_multiplier,
    resolve_paper_fee_model,
    stop_loss_trigger_pct_from_cfg,
)
from ..kalshi_fees import kalshi_buy_debit_cents, kalshi_sell_credit_cents, kalshi_settlement_credit_cents
from ..kalshi_client import KalshiClient
from ..lab_communication import (
    LAB_CHATTER_BRANCHES,
    finalize_think_tank_tick,
    get_lab_communication_bus,
    think_tank_on_ranked_market,
    think_tank_on_sim_open,
)
from ..persistence import Store, _data_log
from ..settings_env import env
from ..types_kalshi import MarketRow

logger = logging.getLogger("kalshibot.engine")


def utc_now() -> dt.datetime:
    return dt.datetime.now(tz=dt.timezone.utc)


def _trade_row_matches_branch(row_branch: Any, target_branch: str) -> bool:
    """True if a SQLite trade/signal row belongs to the engine's logical branch (lab_a includes legacy sim_lab)."""
    b = str(row_branch or "live").strip().lower()
    t = str(target_branch or "live").strip().lower()
    if t == BRANCH_LAB_A:
        return b in ("lab_a", "sim_lab")
    return b == t


def iso(dtobj: dt.datetime) -> str:
    return dtobj.astimezone(dt.timezone.utc).isoformat()


def window_id_for(now: dt.datetime, window_minutes: int) -> str:
    epoch = int(now.timestamp())
    step = max(1, int(window_minutes)) * 60
    return str(epoch // step)


# Per-asset trade cap: 15-minute resolution keyed off contract ``close_time`` (falls back to wall clock if missing).
STUDY_TRADE_WINDOW_MINUTES = int(env.engine_study_trade_window_minutes)

# ─── HELPERS: time, prices, and rule geometry ─────────────────────────────────────────


def _study_cap_key(*, asset_id: str, ticker: str, close_time_iso: str, study_wall_wid: str) -> str:
    """In-memory dedupe: one new entry per (asset, contract ticker) per 15m close bucket within a process lifetime."""
    aid = str(asset_id).strip()
    tick = str(ticker or "").strip()
    if not aid or not tick:
        return ""
    slot = study_wall_wid
    raw = str(close_time_iso or "").strip()
    if raw:
        try:
            cd = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if cd.tzinfo is None:
                cd = cd.replace(tzinfo=dt.timezone.utc)
            cd = cd.astimezone(dt.timezone.utc)
            slot = window_id_for(cd, STUDY_TRADE_WINDOW_MINUTES)
        except (TypeError, ValueError, OSError):
            pass
    return f"{aid}:{tick}:{slot}"


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


def implied_yes_for_open_sim_marks(m: dict[str, Any]) -> float | None:
    """
    Implied P(YES) for paper MTM from a public /markets (or /market) row.

    List endpoints often have thin or one-sided YES quotes; this matches trading fallbacks
    (NO book, mirror, last trade) so mark value does not spuriously read as $0 while a position
    is open — the dashed curve shows potential recovery-to-$1 or slide toward a full loss of premium.
    """
    yb = dollars_to_float(m.get("yes_bid_dollars"))
    ya = dollars_to_float(m.get("yes_ask_dollars"))
    p = implied_yes_probability(yb, ya)
    if p is not None and math.isfinite(p):
        return max(0.0, min(1.0, float(p)))
    na = dollars_to_float(m.get("no_ask_dollars"))
    nb = dollars_to_float(m.get("no_bid_dollars"))
    if na is not None and 0 < na < 1:
        p_no = (na + nb) / 2.0 if (nb is not None and 0 < nb < 1) else na
        return max(0.0, min(1.0, 1.0 - p_no))
    e = effective_no_ask(m, yb, ya)
    if e is not None and 0 < e < 1:
        return max(0.0, min(1.0, 1.0 - float(e)))
    lp = dollars_to_float(m.get("last_price_dollars"))
    if lp is not None and 0 < lp < 1:
        return max(0.0, min(1.0, float(lp)))
    return None


def _entry_implied_yes_from_trade(t: dict[str, Any]) -> float | None:
    try:
        raw_ex = json.loads(str(t.get("extra_json") or "{}"))
    except json.JSONDecodeError:
        return None
    if not isinstance(raw_ex, dict):
        return None
    v = raw_ex.get("entry_implied_yes")
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return max(0.0, min(1.0, f))


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
    Enough YES-side pricing to evaluate YES rules.

    Kalshi **series list** rows often omit ``yes_bid_dollars`` while ``yes_ask_dollars`` is present; ``implied_yes_probability``
    still returns a clamped ask in that case. Requiring both sides used to drop every such row before ``pick_trade_rule``,
    so sim/live never fired despite a usable ask.
    """
    if prob is None or ya is None:
        return False
    try:
        fa = float(ya)
    except (TypeError, ValueError):
        return False
    if not (0 < fa <= 1.0):
        return False
    # Ask-only book: good enough for rule geometry and simulated YES buys at the ask.
    if yb is None:
        return True
    try:
        fb = float(yb)
    except (TypeError, ValueError):
        return True
    if not (0 < fb < 1):
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


def no_bet_yes_implied_cutoff(cfg: dict[str, Any]) -> float | None:
    """
    When ``no_bet_when_yes_below_pct`` is set (1–95), implied YES **strictly below** this probability
    (e.g. 0.32 for 32%) means only NO-side rules are eligible — YES bands are ignored so settings-driven
    NO / auto-NO logic can run.
    """
    raw = cfg.get("no_bet_when_yes_below_pct")
    if raw is None or raw is False:
        return None
    try:
        pct = float(raw)
    except (TypeError, ValueError):
        return None
    thr = pct / 100.0
    if not (0 < thr <= 0.95):
        return None
    return thr


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


def effective_no_ask(
    market: dict[str, Any],
    yes_bid: float | None,
    yes_ask: float | None = None,
) -> float | None:
    """
    Best NO ask in dollars for rule checks and NO limit price.

    Order: explicit ``no_ask_dollars`` from the market row, else ``1 − yes_bid`` (standard binary mirror),
    else ``1 − yes_ask`` when the list row has **ask-only** YES (common on Kalshi series feeds). Without this
    last fallback ``has_no_book`` stays false and **no NO-side trades** fire even when NO sliders match.
    """
    na = dollars_to_float(market.get("no_ask_dollars"))
    if na is not None and 0 < na < 1:
        return na
    if yes_bid is not None and 0 < yes_bid < 1:
        return 1.0 - yes_bid
    if yes_ask is not None and 0 < yes_ask < 1:
        comp = 1.0 - float(yes_ask)
        if 0 < comp < 1:
            return comp
    return None


def rule_axis_probability(prob_yes: float, rule: dict[str, Any]) -> float:
    """Scalar on which ``min_prob``/``max_prob`` apply: implied YES, or implied NO when ``side`` is ``no``."""
    return (1.0 - prob_yes) if rule_trade_side(rule) == "no" else prob_yes


def rule_matches(
    prob_yes: float | None, mins: float | None, rule: dict[str, Any]
) -> bool:
    """
    True only when **both** hold (inclusive bounds):

    - **Price band:** ``min_prob`` ≤ *axis* ≤ ``max_prob``, where *axis* is implied YES mid unless ``side: no``,
      then *axis* is implied NO (= 1 − YES mid).
    - **Time band:** ``min_minutes_left`` ≤ minutes to close ≤ ``max_minutes_left``.

    Gaps **between** configured rules (e.g. YES 0.52 vs next band 0.55) mean **no** match — that is intentional
    unless you widen or add a rule to cover the hole.
    """
    if prob_yes is None or mins is None:
        return False
    p = rule_axis_probability(prob_yes, rule)
    if p < float(rule["min_prob"]) or p > float(rule["max_prob"]):
        return False
    if mins < float(rule["min_minutes_left"]) or mins > float(rule["max_minutes_left"]):
        return False
    return True


def pick_trade_rule(
    prob_yes: float,
    mins: float,
    rules: list[dict[str, Any]],
    *,
    has_yes_rules: bool,
    has_no_book: bool,
    cfg: dict[str, Any],
) -> dict[str, Any] | None:
    """
    Choose one rule to execute: when implied YES is below ``no_bet_when_yes_below_pct``, only NO-side rules
    are considered; otherwise YES rules are tried first, then NO rules (binary YES-then-NO vs list order).
    """
    cutoff = no_bet_yes_implied_cutoff(cfg)
    yes_rules = [r for r in rules if isinstance(r, dict) and rule_trade_side(r) != "no"]
    no_rules = [r for r in rules if isinstance(r, dict) and rule_trade_side(r) == "no"]

    def scan(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
        for r in candidates:
            if not rule_matches(prob_yes, mins, r):
                continue
            if rule_trade_side(r) == "no" and not has_no_book:
                continue
            if rule_trade_side(r) != "no" and not has_yes_rules:
                continue
            return r
        return None

    if cutoff is not None and prob_yes < cutoff:
        return scan(no_rules)
    hit = scan(yes_rules)
    if hit is not None:
        return hit
    return scan(no_rules)


def _market_sim_trade_rank(
    market: dict[str, Any],
    *,
    rules: list[dict[str, Any]],
    cfg: dict[str, Any],
    subtitle_filter: str,
    exclude_substrings: list[str],
    now: dt.datetime,
    dev_floor: float | None,
    simulate_orders: bool,
) -> tuple[int, float, float]:
    """
    Sort key for ``reverse=True`` (best first): among markets with a matched rule and tradable book,
    prefer higher *edge* = implied mid minus the limit price (YES ask or NO ask). Then prefer more
    minutes to close. Rows with no opportunity sort last so API list order no longer wins by default.
    """
    if not isinstance(market, dict):
        return (0, -1e18, 0.0)
    ticker = str(market.get("ticker") or "")
    if not ticker:
        return (0, -1e18, 0.0)
    mstatus = str(market.get("status") or "").lower()
    if mstatus and mstatus not in ("active", "open"):
        return (0, -1e18, 0.0)
    yes_sub = str(market.get("yes_sub_title") or market.get("subtitle") or "").lower()
    if subtitle_filter and subtitle_filter not in yes_sub:
        return (0, -1e18, 0.0)
    for ex in exclude_substrings:
        if ex and ex in yes_sub:
            return (0, -1e18, 0.0)
    close_time = str(market.get("close_time") or "")
    mins = minutes_left(close_time, now)
    if mins is None or mins <= 0:
        return (0, -1e18, 0.0)
    yb = dollars_to_float(market.get("yes_bid_dollars"))
    ya = dollars_to_float(market.get("yes_ask_dollars"))
    prob = implied_yes_probability(yb, ya)
    na = effective_no_ask(market, yb, ya)
    has_yes_rules = has_yes_book_for_rules(yb, ya, prob)
    has_no_book = na is not None and 0 < na < 1
    if prob is None or (not has_yes_rules and not has_no_book):
        return (0, -1e18, float(mins))
    matched_rule = pick_trade_rule(
        prob,
        mins,
        rules,
        has_yes_rules=has_yes_rules,
        has_no_book=has_no_book,
        cfg=cfg,
    )
    if not matched_rule:
        if dev_floor is not None and simulate_orders and has_yes_rules and prob is not None:
            dev_rule = _dev_sim_high_yes_rule(dev_floor)
            if rule_matches(prob, mins, dev_rule):
                matched_rule = dict(dev_rule)
    if not matched_rule:
        return (0, -1e18, float(mins))
    trade_side = rule_trade_side(matched_rule)
    if trade_side == "yes":
        if not has_tradable_yes_ask(ya) and not simulate_orders:
            return (0, -1e18, float(mins))
        if ya is None:
            return (1, -1e18, float(mins))
    else:
        if na is None or not (0 < na < 1):
            return (0, -1e18, float(mins))
        p_no = implied_no_probability(yb, ya)
        if p_no is None:
            return (1, -1e18, float(mins))
    from ..optimizer.weighted_edge import calculate_weighted_edge

    edge = float(calculate_weighted_edge(market, matched_rule))
    return (1, edge, float(mins))


def rule_match_miss_hint(prob_yes: float, mins: float, rules: list[Any], *, cfg: dict[str, Any] | None = None) -> str:
    """
    Human hint when the headline row has a book but ``rules_matched`` is empty — same prob/time geometry as
    ``rule_matches`` (order-book side checks are applied separately when actually trading).
    """
    usable = [r for r in rules if isinstance(r, dict)]
    cutoff = no_bet_yes_implied_cutoff(cfg) if cfg else None
    if cutoff is not None and prob_yes < cutoff:
        usable = [r for r in usable if rule_trade_side(r) == "no"]
        if not usable:
            return (
                f"Implied YES ≈{prob_yes:.2f} is below your auto-NO threshold ({cutoff * 100:.0f}% on the YES scale) — "
                "only NO-side rules apply here, but none are configured. Add a NO rule or raise the threshold."
            )
    if not usable:
        return "No rules in config — add at least one rule band under Settings."
    for r in usable:
        p = rule_axis_probability(prob_yes, r)
        in_p = float(r["min_prob"]) <= p <= float(r["max_prob"])
        in_t = float(r["min_minutes_left"]) <= mins <= float(r["max_minutes_left"])
        if in_p and not in_t:
            return (
                f"“{r.get('name')}”: probability on this rule’s axis is {p:.2f} (inside the band) but "
                f"{mins:.1f}m to close is outside this rule’s "
                f"[{float(r['min_minutes_left']):g},{float(r['max_minutes_left']):g}]m window — no trade."
            )
    for r in usable:
        p = rule_axis_probability(prob_yes, r)
        in_p = float(r["min_prob"]) <= p <= float(r["max_prob"])
        in_t = float(r["min_minutes_left"]) <= mins <= float(r["max_minutes_left"])
        if in_t and not in_p:
            axis = "implied NO (1 − YES mid)" if rule_trade_side(r) == "no" else "implied YES mid"
            return (
                f"“{r.get('name')}”: time {mins:.1f}m is OK but {axis} = {p:.2f} is outside "
                f"[{float(r['min_prob']):.2f},{float(r['max_prob']):.2f}] on that axis — no trade."
            )
    return (
        f"No rule contains this outcome together: YES mid ≈{prob_yes:.2f} with {mins:.1f}m left vs each rule’s "
        "probability **and** time windows. Stock defaults leave gaps (e.g. ~52–55% and ~72–78% YES between "
        "Low/Mid/High). Widen bands or add a rule to cover the hole."
    )


@dataclass
class EngineState:
    last_tick_at: str | None = None
    last_error: str | None = None
    markets_scanned: int = 0
    last_tick_trace: list[str] | None = None
    # Per asset_id: headline market from last tick (for dashboard; not persisted).
    asset_snapshots: dict[str, dict[str, Any]] | None = None


# ─── HELPERS: engine state + tick orchestration ───────────────────────────────────────
class TradingEngine:
    # PHASE 4: keep ``client`` optional for backward safety; prefer shared injection from ``state.require_kalshi()``.
    def __init__(self, store: Store, branch: str = BRANCH_LIVE, *, client: KalshiClient | None = None) -> None:
        self.store = store
        self.branch = branch
        if client is None:
            logger.warning("PHASE 4: TradingEngine(%s) created without injected shared KalshiClient; falling back to new client", branch)
            self.client = KalshiClient()
        else:
            self.client = client
        self.state = EngineState()
        self._seen_keys: set[str] = set()
        self._last_window_id: str | None = None
        self._tick_count: int = 0
        # One automatic branch wipe per error streak when lab auto-reset is enabled.
        self._paper_auto_reset_streak_handled: bool = False
        # Legacy RAM cap (per contract close bucket); sim also uses SQLite per-ticker open guard + budget-window cap.
        self._study_quarter_wid: str | None = None
        self._study_asset_fired: set[str] = set()
        self._study_cap_logged: set[str] = set()
        # At most one new simulated entry per configured asset per balance ``window_id`` (stops repeat fires
        # in the same budget window). Series-wide cap is enforced in SQLite: one open sim per ``series_ticker``
        # prefix per branch (see ``insert_sim_trade_single_open_per_ticker``).
        self._sim_asset_budget_fired: set[str] = set()
        # One log/trace line per budget window for *transient* sim guards (series/ticker already open, atomic race).
        # Do **not** fold these into ``_seen_keys`` — that blocked retries before re-checking guards after settlement.
        self._sim_transient_skip_logged: set[str] = set()
        # Labs B/C/D think tank (observation-only). Share caps + staggered pulses in ``lab_communication`` balance B/C/D voice.
        self._lab_think_tank_next_pulse_mono: float = 0.0
        self._lab_think_tank_last_publish_mono: float = 0.0
        self._lab_think_tank_msgs_this_tick: int = 0
        self._lab_think_tank_market_note_sent: bool = False
        self._lab_think_tank_intro_done: bool = False


def _is_lab_branch(branch: str) -> bool:
    return branch in (BRANCH_LAB_A, BRANCH_LAB_B, BRANCH_LAB_C, BRANCH_LAB_D, BRANCH_LAB_E)


async def tick_once(engine: TradingEngine, *, full_cfg: dict[str, Any] | None = None) -> None:
    now = utc_now()
    engine.state.last_tick_at = iso(now)
    engine.state.last_error = None

    if full_cfg is None:
        full_cfg = await engine.store.load_config()
    cfg = merge_branch_config(full_cfg, engine.branch)
    if not cfg:
        # Otherwise ``last_tick_trace`` stayed stale and looked like the branch was still scanning markets.
        br = str(engine.branch)
        engine.state.markets_scanned = 0
        engine.state.asset_snapshots = {}
        engine.state.last_tick_trace = [
            f"skip {iso(now)} | branch={br} | no merged config — start the engine: "
            f"Settings / ``engine_running`` (Live) or each lab’s ``engine_running`` must be on. "
            f"Child ``lab_child_*`` only stop when engine_running is explicitly off."
        ]
        return

    first_branch_tick = engine._tick_count == 0
    # PHASE 3: env-backed caps preserve defaults while making tuning explicit.
    ob_enrich_cap = int(env.engine_orderbook_enrich_first_tick_cap) if (KalshiClient.prewarm_complete and first_branch_tick) else int(env.engine_orderbook_enrich_steady_cap)

    # PHASE 4: default comes from typed settings while preserving behavior (still overridable in cfg).
    # PHASE FINAL: typed env-backed default, preserving prior fallback value (15).
    window_minutes = int(cfg.get("window_minutes") or env.default_window_minutes)
    wid = window_id_for(now, window_minutes)
    if engine._last_window_id != wid:
        engine._seen_keys.clear()
        engine._sim_asset_budget_fired.clear()
        engine._sim_transient_skip_logged.clear()
        engine._last_window_id = wid

    study_wid = window_id_for(now, STUDY_TRADE_WINDOW_MINUTES)
    if engine._study_quarter_wid != study_wid:
        engine._study_asset_fired.clear()
        engine._study_cap_logged.clear()
        engine._study_quarter_wid = study_wid

    trade_mode = str(cfg.get("_trade_mode") or "simulate")
    branch = str(cfg.get("_branch") or "live")
    if branch in LAB_CHATTER_BRANCHES:
        engine._lab_think_tank_msgs_this_tick = 0
        engine._lab_think_tank_market_note_sent = False

    balance_cents = 0
    if _is_lab_branch(branch):
        lab_key = _lab_key_for_branch(branch) or "lab_a"
        lab = full_cfg.get(lab_key) or {}
        # PHASE FINAL: typed default from settings_env (same fallback as before).
        balance_cents = int(lab.get("paper_balance_cents") or full_cfg.get("paper_balance_cents") or env.default_paper_balance_cents)
    elif trade_mode == "simulate" or bool(cfg.get("_simulate_orders")):
        # Live branch paper sim: stake against configured bankroll only (not exchange balance).
        balance_cents = int(cfg.get("paper_balance_cents") or full_cfg.get("paper_balance_cents") or env.default_paper_balance_cents)
    else:
        try:
            bal = await engine.client.get_private("/portfolio/balance")
            if not isinstance(bal, dict):
                bal = {}
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
        if not isinstance(data, dict):
            data = {}
        markets = list(data.get("markets") or [])
        scanned += len(markets)
        trace.append(f"asset {asset_id} series={series}: fetched {len(markets)} open markets")
        ob_n = await enrich_markets_with_orderbooks(engine.client, markets, now, max_fetches=ob_enrich_cap)
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
            rule_pick_cfg=cfg,
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
        ranked_markets = sorted(
            [m for m in markets if isinstance(m, dict)],
            key=lambda mm: _market_sim_trade_rank(
                mm,
                rules=rules,
                cfg=cfg,
                subtitle_filter=subtitle_filter,
                exclude_substrings=exclude_substrings,
                now=now,
                dev_floor=dev_floor,
                simulate_orders=sim_orders,
            ),
            reverse=True,
        )
        hive_bus = get_lab_communication_bus() if branch in LAB_CHATTER_BRANCHES else None
        for idx, m in enumerate(ranked_markets):
            prob_rank: float | None = None
            if hive_bus is not None and isinstance(m, dict):
                _yb = dollars_to_float(m.get("yes_bid_dollars"))
                _ya = dollars_to_float(m.get("yes_ask_dollars"))
                prob_rank = implied_yes_probability(_yb, _ya)
            kind = await handle_market(
                engine,
                cfg=cfg,
                trade_mode=trade_mode,
                branch=branch,
                window_id=wid,
                asset_id=str(asset_id),
                series_ticker=series,
                market=m,
                rules=rules,
                subtitle_filter=subtitle_filter,
                exclude_substrings=exclude_substrings,
                balance_cents=balance_cents,
                study_wall_wid=study_wid,
                trace=trace,
            )
            if hive_bus is not None:
                think_tank_on_ranked_market(
                    engine,
                    branch,
                    idx=idx,
                    kind=kind,
                    ticker=str(m.get("ticker") or ""),
                    implied_yes=prob_rank,
                    bus=hive_bus,
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
            rule_pick_cfg=cfg,
        )

    engine.state.markets_scanned = scanned
    engine.state.asset_snapshots = snapshots
    engine.state.last_tick_trace = trace[-150:]

    try:
        n_psl = await _handle_patient_stop_loss_exits(engine, full_cfg=full_cfg, cfg=cfg, now=now, trace=trace)
        if n_psl:
            _trace_append(trace, f"patient_stop_loss {branch}: closed {n_psl} position(s) this tick")
    except Exception as e:
        _trace_append(trace, f"patient_stop_loss {branch}: handler error {str(e)[:200]}")
        engine.state.last_error = f"patient_stop_loss: {e}"

    await _maybe_auto_reset_lab_paper_on_tick_failure(engine, full_cfg)

    if branch in LAB_CHATTER_BRANCHES:
        finalize_think_tank_tick(engine, branch, snapshots, scanned, full_cfg=full_cfg)

    engine._tick_count += 1


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

    lab_key = _lab_key_for_branch(br_engine) or "lab_a"
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
        paper = int(lab.get("paper_balance_cents") or full_cfg.get("paper_balance_cents") or env.default_paper_balance_cents)
        equity_cents = paper + settled_pnl - open_committed
        bust = equity_cents <= 0

    should_wipe = (bool(err) or bust) and not engine._paper_auto_reset_streak_handled
    if should_wipe:
        rb = br_engine
        await engine.store.reset_trading_data(backup=False, branch=rb)
        await engine.store.bump_lab_paper_lifetime_basis(rb)
        try:
            await snapshot_equity(engine, full_cfg=full_cfg)
        except Exception:
            pass
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
        engine._last_window_id = None
        engine._tick_count = 0
        engine._study_quarter_wid = None
        engine._study_asset_fired.clear()
        engine._study_cap_logged.clear()
        engine._sim_asset_budget_fired.clear()
        engine._sim_transient_skip_logged.clear()
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
    rule_pick_cfg: dict[str, Any] | None = None,
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
            na = effective_no_ask(m, yb, ya)
            has_yes_rules = has_yes_book_for_rules(yb, ya, prob)
            has_no_book = na is not None and 0 < na < 1
            has_priced_book = has_yes_rules or has_no_book
            if require_orderbook and not has_priced_book:
                continue
            matched_names: list[str] = []
            if prob is not None:
                if rule_pick_cfg is not None:
                    picked = pick_trade_rule(
                        prob,
                        mins,
                        rules,
                        has_yes_rules=has_yes_rules,
                        has_no_book=has_no_book,
                        cfg=rule_pick_cfg,
                    )
                    if picked is not None:
                        matched_names.append(str(picked.get("name") or "rule"))
                else:
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
                "rule_match_hint": (
                    rule_match_miss_hint(prob, mins, rules, cfg=rule_pick_cfg)
                    if (not matched_names and prob is not None and has_priced_book)
                    else None
                ),
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
    markets: list[MarketRow | dict[str, Any]],
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


# ─── HELPERS: trade execution path (sim/live) ─────────────────────────────────────────
async def handle_market(
    engine: TradingEngine,
    *,
    cfg: dict[str, Any],
    trade_mode: str,
    branch: str,
    window_id: str,
    asset_id: str,
    series_ticker: str,
    market: dict[str, Any],
    rules: list[dict[str, Any]],
    subtitle_filter: str,
    exclude_substrings: list[str],
    balance_cents: int,
    study_wall_wid: str,
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
    na = effective_no_ask(market, yb, ya)
    has_yes_rules = has_yes_book_for_rules(yb, ya, prob)
    has_no_book = na is not None and 0 < na < 1
    if prob is None or (not has_yes_rules and not has_no_book):
        return None

    matched_rule = pick_trade_rule(
        prob,
        mins,
        rules,
        has_yes_rules=has_yes_rules,
        has_no_book=has_no_book,
        cfg=cfg,
    )
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

    cap_key = _study_cap_key(asset_id=asset_id, ticker=ticker, close_time_iso=close_time, study_wall_wid=study_wall_wid)
    if cap_key and cap_key in engine._study_asset_fired:
        if cap_key not in engine._study_cap_logged:
            engine._study_cap_logged.add(cap_key)
            _trace_append(
                trace,
                f"  {asset_id} {ticker[:40]}… 1 trade per contract per 15m close bucket (cap)",
            )
        return None

    series_up = str(series_ticker or "").strip().upper()
    simulate = bool(cfg.get("_simulate_orders"))
    if simulate:
        open_blocker_tk: str | None = None
        if series_up:
            open_blocker_tk = await engine.store.first_open_sim_ticker_for_series_prefix(branch, series_up)
        if open_blocker_tk:
            logger.info(
                "[sim_trade_block] skip reason=series_has_open_sim series_family=%s branch=%s new_ticker=%s open_blocker=%s grep=series_open_sim",
                series_up,
                branch,
                str(ticker)[:48],
                str(open_blocker_tk)[:64],
            )
            bt = str(open_blocker_tk)[:100]
            skip_lbl = f"series_has_open_sim — already open: {bt}"
            _skip_log_k = f"{window_id}:{dedupe_key}:series_open"
            if _skip_log_k not in engine._sim_transient_skip_logged:
                engine._sim_transient_skip_logged.add(_skip_log_k)
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
                    skip_reason=skip_lbl,
                    mode=trade_mode,
                    branch=branch,
                    extra={
                        "series_ticker": series_up,
                        "ticker": ticker,
                        "open_blocker_ticker": bt,
                        "note": "At most one open simulated position per series per branch — settle or exit the listed open (or close early) before a new contract in that series.",
                    },
                )
                _trace_append(
                    trace,
                    f"  {asset_id} {ticker[:40]}… skip: series {series_up[:24]}… open sim {bt[:36]}… blocks this branch",
                )
            # Do not add ``dedupe_key`` to ``_seen_keys`` — blocker can clear mid-window; dedupe would skip retries until ``window_id`` rolls.
            return None
        aid = str(asset_id).strip()
        if aid and aid in engine._sim_asset_budget_fired:
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
                skip_reason="asset_budget_one_sim_per_window",
                mode=trade_mode,
                branch=branch,
                extra={
                    "window_id": window_id,
                    "note": "At most one new simulated entry per configured asset per balance window; try again next window or use another asset.",
                },
            )
            engine._seen_keys.add(dedupe_key)
            _trace_append(
                trace,
                f"  {asset_id} {ticker[:40]}… skip: this asset already took a sim slot this budget window ({branch})",
            )
            return None
        if ticker.strip() and await engine.store.has_open_sim_for_ticker(branch, trade_mode, ticker):
            _skip_log_k = f"{window_id}:{dedupe_key}:ticker_open"
            if _skip_log_k not in engine._sim_transient_skip_logged:
                engine._sim_transient_skip_logged.add(_skip_log_k)
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
                    skip_reason="ticker_has_open_sim",
                    mode=trade_mode,
                    branch=branch,
                    extra={
                        "ticker": ticker,
                        "note": "At most one open simulated ticket per market (exact ticker) per branch until it settles or is closed early.",
                    },
                )
                _trace_append(
                    trace,
                    f"  {asset_id} {ticker[:40]}… skip: open sim already exists for this market ({branch})",
                )
            return None

    window_minutes = int(cfg.get("window_minutes") or env.default_window_minutes)
    spent = await spent_in_window(engine.store, window_id, trade_mode, window_minutes, branch)
    fraction = float(cfg.get("balance_fraction_per_window") or env.default_balance_fraction_per_window)
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
    min_c = int(cfg.get("min_contracts") or env.default_min_contracts)
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
        trade_row: dict[str, Any] = {
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
        if ticker.strip():
            tid = await engine.store.insert_sim_trade_single_open_per_ticker(
                trade_row,
                branch=branch,
                trade_mode=trade_mode,
                market_ticker=ticker,
                series_exclusive_prefix=series_up or None,
            )
        else:
            tid = await engine.store.insert_trade(trade_row)
        if tid is None:
            _skip_log_k = f"{window_id}:{dedupe_key}:atomic_guard"
            if _skip_log_k not in engine._sim_transient_skip_logged:
                engine._sim_transient_skip_logged.add(_skip_log_k)
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
                    skip_reason="sim_single_open_guard",
                    mode=trade_mode,
                    branch=branch,
                    extra={
                        "ticker": ticker,
                        "series_ticker": series_up or None,
                        "note": "Insert blocked: another open sim on this series or ticker won the write lock (one per series prefix per branch).",
                    },
                )
                _trace_append(
                    trace,
                    f"  {asset_id} {ticker[:40]}… skip: open sim already exists for this market ({branch}, atomic)",
                )
            return None
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
        if cap_key:
            engine._study_asset_fired.add(cap_key)
        engine._seen_keys.add(dedupe_key)
        aid_ok = str(asset_id).strip()
        if aid_ok:
            engine._sim_asset_budget_fired.add(aid_ok)
        _trace_append(
            trace,
            f"  SIM {branch} {asset_id} {ticker[:36]}… BUY {contracts_fp} {trade_side.upper()} @≈{limit_px:.3f} "
            f"rule=“{matched_rule.get('name')}” yes={prob:.2f} mins={mins:.1f} "
            f"cost¢={gross_amount_cents} (prem¢={amount_cents} fee¢={entry_fee_cents}, stake_cap¢={stake_cents} avail¢={available_cents})",
        )
        if branch in LAB_CHATTER_BRANCHES:
            think_tank_on_sim_open(
                engine,
                branch,
                ticker=ticker,
                side=str(trade_side),
                implied_yes=prob,
                rule_name=str(matched_rule.get("name") or ""),
                bus=get_lab_communication_bus(),
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
        if cap_key:
            engine._study_asset_fired.add(cap_key)
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


# ─── HELPERS: settlement, MTM, and exit management ────────────────────────────────────
def market_dict_from_public_response(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    m = data.get("market")
    if isinstance(m, dict):
        return m
    if "ticker" in data or "yes_bid_dollars" in data:
        return data
    return {}


def _parse_contracts_fp(raw: Any) -> float:
    """Position size from ``contracts_fp`` (or legacy numeric); 0 if missing/invalid so settlement/MTM never throws."""
    if raw is None or raw == "":
        return 0.0
    if isinstance(raw, bool):
        return 0.0
    if isinstance(raw, (int, float)):
        f = float(raw)
        return f if math.isfinite(f) and f > 0 else 0.0
    s = str(raw).strip().replace(",", "")
    if not s:
        return 0.0
    try:
        f = float(s)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(f) or f <= 0:
        return 0.0
    return f


def _public_market_path(ticker: str) -> str:
    """Path for GET /markets/{ticker} with an encoded ticker segment."""
    tk = str(ticker or "").strip()
    return f"/markets/{quote(tk, safe='')}"


def _normalize_settled_outcome_yes_no(m: dict[str, Any]) -> str | None:
    """Winning side ``yes`` / ``no`` once Kalshi marks the contract resolved (field names vary by API version)."""
    for key in ("result", "market_result", "outcome", "winner"):
        raw = m.get(key)
        if raw is None or raw == "":
            continue
        s = str(raw).strip().lower()
        if s in ("yes", "no"):
            return s
    yw = m.get("yes_won")
    if isinstance(yw, bool):
        return "yes" if yw else "no"
    if isinstance(yw, (int, float)):
        try:
            vi = int(yw)
        except (TypeError, ValueError):
            vi = None
        if vi == 1:
            return "yes"
        if vi == 0:
            return "no"
    return None


def _fair_value_open_sim_position_cents(
    m: dict[str, Any], *, side: str, contracts: float, entry_implied_yes: float | None = None
) -> int:
    """
    Mark value in cents: position notional × P(your side wins) at current public quotes.
    As quotes move against you, this trends toward 0 (full loss of premium at resolution);
    in your favor, toward full payout. ``entry_implied_yes`` is a last-resort when the feed
    is one-sided (same idea as the entry snapshot).
    """
    if contracts <= 0 or not math.isfinite(contracts):
        return 0
    py = implied_yes_for_open_sim_marks(m)
    if py is None and entry_implied_yes is not None and math.isfinite(float(entry_implied_yes)):
        py = max(0.0, min(1.0, float(entry_implied_yes)))
    if py is None or not math.isfinite(py):
        return 0
    py = max(0.0, min(1.0, float(py)))
    if str(side or "yes").lower() == "no":
        py = 1.0 - py
    return int(round(contracts * 100.0 * py))


async def compute_open_sim_mark_value_sum_cents(engine: TradingEngine, open_rows: list[dict[str, Any]]) -> int:
    """Sum mark-to-market cents for open simulated rows (one public market fetch per distinct ticker)."""
    if not open_rows:
        return 0
    by_ticker: dict[str, list[dict[str, Any]]] = {}
    for t in open_rows:
        tk = str(t.get("ticker") or "").strip()
        if not tk:
            continue
        by_ticker.setdefault(tk, []).append(t)

    # Parallelize with a cap; cross-branch MTM also dedupes GET /markets/{t} in KalshiClient for ~2.5s.
    sem = asyncio.Semaphore(8)

    async def mark_one(ticker: str, rows: list[dict[str, Any]]) -> int:
        async with sem:
            sub = 0
            try:
                data = await asyncio.wait_for(
                    engine.client.get_market_json_by_ticker_cached(ticker),
                    timeout=4.5,
                )
            except Exception:
                return 0
            m = market_dict_from_public_response(data)
            if not m:
                return 0
            for row in rows:
                side = str(row.get("side") or "yes")
                contracts = _parse_contracts_fp(row.get("contracts_fp"))
                eiy = _entry_implied_yes_from_trade(row)
                sub += _fair_value_open_sim_position_cents(
                    m, side=side, contracts=contracts, entry_implied_yes=eiy
                )
            return sub

    parts = await asyncio.gather(
        *[mark_one(ticker, rows) for ticker, rows in by_ticker.items()],
        return_exceptions=True,
    )
    total = 0
    for p in parts:
        if isinstance(p, int):
            total += p
    return total


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


def _calculate_net_unrealized_pct_after_fees(
    position: dict[str, Any],
    current_mid: float,
    *,
    full_cfg: dict[str, Any],
    branch: str,
) -> float:
    """
    Unrealized return (%) on total cash debited at entry (``amount_cents``) if we sold the open sim
    at a limit price derived from ``current_mid`` (implied YES 0–1), using the same fee model as
    swing / timeout exits (Kalshi quadratic or bps or none).

    Includes full round-trip fee impact on exit (entry fee is already embedded in ``amount_cents``;
    this subtracts modeled sell-side fees from hypothetical proceeds).
    """
    try:
        py = float(current_mid)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(py):
        return 0.0
    py = max(0.0, min(1.0, py))
    side = str(position.get("side") or "yes").strip().lower()
    if side not in ("yes", "no"):
        return 0.0
    contracts = _parse_contracts_fp(position.get("contracts_fp"))
    if contracts <= 0:
        return 0.0
    cost = int(position.get("amount_cents") or 0)
    if cost <= 0:
        return 0.0
    exit_px = py if side == "yes" else max(1e-6, min(1.0 - 1e-6, 1.0 - py))
    proceeds_cents = int(round(contracts * exit_px * 100.0))
    try:
        raw_ex = json.loads(str(position.get("extra_json") or "{}"))
        extra = dict(raw_ex) if isinstance(raw_ex, dict) else {}
    except json.JSONDecodeError:
        extra = {}
    fee_model = resolve_paper_fee_model(extra, full_cfg, branch)
    fee_mult = resolve_kalshi_fee_multiplier(extra, full_cfg, branch)
    kalshi_maker = fee_model == "kalshi_maker"
    fee_bps_now = effective_paper_fee_bps(full_cfg, branch)
    if fee_model in ("kalshi_taker", "kalshi_maker"):
        net_proceeds_cents, _kb = kalshi_sell_credit_cents(
            contracts, exit_px, maker=kalshi_maker, fee_multiplier=fee_mult
        )
    elif fee_model == "none":
        net_proceeds_cents = proceeds_cents
    else:
        fee_bps_used = fee_bps_now
        try:
            fee_bps_used = float(extra.get("paper_fee_bps", fee_bps_now))
        except (TypeError, ValueError):
            fee_bps_used = fee_bps_now
        exit_fee_cents = fee_cents_for_notional(proceeds_cents, fee_bps_used)
        net_proceeds_cents = max(0, proceeds_cents - exit_fee_cents)
    unrealized_cents = int(net_proceeds_cents) - int(cost)
    return (float(unrealized_cents) / float(cost)) * 100.0


async def _handle_patient_stop_loss_exits(
    engine: TradingEngine,
    *,
    full_cfg: dict[str, Any],
    cfg: dict[str, Any],
    now: dt.datetime,
    trace: list[str],
) -> int:
    """
    Paper sim: after rules run, close positions held long enough whose fee-aware mark-to-exit P&L%
    is at or below ``stop_loss_trigger_pct`` (negative threshold vs entry debit).
    """
    branch = str(cfg.get("_branch") or engine.branch)
    if branch == BRANCH_LIVE and not live_paper_trading_enabled(full_cfg):
        return 0
    if not bool(cfg.get("enable_patient_stop_loss", True)):
        _trace_append(trace, f"patient_stop_loss {branch}: disabled in config, skip")
        return 0
    thr = float(stop_loss_trigger_pct_from_cfg(cfg))
    min_hold = int(min_hold_minutes_before_stop_from_cfg(cfg))
    open_rows = await engine.store.open_sim_trades_for_branch(branch)
    if not open_rows:
        return 0
    closed_n = 0
    for t in open_rows:
        if int(t.get("simulated") or 0) != 1:
            continue
        try:
            tid_raw = t.get("id")
            if tid_raw is None:
                continue
            tid = int(tid_raw)
            ticker = str(t.get("ticker") or "").strip()
            if not ticker:
                continue
            side = str(t.get("side") or "yes").strip().lower()
            if side not in ("yes", "no"):
                continue
            created_raw = str(t.get("created_at") or "").strip()
            if not created_raw:
                continue
            created_dt = dateparser.isoparse(created_raw)
            if created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=dt.timezone.utc)
            minutes_held = (now - created_dt.astimezone(dt.timezone.utc)).total_seconds() / 60.0
            if minutes_held < float(min_hold):
                continue
            try:
                data = await engine.client.get_public(_public_market_path(ticker))
            except Exception as e:
                _trace_append(trace, f"patient_stop_loss {branch} {ticker[:28]}… fetch err {str(e)[:80]}")
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
            net_pct = _calculate_net_unrealized_pct_after_fees(t, prob, full_cfg=full_cfg, branch=branch)
            if net_pct > thr:
                continue
            contracts = _parse_contracts_fp(t.get("contracts_fp"))
            if contracts <= 0:
                continue
            cost = int(t.get("amount_cents") or 0)
            exit_px = exit_bid_for_side_close(m, side, yb, ya)
            if exit_px is None or exit_px <= 0:
                _trace_append(trace, f"patient_stop_loss {branch} {ticker[:28]}… skip (no exit bid)")
                continue
            try:
                raw_ex = json.loads(str(t.get("extra_json") or "{}"))
                extra = dict(raw_ex) if isinstance(raw_ex, dict) else {}
            except json.JSONDecodeError:
                extra = {}
            proceeds_cents = int(round(contracts * exit_px * 100.0))
            fee_model = resolve_paper_fee_model(extra, full_cfg, branch)
            fee_mult = resolve_kalshi_fee_multiplier(extra, full_cfg, branch)
            kalshi_maker = fee_model == "kalshi_maker"
            fee_bps_now = effective_paper_fee_bps(full_cfg, branch)
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
            pnl = int(net_proceeds_cents) - int(cost)
            extra.update(
                {
                    "patient_stop_loss": True,
                    "patient_stop_loss_mark_implied_yes": prob,
                    "patient_stop_loss_net_unrealized_pct_after_fees": round(net_pct, 4),
                    "patient_stop_loss_minutes_held": round(minutes_held, 2),
                    "patient_stop_loss_exit_bid": exit_px,
                    "paper_fee_model": fee_model,
                    "paper_fee_bps": fee_bps_used,
                    "patient_stop_loss_exit_fee_cents": exit_fee_cents,
                    "patient_stop_loss_gross_proceeds_cents": proceeds_cents,
                    "patient_stop_loss_net_proceeds_cents": int(net_proceeds_cents),
                },
            )
            await engine.store.update_trade_sim_early_close(
                tid,
                pnl_cents=int(pnl),
                settled_at=iso(now),
                result="patient_stop_loss",
                extra_json=json.dumps(extra),
            )
            closed_n += 1
            msg = (
                f"Patient stop-loss triggered for {ticker} at {net_pct:.1f}% (after fees) after {int(round(minutes_held))} min"
            )
            _trace_append(trace, f"patient_stop_loss {branch}: {msg}")
            _data_log(
                "trading",
                {
                    "event": "patient_stop_loss_triggered",
                    "branch": branch,
                    "trade_id": tid,
                    "ticker": ticker,
                    "side": side,
                    "minutes_held": round(minutes_held, 2),
                    "net_unrealized_pct_after_fees": round(net_pct, 4),
                    "trigger_pct": thr,
                    "min_hold_minutes": min_hold,
                    "exit_bid": exit_px,
                    "pnl_cents": int(pnl),
                    "contracts": contracts,
                    "gross_proceeds_cents": proceeds_cents,
                    "exit_fee_cents": exit_fee_cents,
                    "net_proceeds_cents": int(net_proceeds_cents),
                    "amount_cents_debit": cost,
                },
            )
        except Exception as e:
            _trace_append(trace, f"patient_stop_loss {branch}: row err {str(e)[:160]}")
            continue
    return closed_n


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
    if branch == BRANCH_LIVE and not live_paper_trading_enabled(full_cfg):
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
            data = await engine.client.get_public(_public_market_path(ticker))
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

        contracts = _parse_contracts_fp(t.get("contracts_fp"))
        if contracts <= 0:
            _engine_trace_note(engine, f"swing {branch}: {ticker[:28]}… skip (contracts_fp unresolved)")
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


async def maybe_timeout_close_open_sim_trades(engine: TradingEngine, full_cfg: dict[str, Any]) -> int:
    """
    Auto-close stale simulated open rows so one-open-per-series guards cannot stall trading indefinitely.

    Eligible when either (a) row age exceeds ``auto_close_open_sim_minutes``, or (b) contract ``close_time``
    is more than ``auto_close_grace_minutes_after_event_close`` in the past (Kalshi settlement lag).
    Uses a conservative bid-side close when market data is available; otherwise falls back to entry premium.
    Set ``auto_close_open_sim_minutes`` to <=0 to disable for a branch.
    """
    branch = engine.branch
    cfg = merge_branch_config(full_cfg, branch)
    try:
        timeout_min = float(cfg.get("auto_close_open_sim_minutes") or full_cfg.get("auto_close_open_sim_minutes") or env.default_auto_close_open_sim_minutes)
    except (TypeError, ValueError):
        timeout_min = 75.0
    if timeout_min <= 0:
        return 0
    try:
        grace_after_close = float(
            cfg.get("auto_close_grace_minutes_after_event_close")
            or full_cfg.get("auto_close_grace_minutes_after_event_close")
            or env.default_auto_close_grace_minutes_after_event_close
        )
    except (TypeError, ValueError):
        grace_after_close = 8.0
    open_rows = await engine.store.open_sim_trades_for_branch(branch)
    if not open_rows:
        return 0
    now = utc_now()
    fee_bps_now = effective_paper_fee_bps(full_cfg, branch)
    closed_n = 0
    for t in open_rows:
        try:
            tid_raw = t.get("id")
            if tid_raw is None:
                continue
            tid = int(tid_raw)
            created_raw = str(t.get("created_at") or "").strip()
            if not created_raw:
                continue
            created_dt = dateparser.isoparse(created_raw)
            if created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=dt.timezone.utc)
            age_min = (now - created_dt.astimezone(dt.timezone.utc)).total_seconds() / 60.0
            stale_by_age = age_min >= timeout_min
            ticker = str(t.get("ticker") or "").strip()
            m_cached: dict[str, Any] | None = None
            stale_by_event = False
            if not stale_by_age and grace_after_close > 0 and ticker:
                try:
                    data0 = await engine.client.get_public(_public_market_path(ticker))
                    m_cached = market_dict_from_public_response(data0)
                    close_time = str(m_cached.get("close_time") or "")
                    if close_time:
                        ml = minutes_left(close_time, now)
                        # minutes_left: negative = this many minutes past the contract's close; close after grace
                        if ml is not None and ml <= -grace_after_close:
                            stale_by_event = True
                except Exception:
                    m_cached = None
            if not stale_by_age and not stale_by_event:
                continue
            if not ticker:
                continue
            side = str(t.get("side") or "yes").strip().lower()
            if side not in ("yes", "no"):
                continue
            contracts = _parse_contracts_fp(t.get("contracts_fp"))
            if contracts <= 0:
                continue
            cost = int(t.get("amount_cents") or 0)
            try:
                raw_ex = json.loads(str(t.get("extra_json") or "{}"))
                extra = dict(raw_ex) if isinstance(raw_ex, dict) else {}
            except json.JSONDecodeError:
                extra = {}

            exit_px: float | None = None
            try:
                if m_cached is not None:
                    m = m_cached
                else:
                    data = await engine.client.get_public(_public_market_path(ticker))
                    m = market_dict_from_public_response(data)
                yb = dollars_to_float(m.get("yes_bid_dollars"))
                ya = dollars_to_float(m.get("yes_ask_dollars"))
                exit_px = exit_bid_for_side_close(m, side, yb, ya)
            except Exception:
                exit_px = None
            if exit_px is None or exit_px <= 0:
                ep = dollars_to_float(extra.get("entry_implied_yes"))
                if ep is not None:
                    exit_px = ep if side == "yes" else (1.0 - ep)
            if exit_px is None or exit_px <= 0:
                premium_cents = int(extra.get("entry_premium_cents") or 0)
                if premium_cents > 0:
                    exit_px = max(0.0, min(1.0, premium_cents / (100.0 * contracts)))
            if exit_px is None or exit_px <= 0:
                # Final fallback: close as full loss to unblock stale guard.
                exit_px = 0.0

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
                    "auto_timeout_close": True,
                    "auto_timeout_minutes": timeout_min,
                    "auto_timeout_stale_by_event_close": bool(stale_by_event),
                    "auto_timeout_grace_minutes_after_event_close": (
                        round(grace_after_close, 2) if stale_by_event else None
                    ),
                    "auto_timeout_age_minutes": round(age_min, 2),
                    "auto_timeout_exit_bid": exit_px,
                    "paper_fee_model": fee_model,
                    "paper_fee_bps": fee_bps_used,
                    "auto_timeout_exit_fee_cents": exit_fee_cents,
                    "auto_timeout_gross_proceeds_cents": proceeds_cents,
                    "auto_timeout_net_proceeds_cents": net_proceeds_cents,
                }
            )
            await engine.store.update_trade_sim_early_close(
                tid,
                pnl_cents=int(pnl),
                settled_at=iso(now),
                result="auto_timeout",
                extra_json=json.dumps(extra),
            )
            closed_n += 1
            if stale_by_event and not stale_by_age:
                _engine_trace_note(
                    engine,
                    f"timeout-close {branch} {ticker[:36]}… after_event+{grace_after_close:.0f}m side={side.upper()} "
                    f"exit≈{exit_px:.3f} pnl¢={pnl}",
                )
            else:
                _engine_trace_note(
                    engine,
                    f"timeout-close {branch} {ticker[:36]}… age={age_min:.1f}m side={side.upper()} "
                    f"exit≈{exit_px:.3f} pnl¢={pnl}",
                )
        except Exception as e:
            _engine_trace_note(engine, f"timeout-close {branch}: row err {str(e)[:120]}")
            continue
    return closed_n


async def settle_simulated_trades(engine: TradingEngine, *, full_cfg: dict[str, Any] | None = None) -> int:
    """Mark simulated open rows settled when Kalshi market is finalized. Returns count updated this pass."""
    open_trades = await engine.store.open_sim_trades_for_branch(engine.branch)
    if not open_trades:
        return 0
    now = utc_now()
    settled_n = 0
    if full_cfg is None:
        full_cfg = await engine.store.load_config()
    fee_bps_now = effective_paper_fee_bps(full_cfg, engine.branch)
    for t in open_trades:
        try:
            ticker = str(t.get("ticker") or "").strip()
            if not ticker:
                continue
            tid_raw = t.get("id")
            if tid_raw is None:
                continue
            tid = int(tid_raw)
            try:
                data = await engine.client.get_public(_public_market_path(ticker))
            except Exception as e:
                _engine_trace_note(
                    engine,
                    f"settle {engine.branch}: {ticker[:32]}… market fetch err {str(e)[:80]}",
                )
                continue
            m = market_dict_from_public_response(data)
            status = str(m.get("status") or "").strip().lower()
            # Kalshi lifecycle: ``determined`` → (optional ``disputed`` / ``amended``) → ``finalized``. REST uses
            # ``finalized`` as terminal; ``amended`` carries a re-set result like ``determined``.
            if status not in (
                "finalized",
                "closed",
                "determined",
                "amended",
                "settled",
                "settlement",
                "complete",
                "inactive",
            ):
                continue
            result = _normalize_settled_outcome_yes_no(m)
            if result not in ("yes", "no"):
                _engine_trace_note(
                    engine,
                    f"settle {engine.branch}: {ticker[:32]}… status={status!r} but outcome not yes/no (keys "
                    f"result={m.get('result')!r} yes_won={m.get('yes_won')!r})",
                )
                continue
            side = str(t.get("side") or "yes").strip().lower()
            if side not in ("yes", "no"):
                _engine_trace_note(engine, f"settle {engine.branch}: id={tid} skip (side={side!r})")
                continue
            contracts = _parse_contracts_fp(t.get("contracts_fp"))
            if contracts <= 0:
                _engine_trace_note(engine, f"settle {engine.branch}: {ticker[:32]}… id={tid} skip (contracts_fp)")
                continue
            try:
                amount = int(t.get("amount_cents") or 0)
            except (TypeError, ValueError):
                amount = 0
            payout_per = 1.0 if (side == "yes" and result == "yes") or (side == "no" and result == "no") else 0.0
            try:
                raw_ex = json.loads(str(t.get("extra_json") or "{}"))
                ex = dict(raw_ex) if isinstance(raw_ex, dict) else {}
            except json.JSONDecodeError:
                ex = {}
            if amount <= 0 and ex:
                # Losing / winning PnL must be against full cash paid (gross), not 0 on legacy / bad rows.
                try:
                    ep = int(ex.get("entry_premium_cents") or 0)
                    ef = int(ex.get("entry_fee_cents") or 0)
                    if ep + ef > 0:
                        amount = ep + ef
                except (TypeError, ValueError):
                    pass
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
            await engine.store.update_trade_settlement(tid, result, int(pnl), iso(now), extra_json=json.dumps(ex))
            settled_n += 1
        except Exception as e:
            tk = str(t.get("ticker") or "")[:32]
            _engine_trace_note(engine, f"settle {engine.branch}: {tk}… row err {str(e)[:120]}")
            continue
    return settled_n


async def snapshot_equity(engine: TradingEngine, *, full_cfg: dict[str, Any] | None = None) -> None:
    if full_cfg is None:
        full_cfg = await engine.store.load_config()
    branch = engine.branch

    if branch == BRANCH_LIVE:
        trade_mode_filter = "simulate" if live_paper_trading_enabled(full_cfg) else "live"
    else:
        trade_mode_filter = "simulate"

    roll = await engine.store.dashboard_branch_trade_rollups(branch, trade_mode_filter)
    settled_pnl = int(roll.get("total_pnl_cents") or 0)
    open_committed = int(roll.get("open_committed_cents") or 0)

    mtm_equity: int
    if _is_lab_branch(branch) or (branch == BRANCH_LIVE and live_paper_trading_enabled(full_cfg)):
        if _is_lab_branch(branch):
            paper = lab_paper_equity_start_cents(full_cfg, branch)
        else:
            paper = int(full_cfg.get("paper_balance_cents") or env.default_paper_balance_cents)
        equity = paper + settled_pnl - open_committed
        mode = "simulate"
        open_rows = await engine.store.open_sim_trades_for_branch(branch)
        mark_sum = await compute_open_sim_mark_value_sum_cents(engine, open_rows)
        mtm_equity = paper + settled_pnl - open_committed + mark_sum
    else:
        try:
            bal = await engine.client.get_private("/portfolio/balance")
            equity = int(bal.get("balance") or 0)
            pv_raw = bal.get("portfolio_value")
            if pv_raw is not None and str(pv_raw).strip() != "":
                try:
                    mtm_equity = int(float(str(pv_raw)))
                except (TypeError, ValueError):
                    mtm_equity = equity
            else:
                mtm_equity = equity
        except Exception:
            equity = 0
            mtm_equity = 0
        mode = "live"

    await engine.store.insert_equity_snapshot(
        iso(utc_now()), mode, equity, "auto", branch=branch, mtm_equity_cents=mtm_equity
    )


