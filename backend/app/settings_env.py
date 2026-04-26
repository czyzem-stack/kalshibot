from __future__ import annotations

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
    pk_ready = has_pem or path_ok
    if has_pem:
        source = "pem"
    elif path_ok:
        source = "file"
    elif path_s:
        source = "file_missing"
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


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class EnvSettings:
    kalshi_api_key_id: str = _get("KALSHI_API_KEY_ID")
    kalshi_private_key_path: str = _get("KALSHI_PRIVATE_KEY_PATH")
    kalshi_private_key_pem: str = _get("KALSHI_PRIVATE_KEY_PEM")
    kalshi_env: str = _get("KALSHI_ENV", "demo") or "demo"
    sqlite_path: str = _get(
        "SQLITE_PATH",
        str(_REPO_ROOT / "data" / "bot.sqlite3"),
    )
    cors_origins: str = (
        _get("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
        or "http://localhost:5173,http://127.0.0.1:5173"
    )
    # JSONL logs: signals, trades, optional equity; under repo or absolute path.
    data_log_dir: str = _get("DATA_LOG_DIR", str(_REPO_ROOT / "data" / "logs"))
    data_logging_enabled: bool = _get("DATA_LOGGING", "1").lower() not in ("0", "false", "no", "")
    data_log_equity: bool = _get("DATA_LOG_EQUITY", "0").lower() in ("1", "true", "yes")
    # If set, POST /api/data/reset must send header ``X-Reset-Token: <value>`` in addition to confirm=yes.
    data_reset_token: str = _get("DATA_RESET_TOKEN", "")
    anthropic_api_key: str = _get("ANTHROPIC_API_KEY", "")
    # Optional: POST JSON on new/changed engine ``last_error`` per branch (Discord incoming webhook works with {"content": "..."}).
    alert_webhook_url: str = _get("ALERT_WEBHOOK_URL", "")
    # Minimum seconds between two webhook posts for the same (branch, error prefix) to avoid spam.
    alert_webhook_min_seconds: float = float(_get("ALERT_WEBHOOK_MIN_SECONDS", "120") or 120)

    @property
    def base_rest_url(self) -> str:
        if self.kalshi_env.lower() in ("prod", "production", "live"):
            return "https://api.elections.kalshi.com/trade-api/v2"
        return "https://demo-api.kalshi.co/trade-api/v2"


env = EnvSettings()
