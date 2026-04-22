"""Unit tests for Kalshi quadratic fee helpers."""

from __future__ import annotations

import os
import sys
import unittest
from decimal import Decimal

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app.kalshi_fees import kalshi_buy_debit_cents, kalshi_quadratic_trade_fee_usd, kalshi_sell_credit_cents


class KalshiFeesTest(unittest.TestCase):
    def test_taker_fee_50c_symmetric(self) -> None:
        # 0.07 * 1 * 0.5 * 0.5 = 0.0175 USD before centicent ceil (already on grid)
        f = kalshi_quadratic_trade_fee_usd(1.0, 0.5, maker=False, fee_multiplier=1.0)
        self.assertEqual(f, Decimal("0.0175"))

    def test_maker_is_quarter_of_taker_raw(self) -> None:
        ft = kalshi_quadratic_trade_fee_usd(1.0, 0.4, maker=False, fee_multiplier=1.0)
        fm = kalshi_quadratic_trade_fee_usd(1.0, 0.4, maker=True, fee_multiplier=1.0)
        self.assertEqual(fm * Decimal(4), ft)

    def test_buy_debit_cent_alignment(self) -> None:
        debit, _br = kalshi_buy_debit_cents(1.0, 0.055, maker=False, fee_multiplier=1.0)
        self.assertGreater(debit, 0)
        self.assertEqual(debit, int(debit))

    def test_sell_credit_non_negative(self) -> None:
        credit, _br = kalshi_sell_credit_cents(2.0, 0.42, maker=False, fee_multiplier=1.0)
        self.assertGreaterEqual(credit, 0)


if __name__ == "__main__":
    unittest.main()
