from __future__ import annotations

import unittest

from app.branch_config import BRANCH_LAB_A, effective_parent_lab_engine_running, merge_branch_config
from app.persistence import _normalize_loaded_config


class MergeBranchConfigParentLabsTest(unittest.TestCase):
    def test_missing_lab_block_merges_when_parent_defaults_on(self) -> None:
        """Aligns with dual-loop tick gating: missing lab_* must not make merge None while engine looks on."""
        full_cfg: dict = {
            "paper_balance_cents": 500_000,
        }
        self.assertTrue(effective_parent_lab_engine_running(None, BRANCH_LAB_A))
        m = merge_branch_config(full_cfg, BRANCH_LAB_A)
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.get("_branch"), BRANCH_LAB_A)
        self.assertTrue(m.get("_simulate_orders"))
        self.assertEqual(m.get("_trade_mode"), "simulate")

    def test_explicit_parent_engine_off_returns_none(self) -> None:
        full_cfg: dict = {"lab_a": {"engine_running": False}}
        lab_a = full_cfg["lab_a"]
        assert isinstance(lab_a, dict)
        self.assertFalse(effective_parent_lab_engine_running(lab_a, BRANCH_LAB_A))
        self.assertIsNone(merge_branch_config(full_cfg, BRANCH_LAB_A))

    def test_normalize_strips_legacy_lab_a_stub_engine_false(self) -> None:
        """Old normalize backfill left lab_a stuck off; migration removes that fingerprint."""
        cfg = {
            "lab_a": {
                "engine_running": False,
                "auto_optimize": False,
                "balance_fraction_per_window": 0.05,
                "window_minutes": 15,
                "paper_balance_cents": 500_000,
            }
        }
        out = _normalize_loaded_config(cfg)
        la = out.get("lab_a")
        assert isinstance(la, dict)
        self.assertNotIn("engine_running", la)
        self.assertTrue(effective_parent_lab_engine_running(la, BRANCH_LAB_A))

    def test_normalize_fills_lab_a_when_rules_empty(self) -> None:
        """Lab A was not covered by breeder-only rule guard; empty lab_a.rules meant zero matches forever."""
        cfg = {
            "rules": [
                {
                    "name": "Global YES",
                    "min_prob": 0.5,
                    "max_prob": 0.9,
                    "min_minutes_left": 0.0,
                    "max_minutes_left": 99.0,
                }
            ],
            "lab_a": {"rules": [], "window_minutes": 15},
        }
        out = _normalize_loaded_config(cfg)
        la = out.get("lab_a")
        assert isinstance(la, dict)
        rules = la.get("rules")
        assert isinstance(rules, list)
        self.assertGreater(len(rules), 0)

    def test_normalize_lab_a_default_rules_when_global_missing(self) -> None:
        cfg = {"lab_a": {"rules": []}}
        out = _normalize_loaded_config(cfg)
        la = out.get("lab_a")
        assert isinstance(la, dict)
        rules = la.get("rules")
        assert isinstance(rules, list)
        self.assertGreater(len(rules), 0)


if __name__ == "__main__":
    unittest.main()
