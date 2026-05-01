"""Regression: lab paper auto-reset bust equity must match dashboard baseline."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.engines.engine import _maybe_auto_reset_lab_paper_on_tick_failure


class AutoResetLabPaperTest(unittest.IsolatedAsyncioTestCase):
    async def test_bust_equity_uses_lifetime_basis_like_dashboard(self) -> None:
        """Avoid spurious wipes when paper_balance_cents is small vs cumulative lifetime_basis."""
        engine = MagicMock()
        engine.branch = "lab_a"
        engine.state = MagicMock()
        engine.state.last_error = None
        engine._paper_auto_reset_streak_handled = False
        engine.store = MagicMock()
        engine.store.dashboard_branch_trade_rollups = AsyncMock(
            return_value={"total_pnl_cents": -600_000, "open_committed_cents": 0}
        )
        engine.store.reset_trading_data = AsyncMock()
        engine.store.bump_lab_paper_lifetime_basis = AsyncMock()

        full_cfg = {
            "paper_balance_cents": 500_000,
            "lab_a": {
                "auto_reset_paper_on_tick_failure": True,
                "paper_balance_cents": 500_000,
                "paper_lifetime_basis_cents": 2_000_000,
            },
        }

        with patch("app.engines.engine.snapshot_equity", new_callable=AsyncMock):
            await _maybe_auto_reset_lab_paper_on_tick_failure(engine, full_cfg)

        engine.store.reset_trading_data.assert_not_called()
        engine.store.bump_lab_paper_lifetime_basis.assert_not_called()

    async def test_bust_still_wipes_when_book_negative_under_same_baseline(
        self,
    ) -> None:
        engine = MagicMock()
        engine.branch = "lab_a"
        engine.state = MagicMock()
        engine.state.last_error = None
        engine._paper_auto_reset_streak_handled = False
        engine.store = MagicMock()
        engine.store.dashboard_branch_trade_rollups = AsyncMock(
            return_value={"total_pnl_cents": -2_500_000, "open_committed_cents": 0}
        )
        engine.store.reset_trading_data = AsyncMock()
        engine.store.bump_lab_paper_lifetime_basis = AsyncMock()

        full_cfg = {
            "paper_balance_cents": 500_000,
            "lab_a": {
                "auto_reset_paper_on_tick_failure": True,
                "paper_balance_cents": 500_000,
                "paper_lifetime_basis_cents": 2_000_000,
            },
        }

        with patch("app.engines.engine.snapshot_equity", new_callable=AsyncMock):
            await _maybe_auto_reset_lab_paper_on_tick_failure(engine, full_cfg)

        engine.store.reset_trading_data.assert_called_once()
        engine.store.bump_lab_paper_lifetime_basis.assert_called_once()


if __name__ == "__main__":
    unittest.main()
