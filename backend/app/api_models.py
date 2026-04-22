from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .branch_config import normalize_paper_fee_model
from .persistence import expand_partial_lab_branch


class AssetCfg(BaseModel):
    enabled: bool | None = None
    label: str | None = None
    series_ticker: str | None = None


class RuleCfg(BaseModel):
    name: str = ""
    min_prob: float = 0.0
    max_prob: float = 1.0
    min_minutes_left: float = 0.0
    max_minutes_left: float = 1e9
    # "yes" (default): band is implied YES probability. "no": band is implied NO (= 1 − YES mid); buys NO at no ask.
    side: str | None = Field(default=None, description='yes or no')


def merge_lab_branch_patch(cur: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Merge lab_a / lab_b patch; always coerce ``paper_balance_cents`` to int when provided (non-null)."""
    out = dict(cur)
    for k, v in patch.items():
        if k == "paper_balance_cents":
            if v is None:
                continue
            try:
                out[k] = int(v)
            except (TypeError, ValueError):
                pass
            continue
        if v is not None:
            out[k] = v
    return out


class BotConfigPayload(BaseModel):
    simulate: bool | None = None
    engine_running: bool | None = None
    poll_seconds: float | None = Field(None, ge=2, le=120)
    balance_fraction_per_window: float | None = Field(None, ge=0.0001, le=1.0)
    window_minutes: int | None = Field(None, ge=1, le=1440)
    paper_balance_cents: int | None = None
    assets: dict[str, AssetCfg] | None = None
    rules: list[RuleCfg] | None = None
    only_yes_subtitle_contains: str | None = None
    exclude_yes_subtitle_contains: str | None = None
    # When set (e.g. 30), append a catch-all NO rule: trade NO whenever implied YES < 30% (needs NO book). Send null to clear.
    no_bet_when_yes_below_pct: float | int | None = Field(default=None, ge=1, le=95)
    # Sim-only: buy YES when implied YES ≥ this % and no band matched. Send null to disable. Replaces legacy dev_sim_yes_implied_ge_70.
    dev_sim_yes_implied_ge_pct: float | int | None = Field(default=None, ge=1, le=99)
    # Paper sim: if implied YES moves against the entry by at least this many percentage points (e.g. 50 = 75%→25%), close at bid.
    swing_exit_implied_drop_pct: float | int | None = Field(default=None, ge=0, le=95)
    # Paper sim fee model in basis points (bps) per execution notional. 20 = 0.20%.
    paper_fee_bps: float | int | None = Field(default=None, ge=0, le=500)
    # Kalshi quadratic fee schedule (see https://kalshi.com/docs/kalshi-fee-schedule.pdf) vs flat bps.
    paper_fee_model: str | None = Field(default=None, max_length=32)
    # Multiplier from series metadata (OpenAPI ``Series.fee_multiplier``); 1.0 = table defaults.
    kalshi_fee_multiplier: float | None = Field(default=None, ge=0, le=10)
    min_contracts: int | None = Field(None, ge=1, le=10000)
    lab_a: dict[str, Any] | None = None
    lab_b: dict[str, Any] | None = None
    sim_lab: dict[str, Any] | None = None
    optimizer: dict[str, Any] | None = None

    def merged_into(self, current: dict[str, Any]) -> dict[str, Any]:
        out = dict(current)
        if self.simulate is not None:
            out["simulate"] = bool(self.simulate)
        if self.engine_running is not None:
            out["engine_running"] = bool(self.engine_running)
        if self.poll_seconds is not None:
            out["poll_seconds"] = float(self.poll_seconds)
        if self.balance_fraction_per_window is not None:
            out["balance_fraction_per_window"] = float(self.balance_fraction_per_window)
        if self.window_minutes is not None:
            out["window_minutes"] = int(self.window_minutes)
        if self.paper_balance_cents is not None:
            out["paper_balance_cents"] = int(self.paper_balance_cents)
        if self.only_yes_subtitle_contains is not None:
            out["only_yes_subtitle_contains"] = self.only_yes_subtitle_contains
        if self.exclude_yes_subtitle_contains is not None:
            out["exclude_yes_subtitle_contains"] = self.exclude_yes_subtitle_contains
        if "no_bet_when_yes_below_pct" in self.model_fields_set:
            v = self.no_bet_when_yes_below_pct
            out["no_bet_when_yes_below_pct"] = None if v is None else float(v)
        if "dev_sim_yes_implied_ge_pct" in self.model_fields_set:
            v = self.dev_sim_yes_implied_ge_pct
            out["dev_sim_yes_implied_ge_pct"] = None if v is None else float(v)
            # Legacy bool would still enable 70% bypass if left True
            out["dev_sim_yes_implied_ge_70"] = False
        if "swing_exit_implied_drop_pct" in self.model_fields_set:
            v = self.swing_exit_implied_drop_pct
            if v is None:
                out["swing_exit_implied_drop_pct"] = None
            else:
                fv = float(v)
                out["swing_exit_implied_drop_pct"] = None if fv <= 0 else fv
        if "paper_fee_bps" in self.model_fields_set:
            v = self.paper_fee_bps
            if v is None:
                out["paper_fee_bps"] = None
            else:
                fv = float(v)
                out["paper_fee_bps"] = None if fv <= 0 else fv
        if "paper_fee_model" in self.model_fields_set:
            if self.paper_fee_model is None:
                out["paper_fee_model"] = None
            else:
                out["paper_fee_model"] = normalize_paper_fee_model(self.paper_fee_model)
        if "kalshi_fee_multiplier" in self.model_fields_set:
            if self.kalshi_fee_multiplier is None:
                out["kalshi_fee_multiplier"] = None
            else:
                fv = float(self.kalshi_fee_multiplier)
                out["kalshi_fee_multiplier"] = None if fv <= 0 else min(10.0, fv)
        if self.min_contracts is not None:
            out["min_contracts"] = int(self.min_contracts)
        if self.assets:
            merged_assets = dict(out.get("assets") or {})
            for aid, acfg in self.assets.items():
                base = dict(merged_assets.get(aid) or {})
                patch = {kk: vv for kk, vv in acfg.model_dump().items() if vv is not None}
                merged_assets[aid] = {**base, **patch}
            out["assets"] = merged_assets
        if self.rules is not None:
            out["rules"] = [r.model_dump(exclude_none=True) for r in self.rules]
        if self.sim_lab is not None:
            cur = merge_lab_branch_patch(dict(out.get("lab_a") or out.get("sim_lab") or {}), self.sim_lab)
            out["lab_a"] = expand_partial_lab_branch("lab_a", cur)
            out["sim_lab"] = dict(out["lab_a"])
        if self.lab_a is not None:
            cur = merge_lab_branch_patch(dict(out.get("lab_a") or {}), self.lab_a)
            out["lab_a"] = expand_partial_lab_branch("lab_a", cur)
            out["sim_lab"] = dict(out["lab_a"])
        if self.lab_b is not None:
            cur = merge_lab_branch_patch(dict(out.get("lab_b") or {}), self.lab_b)
            out["lab_b"] = expand_partial_lab_branch("lab_b", cur)
        if self.optimizer is not None:
            cur = dict(out.get("optimizer") or {})
            for k, v in self.optimizer.items():
                if v is not None:
                    cur[k] = v
            out["optimizer"] = cur
        return out
