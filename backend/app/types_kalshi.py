"""PHASE 3: lightweight typed shapes for Kalshi REST/WS payloads.

These TypedDict/dataclass helpers keep runtime behavior unchanged while reducing
`Any` usage in hot-path modules (`kalshi_client`, `kalshi_ws`, engine helpers).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict


class OrderbookFP(TypedDict, total=False):
    yes_dollars: list[list[float]]
    no_dollars: list[list[float]]


class OrderbookPayload(TypedDict, total=False):
    orderbook_fp: OrderbookFP


class MarketRow(TypedDict, total=False):
    ticker: str
    status: str
    close_time: str
    yes_bid_dollars: str | float
    yes_ask_dollars: str | float
    no_bid_dollars: str | float
    no_ask_dollars: str | float
    orderbook: OrderbookFP
    orderbook_fp: OrderbookFP


class OpenMarketsResponse(TypedDict, total=False):
    markets: list[MarketRow]


class WsEnvelope(TypedDict, total=False):
    type: str
    msg: dict[str, object]


@dataclass(frozen=True)
class WsSubscription:
    """One WS subscribe command payload."""

    msg_id: int
    channels: list[str]
    market_tickers: list[str] | None = None

