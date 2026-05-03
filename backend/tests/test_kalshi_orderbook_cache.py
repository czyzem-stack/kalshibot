"""Orderbook in-process cache: WS must not pin empty books over REST."""

from __future__ import annotations

import os
import sys
import time
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app.kalshi_client import (  # noqa: E402
    KalshiClient,
    _orderbook_payload_yes_bid_ask,
)


class KalshiOrderbookCacheTest(unittest.TestCase):
    def test_empty_ladder_yields_no_quotes(self) -> None:
        self.assertEqual(
            _orderbook_payload_yes_bid_ask(
                {"orderbook_fp": {"yes_dollars": [], "no_dollars": []}}
            ),
            (None, None),
        )

    def test_record_ws_skips_empty_payload(self) -> None:
        tk = "KXTEST-EMPTY-WS-CACHE"
        KalshiClient._orderbook_cache.pop(tk, None)
        KalshiClient.record_ws_orderbook_rest_shape(
            tk, {"orderbook_fp": {"yes_dollars": [], "no_dollars": []}}
        )
        self.assertNotIn(tk, KalshiClient._orderbook_cache)

    def test_cache_hit_ttl_short_when_no_quotes(self) -> None:
        """Empty-book entries expire quickly so REST can refill."""
        tk = "KXTEST-EMPTY-TTL"
        KalshiClient._orderbook_cache.pop(tk, None)
        KalshiClient._orderbook_cache[tk] = (
            time.monotonic() - 10.0,
            {"orderbook_fp": {"yes_dollars": [], "no_dollars": []}},
        )
        KalshiClient.ORDERBOOK_CACHE_TTL = 60.0
        age = time.monotonic() - KalshiClient._orderbook_cache[tk][0]
        prev = KalshiClient._orderbook_cache[tk][1]
        yb, ya = _orderbook_payload_yes_bid_ask(prev)
        eff = 60.0
        if yb is None and ya is None:
            eff = min(2.0, max(0.5, eff * 0.2))
        self.assertEqual(eff, 2.0)
        self.assertGreater(age, eff, "stale empty book should exceed short TTL")

