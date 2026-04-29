"""
Emergency diversify: temporarily tighten breeder (B/C/D/E) gates + optimizer yes floors,
then revert after ``emergency_diversify_revert_at``. Invoked from ``POST /labs/diversify``.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from .branch_config import BRANCH_BREEDERS
from .lab_communication import _voice_prefix, get_lab_communication_bus
from .optimizer_claude import force_internal_mutation_once

logger = logging.getLogger("kalshibot.api")

_DIVERSIFY_MINUTES = 45
_YES_FLOOR_BUMP = 5
_NO_BET_BUMP = 6
_YES_FLOOR_CAP = 58
_NO_BET_CAP = 46


def _parse_until_iso(raw: Any) -> dt.datetime | None:
    s = str(raw or "").strip()
    if not s:
        return None
    try:
        t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=dt.timezone.utc)
        return t
    except (TypeError, ValueError):
        return None


def _baseline_snapshot(cfg: dict[str, Any]) -> dict[str, Any]:
    oc = cfg.get("optimizer") if isinstance(cfg.get("optimizer"), dict) else {}
    labs: dict[str, Any] = {}
    for lk in BRANCH_BREEDERS:
        lab = cfg.get(lk) if isinstance(cfg.get(lk), dict) else {}
        labs[lk] = {"no_bet_when_yes_below_pct": lab.get("no_bet_when_yes_below_pct")}
    return {
        "lab_b_yes_floor_pct": oc.get("lab_b_yes_floor_pct"),
        "lab_c_yes_floor_pct": oc.get("lab_c_yes_floor_pct"),
        "lab_d_yes_floor_pct": oc.get("lab_d_yes_floor_pct"),
        "lab_e_yes_floor_pct": oc.get("lab_e_yes_floor_pct"),
        "labs": labs,
    }


def _apply_bumps(cfg: dict[str, Any]) -> None:
    oc = cfg.setdefault("optimizer", {})
    if not isinstance(oc, dict):
        cfg["optimizer"] = {}
        oc = cfg["optimizer"]
    keys = ("lab_b_yes_floor_pct", "lab_c_yes_floor_pct", "lab_d_yes_floor_pct", "lab_e_yes_floor_pct")
    for k in keys:
        try:
            cur = int(float(oc.get(k) or 50))
        except (TypeError, ValueError):
            cur = 50
        oc[k] = min(_YES_FLOOR_CAP, cur + _YES_FLOOR_BUMP)
    for lk in BRANCH_BREEDERS:
        lab = cfg.setdefault(lk, {})
        if not isinstance(lab, dict):
            cfg[lk] = {}
            lab = cfg[lk]
        try:
            nb = int(float(lab.get("no_bet_when_yes_below_pct") or 24))
        except (TypeError, ValueError):
            nb = 24
        lab["no_bet_when_yes_below_pct"] = min(_NO_BET_CAP, nb + _NO_BET_BUMP)


def _restore_from_baseline(cfg: dict[str, Any], base: dict[str, Any]) -> None:
    oc = cfg.setdefault("optimizer", {})
    if not isinstance(oc, dict):
        return
    for k in ("lab_b_yes_floor_pct", "lab_c_yes_floor_pct", "lab_d_yes_floor_pct", "lab_e_yes_floor_pct"):
        if k in base and base[k] is not None:
            oc[k] = base[k]
    labs = base.get("labs") if isinstance(base.get("labs"), dict) else {}
    for lk, patch in labs.items():
        if lk not in cfg or not isinstance(cfg.get(lk), dict):
            continue
        if isinstance(patch, dict) and patch.get("no_bet_when_yes_below_pct") is not None:
            cfg[lk]["no_bet_when_yes_below_pct"] = patch["no_bet_when_yes_below_pct"]
    oc.pop("emergency_diversify_revert_at", None)
    oc.pop("emergency_diversify_baseline", None)


async def maybe_revert_emergency_diversify_if_due(store: Any, cfg: dict[str, Any]) -> bool:
    """
    If ``emergency_diversify_revert_at`` has passed, restore baseline and persist.
    Called from ``Store.load_config`` so any API tick picks up expiry without a dedicated timer.
    """
    oc = cfg.get("optimizer") if isinstance(cfg.get("optimizer"), dict) else {}
    until = _parse_until_iso(oc.get("emergency_diversify_revert_at"))
    base = oc.get("emergency_diversify_baseline")
    if until is None or not isinstance(base, dict):
        return False
    now = dt.datetime.now(dt.timezone.utc)
    if now <= until:
        return False
    _restore_from_baseline(cfg, base)
    await store.save_config(
        cfg,
        history_branch="global",
        history_changed_by="system",
        history_reason="emergency_diversify_expired",
    )
    logger.info("emergency_diversify reverted after window")
    return True


async def apply_emergency_diversify(store: Any) -> dict[str, Any]:
    """Persist tighter breeder gates + floors; force one internal mutation; announce on Think Tank."""
    cfg = await store.load_config()
    oc = cfg.setdefault("optimizer", {})
    if not isinstance(oc, dict):
        cfg["optimizer"] = {}
        oc = cfg["optimizer"]

    now = dt.datetime.now(dt.timezone.utc)
    until_existing = _parse_until_iso(oc.get("emergency_diversify_revert_at"))
    if until_existing and now < until_existing:
        oc["emergency_diversify_revert_at"] = (now + dt.timedelta(minutes=_DIVERSIFY_MINUTES)).isoformat()
        await store.save_config(
            cfg,
            history_branch="global",
            history_changed_by="api:labs_diversify",
            history_reason="emergency_diversify_extend",
        )
        mut = await force_internal_mutation_once(store)
        bus = get_lab_communication_bus()
        banner = "DIVERSIFY EXTENDED—council keep diverging"
        for br in BRANCH_BREEDERS:
            bus.publish(br, f"{_voice_prefix(br)} {banner}", kind="say", action="emergency_diversify")
        return {"ok": True, "extended": True, "revert_at": str(oc.get("emergency_diversify_revert_at") or ""), "internal_mutation": mut}
    else:
        oc["emergency_diversify_baseline"] = _baseline_snapshot(cfg)
        _apply_bumps(cfg)
        oc["emergency_diversify_revert_at"] = (now + dt.timedelta(minutes=_DIVERSIFY_MINUTES)).isoformat()
        await store.save_config(
            cfg,
            history_branch="global",
            history_changed_by="api:labs_diversify",
            history_reason="emergency_diversify_apply",
        )

    bus = get_lab_communication_bus()
    banner = "DIVERSIFY TRIGGERED—B/C/D/E diverge 45m"

    for br in BRANCH_BREEDERS:
        vp = _voice_prefix(br)
        bus.publish(br, f"{vp} {banner}", kind="say", action="emergency_diversify")

    mut = await force_internal_mutation_once(store)
    return {
        "ok": True,
        "revert_at": str(oc.get("emergency_diversify_revert_at") or ""),
        "internal_mutation": mut,
    }
