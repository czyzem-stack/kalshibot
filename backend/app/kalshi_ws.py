# PHASE 2: Optional Kalshi WebSocket session (orderbook + ticker). REST + in-memory cache remain authoritative fallback.

from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Any, Protocol

from .kalshi_client import KalshiClient
from .settings_env import env
from .types_kalshi import MarketRow, OrderbookPayload, WsEnvelope, WsSubscription

logger = logging.getLogger("kalshibot.kalshi_ws")


class _WsClientLike(Protocol):
    async def send(self, data: str) -> None: ...
    async def recv(self) -> str: ...


def _orderbook_dict_from_ws_msg(msg: MarketRow) -> OrderbookPayload | None:
    """
    Normalize WS ``orderbook_snapshot`` / ``orderbook_delta`` payloads toward REST ``/orderbook`` shape.

    Kalshi may send ``orderbook_fp`` or nested ``orderbook``; we only cache shapes ``orderbook_json_to_yes_bid_ask`` understands.
    """
    if not isinstance(msg, dict):
        return None
    if isinstance(msg.get("orderbook_fp"), dict):
        return {"orderbook_fp": msg["orderbook_fp"]}
    ob = msg.get("orderbook")
    if isinstance(ob, dict) and ("yes_dollars" in ob or "no_dollars" in ob):
        return {"orderbook_fp": ob}
    if "yes_dollars" in msg or "no_dollars" in msg:
        return {"orderbook_fp": msg}
    return None


async def _send_subscription(ws: _WsClientLike, sub: WsSubscription) -> None:
    payload: dict[str, Any] = {"id": sub.msg_id, "cmd": "subscribe", "params": {"channels": sub.channels}}
    if sub.market_tickers is not None:
        payload["params"]["market_tickers"] = sub.market_tickers
    await ws.send(json.dumps(payload))


async def _subscribe_orderbooks(ws: _WsClientLike, tickers: list[str], *, chunk: int, msg_id_start: int) -> int:
    mid = msg_id_start
    for i in range(0, len(tickers), chunk):
        part = tickers[i : i + chunk]
        if not part:
            continue
        await _send_subscription(ws, WsSubscription(msg_id=mid, channels=["orderbook_delta"], market_tickers=part))
        mid += 1
    return mid


async def _subscribe_ticker_all(ws: _WsClientLike, msg_id: int) -> None:
    await _send_subscription(ws, WsSubscription(msg_id=msg_id, channels=["ticker"]))


async def kalshi_ws_loop(client: KalshiClient, stop_event: asyncio.Event) -> None:
    """
    PHASE 2: Maintain authenticated WS; subscribe to ``ticker`` + ``orderbook_delta`` for pre-warmed markets.

    Reconnects with exponential backoff + jitter. Updates ``KalshiClient`` orderbook cache so
    ``get_market_orderbook_cached`` often avoids REST. Parsing failures are non-fatal (REST fallback).
    """
    try:
        import websockets
    except ImportError:
        logger.warning("kalshi_ws: websockets package missing; pip install websockets")
        return

    url = KalshiClient.trade_ws_url_from_rest_base(client.base)
    cap = float(env.kalshi_ws_reconnect_cap_s)
    chunk = int(env.kalshi_ws_subscribe_chunk)
    backoff = float(env.kalshi_ws_reconnect_base_s)

    while not stop_event.is_set():
        tickers = list(KalshiClient.ws_subscribe_tickers) or KalshiClient.seed_ws_market_tickers(max_tickers=int(env.kalshi_ws_max_markets))
        if not tickers:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=env.kalshi_ws_no_ticker_sleep_s)
            except TimeoutError:
                pass
            continue

        KalshiClient.ws_connected = False
        KalshiClient.ws_last_error = None
        try:
            headers = [(k, str(v)) for k, v in client.websocket_auth_headers().items()]
            async with websockets.connect(  # type: ignore[attr-defined]
                url,
                additional_headers=headers,
                ping_interval=env.kalshi_ws_ping_interval_s,
                ping_timeout=env.kalshi_ws_ping_timeout_s,
                close_timeout=env.kalshi_ws_close_timeout_s,
            ) as ws:
                KalshiClient.ws_connected = True
                backoff = float(env.kalshi_ws_reconnect_base_s)
                await _subscribe_ticker_all(ws, 1)
                await _subscribe_orderbooks(ws, tickers, chunk=chunk, msg_id_start=2)
                logger.info(
                    "kalshi_ws connected url=%s orderbook_markets=%s ticker_channel=1",
                    url,
                    len(tickers),
                )

                while not stop_event.is_set():
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=env.kalshi_ws_recv_timeout_s)
                    except TimeoutError:
                        continue
                    KalshiClient.ws_messages += 1
                    try:
                        data: WsEnvelope = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    mtype = data.get("type")
                    if mtype == "error":
                        err = data.get("msg") or {}
                        KalshiClient.ws_last_error = str(err)[:400]
                        logger.warning("kalshi_ws server error: %s", KalshiClient.ws_last_error)
                        break
                    if mtype not in ("orderbook_snapshot", "orderbook_delta", "ticker"):
                        continue
                    msg = data.get("msg")
                    if not isinstance(msg, dict):
                        continue
                    if mtype in ("orderbook_snapshot", "orderbook_delta"):
                        tk = str(msg.get("market_ticker") or msg.get("ticker") or "").strip()
                        ob = _orderbook_dict_from_ws_msg(msg)
                        if tk and ob:
                            KalshiClient.record_ws_orderbook_rest_shape(tk, ob)
                    # ticker: informational for now; could hydrate single-market cache later

        except asyncio.CancelledError:
            raise
        except Exception as e:
            KalshiClient.ws_connected = False
            KalshiClient.ws_last_error = str(e)[:400]
            logger.warning("kalshi_ws disconnect: %s", KalshiClient.ws_last_error)
        finally:
            KalshiClient.ws_connected = False

        if stop_event.is_set():
            break
        sleep_s = min(cap, backoff + random.uniform(0.0, env.kalshi_ws_reconnect_jitter_s))
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=sleep_s)
        except TimeoutError:
            pass
        backoff = min(cap, max(env.kalshi_ws_reconnect_base_s, backoff * env.kalshi_ws_reconnect_multiplier))


async def kalshi_ws_task_group_runner(client: KalshiClient, stop_event: asyncio.Event) -> None:
    """PHASE 2: Wrap the WS session in ``TaskGroup`` (single reader task; clean cancel on shutdown)."""
    async with asyncio.TaskGroup() as tg:
        tg.create_task(kalshi_ws_loop(client, stop_event))
