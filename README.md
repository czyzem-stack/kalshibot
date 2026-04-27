# Kalshibot

> **What this is (one sentence):** a **self-hosted** Kalshi trading stack—**FastAPI** + **React**—that polls markets, matches **JSON probability/time rules**, records fills in **SQLite**, and runs **Live** and **four paper labs** in parallel, with an optional **optimizer loop** (internal tuning plus optional **Claude**) that reads all labs but only **auto-persists** sizing-style changes for **Lab A** under guardrails. **Labs Breeding v0.1** adds up to **six** parallel **child** paper branches (`lab_child_1`…`lab_child_6`) with real engines in the dual loop, breeder-driven genomes, adoption/replacement from the pool, and a **Breeder** dashboard mode (personality radar from **`GET /api/optimizer/status`**).

It connects to [Kalshi's API](https://docs.kalshi.com/getting_started/api_keys), runs **rule-based engines** per branch, and ships a **Vite** dashboard for config, charts, and health—**no separate hosted control plane**; your keys and data stay on the machine you run it on.

**Runbooks:** [Quick start (Windows)](#quick-start-windows) · [macOS / Linux](#macos-and-linux-manual) · [Configuration](#configuration) · [API overview](#api-overview) · [Operator flows (diagrams)](#operator-flows-sequences-and-visuals) · [Dashboard (UI map)](#dashboard-ui-map) · [Labs breeding v0.1](#labs-breeding-v01-at-a-glance) · [Optimizer visualizations](#optimizer-visualizations) · [Performance and startup](#performance-and-startup) · [Developer notes](#developer-notes)

**Version:** `v0.2` in [`VERSION`](VERSION) / [`CHANGELOG.md`](CHANGELOG.md) (see **v0.2** for latest dashboard fixes; **v0.0** remains the historical baseline note). The **optimizer** stack includes **v0.1** behavior internally (advanced replay scoring, structured Claude proposals with held-out checks)—see **Optimizer upgrade v0.1** under [Optimizer: internal pulse vs Claude](#optimizer-internal-pulse-vs-claude). **Labs Breeding v0.1** ships in the same tree (child lab engines, `lab_breeding.py`, dashboard **Breeder** view). There are **no** new `OPTIMIZER_*` environment variables and **no** extra advanced-metrics panel on the default Optimizer card; power users read **`GET /api/optimizer/status`** for proposal history, advanced metrics, and **labs breeding** fields (log, children, lineage, personality radar, cooldown timestamps).

**Default workflow:** work on the **`develop`** branch for changes, then merge to **`main`** for release; both should track `origin` the same way if you use a two-branch flow. The UI is a single **Vite** SPA: hot reload in dev, **`npm run build`** for `frontend/dist/`; the API is stateful (SQLite, engine loops) so always restart uvicorn when changing **Python** engine or persistence code.

**Security reminder:** the stack is **intended to run on your own host** (localhost or a private server). The FastAPI app has no built-in multi-user auth—anyone who can reach the API port can change config if you bind beyond loopback. Use a firewall, VPN, or reverse auth if you expose it.

---

## Patient stop-loss (loss-recoup exit)

**Patient stop-loss** is a **paper** (simulated) safety valve that can automatically close a losing open position after a **minimum hold** and when **fee-aware unrealized P&L%** (mark-to-exit after modeled sell fees vs total cash debited at entry) is at or below a **negative threshold**. It is designed to cut depth-of-loss without reacting to the first wiggle: you set **on/off**, **min_hold_minutes_before_stop**, and **stop_loss_trigger_pct** in **Settings** (and per **lab** overlay where applicable). Live in **non-paper** (real) mode does not run this path; Labs are always sim.

| Lab / branch | Role (A/B testing) | Typical patient stop defaults (illustrative) |
|-------------|--------------------|-----------------------------------------------|
| **Live** | Production account; paper when `live_paper_trading` / `simulate` is on | Tuned in Settings; conservative vs labs depends on your saved JSON |
| **Lab A** | Primary experiment; promote-to-Live and optimizer focus | Slightly **tighter** stop / shorter hold in seeded defaults (staging) |
| **Lab B** | Conservative reference arm | **Moderate** threshold & hold (reference) |
| **Lab C** | Moderate–aggressive reference | Between B and D |
| **Lab D** | Aggressive paper reference | **Wider** threshold / different hold in seeded defaults |

Exact numbers live in `default_bot_config()` and your SQLite config; the table reflects the **5-way** **Live + A + B + C + D** layout for comparing how patient exits interact with rules and fees.

---

## Recent Architectural Improvements

| Topic | What changed |
|--------|----------------|
| **Config history** | Every save appends a row to the **`config_history`** table (branch tag, timestamp, full JSON, who/why). The legacy **`bot_config`** single row remains the active config. **GET `/api/config/history`** returns the latest entries for audit; use `include_config=true` for full snapshots. |
| **Money-path tests** | `backend/tests/test_engine_money_path.py` covers non-negative sizing, patient stop gating, promotion fitness helpers, and **confirm-gated** disable of paper mode on Live. |
| **Simulate / paper flag** | Canonical key **`live_paper_trading`** (mirrors legacy **`simulate`**). Disabling paper on Live via **`PUT /api/config`** or **`POST /api/engine/toggle`** requires `confirm=YES`; attempts are logged. |
| **Dashboard API** | Heavier work is split: **`GET /api/dashboard/equity`** (frequent poll, skips slow mark refresh), plus **`/open_positions`**, **`/orderbooks`** (short TTL cache off full runs), **`/recent_trades`**. The UI polls the light equity route more often than the full **`GET /api/dashboard`**. |
| **Labs Breeding v0.1** | Hidden **`lab_child_1`…`lab_child_6`** engines, breeder/adoption logic in **`lab_breeding.py`**, personality radar + status fields on **`GET /api/optimizer/status`**; dashboard **Breeder** mode (footer toggle) is read-only telemetry—**Lab A → Live** promotion rules unchanged. |

---

## Labs Breeding v0.1 (at a glance)

**Purpose.** Paper-only **genetic-style** experimentation alongside the visible labs: breeders produce child genomes into up to **six** parallel child branches; **Lab A** may **adopt** strong children under code gates. This does **not** change **who may be promoted to Live** (**Lab A only**, with existing PnL + confirm gates) or any **real-money** path.

| Topic | Detail |
|--------|--------|
| **Where it runs** | Invoked from the **optimizer tick** via **`run_optimizer_once`** (`backend/app/optimizer_claude.py`) into **`lab_breeding.py`**—same scheduling family as internal pulse / optional Claude, not a second background daemon. |
| **Engines** | **`dual_engine_loop`** settles, snapshots, and ticks **Live + Labs A–D + `lab_child_1`…`lab_child_6`** when those child keys exist in SQLite config with an assigned genome (`backend/app/engines/dual_engine_loop.py`). |
| **Breeders vs staging** | **`BRANCH_BREEDERS`:** Labs **B, C, D** mint offspring into free child slots. **Lab A does not breed**; it is the **staging / adoption** lab (`branch_config.py` + `lab_breeding.py` docstrings). |
| **Genetics** | Children carry **`_labs_breeding_traits`** (`aggressiveness`, `risk_tolerance`, `adaptivity`, `exploration`, `resilience`) plus **`_labs_breeding_origin`** lineage metadata; crossover and mutation combine parent genomes; pool / refill rules handle **hard death** vs **soft cull**. |
| **Cadence** | **`LAB_BREEDING_GENERATION_INTERVAL`** = **30 minutes** in `lab_breeding.py` (wall-clock class constant used by the breeding scheduler inside the optimizer pass). |
| **Lifecycle & cooldown** | **Hard** (e.g. zero-equity) **death** → replacement **without** the 5-minute gate. **Soft cull** and **adoption** record **`labs_breeding_replace_cooldown_until`** (**5 minutes**) to limit churn. **`labs_breeding_death_chamber`** and **`labs_breeding_lineage_history`** are **capped** lists for the status route. |
| **Adoption vs Live** | Adoption into **Lab A** uses **minimum settled-trade** thresholds (e.g. `MIN_SETTLED_FOR_ADOPTION_COMPARE`, `MIN_SETTLED_FOR_SOFT_CULL` in code) plus replay-style fitness context—**gated**, not “auto-Live”. **Promote Lab A → Live** remains the **only** path to copy overlays onto **Live**. |
| **Personality radar** | **`labs_breeding_personality_radar`** exposes **twelve** mood axes (**`MOOD_DIMENSIONS`** in `lab_breeding.py`—Aggressive, Greedy, …, Methodical), each **0–100**, derived from traits + sizing for **read-only** UI (no extra persisted keys for the chart). |
| **Logs & toasts** | **`labs_breeding_log`** (and related slices on **`GET /api/optimizer/status`**) may include **`toast_id` / `toast_family`** for ephemeral dashboard toasts; full audit remains **config + `config_history`** on real saves. |

**Primary files:** `backend/app/lab_breeding.py`, `backend/app/branch_config.py`, `backend/app/optimizer_claude.py`, `backend/app/engines/dual_engine_loop.py`, `backend/app/routers/optimizer_routes.py`, `backend/app/types_api.py` (response shape), `frontend/src/App.tsx` (Optimizer vs Breeder card).

---

## What it does

- **Live branch** — Uses your Kalshi account when credentials are configured. With **simulate** mode on, Live behaves as **paper** (no real orders). With simulate off and the engine on, the bot can **place real limit orders** according to your rules (you are responsible for risk and compliance).
- **Lab A through D** — Separate **simulated** branches with their own paper bankrolls, rules and sizing knobs, and metrics so you can compare strategies without touching Live.
- **Engines** — Background loops scan markets, evaluate rules, and manage positions per branch (see `backend/app/engine.py`).
- **Dashboard** — Single-page UI: branch performance, equity charts, holdings, signals and trades, Kalshi connection status, settings (rules, filters, sizing, engines, optimizer), historical export, and more. The dev server proxies `/api` to the backend. A small **optimizer health** pill (green / yellow / red from internal trace acceptance) sits in the **top bar next to the settings (⚙) control** (hover for a tooltip); it is not shown on the bottom ticker strip.
- **Persistence** — Config (active row + **`config_history`** audit table), trades, signals, and snapshots are stored under `data/` (default SQLite: `data/bot.sqlite3`). Optional **JSONL** logs for signals and trades (and optional equity logging) under `data/logs/` when enabled in `.env`.
- **Optimizer (optional)** — Scheduled or manual analysis can suggest config tweaks; optional Claude-style HTTP calls use `ANTHROPIC_API_KEY` when set (see `.env.example`). The dashboard does not ship a separate “Claude rule editor” surface—**Settings** holds serious config. The main **Optimizer** card defaults to **Optimizer** mode: **“Optimizer Thinking (Lab A)”** radar, **mutation** summary row, and **lab pulse** ticker. Use the **Optimizer \| Breeder** control in the **bottom-right footer** of that same card for **Labs Breeding v0.1**: a **twelve-axis** personality radar fed by **`GET /api/optimizer/status`** (no chart legend—**Recharts `Tooltip`** identifies branches on hover). See [Labs breeding v0.1](#labs-breeding-v01-at-a-glance) and [Breeder view](#breeder-view-labs-breeding-v01). The default radar is **internal optimizer telemetry**; the Breeder radar is **derived display** from traits and sizing knobs.
- **Polling** — The UI leans on **`GET /api/dashboard/equity`** and focused routes for high-frequency updates and **`GET /api/dashboard`** for heavier “full” snapshots, so a slow home Wi‑Fi or large open-book payload does not block the whole page forever.

---

## Operator flows, sequences, and visuals

This section is the **“how do I read the system in motion?”** companion to the tables above. It adds **sequence-style flows**, **merge semantics** for the split dashboard API, and **ASCII** sketches you can paste into design docs.

### Visual: logical stack (browser → API → disk)

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Browser (http://localhost:5173)                                         │
│  ┌──────────────┐   ┌─────────────────┐   ┌──────────────────────────┐ │
│  │ React SPA    │──▶│ Vite /api proxy │──▶│ FastAPI :8765 (or exe)     │ │
│  │ App.tsx      │   │ (vite.config)   │   │ main.py + routers          │ │
│  └──────────────┘   └─────────────────┘   └─────────────┬────────────┘ │
└──────────────────────────────────────────────────────────┼──────────────┘
                                                             │
                    ┌────────────────────────────────────────┴──────────────┐
                    │  asyncio tasks (lifespan)                               │
                    │  dual_engine_loop  │  optimizer_loop  │  KalshiClient │
                    └────────────────────────────┬───────────────────────────┘
                                                 │
                                    ┌────────────▼────────────┐
                                    │ SQLite + optional JSONL │
                                    │ data/bot.sqlite3        │
                                    └─────────────────────────┘
```

**Rule of thumb:** if the **UI** misbehaves, check **origin** (5173 vs raw API port) first; if **data** looks wrong, check **branch** columns in SQLite before blaming the chart.

### Flow A — first dashboard load (happy path)

```mermaid
sequenceDiagram
  autonumber
  participant U as Operator browser
  participant V as Vite dev server
  participant A as FastAPI /api/dashboard
  participant K as Kalshi REST
  participant S as SQLite

  U->>V: GET / (SPA shell)
  U->>V: GET /api/dashboard (proxied)
  V->>A: forward JSON + optional Bearer
  A->>S: read config, trades, signals, equity_series…
  A->>K: portfolio / public probe (as implemented)
  K-->>A: JSON
  A-->>V: 200 Dashboard JSON
  V-->>U: hydrate React state (dash non-null, hide loading)

  Note over U,A: Every ~12s: full /api/dashboard again; every ~4s: /api/dashboard/equity merge (no slow mark pass).
```

**Frozen loading screen?** The SPA must receive a **valid JSON object** once; use **Network** tab to confirm **`/api/dashboard`** is **200** and not blocked by auth. The UI merges **equity-only** polls into the previous payload so a partial route cannot strip optimizer or breeding fields.

### Flow B — split dashboard polling (what merges where)

| Poll | Interval (UI default) | What it skips / includes | Merge rule in UI |
|------|------------------------|---------------------------|------------------|
| **`GET /api/dashboard`** | ~12s | Full payload including heavier mark refresh when `with_marks=True` | Replaces baseline dashboard state (deduped in-flight + epoch guard in `App.tsx`). |
| **`GET /api/dashboard/equity`** | ~4s | Same schema as full dashboard **without** the slow mark pass (`with_marks=False`) | **Shallow merge** `{ ...prevDash, ...equityJson, config: preferNonEmpty }` so nested `optimizer_activity` survives between full polls. |
| **`GET /api/dashboard/recent_trades`** | separate effect | Trades slice for toast merge | Merges into toast stream, not the main `dash` object. |

```mermaid
flowchart LR
  subgraph ui [React dashboard]
    D[dash state]
  end
  F["GET /api/dashboard\n(full)"]
  E["GET /api/dashboard/equity\n(light)"]
  F -->|baseline replace| D
  E -->|merge into prev| D
```

### Flow C — paper trade path (one branch)

```mermaid
flowchart TD
  T[dual_engine_loop tick] --> M[Scan markets / assets cfg]
  M --> R{rule_matches?}
  R -- no --> T
  R -- yes --> P[pick_trade_rule + sizing]
  P --> O{Open / sim guardrails}
  O -- blocked --> L[Log / not_traded_signals]
  O -- ok --> X[Insert simulated trade row\nbranch = lab_x or live]
  X --> S[settle_simulated_trades / swing / timeout handlers]
  S --> Q[SQLite trades updated]
  Q --> N[snapshot_equity per branch]
  N --> E[(equity_snapshots + branch column)]
```

Each **branch** column in **`equity_snapshots`** and **`trades`** is authoritative: identical **chart shapes** across labs usually mean **shared tape + similar rules**, not a single shared array (see fingerprint lines under equity charts in the UI).

### Flow D — promote **Lab A → Live** (decision sketch)

```mermaid
flowchart TD
  start([Operator clicks Promote]) --> gate{Settled PnL cents\nLab A > B,C,D ?}
  gate -- no --> deny[API 400 + UI message]
  gate -- yes --> real{Live real-money\nsimulate off ?}
  real -- yes --> ack{ack_live token\nAPPLY_LIVE}
  ack -- missing --> warn[UI prompts token]
  ack -- ok --> copy[Deep-copy LAB_BRANCH_OVERLAY_KEYS\nfrom lab_a → root]
  real -- no paper live --> copy
  copy --> save[Persist bot_config + config_history]
  save --> done([Live uses merged overlays\nengines unchanged unless edited])
```

### Flow E — Optimizer card modes (default vs Breeder)

| Mode | Primary data route | What you see |
|------|-------------------|--------------|
| **Optimizer** (default) | `GET /api/dashboard` slices (`optimizer_activity`, metrics, …) | Six-axis **Optimizer Thinking** radar, mutation row, lab pulse ticker. **Report** opens structured overlay; **double-click** radar expands. |
| **Breeder** | `GET /api/optimizer/status` | Twelve-axis **personality radar** (traits-derived); spinner while fetching; tooltips identify series. |

```mermaid
flowchart LR
  subgraph card [Optimizer card footer]
    O[Optimizer mode]
    B[Breeder mode]
  end
  O --> DASH[GET /api/dashboard]
  B --> ST[GET /api/optimizer/status]
  DASH --> RAD6[6-axis radar + pulse]
  ST --> RAD12[12-axis radar]
```

### Flow F — config overlays (mental checklist)

1. **Edit JSON** in Settings → `PUT /api/config` (validated paths).
2. **Per-lab keys** in `lab_a`…`lab_d` override only keys listed in **`LAB_BRANCH_OVERLAY_KEYS`** (`branch_config.py`).
3. **Engines read** `merge_branch_config(full_cfg, branch)` each tick — you never hand-merge in the DB manually during normal ops.
4. **Audit** prior versions via **`GET /api/config/history`** (optional `include_config=true`).

### ASCII — branch families (visible vs hidden)

```
VISIBLE ON DASHBOARD STRIP          HIDDEN ENGINES (breeding slots)
──────────────────────────          ───────────────────────────────
Live   Lab A   Lab B   Lab C   Lab D     lab_child_1 … lab_child_6
  │       │       │       │       │                 │
  └───────┴───────┴───────┴───────┴─────engine loop─┴─ same dual_engine_loop
```

### Quick triage table (symptoms → where to look)

| Symptom | Likely layer | First checks |
|---------|--------------|--------------|
| Spinner never ends | UI ↔ API | 5173 origin, `/api/dashboard` status, bearer token match, browser console. |
| Charts identical | Data vs perception | SQLite `branch` on `equity_snapshots`; UI fingerprint “pts / book / settled” per chart. |
| 429 storms | Kalshi client | Logs for `Retry-After`; reduce concurrent markets or enable WS cache path. |
| Optimizer flat | Cold start / no trades | Wait for settles; verify `optimizer.enabled` and scheduler gates in config. |
| Breeder empty | Status route | `GET /api/optimizer/status` JSON; ensure breeding generation interval elapsed. |

### Environment matrix (where secrets and ports live)

| Surface | Typical origin | Kalshi keys | API port | UI |
|---------|----------------|-------------|----------|-----|
| **Local dev** | `launch_local.ps1` | Root `.env` | `8765` | `5173` via Vite proxy |
| **Docker** | `docker run … --env-file .env` | Same vars inside container | published `-p` | Host nginx/Caddy → `dist/` |
| **Windows .exe** | PyInstaller `dist/` output | `.env` beside exe + `data/` | configurable | Still use Vite or static `dist/` |

```text
  .env (repo root)          frontend/.env (optional)
        │                            │
        │   KALSHI_*                 │  VITE_API_BEARER_TOKEN (must match API)
        ▼                            ▼
   uvicorn / exe  ◀──── proxy / CORS ────  npm run dev  OR  static host
```

### Release promotion flow (`develop` → `main`)

```mermaid
flowchart LR
  subgraph dev [Day-to-day]
    D[feature commits]
    DV[origin/develop]
    D --> DV
  end
  subgraph gate [Quality]
    T[pytest backend/tests]
    P[pre-commit optional]
    DV --> T
    T --> P
  end
  subgraph prod [Release line]
    M[main]
    OM[origin/main]
    P -->|merge PR or local merge| M
    M --> OM
  end
```

**Convention:** keep **`release/*.zip`** and unpacked exe trees **out of git** unless you intentionally ship binaries from CI; they bloat history and are not required to run from source.

### Observability hop (one request path)

```mermaid
sequenceDiagram
  participant H as Health check
  participant A as /api/health
  participant L as dual_engine_loop
  participant O as optimizer_loop
  H->>A: GET (no bearer by default)
  A-->>H: ok + task flags
  Note over L,O: Deep health adds SQLite path/size + last_error map without Kalshi I/O.
```

### Equity vs optimizer (do not conflate)

| Concern | Primary surfaces |
|---------|------------------|
| **Ledger PnL path** | Equity small-multiples, `equity_snapshots_*`, `metrics*` on dashboard |
| **Exploration / mutation health** | Optimizer radar + health dot + report overlay |
| **Breeding narrative** | Breeder radar + `labs_breeding_*` on **`GET /api/optimizer/status`** |

Use **both** equity curves and optimizer telemetry when judging an experiment: MTM can move on marks while the optimizer speaks to **acceptance** and **replay-style fitness**, not the same numbers.

### Settings overlay — save path (UI → SQLite)

Most dangerous toggles stay behind **confirm** parameters or modal text; this diagram is the **happy path** for a normal JSON save.

```mermaid
sequenceDiagram
  participant U as Operator
  participant UI as SettingsOverlay
  participant API as PUT /api/config
  participant DB as SQLite bot_config

  U->>UI: Edit JSON + Save
  UI->>API: validated payload
  API->>DB: merge + write active row
  API->>DB: append config_history row
  API-->>UI: 200 refreshed config
  UI-->>U: close or show success
  Note over UI,API: Lab-only partial saves may use lab-branches routes; see OpenAPI /docs.
```

### Handy REST map (non-exhaustive)

| Intent | Verb + path | Notes |
|--------|-------------|-------|
| Full config | `GET/PUT /api/config` | `confirm=YES` when disabling Live paper. |
| Lab parity patch | `PUT /api/config/lab-branches` | Validates embedded `rules` like top-level saves. |
| Engine switches | `POST /api/engine/toggle` | Query flags for live vs each lab. |
| Optimizer tuning | `PUT /api/optimizer/config` | High-level keys only; no hidden v0.1-only weight knobs. |
| Force internal pulse | `POST /api/optimizer/force-internal-mutation` | Same gates as scheduled internal mutation. |
| Breeding + metrics | `GET /api/optimizer/status` | Large read-only JSON; cache-friendly in UI. |

### Color language in docs and UI (legend)

| Color / tone in README tables | Typical meaning in this repo |
|------------------------------|-------------------------------|
| **Green / pos** | Healthy connectivity, acceptance above band, or positive PnL tone in UI tiles. |
| **Yellow / warn** | Degraded path (429 backoff, partial Kalshi data, mid acceptance band). |
| **Red / bad** | Hard errors, low acceptance, or real-money warnings. |

### One-page “day 1” checklist (operators)

1. Copy **`.env.example` → `.env`**, set at least **`KALSHI_ENV`** and key material (or stay read-only without keys).
2. Run **`scripts/launch_local.ps1`** (Windows) or uvicorn + Vite manually (macOS/Linux sections below).
3. Open **`http://localhost:5173`**, confirm **`/api/dashboard`** returns **200** in Network tools.
4. Turn on **one lab** first, watch **Branch performance** + **equity fingerprints** diverge as trades accrue.
5. Read **Optimizer report** before toggling **Breeder** mode so you know whether the scheduler has signal.
6. When exposing beyond localhost, set **`KALSHI_API_BEARER_TOKEN`** + matching **`VITE_API_BEARER_TOKEN`**, tighten **`CORS_ORIGINS`**, and prefer a reverse proxy for TLS.

**Mermaid in GitHub:** diagrams in this README render automatically on **github.com**; in VS Code preview you may need a Mermaid-capable markdown preview extension.

**Line budget:** the README grew by **~34%** line-count versus the pre-expansion baseline so operators get **pictures + orderings**, not only tables (exact % varies slightly as other sections are edited).

---

## Dashboard (UI map)

Where the main **React** surface puts things (all optional panels depending on your layout):

| Area | What you get |
|------|----------------|
| **Top bar** | Connection / engine at-a-glance, **Settings (⚙)**, **optimizer health** color pill (hovers explain acceptance band), toasts. |
| **Branch strip / hero** | Per-branch (Live + A–D) PnL and key metrics; clicking usually ties into compare / filters. |
| **Compare (equity) region** | Multi-line equity / blended or potential view; overplot toggles, granularity tabs; many charts are **double‑click to expand** in a lightbox (Esc to close), matching the pattern used on the **optimizer** radar. |
| **Branch brain (optimizer block)** | **Title row:** “Optimizer” heading, **health** dot, **force** / **report** / **Info**. **Optimizer** mode: **Optimizer Thinking** radar (double‑click to expand), **mutation** row (tier, effective scale, 0–1 dial bar), then **lab pulse** ticker. **Footer (bottom-right):** **Optimizer** \| **Breeder** segmented control. **Breeder** mode: fetches **`GET /api/optimizer/status`** and renders the **twelve-axis** `labs_breeding_personality_radar` only (minimal chrome: spinner while loading; inline legend and status prose removed—use **Tooltip** on the radar). **force** still triggers a Breeder status refetch. Full run metrics, trace, and equity sparklines stay in the **report** overlay. Promote **Lab A → Live** and dangerous toggles still require confirms documented in the UI. |
| **Settings overlay** | Full **JSON** config editor, per-lab overlays, rules, fees, **patient** stop, optimizer tuning—this is the authoritative place for `PUT /api/config` and lab parity with `merge_branch_config`. |

**Resize / mobile:** the compare row and optimizer column use **flex** (`row` on wide, **stack** on small screens); if something looks “missing,” zoom out or widen—the layout does not hard-require two monitors, but the dense dashboard targets **~1280px** width for the full two-column branch experience.

---

## Optimizer visualizations

The **Optimizer** column is **read-only telemetry** for the internal and optional external optimizer. Nothing on this card places orders; engines still run from **Settings** and the dual-engine loop.

### What you see on the card

| Element | What it means |
|--------|----------------|
| **Title row** | **force** — runs an internal mutation path immediately (`POST /api/optimizer/force-internal-mutation`), gated by the same fitness/stat checks as scheduled runs; also bumps the Breeder status refetch when that card is in **Breeder** mode. **report** — opens a full **Optimizer report** overlay (run metrics, acceptance, schedule, change history, pulse log, and richer tables than the main card). **Info** — in-page explainer for the column. |
| **Footer (bottom-right)** | **Optimizer** \| **Breeder** — switches the card body between default **Optimizer Thinking** telemetry (from **`GET /api/dashboard`**) and **Labs Breeding** readout (from **`GET /api/optimizer/status`** only). |
| **Health dot** (red / yellow / green) | **Internal-mutation acceptance rate** over recent trace rows: **above 60%** reads green, **30–60%** yellow, **below 30%** red. The same field drives long-form `optimizer_suggested_action` toasts (throttled), not a duplicate of the dot. |
| **Optimizer Thinking (radar)** | A **Recharts** spider / radar: **six** axes, each **0–100** after server-side normalization so you can compare branches on one scale. Typical spokes: **fitness** (composite replay score), **acceptance** (mutant acceptance %), **mutation** (dial and tier rolled into one view), **stop‑loss safety** (replay stop burden), **equity momentum** (Lab A $/h slope from snapshots), and **streak (inverted)** so **higher = better** (low red-stress). Colored **bands** = **Live + Lab A–D**; **Lab A** is the primary “staging” readout. **Double-click** the chart to open a large modal with a tabular **detail** block and the same series—**Esc** closes. If a branch is cold or lacks data, a spoke can sit in the **mid-50s** or look flat until fresh settles and snapshots exist. |
| **Mutation row** (under the radar) | A compact **tier** label (**Light** / **Medium** / **Strong** — driven by the same acceptance bands as health), the **effective mutation scale** (0–1 internal blend of tier and `mutation_aggressiveness`), and a **horizontal “Dial (0–1)”** bar showing persisted **`mutation_aggressiveness`**. This replaces the old single-line “key internal metrics…” caption: it is the at-a-glance **exploration pressure** readout. |
| **Lab pulse** | A scrolling line of short **engine / optimizer** hints (e.g. open sim, return vs basis, last optimizer note). Sourced from dashboard `lab_thoughts` / `optimizer_activity` slices—useful for “what happened last tick” without opening Settings. |

### Breeder view (Labs Breeding v0.1)

When the main dashboard **Optimizer** card is set to **Breeder** (footer toggle), the UI calls **`GET /api/optimizer/status`** (same bearer rules as other `/api/*` when enabled) and renders breeding telemetry—not the Lab A “Optimizer Thinking” spider chart. For the **system** design (breeders, cadence, adoption gates, files), see [Labs breeding v0.1](#labs-breeding-v01-at-a-glance).

| Topic | Behavior |
|--------|----------|
| **Child engines** | Up to **six** SQLite-backed branches **`lab_child_1`** … **`lab_child_6`** run inside **`dual_engine_loop`** alongside Live and Labs A–D. They are **not** separate tiles on the main branch strip; they exist for **settlement, snapshots, and sim trading** when a slot holds a genome. See `backend/app/branch_config.py` (`BRANCH_CHILD_LABS`) and `backend/app/lab_breeding.py`. |
| **Parents** | **Lab B, Lab C, Lab D** act as breeders; **Lab A** is the primary **staging / adoption** arm in the breeding design. |
| **Replacement cooldown** | A **5-minute** cooldown is recorded for **soft cull** and **adoption** style replacements only. **Hard** (zero-equity) **death** replacement is **immediate** (no cooldown). Server exposes `labs_breeding_replace_cooldown_until` on status. |
| **Personality radar** | Field **`labs_breeding_personality_radar`**: **twelve** normalized **0–100** mood axes derived from **`_labs_breeding_traits`** and sizing-style knobs for **read-only** display (no new persisted keys for the radar itself). Built in `build_labs_breeding_personality_radar` (`lab_breeding.py`) and returned from **`GET /api/optimizer/status`**. |
| **Other status fields** | `labs_breeding_log`, `labs_breeding_children`, `labs_breeding_death_chamber`, `labs_breeding_lineage_history`, `labs_breeding_last_generation_iso` (caps/truncation per route). Types: `backend/app/types_api.py`. |
| **Dashboard UX** | **No** Recharts **legend** and **no** inline status grid under the radar—use **Tooltip** on spokes/polygons. **Loading** uses a spinner only; **errors** still show a short alert line. **Optimizer \| Breeder** lives in the **card footer** (bottom-right), not the title row. |
| **After force mutation** | **Breeder** mode refetches **`GET /api/optimizer/status`** when you click **force** in the title row so the radar matches the latest config. |

**Advanced replay metrics (v0.1):** Sharpe/Sortino/Calmar-style signals, Kelly-style fractions, slippage and drawdown guardrails feed **internal fitness** only. They are **not** exposed on the main **Optimizer** card or under `optimizer_activity` in **`GET /api/dashboard`**. For `advanced_metrics_last`, `proposal_history`, a trimmed trace, and **labs breeding** payloads, call **`GET /api/optimizer/status`** (read-only).

### How it connects to the backend

- **Optimizer** mode (default): the radar and health dot are built from **`GET /api/dashboard`** (and related) metrics: `cfg.optimizer` (acceptance, best fitness, red streak, effective scale, `mutation_tier`, etc.) plus branch rollups. The exact spoke formulas live in the **dashboard builder** in `backend/app/main.py` and the **React** bundle in `App.tsx` (`optimizerThinkingRadarBundle` and friends)—they are **heuristic**, not raw exchange PnL.
- **Breeder** mode: the personality **radar** (and fetch errors) use **`GET /api/optimizer/status`** only (see [Breeder view](#breeder-view-labs-breeding-v01)).
- **Intraday equity movement** and **book vs MTM** on the main **Equity curves** block are **separate** from the optimizer card: the optimizer radar does not replace the equity small-multiples; use both together.
- If **`optimizer.enabled`** is false and no internal pulses have run, spokes may look **neutral**; enable the scheduler in **Settings → Optimizer** and let **Lab A** accumulate **sim** settles so fitness and acceptance have signal.

For **internal pulse vs optional Claude** and what can auto-persist, see [Optimizer: internal pulse vs Claude](#optimizer-internal-pulse-vs-claude).

---

## Branches and optimizer loop (mental model)

Five **visible** branch engines (Live + Labs A–D) share the same Kalshi feed but **separate ledgers**, plus up to **six** optional **`lab_child_*`** instances when breeding slots are active. The optimizer task reads **settled** activity across labs (and breeding logic may touch child branches); **Claude** is optional and **writes through** the same guarded paths as the internal pulse (Lab A–centric).

```mermaid
flowchart TB
  KS[Kalshi REST API]
  subgraph engines [dual_engine_loop — Live + Labs A–D + lab_child_1..6 when enabled]
    L[Live]
    A[Lab A]
    B[Lab B]
    C[Lab C]
    D[Lab D]
    CH[lab_child_1..6]
  end
  SQL[(SQLite config + trades + signals + equity)]
  OPT[optimizer_loop]
  CL[Anthropic optional]
  CFG[merge_branch_config per tick]
  KS <--> L
  KS <--> A
  KS <--> B
  KS <--> C
  KS <--> D
  KS <--> CH
  CFG --> L
  CFG --> A
  CFG --> B
  CFG --> C
  CFG --> D
  CFG --> CH
  L --> SQL
  A --> SQL
  B --> SQL
  C --> SQL
  D --> SQL
  CH --> SQL
  SQL --> OPT
  OPT --> CL
  OPT -.->|internal pulse + gated Claude patches| A
```

- **Live** — Real limits when `simulate` is off and keys are valid; otherwise paper-like behavior per config.
- **Labs B/C/D** — Reference arms for compare and optimizer context; **no** automatic "copy B into Live" from Claude output.
- **Lab A** — Primary experiment branch: promote-to-Live copies **overlays** from Lab A when settled PnL gates pass; optimizer persistence is also **Lab A–biased** by design.
- **`lab_child_1`…`lab_child_6`** — Optional **Labs Breeding v0.1** paper engines with their own ledgers when assigned; see [Labs breeding v0.1](#labs-breeding-v01-at-a-glance) and [Breeder view](#breeder-view-labs-breeding-v01).

---

## Architecture (high level)

```mermaid
flowchart LR
  subgraph client [Browser]
    UI[React dashboard Vite]
  end
  subgraph api [FastAPI backend]
    REST["/api/* JSON"]
    ENG[dual_engine_loop]
    OPT[optimizer_loop]
    KC[KalshiClient]
  end
  subgraph data [Local disk]
    SQL[(SQLite bot_config trades signals equity)]
    LOGS[JSONL logs optional]
  end
  subgraph ext [External]
    KS[Kalshi REST API]
    AN[Anthropic API optional]
  end
  UI -->|"/api proxied"| REST
  REST --> SQL
  ENG --> KC
  KC --> KS
  OPT --> SQL
  OPT --> AN
  REST --> LOGS
```

- **Active config** is one merged JSON row in **`bot_config`**, with **append-only** **`config_history`** for audit. Engines read through `merge_branch_config` so each branch sees **global defaults** plus **lab overlays** where set.
- **Trading engines** share one event loop task group pattern (`dual_engine_loop`): **Live**, **Labs A–D**, and up to **six** **`lab_child_*`** instances when breeding slots are active—each branch key maps to its own `TradingEngine` when present in the `engines` dict.

---

## Configuration layers

Understanding this removes a lot of “why did my lab pick up X?” confusion:

| Layer | Where it lives | Used by |
|--------|----------------|---------|
| **Top-level config** | Keys on the root JSON (same document as labs) | **Live** branch: `live_paper_trading` (canonical; mirrored to `simulate`), `engine_running`, `rules`, `assets`, global paper balance when not overridden, filters, **patient stop-loss** fields, fees, etc. |
| **Per-lab overlays** | `lab_a` … `lab_d` objects | When a lab’s `engine_running` is true, `merge_branch_config` builds effective config by copying globals, then for each key in `LAB_BRANCH_OVERLAY_KEYS` (see `backend/app/branch_config.py`) replacing from that lab if present. Keys include `rules`, `assets`, `balance_fraction_per_window`, `window_minutes`, `poll_seconds`, subtitle filters, fee fields, `paper_balance_cents`, and more. Empty lab `assets` is ignored so you cannot accidentally scan zero markets. |
| **Optimizer blob** | `cfg["optimizer"]` | Scheduler gates, adaptive tuning state, `change_history`, Claude model id, lab style presets, etc. Does not replace the whole config; it patches **`lab_a`** (and optimizer metadata) under controlled conditions. |

API validation for many live fields lives in **`BotConfigPayload`** (`backend/app/api_models.py`). Labs use `merge_lab_branch_patch` / `expand_partial_lab_branch` for partial updates.

**Rules validation** — `PUT /api/config` already validates `rules` through Pydantic when you send that field. **`PUT /api/config/lab-branches`** now runs the same **`RuleCfg`** checks on any embedded `rules` array before expand/save, so bad lab rules cannot bypass the API. The Settings **Advanced** rules editor includes **Validate on server**, which calls **`POST /api/config/validate-rules`** with `{ "rules": [...] }` and returns normalized JSON without persisting.

---

## Health, alerts, and Docker

| Endpoint / artifact | Purpose |
|---------------------|---------|
| **`GET /api/health`** | `status`, `started_at`, whether the dual-engine and optimizer asyncio tasks are still running. |
| **`GET /api/health/deep`** | Read-only extras: resolved SQLite path and file size, non-empty `engine_last_errors` per branch, and whether **`ALERT_WEBHOOK_URL`** is set. No Kalshi I/O. |
| **`POST /api/config/validate-rules`** | Body `{ "rules": [ ... ] }` — returns `{ ok, count, rules }` or **400** with a clear message. |
| **`ALERT_WEBHOOK_URL`** | When a branch gets a **new or changed** `last_error`, the engine loop POSTs a short JSON payload (Discord: `content`; Slack `hooks.slack.com`: `text`). Throttled by **`ALERT_WEBHOOK_MIN_SECONDS`** (default 120) per branch and error prefix. |
| **`Dockerfile`** | Minimal **Python 3.12** image running uvicorn on `0.0.0.0:${KALSHI_BOT_PORT}`. Mount a volume for `data/` if you keep the default SQLite path under the repo. |

**Kalshi 429 backoff** — `backend/app/kalshi_client.py` sleeps using **`Retry-After`**, then common reset headers such as **`X-RateLimit-Reset`** / **`RateLimit-Reset`**, then exponential backoff with jitter.

---

## Promoting Lab A to Live

The dashboard calls **`POST /api/config/promote-lab-a-to-live`** with JSON `{"confirm": true}` (and in **real-money** mode, `{"confirm": true, "ack_live": "APPLY_LIVE"}` after the user types the token).

**Behavior:**

1. Unless `skip_pnl_gate` is true, the API requires **Lab A settled PnL (cents)** to be **strictly greater** than Lab B, Lab C, and Lab D (each from simulate trade rollups). This matches the product gate in the UI.
2. For each key in **`LAB_BRANCH_OVERLAY_KEYS`**, if `lab_a` has that key set (and it is not an empty `assets` dict), the value is **deep-copied onto the top-level config**. So Live inherits Lab A’s rules, sizing, filters, assets, fee settings, etc., for those fields only.
3. **`simulate`** and **`engine_running`** are not special-cased in that loop: only keys present on `lab_a` are copied. The UI still warns before real-money promote.

After promotion, **save** returns the full updated config from SQLite.

---

## Example rules, matching, and edge

Rules are JSON objects stored in the `rules` array (live or per-lab overlay). Defaults are seeded in **`default_bot_config()`** in `backend/app/persistence.py`. Each rule is validated as **`RuleCfg`** in `api_models.py`.

### Example JSON

**YES band** (buy YES when implied YES probability falls in the band and minutes-to-expiry in range):

```json
{
  "name": "Mid 55-72%",
  "min_prob": 0.55,
  "max_prob": 0.72,
  "min_minutes_left": 4.0,
  "max_minutes_left": 18.0
}
```

**NO band** (`side: "no"` — band is on **implied NO** (= 1 − YES mid); execution uses the NO book per `pick_trade_rule` / NO ask helpers):

```json
{
  "name": "NO conviction 62-78%",
  "side": "no",
  "min_prob": 0.62,
  "max_prob": 0.78,
  "min_minutes_left": 3.0,
  "max_minutes_left": 18.0
}
```

Other top-level knobs interact with rules (for example `no_bet_when_yes_below_pct`, `exclude_yes_subtitle_contains`, sim-only `dev_sim_yes_implied_ge_pct`, `swing_exit_implied_drop_pct`). See OpenAPI on **`PUT /api/config`** for bounds and null semantics.

### How matching works (probability × time)

Implementation: **`rule_matches`** / **`pick_trade_rule`** in `backend/app/engine.py`.

1. From the order book, the engine derives an **implied YES mid** (and an **effective NO ask** when NO-side trades are possible).
2. For each rule, the **probability axis** is either implied YES or implied NO, depending on `side` (`rule_axis_probability`).
3. A rule **matches** only if **both** are true (inclusive bounds):
   - **Band:** `min_prob` ≤ axis ≤ `max_prob`
   - **Clock:** `min_minutes_left` ≤ minutes to expiry ≤ `max_minutes_left`
4. When implied YES is below `no_bet_when_yes_below_pct` (if set), **only NO-side rules** are considered for that market; otherwise YES rules are scanned first, then NO rules.

Gaps between bands are intentional "no trade" zones unless you add or widen a rule.

### How **edge** is used when several markets match

When multiple markets match a rule and have a tradable book, the sim ranking key prefers larger **edge** (then more minutes to close). From **`_market_sim_trade_rank`** in `engine.py`:

- **YES leg:** `edge = implied_yes_mid − yes_ask` (paying up to the ask vs fair mid).
- **NO leg:** `edge = implied_no_mid − no_ask` (same idea on the NO side).

So "edge" here is a simple **mid minus limit** surplus in probability units before fees—not a separate ML score. Ties and guardrails (open per ticker, budget window, etc.) are enforced later in the engine and SQLite helpers.

---

## Optimizer: internal pulse vs Claude

Code path: **`run_optimizer_once`** in `backend/app/optimizer_claude.py`. **UI note:** optimizer controls in the dashboard stay intentionally small; anything that brought **Claude-driven rule mutation** back would belong in **Settings** next to the rest of the serious config, not scattered in ad-hoc panels. The **header** (beside **⚙ Settings**) shows a color pill for **optimizer health** (acceptance-rate bands); details and the full trace live under **Settings → Lab & optimizer** and on the main **Optimizer** card.

1. **Internal pulse (always when adaptive / scheduler conditions allow)** — Does **not** require `ANTHROPIC_API_KEY`. It can adjust things like **loss-streak thresholds**, **win-path easing**, and **Lab A `balance_fraction_per_window`** (“bet pulse”) based on settled trades and gates (`min_trades_for_optimize`, `min_profitable_trades`, etc.). Changes append to `optimizer.change_history` and update pulse trace fields.

2. **Claude path** — Runs only when **`optimizer.enabled`** is true **and** `ANTHROPIC_API_KEY` is set. The service loads recent **simulate** trades and signals for **all four labs**, plus equity samples, builds a JSON payload, and POSTs to Anthropic Messages API. The model returns JSON with `recommendations` and `trend_notes`.

3. **What Claude is allowed to persist** — `_apply_claude_bet_recommendations` applies **`balance_fraction_per_window` only for `target: "lab_a"`** after min settled / profitable trade gates pass. Lab B/C/D are **reference arms** in the prompt; threshold or rule rewrites for them are not auto-applied from Claude output.

4. **Recommendations row** — Each run can insert a row into **`optimizer_recommendations`** (SQLite) for audit and the dashboard.

If the scheduler is off and there is no API key, the optimizer still records **internal-only** pulses when adaptive tuning fires.

### Optimizer upgrade v0.1

- `backend/app/optimizer_claude.py` computes an advanced replay score with Sharpe, Sortino, Calmar, profit factor, expectancy, Kelly fraction, drawdown tolerance guards, and regime-aware weighting. Weights and thresholds are **fixed in code** (same numeric defaults as the former optional env tuners); there is **no** `OPTIMIZER_*` surface in [`.env.example`](.env.example) or `EnvSettings`.
- **Claude** still uses structured JSON (`backend/app/optimizer/schemas.py`) with held-out / backtest-style gates where applicable; internal **`proposal_history`** and **`advanced_metrics_last`** persist in `cfg["optimizer"]` for audit and the status route.
- **Dashboard:** unchanged shape for `optimizer_activity` versus v0.0—no `optimizer_advanced_metrics` key on the full dashboard payload.
- **`PUT /api/optimizer/config`** accepts the same high-level optimizer keys as before v0.1; it does **not** accept v0.1-only tuning keys (A/B envelope, per-field replay weights, slippage bps, etc.).
- Optional observability: **`GET /api/optimizer/status`** returns proposal history, internal trace, and latest advanced metrics for automation or debugging.
- **Lab A** remains the only auto-apply target for persisted mutations; Labs B/C/D stay reference-only for auto-persist, as in v0.0.

---

## Health and metrics

**`GET /api/health`** returns JSON suitable for load balancers and simple uptime checks:

- `status` — `"ok"` when the process is serving.
- `started_at` — UTC ISO timestamp when the app lifespan started (after restart).
- `dual_engine_loop_running` — whether the background dual-engine asyncio task is still running.
- `optimizer_loop_running` — whether the optimizer loop task is still running.

Heavier metrics (DB size, last Kalshi error, equity) live in **`GET /api/dashboard`**, **`GET /api/dashboard/equity`**, and related split routes; keep `/api/health` cheap.

---

## Windows packaging

For day-to-day development, use **`scripts/*.ps1`** as documented above.

There is also a **PyInstaller** spec at the repo root (**`kalshibot-api.spec`**) and helper **`scripts/exe_api_entry.py`** for building a **standalone Windows API executable** (bundled Python, no global interpreter). Typical flow: install PyInstaller in the venv, run `pyinstaller kalshibot-api.spec`, ship the `dist` output together with `.env` and a `data/` folder. The full UI still expects **Vite** or a static hosting story unless you add a static mount to FastAPI.

For cross-platform deploy, use the repo **`Dockerfile`** (API-only uvicorn) and mount a volume for `data/`; add nginx or Caddy in front of **`frontend/dist`** if you want a single host for UI + API.

---

## Roadmap and ideas

Constructive extensions that fit this codebase:

| Idea | Notes |
|------|--------|
| **Convergence Engine** | **Not integrated today**—stability, correctness, and dashboard UX were prioritized first. When/if an external convergence or research loop lands, it should feed the same **SQLite + guarded config** paths as the existing optimizer rather than a parallel mutation channel. |
| **Webhooks** | Baseline: `ALERT_WEBHOOK_URL` for engine errors (see Health section). Richer POSTs (drawdown, settle bursts) could when `last_error` changes or drawdown exceeds a threshold (would read from engine state or dashboard builder). |
| **Richer health** | `GET /api/health/deep` already covers lightweight DB / error introspection; extend if you need more without full `/api/dashboard` cost. |
| **Config UX** | More guided panels for rules and lab diff vs live; today much of the power is in JSON / Settings overlay. |
| **Stricter settings** | Expand Pydantic coverage for nested `optimizer` and lab dicts beyond `BotConfigPayload` merge paths. |
| **Tests** | Add unit tests around rule matching, sizing, and sim guards in `engine.py` (see existing `backend/tests/`). |
| **Kalshi rate limits** | `kalshi_client.py` already honors **`Retry-After`** on **429** with exponential backoff; if Kalshi adds consistent rate-limit headers, thread them into the same helper. |
| **Docker / static UI** | `Dockerfile` is API-only today; add nginx sidecar or Caddy for static `frontend/dist` when you want one URL for operators. |

---

## Requirements

| Component | Notes |
|-----------|--------|
| **OS** | Developed for **Windows** (PowerShell scripts). The same code runs on macOS or Linux if you invoke Python and npm manually. |
| **Python** | **3.11, 3.12, or 3.13** recommended. **3.14** often forces a `pydantic-core` source build (needs Rust or MSVC on Windows); the venv script warns about this. |
| **Node.js** | **18+** (for Vite 5 and the React app). |
| **Kalshi** | Optional for UI-only exploration; for real data and trading you need API access and keys from Kalshi (demo vs prod base URL is configured in `.env`). |
| **SQLite** | The default store is a single file (`data/bot.sqlite3` or `SQLITE_PATH`); you can open it with **DB Browser for SQLite** for read-only forensics, but do not lock the file while the API is writing. |
| **Git** | Used for source control only; the running bot does not need git on the server if you deploy from CI artifacts. |

**Performance hint:** a low-power NAS or $5 VPS is fine for **read-only** monitoring, but the **engines + optimizer** benefit from a steady **CPU** core and local disk (avoid network-attached `SQLITE_PATH` on Wi‑Fi for production).

## Performance and startup

The API avoids heavy import-time work: a **base set of five `TradingEngine` instances** (Live + Labs A–D), **plus** optional **`lab_child_*`** engines when breeding slots are active, and a **single shared `httpx.AsyncClient`** are created in the FastAPI **lifespan**; Kalshi’s `/markets` list is **pre-warmed** once from your configured `assets` (deduped series tickers) so early `dual_engine_loop` turns mostly hit the in-process cache instead of many parallel cold fetches. In-memory cache TTLs are **wider for the first few seconds** (`KALSHI_COLD_START_CACHE_TTL_S`, default 90) and then return to `KALSHI_OPEN_MARKETS_TTL_S` / `KALSHI_ORDERBOOK_TTL_S`.

Set **`KALSHI_PROFILE_STARTUP=1`** to log phase timings (`http_client_and_cold_ttls`, `trading_engines`, `prewarm_open_markets`, `startup_complete`, optional `kalshi_ws_task`, `kalshibot_startup_ready`).

Details: [docs/startup_performance.md](docs/startup_performance.md).

Cold startup reduced from ~60 s to 6.8 s (9x faster) with WebSocket orderbook cache hit rate of 88.9% in steady state (see [docs/startup_performance.md](docs/startup_performance.md)).

### WebSocket mode (Phase 2)

When **`KALSHI_WS_ENABLED=1`**, the API opens an authenticated WebSocket to Kalshi’s trade feed (`wss://…/trade-api/ws/v2`, aligned with `KALSHI_ENV`) and subscribes to **`ticker`** plus **`orderbook_delta`** for up to **`KALSHI_WS_MAX_MARKETS`** tickers seeded from the pre-warmed `/markets` cache. Incoming **orderbook** messages are normalized into the same in-memory shape as REST **`/orderbook`**, so `get_market_orderbook_cached` usually **does not** issue HTTP while the socket is up and parsing succeeds.

**Fallback:** if the package is missing, auth fails, the socket drops, or a message cannot be parsed, the bot **keeps using REST** and the existing TTL cache — no behavior change to rules or fills.

**Observability:** **`GET /api/health/startup`** (same bearer rules as other `/api/health*`) returns `startup_complete`, WS connection flags, message counts, and orderbook cache hit/miss counters. Optional **`KALSHI_LOG_TICK_INTERVAL_S`** (e.g. `30`) logs tick wall time and cache hit percentage on the dual-engine loop.

---

## Architecture & performance (Phase 3)

- **Typed runtime surfaces:** WS/REST payload adapters now use lightweight `TypedDict`/`dataclass` shapes (`backend/app/types_kalshi.py`) to reduce `Any` sprawl without adding runtime model-validation overhead.
- **Centralized tuning knobs:** remaining hot-path constants (HTTP pool + retries, WS ping/reconnect cadence, prewarm concurrency, startup TTL restore delay, dashboard orderbook cache TTL, engine orderbook caps) are env-backed in `EnvSettings` with defaults equal to prior behavior.
- **No behavior drift:** Phase 2 startup sequencing (`prewarm -> seed WS tickers -> startup_complete -> background tasks`) and REST fallback semantics remain unchanged.

### Final pass notes

- **PHASE FINAL:** response contracts (`types_api.py`) are now used consistently for health + dashboard endpoints as type hints only.
- **PHASE FINAL:** remaining engine/loop fallback defaults are centralized in `settings_env.py` (`DEFAULT_*`) with values matching prior behavior.

---

## Glossary (quick)

Terms that appear in the **dashboard** and in backend logs, without re-explaining the whole `engine.py`:

| Term | Meaning in this project |
|------|-------------------------|
| **Book (return)** | Equity / PnL measured from the **ledger** and settled states—what your account *knows* it holds. |
| **MTM (return)** | Mark-to-market: unrealized marks blended with the book; **Mtm–book** style gaps show when marks diverge from the ledger. |
| **Decisive** (win/loss) | A closed trade counted as a win/loss in our rolled-up %—see metrics panel for the exact field used per tile. |
| **Scratch** | A sim exit that closes without a standard settle path; tracked separately from “clean” wins/losses. |
| **Red streak** | Consecutive “bad” optimizer / acceptance cycles (internal to the **optimizer** loop); the radar **inverts** it so **higher on the chart = better** (less stress). |
| **Balance fraction** | The fraction of a branch **paper** bankroll **per time window** used as sizing cap input (`balance_fraction_per_window`); not the only sizing knob. |
| **Promote** | Copy **allowed** `lab_a` keys onto the top-level **Live** config (with PnL and ack gates), not a Git operation. |
| **Breeder / child** | **Breeder** = dashboard mode for **`labs_breeding_*`** status. **Child** = `lab_child_1`…`lab_child_6` hidden paper engine slot (genome + traits), not a visible branch tile. |
| **Death chamber** | Rolling list of recent **hard/soft** breeding exits (capped), surfaced on **`GET /api/optimizer/status`** for debugging / narrative. |
| **Adoption (Lab A)** | Copying a vetted **child genome** into **Lab A** staging under **`lab_breeding`** gates—**separate** from **Promote Lab A → Live** and still subject to cooldown rules where applicable. |

---

## Quick start (Windows)

From the **repository root** (the folder that contains `backend/`, `frontend/`, `scripts/`).

### 1. Create the Python virtual environment

```powershell
.\scripts\create_venv.ps1
```

Optional: pick an interpreter explicitly:

```powershell
.\scripts\create_venv.ps1 -PythonExe "C:\Path\to\Python313\python.exe"
```

This creates `.venv`, installs `requirements.txt`, and does **not** replace your global Python.

### 2. Configure environment variables

```powershell
Copy-Item .env.example .env
```

Edit **`.env`** in the repo root (see [Configuration](#configuration)). At minimum for Kalshi:

- `KALSHI_ENV` — `demo` or prod-style host per `.env.example`
- `KALSHI_API_KEY_ID` and either `KALSHI_PRIVATE_KEY_PATH` or `KALSHI_PRIVATE_KEY_PEM`

Restart the backend after changing `.env`.

### 3. Run API and dashboard together (easiest)

```powershell
.\scripts\launch_local.ps1
```

This starts **uvicorn** in a **new** PowerShell window (default **http://127.0.0.1:8765**) and **Vite** in the current window (**http://localhost:5173**). Open the **5173** URL in your browser, **not** the API port alone, so `/api` is proxied correctly.

### 4. Or run backend and frontend separately

**Terminal A — API:**

```powershell
.\scripts\run_backend.ps1
```

**Terminal B — UI:**

```powershell
cd frontend
npm install
npm run dev
```

Then open **http://localhost:5173**.

---

## macOS and Linux (manual)

There are no `scripts/*.ps1` helpers on these platforms. Use the same **Python 3.11+** and **Node 18+** as above, from the **repository root**.

### 1. Virtual environment and dependencies

```bash
cp .env.example .env
# Edit .env with your editor; set Kalshi keys when ready.

python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

### 2. Backend (Terminal 1)

Default port **8765** (override with `export KALSHI_BOT_PORT=8080` if needed):

```bash
source .venv/bin/activate
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port "${KALSHI_BOT_PORT:-8765}"
```

Run this from the repo root so the `backend` package resolves. Confirm **http://127.0.0.1:8765/api/health**.

### 3. Frontend (Terminal 2)

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**. If you changed the API port, add `frontend/.env` with `VITE_API_ORIGIN=http://127.0.0.1:YOUR_PORT` (see [Configuration](#configuration)).

---

## Configuration

All backend env vars are documented in **`.env.example`**. Highlights:

| Variable | Purpose |
|----------|---------|
| `KALSHI_ENV` | Selects demo vs production-style API host (see comments in `.env.example`). |
| `KALSHI_API_KEY_ID` / `KALSHI_PRIVATE_KEY_*` | RSA private key authentication for Kalshi. |
| `KALSHI_BOT_PORT` | API listen port (default **8765**). Use if 8765 is blocked (for example some Windows reserved ranges). |
| `SQLITE_PATH` | Override SQLite file location (default `data/bot.sqlite3`). |
| `DATA_LOG_DIR`, `DATA_LOGGING`, `DATA_LOG_EQUITY` | Append-only **JSONL** logs under `data/logs/`. |
| `DATA_RESET_TOKEN` | If set, destructive reset endpoints require matching `X-Reset-Token` header. |
| `ANTHROPIC_API_KEY` | Enables optimizer paths that call Anthropic's HTTP API. |
| `ALERT_WEBHOOK_URL` | Optional Discord or Slack incoming webhook for new/changed engine errors (see [Health, alerts, and Docker](#health-alerts-and-docker)). |
| `ALERT_WEBHOOK_MIN_SECONDS` | Minimum seconds between similar webhook posts (default **120**). |

### Bot config (SQLite JSON) — paper mode and patient stop-loss

| Key | Scope | Purpose |
|-----|--------|---------|
| `live_paper_trading` | **Live** (root) | Canonical boolean: when **true**, Live uses paper / simulated order flow. Kept in sync with legacy **`simulate`**. |
| `simulate` | **Live** (root) | Legacy mirror of `live_paper_trading` for clients and history. **Disabling** paper (switching to real limit orders) requires **`?confirm=YES`** on `PUT /api/config` or `POST /api/engine/toggle?simulate=false`. |
| `enable_patient_stop_loss` | **Live** or per **`lab_*`** | Turn patient stop-loss on or off. |
| `stop_loss_trigger_pct` | same | Fee-aware unrealized P&L% (negative) at or below which an exit is allowed after min hold. |
| `min_hold_minutes_before_stop` | same | Minimum minutes **held** before the stop can fire. |

### Frontend dev proxy

Vite proxies **`/api`** to **`http://127.0.0.1:8765`** by default (`frontend/vite.config.ts`). If you change the API port:

1. Set `KALSHI_BOT_PORT` in the root `.env` for the backend.
2. Create **`frontend/.env`** with:

   ```env
   VITE_API_ORIGIN=http://127.0.0.1:YOUR_PORT
   ```

Restart `npm run dev`.

---

## Ports and URLs

| Service | Default URL | Role |
|---------|-------------|------|
| **Dashboard (Vite)** | http://localhost:5173 | React UI; use this day-to-day. |
| **Backend (FastAPI)** | http://127.0.0.1:8765 | JSON API and `/docs` Swagger. Visiting `/` on the API port shows a short HTML hint. |

Health: **GET** http://127.0.0.1:8765/api/health and **GET** http://127.0.0.1:8765/api/health/deep — see [Health, alerts, and Docker](#health-alerts-and-docker).

---

## API overview

Interactive docs: **http://127.0.0.1:8765/docs** (when the server is running).

Representative routes:

- `GET /api/dashboard` — Full dashboard (metrics, engines, recent trades and signals, equity snapshots, order-book refresh where applicable).
- `GET /api/dashboard/equity` — Same shape as the full dashboard but **skips the slow per-position mark-refresh** pass; use for **frequent** polling. **`GET /api/dashboard/open_positions`**, **`/orderbooks`**, **`/recent_trades`** return focused slices; **`orderbooks`** may serve a **cached** payload for a few seconds.
- `GET /api/config`, `PUT /api/config` — Bot configuration (see `confirm=YES` when disabling **paper** on Live).
- `GET /api/config/history` — Last **N** **config** snapshots (default 20) from **`config_history`**.
- `GET /api/account`, `GET /api/engine/status` — Account and engine summaries.
- `POST /api/engine/toggle` — Start or stop engines / paper mode (OpenAPI: **`confirm=YES`** when `simulate=false`).
- `GET /api/trades`, `GET /api/signals` — Recent activity.
- `GET /api/history/{table}`, `GET /api/history/export.csv` — Historical tables and CSV export.
- `POST /api/data/reset` — Reset trading data (protect with `DATA_RESET_TOKEN` in production contexts).
- Optimizer: `GET /api/optimizer/recommendations`, `PUT /api/optimizer/config`, `POST /api/optimizer/run`, `POST /api/optimizer/force-internal-mutation`, and **`GET /api/optimizer/status`** (v0.1: `advanced_metrics_last`, `proposal_history`, trace caps; **Labs Breeding v0.1**: `labs_breeding_log`, `labs_breeding_children`, `labs_breeding_death_chamber`, `labs_breeding_lineage_history`, `labs_breeding_personality_radar`, `labs_breeding_last_generation_iso`, `labs_breeding_replace_cooldown_until`). Default **Optimizer** radar / mutation dial / acceptance come from **`GET /api/dashboard`** (and equity split routes). The dashboard **Breeder** mode reads **`GET /api/optimizer/status`** for the **twelve-axis radar** (minimal UI: no extra tables on the card). If the default radar looks **flat/50s**, the API may still be warming up or a branch has no settled trades yet.
- `POST /api/config/validate-rules` — validate a `rules` array without saving.
- **`POST /api/config/promote-lab-a-to-live`** — gated PnL compare vs B/C/D, optional `ack_live=APPLY_LIVE` in real mode (see [Promoting Lab A to Live](#promoting-lab-a-to-live)).
- **OpenAPI** — `GET` parameters like `?confirm=YES` and JSON bodies for toggles are documented in **`/docs`**; when debugging 400s, read the `detail` string in the response body (FastAPI’s error shape).

**Rate and cost:** the backend batches Kalshi I/O; do not point multiple independent bots at the same API key with overlapping markets without understanding Kalshi’s rate policy—`kalshi_client` backs off on **HTTP 429** (see [Health, alerts, and Docker](#health-alerts-and-docker)).

---

## Production UI build

The dashboard is normally run through Vite in development. To produce static assets:

```powershell
cd frontend
npm install
npm run build
```

Output is under **`frontend/dist/`**. Serving that folder is **not** wired into `main.py` by default. Pick one of these patterns:

1. **Reverse proxy** (recommended) — e.g. **Caddy** or **nginx** serves `dist` on **:443** and `proxy_pass`es **`/api`**, **`/docs`**, and **`/openapi.json`** to uvicorn on **:8765** (or a unix socket). Same origin avoids CORS headaches.
2. **FastAPI `StaticFiles`** — In your fork, you can `mount("/", StaticFiles(..., html=True))` *after* registering API routes, so `/` returns `index.html`; keep a backup if you do this, because route order matters.
3. **Two hosts** — Dev-style `VITE_API_ORIGIN=https://api.example.com` in **`frontend/.env` build args** and host **`dist` on a CDN**; ensure Kalshi and session cookies (if you add any later) are compatible with your CORS list.

**Cache busting:** Vite filenames are content-hashed in **`dist/assets/`**; re-run **`npm run build`** after any UI change—operators should hard-refresh (Ctrl+F5) once after deploy.

---

## Development (structured logging + CI)

- **Logging** — The API uses **structlog** with the stdlib: every existing `logger = logging.getLogger(__name__)` call is unchanged. Configure with **`LOG_JSON`** and **`LOG_LEVEL`** in `.env` (see `.env.example`). **Dev** (default `LOG_JSON=0`): colored console. **Prod / Docker** (`LOG_JSON=1`): one **JSON** object per line on stdout, suitable for log aggregators. **Request context**: each HTTP request gets a `request_id` (from the `X-Request-Id` header or a new UUID) bound into the log context and echoed on the response as **`X-Request-Id`**. Implementation: **`backend/app/core/logging.py`**; **`main.py`** calls `configure_logging()` at import and `reset_uvicorn_loggers_to_root()` in the app lifespan so **uvicorn** / **uvicorn.error** / **uvicorn.access** use the same formatter as application logs.
- **CI** — **GitHub Actions** (`.github/workflows/ci.yml` on `main` / `develop`): Python **3.12**, `pip install -r requirements.txt` + `pytest` + `pytest-cov` + `pre-commit`, then **`pre-commit run --all-files`** and **`python -m pytest backend/tests -q --cov=app --cov-report=term-missing`**. Reproduce locally after installing deps:  
  `python -m pip install pytest pytest-cov pre-commit`  
  `pre-commit run --all-files`  
  `LOG_JSON=0 LOG_LEVEL=INFO python -m pytest backend/tests -q --cov=app --cov-report=term-missing`
- For **install, tests, pre-commit, bearer, keyring, and Docker** commands used day-to-day, use [Migration and testing (exact commands)](#migration-and-testing-exact-commands) below (same as earlier phases; no extra flags required for structlog in normal local runs).

---

## Migration and testing (exact commands)

*As of the usual `develop` / `main` workflow (Apr 26, 2026). After applying a full restructure or any incremental phase, verify with the steps below.*

### Install dependencies

From the **repository root** (venv recommended):

```bash
python -m pip install -U pip
python -m pip install -r requirements.txt
```

### Backend tests

Run from **repository root** — `pytest.ini` sets `pythonpath = backend` so `import app.…` resolves without `cd backend`:

```bash
python -m pytest backend/tests -q
```

On Windows, with the venv activated: `.\.venv\Scripts\python.exe -m pytest backend/tests -q`. Install `pytest` first if it is not already in the environment: `python -m pip install pytest`.

### Optional pre-commit hooks (recommended)

```bash
pip install pre-commit
pre-commit install
pre-commit run --all-files
```

Ruff is configured to touch `backend/` only (see `.pre-commit-config.yaml`).

### When enabling API bearer token auth

- **Root `.env`:** set `KALSHI_API_BEARER_TOKEN` to a long random string (no angle brackets in the value).
- **`frontend/.env`:** set `VITE_API_BEARER_TOKEN` to the **same** string so the browser sends `Authorization: Bearer …` on `/api/*`.
- Restart both **uvicorn** and **`npm run dev`**

### Keyring support (optional)

```bash
keyring set kalshibot KALSHI_PRIVATE_KEY_PEM
```

In **`.env`:** `KALSHI_USE_KEYRING=1` (and remove the inline PEM or path). Restart the API.

### Docker (recommended)

```bash
docker volume create kalshibot-data
docker build -t kalshibot-api .
docker run --rm -p 8765:8765 \
  --env-file .env \
  -e SQLITE_PATH=/app/data/bot.sqlite3 \
  -v kalshibot-data:/app/data \
  kalshibot-api
```

---

## Repository layout

- **`backend/app/`** — FastAPI app, engines, Kalshi client, persistence, optimizer.
- **`backend/app/main.py`** — App factory, CORS, lifespan, route registration.
- **`backend/app/engine.py`** — `dual_engine_loop`, `TradingEngine`, rule match / sim trade ranking, per-branch execution (large file: search `rule_matches`, `pick_trade_rule` for behavior).
- **`backend/app/branch_config.py`**, **`persistence.py`** — `merge_branch_config`, `default_bot_config`, SQLite row shapes.
- **`backend/app/optimizer_claude.py`** — `run_optimizer_once` and internal pulse; Claude gating and **Lab A–only** `balance_fraction_per_window` auto-apply.
- **`backend/app/lab_breeding.py`** — Labs Breeding v0.1: child genomes, adoption/replacement, cooldowns, `build_labs_breeding_personality_radar`, toast-oriented log hints.
- **`backend/tests/`** — Pytest: money-path, engine guards, API contracts where present—run from repo root: **`python -m pytest backend/tests -q`** (see [Migration and testing](#migration-and-testing-exact-commands)); **`pytest.ini`** at the repo root sets `pythonpath = backend`.
- **`frontend/src/`** — React dashboard: **`App.tsx`** holds the main board, large equity/compare blocks, **Optimizer / Breeder** footer toggle on the optimizer card, and **Recharts** radars; **`SettingsOverlay.tsx`** is the full-screen config editor.
- **`scripts/`** — Windows PowerShell: venv creation, run API, launch API plus UI.
- **`data/`** — Default SQLite and logs (created at runtime; may be gitignored).
- **`requirements.txt`** — Python dependencies for the API.
- **`pytest.ini`** (repo root) — Sets `pythonpath = backend` so you can run **`python -m pytest backend/tests -q`** from the repo root.
- **`.env.example`** — Documented environment template.
- **`kalshibot-api.spec`**, **`scripts/exe_api_entry.py`** — PyInstaller one-file API **.exe** build; UI still Vite or static-serve in production.
- **`Dockerfile`** — API-only container build (see [Health, alerts, and Docker](#health-alerts-and-docker)).

---

## Developer notes

- **TypeScript** — The frontend uses **Vite 5** + **React**; `npm run build` must be clean before you tag a release; the repo does not commit `frontend/dist/` for every change by default, so your deploy step should `npm run build` and copy **`dist/`** to your static host or add a `StaticFiles` mount in `main.py` if you self-host a single process.
- **Config shape** — When in doubt, **`GET /api/config` is truth**; `BotConfigPayload` in **`backend/app/api_models.py`** documents safe ranges. Partial lab updates go through dedicated routes; never assume the UI holds every key the server defaults.
- **Migrations** — Schema lives in `persistence` helpers; the project favors **forward-additive** SQLite `ALTER` patterns—back up `data/bot.sqlite3` before updating from a much older tag.
- **Recharts / dashboard** — Radar and line charts are standard **Recharts**; avoid adding another charting library for the same tiles unless you refactor. Accessibility: we rely on browser tooltips and ARIA for dialogs where implemented—extra props welcome in small PRs.
- **Branches in git** — **`develop` → `main`** is the typical integration path described at the top of this README; force-push to `main` only in emergencies and coordinate with anyone running forks.

---

## Scripts reference (Windows)

| Script | Purpose |
|--------|---------|
| `scripts\create_venv.ps1` | Create `.venv` and `pip install -r requirements.txt`. |
| `scripts\run_backend.ps1` | Run uvicorn with reload on `127.0.0.1` and `KALSHI_BOT_PORT` (default 8765). |
| `scripts\launch_local.ps1` | Start backend in a new window, wait for `/api/health`, then `npm run dev` in `frontend/`. |

For a frozen **Windows .exe**, see **`kalshibot-api.spec`** and **`scripts/exe_api_entry.py`**. For Linux servers without PowerShell, prefer **`Dockerfile`** or the manual uvicorn command in [macOS and Linux](#macos-and-linux-manual).

---

## Safety and responsibility

- **Real money** can be at risk when **simulate is off** on Live and the **engine posts orders**. Confirm `KALSHI_ENV`, account, and rules before enabling automation.
- Treat **`.env` and private keys** as secrets; do not commit them.
- Use **`DATA_RESET_TOKEN`** if you expose the API beyond localhost.

---

## Troubleshooting

- **401 on `/api/*`** — If you enabled `KALSHI_API_BEARER_TOKEN`, set the same value as `VITE_API_BEARER_TOKEN` in `frontend/.env` and restart Vite, or call the API with `Authorization: Bearer …`.
- **Cannot reach the backend / failed fetch** — Start the API first; use **http://localhost:5173** so the Vite proxy forwards `/api` to uvicorn.
- **404 on `/api`** — You opened the wrong origin (for example only port 8765 without the Vite app). Use port **5173** for normal UI work, or call **8765** directly only for JSON and `/docs`.
- **Port 8765 in use** — Set `KALSHI_BOT_PORT` and matching `VITE_API_ORIGIN` in `frontend/.env`, then restart both processes.
- **Slow `/api/dashboard`** — The payload can be heavy (open positions, order books). The UI may show timeouts; reduce open sim positions, pause engines, or inspect backend logs. Prefer the split routes (`/dashboard/equity`, `/open_positions`, etc.) in custom scripts for automation.
- **Optimizer / radar looks wrong after restore** — If you restored a DB or reset `data/`, the optimizer and equity slopes need fresh snapshots: let engines run, confirm **`GET /api/health`** shows both loops, then recheck. Red streak and acceptance read from optimizer state, not the chart alone.
- **PyInstaller or Docker shows API only** — The Windows `.exe` and **`Dockerfile`** are **API-first**; open the Vite dev app against that API (`VITE_API_ORIGIN`) or build **`frontend/dist`** and serve with nginx—there is no embedded React in the default `Dockerfile` image.

---

## License

This project is released under the [MIT License](LICENSE).

## Contributing

- Default branch for day-to-day work: **`develop`**; release merges use **`main`** (see the intro above).
- Before large Python changes, run **`python -m pytest backend/tests -q`** from the repo root (see [Migration and testing](#migration-and-testing-exact-commands)) and respect **`backend/mypy.ini`**. Do not weaken the **Live + Labs A–D** core model, optional **`lab_child_*`** breeding contracts, **`merge_branch_config`**, or **confirm=YES** gates without explicit review.
- Optional: **`pre-commit install`** (see [Migration and testing](#migration-and-testing-exact-commands) and `.pre-commit-config.yaml`).

## Optional API authentication & hardening

- **`KALSHI_API_BEARER_TOKEN`**: when non-empty, requests to `/api/*` require an `Authorization: Bearer` header whose value matches this secret, except **`GET /api/health`**. The interactive dashboard should set the same value in **`frontend/.env`** as **`VITE_API_BEARER_TOKEN`** (see `frontend/.env.example` and [Migration and testing](#migration-and-testing-exact-commands)). Default is **off** for local use.
- **`CORS_ORIGINS`**: comma-separated **exact** origins (default includes Vite dev URLs). In production, set this to the single origin that serves the dashboard.
- **`KALSHI_USE_KEYRING`**: when `1` and neither inline PEM nor path is set, the Kalshi private key PEM is read from the OS keyring (requires `keyring` in `requirements.txt` and a stored secret under `KALSHI_KEYRING_SERVICE` / `KALSHI_KEYRING_USERNAME`).
- The API sets conservative **security headers** (frame deny, nosniff, etc.). **HSTS** and TLS termination should be configured on your reverse proxy if you expose the service.

---

## Kalshi

This project is an independent tool for the Kalshi API. **Kalshi** is a trademark of KalshiEX LLC. Follow Kalshi's terms of service and API rules when using this software.
