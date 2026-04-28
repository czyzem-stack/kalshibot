# Changelog

All notable project-level changes should be documented in this file.

## v0.4.15.002 - Lab Agent Chatter v4 (balanced B/C/D + ticker readability) - 2026-04-28

- **Backend (`lab_communication.py`):** Fair rotation (~34% soft cap on proactive lines per lab), chain replies driven by `last_from_other()` with short agree/disagree/build-on copy, heartbeats on **12–28s**, one bootstrap line per lab after restart, single proactive headline per tick, messages capped for marquee length.
- **Backend (`engines/engine.py`):** Tracks chatter headline/bootstrap/publish timestamps; resets headline flag each tick.
- **Frontend (`LabTicker.tsx`, `styles.css`):** Two-line pair columns, slower marquee, larger lab glyphs (🟡/🔥/🧪), stronger lab colors; respects reduced-motion.

## v0.4.15.001 - Header version badge placement + unified version bump - 2026-04-28

- **Frontend (`frontend/src/App.tsx`, `frontend/src/styles.css`):** moved the UI track and app version pills from the title cluster to the right-side header actions, placing them next to Settings for a cleaner top bar layout.
- **Versioning:** bumped unified stack version from **v0.4.15.0** to **v0.4.15.001** across `VERSION`, README/version references, and breeding metadata labels.

## v0.4.15.0 - Unified versioning + Breeder explainability & Family Tree visualizer upgrade - 2026-04-28

- **Versioning:** Standardized project branding to **v0.4.15.0** across backend/frontend/docs and removed separate breeder/family sub-version labels.
- **Backend (`lab_breeding.py`):** Labs Breeding uses tournament-style parent selection (top-3 rank, 70% elite / 20% runner-up / 10% diversity pick), explicit **breeder reasons**, and trait-complementarity **synergy_score** for each pairing.
- **Backend (`lab_breeding.py`):** Child origin metadata is now richer and explainable: `parent_ids`, `parent_fitness`, `inherited_rules_count`, `mutated_traits`, `breeder_reason`, `breeder_reason_short`, `synergy_score`, and `fitness_delta_vs_parents`.
- **Backend (`lab_breeding.py`):** `build_labs_breeding_tree_snapshot` upgraded with parent fitness/reason fields and child-node story fields (`fitness_delta`, short/full reason, inherited trait summary, parent labels, mutation list), while preserving old DB compatibility and existing caps/cooldowns.
- **Frontend (`frontend/src/App.tsx`):** Family tab now renders as a compact hierarchical tree (parents row, connector spine, child nodes with parent arrows, fitness delta, "why" summary, trait badges) within the existing panel footprint.
- **Frontend (`frontend/src/App.tsx`):** Family double-click overlay is now story-focused: selecting a child shows lineage path, full reason text, synergy, inherited rules, and mutated traits so users can see **who bred whom and why** at a glance.

## v0.4.09 - Dashboard catch-up + fast equity MTM timeout + sim settle `amended` - 2026-04-26

- **Frontend:** `frontend/src/dashboardPolling.ts` — on **tab visible**, **`pageshow`**, and **`online`**, immediately refresh **`GET /api/dashboard`** and **`GET /api/dashboard/equity`** so the UI does not stay stale while background tabs throttle `setInterval` (editing via Vite previously looked like the “fix” because Fast Refresh remounted the poll effect).
- **Backend:** `DASHBOARD_FAST_MTM_GATHER_TIMEOUT_S` (default **22**s, env-clamped) replaces a hard **5s** `asyncio.wait_for` around parallel paper MTM refresh on the fast equity route; timeouts log a warning instead of silently freezing MTM vs book until the next full dashboard poll.
- **Backend:** `settle_simulated_trades` treats Kalshi **`amended`** (post-dispute re-determination) like other terminal/determined statuses so paper rows settle when the API exposes a yes/no outcome.

## v0.4.08 - `all_labs` reset includes Live (SQLite + charts) - 2026-04-28

- **API:** `POST /api/data/reset?branch=all_labs` and `PUT /api/config/lab-branches` with `reset_data=all_labs` now also delete **Live** signals, trades, and `equity_snapshots` (previously only Labs A–D, so the Live branch chart still showed old history). Equity snapshot re-seed after reset includes **Live** first.
- **UI:** Settings bulk reset copy updated: **“Reset Live + all labs (A–D)**” and matching confirm text.

## v0.4.07 - Local develop + main only (drop test worktree stack) - 2026-04-27

- **Scripts:** Remove optional third stack: delete **`setup-test-worktree.ps1`**, **`bootstrap-test-worktree.ps1`**, **`launch-test-sidecar.ps1`**. **`launch_local.ps1`** and **`update_all_worktrees.ps1`** only handle **develop** + **main** (Vite **5174** + **5173**, APIs **8765** + **8770**). **`-SkipTestSidecar`**, **`-TestWorktreePath`**, and **`KALSHIBOT_TEST_WORKTREE`** are no longer used.
- **Bootstrap:** **`bootstrap-main-worktree.ps1`** / **`setup-main-worktree.ps1`:** **`CORS_ORIGINS`** default is **5173+5174** only (no **:5175**).
- **Frontend:** **`uiTrack.ts`** infers **dev**/**main** from port **5174**/**5173** and **8770**; removed **:5175** and **:8775** auto-mapping (explicit **`VITE_UI_TRACK=test`** still works for rare cases).
- **Docs:** README / **`.env.example`** updated for the two-stack workflow.
- **Scripts:** **`launch_local.ps1`** with a **main** sidecar no longer opens a **separate** window for **develop** Vite; **:5174** runs in the terminal you launched from, and only **:5173** (main UI) + API windows use extra PowerShell windows.

## v0.4.06 - Optional `test` worktree + triple local launch - 2026-04-27

- **Scripts:** **`setup-test-worktree.ps1`** / **`bootstrap-test-worktree.ps1`** add a sibling **`[test]`** git worktree (default `../Kalshibot-test`) with API **8775**, Vite **5175**, and its own **`data/bot.sqlite3`** under that checkout. **`launch_local.ps1`** starts develop + optional main + optional test in parallel; **`-SkipTestSidecar`** / **`-SkipMainSidecar`** omit stacks. **`launch-test-sidecar.ps1`** runs test only.
- **Scripts:** **`launch_local.ps1`** / **`launch-test-sidecar.ps1`** resolve the test checkout by **`KALSHIBOT_TEST_WORKTREE`**, then **`git worktree list` `[test]`**, then sibling **`Kalshibot-test`** / **`kalshibot-test`** if either has a **`.git`** (any branch)—so the third stack runs without requiring the git branch to be named `test` when the folder convention matches.
- **Scripts:** **`launch_local.ps1`** now auto-invokes **`bootstrap-main-worktree.ps1`** / **`bootstrap-test-worktree.ps1`** when a sidecar has **`.git`** but no **`.env`**, and runs **`setup-test-worktree.ps1`** for missing conventional **`..\Kalshibot-test`** (unless **`KALSHIBOT_TEST_WORKTREE`** overrides the path)—so a single **`.\scripts\launch_local.ps1`** run can bring up **5175** without separate copy-paste bootstrap steps.
- **Scripts:** **`update_all_worktrees.ps1`** runs **`git fetch`** + **`git pull --ff-only`** on develop + main + test paths (same discovery rules); optional **`-Pip`** / **`-Npm`** refresh deps in each checkout that has **`.venv`** / **`frontend`**. **`launch_local.ps1`** fix: define **`$repoCanon`** in **`Resolve-TestWorktreeRoot`** when scanning sibling test folders.
- **`bootstrap-main-worktree.ps1`** / **`setup-main-worktree.ps1`:** default **`CORS_ORIGINS`** examples now include **:5175** for triple-local.
- **Frontend:** **`VITE_UI_TRACK=test`**, port **8775** inference, tab title **Chomp's Diner test**, pill styles **`.ui-track-pill--test`** (`frontend/src/uiTrack.ts`, `styles.css`, `App.tsx` tooltip).
- **Docs:** README environment matrix, scripts table, and **test → develop → main** promotion diagram notes.
- **Local Vite:** fixed convention — **main = :5173**, **develop = :5174**, **test = :5175** (`launch_local.ps1`, `launch-main-sidecar.ps1`, `frontend/vite.config.ts` default, README; CORS still lists all three).

## v0.4.05 - Fleet committed % and child labs default on - 2026-04-27

- **Dashboard / API:** Branch performance **committed** subtitle uses **`committed_pct_of_fleet_start`** when present: open premium as a % of **combined** configured paper starts (Live when in paper mode + Labs A–D). **`committed_pct_of_start`** remains per-branch. New helper **`fleet_visible_paper_start_cents`** in `branch_config.py`.
- **Breeding child engines (`lab_child_*`):** Defaults and runtime treat children as **on** unless **`engine_running` is explicitly `false`** (e.g. cleared slot after eviction). **`merge_branch_config`**, **`dual_engine_loop`**, and **`POST` breeding** new-slot writes align with that; default config sets **`engine_running`: true** for all six child keys.

## v0.4.04 - Dual UI tab title and track pill - 2026-04-27

- **Frontend:** Browser tab title is **`Chomp's Diner beta`** when this UI targets the develop stack (`VITE_UI_TRACK=dev` or default when `VITE_API_ORIGIN` is not port **8770**), and **`Chomp's Diner live`** for the main sidecar (`main` / `live` track or **8770** in the API origin). `index.html` default title is **`Chomp's Diner`** until the SPA mounts.
- **Bootstrap:** Main worktree `frontend/.env` also gets **`VITE_UI_TRACK=main`** (with **`VITE_API_ORIGIN`**) so the title row pill and tab text stay aligned without hand-editing.

## v0.4.03 - Separate DBs per checkout (env path resolution) - 2026-04-27

- **Settings:** `SQLITE_PATH` and `DATA_LOG_DIR` treat **relative** values as paths under **this checkout’s repo root** (not the process working directory), so develop and a sibling `main` worktree keep distinct SQLite and JSONL trees by default. `launch_local.ps1` warns if both `.env` files set the same explicit `SQLITE_PATH` string. `setup-main-worktree.ps1`’s `ENV_SIDECAR.example` now includes `SQLITE_PATH` + `DATA_LOG_DIR` lines for clarity.
- **Scripts:** `launch_local.ps1` discovers the `main` worktree via `git worktree list` (not only `..\Kalshibot-main`) and prints a **yellow reason** when dual UI is skipped (missing checkout vs missing `.env`).
- **Scripts:** `bootstrap-main-worktree.ps1` runs `setup-main-worktree.ps1` if needed, then creates/updates the worktree **`.env`** and **`frontend/.env`** from develop (or examples) with sidecar ports and CORS so **`launch_local.ps1`** can start dual UI without manual merges.

## v0.4.02 - Parallel `main` worktree (run stable while developing) - 2026-04-27

- **Dev workflow:** `scripts/setup-main-worktree.ps1` adds a sibling **`main`** git worktree (default `../Kalshibot-main`) with example env for **API 8770** + **Vite 5173**; `scripts/launch-main-sidecar.ps1` starts that stack alone. **`launch_local.ps1`** can start **develop + main** (Vite **5174** + **5173**) when the worktrees have `.env`; the main API uses the worktree’s **`.venv`** when it exists. `scripts/run_backend_at.ps1` runs uvicorn from an arbitrary repo root.
- **Docs:** README developer note on two checkouts, ports, and not double-writing Live with the same keys.

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
