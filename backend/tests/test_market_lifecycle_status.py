"""Kalshi market row ``status`` vs trading gates."""

from __future__ import annotations

import unittest

from app.engines.engine import market_row_lifecycle_allows_trading


class MarketLifecycleStatusTest(unittest.TestCase):
    def test_initialized_is_not_blocked(self) -> None:
        """Prod /markets lists often include ``initialized`` rows alongside ``active``."""
        self.assertTrue(
            market_row_lifecycle_allows_trading({"status": "initialized", "ticker": "X"})
        )

    def test_active_and_open_allowed(self) -> None:
        self.assertTrue(market_row_lifecycle_allows_trading({"status": "active"}))
        self.assertTrue(market_row_lifecycle_allows_trading({"status": "open"}))

    def test_terminal_blocked(self) -> None:
        for s in ("finalized", "closed", "determined", "inactive", "settled"):
            self.assertFalse(market_row_lifecycle_allows_trading({"status": s}))

    def test_empty_status_allowed(self) -> None:
        self.assertTrue(market_row_lifecycle_allows_trading({"ticker": "Z"}))


if __name__ == "__main__":
    unittest.main()
