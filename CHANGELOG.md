# Changelog

All notable project-level changes should be documented in this file.

## v0.4.15.010 - Lab E full-stack UI + optimizer radar - 2026-04-28

- **Frontend:** Lab **E** wired through **branch performance**, **equity** (six small multiples + compare overlay), **Assets to watch**, **Account** holdings/engine tabs, **optimizer thinking radar** (seven traces), **hero marquee/snapshot**, **Lab pulse**, **ActivityHints** for D/E engines, **promote Lab A→Live** vs B/C/D/E, **Settings** (engines, patient stop, simulation labs bulk save/reset, optimizer Lab E toggles/style/floors), and **help playbook** copy. **`BranchMarketTickers`:** `lab_e` in hero order, norms, positions, compact segments. **`labHiveChat`:** Breeding Council header (“working together”); **`balanceHiveMessagesForTicker`** now round-robins **lab_e** with B/C/D (was omitting E).
- **Backend:** Lab E metrics/equity/engine/dashboard/API/optimizer paths; **`lab_communication._voice_prefix`** returns **`E:`** for **`lab_e`** (was **`?:`**).
- **Backend (`persistence.py`):** Breeding Council parents **B/C/D/E** never persist with empty **`rules`** (would override globals and freeze signals): **`_ensure_breeder_labs_have_rules`** copies global rules or injects a loose BTC/ETH-friendly pack. **`default_bot_config`** seeds each breeder with **`rules`**, looser **`no_bet_when_yes_below_pct`**, slightly lower optimizer **yes_floor** / **min_minutes_left** for **B/D/E**, and **`engine_running: true`** on **B–E** so fresh installs tick immediately after restart.
- **Backend (`engines/engine.py`, `kalshi_client.py`, `market_pulse.py`):** Guard **`/markets`** and balance payloads so a non-**dict** (or bad cache value) never reaches **`.get("markets")`** / **`.get("balance")`** — fixes **`NoneType` … `'get'`** on Lab E and other branches when the API or cache returns an unexpected shape.
- **Backend (`main.py`):** **`_lab_thought_lines`** treats a missing/non-dict **`metrics`** as **`{}`** so dashboard **`lab_thoughts`** never throws for Lab E.
- **Backend (`lab_communication.py`):** Extra short **Think Tank** team lines (**E+C** / **B/D** / **Lab A** handoff) in strategic pulses and peer replies.
- **Backend (`engines/dual_engine_loop.py`):** Module docstring now lists **Lab A–E** (loop already ticked **`lab_e`** via **`BRANCH_LABS`**).
- **Frontend (`BranchMarketTickers.tsx`):** **`branchHeadlineDollars`** coerces null/invalid **`metrics`** to **`{}`** before reading equity fields.
- **Frontend (`dashboardPolling.ts`):** Comment documents keeping **`equity_snapshots_lab_*`** / **`metrics_lab_*`** in sync with **`App.tsx`** catch-up keys (includes **`lab_e`**).

## v0.4.15.009 - Lab Think Tank variety + balance - 2026-04-28

- **Backend (`lab_communication.py`):** Much larger **peer/strategic** template pools; **`_pick_varied`** avoids lines too close to the last **8** bus messages (word-overlap / prefix guard). **`_c_overrepresented`** blocks **C** proactive pulses when C dominates the tail; **`_needs_voice_turn`** boosts **B/D** when quiet or when **C** has run the board. **`_team_peer_reply_line`** expanded dual- and single-peer lines + team tags.

## v0.4.15.008 - Lab Think Tank pure team dialogue - 2026-04-28

- **Backend (`lab_communication.py`):** Think Tank copy is **dialogue-only**: rewritten **`_contextual_strategic_pulse`** and council path via **`_team_peer_reply_line`** (natural back-and-forth, B/C/D names, agree/but/interesting/building on). **Max ~62 chars.** Ranked-market hook **publishes nothing** (no ticker dumps). Sim opens emit **peer-anchored team lines** instead of ticker narration. Stronger rotation when **not all three** labs appear in the recent tail.
- **Frontend (`LabThinkTank.tsx`, `styles.css`):** Latest **5** lines; tighter padding/gaps/fonts.

## v0.4.15.007 - Lab Think Tank dialogue + ultra-compact UI - 2026-04-28

- **Backend (`lab_communication.py`):** Messages capped **<70** chars; council reply gaps **6–15s**; strategic pulses rewritten for explicit **B/C/D back-and-forth** (agree/but/interesting/building on); `reply_to` still anchors to latest other lab; **`_needs_voice_turn`** biases underrepresented labs so all three stay in rotation; catch-up council timing when a lab is behind.
- **Frontend (`LabThinkTank.tsx`, `styles.css`):** Latest **6** lines only; tighter padding/line-height — denser console strip in Optimizer.

## v0.4.15.006 - Lab Think Tank cadence + visibility fixes - 2026-04-28

- **Backend (`lab_communication.py`):** Loosened proactive share cap / shorter rolling window; **bootstrap phase** (first ~16 bus lines) skips share throttling so messages appear immediately; faster council (**~2–9s**) and strategic (**~8–18s**) gaps; intros schedule the next pulse in **~3–8s** (was tied to the full gap); **`publish_think_tank_break_silence_if_due`** escapes share-cap deadlock so overrepresented labs still speak after ~14s quiet; ranked-market pings no longer double-block on share cap; UI polling interval **2.5s**.
- **Frontend (`dashboardPolling.ts`, `LabThinkTank.tsx`):** Faster `/labs/chat` polling; clearer empty-state copy when engines haven’t published yet.

## v0.4.15.005 - Lab Think Tank conversational threading - 2026-04-28

- **Backend (`lab_communication.py`):** Rolling **last 4** thread tail drives prompts; strategic pulses **anchor** to another lab’s latest line (`reply_to` UUID); council replies include **`reply_to`**; messages capped **70** chars; council gaps **8–18s**; contextual ranked/sim lines optional **`reply_to`**.
- **Frontend (`LabThinkTank.tsx`, `styles.css`, `labHiveChat.tsx`):** Optional **`reply_to`** on rows; compact log shows **→** when replying to the **previous visible** line.

## v0.4.15.004 - Lab Think Tank v5 (compact UI + short agent banter) - 2026-04-28

- **Backend (`lab_communication.py`):** Messages capped ~**65–78** chars; pulses **18–35s**; faster council replies (**6–14s** gap); tighter proactive share cap (**0.34**); short intros / ranked pings / sim lines / breeding whispers.
- **Frontend (`LabThinkTank.tsx`, `styles.css`):** Max **~180px** viewport; latest **8** lines; tight **live-log** rows (emoji + B/C/D + message); removed chat-thread styling.

## v0.4.15.003 - Breeding Council Think Tank (Labs B/C/D in Optimizer) - 2026-04-28

- **Frontend:** Removed header lab ticker; added collapsible **Lab Think Tank** panel under Optimizer (pulse strip) with council transcript UI; Settings toggle renamed **Enable Agent Collaboration** (`LAB_COLLABORATION_STORAGE_KEY`, migrates legacy chat key).
- **Backend (`lab_communication.py`):** Renamed conceptually to think tank / Breeding Council — slower strategic pulses (~25–50s), council replies, rare ranked-market analysis, sim-open narration; structlog event **`think_tank_message`**; `finalize_think_tank_tick(..., full_cfg=)` reads **`optimizer.breeding_enabled`** for breeding-themed lines without touching `lab_breeding.py`.
- **Backend (`engines/engine.py`):** Wires think-tank finalize with full config; engine state keys **`_lab_think_tank_*`**.

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
