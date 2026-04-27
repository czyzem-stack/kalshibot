# Changelog

All notable project-level changes should be documented in this file.

## v0.2 - 2026-04-27

- **Dashboard charts:** `ChartDblClickExpand` listens for `dblclick` in the **capture** phase so Recharts SVG (equity lines, compare overlay, optimizer radar) still opens the enlarge overlay when double-clicking on the plot.
- **Breeder:** personality radar wrapped in the same expand overlay; shared `BreederPersonalityRadarChart` helper.
- **Cursor:** optional project rule `.cursor/rules/kalshibot-operating-contract.mdc` (locked architecture + safety) for agents using this repo.

## v0.0 - 2026-04-26

- Optimizer **v0.1** (internal): advanced replay fitness, status-only observability (`GET /api/optimizer/status`), no new `OPTIMIZER_*` env vars or dashboard `optimizer_advanced_metrics` (documented in README).
- Baseline version tag for the Phase 1-4 + final optimization series.
- Startup and cache performance documentation finalized.
- WebSocket-first Kalshi orderbook integration and typed API cleanup finalized.

## Versioning going forward

- Use semantic-style tags from this baseline (`v0.1`, `v0.2`, etc.).
- Add a dated section per release and summarize behavior-impacting changes.
