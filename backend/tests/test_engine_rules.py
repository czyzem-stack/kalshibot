from __future__ import annotations

import unittest

from app.engine import pick_trade_rule, rule_axis_probability, rule_matches


class RuleMatchesTest(unittest.TestCase):
    def test_yes_band_center(self) -> None:
        r = {
            "name": "t",
            "min_prob": 0.5,
            "max_prob": 0.6,
            "min_minutes_left": 5.0,
            "max_minutes_left": 20.0,
        }
        self.assertTrue(rule_matches(0.55, 10.0, r))
        self.assertFalse(rule_matches(0.45, 10.0, r))
        self.assertFalse(rule_matches(0.55, 4.0, r))

    def test_no_side_uses_implied_no_axis(self) -> None:
        r = {
            "name": "no",
            "side": "no",
            "min_prob": 0.35,
            "max_prob": 0.45,
            "min_minutes_left": 0.0,
            "max_minutes_left": 30.0,
        }
        # implied YES 0.70 => implied NO 0.30 — inside [0.35, 0.45]? 0.30 < 0.35 => no match
        self.assertFalse(rule_matches(0.70, 10.0, r))
        # implied YES 0.62 => NO 0.38 — in band
        self.assertTrue(rule_matches(0.62, 10.0, r))

    def test_rule_axis_probability(self) -> None:
        r_no = {
            "side": "no",
            "min_prob": 0.2,
            "max_prob": 0.8,
            "min_minutes_left": 0.0,
            "max_minutes_left": 99.0,
        }
        self.assertAlmostEqual(rule_axis_probability(0.75, r_no), 0.25)
        r_yes = {
            "min_prob": 0.0,
            "max_prob": 1.0,
            "min_minutes_left": 0.0,
            "max_minutes_left": 99.0,
        }
        self.assertAlmostEqual(rule_axis_probability(0.75, r_yes), 0.75)


class PickTradeRuleTest(unittest.TestCase):
    def test_low_yes_cutoff_prefers_no_rules(self) -> None:
        cfg = {"no_bet_when_yes_below_pct": 40}
        yes_r = {
            "name": "y",
            "min_prob": 0.5,
            "max_prob": 0.9,
            "min_minutes_left": 0.0,
            "max_minutes_left": 30.0,
        }
        # When implied YES is 0.30, axis for NO rules is ~0.70 — band must cover that.
        no_r = {
            "name": "n",
            "side": "no",
            "min_prob": 0.65,
            "max_prob": 0.85,
            "min_minutes_left": 0.0,
            "max_minutes_left": 30.0,
        }
        rules = [yes_r, no_r]
        picked = pick_trade_rule(
            0.30,
            10.0,
            rules,
            has_yes_rules=True,
            has_no_book=True,
            cfg=cfg,
        )
        self.assertIsNotNone(picked)
        self.assertEqual(picked.get("side"), "no")

    def test_no_book_blocks_no_rule(self) -> None:
        cfg = {}
        no_r = {
            "name": "n",
            "side": "no",
            "min_prob": 0.2,
            "max_prob": 0.9,
            "min_minutes_left": 0.0,
            "max_minutes_left": 30.0,
        }
        yes_r = {
            "name": "y",
            "min_prob": 0.4,
            "max_prob": 0.6,
            "min_minutes_left": 0.0,
            "max_minutes_left": 30.0,
        }
        rules = [yes_r, no_r]
        self.assertIsNone(
            pick_trade_rule(
                0.55, 10.0, rules, has_yes_rules=False, has_no_book=False, cfg=cfg
            ),
        )


if __name__ == "__main__":
    unittest.main()
