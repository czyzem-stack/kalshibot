from __future__ import annotations

import json
import shutil
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from .branch_config import (
    ALL_CFG_LAB_KEYS,
    BRANCH_CHILD_LABS,
    ensure_patient_stop_loss_on_branch_dict,
    sync_live_paper_trading_keys,
)
from .settings_env import env

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _data_log(stream: str, payload: dict[str, Any]) -> None:
    try:
        from .data_log import append_event

        append_event(stream, payload)
    except Exception:
        pass


_CATCHALL_MID_RULE: dict[str, Any] = {
    "name": "Mid 55–85%, 0–20m (fills demo / typical mids)",
    "min_prob": 0.55,
    "max_prob": 0.85,
    "min_minutes_left": 0.0,
    "max_minutes_left": 20.0,
}


def _rules_miss_mid_yes_band(rules: Any) -> bool:
    """True if no rule could match ~60–72% implied YES (common on 15m crypto demo with old defaults)."""
    if not isinstance(rules, list) or not rules:
        return False
    for r in rules:
        if not isinstance(r, dict):
            continue
        try:
            lo = float(r["min_prob"])
            hi = float(r["max_prob"])
        except (KeyError, TypeError, ValueError):
            continue
        if lo <= 0.58 and hi >= 0.72:
            return False
    return True


def _sql_canonical_branch_key_expr() -> str:
    """
    Stable branch bucket for SQLite filters and the open-sim UNIQUE index.

    - Legacy ``sim_lab`` folds into ``lab_a`` (same paper book as Lab A).
    - NULL / empty / whitespace branch is treated as ``live`` (matches COALESCE defaults).
    - Otherwise ``lower(trim(branch))`` so casing/spacing cannot split one logical branch.
    """
    return (
        "CASE WHEN lower(trim(coalesce(branch, ''))) = 'sim_lab' THEN 'lab_a' "
        "WHEN nullif(trim(coalesce(branch, '')), '') IS NULL THEN 'live' "
        "ELSE lower(trim(branch)) END"
    )


def _sql_branch_predicate(branch: str) -> str:
    """
    SQL boolean expression for rows belonging to one logical branch.
    Lab A includes legacy ``sim_lab`` rows so rollups, charts, and history stay consistent.
    """
    key = _sql_canonical_branch_key_expr()
    b = str(branch or "").strip().lower()
    if b == "sim_lab":
        b = "lab_a"
    for cand in ALL_CFG_LAB_KEYS:
        if b == cand:
            return f"({key}) = '{cand}'"
    if b == "live":
        return f"({key}) = 'live'"
    raise ValueError(f"unsupported branch for SQL filter: {branch!r}")


def normalize_trade_branch_for_db(branch: str | None) -> str:
    """Persisted ``branch`` on signals/trades: lowercase known keys; ``sim_lab`` -> ``lab_a``."""
    b = str(branch or "").strip().lower()
    if b in ("", "none"):
        return "live"
    if b == "sim_lab":
        return "lab_a"
    if b == "live" or b in ALL_CFG_LAB_KEYS:
        return b
    return b


def _sql_sim_open_book_predicate(branch: str) -> str:
    """
    Simulated rows that count as an open book position for a branch (holdings table, duplicate-trade guard).

    Uses the same shape as the dashboard ``open_sim_trades_for_branch`` query: **no** ``mode`` filter so legacy
    rows (empty or odd ``mode``) still align with the duplicate guard — otherwise the atomic insert could miss them
    while the UI still showed two tickets.
    """
    br = _sql_branch_predicate(branch)
    return f"simulated = 1 AND LOWER(COALESCE(status, '')) IN ('open', 'resting') AND ({br})"


def _series_prefix_like_pattern(series_prefix: str) -> str | None:
    """``LIKE`` pattern for ``UPPER(TRIM(ticker)) LIKE ? ESCAPE '\\'``; None if empty."""
    pfx = str(series_prefix or "").strip().upper()
    if not pfx:
        return None
    esc = pfx.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return esc + "%"


SCHEMA = """
CREATE TABLE IF NOT EXISTS bot_config (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  json TEXT NOT NULL
);

-- Append-only audit log of full config JSON after each successful save. The active row remains in
-- ``bot_config`` (id=1); this table enables rollback / forensics without replacing the hot path.
CREATE TABLE IF NOT EXISTS config_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  branch_name TEXT NOT NULL DEFAULT 'global',
  timestamp TEXT NOT NULL,
  config_json TEXT NOT NULL,
  changed_by TEXT,
  reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_config_history_ts ON config_history (timestamp DESC);

CREATE TABLE IF NOT EXISTS signals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  window_id TEXT NOT NULL,
  asset_id TEXT NOT NULL,
  ticker TEXT NOT NULL,
  side TEXT NOT NULL,
  implied_prob REAL,
  minutes_left REAL,
  rule_name TEXT,
  executed INTEGER NOT NULL,
  skip_reason TEXT,
  mode TEXT NOT NULL,
  extra_json TEXT,
  branch TEXT DEFAULT 'live'
);

CREATE TABLE IF NOT EXISTS trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  mode TEXT NOT NULL,
  ticker TEXT NOT NULL,
  side TEXT NOT NULL,
  contracts_fp TEXT NOT NULL,
  limit_yes_dollars TEXT,
  amount_cents INTEGER NOT NULL,
  simulated INTEGER NOT NULL,
  order_id TEXT,
  client_order_id TEXT,
  status TEXT NOT NULL,
  result TEXT,
  pnl_cents INTEGER,
  settled_at TEXT,
  extra_json TEXT,
  branch TEXT DEFAULT 'live'
);

CREATE TABLE IF NOT EXISTS equity_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  mode TEXT NOT NULL,
  equity_cents INTEGER NOT NULL,
  mtm_equity_cents INTEGER,
  note TEXT,
  branch TEXT DEFAULT 'live'
);

CREATE TABLE IF NOT EXISTS optimizer_recommendations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  window_start TEXT,
  window_end TEXT,
  source_branches TEXT NOT NULL,
  summary TEXT NOT NULL,
  recommendation_json TEXT NOT NULL,
  raw_json TEXT
);
"""


def default_bot_config() -> dict[str, Any]:
    return {
        "simulate": True,
        "live_paper_trading": True,  # canonical; mirrored to ``simulate`` (see ``sync_live_paper_trading_keys``)
        "engine_running": False,
        "poll_seconds": 8,
        "balance_fraction_per_window": 0.03,
        "window_minutes": 18,
        "assets": {
            "btc": {"enabled": True, "label": "BTC 15m", "series_ticker": "KXBTC15M"},
            "eth": {"enabled": True, "label": "ETH 15m", "series_ticker": "KXETH15M"},
            "sol": {"enabled": True, "label": "SOL 15m", "series_ticker": "KXSOL15M"},
            "xrp": {"enabled": True, "label": "XRP 15m", "series_ticker": "KXXRP15M"},
            "doge": {"enabled": True, "label": "DOGE 15m", "series_ticker": "KXDOGE15M"},
            "ada": {"enabled": True, "label": "ADA 15m", "series_ticker": "KXADA15M"},
            "bch": {"enabled": True, "label": "BCH 15m", "series_ticker": "KXBCH15M"},
            "bnb": {"enabled": True, "label": "BNB 15m", "series_ticker": "KXBNB15M"},
            "hype": {"enabled": True, "label": "HYPE 15m", "series_ticker": "KXHYPE15M"},
        },
        "rules": [
            {"name": "Low 42-52%", "min_prob": 0.42, "max_prob": 0.52, "min_minutes_left": 6.0, "max_minutes_left": 20.0},
            {"name": "Mid 55-72%", "min_prob": 0.55, "max_prob": 0.72, "min_minutes_left": 4.0, "max_minutes_left": 18.0},
            {"name": "High 78-94%", "min_prob": 0.78, "max_prob": 0.94, "min_minutes_left": 3.0, "max_minutes_left": 15.0},
            {
                "name": "NO conviction 62-78%",
                "side": "no",
                "min_prob": 0.62,
                "max_prob": 0.78,
                "min_minutes_left": 3.0,
                "max_minutes_left": 18.0,
            },
        ],
        "only_yes_subtitle_contains": "",
        "exclude_yes_subtitle_contains": "",
        "no_bet_when_yes_below_pct": 32,
        "dev_sim_yes_implied_ge_pct": None,
        "swing_exit_implied_drop_pct": 25,
        "enable_patient_stop_loss": True,
        "stop_loss_trigger_pct": -10.0,
        "min_hold_minutes_before_stop": 45,
        "min_contracts": 1,
        "paper_fee_model": "kalshi_taker",
        "kalshi_fee_multiplier": 1.0,
        "paper_fee_bps": 0,
        "paper_balance_cents": 500_000,
        # Lab A: staging / blend before Live — internal auto-tune may adjust sizing from PnL.
        "lab_a": {
            "engine_running": False,
            "auto_optimize": True,
            "auto_reset_paper_on_tick_failure": False,
            "enable_patient_stop_loss": True,
            "stop_loss_trigger_pct": -6.0,
            "min_hold_minutes_before_stop": 20,
            "balance_fraction_per_window": 0.055,
            "window_minutes": 15,
            "paper_fee_model": "kalshi_taker",
            "kalshi_fee_multiplier": 1.0,
            "paper_fee_bps": 0,
            "paper_balance_cents": 500_000,
        },
        # Lab B: conservative paper reference (does not apply scheduled optimizer rule changes).
        "lab_b": {
            "engine_running": False,
            "auto_optimize": False,
            "auto_reset_paper_on_tick_failure": False,
            "enable_patient_stop_loss": True,
            "stop_loss_trigger_pct": -8.0,
            "min_hold_minutes_before_stop": 30,
            "balance_fraction_per_window": 0.04,
            "window_minutes": 18,
            "paper_fee_model": "kalshi_taker",
            "kalshi_fee_multiplier": 1.0,
            "paper_fee_bps": 0,
            "paper_balance_cents": 500_000,
        },
        # Lab C: aggressive paper reference (does not apply scheduled optimizer rule changes).
        "lab_c": {
            "engine_running": False,
            "auto_optimize": False,
            "auto_reset_paper_on_tick_failure": False,
            "enable_patient_stop_loss": True,
            "stop_loss_trigger_pct": -12.0,
            "min_hold_minutes_before_stop": 60,
            "balance_fraction_per_window": 0.11,
            "window_minutes": 12,
            "paper_fee_model": "kalshi_taker",
            "kalshi_fee_multiplier": 1.0,
            "paper_fee_bps": 0,
            "paper_balance_cents": 500_000,
        },
        # Lab D: wild reference branch; optimizer may use B/C momentum to influence Lab A sizing.
        "lab_d": {
            "engine_running": False,
            "auto_optimize": False,
            "auto_reset_paper_on_tick_failure": False,
            "enable_patient_stop_loss": True,
            "stop_loss_trigger_pct": -7.0,
            "min_hold_minutes_before_stop": 25,
            "balance_fraction_per_window": 0.13,
            "window_minutes": 10,
            "paper_fee_model": "kalshi_taker",
            "kalshi_fee_multiplier": 1.0,
            "paper_fee_bps": 0,
            "paper_balance_cents": 500_000,
        },
        # LABS BREEDING v0.1 — invisible child engines: on by default (explicit ``engine_running: false`` clears a slot).
        **{
            ck: {
                "engine_running": True,
                "auto_optimize": False,
                "auto_reset_paper_on_tick_failure": False,
                "enable_patient_stop_loss": True,
                "stop_loss_trigger_pct": -9.0,
                "min_hold_minutes_before_stop": 22,
                "balance_fraction_per_window": 0.09,
                "window_minutes": 12,
                "paper_fee_model": "kalshi_taker",
                "kalshi_fee_multiplier": 1.0,
                "paper_fee_bps": 0,
                "paper_balance_cents": 500_000,
            }
            for ck in BRANCH_CHILD_LABS
        },
        "optimizer": {
            "enabled": True,
            "interval_minutes": 20,
            "lookback_hours": 48,
            "max_rows_per_table": 5000,
            "model": "claude-sonnet-4-5",
            "adaptive_enabled": True,
            "mode": "duel",
            "lab_a_enabled": True,
            "lab_b_enabled": True,
            "lab_c_enabled": True,
            "lab_d_enabled": True,
            "lab_a_style": "blend",
            "lab_b_style": "conservative",
            "lab_c_style": "aggressive",
            "lab_d_style": "wild",
            "loss_streak_trigger": 1,
            "threshold_step_pct": 2,
            "minute_step": 2,
            "max_history": 120,
            "lab_a_yes_floor_pct": 56,
            "lab_b_yes_floor_pct": 58,
            "lab_c_yes_floor_pct": 52,
            "lab_d_yes_floor_pct": 50,
            "lab_a_min_minutes_left": 5,
            "lab_b_min_minutes_left": 6,
            "lab_c_min_minutes_left": 3,
            "lab_d_min_minutes_left": 2,
            "min_trades_for_optimize": 8,
            "min_profitable_trades": 2,
            "optimize_bet_size": True,
            "include_fees_in_score": True,
            "regime_lookback_hours": 4,
            "backtest_proposals": True,
            "adaptive_skip_backtest_gate": False,
            "optimize_rules_with_claude": True,
            "optimizer_cycle_count": 0,
            "claude_proposals_trace": [],
            "change_history": [],
            "pulse_trace": [],
            "next_tick_preview": "",
            "pulse_eval_count": 0,
            "last_pulse_eval_at": "",
            "last_run_at": None,
            "last_status": "",
            "last_error": "",
            # B/C/D child-lab GA + adoption: can run on the optimizer interval even when
            # ``enabled`` and ``adaptive_enabled`` are false; see ``architecture-breeding`` rule.
            "breeding_enabled": True,
            "breeding_last_run_at": "",
            "breeding_last_summary": "",
        },
    }


def expand_partial_lab_branch(branch: str, lab: dict[str, Any]) -> dict[str, Any]:
    """
    Shallow-merge ``lab`` over ``default_bot_config()[branch]`` so thin saves (e.g. only paper / fraction / window)
    cannot strip ``engine_running``, fee keys, or other lab defaults.
    """
    if branch not in ALL_CFG_LAB_KEYS:
        raise ValueError(f"branch must be a known lab key (parents or lab_child_*), got {branch!r}")
    base = dict(default_bot_config().get(branch) or {})
    base.update(lab)
    if isinstance(base.get("assets"), dict) and len(base["assets"]) == 0:
        del base["assets"]
    ensure_patient_stop_loss_on_branch_dict(base)
    return base


async def _migrate_columns(db: aiosqlite.Connection) -> None:
    async def cols(table: str) -> set[str]:
        cur = await db.execute(f"PRAGMA table_info({table})")
        rows = await cur.fetchall()
        return {str(r[1]) for r in rows}

    for table in ("signals", "trades", "equity_snapshots"):
        have = await cols(table)
        if "branch" not in have:
            await db.execute(f"ALTER TABLE {table} ADD COLUMN branch TEXT DEFAULT 'live'")
    eq_have = await cols("equity_snapshots")
    if "mtm_equity_cents" not in eq_have:
        await db.execute("ALTER TABLE equity_snapshots ADD COLUMN mtm_equity_cents INTEGER")
    await db.commit()


async def _migrate_config_history_audit_meta(db: aiosqlite.Connection) -> None:
    """Append-only ``config_history`` gains optional ``audit_meta`` JSON for high-risk writes (e.g. Live paper off)."""
    cur = await db.execute("PRAGMA table_info(config_history)")
    cols = {str(r[1]) for r in await cur.fetchall()}
    if "audit_meta" not in cols:
        await db.execute("ALTER TABLE config_history ADD COLUMN audit_meta TEXT")
        await db.commit()


async def _migrate_trades_open_sim_unique(db: aiosqlite.Connection) -> None:
    """
    At most one open/resting simulated row per (canonical branch, ticker): dedupe legacy duplicates, then enforce
    with a partial UNIQUE index so races cannot stack two tickets on the same contract (e.g. Lab C “2 open tickets”).

    Canonical branch matches ``_sql_canonical_branch_key_expr`` (``sim_lab`` -> ``lab_a``, NULL/blank -> ``live``,
    ``lower(trim(branch))`` otherwise) so the pre-insert SELECT and the index cannot disagree.
    """
    cur = await db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name='ux_trades_open_sim_cbr_ticker' LIMIT 1"
    )
    if await cur.fetchone():
        return

    await db.execute("DROP INDEX IF EXISTS ux_trades_open_sim_branch_ticker")

    key_sql = _sql_canonical_branch_key_expr()
    cur2 = await db.execute(
        f"""
        SELECT id, ({key_sql}) AS cbr, UPPER(TRIM(COALESCE(ticker, ''))) AS ut
        FROM trades
        WHERE simulated = 1 AND LOWER(COALESCE(status, '')) IN ('open', 'resting')
        ORDER BY id ASC
        """
    )
    rows = await cur2.fetchall()
    keeper: dict[tuple[str, str], int] = {}
    del_ids: list[int] = []
    for r in rows:
        d = dict(r)
        ut = str(d.get("ut") or "").strip()
        if not ut:
            continue
        cbr = str(d.get("cbr") or "live").strip().lower()
        rid = int(d["id"])
        key = (cbr, ut)
        prev = keeper.get(key)
        if prev is None:
            keeper[key] = rid
        elif rid > prev:
            del_ids.append(prev)
            keeper[key] = rid
        else:
            del_ids.append(rid)

    if del_ids:
        chunk = 400
        for i in range(0, len(del_ids), chunk):
            part = del_ids[i : i + chunk]
            qmarks = ",".join("?" * len(part))
            await db.execute(f"DELETE FROM trades WHERE id IN ({qmarks})", part)

    await db.execute(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_trades_open_sim_cbr_ticker
        ON trades ({key_sql}, UPPER(TRIM(ticker)))
        WHERE simulated = 1
          AND LOWER(COALESCE(status, '')) IN ('open', 'resting')
          AND TRIM(COALESCE(ticker, '')) != ''
        """
    )
    await db.commit()


def _normalize_loaded_config(cfg: dict[str, Any]) -> dict[str, Any]:
    # Legacy default skipped every Kalshi demo row ("Target price: TBD") for *trading* while the
    # dashboard could still show prices — sim never fired. Clear exact lone "tbd"; use ",tbd" if you need it back.
    ex = cfg.get("exclude_yes_subtitle_contains")
    if isinstance(ex, str) and ex.strip().casefold() == "tbd":
        cfg["exclude_yes_subtitle_contains"] = ""

    rules = cfg.get("rules")
    if isinstance(rules, list) and rules and _rules_miss_mid_yes_band(rules):
        cfg["rules"] = [*rules, dict(_CATCHALL_MID_RULE)]

    # Widen legacy "mid" band so 15m-to-close rows and last-second demo lines can match (old caps were 14–15m / 2m min).
    rules2 = cfg.get("rules")
    if isinstance(rules2, list):
        for r in rules2:
            if not isinstance(r, dict):
                continue
            name = str(r.get("name") or "")
            if "Mid 55" not in name and "mid 55" not in name.lower():
                continue
            try:
                lo = float(r.get("min_minutes_left", 0))
                hi = float(r.get("max_minutes_left", 0))
            except (TypeError, ValueError):
                continue
            if lo >= 1.0 or hi <= 16.0:
                r["min_minutes_left"] = 0.0
                r["max_minutes_left"] = max(hi, 20.0)
                r["name"] = "Mid 55–85%, 0–20m (fills demo / typical mids)"

    if "lab_a" not in cfg or not isinstance(cfg.get("lab_a"), dict):
        # Backfill from legacy sim_lab when present.
        legacy = cfg.get("sim_lab") if isinstance(cfg.get("sim_lab"), dict) else {}
        cfg["lab_a"] = {
            "engine_running": False,
            "auto_optimize": False,
            "balance_fraction_per_window": legacy.get("balance_fraction_per_window", 0.05),
            "window_minutes": legacy.get("window_minutes", 15),
            "paper_balance_cents": legacy.get("paper_balance_cents", cfg.get("paper_balance_cents") or 500_000),
        }
    if "lab_b" not in cfg or not isinstance(cfg.get("lab_b"), dict):
        cfg["lab_b"] = {
            "engine_running": False,
            "auto_optimize": False,
            "balance_fraction_per_window": 0.05,
            "window_minutes": 15,
            "paper_balance_cents": cfg.get("paper_balance_cents") or 500_000,
        }
    if "lab_c" not in cfg or not isinstance(cfg.get("lab_c"), dict):
        cfg["lab_c"] = {
            "engine_running": False,
            "auto_optimize": False,
            "balance_fraction_per_window": 0.08,
            "window_minutes": 12,
            "paper_balance_cents": cfg.get("paper_balance_cents") or 500_000,
        }
    if "lab_d" not in cfg or not isinstance(cfg.get("lab_d"), dict):
        cfg["lab_d"] = {
            "engine_running": False,
            "auto_optimize": False,
            "balance_fraction_per_window": 0.13,
            "window_minutes": 10,
            "paper_balance_cents": cfg.get("paper_balance_cents") or 500_000,
        }
    _dchild = default_bot_config()
    for ck in BRANCH_CHILD_LABS:
        if ck not in cfg or not isinstance(cfg.get(ck), dict):
            cfg[ck] = dict(_dchild.get(ck) or {})
    dopt = dict(default_bot_config().get("optimizer") or {})
    cur_o = cfg.get("optimizer") if isinstance(cfg.get("optimizer"), dict) else {}
    merged_o = {**dopt, **cur_o}
    merged_o.pop("max_bet_fraction", None)
    cfg["optimizer"] = merged_o
    assets = cfg.get("assets")
    default_assets = default_bot_config().get("assets") or {}
    if isinstance(default_assets, dict) and default_assets:
        if not isinstance(assets, dict):
            cfg["assets"] = {k: dict(v) if isinstance(v, dict) else v for k, v in default_assets.items()}
        else:
            merged = dict(assets)
            for aid, adef in default_assets.items():
                if aid in merged:
                    continue
                merged[aid] = dict(adef) if isinstance(adef, dict) else adef
            cfg["assets"] = merged

    # Partial asset dicts (e.g. only label + series_ticker) must not imply disabled — missing enabled = on.
    assets_norm = cfg.get("assets")
    if isinstance(assets_norm, dict):
        for aid, a in list(assets_norm.items()):
            if isinstance(a, dict) and "enabled" not in a:
                assets_norm[aid] = {**a, "enabled": True}

    # Dev sim high-YES bypass: migrate legacy boolean to percent field
    if cfg.get("dev_sim_yes_implied_ge_pct") is None and bool(cfg.get("dev_sim_yes_implied_ge_70")):
        cfg["dev_sim_yes_implied_ge_pct"] = 70.0
    for lk in ALL_CFG_LAB_KEYS:
        if isinstance(cfg.get(lk), dict):
            cfg[lk] = expand_partial_lab_branch(lk, dict(cfg[lk]))
    # Per-lab ``assets: {}`` would override globals at merge time and disable all scanning for that lab.
    for lk in ALL_CFG_LAB_KEYS:
        block = cfg.get(lk)
        if isinstance(block, dict) and isinstance(block.get("assets"), dict) and len(block["assets"]) == 0:
            del block["assets"]
            cfg[lk] = block
    # Drop legacy mirror key from persisted config (clients use lab_a only).
    if "sim_lab" in cfg:
        del cfg["sim_lab"]
    sync_live_paper_trading_keys(cfg)
    return cfg


class Store:
    def __init__(self, path: str | None = None) -> None:
        self.path = path or env.sqlite_path

    @asynccontextmanager
    async def _open_db(self) -> AsyncIterator[aiosqlite.Connection]:
        """One SQLite session per use. Do not await connect() then async with the same handle (aiosqlite 0.20+)."""
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            # Avoid ``database is locked`` flakes when the engine loop and /api/dashboard overlap.
            await db.execute("PRAGMA busy_timeout=10000")
            await db.executescript(SCHEMA)
            await _migrate_columns(db)
            await _migrate_trades_open_sim_unique(db)
            await _migrate_config_history_audit_meta(db)
            cur = await db.execute("SELECT COUNT(*) c FROM bot_config WHERE id=1")
            row = await cur.fetchone()
            if row is None or int(row["c"]) == 0:
                await db.execute(
                    "INSERT INTO bot_config (id, json) VALUES (1, ?)",
                    (json.dumps(default_bot_config()),),
                )
                await db.commit()
            yield db

    async def load_config(self) -> dict[str, Any]:
        async with self._open_db() as db:
            cur = await db.execute("SELECT json FROM bot_config WHERE id=1")
            row = await cur.fetchone()
            if not row:
                return default_bot_config()
            raw = row["json"]
            try:
                parsed = json.loads(raw)
            except (json.JSONDecodeError, TypeError, ValueError):
                merged = default_bot_config()
                await db.execute("UPDATE bot_config SET json=? WHERE id=1", (json.dumps(merged),))
                await db.commit()
                _data_log(
                    "system",
                    {
                        "event": "bot_config_json_repaired",
                        "reason": "invalid_or_unreadable_json",
                        "at": datetime.now(timezone.utc).isoformat(),
                    },
                )
                return _normalize_loaded_config(merged)
            if not isinstance(parsed, dict):
                merged = default_bot_config()
                await db.execute("UPDATE bot_config SET json=? WHERE id=1", (json.dumps(merged),))
                await db.commit()
                _data_log(
                    "system",
                    {
                        "event": "bot_config_json_repaired",
                        "reason": "json_not_object",
                        "at": datetime.now(timezone.utc).isoformat(),
                    },
                )
                return _normalize_loaded_config(merged)
            return _normalize_loaded_config(parsed)

    async def save_config(
        self,
        cfg: dict[str, Any],
        *,
        history_branch: str = "global",
        history_changed_by: str | None = "api",
        history_reason: str | None = None,
        skip_config_history: bool = False,
        history_audit_meta: dict[str, Any] | None = None,
    ) -> None:
        """
        Persist the merged bot config to the single active row in ``bot_config`` (id=1).

        Unless ``skip_config_history`` is True, also appends a full JSON snapshot to ``config_history``
        for audit and optional rollback. ``branch_name`` in history is a logical tag (e.g. ``global``,
        ``lab_a``) for who initiated the change; the stored ``config_json`` is always the full config object.

        ``history_audit_meta`` (optional) is JSON-serialized into ``audit_meta`` for forensics (e.g. confirm gate
        context when disabling Live paper trading). Older databases pick up the column via ``_migrate_config_history_audit_meta``.
        """
        sync_live_paper_trading_keys(cfg)
        payload = json.dumps(cfg, default=str)
        ts = datetime.now(timezone.utc).isoformat()
        br = (history_branch or "global").strip() or "global"
        audit_blob: str | None = None
        if history_audit_meta is not None:
            try:
                audit_blob = json.dumps(history_audit_meta, default=str)
            except (TypeError, ValueError):
                audit_blob = json.dumps({"error": "audit_meta_not_serializable"})
        async with self._open_db() as db:
            if not skip_config_history:
                await db.execute(
                    """
                    INSERT INTO config_history (branch_name, timestamp, config_json, changed_by, reason, audit_meta)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (br, ts, payload, history_changed_by, history_reason, audit_blob),
                )
            await db.execute("UPDATE bot_config SET json=? WHERE id=1", (payload,))
            await db.commit()

    async def apply_uniform_paper_balance_after_scope_reset(
        self,
        cents: int,
        *,
        history_branch: str = "global",
        history_changed_by: str | None = "api:data_reset",
        history_reason: str | None = "uniform_paper_balance_after_scope_reset",
    ) -> dict[str, Any]:
        """
        Set the same paper seed on Live + every lab and clear per-lab ``paper_lifetime_basis_cents``.

        Uses one ``BEGIN IMMEDIATE`` transaction so a concurrent ``save_config`` (e.g. the optimizer loop)
        cannot overwrite this write with a stale snapshot, and vice versa — **optimizer** and the rest of
        ``bot_config`` are read fresh under the write lock then written back unchanged except bankroll keys.
        """
        _max_cents = 100_000_000
        c = max(0, min(_max_cents, int(cents)))
        ts = datetime.now(timezone.utc).isoformat()
        br = (history_branch or "global").strip() or "global"
        async with self._open_db() as db:
            await db.execute("BEGIN IMMEDIATE")
            cur = await db.execute("SELECT json FROM bot_config WHERE id=1")
            row = await cur.fetchone()
            if not row:
                merged = default_bot_config()
                merged["paper_balance_cents"] = c
                merged.pop("paper_lifetime_basis_cents", None)
                for lk in ALL_CFG_LAB_KEYS:
                    block = dict(merged.get(lk) or {})
                    block["paper_balance_cents"] = c
                    block.pop("paper_lifetime_basis_cents", None)
                    merged[lk] = expand_partial_lab_branch(lk, block)
                sync_live_paper_trading_keys(merged)
                payload = json.dumps(merged, default=str)
                await db.execute(
                    """
                    INSERT INTO config_history (branch_name, timestamp, config_json, changed_by, reason, audit_meta)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (br, ts, payload, history_changed_by, history_reason, None),
                )
                await db.execute("UPDATE bot_config SET json=? WHERE id=1", (payload,))
                await db.commit()
            else:
                raw = row["json"]
                parsed_obj: Any
                try:
                    parsed_obj = json.loads(raw)
                except (json.JSONDecodeError, TypeError, ValueError):
                    cfg = _normalize_loaded_config(default_bot_config())
                    _data_log(
                        "system",
                        {
                            "event": "bot_config_json_repaired",
                            "reason": "invalid_or_unreadable_json_uniform_paper",
                            "at": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                else:
                    if not isinstance(parsed_obj, dict):
                        cfg = _normalize_loaded_config(default_bot_config())
                        _data_log(
                            "system",
                            {
                                "event": "bot_config_json_repaired",
                                "reason": "json_not_object_uniform_paper",
                                "at": datetime.now(timezone.utc).isoformat(),
                            },
                        )
                    else:
                        cfg = _normalize_loaded_config(parsed_obj)
                cfg["paper_balance_cents"] = c
                cfg.pop("paper_lifetime_basis_cents", None)
                for lk in ALL_CFG_LAB_KEYS:
                    block = dict(cfg.get(lk) or {})
                    block["paper_balance_cents"] = c
                    block.pop("paper_lifetime_basis_cents", None)
                    cfg[lk] = expand_partial_lab_branch(lk, block)
                sync_live_paper_trading_keys(cfg)
                payload = json.dumps(cfg, default=str)
                await db.execute(
                    """
                    INSERT INTO config_history (branch_name, timestamp, config_json, changed_by, reason, audit_meta)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (br, ts, payload, history_changed_by, history_reason, None),
                )
                await db.execute("UPDATE bot_config SET json=? WHERE id=1", (payload,))
                await db.commit()
        return {
            "paper_balance_cents": c,
            "applied_to": ["live_paper", *ALL_CFG_LAB_KEYS],
            "paper_lifetime_basis_cents_cleared": True,
        }

    async def list_config_history(
        self, limit: int = 20, *, include_config: bool = False
    ) -> list[dict[str, Any]]:
        """
        Return the most recent entries from ``config_history`` (newest first). When
        ``include_config`` is False, only row metadata and ``config_bytes`` are returned (lighter for UI).
        """
        n = max(1, min(100, int(limit)))
        out: list[dict[str, Any]] = []
        async with self._open_db() as db:
            if include_config:
                cur = await db.execute(
                    """
                    SELECT id, branch_name, timestamp, config_json, changed_by, reason, audit_meta
                    FROM config_history
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (n,),
                )
            else:
                cur = await db.execute(
                    """
                    SELECT id, branch_name, timestamp, changed_by, reason, length(config_json) AS config_bytes, audit_meta
                    FROM config_history
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (n,),
                )
            rows = await cur.fetchall()
        for r in rows:
            d = dict(r)
            am = d.pop("audit_meta", None)
            if am is not None and str(am).strip():
                try:
                    d["audit_meta"] = json.loads(str(am))
                except (json.JSONDecodeError, TypeError, ValueError):
                    d["audit_meta"] = {"raw": str(am)[:4000]}
            else:
                d["audit_meta"] = None
            if include_config:
                raw = d.pop("config_json", None)
                if raw is not None:
                    try:
                        d["config"] = json.loads(str(raw))
                    except (json.JSONDecodeError, TypeError, ValueError):
                        d["config"] = None
            out.append(d)
        return out

    async def bump_lab_paper_lifetime_basis(self, branch: str) -> None:
        """
        After an auto lab wipe, add one more paper seed tranche to cumulative basis.

        Dashboard return % vs ``paper_lifetime_basis_cents`` (falling back to per-lab
        ``paper_balance_cents``) then reflects all capital ever re-seeded into that lab.
        """
        br = str(branch or "").strip().lower()
        if br not in ALL_CFG_LAB_KEYS:
            return
        cfg = await self.load_config()
        lab_key = br
        lab = dict(cfg.get(lab_key) or {})
        seed = int(lab.get("paper_balance_cents") or cfg.get("paper_balance_cents") or 500_000)
        prev = int(lab.get("paper_lifetime_basis_cents") or 0)
        if prev <= 0:
            prev = seed
        lab["paper_lifetime_basis_cents"] = prev + seed
        cfg[lab_key] = lab
        await self.save_config(cfg)

    async def insert_signal(self, row: dict[str, Any]) -> int:
        async with self._open_db() as db:
            cur = await db.execute(
                """
                INSERT INTO signals (
                  created_at, window_id, asset_id, ticker, side, implied_prob, minutes_left,
                  rule_name, executed, skip_reason, mode, extra_json, branch
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    row["created_at"],
                    row["window_id"],
                    row["asset_id"],
                    row["ticker"],
                    row["side"],
                    row.get("implied_prob"),
                    row.get("minutes_left"),
                    row.get("rule_name"),
                    1 if row["executed"] else 0,
                    row.get("skip_reason"),
                    row["mode"],
                    row.get("extra_json"),
                    normalize_trade_branch_for_db(row.get("branch")),
                ),
            )
            await db.commit()
            lr = cur.lastrowid
            rid = int(lr) if lr is not None else 0
        _data_log("signals", {"action": "insert", "id": rid, **row})
        return rid

    async def insert_trade(self, row: dict[str, Any]) -> int:
        async with self._open_db() as db:
            cur = await db.execute(
                """
                INSERT INTO trades (
                  created_at, mode, ticker, side, contracts_fp, limit_yes_dollars,
                  amount_cents, simulated, order_id, client_order_id, status, result, pnl_cents, settled_at, extra_json, branch
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    row["created_at"],
                    row["mode"],
                    row["ticker"],
                    row["side"],
                    row["contracts_fp"],
                    row.get("limit_yes_dollars"),
                    row["amount_cents"],
                    1 if row["simulated"] else 0,
                    row.get("order_id"),
                    row.get("client_order_id"),
                    row["status"],
                    row.get("result"),
                    row.get("pnl_cents"),
                    row.get("settled_at"),
                    row.get("extra_json"),
                    normalize_trade_branch_for_db(row.get("branch")),
                ),
            )
            await db.commit()
            lr = cur.lastrowid
            rid = int(lr) if lr is not None else 0
        _data_log("trades", {"action": "insert", "id": rid, **row})
        return rid

    async def insert_sim_trade_single_open_per_ticker(
        self,
        row: dict[str, Any],
        *,
        branch: str,
        trade_mode: str,
        market_ticker: str,
        series_exclusive_prefix: str | None = None,
    ) -> int | None:
        """
        Insert a simulated open trade only if no conflicting open/resting sim row exists for this branch.

        When ``series_exclusive_prefix`` is set (e.g. ``KXETH15M``), at most **one** open sim is allowed for any
        ticker starting with that prefix (one educated bet per series). Otherwise the legacy check applies:
        at most one open per **exact** market ticker.
        Uses BEGIN IMMEDIATE so the re-check and INSERT share one write lock.
        """
        tk = str(market_ticker or row.get("ticker") or "").strip().upper()
        if not tk:
            return await self.insert_trade(row)
        _ = trade_mode
        branch_db = normalize_trade_branch_for_db(branch)
        open_book = _sql_sim_open_book_predicate(branch_db)
        series_pat = _series_prefix_like_pattern(series_exclusive_prefix or "")
        async with self._open_db() as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                if series_pat:
                    cur = await db.execute(
                        f"""
                        SELECT COUNT(*) AS c FROM trades
                        WHERE {open_book}
                          AND UPPER(TRIM(ticker)) LIKE ? ESCAPE '\\'
                        """,
                        (series_pat,),
                    )
                else:
                    cur = await db.execute(
                        f"""
                        SELECT COUNT(*) AS c FROM trades
                        WHERE {open_book}
                          AND UPPER(TRIM(ticker)) = ?
                        """,
                        (tk,),
                    )
                r = await cur.fetchone()
                cnt = int(dict(r or {}).get("c") or 0) if r else 0
                if cnt >= 1:
                    await db.execute("ROLLBACK")
                    return None
                try:
                    cur = await db.execute(
                        """
                        INSERT INTO trades (
                          created_at, mode, ticker, side, contracts_fp, limit_yes_dollars,
                          amount_cents, simulated, order_id, client_order_id, status, result, pnl_cents, settled_at, extra_json, branch
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            row["created_at"],
                            row["mode"],
                            row["ticker"],
                            row["side"],
                            row["contracts_fp"],
                            row.get("limit_yes_dollars"),
                            row["amount_cents"],
                            1 if row["simulated"] else 0,
                            row.get("order_id"),
                            row.get("client_order_id"),
                            row["status"],
                            row.get("result"),
                            row.get("pnl_cents"),
                            row.get("settled_at"),
                            row.get("extra_json"),
                            branch_db,
                        ),
                    )
                    await db.commit()
                except sqlite3.IntegrityError:
                    try:
                        await db.execute("ROLLBACK")
                    except Exception:
                        pass
                    return None
                except Exception as e:
                    if "UNIQUE constraint failed" not in str(e):
                        raise
                    try:
                        await db.execute("ROLLBACK")
                    except Exception:
                        pass
                    return None
                lr = cur.lastrowid
                rid = int(lr) if lr is not None else 0
            except Exception:
                try:
                    await db.execute("ROLLBACK")
                except Exception:
                    pass
                raise
        _data_log("trades", {"action": "insert", "id": rid, **row})
        return rid

    async def update_trade_settlement(
        self,
        trade_id: int,
        result: str,
        pnl_cents: int,
        settled_at: str,
        *,
        extra_json: str | None = None,
    ) -> None:
        async with self._open_db() as db:
            if extra_json is not None:
                await db.execute(
                    "UPDATE trades SET result=?, pnl_cents=?, settled_at=?, status=?, extra_json=? WHERE id=?",
                    (result, pnl_cents, settled_at, "settled", extra_json, trade_id),
                )
            else:
                await db.execute(
                    "UPDATE trades SET result=?, pnl_cents=?, settled_at=?, status=? WHERE id=?",
                    (result, pnl_cents, settled_at, "settled", trade_id),
                )
            await db.commit()
        _data_log(
            "trades",
            {
                "action": "settle",
                "trade_id": trade_id,
                "result": result,
                "pnl_cents": pnl_cents,
                "settled_at": settled_at,
            },
        )

    async def update_trade_sim_early_close(
        self,
        trade_id: int,
        *,
        pnl_cents: int,
        settled_at: str,
        result: str,
        extra_json: str,
    ) -> None:
        """Paper sim: close an open/resting row before Kalshi finalization (e.g. swing exit at bid)."""
        async with self._open_db() as db:
            await db.execute(
                """
                UPDATE trades
                SET result=?, pnl_cents=?, settled_at=?, status=?, extra_json=?
                WHERE id=? AND simulated=1 AND LOWER(COALESCE(status,'')) IN ('open','resting')
                """,
                (result, pnl_cents, settled_at, "settled", extra_json, trade_id),
            )
            await db.commit()
        _data_log(
            "trades",
            {
                "action": "swing_close",
                "trade_id": trade_id,
                "result": result,
                "pnl_cents": pnl_cents,
                "settled_at": settled_at,
            },
        )

    async def insert_equity_snapshot(
        self,
        created_at: str,
        mode: str,
        equity_cents: int,
        note: str,
        branch: str = "live",
        *,
        mtm_equity_cents: int | None = None,
    ) -> None:
        async with self._open_db() as db:
            await db.execute(
                "INSERT INTO equity_snapshots (created_at, mode, equity_cents, mtm_equity_cents, note, branch) VALUES (?,?,?,?,?,?)",
                (created_at, mode, equity_cents, mtm_equity_cents, note, branch),
            )
            await db.commit()
        try:
            from .data_log import maybe_log_equity

            maybe_log_equity(
                {
                    "action": "insert",
                    "created_at": created_at,
                    "mode": mode,
                    "equity_cents": equity_cents,
                    "mtm_equity_cents": mtm_equity_cents,
                    "note": note,
                    "branch": branch,
                }
            )
        except Exception:
            pass

    async def recent_signals(self, limit: int = 200) -> list[dict[str, Any]]:
        async with self._open_db() as db:
            cur = await db.execute(
                "SELECT * FROM signals ORDER BY id DESC LIMIT ?", (limit,)
            )
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def recent_trades(self, limit: int = 200) -> list[dict[str, Any]]:
        async with self._open_db() as db:
            cur = await db.execute("SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,))
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def dashboard_branch_trade_rollups(self, branch: str, trade_mode: str) -> dict[str, Any]:
        """
        Full-table aggregates for one branch + trade mode (not capped at recent N rows).
        Settled / fee slices still use ``trade_mode`` (paper vs live). Open sim **premium** uses
        ``_sql_sim_open_book_predicate`` (same rows as ``open_sim_trades_for_branch``). The dashboard
        may replace ``open_sim_trades`` with a Holdings-visible **asset-row** count (configured series only).
        """
        async with self._open_db() as db:
            bp = _sql_branch_predicate(branch)
            cur = await db.execute(
                f"""
                SELECT
                  COALESCE(SUM(pnl_cents), 0) AS total_pnl_cents,
                  COUNT(*) AS settled_n,
                  COALESCE(SUM(CASE WHEN pnl_cents > 0 THEN 1 ELSE 0 END), 0) AS wins,
                  COALESCE(SUM(CASE WHEN pnl_cents < 0 THEN 1 ELSE 0 END), 0) AS losses,
                  COALESCE(SUM(CASE WHEN pnl_cents = 0 THEN 1 ELSE 0 END), 0) AS scratches,
                  MIN(created_at) AS first_settled_ca,
                  MAX(created_at) AS last_settled_ca
                FROM trades
                WHERE {bp}
                  AND LOWER(COALESCE(status, '')) = 'settled'
                  AND pnl_cents IS NOT NULL
                  AND (
                    mode = ?
                    OR (? = 'simulate' AND COALESCE(mode, '') = '' AND simulated = 1)
                  )
                """,
                (trade_mode, trade_mode),
            )
            settled_row = await cur.fetchone()
            # Open sim book: same predicate as ``open_sim_trades_for_branch`` (no ``mode`` filter) so
            # committed premium and MTM use the same open rows as the store list; Holdings line count may differ.
            cur2 = await db.execute(
                f"""
                SELECT COUNT(*) AS open_n, COALESCE(SUM(amount_cents), 0) AS open_cents
                FROM trades
                WHERE {_sql_sim_open_book_predicate(branch)}
                """
            )
            open_row = await cur2.fetchone()
            cur3 = await db.execute(
                f"""
                SELECT extra_json
                FROM trades
                WHERE {bp}
                  AND (
                    mode = ?
                    OR (? = 'simulate' AND COALESCE(mode, '') = '' AND simulated = 1)
                  )
                """,
                (trade_mode, trade_mode),
            )
            fee_rows = await cur3.fetchall()

        sr = dict(settled_row) if settled_row else {}
        orow = dict(open_row) if open_row else {}
        total_fee_cents = 0
        for r in fee_rows or []:
            try:
                raw = dict(r).get("extra_json")
                ex = json.loads(str(raw or "{}"))
            except Exception:
                ex = {}
            # Count modeled fees across all paper close paths:
            # - entry (open)
            # - swing exit
            # - settlement close
            # - timeout close
            # - patient stop-loss close
            # plus legacy/generic ``exit_fee_cents`` if present.
            fee_keys = (
                "entry_fee_cents",
                "swing_exit_fee_cents",
                "settlement_exit_fee_cents",
                "auto_timeout_exit_fee_cents",
                "patient_stop_loss_exit_fee_cents",
                "exit_fee_cents",
            )
            for fk in fee_keys:
                try:
                    total_fee_cents += int(ex.get(fk) or 0)
                except (TypeError, ValueError):
                    continue
        return {
            "total_pnl_cents": int(sr.get("total_pnl_cents") or 0),
            "total_fee_cents": max(0, int(total_fee_cents)),
            "settled_n": int(sr.get("settled_n") or 0),
            "wins": int(sr.get("wins") or 0),
            "losses": int(sr.get("losses") or 0),
            "scratches": int(sr.get("scratches") or 0),
            "first_settled_ca": sr.get("first_settled_ca"),
            "last_settled_ca": sr.get("last_settled_ca"),
            "open_n": int(orow.get("open_n") or 0),
            "open_committed_cents": int(orow.get("open_cents") or 0),
        }

    async def open_sim_trades_for_branch(self, branch: str) -> list[dict[str, Any]]:
        async with self._open_db() as db:
            cur = await db.execute(
                f"""
                SELECT * FROM trades
                WHERE {_sql_sim_open_book_predicate(branch)}
                ORDER BY id DESC
                """
            )
            rows = await cur.fetchall()
            out: list[dict[str, Any]] = []
            seen_ids: set[int] = set()
            for r in rows:
                d = dict(r)
                rid = d.get("id")
                if rid is not None:
                    try:
                        ii = int(rid)
                    except (TypeError, ValueError):
                        ii = None
                    if ii is not None:
                        if ii in seen_ids:
                            continue
                        seen_ids.add(ii)
                out.append(d)
            return out

    async def has_open_sim_for_ticker(self, branch: str, trade_mode: str, market_ticker: str) -> bool:
        """
        True if this branch already has a simulated open/resting row for this **exact** Kalshi market ticker.

        ``trade_mode`` is kept for call-site compatibility; open rows are matched like ``open_sim_trades_for_branch``
        (no ``mode`` filter) so legacy rows cannot hide from this check while still listed in holdings.
        """
        _ = trade_mode
        tk = str(market_ticker or "").strip().upper()
        if not tk:
            return False
        async with self._open_db() as db:
            cur = await db.execute(
                f"""
                SELECT 1 FROM trades
                WHERE {_sql_sim_open_book_predicate(branch)}
                  AND UPPER(TRIM(ticker)) = ?
                LIMIT 1
                """,
                (tk,),
            )
            row = await cur.fetchone()
        return row is not None

    async def has_open_sim_for_series_prefix(self, branch: str, series_prefix: str) -> bool:
        """
        True if this branch already has any simulated open/resting row whose ticker starts with
        ``series_prefix`` (Kalshi series family, e.g. KXETH15M). Used to enforce one open sim per series.
        """
        pat = _series_prefix_like_pattern(series_prefix)
        if not pat:
            return False
        async with self._open_db() as db:
            cur = await db.execute(
                f"""
                SELECT 1 FROM trades
                WHERE {_sql_sim_open_book_predicate(branch)}
                  AND UPPER(TRIM(ticker)) LIKE ? ESCAPE '\\'
                LIMIT 1
                """,
                (pat,),
            )
            row = await cur.fetchone()
        return row is not None

    async def first_open_sim_ticker_for_series_prefix(self, branch: str, series_prefix: str) -> str | None:
        """
        Newest open-sim row whose market ticker is under this series family (same filter as
        :meth:`has_open_sim_for_series_prefix`). When non-empty, a new bet in that family is blocked; return the
        blocking ticker for Activity log / ``skip_reason`` text.
        """
        pat = _series_prefix_like_pattern(series_prefix)
        if not pat:
            return None
        async with self._open_db() as db:
            cur = await db.execute(
                f"""
                SELECT TRIM(ticker) FROM trades
                WHERE {_sql_sim_open_book_predicate(branch)}
                  AND UPPER(TRIM(ticker)) LIKE ? ESCAPE '\\'
                ORDER BY id DESC
                LIMIT 1
                """,
                (pat,),
            )
            row = await cur.fetchone()
        if not row or row[0] is None:
            return None
        s = str(row[0]).strip()
        return s or None

    async def open_committed_cents_for_branch_mode(self, branch: str, trade_mode: str) -> int:
        """
        Sum of premium tied up in open/resting simulated rows for one branch + mode.
        For simulate mode, legacy empty mode rows are treated as simulate.
        """
        async with self._open_db() as db:
            cur = await db.execute(
                f"""
                SELECT COALESCE(SUM(amount_cents), 0) AS open_cents
                FROM trades
                WHERE {_sql_branch_predicate(branch)}
                  AND simulated = 1
                  AND LOWER(COALESCE(status, '')) IN ('open', 'resting')
                  AND (
                    mode = ?
                    OR (? = 'simulate' AND COALESCE(mode, '') = '')
                  )
                """,
                (trade_mode, trade_mode),
            )
            row = await cur.fetchone()
        if not row:
            return 0
        d = dict(row)
        return int(d.get("open_cents") or 0)

    async def equity_series(self, limit: int = 500, branch: str | None = None) -> list[dict[str, Any]]:
        async with self._open_db() as db:
            if branch:
                cur = await db.execute(
                    f"SELECT * FROM equity_snapshots WHERE {_sql_branch_predicate(branch)} ORDER BY id DESC LIMIT ?",
                    (limit,),
                )
                rows = await cur.fetchall()
                # Newest-first query → reverse to chronological order for charts / slopes.
                return [dict(r) for r in reversed(rows)]
            cur = await db.execute(
                "SELECT * FROM equity_snapshots ORDER BY id ASC LIMIT ?", (limit,)
            )
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def query_table(
        self,
        table: str,
        *,
        branch: str | None = None,
        mode: str | None = None,
        ticker: str | None = None,
        start_at: str | None = None,
        end_at: str | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        if table not in {"signals", "trades", "equity_snapshots"}:
            raise ValueError("unsupported table")
        where: list[str] = []
        params: list[Any] = []
        if branch:
            bn = str(branch).strip().lower()
            if bn == "sim_lab":
                bn = "lab_a"
            if bn != "live" and bn not in ALL_CFG_LAB_KEYS:
                raise ValueError(
                    f"branch filter must be live, a parent lab, lab_child_1..6, or sim_lab (legacy) (got {branch!r})"
                )
            where.append(_sql_branch_predicate(bn))
        if mode and table in {"signals", "trades", "equity_snapshots"}:
            m = str(mode).strip()
            # Simulated rows historically used empty ``mode``; match engine rollups when filtering simulate.
            if m == "simulate" and table in ("signals", "trades"):
                where.append("(mode = ? OR COALESCE(mode, '') = '')")
                params.append(m)
            else:
                where.append("mode = ?")
                params.append(m)
        if ticker and table in {"signals", "trades"}:
            where.append("ticker LIKE ?")
            params.append(f"%{ticker}%")
        if start_at:
            where.append("created_at >= ?")
            params.append(start_at)
        if end_at:
            where.append("created_at <= ?")
            params.append(end_at)
        ws = f"WHERE {' AND '.join(where)}" if where else ""
        sql = f"SELECT * FROM {table} {ws} ORDER BY id DESC LIMIT ? OFFSET ?"
        params.extend([max(1, min(10000, int(limit))), max(0, int(offset))])
        async with self._open_db() as db:
            cur = await db.execute(sql, tuple(params))
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def insert_optimizer_recommendation(
        self,
        *,
        created_at: str,
        window_start: str | None,
        window_end: str | None,
        source_branches: list[str],
        summary: str,
        recommendation_json: dict[str, Any],
        raw_json: dict[str, Any] | None = None,
    ) -> int:
        async with self._open_db() as db:
            cur = await db.execute(
                """
                INSERT INTO optimizer_recommendations
                (created_at, window_start, window_end, source_branches, summary, recommendation_json, raw_json)
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    created_at,
                    window_start,
                    window_end,
                    json.dumps(source_branches),
                    summary,
                    json.dumps(recommendation_json),
                    json.dumps(raw_json) if raw_json is not None else None,
                ),
            )
            await db.commit()
            lr = cur.lastrowid
            return int(lr) if lr is not None else 0

    async def recent_optimizer_recommendations(self, limit: int = 50) -> list[dict[str, Any]]:
        async with self._open_db() as db:
            cur = await db.execute(
                "SELECT * FROM optimizer_recommendations ORDER BY id DESC LIMIT ?",
                (max(1, min(500, int(limit))),),
            )
            rows = await cur.fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            for k in ("source_branches", "recommendation_json", "raw_json"):
                try:
                    d[k] = json.loads(d[k]) if d.get(k) else None
                except Exception:
                    pass
            out.append(d)
        return out

    _EXPORT_TABLES = ("signals", "trades", "equity_snapshots")

    async def dump_trading_tables_jsonl(self, dest_dir: Path, ts: str) -> list[str]:
        """Write all rows of trading tables to ``<table>_<ts>.jsonl`` under ``dest_dir``."""
        written: list[str] = []
        dest_dir.mkdir(parents=True, exist_ok=True)
        async with self._open_db() as db:
            for table in self._EXPORT_TABLES:
                cur = await db.execute(f"SELECT * FROM {table} ORDER BY id")
                rows = await cur.fetchall()
                path = dest_dir / f"{table}_{ts}.jsonl"
                with path.open("w", encoding="utf-8") as f:
                    for r in rows:
                        f.write(json.dumps(dict(r), default=str) + "\n")
                written.append(str(path.resolve()))
        return written

    async def reset_trading_data(
        self, *, backup: bool = True, branch: str | None = None, vacuum: bool = False
    ) -> dict[str, Any]:
        """
        Delete signals, trades, and equity snapshots. Keeps ``bot_config``.

        * ``branch`` is None / ``\"all\"`` / empty: delete **all** rows (legacy behaviour).
        * ``branch`` in ``live`` / ``lab_a`` / ``lab_b`` / ``lab_c`` / ``lab_d``: delete only rows for that branch
          (Lab A predicate includes legacy ``sim_lab``).

        When ``backup`` is True, copies the SQLite file and exports JSONL dumps under ``DATA_LOG_DIR/exports``.

        ``vacuum`` defaults to False: ``VACUUM`` can fail or stall on Windows when the file is busy;
        ordinary deletes are enough for correctness.
        """
        exports: list[str] = []
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        log_root = Path(env.data_log_dir)
        if not log_root.is_absolute():
            log_root = _REPO_ROOT / log_root
        export_dir = log_root / "exports"
        if backup:
            export_dir.mkdir(parents=True, exist_ok=True)
            try:
                src = Path(self.path)
                if src.is_file():
                    dest_sql = export_dir / f"bot_{ts}.sqlite3.bak"
                    shutil.copy2(src, dest_sql)
                    exports.append(str(dest_sql.resolve()))
            except OSError as e:
                exports.append(f"sqlite_copy_error:{e}")
            try:
                dumped = await self.dump_trading_tables_jsonl(export_dir, ts)
                exports.extend(dumped)
            except OSError as e:
                exports.append(f"jsonl_export_error:{e}")
        br_arg = str(branch or "").strip().lower()
        scope = "all" if br_arg in ("", "all") else br_arg
        _allowed = ("all", "live", *ALL_CFG_LAB_KEYS)
        if scope not in _allowed:
            raise ValueError(f"invalid reset branch: {branch!r}")
        pred = None if scope == "all" else _sql_branch_predicate(scope)
        async with self._open_db() as db:
            if pred is None:
                await db.execute("DELETE FROM equity_snapshots")
                await db.execute("DELETE FROM signals")
                await db.execute("DELETE FROM trades")
            else:
                await db.execute(f"DELETE FROM equity_snapshots WHERE {pred}")
                await db.execute(f"DELETE FROM signals WHERE {pred}")
                await db.execute(f"DELETE FROM trades WHERE {pred}")
            await db.commit()
            if vacuum:
                try:
                    await db.execute("VACUUM")
                    await db.commit()
                except Exception as e:
                    exports.append(f"vacuum_skipped:{e}")
        _data_log(
            "system",
            {
                "event": "reset_trading_data",
                "backup": backup,
                "branch": scope,
                "vacuum": vacuum,
                "exports": exports,
                "at": datetime.now(timezone.utc).isoformat(),
            },
        )
        return {"ok": True, "backup": backup, "branch": scope, "exports": exports}
