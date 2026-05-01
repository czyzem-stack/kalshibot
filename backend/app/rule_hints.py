from __future__ import annotations

import math
from typing import Any


def _gather_probs_mins(
    snapshots: dict[str, Any] | None,
) -> tuple[list[float], list[float]]:
    probs: list[float] = []
    mins: list[float] = []
    if not isinstance(snapshots, dict):
        return probs, mins
    for v in snapshots.values():
        if not isinstance(v, dict) or not v.get("ok"):
            continue
        p = v.get("implied_prob")
        if p is not None and math.isfinite(float(p)):
            probs.append(float(p))
        ml = v.get("minutes_left")
        if ml is not None and math.isfinite(float(ml)):
            mins.append(float(ml))
    return probs, mins


def rule_suggestions_from_snapshots(
    snaps_live: dict[str, Any] | None,
    *snaps_labs: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Heuristic band ideas from recent engine snapshots (not ML / not financial advice).
    Widen or shift bands when observed implied YES sits outside typical defaults.
    """
    probs, mins = _gather_probs_mins(snaps_live)
    for sl in snaps_labs:
        p2, m2 = _gather_probs_mins(sl)
        probs.extend(p2)
        mins.extend(m2)

    if len(probs) < 1:
        return {
            "note": "No priced engine snapshots yet. Turn engines on and wait for a tick without 429 errors.",
            "presets": _default_presets(),
        }

    lo, hi = min(probs), max(probs)
    mid = (lo + hi) / 2.0
    span = max(0.08, min(0.35, (hi - lo) / 2.0 + 0.06))
    m_lo = min(mins) if mins else 4.0
    m_hi = max(mins) if mins else 14.0
    m_pad = max(1.0, (m_hi - m_lo) * 0.25 + 1.0)
    band_mins_lo = max(0.5, m_lo - m_pad)
    band_mins_hi = min(20.0, m_hi + m_pad)

    dynamic = {
        "name": f"Snapshot-centered ~{mid:.0%}",
        "min_prob": round(max(0.01, mid - span), 3),
        "max_prob": round(min(0.99, mid + span), 3),
        "min_minutes_left": round(band_mins_lo, 1),
        "max_minutes_left": round(band_mins_hi, 1),
    }

    return {
        "note": f"Observed implied YES across assets (last ticks): ~{lo:.0%}–{hi:.0%}. "
        f"Below are presets plus one band auto-centered on that range.",
        "observed_prob_min": round(lo, 4),
        "observed_prob_max": round(hi, 4),
        "presets": _default_presets(),
        "dynamic_band": dynamic,
    }


def _default_presets() -> list[dict[str, Any]]:
    return [
        {
            "id": "tight_mid",
            "label": "Tight mid (crypto chop)",
            "rules": [
                {
                    "name": "Mid 48–55%, 3–12m",
                    "min_prob": 0.48,
                    "max_prob": 0.55,
                    "min_minutes_left": 3.0,
                    "max_minutes_left": 12.0,
                },
                {
                    "name": "High conv 72–82%, 2–8m",
                    "min_prob": 0.72,
                    "max_prob": 0.82,
                    "min_minutes_left": 2.0,
                    "max_minutes_left": 8.0,
                },
                {
                    "name": "Very high 88–97%, 2–10m",
                    "min_prob": 0.88,
                    "max_prob": 0.97,
                    "min_minutes_left": 2.0,
                    "max_minutes_left": 10.0,
                },
            ],
        },
        {
            "id": "wide_mid",
            "label": "Wide mid (catch more)",
            "rules": [
                {
                    "name": "Wide mid 40–60%, 2–14m",
                    "min_prob": 0.4,
                    "max_prob": 0.6,
                    "min_minutes_left": 2.0,
                    "max_minutes_left": 14.0,
                },
                {
                    "name": "High 65–85%, 2–12m",
                    "min_prob": 0.65,
                    "max_prob": 0.85,
                    "min_minutes_left": 2.0,
                    "max_minutes_left": 12.0,
                },
                {
                    "name": "Extreme 90–99%, 1–8m",
                    "min_prob": 0.9,
                    "max_prob": 0.99,
                    "min_minutes_left": 1.0,
                    "max_minutes_left": 8.0,
                },
            ],
        },
    ]
