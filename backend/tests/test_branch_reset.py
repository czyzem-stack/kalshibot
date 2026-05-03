from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import aiosqlite

from app.branch_config import lab_paper_cumulative_basis_cents, lab_paper_equity_start_cents
from app.persistence import Store, _normalize_loaded_config, normalize_trade_branch_for_db


class NormalizeLoadedConfigTest(unittest.TestCase):
    def test_empty_top_level_rules_gets_default_pack(self) -> None:
        cfg: dict = {"rules": []}
        _normalize_loaded_config(cfg)
        self.assertGreater(len(cfg["rules"]), 0)
        self.assertTrue(
            all(isinstance(r, dict) and "min_prob" in r for r in cfg["rules"])
        )


class BranchResetTest(unittest.IsolatedAsyncioTestCase):
    def test_normalize_trade_branch_for_db_folds_spaces(self) -> None:
        self.assertEqual(normalize_trade_branch_for_db("lab b"), "lab_b")
        self.assertEqual(normalize_trade_branch_for_db("LAB  C"), "lab_c")

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

    async def test_equity_snapshot_insert_normalizes_branch_for_series_query(self) -> None:
        """Spaced/odd branch labels must store canonically so ``equity_series(branch='lab_e')`` sees rows."""
        await self.store.load_config()
        await self.store.insert_equity_snapshot(
            "2026-01-01T12:00:00+00:00",
            "simulate",
            500_000,
            "test",
            branch=" lab_e ",
            mtm_equity_cents=500_000,
        )
        rows = await self.store.equity_series(limit=20, branch="lab_e")
        self.assertTrue(len(rows) >= 1)
        self.assertEqual(
            str(rows[-1].get("branch") or "").strip().lower(),
            "lab_e",
        )

    async def test_reset_lab_b_deletes_legacy_spaced_branch_column(self) -> None:
        """Rows stored as ``lab b`` (pre-normalization) must still match ``lab_b`` scoped DELETE."""
        await self.store.load_config()
        async with aiosqlite.connect(self.store.path) as db:
            await db.execute(
                """
                INSERT INTO signals (
                  created_at, window_id, asset_id, ticker, side, executed, mode, branch
                ) VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    "2026-01-01T00:00:00+00:00",
                    "w",
                    "btc",
                    "TXSPACE",
                    "yes",
                    0,
                    "simulate",
                    "lab b",
                ),
            )
            await db.commit()
        await self.store.reset_trading_data(backup=False, branch="lab_b")
        sigs = await self.store.recent_signals(limit=50)
        tickers = {str(s.get("ticker")) for s in sigs}
        self.assertNotIn("TXSPACE", tickers)

    async def test_bulk_reset_one_transaction_removes_listed_branches(self) -> None:
        for ticker, branch in (
            ("TX", "live"),
            ("TY", "lab_a"),
            ("TZ", "lab_child_1"),
        ):
            await self.store.insert_signal(
                {
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "window_id": "w",
                    "asset_id": "btc",
                    "ticker": ticker,
                    "side": "yes",
                    "executed": False,
                    "mode": "simulate",
                    "branch": branch,
                }
            )
        await self.store.reset_trading_data_bulk(
            ["lab_a", "lab_child_1"],
            backup=False,
        )
        sigs = await self.store.recent_signals(limit=50)
        tickers = {str(s.get("ticker")) for s in sigs}
        self.assertIn("TX", tickers)
        self.assertNotIn("TY", tickers)
        self.assertNotIn("TZ", tickers)

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
        rows = await self.store.query_table(
            "trades", branch="lab_a", limit=20, offset=0
        )
        tickers = {str(r.get("ticker")) for r in rows}
        self.assertIn("KX-OLD", tickers)

    def test_lab_paper_book_ignores_lifetime_cumulative_does_not(self) -> None:
        cfg = {
            "paper_balance_cents": 100_000,
            "lab_b": {
                "paper_balance_cents": 100_000,
                "paper_lifetime_basis_cents": 300_000,
            },
        }
        self.assertEqual(lab_paper_equity_start_cents(cfg, "lab_b"), 100_000)
        self.assertEqual(lab_paper_cumulative_basis_cents(cfg, "lab_b"), 300_000)

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

    async def test_uniform_paper_balance_keeps_optimizer_settings(self) -> None:
        cfg = await self.store.load_config()
        oc = dict(cfg.get("optimizer") or {})
        oc["optimizer_cycle_count"] = 77
        oc["_mass_reset_test_marker"] = "preserve"
        cfg["optimizer"] = oc
        cfg["paper_balance_cents"] = 50_000
        for lk in ("lab_a", "lab_b", "lab_c", "lab_d"):
            cfg[lk] = {
                **(cfg.get(lk) or {}),
                "paper_balance_cents": 50_000,
                "paper_lifetime_basis_cents": 80_000,
            }
        await self.store.save_config(cfg)

        out = await self.store.apply_uniform_paper_balance_after_scope_reset(
            600_000,
            history_branch="global",
            history_changed_by="test",
            history_reason="uniform_paper_balance_after_scope_reset",
        )
        self.assertEqual(out["paper_balance_cents"], 600_000)

        cfg2 = await self.store.load_config()
        oc2 = cfg2.get("optimizer") if isinstance(cfg2.get("optimizer"), dict) else {}
        self.assertEqual(int(oc2.get("optimizer_cycle_count") or 0), 77)
        self.assertEqual(str(oc2.get("_mass_reset_test_marker") or ""), "preserve")
        self.assertEqual(int(cfg2["paper_balance_cents"]), 600_000)
        self.assertNotIn("paper_lifetime_basis_cents", cfg2.get("lab_a") or {})


if __name__ == "__main__":
    unittest.main()
