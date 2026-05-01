"""Composite fitness score, drawdown/vol/sharpe helpers, and control-lab statistical gates."""

from __future__ import annotations

import math
from statistics import mean, pstdev
from typing import Any, Sequence


def max_drawdown_cents_from_cumulative(cumulative_equity_cents: Sequence[int]) -> int:
    """
    Max peak-to-trough drop in cents along the cumulative equity path (non-negative int).
    Path should include initial 0 if representing prefix sums.
    """
    if not cumulative_equity_cents:
        return 0
    peak = int(cumulative_equity_cents[0])
    worst = 0
    for x in cumulative_equity_cents:
        xi = int(x)
        if xi > peak:
            peak = xi
        dd = peak - xi
        if dd > worst:
            worst = dd
    return max(0, worst)


def volatility_dollars_from_equity_curve(
    cumulative_equity_cents: Sequence[int],
) -> float:
    """Std dev of step-to-step equity changes in dollars (empty / single -> 0)."""
    if len(cumulative_equity_cents) < 2:
        return 0.0
    diffs: list[float] = []
    prev = int(cumulative_equity_cents[0])
    for i in range(1, len(cumulative_equity_cents)):
        cur = int(cumulative_equity_cents[i])
        diffs.append((cur - prev) / 100.0)
        prev = cur
    if len(diffs) < 2:
        return 0.0
    try:
        return float(pstdev(diffs))
    except Exception:
        return 0.0


def sharpe_approx(
    per_trade_pnls_dollars: Sequence[float], *, eps: float = 1e-9
) -> float:
    """
    Very rough per-trade Sharpe: mean / std of dollar PnLs (not annualized).
    """
    xs = [float(x) for x in per_trade_pnls_dollars]
    if len(xs) < 2:
        return 0.0
    m = mean(xs)
    s = pstdev(xs)
    if s <= eps:
        return 0.0
    return m / s


def per_trade_pnls_dollars(per_trade_pnl_cents: Sequence[int]) -> list[float]:
    return [int(x) / 100.0 for x in per_trade_pnl_cents]


def composite_fitness_score(
    *,
    total_pnl_cents: int,
    cumulative_equity_cents: Sequence[int],
    per_trade_pnl_cents: Sequence[int],
    w_dd: float = 2.0,
    w_vol: float = 1.5,
    w_sharpe: float = 3.0,
) -> dict[str, Any]:
    """
    score_dollars = pnl - w_dd*max_dd - w_vol*vol + w_sharpe*sharpe_approx
    (all dollar-ish except Sharpe which is dimensionless — kept as user-specified blend).
    """
    pnl_d = total_pnl_cents / 100.0
    mdd_c = max_drawdown_cents_from_cumulative(cumulative_equity_cents)
    mdd_d = mdd_c / 100.0
    vol_d = volatility_dollars_from_equity_curve(cumulative_equity_cents)
    sh = sharpe_approx(per_trade_pnls_dollars(per_trade_pnl_cents))
    score = pnl_d - (w_dd * mdd_d) - (w_vol * vol_d) + (w_sharpe * sh)
    return {
        "score_dollars": float(score),
        "pnl_dollars": float(pnl_d),
        "max_drawdown_dollars": float(mdd_d),
        "equity_volatility_dollars": float(vol_d),
        "sharpe_approx": float(sh),
        "weights": {"drawdown": w_dd, "volatility": w_vol, "sharpe": w_sharpe},
    }


def _sample_var(xs: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return sum((x - m) ** 2 for x in xs) / (n - 1)


def welch_t_statistic(a: list[float], b: list[float]) -> tuple[float, float]:
    """Returns (t, df_welch)."""
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return 0.0, 1.0
    ma, mb = mean(a), mean(b)
    va, vb = _sample_var(a), _sample_var(b)
    sea = va / na
    seb = vb / nb
    denom = math.sqrt(sea + seb)
    if denom <= 0:
        return (1e9 if ma > mb else -1e9), 1.0
    t = (ma - mb) / denom
    num = (sea + seb) ** 2
    den_df = (sea**2) / max(1, na - 1) + (seb**2) / max(1, nb - 1)
    df = num / den_df if den_df > 0 else float(max(na, nb))
    return float(t), float(max(1.0, df))


def _normal_sf(x: float) -> float:
    """Upper tail P(Z > x) for standard normal Z (erf-based)."""
    return 0.5 * math.erfc(x / math.sqrt(2.0))


def welch_one_sided_pvalue_approx(a: list[float], b: list[float]) -> float:
    """Approximate P(T > t) one-sided (A better than B) using normal tail on Welch t."""
    t, df = welch_t_statistic(a, b)
    if t <= 0:
        return 1.0
    # Inflate variance slightly for small df vs normal
    adj = 1.0 + max(0.0, 15.0 - df) * 0.02
    z = t / adj
    return float(max(0.0, min(1.0, _normal_sf(z))))


def is_statistically_better(
    lab_a_per_trade_pnls_dollars: list[float],
    control_per_trade_pnls_dollars: list[float],
    *,
    lab_a_score: float,
    control_scores: Sequence[float],
    alpha: float = 0.10,
    score_margin_pct: float = 0.15,
) -> tuple[bool, dict[str, Any]]:
    """
    True if either:
      (1) Welch one-sided p-value < alpha and mean(A) > mean(control), or
      (2) lab_a_score >= (1 + score_margin_pct) * median(control_scores)

    ``control_scores`` should be one composite score per control lab (B,C,D) with enough data; filter NaNs.
    """
    ctrl_scores = [
        float(x) for x in control_scores if isinstance(x, (int, float)) and x == x
    ]
    med_ctrl = float(sorted(ctrl_scores)[len(ctrl_scores) // 2]) if ctrl_scores else 0.0
    score_ok = (
        bool(lab_a_score >= (1.0 + score_margin_pct) * med_ctrl)
        if ctrl_scores
        else False
    )

    t_p = welch_one_sided_pvalue_approx(
        lab_a_per_trade_pnls_dollars, control_per_trade_pnls_dollars
    )
    mean_a = mean(lab_a_per_trade_pnls_dollars) if lab_a_per_trade_pnls_dollars else 0.0
    mean_b = (
        mean(control_per_trade_pnls_dollars) if control_per_trade_pnls_dollars else 0.0
    )
    t_ok = bool(
        t_p < alpha
        and mean_a > mean_b
        and len(lab_a_per_trade_pnls_dollars) >= 3
        and len(control_per_trade_pnls_dollars) >= 3
    )

    ok = score_ok or t_ok
    detail: dict[str, Any] = {
        "welch_one_sided_p_approx": t_p,
        "mean_a": mean_a,
        "mean_control": mean_b,
        "median_control_scores": med_ctrl,
        "lab_a_score": lab_a_score,
        "score_margin_pct": score_margin_pct,
        "score_ratio_gate": score_ok,
        "t_test_gate": t_ok,
        "alpha": alpha,
    }
    return ok, detail


__all__ = [
    "composite_fitness_score",
    "is_statistically_better",
    "max_drawdown_cents_from_cumulative",
    "per_trade_pnls_dollars",
    "sharpe_approx",
    "volatility_dollars_from_equity_curve",
    "welch_one_sided_pvalue_approx",
]
