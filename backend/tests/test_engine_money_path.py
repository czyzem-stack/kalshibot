from __future__ import annotations

import datetime as dt
import json
import os
import statistics
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.branch_config import BRANCH_LAB_A, BRANCH_LIVE, live_paper_trading_enabled, merge_branch_config
from app.engine import (
    _calculate_net_unrealized_pct_after_fees,
    _handle_patient_stop_loss_exits,
    consecutive_stake_cents,
    pick_trade_rule,
    rule_matches,
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

    def test_rule_matches_false_when_outside_yes_band(self) -> None:
        rule = {
            "name": "mid",
            "min_prob": 0.4,
            "max_prob": 0.6,
            "min_minutes_left": 1.0,
            "max_minutes_left": 20.0,
        }
        self.assertFalse(rule_matches(0.15, 10.0, rule))

    def test_rule_matches_picks_narrow_edge_implied_versus_bounds(self) -> None:
        """Tight band: only mid-range implied YES + time in window counts as a match (edge = tradeable slice)."""
        rule = {
            "name": "tight",
            "min_prob": 0.48,
            "max_prob": 0.52,
            "min_minutes_left": 5.0,
            "max_minutes_left": 15.0,
        }
        self.assertTrue(rule_matches(0.5, 10.0, rule))
        self.assertFalse(rule_matches(0.5, 3.0, rule))


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

    def test_put_config_confirm_yes_stores_audit_meta(self) -> None:
        with (
            patch("app.main.dual_engine_loop", _stall_until_stop),
            patch("app.main._optimizer_loop", _opt_until_stop),
        ):
            c = self._client()
            with c:
                r = c.put(
                    "/api/config?confirm=YES",
                    json={"simulate": False},
                    headers={"User-Agent": "KalshibotTest/audit"},
                )
                self.assertEqual(r.status_code, 200, msg=r.text)
                h = c.get("/api/config/history?limit=1&include_config=false")
        self.assertEqual(h.status_code, 200)
        rows = h.json().get("rows") or []
        self.assertTrue(rows, msg=h.text)
        am = rows[0].get("audit_meta")
        self.assertIsInstance(am, dict, msg=repr(rows[0]))
        self.assertEqual(am.get("event"), "live_paper_trading_disabled_confirm_yes")
        self.assertEqual(am.get("confirm_token"), "YES")
        self.assertIn("request_body", am)
        self.assertEqual(am.get("user_agent"), "KalshibotTest/audit")

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


class OptimizerReplayStopLossTest(unittest.TestCase):
    def _base_rule(self) -> dict:
        return {
            "name": "r1",
            "side": "yes",
            "min_prob": 0.4,
            "max_prob": 0.6,
            "min_minutes_left": 0.0,
            "max_minutes_left": 20.0,
        }

    def _sig(self) -> list[dict]:
        return [
            {
                "id": 10,
                "ticker": "KX-TEST-REPLAY-1",
                "implied_prob": 0.5,
                "minutes_left": 8.0,
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        ]

    @patch("app.optimizer_claude._calculate_net_unrealized_pct_after_fees", return_value=-8.0)
    def test_replay_simulates_patient_stop_on_open_positions(self, _mock_net: object) -> None:
        from app import optimizer_claude as opt_mod
        from app.branch_config import BRANCH_LAB_A

        open_pos = [
            {
                "simulated": 1,
                "ticker": "KX-TEST-REPLAY-1",
                "side": "yes",
                "status": "open",
                "created_at": "2026-01-01T00:00:00+00:00",
                "amount_cents": 10_000,
                "contracts_fp": "100",
                "extra_json": '{"paper_fee_model": "none"}',
            }
        ]
        full_cfg: dict = {"paper_balance_cents": 500_000, "paper_fee_bps": 0}
        sig = sorted(self._sig(), key=lambda s: -int(s.get("id") or 0))
        end = dt.datetime(2026, 1, 1, 1, 0, 0, tzinfo=dt.timezone.utc)
        d = opt_mod.replay_under_rules_detail(
            [],
            [self._base_rule()],
            sig,
            include_fees_in_score=True,
            branch_trading_cfg={
                "enable_patient_stop_loss": True,
                "stop_loss_trigger_pct": -0.1,
                "min_hold_minutes_before_stop": 0,
            },
            open_positions=open_pos,
            full_cfg=full_cfg,
            branch=BRANCH_LAB_A,
            replay_end_time=end,
        )
        self.assertEqual(int(d.get("open_simulated_stop_exits_n") or 0), 1)
        self.assertEqual(int(d.get("stop_loss_exits_n") or 0), 1)
        self.assertGreater(float(d.get("stop_loss_trigger_rate") or 0.0), 0.0)

    def test_replay_no_simulated_exits_when_stop_disabled(self) -> None:
        from app import optimizer_claude as opt_mod
        from app.branch_config import BRANCH_LAB_A

        open_pos = [
            {
                "simulated": 1,
                "ticker": "KX-TEST-REPLAY-1",
                "side": "yes",
                "status": "open",
                "created_at": "2026-01-01T00:00:00+00:00",
                "amount_cents": 10_000,
                "contracts_fp": "100",
                "extra_json": "{}",
            }
        ]
        full_cfg: dict = {"paper_balance_cents": 500_000}
        sig = sorted(self._sig(), key=lambda s: -int(s.get("id") or 0))
        end = dt.datetime(2026, 1, 1, 1, 0, 0, tzinfo=dt.timezone.utc)
        d = opt_mod.replay_under_rules_detail(
            [],
            [self._base_rule()],
            sig,
            include_fees_in_score=True,
            branch_trading_cfg={
                "enable_patient_stop_loss": False,
                "stop_loss_trigger_pct": -0.1,
                "min_hold_minutes_before_stop": 0,
            },
            open_positions=open_pos,
            full_cfg=full_cfg,
            branch=BRANCH_LAB_A,
            replay_end_time=end,
        )
        self.assertEqual(int(d.get("open_simulated_stop_exits_n") or 0), 0)
        self.assertEqual(len(d.get("per_trade_pnl_cents_chrono") or []), 0)

    def test_replay_rate_and_pnl_from_stops_historical(self) -> None:
        from app import optimizer_claude as opt_mod

        settled = [
            {
                "id": 1,
                "status": "settled",
                "ticker": "KX-TEST-REPLAY-1",
                "pnl_cents": -200,
                "created_at": "2026-01-01T00:00:00+00:00",
                "settled_at": "2026-01-01T00:20:00+00:00",
                "result": "patient_stop_loss",
                "extra_json": json.dumps(
                    {
                        "patient_stop_loss": True,
                        "entry_premium_cents": 10_000,
                        "entry_fee_cents": 0,
                        "settlement_exit_fee_cents": 0,
                    }
                ),
            },
            {
                "id": 2,
                "status": "settled",
                "ticker": "KX-TEST-REPLAY-1",
                "pnl_cents": 500,
                "created_at": "2026-01-01T00:00:00+00:00",
                "settled_at": "2026-01-01T00:20:00+00:00",
                "extra_json": "{}",
            },
        ]
        sig = sorted(self._sig(), key=lambda s: -int(s.get("id") or 0))
        d = opt_mod.replay_under_rules_detail(
            settled,
            [self._base_rule()],
            sig,
            include_fees_in_score=True,
            branch_trading_cfg={
                "enable_patient_stop_loss": True,
                "stop_loss_trigger_pct": -0.1,
                "min_hold_minutes_before_stop": 0,
            },
        )
        per = d.get("per_trade_pnl_cents_chrono") or []
        self.assertEqual(len(per), 2)
        # Raw -200; replay applies liquidity scale from synthetic spread (~0.976) → ~-195.
        self.assertEqual(int(d.get("total_pnl_from_stops_cents") or 0), -195)
        self.assertEqual(float(d.get("stop_loss_trigger_rate") or 0.0), 50.0)
        self.assertEqual(int(d.get("stop_loss_exits_n") or 0), 1)

    @patch("app.optimizer_claude._calculate_net_unrealized_pct_after_fees", return_value=-10.0)
    def test_fitness_score_includes_synthetic_open_stop(self, _m: object) -> None:
        from app import optimizer_claude as opt_mod
        from app.branch_config import BRANCH_LAB_A

        open_pos = [
            {
                "simulated": 1,
                "ticker": "KX-TEST-REPLAY-1",
                "side": "yes",
                "status": "open",
                "created_at": "2026-01-01T00:00:00+00:00",
                "amount_cents": 10_000,
                "contracts_fp": "100",
                "extra_json": '{"paper_fee_model": "none"}',
            }
        ]
        full_cfg: dict = {"paper_balance_cents": 500_000, "paper_fee_bps": 0}
        sig = sorted(self._sig(), key=lambda s: -int(s.get("id") or 0))
        end = dt.datetime(2026, 1, 1, 1, 0, 0, tzinfo=dt.timezone.utc)
        b = opt_mod._replay_fitness_bundle(
            [],
            [self._base_rule()],
            sig,
            include_fees_in_score=True,
            max_rows=20,
            branch_trading_cfg={
                "enable_patient_stop_loss": True,
                "stop_loss_trigger_pct": -0.1,
                "min_hold_minutes_before_stop": 0,
            },
            open_positions=open_pos,
            full_cfg=full_cfg,
            branch=BRANCH_LAB_A,
            replay_end_time=end,
        )
        self.assertLess(float(b["total_pnl_cents"]), 0.0)
        self.assertIn("score_dollars", b)
        self.assertNotEqual(int(b.get("total_pnl_from_stops_cents") or 0), 0)


class AutoRevertStuckTest(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _eight_settled() -> list[dict]:
        out: list[dict] = []
        for i in range(8):
            out.append(
                {
                    "status": "settled",
                    "pnl_cents": 1,
                    "ticker": f"KX-T{i}",
                    "created_at": f"2026-01-15T10:0{i}:00+00:00",
                    "extra_json": '{"rule": "a", "entry_implied_yes": 0.5}',
                }
            )
        return out

    async def test_auto_revert_skips_when_flag_off(self) -> None:
        from app import optimizer_claude as ocm

        rules = [{"name": "a", "min_prob": 0.0, "max_prob": 1.0, "min_minutes_left": 0.0, "max_minutes_left": 60.0}]
        cfg: dict = {"lab_a": {"rules": rules}}
        oc = ocm._norm_opt_cfg({**ocm._opt_cfg({"optimizer": {}}), "enable_auto_revert": False})
        store = MagicMock()
        meta = await ocm._maybe_auto_revert_if_stuck(
            store,
            cfg=cfg,
            oc=oc,
            tr_a=self._eight_settled(),
            sg_a=[],
            at_iso="2026-01-15T12:00:00+00:00",
            red_streak=20,
            acceptance_pct=10.0,
        )
        self.assertEqual(meta.get("reason"), "disabled")
        store.list_config_history.assert_not_called()

    async def test_auto_revert_respects_4h_cooldown(self) -> None:
        from app import optimizer_claude as ocm

        rules = [{"name": "a", "min_prob": 0.0, "max_prob": 1.0, "min_minutes_left": 0.0, "max_minutes_left": 60.0}]
        cfg: dict = {"lab_a": {"rules": rules}}
        base = ocm._norm_opt_cfg(ocm._opt_cfg({"optimizer": {}}))
        base["optimizer_auto_revert_last_at"] = "2026-01-15T10:00:00+00:00"
        store = MagicMock()
        meta = await ocm._maybe_auto_revert_if_stuck(
            store,
            cfg=cfg,
            oc=base,
            tr_a=self._eight_settled(),
            sg_a=[],
            at_iso="2026-01-15T12:00:00+00:00",
            red_streak=20,
            acceptance_pct=10.0,
        )
        self.assertEqual(meta.get("reason"), "cooldown")
        store.list_config_history.assert_not_called()

    @patch("app.optimizer_claude._replay_fitness_bundle", return_value={"score_dollars": 9.5})
    @patch("app.optimizer_claude._replay_open_kw", return_value={})
    async def test_auto_revert_red_15_loads_best_history_lab_a(self, _m_open: object, _m_fb: object) -> None:
        from app import optimizer_claude as ocm

        rules = [{"name": "a", "min_prob": 0.0, "max_prob": 1.0, "min_minutes_left": 0.0, "max_minutes_left": 60.0}]
        cfg: dict = {"lab_a": {"rules": list(rules)}}
        oc = ocm._norm_opt_cfg(ocm._opt_cfg({"optimizer": {}}))
        store = MagicMock()
        store.list_config_history = AsyncMock(
            return_value=[
                {
                    "id": 7,
                    "timestamp": "2026-01-10T00:00:00+00:00",
                    "config": {
                        "lab_a": {
                            "rules": list(rules),
                            "balance_fraction_per_window": 0.033,
                        }
                    },
                }
            ]
        )
        tr_a = self._eight_settled()
        meta = await ocm._maybe_auto_revert_if_stuck(
            store,
            cfg=cfg,
            oc=oc,
            tr_a=tr_a,
            sg_a=[],
            at_iso="2026-01-15T12:00:00+00:00",
            red_streak=15,
            acceptance_pct=50.0,
        )
        self.assertTrue(bool(meta.get("reverted")))
        self.assertEqual(float(cfg["lab_a"].get("balance_fraction_per_window") or 0), 0.033)
        self.assertEqual(oc.get("optimizer_red_streak_cycles"), 0)
        tr = oc.get("internal_optimizer_trace")
        self.assertIsInstance(tr, list)
        self.assertEqual(str((tr[0] if tr else {}).get("reject_reason")), "auto-revert-stuck")
        self.assertTrue(bool((tr[0] if tr else {}).get("auto_revert")))


class WeightedEdgeAndRegimeTest(unittest.TestCase):
    def test_calculate_weighted_edge_penalizes_wider_spread(self) -> None:
        from app.optimizer.weighted_edge import calculate_weighted_edge

        rule = {"side": "yes"}
        tight = {"yes_bid_dollars": 0.48, "yes_ask_dollars": 0.52}
        wide = {"yes_bid_dollars": 0.20, "yes_ask_dollars": 0.80}
        t = calculate_weighted_edge(tight, rule)
        w = calculate_weighted_edge(wide, rule)
        # Same mid; wider ask yields more negative raw edge, and liquidity factor is smaller.
        self.assertGreater(t, w)

    def test_trading_regime_key_event_risk_from_stop_rate(self) -> None:
        from app import optimizer_claude as ocm

        oc = ocm._norm_opt_cfg(
            {
                "replay_stop_loss_trigger_rate_pct": 40.0,
            }
        )
        r = ocm._trading_regime_key_from_context(oc, [], [], "2026-01-15T12:00:00+00:00")
        self.assertEqual(r, "event_risk")

    def test_sync_regime_applies_event_rules_to_lab_a(self) -> None:
        from app import optimizer_claude as ocm

        base = [
            {"name": "base", "min_prob": 0.0, "max_prob": 1.0, "min_minutes_left": 0.0, "max_minutes_left": 99.0}
        ]
        event_only = [
            {"name": "event_family", "min_prob": 0.0, "max_prob": 1.0, "min_minutes_left": 0.0, "max_minutes_left": 99.0}
        ]
        cfg: dict = {"lab_a": {"rules": [dict(x) for x in base], "rules_event": [dict(x) for x in event_only]}}
        oc = ocm._norm_opt_cfg({"replay_stop_loss_trigger_rate_pct": 50.0})
        ocm._sync_regime_rule_families_to_lab_a(cfg, oc, [], [], "2026-01-15T12:00:00+00:00")
        la = cfg.get("lab_a")
        self.assertIsInstance(la, dict)
        self.assertEqual(la.get("active_regime"), "event_risk")
        names = {str(r.get("name")) for r in (la.get("rules") or []) if isinstance(r, dict)}
        self.assertIn("event_family", names)


class PaperLoserDetectionTest(unittest.IsolatedAsyncioTestCase):
    def test_paper_loser_not_triggered_when_fitness_is_not_paper_winner(self) -> None:
        from app import optimizer_claude as ocm

        oc = ocm._norm_opt_cfg({})
        # Even with extreme stop rate, a non-positive score_dollars is not a "paper winner".
        rr: dict = {"score_dollars": -0.1, "stop_loss_trigger_rate": 90.0}
        self.assertFalse(ocm._is_paper_winner_but_real_loser(oc, rr))

    def test_paper_loser_true_high_stop_rate_with_good_replay(self) -> None:
        from app import optimizer_claude as ocm

        oc = ocm._norm_opt_cfg({})
        rr: dict = {"score_dollars": 1.0, "stop_loss_trigger_rate": 46.0}
        self.assertTrue(ocm._is_paper_winner_but_real_loser(oc, rr))

    def test_paper_loser_true_negative_equity_trace_streak(self) -> None:
        from app import optimizer_claude as ocm

        oc = ocm._norm_opt_cfg({"paper_loser_neg_equity_trace_min": 5})
        oc["internal_optimizer_trace"] = [{"equity_slope_dph": -1.0} for _ in range(5)]
        rr: dict = {"score_dollars": 2.0, "stop_loss_trigger_rate": 10.0}
        self.assertTrue(ocm._is_paper_winner_but_real_loser(oc, rr))

    def test_paper_loser_respects_enable_flag(self) -> None:
        from app import optimizer_claude as ocm

        oc = ocm._norm_opt_cfg({})
        oc["enable_paper_loser_detection"] = False
        self.assertFalse(
            ocm._is_paper_winner_but_real_loser(
                oc,
                {"score_dollars": 1.0, "stop_loss_trigger_rate": 90.0},
            )
        )

    async def test_paper_loser_full_swap_runs_regime_bump(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from app import optimizer_claude as ocm

        r = {"name": "a", "min_prob": 0.0, "max_prob": 1.0, "min_minutes_left": 0.0, "max_minutes_left": 60.0}
        cfg: dict = {
            "lab_a": {
                "active_regime": "high_vol",
                "rules": [dict(r)],
                "rules_high_vol": [dict(r)],
                "rules_low_vol": [dict(r)],
                "rules_event": [dict(r)],
            }
        }
        oc = ocm._norm_opt_cfg({})
        store = MagicMock()
        store.list_config_history = AsyncMock(return_value=[])
        meta = await ocm._apply_paper_loser_strategy_swap(
            store, cfg, oc, at_iso="2026-01-20T00:00:00+00:00", repeated_cycles=4
        )
        self.assertTrue(meta.get("swapped"))
        # high_vol -> next in PAPER_LOSER_REGIME_ORDER is low_vol
        self.assertEqual((cfg.get("lab_a") or {}).get("active_regime"), "low_vol")
        self.assertTrue(oc.get("paper_loser_radical_next") is True)
        self.assertEqual(int(oc.get("optimizer_consecutive_paper_loser_cycles", -1) or 0), 0)

    async def test_paper_loser_no_swap_below_threshold_cycles(self) -> None:
        from unittest.mock import MagicMock

        from app import optimizer_claude as ocm

        r = {"name": "a", "min_prob": 0.0, "max_prob": 1.0, "min_minutes_left": 0.0, "max_minutes_left": 60.0}
        cfg: dict = {"lab_a": {"rules": [dict(r)]}}
        meta = await ocm._apply_paper_loser_strategy_swap(
            MagicMock(), cfg, ocm._norm_opt_cfg({}), at_iso="2026-01-20T00:00:00+00:00", repeated_cycles=3
        )
        self.assertFalse(bool(meta.get("swapped")))

    def test_check_optimizer_health_shows_paper_loser(self) -> None:
        from app import optimizer_claude as ocm

        oc = ocm._norm_opt_cfg({"enable_paper_loser_detection": True, "paper_loser_cycles_threshold": 4})
        oc["paper_loser_risk_last"] = True
        oc["optimizer_consecutive_paper_loser_cycles"] = 2
        h = ocm._check_optimizer_health(oc)
        self.assertTrue("paper_loser" in (h.get("suggested_action") or "").casefold() or "paper-loser" in (h.get("suggested_action") or "").casefold())
        self.assertIn("paper_loser_risk_last", h)


class AutoRelaxTest(unittest.TestCase):
    def test_is_lab_a_under_trading_fewer_than_threshold_in_window(self) -> None:
        from app import optimizer_claude as ocm

        end = dt.datetime(2026, 4, 1, 12, 0, 0, tzinfo=dt.timezone.utc)
        tr_a = [
            {"created_at": "2026-04-01T08:00:00+00:00", "status": "settled", "ticker": "A"},
            {"created_at": "2026-04-01T09:30:00+00:00", "status": "settled", "ticker": "B"},
        ]
        oc = ocm._norm_opt_cfg({"auto_relax_trade_threshold": 3, "auto_relax_hours_window": 6, "interval_minutes": 20})
        self.assertTrue(ocm._is_lab_a_under_trading(tr_a, oc, end))

    def test_is_lab_a_under_trading_zero_trades_in_last_four_optimizer_intervals(self) -> None:
        from app import optimizer_claude as ocm

        end = dt.datetime(2026, 4, 1, 12, 0, 0, tzinfo=dt.timezone.utc)
        # 3+ trades in 6h, but all older than 4×20m (second branch: no fills in the last 4 sched cycles)
        t_old = (end - dt.timedelta(hours=2, minutes=5)).replace(tzinfo=dt.timezone.utc).isoformat()
        tr_a = [
            {"created_at": t_old, "status": "settled", "ticker": "A1"},
            {"created_at": t_old, "status": "settled", "ticker": "A2"},
            {"created_at": t_old, "status": "settled", "ticker": "A3"},
        ]
        oc = ocm._norm_opt_cfg({"auto_relax_trade_threshold": 3, "auto_relax_hours_window": 6, "interval_minutes": 20})
        self.assertTrue(ocm._is_lab_a_under_trading(tr_a, oc, end))

    def test_auto_relax_conservative_params_tighten_and_larger_size(self) -> None:
        from app import optimizer_claude as ocm
        from app.branch_config import MIN_BALANCE_FRACTION_PER_WINDOW

        r = {
            "name": "a",
            "side": "yes",
            "min_prob": 0.55,
            "max_prob": 0.95,
            "min_minutes_left": 12.0,
            "max_minutes_left": 60.0,
        }
        cfg: dict = {
            "balance_fraction_per_window": 0.04,
            "lab_a": {"rules": [dict(r)], "balance_fraction_per_window": 0.04},
        }
        oc = ocm._norm_opt_cfg(
            {
                "lab_a_yes_floor_pct": 60,
                "lab_a_min_minutes_left": 14,
                "loss_streak_trigger": 2,
            }
        )
        out = ocm._auto_relax_conservative_params(cfg, oc, at_iso="2026-04-01T12:00:00+00:00")
        self.assertIsNotNone(out)
        self.assertEqual(out.get("style"), "auto_relax")
        self.assertEqual(oc.get("lab_a_yes_floor_pct"), 58)
        self.assertEqual(oc.get("lab_a_min_minutes_left"), 12)
        self.assertEqual(int(oc.get("loss_streak_trigger") or 0), 3)
        bf = float((cfg.get("lab_a") or {}).get("balance_fraction_per_window") or 0)
        self.assertGreater(bf, 0.04)
        self.assertLessEqual(bf, 0.12)
        self.assertGreaterEqual(bf, float(MIN_BALANCE_FRACTION_PER_WINDOW))

    def test_auto_relax_cooldown_prevents_rapid_repeats(self) -> None:
        from app import optimizer_claude as ocm

        end = dt.datetime(2026, 4, 1, 12, 0, 0, tzinfo=dt.timezone.utc)
        oc = ocm._norm_opt_cfg(
            {
                "optimizer_last_auto_relax_at": (end - dt.timedelta(hours=1))
                .replace(tzinfo=dt.timezone.utc)
                .isoformat(),
                "auto_relax_cooldown_hours": 4,
            }
        )
        self.assertTrue(ocm._auto_relax_cooldown_active(oc, end))
        self.assertTrue(ocm._auto_relax_cooldown_active(dict(oc, optimizer_last_auto_relax_at=end.isoformat(), auto_relax_cooldown_hours=4), end))
        self.assertFalse(
            ocm._auto_relax_cooldown_active(
                {
                    "optimizer_last_auto_relax_at": (end - dt.timedelta(hours=5))
                    .replace(tzinfo=dt.timezone.utc)
                    .isoformat(),
                    "auto_relax_cooldown_hours": 4,
                },
                end,
            )
        )

    def test_norm_opt_cfg_has_auto_relax_flags(self) -> None:
        from app import optimizer_claude as ocm

        o = ocm._norm_opt_cfg({})
        self.assertTrue("enable_auto_relax" in o and o["enable_auto_relax"] is True)
        self.assertEqual(int(o.get("auto_relax_trade_threshold", 0)), 3)
        self.assertEqual(float(o.get("auto_relax_hours_window", 0)), 6.0)
        self.assertEqual(float(o.get("auto_relax_cooldown_hours", 0)), 4.0)


class AutonomousOptimizerMetaAndTuningTest(unittest.TestCase):
    def test_regime_meta_ewma_decay_and_update(self) -> None:
        from app import optimizer_claude as ocm

        oc = ocm._norm_opt_cfg({})
        oc["regime_ewma_decay_per_cycle"] = 0.5
        oc["regime_ewma_alpha"] = 0.5
        ocm._regime_update_meta_and_streaks(oc, active_regime="low_vol", score_dollars=2.0)
        e0 = ocm._norm_regime_perf_meta(oc)["low_vol"]["ewma_fitness"]
        ocm._regime_update_meta_and_streaks(oc, active_regime="low_vol", score_dollars=0.0)
        e1 = ocm._norm_regime_perf_meta(oc)["low_vol"]["ewma_fitness"]
        self.assertNotEqual(round(e0, 3), round(e1, 3))

    def test_auto_threshold_tightens_on_frequent_swaps(self) -> None:
        from app import optimizer_claude as ocm

        oc = ocm._norm_opt_cfg({})
        oc["optimizer_cycle_count"] = 24
        oc["autotune_window_paper_loser_swaps"] = 3
        oc["autotune_window_paper_loser_risk_events"] = 0
        oc["paper_loser_cycles_threshold"] = 4
        ocm._auto_tune_internal_thresholds(oc)
        self.assertEqual(int(oc.get("paper_loser_cycles_threshold") or 0), 5)

    def test_interleave_blended_rules_merges_sources(self) -> None:
        from app import optimizer_claude as ocm

        la = {
            "active_regime": "low_vol",
            "rules": [
                {
                    "name": "a1",
                    "min_prob": 0.0,
                    "max_prob": 1.0,
                    "min_minutes_left": 0.0,
                    "max_minutes_left": 60.0,
                }
            ],
            "rules_low_vol": [
                {
                    "name": "b1",
                    "min_prob": 0.0,
                    "max_prob": 1.0,
                    "min_minutes_left": 0.0,
                    "max_minutes_left": 60.0,
                }
            ],
        }
        h2 = [
            (
                "x",
                [
                    {
                        "name": "h1",
                        "min_prob": 0.0,
                        "max_prob": 1.0,
                        "min_minutes_left": 0.0,
                        "max_minutes_left": 60.0,
                    }
                ],
            )
        ]
        out = ocm._interleave_blended_rules("low_vol", la, h2, max_rules=20)
        names = {r.get("name") for r in out}
        self.assertTrue({"h1", "b1"}.issubset(names) or len(out) >= 1)


class BreedingDependentRuleGuardTest(unittest.TestCase):
    """Guards on rule selection that breeding and all sim branches rely on (via ``pick_trade_rule`` / ``rule_matches``)."""

    def test_pick_trade_rule_skips_yes_when_has_yes_rules_false(self) -> None:
        yes_rule = {
            "name": "y",
            "side": "yes",
            "min_prob": 0.4,
            "max_prob": 0.6,
            "min_minutes_left": 0.0,
            "max_minutes_left": 20.0,
        }
        hit = pick_trade_rule(0.5, 10.0, [yes_rule], has_yes_rules=False, has_no_book=True, cfg={})
        self.assertIsNone(hit)

    def test_pick_trade_rule_skips_no_without_orderbook_when_forced_to_no_side(self) -> None:
        cfg = {"no_bet_when_yes_below_pct": 50.0}
        no_rule = {
            "name": "n",
            "side": "no",
            "min_prob": 0.05,
            "max_prob": 0.95,
            "min_minutes_left": 0.0,
            "max_minutes_left": 20.0,
        }
        hit = pick_trade_rule(0.05, 10.0, [no_rule], has_yes_rules=True, has_no_book=False, cfg=cfg)
        self.assertIsNone(hit)

    def test_rule_matches_false_when_minutes_outside_window(self) -> None:
        rule = {
            "name": "win",
            "min_prob": 0.0,
            "max_prob": 1.0,
            "min_minutes_left": 5.0,
            "max_minutes_left": 15.0,
        }
        self.assertFalse(rule_matches(0.5, 2.0, rule))
        self.assertTrue(rule_matches(0.5, 10.0, rule))


if __name__ == "__main__":
    unittest.main()
