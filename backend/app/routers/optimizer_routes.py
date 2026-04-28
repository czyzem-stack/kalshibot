"""Optimizer read/write endpoints (internal pulse / mutations run in the backend)."""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from fastapi import APIRouter, Query

from ..lab_breeding import LABS_BREEDING_VERSION, build_labs_breeding_personality_radar, build_labs_breeding_tree_snapshot
from ..optimizer_claude import force_internal_mutation_once, run_optimizer_once
from .. import state
from ..types_api import OptimizerStatusResponse

router = APIRouter(prefix="/api/optimizer", tags=["optimizer"])
logger = logging.getLogger("kalshibot.api")


@router.get("/recommendations")
async def optimizer_recommendations(limit: int = Query(30, ge=1, le=200)) -> dict[str, Any]:
    cfg = await state.store.load_config()
    rows = await state.store.recent_optimizer_recommendations(limit=limit)
    return {"config": cfg.get("optimizer") or {}, "rows": rows}


@router.put("/config")
async def optimizer_config(body: dict[str, Any]) -> dict[str, Any]:
    cfg = await state.store.load_config()
    cur = cfg.get("optimizer") if isinstance(cfg.get("optimizer"), dict) else {}
    nxt = dict(cur)
    for k in (
        "enabled",
        "interval_minutes",
        "lookback_hours",
        "max_rows_per_table",
        "model",
        "adaptive_enabled",
        "mode",
        "lab_a_enabled",
        "lab_b_enabled",
        "lab_c_enabled",
        "lab_d_enabled",
        "lab_e_enabled",
        "lab_a_style",
        "lab_b_style",
        "lab_c_style",
        "lab_d_style",
        "lab_e_style",
        "loss_streak_trigger",
        "threshold_step_pct",
        "minute_step",
        "max_history",
        "lab_a_yes_floor_pct",
        "lab_b_yes_floor_pct",
        "lab_a_min_minutes_left",
        "lab_b_min_minutes_left",
        "lab_c_yes_floor_pct",
        "lab_c_min_minutes_left",
        "lab_d_yes_floor_pct",
        "lab_d_min_minutes_left",
        "lab_e_yes_floor_pct",
        "lab_e_min_minutes_left",
        "min_trades_for_optimize",
        "min_profitable_trades",
        "regime_lookback_hours",
        "optimize_bet_size",
        "include_fees_in_score",
        "backtest_proposals",
        "adaptive_skip_backtest_gate",
        "optimize_internal_mutations",
    ):
        if k in body:
            v = body[k]
            if k in (
                "max_rows_per_table",
                "max_history",
                "min_trades_for_optimize",
                "min_profitable_trades",
            ) and v is not None:
                try:
                    nxt[k] = int(v)
                except (TypeError, ValueError):
                    nxt[k] = v
            elif k == "lookback_hours" and v is not None:
                try:
                    nxt[k] = max(1, min(24 * 30, int(float(v))))
                except (TypeError, ValueError):
                    nxt[k] = v
            elif k == "regime_lookback_hours" and v is not None:
                try:
                    nxt[k] = max(1, min(168, int(float(v))))
                except (TypeError, ValueError):
                    nxt[k] = v
            elif k == "interval_minutes" and v is not None:
                try:
                    nxt[k] = max(5, min(24 * 60, int(float(v))))
                except (TypeError, ValueError):
                    nxt[k] = v
            elif k in (
                "optimize_bet_size",
                "include_fees_in_score",
                "backtest_proposals",
                "adaptive_skip_backtest_gate",
                "optimize_internal_mutations",
                "breeding_enabled",
            ):
                nxt[k] = bool(v)
            else:
                nxt[k] = v
    nxt.pop("max_bet_fraction", None)
    cfg["optimizer"] = nxt
    await state.store.save_config(
        cfg,
        history_branch="global",
        history_changed_by="api:put_optimizer",
        history_reason="optimizer_settings_patch",
    )
    return {"ok": True, "optimizer": nxt}


@router.post("/run")
async def optimizer_run() -> dict[str, Any]:
    return await run_optimizer_once(state.store, force=True)


@router.post("/force-internal-mutation")
async def optimizer_force_internal_mutation() -> dict[str, Any]:
    """Force one internal mutant cycle (bypasses scheduler cadence)."""
    logger.info("forced internal mutation requested via API")
    return await force_internal_mutation_once(state.store)


def _breeding_minutes_ago(iso_s: str) -> float | None:
    s = str(iso_s or "").strip()
    if not s:
        return None
    try:
        t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=dt.timezone.utc)
        return max(0.0, (dt.datetime.now(tz=dt.timezone.utc) - t).total_seconds() / 60.0)
    except (TypeError, ValueError):
        return None


def _labs_breeding_child_status_row(c: dict) -> dict:
    """Trim child payloads for ``GET /api/optimizer/status`` (full genomes stay in persisted config)."""
    lab = c.get("lab") if isinstance(c.get("lab"), dict) else {}
    return {
        "id": c.get("id"),
        "parent": c.get("parent"),
        "born_at": c.get("born_at"),
        "replay_fitness": c.get("replay_fitness"),
        "traits": c.get("traits") if isinstance(c.get("traits"), dict) else {},
        "rules_n": len(lab.get("rules") or []) if isinstance(lab.get("rules"), list) else 0,
        "balance_fraction_per_window": lab.get("balance_fraction_per_window"),
        "window_minutes": lab.get("window_minutes"),
        "paper_balance_cents": lab.get("paper_balance_cents"),
    }


@router.get("/status")
async def optimizer_status() -> OptimizerStatusResponse:
    # OPTIMIZER — keep smart core, remove visible settings per user request (advanced users only).
    # HELP CLEANUP — thorough & professional: status payload is the read-only observability surface (includes compact internal logs).
    cfg = await state.store.load_config()
    oc = cfg.get("optimizer") if isinstance(cfg.get("optimizer"), dict) else {}
    _bla = str(oc.get("breeding_last_run_at") or "").strip()
    return {
        "enabled": bool(oc.get("enabled")),
        "adaptive_enabled": bool(oc.get("adaptive_enabled", True)),
        "breeding_enabled": bool(oc.get("breeding_enabled", True)),
        "breeding_last_run_at": str(oc.get("breeding_last_run_at") or ""),
        "breeding_last_summary": str(oc.get("breeding_last_summary") or ""),
        "breeding_last_run_minutes_ago": _breeding_minutes_ago(_bla),
        "model": str(oc.get("model") or "internal"),
        "optimizer_cycle_count": int(oc.get("optimizer_cycle_count") or 0),
        "pulse_eval_count": int(oc.get("pulse_eval_count") or 0),
        "last_run_at": str(oc.get("last_run_at") or ""),
        "last_status": str(oc.get("last_status") or ""),
        "last_error": str(oc.get("last_error") or ""),
        "next_tick_preview": str(oc.get("next_tick_preview") or "")[:1200],
        "proposal_history": [x for x in (oc.get("proposal_history") or []) if isinstance(x, dict)][:50],
        # LABS BREEDING — fully automatic, invisible, continuous replacement (4 active slots only)
        "labs_breeding_log": [x for x in (oc.get("labs_breeding_log") or []) if isinstance(x, dict)][:64],
        "labs_breeding_children": [
            _labs_breeding_child_status_row(x) for x in (oc.get("labs_breeding_children") or []) if isinstance(x, dict)
        ][:10],
        "labs_breeding_death_chamber": [x for x in (oc.get("labs_breeding_death_chamber") or []) if isinstance(x, dict)][:10],
        "labs_breeding_lineage_history": [x for x in (oc.get("labs_breeding_lineage_history") or []) if isinstance(x, dict)][:10],
        "labs_breeding_tree_snapshot": build_labs_breeding_tree_snapshot(oc, cfg),
        "labs_breeding_version": LABS_BREEDING_VERSION,
        # LABS BREEDING — radar chart + Optimizer/Breeder toggle (Settings > Optimizer > Breeder).
        "labs_breeding_personality_radar": build_labs_breeding_personality_radar(cfg),
        "labs_breeding_last_generation_iso": str(oc.get("labs_breeding_last_generation_iso") or ""),
        "labs_breeding_replace_cooldown_until": str(oc.get("labs_breeding_replace_cooldown_until") or ""),
        "internal_optimizer_trace": [x for x in (oc.get("internal_optimizer_trace") or []) if isinstance(x, dict)][:30],
        "advanced_metrics_last": dict(oc.get("advanced_metrics_last") or {}),
        "acceptance_rate_pct": float(oc.get("acceptance_rate_pct") or 0.0),
    }
