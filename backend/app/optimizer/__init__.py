"""Optimizer helpers: schemas, fitness scoring, replay detail, promotion gates, lab auto-tune."""

from .auto_optimize import maybe_auto_optimize
from .fitness import (
    composite_fitness_score,
    is_statistically_better,
    max_drawdown_cents_from_cumulative,
    per_trade_pnls_dollars,
    sharpe_approx,
    volatility_dollars_from_equity_curve,
)
from .schemas import ClaudeOptimizerResponse, parse_claude_optimizer_json

__all__ = [
    "ClaudeOptimizerResponse",
    "maybe_auto_optimize",
    "composite_fitness_score",
    "is_statistically_better",
    "max_drawdown_cents_from_cumulative",
    "parse_claude_optimizer_json",
    "per_trade_pnls_dollars",
    "sharpe_approx",
    "volatility_dollars_from_equity_curve",
]
