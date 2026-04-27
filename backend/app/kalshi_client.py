from __future__ import annotations

import asyncio
import base64
import datetime as dt
import importlib
import random
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import httpx
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from .settings_env import env
from .types_kalshi import OpenMarketsResponse, OrderbookPayload


def _retry_after_seconds(headers: httpx.Headers) -> float | None:
    """Parse ``Retry-After`` as seconds (Kalshi may send this on 429)."""
    ra = headers.get("retry-after") or headers.get("Retry-After")
    if ra is None:
        return None
    try:
        v = float(str(ra).strip())
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def _rate_limit_reset_sleep(headers: httpx.Headers) -> float | None:
    """
    Best-effort sleep from vendor rate-limit headers (unix seconds or ms until reset).

    Checks common names; ignores parse errors.
    """
    now = dt.datetime.now(tz=dt.timezone.utc).timestamp()
    for key in (
        "x-ratelimit-reset",
        "x-ratelimit-reset-requests",
        "ratelimit-reset",
        "RateLimit-Reset",
    ):
        raw = headers.get(key)
        if not raw:
            continue
        s = str(raw).strip()
        try:
            ts = float(s)
        except (TypeError, ValueError):
            continue
        if ts > 1e12:
            ts = ts / 1000.0
        if ts > now + 3600 * 24 * 365:
            continue
        if ts > 1e9:
            delta = max(0.0, ts - now)
            return min(120.0, max(0.5, delta))
        if 0 < ts <= 600:
            return min(120.0, max(0.5, ts))
    return None


async def _backoff_sleep_after_429(r: httpx.Response, attempt: int) -> None:
    """429 backoff: Retry-After, then common rate-limit reset headers, else exponential + jitter."""
    wait = _retry_after_seconds(r.headers) or 0.0
    if wait <= 0:
        wait = _rate_limit_reset_sleep(r.headers) or 0.0
    if wait <= 0:
        wait = min(env.kalshi_429_backoff_cap_s, env.kalshi_429_backoff_base_s * (2**attempt) + random.uniform(0, env.kalshi_429_jitter_s))
    wait = min(120.0, max(0.5, wait))
    await asyncio.sleep(wait)


async def _backoff_sleep_after_transient_5xx(attempt: int) -> None:
    """Same formula as public GET retries for 502/503/504."""
    await asyncio.sleep(min(env.kalshi_5xx_backoff_cap_s, env.kalshi_5xx_backoff_base_s * (2**attempt) + random.random()))


def _private_key_pem_from_keyring() -> str | None:
    if not env.kalshi_use_keyring:
        return None
    try:
        keyring = importlib.import_module("keyring")
    except ImportError as e:
        raise RuntimeError("KALSHI_USE_KEYRING=1 but `keyring` is not installed. Run: pip install keyring") from e
    get_pw = getattr(keyring, "get_password", None)
    if not callable(get_pw):
        raise RuntimeError("keyring.get_password is not available")
    secret = get_pw(env.kalshi_keyring_service, env.kalshi_keyring_username)
    if not secret or not str(secret).strip():
        return None
    return str(secret).strip()


def _load_private_key() -> Any:
    if env.kalshi_private_key_pem:
        pem = env.kalshi_private_key_pem.replace("\\n", "\n").encode()
        return serialization.load_pem_private_key(pem, password=None, backend=default_backend())
    if env.kalshi_private_key_path:
        data = Path(env.kalshi_private_key_path).read_bytes()
        return serialization.load_pem_private_key(data, password=None, backend=default_backend())
    kr = _private_key_pem_from_keyring()
    if kr:
        pem = kr.replace("\\n", "\n").encode()
        return serialization.load_pem_private_key(pem, password=None, backend=default_backend())
    raise RuntimeError(
        "Set KALSHI_PRIVATE_KEY_PEM or KALSHI_PRIVATE_KEY_PATH, or KALSHI_USE_KEYRING=1 with keyring secret stored."
    )


def _sign(private_key: Any, timestamp_ms: str, method: str, sign_path: str) -> str:
    message = f"{timestamp_ms}{method.upper()}{sign_path}".encode("utf-8")
    sig = private_key.sign(
        message,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )
    return base64.b64encode(sig).decode("utf-8")


# Shared HTTP connection pool: one AsyncClient for the whole process (set from FastAPI lifespan).
_DEFAULT_HTTP_TIMEOUT = httpx.Timeout(env.kalshi_http_timeout_s, connect=env.kalshi_http_connect_timeout_s)
_DEFAULT_LIMITS = httpx.Limits(max_connections=env.kalshi_http_max_connections, max_keepalive_connections=env.kalshi_http_max_keepalive_connections)


def new_shared_http_client() -> httpx.AsyncClient:
    """Single process-wide pool; use from FastAPI lifespan and ``require_kalshi`` lazy path."""
    return httpx.AsyncClient(timeout=_DEFAULT_HTTP_TIMEOUT, limits=_DEFAULT_LIMITS, http2=False)


def series_tickers_from_full_config(full_cfg: dict[str, Any]) -> list[str]:
    """
    Union of ``series_ticker`` from global ``assets`` and each lab block so pre-warm matches all branches.
    """
    found: set[str] = set()
    blocks: list[dict[str, Any]] = [full_cfg]
    for k in ("lab_a", "lab_b", "lab_c", "lab_d"):
        b = full_cfg.get(k)
        if isinstance(b, dict):
            blocks.append(b)
    for block in blocks:
        for _aid, acfg in (block.get("assets") or {}).items():
            if not isinstance(acfg, dict):
                continue
            s = str(acfg.get("series_ticker") or "").strip()
            if s:
                found.add(s)
    return sorted(found)


class KalshiClient:
    """Class-level caches: all ``TradingEngine`` instances + dashboard share one /markets + orderbook view per key."""

    _open_markets_cache: dict[str, tuple[float, OpenMarketsResponse | dict[str, Any]]] = {}
    _orderbook_cache: dict[str, tuple[float, OrderbookPayload | dict[str, Any]]] = {}
    _single_market_cache: dict[str, tuple[float, dict[str, Any]]] = {}
    OPEN_MARKETS_CACHE_TTL: float = 10.0
    ORDERBOOK_CACHE_TTL: float = 10.0
    SINGLE_MARKET_CACHE_TTL_S: float = 2.5
    # After lifespan pre-warm, first engine ticks can short-circuit orderbook backfill a bit.
    prewarm_complete: bool = False
    _private_call_sem = asyncio.Semaphore(env.kalshi_private_call_concurrency)
    # PHASE 2: WebSocket bridge metrics (optional; see ``kalshi_ws``).
    ws_connected: bool = False
    ws_last_error: str | None = None
    ws_messages: int = 0
    ws_orderbook_cache_writes: int = 0
    ws_subscribe_tickers: list[str] = []
    # PHASE 2: lightweight observability for logs / GET /api/health/startup (REST path only; WS writes bypass miss).
    orderbook_cache_hits: int = 0
    orderbook_cache_misses: int = 0

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self.base = env.base_rest_url.rstrip("/")
        self._key_id = env.kalshi_api_key_id
        self._pk: Any | None = None
        self._http = http_client if http_client is not None else new_shared_http_client()
        self._own_http = http_client is None

    @classmethod
    def apply_cold_start_cache_ttls(cls, *, open_markets: float, orderbooks: float, single_market: float | None = None) -> None:
        """Widen TTLs for the first minutes after process start; call ``apply_steady_state_cache_ttls`` after pre-warm."""
        cls.OPEN_MARKETS_CACHE_TTL = max(5.0, open_markets)
        cls.ORDERBOOK_CACHE_TTL = max(5.0, orderbooks)
        if single_market is not None:
            cls.SINGLE_MARKET_CACHE_TTL_S = max(1.0, single_market)

    @classmethod
    def apply_steady_state_cache_ttls(
        cls,
        *,
        open_markets: float | None = None,
        orderbooks: float | None = None,
        single_market: float | None = None,
    ) -> None:
        """Restore defaults from env (or passed values) so steady state does not use cold TTL forever."""
        cls.OPEN_MARKETS_CACHE_TTL = open_markets if open_markets is not None else float(env.kalshi_open_markets_ttl_s)
        cls.ORDERBOOK_CACHE_TTL = orderbooks if orderbooks is not None else float(env.kalshi_orderbook_ttl_s)
        cls.SINGLE_MARKET_CACHE_TTL_S = single_market if single_market is not None else 2.5

    async def aclose(self) -> None:
        if self._own_http and self._http is not None:
            await self._http.aclose()

    def websocket_auth_headers(self) -> dict[str, str]:
        """# PHASE 2: Kalshi WS handshake (sign ``GET`` + ``/trade-api/ws/v2`` per vendor docs)."""
        if not self._key_id:
            raise RuntimeError("KALSHI_API_KEY_ID is not set.")
        if self._pk is None:
            self._pk = _load_private_key()
        ts = str(int(dt.datetime.now(tz=dt.timezone.utc).timestamp() * 1000))
        sign_path = "/trade-api/ws/v2"
        sig = _sign(self._pk, ts, "GET", sign_path)
        return {
            "KALSHI-ACCESS-KEY": self._key_id,
            "KALSHI-ACCESS-SIGNATURE": sig,
            "KALSHI-ACCESS-TIMESTAMP": ts,
        }

    @staticmethod
    def trade_ws_url_from_rest_base(rest_base: str) -> str:
        """# PHASE 2: ``https://…/trade-api/v2`` → ``wss://…/trade-api/ws/v2``."""
        b = str(rest_base or "").rstrip("/")
        if b.endswith("/trade-api/v2"):
            return b.replace("https://", "wss://").replace("http://", "ws://").replace("/trade-api/v2", "/trade-api/ws/v2")
        if "demo-api.kalshi.co" in b:
            return "wss://demo-api.kalshi.co/trade-api/ws/v2"
        return "wss://api.elections.kalshi.com/trade-api/ws/v2"

    @classmethod
    def seed_ws_market_tickers(cls, *, max_tickers: int) -> list[str]:
        """# PHASE 2: Build subscription list from pre-warmed ``/markets`` cache rows."""
        out: list[str] = []
        seen: set[str] = set()
        for _k, (_t, data) in list(cls._open_markets_cache.items()):
            if not isinstance(data, dict):
                continue
            for m in data.get("markets") or []:
                if len(out) >= max_tickers:
                    cls.ws_subscribe_tickers = list(out)
                    return list(out)
                if isinstance(m, dict):
                    t = str(m.get("ticker") or "").strip()
                    if t and t not in seen:
                        seen.add(t)
                        out.append(t)
        cls.ws_subscribe_tickers = list(out)
        return list(out)

    @classmethod
    def record_ws_orderbook_rest_shape(cls, ticker: str, orderbook_payload: OrderbookPayload | dict[str, Any]) -> None:
        """# PHASE 2: Push WS snapshot/delta-derived book into the same cache REST readers use."""
        tk = str(ticker or "").strip()
        if not tk or not isinstance(orderbook_payload, dict):
            return
        now = time.monotonic()
        cls._orderbook_cache[tk] = (now, orderbook_payload)
        cls.ws_orderbook_cache_writes += 1

    def _auth_headers(self, method: str, path_with_query: str) -> dict[str, str]:
        if not self._key_id:
            raise RuntimeError("KALSHI_API_KEY_ID is not set.")
        if self._pk is None:
            self._pk = _load_private_key()
        ts = str(int(dt.datetime.now(tz=dt.timezone.utc).timestamp() * 1000))
        sign_path = urlparse(self.base + path_with_query).path
        sig = _sign(self._pk, ts, method, sign_path)
        return {
            "KALSHI-ACCESS-KEY": self._key_id,
            "KALSHI-ACCESS-SIGNATURE": sig,
            "KALSHI-ACCESS-TIMESTAMP": ts,
        }

    async def get_public(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET with retries on 429 / transient 5xx (demo API is easy to rate-limit)."""
        url = self.base + path
        for attempt in range(env.kalshi_public_max_attempts):
            r = await self._http.get(url, params=params)
            if r.status_code == 429:
                if attempt >= env.kalshi_public_max_attempts - 1:
                    r.raise_for_status()
                await _backoff_sleep_after_429(r, attempt)
                continue
            if r.status_code in (502, 503, 504):
                if attempt >= env.kalshi_public_max_attempts - 1:
                    r.raise_for_status()
                await _backoff_sleep_after_transient_5xx(attempt)
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError("get_public: exhausted retries")

    async def get_market_json_by_ticker_cached(self, ticker: str) -> Any:
        """GET /markets/{ticker} (full market row) with a short in-process dedupe for dashboard MTM."""
        tk = str(ticker or "").strip()
        if not tk:
            raise ValueError("ticker required")
        now = time.monotonic()
        hit = KalshiClient._single_market_cache.get(tk)
        if hit and (now - hit[0]) < KalshiClient.SINGLE_MARKET_CACHE_TTL_S:
            return hit[1]
        path = f"/markets/{quote(tk, safe='')}"
        data = await self.get_public(path)
        KalshiClient._single_market_cache[tk] = (now, data)
        if len(KalshiClient._single_market_cache) > 400:
            for k in list(KalshiClient._single_market_cache.keys())[:200]:
                KalshiClient._single_market_cache.pop(k, None)
        return data

    async def get_open_markets_cached(
        self,
        series_ticker: str,
        *,
        limit: int = 80,
    ) -> Any:
        """GET /markets for one series; cached briefly across engine branches and pulse."""
        key = f"{series_ticker}:{limit}"
        now = time.monotonic()
        hit = KalshiClient._open_markets_cache.get(key)
        if hit and (now - hit[0]) < KalshiClient.OPEN_MARKETS_CACHE_TTL:
            return hit[1]
        data = await self.get_public(
            "/markets",
            {"series_ticker": series_ticker, "status": "open", "limit": str(limit)},
        )
        KalshiClient._open_markets_cache[key] = (now, data)
        return data

    async def get_market_orderbook_cached(self, ticker: str) -> Any:
        """GET /markets/{ticker}/orderbook — cached; public. Fills gaps when /markets list omits bid/ask."""
        key = ticker.strip()
        if not key:
            raise ValueError("ticker required")
        now = time.monotonic()
        hit = KalshiClient._orderbook_cache.get(key)
        if hit and (now - hit[0]) < KalshiClient.ORDERBOOK_CACHE_TTL:
            KalshiClient.orderbook_cache_hits += 1
            return hit[1]
        KalshiClient.orderbook_cache_misses += 1
        path = f"/markets/{quote(key, safe='')}/orderbook"
        data = await self.get_public(path, {"depth": "0"})
        KalshiClient._orderbook_cache[key] = (now, data)
        return data

    async def get_private(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Signed GET with the same 8-attempt 429 / transient-5xx pattern as ``get_public``."""
        q = httpx.QueryParams(params or {})
        path_with_query = path + (f"?{q}" if str(q) else "")
        url = self.base + path_with_query
        async with KalshiClient._private_call_sem:
            for attempt in range(env.kalshi_private_max_attempts):
                headers = self._auth_headers("GET", path_with_query)
                r = await self._http.get(url, headers=headers)
                if r.status_code == 429:
                    if attempt >= env.kalshi_private_max_attempts - 1:
                        r.raise_for_status()
                    await _backoff_sleep_after_429(r, attempt)
                    continue
                if r.status_code in (502, 503, 504):
                    if attempt >= env.kalshi_private_max_attempts - 1:
                        r.raise_for_status()
                    await _backoff_sleep_after_transient_5xx(attempt)
                    continue
                r.raise_for_status()
                return r.json()
        raise RuntimeError("get_private: exhausted retries")

    async def post_private(self, path: str, body: dict[str, Any]) -> tuple[int, Any]:
        """Signed POST: retries on 429 / 502–504 with the same backoff as public GET; then returns status + body."""
        url = self.base + path
        async with KalshiClient._private_call_sem:
            for attempt in range(env.kalshi_private_max_attempts):
                headers = self._auth_headers("POST", path)
                headers["Content-Type"] = "application/json"
                r = await self._http.post(url, headers=headers, json=body)
                try:
                    payload = r.json()
                except Exception:
                    payload = {"raw": r.text}
                if r.status_code == 429:
                    if attempt >= env.kalshi_private_max_attempts - 1:
                        return r.status_code, payload
                    await _backoff_sleep_after_429(r, attempt)
                    continue
                if r.status_code in (502, 503, 504):
                    if attempt >= env.kalshi_private_max_attempts - 1:
                        return r.status_code, payload
                    await _backoff_sleep_after_transient_5xx(attempt)
                    continue
                return r.status_code, payload
        raise RuntimeError("post_private: exhausted retries")


async def prewarm_open_markets_for_config(
    client: KalshiClient,
    full_cfg: dict[str, Any],
    *,
    max_concurrent: int = 4,
) -> None:
    """
    Seeded GET /markets per configured series (deduped) so the first engine loop tick hits cache, not 5× cold HTTP.
    """
    series = series_tickers_from_full_config(full_cfg)
    if not series:
        return
    # PHASE 3: env-backed default preserves prior behavior when caller passes explicit value.
    sem = asyncio.Semaphore(max(1, int(max_concurrent or env.prewarm_max_concurrent)))

    async def one(s: str) -> None:
        async with sem:
            try:
                await client.get_open_markets_cached(s, limit=100)
            except Exception:
                return

    await asyncio.gather(*[one(s) for s in series], return_exceptions=True)
    KalshiClient.prewarm_complete = True

