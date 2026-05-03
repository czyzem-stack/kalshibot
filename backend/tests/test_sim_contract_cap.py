from __future__ import annotations

import unittest

from app.branch_config import BRANCH_LAB_A, BRANCH_LAB_C, BRANCH_LIVE
from app.engines.engine import effective_sim_max_contracts_per_order


class SimContractCapTest(unittest.TestCase):
    def test_live_uncapped(self) -> None:
        self.assertIsNone(
            effective_sim_max_contracts_per_order(BRANCH_LIVE, {}, {})
        )

    def test_lab_a_uncapped(self) -> None:
        self.assertIsNone(
            effective_sim_max_contracts_per_order(BRANCH_LAB_A, {}, {})
        )

    def test_lab_c_default_cap(self) -> None:
        self.assertEqual(
            effective_sim_max_contracts_per_order(BRANCH_LAB_C, {}, {}),
            45,
        )

    def test_lab_child_default_cap(self) -> None:
        self.assertEqual(
            effective_sim_max_contracts_per_order("lab_child_3", {}, {}),
            45,
        )

    def test_cfg_override(self) -> None:
        self.assertEqual(
            effective_sim_max_contracts_per_order(
                BRANCH_LAB_C, {"max_contracts_per_sim_order": 12}, {}
            ),
            12,
        )


if __name__ == "__main__":
    unittest.main()
