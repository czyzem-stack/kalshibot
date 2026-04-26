from __future__ import annotations

import unittest

from app.branch_config import BRANCH_LAB_A, BRANCH_LAB_B, BRANCH_LAB_C, BRANCH_LAB_D
from app.optimizer_claude import _build_payload


class OptimizerGuardrailsTest(unittest.TestCase):
    def test_payload_is_lab_only(self) -> None:
        payload = _build_payload(
            cfg={"lab_a": {"window_minutes": 15}, "lab_b": {"window_minutes": 20}, "rules": []},
            trades=[],
            signals=[],
            metrics={"lab_a": {}, "lab_b": {}},
            oc={},
        )
        self.assertEqual(payload.get("branches"), [BRANCH_LAB_A, BRANCH_LAB_B, BRANCH_LAB_C, BRANCH_LAB_D])
        self.assertTrue(payload.get("live_branch_forbidden"))
        self.assertIn("lab_a", payload.get("current_config_excerpt", {}))
        self.assertIn("lab_b", payload.get("current_config_excerpt", {}))
        self.assertIn("lab_c", payload.get("current_config_excerpt", {}))
        self.assertIn("lab_d", payload.get("current_config_excerpt", {}))
        self.assertIn("performance_metrics", payload)


if __name__ == "__main__":
    unittest.main()

