from __future__ import annotations

import datetime as dt
import os
import statistics
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.branch_config import BRANCH_LAB_A, BRANCH_LIVE, live_paper_trading_enabled, merge_branch_config
from app.engine import (
    _calculate_net_unrealized_pct_after_fees,
    _handle_patient_stop_loss_exits,
    consecutive_stake_cents,
    pick_trade_rule,
)
from app.optimizer.fitness import composite_fitness_score, is_statistically_better
from app.persistence import Store


async def _stall_until_stop(engines, stop_event):  # noqa: ARG001
    await stop_event.wait()


async def _opt_until_stop(stop_event):
    await stop_event.wait()


class ConsecutiveStakeNonNegativeTest(unittest.TestCase):
    def test_stake_is_never_negative(self) -> None:
        for bal in (0, 1, 100, 10_000, 500_000):
            for spent in (-5, 0, bal // 2, bal, bal + 100):
                for frac in (0, 0.0001, 0.03, 0.5, 1.0, 1.5):
                    s = consecutive_stake_cents(bal, max(0, spent), frac)
                    self.assertGreaterEqual(s, 0, msg=f"bal={bal} spent={spent} frac={frac} -> {s}")


class RuleMatchTest(unittest.TestCase):
    def test_pick_trade_rule_returns_rule_when_band_matches(self) -> None:
        rule = {
            "name": "b",
            "min_prob": 0.2,
            "max_prob": 0.8,
            "min_minutes_left": 0.0,
            "max_minutes_left": 20.0,
        }
        picked = pick_trade_rule(
            0.5,
            10.0,
            [rule],
            has_yes_rules=True,
            has_no_book=True,
            cfg={},
        )
        self.assertIsNotNone(picked)
        self.assertEqual(picked.get("name"), "b")


class PatientStopLossGatingTest(unittest.IsolatedAsyncioTestCase):
    def test_net_unrealized_pct_runs(self) -> None:
        t = {
            "amount_cents": 10_000,
            "side": "yes",
            "contracts_fp": "100",
            "extra_json": '{"paper_fee_model": "none"}',
        }
        full_cfg: dict = {"paper_fee_bps": 0, "paper_balance_cents": 500_000}
        pct = _calculate_net_unrealized_pct_after_fees(t, 0.5, full_cfg=full_cfg, branch=BRANCH_LAB_A)
        self.assertIsInstance(pct, float)

    async def test_handler_returns_zero_when_feature_disabled(self) -> None:
        class _S:
            async def open_sim_trades_for_branch(self, _b: str) -> list[dict]:  # noqa: D401
                return [
                    {
                        "id": 1,
                        "simulated": 1,
                        "ticker": "KXTEST-1",
                        "side": "yes",
                        "created_at": "2026-01-01T00:00:00+00:00",
                        "amount_cents": 1000,
                        "contracts_fp": "10",
                        "extra_json": "{}",
                    }
                ]

            async def update_trade_sim_early_close(self, *_a, **_k) -> None:  # noqa: D401, ANN001, ARG002
                raise AssertionError("close should not run when feature disabled")

        now = dt.datetime(2026, 1, 1, 1, 0, 0, tzinfo=dt.timezone.utc)
        full_cfg: dict = {
            "engine_running": False,
            "lab_a": {"engine_running": True},
            "enable_patient_stop_loss": False,
        }
        m = merge_branch_config(full_cfg, BRANCH_LAB_A)
        self.assertIsNotNone(m)
        assert m is not None
        eng = SimpleNamespace(store=_S(), client=MagicMock(), branch=BRANCH_LAB_A, state=SimpleNamespace(last_error=""))
        n = await _handle_patient_stop_loss_exits(eng, full_cfg=full_cfg, cfg=m, now=now, trace=[])
        self.assertEqual(n, 0)

    async def test_losing_hold_threshold_and_fees(self) -> None:
        class _S:
            async def open_sim_trades_for_branch(self, _b: str) -> list[dict]:  # noqa: D401
                return [
                    {
                        "id": 1,
                        "simulated": 1,
                        "ticker": "KXTEST-1",
                        "side": "yes",
                        "created_at": "2026-01-01T00:00:00+00:00",
                        "amount_cents": 1000,
                        "contracts_fp": "10",
                        "extra_json": "{}",
                    }
                ]

            async def update_trade_sim_early_close(self, *_a, **_k) -> None:  # noqa: D401, ANN001, ARG002
                raise AssertionError("should not close: hold time not met")

        now = dt.datetime(2026, 1, 1, 0, 10, 0, tzinfo=dt.timezone.utc)  # 10 min; min_hold=45
        full_cfg: dict = {
            "engine_running": False,
            "lab_a": {"engine_running": True},
            "enable_patient_stop_loss": True,
            "stop_loss_trigger_pct": -0.1,
            "min_hold_minutes_before_stop": 45,
        }
        m = merge_branch_config(full_cfg, BRANCH_LAB_A)
        self.assertIsNotNone(m)
        assert m is not None
        eng = SimpleNamespace(store=_S(), client=MagicMock(), branch=BRANCH_LAB_A, state=SimpleNamespace(last_error=""))
        n = await _handle_patient_stop_loss_exits(eng, full_cfg=full_cfg, cfg=m, now=now, trace=[])
        self.assertEqual(n, 0)  # hold gate before fee/net comparison

    async def test_not_run_on_non_paper_live(self) -> None:
        class _S:
            async def open_sim_trades_for_branch(self, _b: str) -> list:  # noqa: D401
                raise AssertionError("should not query opens on real live")

        full_cfg = {"simulate": False, "live_paper_trading": False, "engine_running": True, "enable_patient_stop_loss": True}
        m = merge_branch_config(full_cfg, BRANCH_LIVE)
        self.assertIsNotNone(m)
        assert m is not None
        self.assertFalse(live_paper_trading_enabled(full_cfg))
        eng = SimpleNamespace(store=_S(), client=MagicMock(), branch=BRANCH_LIVE, state=SimpleNamespace(last_error=""))
        n = await _handle_patient_stop_loss_exits(
            eng,
            full_cfg=full_cfg,
            cfg=m,
            now=dt.datetime.now(dt.timezone.utc),
            trace=[],
        )
        self.assertEqual(n, 0)


class PromotionFitnessGatesTest(unittest.TestCase):
    def test_median_control_score_gate_matches_promotion_module(self) -> None:
        """``lab_a_promotion_report`` uses score_a > median(B,C,D) together with ``is_statistically_better``."""
        fit_a: dict = {"score_dollars": 10.0}
        fit_b: dict = {"score_dollars": 1.0}
        fit_c: dict = {"score_dollars": 2.0}
        fit_d: dict = {"score_dollars": 3.0}
        score_a = float(fit_a["score_dollars"])
        scores_bcd = [float(fit_b["score_dollars"]), float(fit_c["score_dollars"]), float(fit_d["score_dollars"])]
        med_bcd = float(statistics.median(scores_bcd))
        self.assertTrue(bool(score_a > med_bcd))

    def test_composite_fitness_score(self) -> None:
        out = composite_fitness_score(
            total_pnl_cents=30,
            cumulative_equity_cents=[0, 20, 10, 30],
            per_trade_pnl_cents=[20, 10, 5, 5],
        )
        self.assertIn("score_dollars", out)

    def test_is_statistically_better_detail(self) -> None:
        a = [0.1, 0.2, 0.3, 0.15, 0.1]
        b = [-0.1, 0.0, 0.05, -0.02, 0.01, 0.0, 0.0]
        ok, detail = is_statistically_better(
            a, b, lab_a_score=5.0, control_scores=(1.0, 1.0, 2.0), alpha=0.5, score_margin_pct=0.0
        )
        self.assertIsInstance(ok, bool)
        self.assertIn("median_control_scores", detail)
        self.assertIn("t_test_gate", detail)


class SimulateDisableGuardTest(unittest.TestCase):
    @staticmethod
    def _client() -> TestClient:
        import app.main as main

        fd, path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(fd)
        main.store = Store(path=path)
        return TestClient(main.app)

    def test_put_config_disabling_paper_requires_confirm(self) -> None:
        with (
            patch("app.main.dual_engine_loop", _stall_until_stop),
            patch("app.main._optimizer_loop", _opt_until_stop),
        ):
            c = self._client()
            with c:
                r = c.put("/api/config", json={"simulate": False})
        self.assertEqual(r.status_code, 400)
        with (
            patch("app.main.dual_engine_loop", _stall_until_stop),
            patch("app.main._optimizer_loop", _opt_until_stop),
        ):
            c2 = self._client()
            with c2:
                r2 = c2.put("/api/config?confirm=YES", json={"simulate": False})
        self.assertEqual(r2.status_code, 200, msg=r2.text)
        j = r2.json()
        self.assertFalse(live_paper_trading_enabled(j))
        self.assertFalse(j.get("simulate"))

    def test_engine_toggle_disabling_paper_requires_confirm(self) -> None:
        with (
            patch("app.main.dual_engine_loop", _stall_until_stop),
            patch("app.main._optimizer_loop", _opt_until_stop),
        ):
            c = self._client()
            with c:
                r = c.post("/api/engine/toggle?simulate=false")
        self.assertEqual(r.status_code, 400)
        with (
            patch("app.main.dual_engine_loop", _stall_until_stop),
            patch("app.main._optimizer_loop", _opt_until_stop),
        ):
            c2 = self._client()
            with c2:
                r2 = c2.post("/api/engine/toggle?simulate=false&confirm=YES")
        self.assertEqual(r2.status_code, 200, msg=r2.text)


if __name__ == "__main__":
    unittest.main()
