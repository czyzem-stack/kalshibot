from __future__ import annotations

import unittest

from app.engines.engine import implied_yes_probability


class ImpliedYesProbabilityTest(unittest.TestCase):
    def test_zero_zero_placeholder_is_unknown(self) -> None:
        self.assertIsNone(implied_yes_probability(0.0, 0.0))

    def test_positive_mid_still_works(self) -> None:
        self.assertAlmostEqual(implied_yes_probability(0.4, 0.6), 0.5)

    def test_one_sided_zero_is_unknown(self) -> None:
        self.assertIsNone(implied_yes_probability(None, 0.0))
        self.assertIsNone(implied_yes_probability(0.0, None))

    def test_one_sided_positive(self) -> None:
        self.assertAlmostEqual(implied_yes_probability(None, 0.55), 0.55)
        self.assertAlmostEqual(implied_yes_probability(0.45, None), 0.45)


if __name__ == "__main__":
    unittest.main()
