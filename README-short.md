# Kalshibot (Chomp's Diner)

Self-hosted Kalshi trading stack: **FastAPI + React**, with **Live + Lab A-D + up to six child breeding labs** running in parallel on your own machine.

## Why it stands out

- **Unified version:** `v0.4.15.008`
- **Explainable Breeder:** tournament parent selection (70/20/10), momentum-aware scoring, synergy metadata, and readable child "why" reasons
- **Family Tree UI:** compact hierarchical tree in the Optimizer panel with parent arrows, deltas, badges, and story drill-down
- **Risk controls:** patient stop-loss, fee-aware scoring, branch isolation, and Lab A-only promotion path to Live

## What you get

- **Dashboard:** branch performance, equity curves, optimizer radar, breeder telemetry
- **Persistence:** SQLite (`data/bot.sqlite3`) + optional JSONL logs
- **API:** `/api/dashboard`, `/api/dashboard/equity`, `/api/optimizer/status`, `/api/config`, and more

## Quick start (Windows)

1. `.\scripts\create_venv.ps1`
2. Copy `.env.example` to `.env` and set Kalshi credentials
3. `.\scripts\launch_local.ps1`
4. Open `http://localhost:5174`

## Read more

- Full docs: [`README.md`](README.md)
- Breeding architecture: [`.cursor/rules/architecture-breeding.md`](.cursor/rules/architecture-breeding.md)
