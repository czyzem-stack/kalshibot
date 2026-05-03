import unittest

from app.lab_communication import snapshots_have_usable_feed


class ThinkTankFeedGateTest(unittest.TestCase):
    def test_empty_and_errors_no_feed(self) -> None:
        self.assertFalse(snapshots_have_usable_feed({}))
        self.assertFalse(
            snapshots_have_usable_feed(
                {"btc": {"ok": False, "reason": "no_contracts"}},
            ),
        )

    def test_ok_snapshot_unlocks(self) -> None:
        self.assertTrue(
            snapshots_have_usable_feed(
                {
                    "btc": {"ok": False, "reason": "fetch_error"},
                    "eth": {"ok": True, "implied_prob": 0.52},
                },
            ),
        )


if __name__ == "__main__":
    unittest.main()
