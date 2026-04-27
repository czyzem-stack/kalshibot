"""# PHASE 3.1 dashboard/API response contract types.

TypedDict response contracts for health and dashboard-family endpoints.
These are type-hint only and intentionally do not alter runtime behavior.
"""

from __future__ import annotations

from typing import Any, TypedDict


class HealthResponse(TypedDict, total=False):
    status: str
    started_at: str | None
    dual_engine_loop_running: bool
    optimizer_loop_running: bool


class HealthStartupResponse(TypedDict, total=False):
    startup_complete: bool
    prewarm_complete: bool
    kalshi_ws_enabled: bool
    kalshi_ws_task_running: bool
    ws_connected: bool
    ws_messages: int
    ws_orderbook_cache_writes: int
    ws_subscribe_tickers: int
    ws_last_error: str | None
    orderbook_cache_hits: int
    orderbook_cache_misses: int


class HealthDeepResponse(TypedDict, total=False):
    status: str
    started_at: str | None
    sqlite_path: str
    sqlite_bytes: int | None
    dual_engine_loop_running: bool
    optimizer_loop_running: bool
    engine_last_errors: dict[str, str]
    alert_webhook_configured: bool


class DataStorageResponse(TypedDict, total=False):
    sqlite_path: str
    data_log_dir: str
    data_logging_enabled: bool
    data_log_equity: bool
    data_reset_token_configured: bool


class EngineStatusBlock(TypedDict, total=False):
    engine_running: bool
    simulate_orders: bool
    last_tick_at: str | None
    last_error: str | None
    markets_scanned: int
    last_tick_trace: list[str] | None
    asset_snapshots: dict[str, dict[str, Any]]
    auto_optimize: bool
    optimizer_note: str | None
    simulate: bool


class EngineStatusResponse(TypedDict):
    live: EngineStatusBlock
    lab_a: EngineStatusBlock
    lab_b: EngineStatusBlock
    lab_c: EngineStatusBlock
    lab_d: EngineStatusBlock


class AccountResponse(TypedDict, total=False):
    balance: dict[str, Any] | None
    positions: list[dict[str, Any]]
    orders: list[dict[str, Any]]
    position_count: int
    resting_order_count: int
    error: str | None


class MarketsPreviewResponse(TypedDict):
    series_ticker: str
    markets: list[Any]


class MarketPulseResponse(TypedDict, total=False):
    branch: str
    generated_at: str
    items: list[dict[str, Any]]


class DashboardRecentTradesResponse(TypedDict):
    recent_trades: list[dict[str, Any]]
    recent_signals: list[dict[str, Any]]
    not_traded_signals: list[dict[str, Any]]


class DashboardOpenPositionsResponse(TypedDict):
    account_snapshot: dict[str, Any]
    remote_balance: dict[str, Any] | None


class DashboardOrderbooksResponse(TypedDict, total=False):
    cached: bool
    cache_age_s: float
    as_of_utc: str
    metrics: dict[str, Any]
    metrics_lab_a: dict[str, Any]
    metrics_lab_b: dict[str, Any]
    metrics_lab_c: dict[str, Any]
    metrics_lab_d: dict[str, Any]
    order_writes_live: bool


class DashboardResponse(TypedDict, total=False):
    config: dict[str, Any]
    storage: dict[str, Any]
    kalshi: dict[str, Any]
    engine: dict[str, Any]
    asset_snapshots: dict[str, Any]
    rule_suggestions: dict[str, Any]
    metrics: dict[str, Any]
    metrics_lab_a: dict[str, Any]
    metrics_lab_b: dict[str, Any]
    metrics_lab_c: dict[str, Any]
    metrics_lab_d: dict[str, Any]
    equity_snapshots: list[dict[str, Any]]
    equity_snapshots_lab_a: list[dict[str, Any]]
    equity_snapshots_lab_b: list[dict[str, Any]]
    equity_snapshots_lab_c: list[dict[str, Any]]
    equity_snapshots_lab_d: list[dict[str, Any]]
    recent_signals: list[dict[str, Any]]
    not_traded_signals: list[dict[str, Any]]
    recent_trades: list[dict[str, Any]]
    remote_balance: dict[str, Any] | None
    account_snapshot: dict[str, Any]
    lab_a_config: dict[str, Any]
    lab_b_config: dict[str, Any]
    lab_c_config: dict[str, Any]
    lab_d_config: dict[str, Any]
    lab_thoughts: dict[str, list[str]]
    optimizer_activity: dict[str, Any]
