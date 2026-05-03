"""Guards on implied YES used for open-sim MTM marks (feed glitches → chart spikes)."""

import pytest

from app.engines.engine import implied_yes_for_open_sim_marks


def test_wide_yes_spread_returns_none():
    m = {"yes_bid_dollars": "0.05", "yes_ask_dollars": "0.95"}
    assert implied_yes_for_open_sim_marks(m) is None


def test_crossed_yes_book_returns_none():
    m = {"yes_bid_dollars": "0.60", "yes_ask_dollars": "0.55"}
    assert implied_yes_for_open_sim_marks(m) is None


def test_ask_only_near_par_returns_none():
    m = {"yes_ask_dollars": "0.999", "yes_bid_dollars": None}
    assert implied_yes_for_open_sim_marks(m) is None


def test_tight_two_sided_book_returns_mid():
    m = {"yes_bid_dollars": "0.44", "yes_ask_dollars": "0.48"}
    assert implied_yes_for_open_sim_marks(m) == pytest.approx(0.46)


def test_last_price_extreme_returns_none():
    m = {"last_price_dollars": "0.9995"}
    assert implied_yes_for_open_sim_marks(m) is None


def test_lone_no_ask_without_yes_returns_none():
    """Tiny stub NO ask with no YES book ⇒ do not infer YES ≈ 1 (chart MTM spike)."""
    m = {"no_ask_dollars": "0.02", "yes_bid_dollars": None, "yes_ask_dollars": None}
    assert implied_yes_for_open_sim_marks(m) is None


def test_two_sided_no_without_yes_quotes_still_marks():
    m = {
        "no_ask_dollars": "0.52",
        "no_bid_dollars": "0.48",
        "yes_bid_dollars": None,
        "yes_ask_dollars": None,
    }
    assert implied_yes_for_open_sim_marks(m) == pytest.approx(0.50)
