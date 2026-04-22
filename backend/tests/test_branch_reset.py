from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from app.persistence import Store


class BranchResetTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.store = Store(path=str(Path(self._tmpdir.name) / "t.sqlite3"))

    async def test_scoped_delete_keeps_other_branches(self) -> None:
        await self.store.insert_signal(
            {
                "created_at": "2026-01-01T00:00:00+00:00",
                "window_id": "w",
                "asset_id": "btc",
                "ticker": "T1",
                "side": "yes",
                "executed": False,
                "mode": "simulate",
                "branch": "live",
            }
        )
        await self.store.insert_signal(
            {
                "created_at": "2026-01-01T00:00:00+00:00",
                "window_id": "w",
                "asset_id": "btc",
                "ticker": "T2",
                "side": "yes",
                "executed": False,
                "mode": "simulate",
                "branch": "lab_a",
            }
        )
        await self.store.insert_signal(
            {
                "created_at": "2026-01-01T00:00:00+00:00",
                "window_id": "w",
                "asset_id": "btc",
                "ticker": "T3",
                "side": "yes",
                "executed": False,
                "mode": "simulate",
                "branch": "sim_lab",
            }
        )
        await self.store.insert_signal(
            {
                "created_at": "2026-01-01T00:00:00+00:00",
                "window_id": "w",
                "asset_id": "btc",
                "ticker": "T4",
                "side": "yes",
                "executed": False,
                "mode": "simulate",
                "branch": "lab_b",
            }
        )
        await self.store.reset_trading_data(backup=False, branch="lab_a")
        sigs = await self.store.recent_signals(limit=50)
        tickers = {str(s.get("ticker")) for s in sigs}
        self.assertIn("T1", tickers)
        self.assertIn("T4", tickers)
        self.assertNotIn("T2", tickers)
        self.assertNotIn("T3", tickers)

    async def test_query_table_lab_a_includes_sim_lab(self) -> None:
        await self.store.insert_trade(
            {
                "created_at": "2026-01-01T00:00:00+00:00",
                "mode": "simulate",
                "ticker": "KX-OLD",
                "side": "yes",
                "contracts_fp": "1",
                "amount_cents": 100,
                "simulated": 1,
                "order_id": None,
                "client_order_id": "c1",
                "status": "settled",
                "result": "yes",
                "pnl_cents": 0,
                "settled_at": "2026-01-01T01:00:00+00:00",
                "extra_json": "{}",
                "branch": "sim_lab",
            }
        )
        rows = await self.store.query_table("trades", branch="lab_a", limit=20, offset=0)
        tickers = {str(r.get("ticker")) for r in rows}
        self.assertIn("KX-OLD", tickers)

    async def test_bump_lab_paper_lifetime_basis_accumulates(self) -> None:
        cfg = await self.store.load_config()
        cfg["paper_balance_cents"] = 100_000
        cfg["lab_a"] = {**(cfg.get("lab_a") or {}), "paper_balance_cents": 100_000}
        await self.store.save_config(cfg)
        await self.store.bump_lab_paper_lifetime_basis("lab_a")
        cfg1 = await self.store.load_config()
        self.assertEqual(int(cfg1["lab_a"]["paper_lifetime_basis_cents"]), 200_000)
        await self.store.bump_lab_paper_lifetime_basis("lab_a")
        cfg2 = await self.store.load_config()
        self.assertEqual(int(cfg2["lab_a"]["paper_lifetime_basis_cents"]), 300_000)


if __name__ == "__main__":
    unittest.main()
