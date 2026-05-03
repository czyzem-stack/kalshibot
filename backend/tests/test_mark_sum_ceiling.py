"""MTM mark sum cannot exceed sum(contracts × $1) for open binary sim rows."""

from __future__ import annotations

import unittest

from app.engines.engine import (
    clamp_open_sim_mark_sum_to_position_ceiling,
    max_fair_mark_value_cents_for_open_rows,
)


class MarkSumCeilingTest(unittest.TestCase):
    def test_ceiling_scales_with_contracts_fp(self) -> None:
        rows = [{"contracts_fp": "2.5"}, {"contracts_fp": 1}]
        self.assertEqual(max_fair_mark_value_cents_for_open_rows(rows), 300 + 100)

    def test_clamp_when_mark_exceeds_theoretical_max(self) -> None:
        rows = [{"contracts_fp": "3"}]
        self.assertEqual(
            clamp_open_sim_mark_sum_to_position_ceiling(
                9_999_999, rows, branch="lab_e", ctx="test"
            ),
            300,
        )

    def test_empty_rows_no_clamp(self) -> None:
        self.assertEqual(
            clamp_open_sim_mark_sum_to_position_ceiling(
                123, [], branch="lab_e", ctx="test"
            ),
            123,
        )


if __name__ == "__main__":
    unittest.main()
