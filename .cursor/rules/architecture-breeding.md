# Breeding vs visible paper labs (operator architecture)

**Last updated:** April 2026

This document explains the **two independent “testing” paths** in Kalshibot and how **`optimizer.breeding_enabled`** fits next to **`optimizer.enabled`** and **`optimizer.adaptive_enabled`**.

## Two paths (do not conflate them)

1. **Visible paper trading (dashboard charts & Branch performance)**  
   **`dual_engine_loop`** ticks **Live** + **Lab A–D** and **child** branches (`lab_child_1`…`lab_child_6`) on `poll_seconds`. Fills, signals, and equity for B/C/D in the main UI are **this** path. If “nothing is moving” on a lab tile, the usual causes are **engine off** for that branch, **no rule match**, or **per-series caps** (see `series_has_open_sim` in logs, grep: `series_open_sim`).

2. **Child-lab GA / Labs Breeding (B, C, D → child slots, adoption, culls)**  
   Implemented in **`lab_breeding.py`**, driven from config via **`run_optimizer_once`** in **`optimizer_claude.py`**. It replays **paper** history, mints or culls children, and may adopt into Lab A. This is **not** the same as “B/C/D charts are updating”; charts can be flat while breeding still **ticks** and writes **telemetry** (`breeding_last_run_at`, `breeding_last_summary` on **`GET /api/optimizer/status`**).

## Config flags (backward compatible defaults)

| Key | Default | Effect |
|-----|---------|--------|
| `optimizer.enabled` | `true` | **Scheduled** full optimizer: cycle counter, Lab A adaptive, internal mutation path, and (if `breeding_enabled`) the breeding block. |
| `optimizer.adaptive_enabled` | `true` | Lab A adaptive / win-relax and related **adaptive** behavior in the full tick (requires full tick to run; see `run_optimizer_once`). |
| `optimizer.breeding_enabled` | `true` | B/C/D **child-lab** pipeline (hard death, soft cull, ~30m GA). Can run on the same interval **even when** `enabled` and `adaptive_enabled` are both **false** via the **breeding-only** path (`_run_breeding_only_tick`). |

**Idle loop:** If all three are false, the optimizer **background task** does nothing and logs once (grep: `optimizer_loop_idle`).

## Operator FAQ

- **“B/C/D aren’t testing”** — Distinguish **no chart movement** (tick loop, rules, series cap) from **no breeding** (optimizer flags). Tail logs with `grep=breeding_` and `series_open_sim`.  
- **30-minute GA** — `LAB_BREEDING_GENERATION_INTERVAL` in `lab_breeding.py`; skips log `grep=breeding_ga_cooldown`.  
- **Replacement cooldown** (soft cull / adoption) — `labs_breeding_replace_cooldown_until`; soft cull skip logs `grep=breeding_soft_cull`.  
- **Parent with no / zero equity** — GA may skip a breeder; logs `grep=breeding_parent_equity`.  

## Source references

- **Tick loop (paper):** `backend/app/engines/dual_engine_loop.py`  
- **Series cap (sim):** `backend/app/engines/engine.py` (structured log `grep=series_open_sim`)  
- **Breeding + GA:** `backend/app/lab_breeding.py`  
- **Scheduler / full vs breeding-only tick:** `backend/app/optimizer_claude.py` (`run_optimizer_once`, `_run_breeding_only_tick`)  
- **Background task gate:** `backend/app/main.py` (`_optimizer_loop`)  
- **API:** `GET /api/optimizer/status` (`breeding_enabled`, `breeding_last_run_at`, `breeding_last_summary`, `breeding_last_run_minutes_ago`); `PUT /api/optimizer/config` can set `breeding_enabled`.

## v0.4.15.0 additions (Unified breeder + family tree upgrade)

- **Parent selection is now tournament-based and explainable:** top-3 breeders are ranked by replay fitness + recent momentum, then selected with a 70%/20%/10% elite/diversity split.
- **Every child carries a "why" story:** pairing emits `breeder_reason`, `breeder_reason_short`, `synergy_score`, `parent_ids`, `mutated_traits`, and `fitness_delta_vs_parents`.
- **Tree snapshot is now lineage-rich:** `labs_breeding_tree_snapshot` includes parent fitness/reason and child-node summaries suitable for compact hierarchical rendering in the Family tab (who bred whom and why).
