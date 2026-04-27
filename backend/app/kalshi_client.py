from __future__ import annotations

import asyncio
import base64
import datetime as dt
import importlib
import random
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import httpx
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from .settings_env import env


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
        wait = min(55.0, 1.8 * (2**attempt) + random.uniform(0, 0.6))
    wait = min(120.0, max(0.5, wait))
    await asyncio.sleep(wait)


async def _backoff_sleep_after_transient_5xx(attempt: int) -> None:
    """Same formula as public GET retries for 502/503/504."""
    await asyncio.sleep(min(8.0, 0.4 * (2**attempt) + random.random()))


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


class KalshiClient:
    """Class-level caches: all ``TradingEngine`` instances + dashboard share one /markets + orderbook view per key."""

    _open_markets_cache: dict[str, tuple[float, Any]] = {}
    _orderbook_cache: dict[str, tuple[float, Any]] = {}
    # GET /markets/{ticker} — short TTL: five parallel MTM passes often repeat the same tickers.
    _single_market_cache: dict[str, tuple[float, Any]] = {}
    OPEN_MARKETS_CACHE_TTL = 10.0
    ORDERBOOK_CACHE_TTL = 10.0
    SINGLE_MARKET_CACHE_TTL_S = 2.5
    # Limit concurrent signed (private) calls across all engine instances + dashboard.
    _private_call_sem = asyncio.Semaphore(3)

    def __init__(self) -> None:
        self.base = env.base_rest_url.rstrip("/")
        self._key_id = env.kalshi_api_key_id
        self._pk: Any | None = None

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
        async with httpx.AsyncClient(timeout=30.0) as client:
            for attempt in range(8):
                r = await client.get(url, params=params)
                if r.status_code == 429:
                    if attempt >= 7:
                        r.raise_for_status()
                    await _backoff_sleep_after_429(r, attempt)
                    continue
                if r.status_code in (502, 503, 504):
                    if attempt >= 7:
                        r.raise_for_status()
                    await _backoff_sleep_after_transient_5xx(attempt)
                    continue
                r.raise_for_status()
                return r.json()
        raise RuntimeError("get_public: exhausted retries")

    async def get_market_json_by_ticker_cached(self, ticker: str) -> Any:
        """GET /markets/{ticker} (full market row) with a short in-process dedupe for dashboard MTM."""
        import time as _time

        tk = str(ticker or "").strip()
        if not tk:
            raise ValueError("ticker required")
        now = _time.monotonic()
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
        import time as _time

        key = f"{series_ticker}:{limit}"
        now = _time.monotonic()
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
        import time as _time

        key = ticker.strip()
        if not key:
            raise ValueError("ticker required")
        now = _time.monotonic()
        hit = KalshiClient._orderbook_cache.get(key)
        if hit and (now - hit[0]) < KalshiClient.ORDERBOOK_CACHE_TTL:
            return hit[1]
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
            async with httpx.AsyncClient(timeout=30.0) as client:
                for attempt in range(8):
                    headers = self._auth_headers("GET", path_with_query)
                    r = await client.get(url, headers=headers)
                    if r.status_code == 429:
                        if attempt >= 7:
                            r.raise_for_status()
                        await _backoff_sleep_after_429(r, attempt)
                        continue
                    if r.status_code in (502, 503, 504):
                        if attempt >= 7:
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
            async with httpx.AsyncClient(timeout=30.0) as client:
                for attempt in range(8):
                    headers = self._auth_headers("POST", path)
                    headers["Content-Type"] = "application/json"
                    r = await client.post(url, headers=headers, json=body)
                    try:
                        payload = r.json()
                    except Exception:
                        payload = {"raw": r.text}
                    if r.status_code == 429:
                        if attempt >= 7:
                            return r.status_code, payload
                        await _backoff_sleep_after_429(r, attempt)
                        continue
                    if r.status_code in (502, 503, 504):
                        if attempt >= 7:
                            return r.status_code, payload
                        await _backoff_sleep_after_transient_5xx(attempt)
                        continue
                    return r.status_code, payload
        raise RuntimeError("post_private: exhausted retries")
