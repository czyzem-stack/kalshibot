"""Unit tests for optimizer fitness helpers (no TradingEngine import)."""

from __future__ import annotations

import unittest

from app.optimizer.fitness import composite_fitness_score, is_statistically_better


class OptimizerFitnessTest(unittest.TestCase):
    def test_composite_prefers_lower_drawdown(self) -> None:
        a = composite_fitness_score(
            total_pnl_cents=1000,
            cumulative_equity_cents=[0, 500, 200, 1000],
            per_trade_pnl_cents=[500, -300, 500, 300],
        )
        b = composite_fitness_score(
            total_pnl_cents=1000,
            cumulative_equity_cents=[0, 200, 400, 1000],
            per_trade_pnl_cents=[200, 200, 200, 400],
        )
        self.assertGreater(float(b["score_dollars"]), float(a["score_dollars"]))

    def test_statistical_better_margin(self) -> None:
        ok, detail = is_statistically_better(
            [1.0, 1.0, 1.0],
            [0.0, 0.0, 0.0],
            lab_a_score=10.0,
            control_scores=[1.0, 1.0, 1.0],
        )
        self.assertTrue(ok)
        self.assertTrue(detail["score_ratio_gate"])


if __name__ == "__main__":
    unittest.main()
