"""Breeding must not persist ``engine_running: false`` onto parent labs (``lab_a``–``lab_e``)."""

from __future__ import annotations

import unittest

from app.lab_breeding import _expand_parent_lab_after_replacement


class TestExpandParentLabAfterReplacement(unittest.TestCase):
    def test_parent_lab_forces_engine_on(self) -> None:
        out = _expand_parent_lab_after_replacement(
            "lab_c",
            {"engine_running": False, "window_minutes": 7},
        )
        self.assertTrue(out["engine_running"])
        self.assertEqual(out["window_minutes"], 7)

    def test_child_slot_key_does_not_force_engine(self) -> None:
        out = _expand_parent_lab_after_replacement(
            "lab_child_1",
            {"engine_running": False, "window_minutes": 12},
        )
        self.assertFalse(out["engine_running"])
        self.assertEqual(out["window_minutes"], 12)


if __name__ == "__main__":
    unittest.main()
