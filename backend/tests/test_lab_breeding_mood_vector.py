"""Breeder personality radar: mood spokes must react to lab knobs for child genomes, not traits alone."""

from __future__ import annotations

import copy

from app.lab_breeding import mood_vector_for_lab


def _base_child() -> dict:
    return {
        "balance_fraction_per_window": 0.09,
        "window_minutes": 12,
        "min_hold_minutes_before_stop": 22,
        "stop_loss_trigger_pct": -9.0,
        "rules": [],
        "_labs_breeding_traits": {
            "aggressiveness": 0.88,
            "risk_tolerance": 0.9,
            "adaptivity": 0.9,
            "exploration": 0.9,
            "resilience": 0.9,
        },
    }


def test_mood_bottom_spokes_shift_with_window_not_only_traits() -> None:
    base_rules: list = []
    a = mood_vector_for_lab(copy.deepcopy(_base_child()), base_rules=base_rules)
    b_lab = copy.deepcopy(_base_child())
    b_lab["window_minutes"] = 45
    b = mood_vector_for_lab(b_lab, base_rules=base_rules)
    assert a["adaptive"] != b["adaptive"], "adaptive should incorporate window_minutes (wm_u)"
    c_lab = copy.deepcopy(_base_child())
    c_lab["min_hold_minutes_before_stop"] = 90
    c = mood_vector_for_lab(c_lab, base_rules=base_rules)
    assert a["exploratory"] != c["exploratory"], "exploratory should incorporate min_hold (mh_u)"


def test_mood_resilient_moves_with_stop_tightness() -> None:
    base_rules: list = []
    a = mood_vector_for_lab(copy.deepcopy(_base_child()), base_rules=base_rules)
    b_lab = copy.deepcopy(_base_child())
    b_lab["stop_loss_trigger_pct"] = -28.0
    b = mood_vector_for_lab(b_lab, base_rules=base_rules)
    assert a["resilient"] != b["resilient"], "resilient should reflect stop_loss_trigger_pct (stp_n)"


def test_mood_all_twelve_keys_present_for_empty_child_stub() -> None:
    """Unassigned / thin slots still return a full vector (defaults + knobs)."""
    m = mood_vector_for_lab({}, base_rules=[])
    for k in (
        "aggressive",
        "greedy",
        "sophisticated",
        "patient",
        "calm",
        "adaptive",
        "exploratory",
        "resilient",
        "optimistic",
        "cautious",
        "ruthless",
        "methodical",
    ):
        assert k in m
        assert 0.0 <= float(m[k]) <= 100.0
