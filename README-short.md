# Kalshibot (Chomp's Diner)

Self-hosted **Kalshi** stack: **FastAPI + React**, **Live + Lab A–E** (+ optional **child** labs) on your machine — rules, fills, equity, and an **optimizer** with explainable **Labs Breeding** and a **Breeding Council Think Tank** (B–E).

| | |
|---|---|
| **Version** | See [`VERSION`](VERSION) · [`CHANGELOG.md`](CHANGELOG.md) |
| **Stand-out** | **Labs Breeding** closed loop (B–E parents → `lab_child_*` → pool/death chamber → gated adoption → Lab A) · Family tree + Breeder radar · Lab A–E parity · Mass apply / lab-branches toggles · Think Tank = dialogue only · Lab A–only promotion to Live |

## Quick start (Windows)

1. `.\scripts\create_venv.ps1`
2. Copy `.env.example` → `.env` (Kalshi keys + ports)
3. `.\scripts\launch_local.ps1`
4. UI → `http://127.0.0.1:5174` (see script for API port)

## Docs

- Full guide: [`README.md`](README.md)
- Breeding architecture: [`.cursor/rules/architecture-breeding.md`](.cursor/rules/architecture-breeding.md)
- Changelog: [`CHANGELOG.md`](CHANGELOG.md)
