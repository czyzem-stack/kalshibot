# Startup performance (API)

## Goals

- Avoid creating five `TradingEngine` instances and five implicit HTTP stacks at **import** time.
- Use **one** shared `httpx.AsyncClient` for all Kalshi REST calls (no per-request `AsyncClient()`).
- **Pre-warm** the in-process `/markets` cache once from config so the first `dual_engine_loop` tick is mostly cache hits.
- Widen in-memory TTLs for a short **cold-start window**, then restore steady defaults from `KALSHI_OPEN_MARKETS_TTL_S` / `KALSHI_ORDERBOOK_TTL_S`.

## Phase 2 (WebSocket + startup gate)

- **`state.startup_complete`**: cleared at lifespan entry, **set** only after `prewarm_open_markets_for_config` and `KalshiClient.seed_ws_market_tickers`. `dual_engine_loop` **awaits** this event before its first iteration so ticks never run ahead of the shared `/markets` cache.
- **Optional Kalshi WebSocket** (`KALSHI_WS_ENABLED=1`): authenticated `wss://…/trade-api/ws/v2` with `ticker` + `orderbook_delta` subscriptions; snapshots/deltas update the same in-memory orderbook cache REST readers use, so many `get_market_orderbook_cached` calls avoid HTTP while the socket is healthy.
- **Parallel per-branch settle/swing/timeout** inside `dual_engine_loop` (`asyncio.gather`) to shorten tick wall time.
- **Telemetry**: `GET /api/health/startup` exposes `startup_complete`, WS flags, and orderbook cache hit/miss counters; periodic tick logs when `KALSHI_LOG_TICK_INTERVAL_S` is greater than 0.

## Phase 3 (maintainability + typed tuning surface)

- **PHASE 3:** constants that were still hardcoded in HTTP/WS/startup loops are now env-backed in `EnvSettings` (timeouts, retry counts, WS ping/reconnect, prewarm concurrency, dashboard cache TTL, etc.) with defaults matching previous behavior.
- **PHASE 3:** Kalshi payload typing uses lightweight `TypedDict`/`dataclass` models in `backend/app/types_kalshi.py` to reduce `Any` usage in REST/WS paths without runtime overhead.
- **PHASE 3:** no startup flow changes; strict prewarm barrier + optional WS task sequence remains intact from Phase 2.

## Phase 3.1 (typed API contracts, no runtime changes)

- **PHASE 3.1:** dashboard/health response contracts are captured as `TypedDict` models (`backend/app/types_api.py`) and used as route return annotations.
- **PHASE 3.1:** this pass is type-safety only; no startup/tick behavior or performance logic changed.

## Phase FINAL (all-in-one consistency pass)

- **PHASE FINAL:** `TradingEngine` now clearly prefers injected shared `KalshiClient`; fallback construction remains for backward safety and emits a warning.
- **PHASE FINAL:** health routes and dashboard-family routes use typed response contracts (`types_api.py`) while preserving identical JSON output.
- **PHASE FINAL:** remaining engine/loop fallback literals are env-backed via typed `EnvSettings` defaults (`DEFAULT_*`) so behavior stays identical but tuning/maintenance is centralized.

## How to measure

Set:

```bash
KALSHI_PROFILE_STARTUP=1
```

Restart the API. Logs from `kalshibot.api` include:

- `kalshibot_startup phase=... total_ms=...` for phases: `http_client_and_cold_ttls`, `trading_engines`, `prewarm_open_markets`, **`startup_complete`**, optional **`kalshi_ws_task`**, and `kalshibot_startup_ready` for end-to-end time before request handling.

**Before/after** numbers depend on machine, Kalshi rate limits, asset count, and network; use the same host and config when comparing.

### Illustrative ranges (not guarantees)

| Stage | Phase 1 (typical laptop, demo) | Phase 2 (same + WS enabled after warm) |
|--------|--------------------------------|----------------------------------------|
| Through `prewarm_open_markets` | Often **~2–6 s** extra after pool + engines | Same baseline |
| First engine tick | Mostly cache hits on `/markets` | Fewer REST orderbook calls when WS feeds the cache |
| Steady tick | Dominated by rule scan + SQLite | Shorter wall time when orderbook rows are cache-fed |

### Fill in your final numbers (Phase 1 -> 2 -> 3)

Measured on 2026-04-26 with Python 3.13 (`KALSHI_PROFILE_STARTUP=1`; latest sampled run also used `KALSHI_LOG_TICK_INTERVAL_S=1`).

<!-- # PHASE FINAL.2 -->
| Metric (seconds) | Phase 1 (s) | Phase 2 (s) | Phase 3 (s) | FINAL (s) |
|--------|---------|---------|---------|-------|
| Startup ready (`kalshibot_startup_ready`) | 60.0 s | 2.7 s | 6.8 s | 6.8 s |
| Through prewarm (`prewarm_open_markets`) | 60.0 s | 2.7 s | 6.8 s | 6.8 s |
| Median `dual_engine_tick_ms` (steady) | — (not yet measured) | — (not yet measured) | 4.7 s | 4.7 s |
| Orderbook cache hit % (steady) | — (not yet measured) | — (not yet measured) | 88.9% | 88.9% |

WS-enabled runs show significantly higher cache hit rates in steady state.

Use `KALSHI_LOG_TICK_INTERVAL_S=30` to log `dual_engine_tick_ms` and `ob_cache_hit_pct` without spamming.

## Relevant environment variables

| Variable | Default | Role |
|----------|---------|------|
| `KALSHI_PROFILE_STARTUP` | `0` | Enable phase timing logs. |
| `KALSHI_COLD_START_CACHE_TTL_S` | `90` | Longer `/markets` and orderbook in-memory TTL for the first several seconds. |
| `KALSHI_OPEN_MARKETS_TTL_S` | `10` | Restored steady-state TTL (seconds). |
| `KALSHI_ORDERBOOK_TTL_S` | `10` | Restored steady-state orderbook cache TTL. |
| `KALSHI_WS_ENABLED` | `0` | **Phase 2:** enable Kalshi WebSocket (orderbook + ticker). |
| `KALSHI_WS_MAX_MARKETS` | `120` | Cap markets subscribed for `orderbook_delta`. |
| `KALSHI_WS_SUBSCRIBE_CHUNK` | `40` | Markets per subscribe command. |
| `KALSHI_WS_RECONNECT_CAP_S` | `60` | Max backoff between reconnect attempts. |
| `KALSHI_LOG_TICK_INTERVAL_S` | `0` | Log dual-engine tick latency / WS / cache hit % at this interval (0 = off). |
| `KALSHI_PREWARM_MAX_CONCURRENT` | `4` | Max parallel `/markets` prewarm requests. |
| `KALSHI_STARTUP_RESTORE_TTLS_DELAY_S` | `8` | Delay before reverting cold-start cache TTLs. |
| `KALSHI_HTTP_TIMEOUT_S` | `30` | Shared `httpx` request timeout. |
| `KALSHI_HTTP_CONNECT_TIMEOUT_S` | `15` | Shared `httpx` connect timeout. |
| `KALSHI_PRIVATE_CALL_CONCURRENCY` | `3` | Max concurrent signed private REST calls. |
| `DASHBOARD_ORDERBOOK_CACHE_TTL_S` | `5` | Cache TTL for `GET /api/dashboard/orderbooks`. |

## Not changed in this pass

- SQLite is still **one connection per operation** in `Store` (schema runs per transaction); pooling a single `aiosqlite` connection was skipped to keep behavior predictable.
