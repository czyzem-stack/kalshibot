from __future__ import annotations

# LABS BREEDING v0.1 (Lab A staging/adopts + B/C/D breed + competitive children) — caps and cadence live in
# ``branch_config`` / ``lab_breeding`` (not env).

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def kalshi_credentials_report() -> dict[str, Any]:
    """Non-secret summary for UI: what is configured in environment."""
    has_id = bool(_get("KALSHI_API_KEY_ID"))
    pem = _get("KALSHI_PRIVATE_KEY_PEM")
    has_pem = bool(pem)
    path_s = _get("KALSHI_PRIVATE_KEY_PATH")
    path_obj = Path(path_s).expanduser() if path_s else None
    path_ok = False
    if path_obj:
        try:
            path_ok = path_obj.is_file()
        except OSError:
            path_ok = False
    use_kr = _get("KALSHI_USE_KEYRING", "0").lower() in ("1", "true", "yes")
    pk_ready = has_pem or path_ok or use_kr
    if has_pem:
        source = "pem"
    elif path_ok:
        source = "file"
    elif path_s:
        source = "file_missing"
    elif use_kr:
        source = "keyring"
    else:
        source = "not_set"
    return {
        "api_key_id_configured": has_id,
        "private_key_configured": pk_ready,
        "private_key_source": source,
    }


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, val)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_load_dotenv(_REPO_ROOT / ".env")


def _resolved_path_env(name: str, *, default: Path) -> str:
    """
    Resolve SQLITE_PATH / DATA_LOG_DIR: relative values are anchored at this checkout's repo root
    (not the process cwd), so parallel develop + worktree APIs never accidentally share one file.
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return str(default.resolve())
    p = Path(raw)
    if p.is_absolute():
        return str(p.resolve())
    return str((_REPO_ROOT / p).resolve())


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _get_int(name: str, default: int, *, min_value: int | None = None, max_value: int | None = None) -> int:
    try:
        v = int(_get(name, str(default)) or default)
    except (TypeError, ValueError):
        v = int(default)
    if min_value is not None:
        v = max(min_value, v)
    if max_value is not None:
        v = min(max_value, v)
    return v


def _get_float(name: str, default: float, *, min_value: float | None = None, max_value: float | None = None) -> float:
    try:
        v = float(_get(name, str(default)) or default)
    except (TypeError, ValueError):
        v = float(default)
    if min_value is not None:
        v = max(min_value, v)
    if max_value is not None:
        v = min(max_value, v)
    return v


@dataclass(frozen=True)
class EnvSettings:
    kalshi_api_key_id: str = _get("KALSHI_API_KEY_ID")
    kalshi_private_key_path: str = _get("KALSHI_PRIVATE_KEY_PATH")
    kalshi_private_key_pem: str = _get("KALSHI_PRIVATE_KEY_PEM")
    kalshi_env: str = _get("KALSHI_ENV", "demo") or "demo"
    sqlite_path: str = _resolved_path_env(
        "SQLITE_PATH",
        default=_REPO_ROOT / "data" / "bot.sqlite3",
    )
    cors_origins: str = (
        _get("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
        or "http://localhost:5173,http://127.0.0.1:5173"
    )
    # Logging: LOG_JSON=1 for one JSON line per log (Docker / prod). LOG_LEVEL=DEBUG|INFO|…
    log_json: bool = _get("LOG_JSON", "0").lower() in ("1", "true", "yes")
    log_level: str = _get("LOG_LEVEL", "INFO") or "INFO"
    # When set, all /api routes require Authorization: Bearer <token> except /api/health*. Disabled by default (local dev).
    api_bearer_token: str = _get("KALSHI_API_BEARER_TOKEN", "")
    # Optional OS keychain: if KALSHI_USE_KEYRING=1 and PEM/path are empty, load PEM from keyring (requires `pip install keyring`).
    kalshi_use_keyring: bool = _get("KALSHI_USE_KEYRING", "0").lower() in ("1", "true", "yes")
    kalshi_keyring_service: str = _get("KALSHI_KEYRING_SERVICE", "kalshibot")
    kalshi_keyring_username: str = _get("KALSHI_KEYRING_USERNAME", "KALSHI_PRIVATE_KEY_PEM")
    # JSONL logs: signals, trades, optional equity; under repo or absolute path.
    data_log_dir: str = _resolved_path_env(
        "DATA_LOG_DIR",
        default=_REPO_ROOT / "data" / "logs",
    )
    data_logging_enabled: bool = _get("DATA_LOGGING", "1").lower() not in ("0", "false", "no", "")
    data_log_equity: bool = _get("DATA_LOG_EQUITY", "0").lower() in ("1", "true", "yes")
    # If set, POST /api/data/reset must send header ``X-Reset-Token: <value>`` in addition to confirm=yes.
    data_reset_token: str = _get("DATA_RESET_TOKEN", "")
    anthropic_api_key: str = _get("ANTHROPIC_API_KEY", "")
    # Optional: POST JSON on new/changed engine ``last_error`` per branch (Discord incoming webhook works with {"content": "..."}).
    alert_webhook_url: str = _get("ALERT_WEBHOOK_URL", "")
    # Minimum seconds between two webhook posts for the same (branch, error prefix) to avoid spam.
    alert_webhook_min_seconds: float = _get_float("ALERT_WEBHOOK_MIN_SECONDS", 120.0, min_value=1.0)
    # Longer in-process /markets and orderbook TTL right after process start to avoid a 5× cold-start storm.
    kalshi_cold_start_cache_ttl_s: float = _get_float("KALSHI_COLD_START_CACHE_TTL_S", 90.0, min_value=5.0)
    # Steady-state defaults after warm-up (restored a few seconds after pre-warm; see kalshi_client).
    kalshi_open_markets_ttl_s: float = _get_float("KALSHI_OPEN_MARKETS_TTL_S", 10.0, min_value=1.0)
    kalshi_orderbook_ttl_s: float = _get_float("KALSHI_ORDERBOOK_TTL_S", 10.0, min_value=1.0)
    # Log perf_counter() phases during API lifespan (also force-enabled when KALSHI_PROFILE_STARTUP=1).
    profile_startup: bool = _get("KALSHI_PROFILE_STARTUP", "0").lower() in ("1", "true", "yes")
    # PHASE 2: optional Kalshi WebSocket (orderbook + ticker); REST cache remains fallback.
    kalshi_ws_enabled: bool = _get("KALSHI_WS_ENABLED", "0").lower() in ("1", "true", "yes")
    kalshi_ws_max_markets: int = _get_int("KALSHI_WS_MAX_MARKETS", 120, min_value=1, max_value=500)
    kalshi_ws_subscribe_chunk: int = _get_int("KALSHI_WS_SUBSCRIBE_CHUNK", 40, min_value=5, max_value=80)
    kalshi_ws_reconnect_cap_s: float = _get_float("KALSHI_WS_RECONNECT_CAP_S", 60.0, min_value=5.0)
    # Log dual_engine_loop iteration wall time when interval (seconds) > 0 (e.g. 30 = log every 30s).
    kalshi_log_tick_interval_s: float = _get_float("KALSHI_LOG_TICK_INTERVAL_S", 0.0, min_value=0.0)
    # PHASE 3: centralize remaining hot-path constants (no behavior change; defaults match prior code).
    kalshi_http_timeout_s: float = _get_float("KALSHI_HTTP_TIMEOUT_S", 30.0, min_value=5.0)
    kalshi_http_connect_timeout_s: float = _get_float("KALSHI_HTTP_CONNECT_TIMEOUT_S", 15.0, min_value=1.0)
    kalshi_http_max_connections: int = _get_int("KALSHI_HTTP_MAX_CONNECTIONS", 40, min_value=5)
    kalshi_http_max_keepalive_connections: int = _get_int("KALSHI_HTTP_MAX_KEEPALIVE_CONNECTIONS", 20, min_value=2)
    kalshi_private_call_concurrency: int = _get_int("KALSHI_PRIVATE_CALL_CONCURRENCY", 3, min_value=1, max_value=16)
    kalshi_public_max_attempts: int = _get_int("KALSHI_PUBLIC_MAX_ATTEMPTS", 8, min_value=1, max_value=20)
    kalshi_private_max_attempts: int = _get_int("KALSHI_PRIVATE_MAX_ATTEMPTS", 8, min_value=1, max_value=20)
    kalshi_429_backoff_base_s: float = _get_float("KALSHI_429_BACKOFF_BASE_S", 1.8, min_value=0.1)
    kalshi_429_backoff_cap_s: float = _get_float("KALSHI_429_BACKOFF_CAP_S", 55.0, min_value=1.0)
    kalshi_429_jitter_s: float = _get_float("KALSHI_429_JITTER_S", 0.6, min_value=0.0)
    kalshi_5xx_backoff_base_s: float = _get_float("KALSHI_5XX_BACKOFF_BASE_S", 0.4, min_value=0.05)
    kalshi_5xx_backoff_cap_s: float = _get_float("KALSHI_5XX_BACKOFF_CAP_S", 8.0, min_value=0.5)
    kalshi_ws_ping_interval_s: float = _get_float("KALSHI_WS_PING_INTERVAL_S", 20.0, min_value=5.0)
    kalshi_ws_ping_timeout_s: float = _get_float("KALSHI_WS_PING_TIMEOUT_S", 45.0, min_value=5.0)
    kalshi_ws_close_timeout_s: float = _get_float("KALSHI_WS_CLOSE_TIMEOUT_S", 5.0, min_value=1.0)
    kalshi_ws_recv_timeout_s: float = _get_float("KALSHI_WS_RECV_TIMEOUT_S", 1.0, min_value=0.1)
    kalshi_ws_no_ticker_sleep_s: float = _get_float("KALSHI_WS_NO_TICKER_SLEEP_S", 15.0, min_value=1.0)
    kalshi_ws_reconnect_base_s: float = _get_float("KALSHI_WS_RECONNECT_BASE_S", 1.0, min_value=0.1)
    kalshi_ws_reconnect_multiplier: float = _get_float("KALSHI_WS_RECONNECT_MULTIPLIER", 1.8, min_value=1.1)
    kalshi_ws_reconnect_jitter_s: float = _get_float("KALSHI_WS_RECONNECT_JITTER_S", 0.35, min_value=0.0)
    startup_restore_ttls_delay_s: float = _get_float("KALSHI_STARTUP_RESTORE_TTLS_DELAY_S", 8.0, min_value=0.0)
    prewarm_max_concurrent: int = _get_int("KALSHI_PREWARM_MAX_CONCURRENT", 4, min_value=1, max_value=16)
    dual_engine_lab_tick_stagger_s: float = _get_float("KALSHI_LAB_TICK_STAGGER_S", 0.45, min_value=0.0)
    dashboard_orderbook_cache_ttl_s: float = _get_float("DASHBOARD_ORDERBOOK_CACHE_TTL_S", 5.0, min_value=0.5)
    engine_study_trade_window_minutes: int = _get_int("ENGINE_STUDY_TRADE_WINDOW_MINUTES", 15, min_value=1)
    engine_orderbook_enrich_first_tick_cap: int = _get_int("ENGINE_ORDERBOOK_ENRICH_FIRST_TICK_CAP", 10, min_value=1)
    engine_orderbook_enrich_steady_cap: int = _get_int("ENGINE_ORDERBOOK_ENRICH_STEADY_CAP", 20, min_value=1)
    # PHASE FINAL: centralized defaults used by engine/loop cfg fallbacks (same values as previous behavior).
    default_poll_seconds: float = _get_float("DEFAULT_POLL_SECONDS", 8.0, min_value=0.1)
    default_window_minutes: int = _get_int("DEFAULT_WINDOW_MINUTES", 15, min_value=1)
    default_balance_fraction_per_window: float = _get_float("DEFAULT_BALANCE_FRACTION_PER_WINDOW", 0.03, min_value=0.0)
    default_min_contracts: int = _get_int("DEFAULT_MIN_CONTRACTS", 1, min_value=1)
    default_paper_balance_cents: int = _get_int("DEFAULT_PAPER_BALANCE_CENTS", 500_000, min_value=0)
    default_auto_close_open_sim_minutes: float = _get_float("DEFAULT_AUTO_CLOSE_OPEN_SIM_MINUTES", 75.0, min_value=0.0)
    # OPTIMIZER v0.1 — keep smart core, remove visible settings per user request (replay weights live in optimizer_claude).

    @property
    def base_rest_url(self) -> str:
        if self.kalshi_env.lower() in ("prod", "production", "live"):
            return "https://api.elections.kalshi.com/trade-api/v2"
        return "https://demo-api.kalshi.co/trade-api/v2"


env = EnvSettings()
