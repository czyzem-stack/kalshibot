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
    lab_e: EngineStatusBlock


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
    metrics_lab_e: dict[str, Any]
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
    metrics_lab_e: dict[str, Any]
    equity_snapshots: list[dict[str, Any]]
    equity_snapshots_lab_a: list[dict[str, Any]]
    equity_snapshots_lab_b: list[dict[str, Any]]
    equity_snapshots_lab_c: list[dict[str, Any]]
    equity_snapshots_lab_d: list[dict[str, Any]]
    equity_snapshots_lab_e: list[dict[str, Any]]
    recent_signals: list[dict[str, Any]]
    not_traded_signals: list[dict[str, Any]]
    recent_trades: list[dict[str, Any]]
    remote_balance: dict[str, Any] | None
    account_snapshot: dict[str, Any]
    lab_a_config: dict[str, Any]
    lab_b_config: dict[str, Any]
    lab_c_config: dict[str, Any]
    lab_d_config: dict[str, Any]
    lab_e_config: dict[str, Any]
    lab_thoughts: dict[str, list[str]]
    # OPTIMIZER v0.1 — keep smart core, remove visible settings per user request
    optimizer_activity: dict[str, Any]


class OptimizerStatusResponse(TypedDict, total=False):
    # HELP CLEANUP — thorough & professional: contract for GET /api/optimizer/status (read-only diagnostics).
    # OPTIMIZER v0.1 — keep smart core, remove visible settings per user request
    enabled: bool
    adaptive_enabled: bool
    model: str
    optimizer_cycle_count: int
    pulse_eval_count: int
    last_run_at: str
    last_status: str
    last_error: str
    next_tick_preview: str
    proposal_history: list[dict[str, Any]]
    # LABS BREEDING v0.1 REVAMP — fully automatic, invisible (observability via status only)
    # Rows may include toast_id / toast_family for ephemeral dashboard toasts (labs breeding).
    labs_breeding_log: list[dict[str, Any]]
    labs_breeding_children: list[dict[str, Any]]
    labs_breeding_death_chamber: list[dict[str, Any]]
    labs_breeding_lineage_history: list[dict[str, Any]]
    labs_breeding_tree_snapshot: dict[str, Any]
    labs_breeding_version: str
    # LABS BREEDING v0.1 — radar chart + Optimizer/Breeder toggle (derived moods; no new persisted keys).
    labs_breeding_personality_radar: dict[str, Any]
    labs_breeding_last_generation_iso: str
    labs_breeding_replace_cooldown_until: str
    breeding_enabled: bool
    breeding_last_run_at: str
    breeding_last_summary: str
    breeding_last_run_minutes_ago: float | None
    internal_optimizer_trace: list[dict[str, Any]]
    advanced_metrics_last: dict[str, Any]
    acceptance_rate_pct: float
