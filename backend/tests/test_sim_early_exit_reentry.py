from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.persistence import SIM_EARLY_EXIT_RESULT_VALUES, Store


class SimEarlyExitReentryTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.store = Store(path=str(Path(self._tmpdir.name) / "t.sqlite3"))
        await self.store.load_config()

    async def test_has_sim_early_exit_for_ticker_after_swing_exit(self) -> None:
        branch = "lab_a"
        ticker = "KXTEST-26JAN01-T1"
        rid = await self.store.insert_trade(
            {
                "created_at": "2026-01-01T12:00:00+00:00",
                "mode": "simulate",
                "ticker": ticker,
                "side": "yes",
                "contracts_fp": "1.00",
                "limit_yes_dollars": "0.5000",
                "amount_cents": 50,
                "simulated": True,
                "order_id": None,
                "client_order_id": "cid-1",
                "status": "open",
                "result": None,
                "pnl_cents": None,
                "settled_at": None,
                "extra_json": json.dumps({"entry_implied_yes": 0.5}),
                "branch": branch,
            },
        )
        self.assertFalse(
            await self.store.has_sim_early_exit_for_ticker(branch, ticker),
        )
        await self.store.update_trade_sim_early_close(
            rid,
            pnl_cents=-5,
            settled_at="2026-01-01T13:00:00+00:00",
            result="swing_exit",
            extra_json=json.dumps({"swing_exit": True}),
        )
        self.assertTrue(
            await self.store.has_sim_early_exit_for_ticker(branch, ticker),
        )

    async def test_kalshi_settlement_row_does_not_block_reentry(self) -> None:
        branch = "lab_b"
        ticker = "KXTEST-26JAN01-T2"
        rid = await self.store.insert_trade(
            {
                "created_at": "2026-01-01T12:00:00+00:00",
                "mode": "simulate",
                "ticker": ticker,
                "side": "yes",
                "contracts_fp": "1.00",
                "limit_yes_dollars": "0.5000",
                "amount_cents": 50,
                "simulated": True,
                "order_id": None,
                "client_order_id": "cid-2",
                "status": "open",
                "result": None,
                "pnl_cents": None,
                "settled_at": None,
                "extra_json": "{}",
                "branch": branch,
            },
        )
        await self.store.update_trade_settlement(
            rid,
            "yes",
            50,
            "2026-01-02T00:00:00+00:00",
        )
        self.assertFalse(
            await self.store.has_sim_early_exit_for_ticker(branch, ticker),
        )

    async def test_insert_sim_trade_blocked_after_early_close(self) -> None:
        branch = "lab_c"
        ticker = "KXTEST-26JAN01-T3"
        rid = await self.store.insert_trade(
            {
                "created_at": "2026-01-01T12:00:00+00:00",
                "mode": "simulate",
                "ticker": ticker,
                "side": "yes",
                "contracts_fp": "1.00",
                "limit_yes_dollars": "0.5000",
                "amount_cents": 50,
                "simulated": True,
                "order_id": None,
                "client_order_id": "cid-3",
                "status": "open",
                "result": None,
                "pnl_cents": None,
                "settled_at": None,
                "extra_json": "{}",
                "branch": branch,
            },
        )
        await self.store.update_trade_sim_early_close(
            rid,
            pnl_cents=0,
            settled_at="2026-01-01T14:00:00+00:00",
            result="auto_timeout",
            extra_json=json.dumps({"auto_timeout_close": True}),
        )
        tid = await self.store.insert_sim_trade_single_open_per_ticker(
            {
                "created_at": "2026-01-01T15:00:00+00:00",
                "mode": "simulate",
                "ticker": ticker,
                "side": "yes",
                "contracts_fp": "1.00",
                "limit_yes_dollars": "0.5500",
                "amount_cents": 55,
                "simulated": True,
                "order_id": None,
                "client_order_id": "cid-4",
                "status": "open",
                "result": None,
                "pnl_cents": None,
                "settled_at": None,
                "extra_json": "{}",
                "branch": branch,
            },
            branch=branch,
            trade_mode="simulate",
            market_ticker=ticker,
            series_exclusive_prefix=None,
        )
        self.assertIsNone(tid)

    def test_early_exit_constants_cover_update_trade_paths(self) -> None:
        self.assertEqual(
            set(SIM_EARLY_EXIT_RESULT_VALUES),
            {"patient_stop_loss", "swing_exit", "auto_timeout"},
        )


if __name__ == "__main__":
    unittest.main()
