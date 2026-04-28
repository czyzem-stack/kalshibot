# Kalshibot (Chomp's Diner)

> **What this is:** A **self-hosted** Kalshi trading stack - FastAPI + React - that polls markets, executes JSON probability/time-based rules, records fills in SQLite, and runs **Live + four paper labs + up to six child breeding labs** in parallel. It includes an advanced **Optimizer** with internal tuning, optional Claude suggestions, and **Labs Breeding** that evolves strategies through tournament selection, trait synergy, and full explainability.

**v0.4.15.001** - Unified versioning, explainable Breeder engine, and a beautiful compact **Family Tree visualizer** in the Optimizer panel.

**If you are new here:**
- **Branch performance** and **Equity** show **Live + Lab A-D**.
- Child labs (`lab_child_1`...`lab_child_6`) run silently in the background.
- Watch breeding via the **Breeding** pill (Branch performance), the **Breeding** row (Optimizer card), and the **Tree** tab (shows the new hierarchical family tree).
- Everything stays on **your machine** - no third-party custody, no shared keys.

**Key Features**
- **Real family-tree visualizer** - Compact hierarchical layout with connector lines, parent arrows, fitness deltas, one-line "why" reasons, and trait badges.
- **Explainable Breeder** - Tournament selection (70/20/10), weighted fitness + recent momentum, synergy scores, and human-readable breeding stories.
- **Fleet-wide committed %** - One unified risk view across Live + Labs A-D.
- **Always-on child labs** by default.
- **Patient stop-loss**, fee-aware scoring, rule-based edge detection.
- **Beautiful local dashboard** with equity curves, personality radar, lineage, and live breeding telemetry.

**Runbooks:** [Quick Start (Windows)](#quick-start-windows) · [Full Installation & Run Options](#full-installation--run-options) · [Quick Start - Breeding Mode](#quick-start---breeding-mode) · [Monitoring Breeding](#monitoring-breeding) · [Configuration](#configuration-highlights) · [API Overview](#api-overview) · [Dashboard UI Map](#dashboard-ui-map-optimizer-card)

---

## Breeding vs Chart Testing (Architecture)

**Shorthand:**
- **Chart** = dual engine loop (Live + Lab A-D + children).
- **Breeding** = genetic-style evolution inside the optimizer loop (`lab_breeding.py`).

Full details and grep keys: [`.cursor/rules/architecture-breeding.md`](.cursor/rules/architecture-breeding.md).

**Version:** `v0.4.15.001` (unified across the entire stack).

---

## Production Readiness & Known Limitations

| Area                  | Current State                                      | What to Expect |
|-----------------------|----------------------------------------------------|----------------|
| **Auth**              | Optional bearer token                              | No built-in multi-user RBAC |
| **Child labs**        | Real engines (`lab_child_1`-`6`)                   | Visible only via Breeding pill + Tree tab |
| **Fees in breeding**  | Same paper fee model as optimizer                  | Consistent sim scoring (not byte-for-byte live Kalshi fees) |
| **Personality radar** | Derived from traits + sizing                       | Great for comparison, not absolute truth |
| **Tests**             | Strong on engine core; lighter on breeding         | Focus on rule guards and money-path |

**Monitoring tip:** Use the **Breeding pill**, **Optimizer Breeding row**, and **Tree** tab together. All powered by `GET /api/optimizer/status`.

---

## Quick Start - Breeding Mode

### One-page checklist (2 minutes)

1. **Settings (gear)** -> **Optimizer** tab -> Enable **"Enable scheduled optimizer loop"** -> Save.
2. Go to **Branch performance** card -> look for the **Breeding** pill (pool / death chamber counts).
3. Scroll to **Optimizer** card -> click **Breeding** row or footer **Tree** tab.
4. Watch the new **Family Tree** appear with parent arrows, reasons, and trait badges.

**What you'll see in the first 30-60 minutes:**
- Breeding pill and Tree start populating after the first generation cycle (~30 min default).
- Rich "who bred whom and why" stories appear automatically.

**Safety notes:**
- Only **Lab A** can be promoted to Live.
- Hard deaths refill immediately; soft culls have a 5-minute cooldown.

---

## Monitoring Breeding

| Surface              | Location                          | Purpose |
|----------------------|-----------------------------------|--------|
| **Breeding pill**    | Branch performance title row      | Quick pool / death chamber counts (click -> Tree) |
| **Breeding row**     | Optimizer card                    | Summary + click to Tree |
| **Tree tab**         | Optimizer card footer             | Full **Family Tree visualizer** + Lineage / Children / Cullings / Log |

---

## Dashboard UI Map (Optimizer Card)

The **Optimizer** card now features:
- **Optimizer** tab - 6-axis thinking radar + mutation dial
- **Breeder** tab - 12-axis personality radar
- **Tree** tab - **New hierarchical Family Tree v0.4.15.001** with:
  - Breeder parents row (Lab B · C · D with fitness)
  - Vertical connector spine
  - Child cards showing short ID, parent arrow (`<- Lab B + Lab D`), fitness + delta, one-line reason, trait badges
  - Click any child for full breeding story (synergy score, inherited rules, mutated traits, lineage path)
  - Double-click anywhere for rich modal overlay

**Everything fits in the original panel footprint.**

---

## Labs Breeding (Current)

The breeding engine is now significantly more intelligent and transparent:
- **Tournament selection** with 70/20/10 elite/diversity weighting
- **Weighted scoring** (77% fitness + 23% recent momentum)
- **Rich metadata** on every child: `breeder_reason`, `breeder_reason_short`, `synergy_score`, `fitness_delta_vs_parents`, inherited traits, etc.
- **Family Tree visualizer** makes the entire evolutionary process visible and addictive to watch

**Lab A** remains the only staging/adoption lab that can be promoted to Live.

---

## What It Does (Core)

- **Live** - Real-money or paper (configurable)
- **Lab A-D** - Isolated paper strategies for comparison
- **Child labs (1-6)** - Background breeding population (always on by default)
- **Optimizer** - Internal tuning + optional Claude + genetic breeding
- **Persistence** - SQLite (`data/bot.sqlite3`) + optional JSONL logs
- **Dashboard** - Real-time equity curves, signals, trades, settings, and breeding telemetry

---

## Quick Start (Windows)

(See the installation section below for macOS/Linux, Docker, and production options.)

1. `.\scripts\create_venv.ps1`
2. Copy `.env.example` -> `.env` and configure Kalshi keys
3. `.\scripts\launch_local.ps1` (starts API + Vite dev server)

Open **http://localhost:5174** (develop branch).

---

## Full Installation & Run Options

- **Windows (recommended):** Use the `scripts/*.ps1` helpers.
- **macOS / Linux:** Manual venv + uvicorn + `npm run dev`.
- **Docker:** See Dockerfile + volume for `data/`.
- **Production:** Build `frontend/dist/` and serve behind nginx/Caddy with API proxy.

---

## Configuration Highlights

- All settings live in **Settings (gear)** overlay or raw JSON.
- `live_paper_trading` (canonical paper mode for Live).
- `optimizer.enabled` + `optimizer.breeding_enabled`.
- Per-lab overlays via `merge_branch_config`.
- Patient stop-loss, fees, rules, assets - all tunable.

---

## API Overview

Interactive docs at `http://127.0.0.1:8765/docs`.

Key endpoints:
- `GET /api/dashboard` and `/api/dashboard/equity`
- `GET /api/optimizer/status` (breeding + Family Tree data)
- `PUT /api/config` and `/api/config/lab-branches`
- `POST /api/config/promote-lab-a-to-live`
- `POST /api/data/reset` (scoped reset for live/labs/all_labs/all)
- `POST /api/engine/toggle` and `GET /api/engine/status`

---

## Operator Responsibility

This is **operator-grade self-hosted software**. Real money can be at risk when `simulate` is off on Live. You are responsible for risk management, compliance, and monitoring.

---

## License

MIT License.
