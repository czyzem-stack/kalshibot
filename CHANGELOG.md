# Changelog

All notable project-level changes should be documented in this file.

## v0.4.01 - Versioning policy (patch train under v0.4) - 2026-04-27

- **Versioning:** After **v0.4**, routine releases use **patch** numbers **`v0.4.01`**, **`v0.4.02`**, … in [`VERSION`](VERSION) until the operator asks for a **bump** (next minor/major, e.g. **v0.5**). See **Versioning going forward** at the bottom of this file.

## v0.4 - Further README clarity and minor observability polish - 2026-04-27

- **Docs:** README beginner polish for Labs Breeding + Optimizer; expanded **Quick Start – Breeding Mode** with click-paths and a **first 30–60 minutes** timeline; **Production readiness** clarifies child-lab tiles vs Optimizer/Tree; new **Monitoring Breeding** subsection (strip, Tree, toasts); **Paper vs live fees** comparison table under breeding fitness.
- **Dashboard:** compact **Breeding** status pill on the **Branch performance** card header (same `GET /api/optimizer/status` poll as the Optimizer strip); click scrolls to the Optimizer card and selects **Tree**.

## v0.3 - Enhanced observability, audit trail, and README clarity - 2026-04-27

- **Dashboard:** **Breeding** pool / death-chamber strip on the **Optimizer** card (polls `GET /api/optimizer/status` ~45s); click opens **Tree** mode on the same card. **Optimizer \| Breeder \| Tree** footer toggles; mutation dial + lab pulse stay above the tab row. Breeder/Tree reuse cached status when switching tabs to avoid skeleton flicker.
- **Dashboard fix:** `BranchHeroMarquee` defines **`cashLiveStr`** for the Live snapshot row (was a missing binding and could blank the entire SPA).
- **Audit:** `config_history` gains optional **`audit_meta`** JSON; disabling Live paper with `confirm=YES` via `PUT /api/config` or `POST /api/engine/toggle` records confirm token, request body or query snapshot, and client IP / User-Agent / common proxy headers.
- **Docs:** README overhaul—optimizer + breeding integration, production readiness & limitations, **Quick Start – Breeding Mode** checklist, fee-model notes for breeding fitness; **VERSION** bump to `v0.3`.
- **Tests:** extra rule-matching / `pick_trade_rule` guard coverage and audit assertion for paper-disable path.

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

- **Patch train (default):** From **v0.4** onward, incremental work ships as **`v0.4.01`**, **`v0.4.02`**, **`v0.4.03`**, … (three-part tag in `VERSION` + matching `CHANGELOG` section title). Agents and contributors bump this for every merge-worthy slice unless the operator says otherwise.
- **Bump (explicit only):** When the operator says **“bump”** (or names a new minor/major, e.g. **v0.5**), advance the **middle or major** segment and reset the patch (e.g. **v0.5** or **v0.5.01** per whatever scheme is agreed then)—do not keep incrementing `0.4.x` after a deliberate bump.
- Add a **dated** section per release and summarize **behavior-impacting** changes; doc-only patch entries are fine with a single-line summary.
