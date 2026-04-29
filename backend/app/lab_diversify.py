"""
Council diversity pulse: ``POST /labs/diversify`` sets ``labs_council_diversity_until`` so the
Think Tank runs hotter adversarial / rotation mix for ~45 minutes. No internal mutation and no
gate bumps (distinct from ``force`` internal mutation).

Legacy ``emergency_diversify_*`` keys are still reverted by expiry for older configs.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from .branch_config import BRANCH_BREEDERS
from .lab_communication import _voice_prefix, get_lab_communication_bus

logger = logging.getLogger("kalshibot.api")

_DIVERSIFY_MINUTES = 45
_COUNCIL_DIVERSITY_KEY = "labs_council_diversity_until"

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


def _restore_legacy_from_baseline(cfg: dict[str, Any], base: dict[str, Any]) -> None:
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
    Legacy gate-bump window (pre–council-only diversify). Restore baseline when expired.
    """
    oc = cfg.get("optimizer") if isinstance(cfg.get("optimizer"), dict) else {}
    until = _parse_until_iso(oc.get("emergency_diversify_revert_at"))
    base = oc.get("emergency_diversify_baseline")
    if until is None or not isinstance(base, dict):
        return False
    now = dt.datetime.now(dt.timezone.utc)
    if now <= until:
        return False
    _restore_legacy_from_baseline(cfg, base)
    await store.save_config(
        cfg,
        history_branch="global",
        history_changed_by="system",
        history_reason="emergency_diversify_expired",
    )
    logger.info("legacy emergency_diversify gates reverted after window")
    return True


async def maybe_revert_council_diversity_if_due(store: Any, cfg: dict[str, Any]) -> bool:
    """Clear ``labs_council_diversity_until`` when the pulse window has ended."""
    oc = cfg.get("optimizer") if isinstance(cfg.get("optimizer"), dict) else {}
    until = _parse_until_iso(oc.get(_COUNCIL_DIVERSITY_KEY))
    if until is None:
        return False
    now = dt.datetime.now(dt.timezone.utc)
    if now <= until:
        return False
    oc2 = cfg.setdefault("optimizer", {})
    if isinstance(oc2, dict):
        oc2.pop(_COUNCIL_DIVERSITY_KEY, None)
    await store.save_config(
        cfg,
        history_branch="global",
        history_changed_by="system",
        history_reason="council_diversity_pulse_expired",
    )
    logger.info("council diversity pulse window ended")
    return True


async def apply_emergency_diversify(store: Any) -> dict[str, Any]:
    """
    Council diversity pulse only: extends adversarial Think Tank mix for ~45m, posts DIVERSITY PULSE lines.
    Does **not** run internal mutation (use ``force`` for that) and does **not** change breeder gates.
    """
    cfg = await store.load_config()
    oc = cfg.setdefault("optimizer", {})
    if not isinstance(oc, dict):
        cfg["optimizer"] = {}
        oc = cfg["optimizer"]

    now = dt.datetime.now(dt.timezone.utc)
    until_new = (now + dt.timedelta(minutes=_DIVERSIFY_MINUTES)).isoformat()
    until_existing = _parse_until_iso(oc.get(_COUNCIL_DIVERSITY_KEY))
    extended = bool(until_existing and now < until_existing)
    oc[_COUNCIL_DIVERSITY_KEY] = until_new

    await store.save_config(
        cfg,
        history_branch="global",
        history_changed_by="api:labs_diversify",
        history_reason="council_diversity_pulse_extend" if extended else "council_diversity_pulse_apply",
    )

    bus = get_lab_communication_bus()
    banners = [
        "DIVERSITY PULSE 45m—split the pile",
        "DIVERSITY PULSE—talk your book",
        "DIVERSITY PULSE—no groupthink",
        "DIVERSITY PULSE—oppose default",
    ]
    for i, br in enumerate(BRANCH_BREEDERS):
        vp = _voice_prefix(br)
        line = f"{vp} {banners[i % len(banners)]}"
        if len(line) > 69:
            line = line[:69].rsplit(" ", 1)[0]
        bus.publish(br, line, kind="say", action="council_diversity_pulse")

    return {
        "ok": True,
        "extended": extended,
        "council_diversity_until": str(oc.get(_COUNCIL_DIVERSITY_KEY) or ""),
        "internal_mutation": None,
    }
