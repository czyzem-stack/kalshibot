"""Lab A → Live promotion gates: legacy PnL, composite score, statistical vs B/C/D."""

from __future__ import annotations

import datetime as dt
import statistics
from typing import TYPE_CHECKING, Any

from ..branch_config import BRANCH_LAB_A, BRANCH_LAB_B, BRANCH_LAB_C, BRANCH_LAB_D
from .fitness import composite_fitness_score, is_statistically_better

if TYPE_CHECKING:
    from ..persistence import Store


def _opt_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    o = cfg.get("optimizer")
    return dict(o) if isinstance(o, dict) else {}


def _iso(v: dt.datetime) -> str:
    return v.astimezone(dt.timezone.utc).isoformat()


def _ensure_lab_rules(cfg: dict[str, Any], branch: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from ..branch_config import _lab_key_for_branch

    lk = _lab_key_for_branch(branch) or "lab_a"
    lab = cfg.get(lk)
    if not isinstance(lab, dict):
        lab = {}
    rules = lab.get("rules")
    if not isinstance(rules, list) or not rules:
        base = cfg.get("rules")
        rules = [dict(r) for r in base] if isinstance(base, list) else []
    return dict(lab), [dict(r) for r in rules if isinstance(r, dict)]


async def lab_a_promotion_report(
    store: Store,
    cfg: dict[str, Any],
    *,
    lookback_hours: int = 168,
    max_rows: int = 3000,
    replay_tail: int = 120,
) -> dict[str, Any]:
    """
    Build promotion diagnostics: rollups, composite scores, statistical gate components.
    """
    # Local import avoids loading ``TradingEngine`` / Kalshi stack when only importing this module.
    from ..optimizer_claude import _signals_sorted_desc, replay_under_rules_detail

    oc = _opt_cfg(cfg)
    include_fees = bool(oc.get("include_fees_in_score", True))
    end = dt.datetime.now(tz=dt.timezone.utc)
    start = end - dt.timedelta(hours=max(24, lookback_hours))
    start_iso, end_iso = _iso(start), _iso(end)

    roll_a = await store.dashboard_branch_trade_rollups(BRANCH_LAB_A, "simulate")
    roll_b = await store.dashboard_branch_trade_rollups(BRANCH_LAB_B, "simulate")
    roll_c = await store.dashboard_branch_trade_rollups(BRANCH_LAB_C, "simulate")
    roll_d = await store.dashboard_branch_trade_rollups(BRANCH_LAB_D, "simulate")
    pa = int(roll_a.get("total_pnl_cents") or 0)
    pb = int(roll_b.get("total_pnl_cents") or 0)
    pc = int(roll_c.get("total_pnl_cents") or 0)
    pd = int(roll_d.get("total_pnl_cents") or 0)
    legacy_ok = bool(pa > pb and pa > pc and pa > pd)

    tr_a = await store.query_table(
        "trades", branch=BRANCH_LAB_A, mode="simulate", start_at=start_iso, end_at=end_iso, limit=max_rows
    )
    tr_b = await store.query_table(
        "trades", branch=BRANCH_LAB_B, mode="simulate", start_at=start_iso, end_at=end_iso, limit=max_rows
    )
    tr_c = await store.query_table(
        "trades", branch=BRANCH_LAB_C, mode="simulate", start_at=start_iso, end_at=end_iso, limit=max_rows
    )
    tr_d = await store.query_table(
        "trades", branch=BRANCH_LAB_D, mode="simulate", start_at=start_iso, end_at=end_iso, limit=max_rows
    )
    sg_a = await store.query_table(
        "signals", branch=BRANCH_LAB_A, mode="simulate", start_at=start_iso, end_at=end_iso, limit=max_rows
    )
    sg_b = await store.query_table(
        "signals", branch=BRANCH_LAB_B, mode="simulate", start_at=start_iso, end_at=end_iso, limit=max_rows
    )
    sg_c = await store.query_table(
        "signals", branch=BRANCH_LAB_C, mode="simulate", start_at=start_iso, end_at=end_iso, limit=max_rows
    )
    sg_d = await store.query_table(
        "signals", branch=BRANCH_LAB_D, mode="simulate", start_at=start_iso, end_at=end_iso, limit=max_rows
    )

    def _settled(tr: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            t
            for t in tr
            if str(t.get("status") or "").lower() == "settled" and t.get("pnl_cents") is not None
        ]

    st_a = _settled(tr_a)
    st_b = _settled(tr_b)
    st_c = _settled(tr_c)
    st_d = _settled(tr_d)
    _, rules_a = _ensure_lab_rules(cfg, BRANCH_LAB_A)
    _, rules_b = _ensure_lab_rules(cfg, BRANCH_LAB_B)
    _, rules_c = _ensure_lab_rules(cfg, BRANCH_LAB_C)
    _, rules_d = _ensure_lab_rules(cfg, BRANCH_LAB_D)

    sa = _signals_sorted_desc(sg_a)
    sb = _signals_sorted_desc(sg_b)
    sc = _signals_sorted_desc(sg_c)
    sd = _signals_sorted_desc(sg_d)

    def _replay(branch: str, settled: list[dict[str, Any]], rules: list[dict[str, Any]], sig: list[dict[str, Any]]) -> dict[str, Any]:
        tail = settled[:replay_tail] if len(settled) > replay_tail else settled
        return replay_under_rules_detail(tail, rules, sig, include_fees_in_score=include_fees, max_considered=replay_tail)

    rep_a = _replay(BRANCH_LAB_A, st_a, rules_a, sa)
    rep_b = _replay(BRANCH_LAB_B, st_b, rules_b, sb)
    rep_c = _replay(BRANCH_LAB_C, st_c, rules_c, sc)
    rep_d = _replay(BRANCH_LAB_D, st_d, rules_d, sd)

    fit_a = composite_fitness_score(
        total_pnl_cents=int(rep_a["total_pnl_cents"]),
        cumulative_equity_cents=rep_a["cumulative_equity_cents"],
        per_trade_pnl_cents=rep_a["per_trade_pnl_cents_chrono"],
    )
    fit_b = composite_fitness_score(
        total_pnl_cents=int(rep_b["total_pnl_cents"]),
        cumulative_equity_cents=rep_b["cumulative_equity_cents"],
        per_trade_pnl_cents=rep_b["per_trade_pnl_cents_chrono"],
    )
    fit_c = composite_fitness_score(
        total_pnl_cents=int(rep_c["total_pnl_cents"]),
        cumulative_equity_cents=rep_c["cumulative_equity_cents"],
        per_trade_pnl_cents=rep_c["per_trade_pnl_cents_chrono"],
    )
    fit_d = composite_fitness_score(
        total_pnl_cents=int(rep_d["total_pnl_cents"]),
        cumulative_equity_cents=rep_d["cumulative_equity_cents"],
        per_trade_pnl_cents=rep_d["per_trade_pnl_cents_chrono"],
    )
    score_a = float(fit_a["score_dollars"])
    scores_bcd = [float(fit_b["score_dollars"]), float(fit_c["score_dollars"]), float(fit_d["score_dollars"])]
    med_bcd = float(statistics.median(scores_bcd)) if scores_bcd else 0.0
    score_gate = bool(score_a > med_bcd)

    a_dollars = [x / 100.0 for x in rep_a["per_trade_pnl_cents_chrono"]]
    ctrl_pool: list[float] = (
        [x / 100.0 for x in rep_b["per_trade_pnl_cents_chrono"]]
        + [x / 100.0 for x in rep_c["per_trade_pnl_cents_chrono"]]
        + [x / 100.0 for x in rep_d["per_trade_pnl_cents_chrono"]]
    )
    stat_ok, stat_detail = is_statistically_better(
        a_dollars,
        ctrl_pool,
        lab_a_score=score_a,
        control_scores=scores_bcd,
    )

    fitness_ok = bool(score_gate and stat_ok)
    promotion_gates_ok = bool(legacy_ok and fitness_ok)
    return {
        "window_start": start_iso,
        "window_end": end_iso,
        "legacy_pnl_cents": {"lab_a": pa, "lab_b": pb, "lab_c": pc, "lab_d": pd},
        "legacy_pnl_ok": legacy_ok,
        "composite_scores": {"lab_a": fit_a, "lab_b": fit_b, "lab_c": fit_c, "lab_d": fit_d},
        "score_median_controls": med_bcd,
        "score_gate": score_gate,
        "statistical_gate": stat_detail,
        "statistical_ok": stat_ok,
        "fitness_ok": fitness_ok,
        "promotion_gates_ok": promotion_gates_ok,
        "replay_tail": replay_tail,
    }
