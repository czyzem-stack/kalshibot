# Changelog

All notable project-level changes should be documented in this file.

## v0.4.15.056 - Lab B–E never ticked: stub ``engine_running: false`` + missing-key defaults - 2026-04-29

- **Backend (`persistence.py`):** Legacy ``_normalize_loaded_config`` stubs for **lab_b–lab_e** embedded ``engine_running: false``. ``expand_partial_lab_branch`` merges user dict over defaults, so **False overwrote** shipped breeder defaults (**True**) and kept those labs permanently off. **Fix:** stubs no longer set ``engine_running``; **``_maybe_strip_legacy_breeder_stub_engine_false``** removes the stale false flag when a lab block still matches the old stub fingerprint so the next merge restores defaults.
- **Backend (`branch_config.py`):** ``effective_parent_lab_engine_running`` — when ``engine_running`` is **omitted** on any parent lab (**lab_a–lab_e**), default **on** (explicit ``false`` still pauses).
- **Frontend (`App.tsx`):** Engine polling hint no longer claims outdated global defaults.

## v0.4.15.055 - Paper Live + Lab A: engines on by default - 2026-04-29

- **Backend (`branch_config.py`, `main.py`, `engines/dual_engine_loop.py`):** Introduced ``effective_live_engine_running`` and ``effective_parent_lab_engine_running``. When ``engine_running`` is **omitted**, **Live** ticks in **paper** mode by default (still **off** when ``live_paper_trading`` is false / real money until explicitly enabled). **Lab A** defaults **on** when the key is omitted (staging aligned with breeder labs). Dashboard ``engine_running`` flags and ``/api/engine/status`` use the same semantics so the UI matches the dual loop.
- **Backend (`persistence.py`):** Fresh ``default_bot_config()`` no longer writes ``engine_running: false`` for Live or Lab A (omit keys so effective defaults apply).

## v0.4.15.046 - Reset: stop trade toast spam (SQLite id recycle) - 2026-04-29

- **Frontend (`App.tsx`):** When ``dashboard.trading_data_revision`` advances after ``POST /api/data/reset``, clear trade toast bootstrap state and ``seen`` id sets, drop queued ``trade-initiated-*`` / ``trade-resolved-*`` cards, then re-bootstrap from the current trade lists only — so recycled low SQLite ids are not treated as brand-new fills across every branch.

## v0.4.15.045 - Fast equity merge: Lab E stale chart after reset - 2026-04-29

- **Frontend (`App.tsx`):** When ``trading_data_revision`` advances, ``mergeDashboardFastPoll`` now treats **missing** ``equity_snapshots_lab_*`` / list keys on the partial ``GET /api/dashboard/equity`` payload as **empty arrays** instead of leaving the previous merge spread (often leaving **Lab E** with old points while C/D cleared).

## v0.4.15.044 - Reset clears chart data (revision + merge fix) - 2026-04-29

- **Frontend (`App.tsx`):** ``mergeDashboardFastPoll`` no longer resurrects **pre-reset** equity/trade series when the fast GET ``/api/dashboard/equity`` returns empty arrays after a wipe — it treats empty arrays as authoritative when ``trading_data_revision`` has advanced (see backend).
- **Backend (`persistence.py`, `main.py`):** ``Store`` tracks a monotonic ``trading_data_revision`` incremented on every ``reset_trading_data`` commit; **full and partial** dashboard payloads include it; reset API responses include the new revision. **``all_labs``** wipes now also delete **``lab_child_1``–``lab_child_6``** SQLite rows (aligned with seed snapshots and breeding engines).

## v0.4.15.043 - Breeder council trading + distinct B–E defaults - 2026-04-29

- **Backend (`lab_communication.py`):** Think Tank bus now maintains an ephemeral **`council_signal`** for engines (`think_tank_yes_no_bias_last_n`, `refresh_engine_council_signal`, `peek_engine_council_signal`). It refreshes at the end of each breeder **`finalize_think_tank_tick`** and after **`POST /labs/diversify`** so the next tick can read YES/NO lean, strength, and diversity context.
- **Backend (`engines/engine.py`):** Labs **B–E** apply per-lab **personality drift**, **follow vs fade** of council lean (stronger under **diversity pulse**), **Lab D** occasional consensus flip, **Lab E** extra weight on strong signals, **time-to-close** scaling on tilt and sim-rank **edge**. Rule matching uses an effective YES probability; logged mids stay the real book. **`GET /api/optimizer/status`** exposes **`council_influence_active`** when a signal is queued or a breeder tick applied tilt.
- **Backend (`persistence.py`):** When a breeder has **no rules** and there is no global rules list, each lab gets its own **`_breeder_fallback_rules_for`** pack (tight B, wide/aggressive C, experimental D, balanced E). Default config uses those packs and raised **lab_b** / lowered **lab_c** optimizer yes-floor defaults.
- **Frontend (`App.tsx`, `SettingsOverlay.tsx`):** Optimizer strip shows **Council influence active** when the status flag is true; Settings **Diversify council** control is a **compact secondary** button next to the primary **Force** action.

## v0.4.15.042 - Equity “Live” tab: 6-hour dense window - 2026-04-29

- **Frontend (`App.tsx`, `dashboardPolling.ts`):** The **Live** time-scale tab (granularity id ``hourly``) now plots a **rolling 6 hours** of **dense** SQLite ticks (same treatment as **Intraday**, no hourly bucketing). Caps at **2500** points like Intraday. Tab tooltips and Equity **Info** copy updated (removed outdated “7 days / hourly bucket / calendar bucket” language for Live and D–Y).

## v0.4.15.041 - Equity charts: linear time on X-axis (``tsMs``) - 2026-04-29

- **Frontend (`App.tsx`):** Equity **``LineChart``** used **``XAxis`` ``dataKey="t"``** (formatted strings), so Recharts treated the axis as **categories** — consecutive points were **evenly spaced** regardless of real time. That made a **~52 minute** gap and a **~40 second** gap look the same and produced misleading “same timestamp” clusters. Switched to **``type="number"``**, **``dataKey="tsMs"``**, **``domain={['dataMin','dataMax']}``** (epoch ms, linear scale), tick + tooltip formatters from milliseconds. Applied the same fix to the **Compare** overlay chart. **``fmtEquityCompareXTick``** now formats numeric ticks; string fallback kept for edge labels.

## v0.4.15.040 - Optimizer: remove breeding blurb under title - 2026-04-29

- **Frontend (`App.tsx`):** Removed the extra **``dash-optimizer-breeding-hook``** paragraph (breeding / manual nukes / POST endpoints) above the breeding snapshot pill — the pill and **Info** tooltip still cover that context.

## v0.4.15.039 - Equity D/D–Y/Y: dense rolling snapshot history - 2026-04-29

- **Frontend (`dashboardPolling.ts`, `App.tsx`):** **D / D**, **W / W**, **M / M**, and **Y / Y** equity tabs no longer use **one point per closed calendar bucket** (which looked empty or flat until a new “resolved” period). They now use the **same dense SQLite tick stream** as **Intraday**, filtered by a **rolling wall-clock window** per tab and **uniformly downsampled** to at most **280** points for chart performance. **Intraday** (24h) and **Live** (hourly buckets, 7d) behavior is unchanged. Added **``surfaceHint``** “Rolling history — dense ticks” under each equity chart and the Compare overlay when those tabs are active.
- **Backend (`main.py`):** Raised per-branch **``equity_series``** fetch limit for the dashboard payload from **2000 → 4000** so long windows still have enough newest-first rows after the client window filter.

## v0.4.15.038 - Bottom marquee: hide horizontal scrollbar (clip + drift) - 2026-04-29

- **Frontend (`styles.css`):** Bottom ticker viewport used **``overflow-x: auto``**, which showed the **native horizontal scrollbar** under the text. Switched to **``overflow: hidden``** so the strip **clips** while **CSS drift** still scrolls the track; removed the reduced-motion **``overflow-x: auto !important``** override for the bottom variant. **``justify-content: center``** on the scroll row to help **vertical** centering of the line in the host.

## v0.4.15.037 - Bottom marquee: one horizontal row (nowrap + fixed strip height) - 2026-04-29

- **Frontend (`styles.css`, `App.tsx`):** The bottom **``BranchHeroMarquee``** could still render as **many wrapped lines** (Live + each Lab read like separate rows) because long copy **wraps at spaces** inside **inline-block** chunks and the host **grew in height**. Enforced **``white-space: nowrap``** on the track, chunks, branches, and **``.ticker-seg``**; **``inline-flex``** + **``flex-wrap: nowrap``** on chunks/branches; **``width: max-content``** on the track; **``overflow-x: auto``** on the marquee viewport; **``max-height``** on **``.app-bottom-marquee``** and the inner root so the strip stays **one scannable line** (scroll/drag when wider than the screen). Host inline **``height`` / ``maxHeight`` / ``overflow: hidden``** aligned with **``--app-bottom-marquee-h``** for page padding.
- **Frontend (`BranchMarketTickers.tsx`, `styles.css`):** Under **``prefers-reduced-motion``**, the bottom strip still **runs the CSS drift** (``embedVariant === "bottomBodyRoot"`` skips the JS animation kill) so **all-branch text keeps cycling horizontally**; wrap/no-animation rules are scoped to **``.branch-hero-marquee:not(.branch-hero-marquee--bottom-body-root)``** only.

## v0.4.15.036 - Bottom marquee vs reduced-motion wrap - 2026-04-29

- **Frontend (`styles.css`):** Under **`prefers-reduced-motion: reduce`**, global ticker rules set **`flex-wrap: wrap`** and **`white-space: normal`** on **``.branch-ticker-track-inner``** / **``.branch-ticker-chunk``**, which turned the **fixed bottom** **``BranchHeroMarquee``** into **many wrapped lines** inside a **short** host (dead space on top, **bottom rows clipped**). Added overrides for **``.branch-hero-marquee--bottom-body-root``** so that strip stays **one row** (**``nowrap``**, **``width: max-content``**) and uses the existing **horizontal scroll** on the marquee viewport.

## v0.4.15.035 - Bottom marquee: vertical center + border chrome - 2026-04-29

- **Frontend (`styles.css`, `App.tsx`):** The body ticker host is a **flex row** with **`align-items: center`** so the marquee sits vertically in the strip. **Bottom-body-root** uses **flex** on the scroll row and marquee (replacing **`display: block`**, which dropped **`align-items: center`**). **Nested card** border, radius, and gradient on **``.branch-hero-marquee``** are cleared inside **``.app-bottom-marquee``** so only the host **top border** frames the strip (avoids uneven / clipped rounded corners at the screen edge). **``outline: none``** on focus for that subtree so a clipped default focus ring does not read as a stray white border.

## v0.4.15.034 - Bottom marquee: ``embedVariant="bottomBodyRoot"`` (no ticker-only collapse) - 2026-04-29

- **Frontend (`BranchMarketTickers.tsx`, `App.tsx`, `styles.css`):** The body-mounted bottom strip still used **``branch-hero-marquee--ticker-only``** (flex + ``min-height: 0``), which could **collapse the scrolling row** outside the main dashboard flex context. Added **``embedVariant="bottomBodyRoot"``** on **``BranchHeroMarquee``** for the **``createRoot``** host only, with class **``branch-hero-marquee--bottom-body-root``** and **block layout + explicit min-heights** so the marquee track always has height. Removed the **``data-kalshibot-bottom-ticker``** attribute and the v0.4.15.033 host-only overrides (superseded by this layout variant).

## v0.4.15.033 - Bottom ticker visible (fix ticker-only collapse) - 2026-04-29

- **Frontend (`styles.css`):** When the hero marquee runs as **ticker-only** inside the **body-mounted** host (`[data-kalshibot-bottom-ticker="1"]`), **flex + ``min-height: 0``** on ``.branch-hero-marquee__scroll`` could **collapse the scroll row to zero height** — only the host’s **top border** (looked like a thin cyan line) stayed visible. Added overrides: **non-zero min-heights**, **``flex: 0 1 auto``**, **``position: relative``**, **``overflow: visible``** on the strip, and **removed ``mask-image``** on the track for that host so text always paints.
- **Frontend (`App.tsx`):** Host **``borderTop``** toned down from a thick cyan debug line to **``1px solid var(--border)``** (CSS variables apply on ``body``).

## v0.4.15.032 - Bottom ticker: dedicated ``createRoot`` on ``body`` - 2026-04-29

- **Frontend (`App.tsx`):** Replaced **`createPortal`** with a **``<div>`` on ``document.body``** plus **`createRoot`** from **`react-dom/client`**. One **`useLayoutEffect`** creates the host (if needed) and **`root.render(<BranchHeroMarquee … />)`** on each **`dash` / `cfg` / hero speed** update — **not** split into mount + update effects, because **React Strict Mode** was running the mount effect’s cleanup and **removing the host before the update effect ran**, so the ticker never appeared. A separate **`useEffect`** with an empty dependency array **only** tears down the root on **App unmount**. **Try/catch** around **`root.render`**; inline **`z-index: 2400`**. Root **``.page``** is a **single div** again.

## v0.4.15.031 - Bottom ticker: always-on body portal - 2026-04-29

- **Frontend (`App.tsx`):** Root return is now a **fragment**: **``.page``** and the bottom ticker **portal are siblings** (portal is no longer nested under ``#root``’s div tree). The ticker **always** mounts to **`document.body`** in the browser — it is **no longer gated on ``tickerDash``**, so the strip is present even before the first `/api/dashboard` payload; **`BranchHeroMarquee`** receives **`tickerDash ?? {}`** (placeholders until data exists). **Critical layout** (``position``, ``zIndex: 2400``, ``minHeight``, solid background) is applied with **inline styles** so outer CSS cannot collapse or hide the bar.

## v0.4.15.030 - Bottom ticker: body portal + no blur compositing - 2026-04-29

- **Frontend (`App.tsx`):** Bottom **`BranchHeroMarquee`** again uses **`createPortal(..., document.body)`** so it is not clipped by **`#root` / `.page`** or nested scroll/overflow. Renders only when **`tickerDash`** is set (live **`dash`** or **`dashSnapshotRef`** fallback).
- **Frontend (`styles.css`):** Removed **`backdrop-filter`** / **`translateZ(0)`** / **`isolation`** / **`backface-visibility`** from **`.app-bottom-marquee`** — on some Windows + GPU drivers those compositing paths made the fixed strip **not paint**. Solid **`#0d1228`** background and **`z-index: 1950`** (below loading **2000**, above chart overlays).

## v0.4.15.029 - Bottom ticker: first paint + snapshot dash - 2026-04-29

- **Frontend (`App.tsx`):** Dropped **`createPortal`** for the bottom ticker. The strip is the **first child** of **`.page`** (above the toast stack and dashboard grid) so it is **never under Recharts** / transformed subtrees. It renders from **`tickerDash = dash ?? dashSnapshotRef.current`** so it stays on screen if `dash` is briefly unset while a prior payload remains in the ref. **`cfgWithHeroMarqueeSpeed`** now prefers **`tickerDash.config`** with **`dashboardConfigFallbackRef`** so the marquee still has simulate / lab keys when only the snapshot ref is available. **`.page--bottom-marquee`** follows **`tickerDash`** so bottom padding matches whenever the strip is shown.

## v0.4.15.028 - Bottom branch ticker portal - 2026-04-29

- **Superseded by v0.4.15.029** (portal alone did not reliably restore the bar in practice). Kept **`z-index: 1350`** on **`.app-bottom-marquee`** from this release.

## v0.4.15.027 - Equity charts after reset + paper MTM refresh - 2026-04-29

- **Frontend (`App.tsx`):** Equity **live tail** from dashboard metrics (book + MTM) now appends on **every** granularity tab (D/D, W/W, M/M, Y/Y), not only Intraday/Hourly — so after a data reset, curves still track **current** values between snapshot buckets instead of looking flat vs open positions.
- **Backend (`main.py`, `settings_env.py`):** Paper MTM refresh uses a **per-branch** `asyncio.wait_for` instead of one timeout on the whole batch — one slow lab no longer cancels mark refresh for all branches. Default **`DASHBOARD_FAST_MTM_GATHER_TIMEOUT_S`** raised **22 → 30** (still capped 5–120s).

## v0.4.15.026 - Optimizer nukes → Settings only - 2026-04-29

- **Frontend:** Removed **force** and **Diversify Labs** from the Optimizer dashboard card (automation-first). **Nuke options** remain under **Settings → Optimizer → Manual / nuke**: **Force Internal Mutation Now** and **Diversify council (Think Tank)** (same `POST` endpoints as before). **Info** copy and breeding blurb point to Settings / `curl`. Backend routes unchanged.

## v0.4.15.025 - Optimizer force vs Diversify visuals - 2026-04-29

- **Frontend (`App.tsx`, `styles.css`):** **force** and **Diversify Labs** are no longer the same “primary” pill — **force** uses an **amber / warm** stacked button (“Self-correct Lab A”); **Diversify Labs** uses a **teal** stacked button (“Self-correct council”). **report** / **Info** stay the standard primary style. Tooltips and Info copy frame both as **self-correcting** controls (Lab A mutation+replay vs council-only dispute window).

## v0.4.15.024 - Optimizer header layout + less copy - 2026-04-29

- **Frontend (`App.tsx`, `styles.css`):** Optimizer title row wrapped in **`dash-optimizer-panel__head-top`** so **Optimizer** no longer truncates beside buttons; removed redundant **force / Diversify** legend line (tooltips + **Info** keep detail). **Breeding** blurb shortened to one tight line.

## v0.4.15.023 - Force vs Diversify split (council quota) - 2026-04-29

- **Think Tank (`lab_communication.py`):** During **`labs_council_diversity_until`**, a rolling deque holds **~40–50%** of recent peer + strategic lines on the **adversarial (direct counter)** pool; quota nudges probabilities up/down to stay in band. **Extra opposing-thesis lines** when the pulse is active; **less “team” fluff** on peer/strategic lines; **breeding_whisper** cooperative lines **suppressed** for that window so they do not dilute the dispute tone.
- **Frontend:** One-line **legend** under the Optimizer action row (**force** = Lab A mutation + replay; **Diversify Labs** = B–E chat-only 45m). Tooltips/aria updated to match.

## v0.4.15.022 - Optimizer Think Tank + diversify UX - 2026-04-29

- **POST /labs/diversify** is now a **council-only** pulse: sets **`labs_council_diversity_until`** (~45m), posts **DIVERSITY PULSE** lines to the Think Tank, and **does not** run internal mutation or change breeder gates (distinct from **force**). Legacy **`emergency_diversify_*`** gate windows still auto-revert on expiry. **`load_config`** also clears expired **`labs_council_diversity_until`**.
- **Think Tank (`lab_communication.py`):** reads the diversity window to **raise adversarial/strategic fractions**, slightly **tighter pulse gaps**, and **looser proactive share caps**; message cap **58** chars; a bit blunter copy. **`GET /api/optimizer/status`** exposes **`labs_council_diversity_until`** for the UI.
- **Frontend:** **force** unchanged; **Diversify Labs** is a small neutral button. **Lab Think Tank** — no emoji avatars, **why?** per-line explainer (action / confidence / thread), diversity banner when the window is active. **Tree → Family** adds an **SVG lineage graph** from **`labs_breeding_tree_snapshot.edges`**. **Info** copy distinguishes force vs diversify.

## v0.4.15.021 - Think Tank adversarial + Emergency Diversify - 2026-04-29

- **Backend (`lab_communication.py`):** Breeding Council dialogue — **~40% adversarial** peer replies and strategic pulses (counter-thesis YES/NO, pushback on **C**, “fake edge / sitting out”, opposing sizing). **Stronger anti-monopoly:** C proactive damp when C’s recent share is high; tighter **overrepresented** / **needs voice** thresholds so **B/D/E** re-enter sooner against **C** dominance. Message cap **69** chars.
- **Backend (`lab_diversify.py`, `main.py`, `persistence.py`):** **`POST /labs/diversify`** — bumps **optimizer** `lab_*_yes_floor_pct` and per-lab **`no_bet_when_yes_below_pct`** for breeders **B–E**, persists **`emergency_diversify_revert_at`** (~45m) + baseline snapshot, **`force_internal_mutation_once`**, and **Think Tank** banner from each breeder. **`load_config`** (outside DB lock) auto-reverts when the window expires.
- **Frontend (`App.tsx`, `styles.css`):** Optimizer title row — **Emergency Diversify** button (🚨) next to **force**; calls **`POST /labs/diversify`** with loading state + refresh hooks.

## v0.4.15.020 - equity UX + README equity deep dive - 2026-04-29

- **Frontend (`App.tsx`, `styles.css`):** Equity **Compare** overlay — **granularity tabs** (Intraday…Y/Y) in-modal synced with dashboard; **Compare** moved beside **Info**; dashboard controls layout (**$/%Δ** toggle, no orphan scrollbar); overlay chart **step-after** lines, compact axes, duplicate legend removed; shared **`EQUITY_GRANULARITY_TAB_DEFS`**.
- **Hours / days:** **Hourly** tab (local hour buckets, rolling 7d); **D/D** buckets **local** calendar days.
- **README:** Large new section [**Equity curves (deep dive)**](README.md#equity-curves-deep-dive) — time tabs, $/%Δ, Compare semantics, API snapshot limits, how to read book vs MTM; TOC updated.

## v0.4.15.019 - equity intraday 24h window - 2026-04-29

- **Frontend (`App.tsx`):** **Equity curves → Intraday** now plots snapshots from the **rolling last 24 hours** (wall clock). Previously the UI took only the **last 400** snapshot rows, which at tight engine cadence looked like “a few hours.” **D / D**, **W / W**, etc. unchanged (UTC calendar buckets). Docs: [`README.md`](README.md) Dashboard map.

## v0.4.15.018 - footer marquee smoothness - 2026-04-29

- **Frontend (`App.tsx`, `styles.css`):** Branch active-trades ticker and Lab pulse marquee — **rAF-coalesced** `ResizeObserver`, **skip redundant** `needsScroll` updates, **tiered** `animation-duration` so dashboard polls do not restart the CSS animation on tiny text changes; **`translate3d`** keyframes, **`will-change`** only while scrolling, compositing hints and **`isolation`** on masked viewports to reduce flicker.

## v0.4.15.017 - series_open log gate tightened - 2026-04-29

- **Backend (engines/engine.py):** series_has_open_sim dedupe key no longer includes matched rule/side (dedupe_key). It now gates by **window + branch + series**, preventing repeated INFO lines for the same blocked series in one window when different rules fire.

## v0.4.15.016 - sim_trade_block log dedupe - 2026-04-29

- **Backend (`engines/engine.py`):** **`[sim_trade_block] series_has_open_sim`** `logger.info` now shares the same **`_sim_transient_skip_logged`** gate as **`log_signal`** — one line per window+key per branch, not every tick while an older contract blocks the series.

## v0.4.15.015 - README overhaul - 2026-04-29

- **README:** Stronger onboarding — **Run it (TL;DR)** (Windows + Unix copy-paste), **Safety** callout, **Operator playbook** (Mass apply, lab toggles, Think Tank logs, dual Vite ports), **Upgrading & parallel checkouts**, **Glossary**, expanded troubleshooting, merged duplicate testing into **Development & testing**, fixed dynamic version line (see **`VERSION`**).
- **README-short:** Version row points at **`VERSION`** / **`CHANGELOG`** instead of a stale literal.

## v0.4.15.014 - UI track pill: port 5175 + dev port wins - 2026-04-29

- **Frontend (`uiTrack.ts`, `App.tsx` tooltip, `frontend/.env.example`):** Map dev URL **:5175** → **`test`** (tab title / pill). In **`vite dev`**, **5173 / 5174 / 5175** infer track **before** `VITE_UI_TRACK`, so **:5174** and **:5175** are not both labeled **`dev`** when `.env` pins `VITE_UI_TRACK=dev`.

## v0.4.15.013 - Think Tank default silent logs - 2026-04-29

- **Backend (`lab_communication.py`):** **`think_tank_message`** is emitted only when **`LAB_THINK_TANK_LOG_INFO=1`**. Default no longer logs at **DEBUG** (that still flooded consoles when **`LOG_LEVEL=DEBUG`**).
- **Docs:** **README**, **`.env.example`**, **`settings_env.py`** comments aligned.

## v0.4.15.012 - Breeding relevance (docs + Optimizer hook) - 2026-04-29

- **README / README-short:** Lead with **Labs Breeding** as the strategic loop (B–E → `lab_child_*` → pool / death chamber → gated adoption → Lab A); new section **Labs Breeding (the closed loop)**; branch table gains **Breeding role** column; Think Tank explicitly **cosmetic**; API/dashboard rows clarified.
- **Frontend (`App.tsx`):** Optimizer card — short **Labs Breeding** hook paragraph above the pool/death-chamber strip; **Info** overlay opens with a **Labs Breeding (substance)** paragraph before the existing Optimizer explanation.
- **Frontend (`SettingsOverlay.tsx`, `settingsHelpPlaybook.tsx`):** Simulation labs + help playbook tie **Labs B–E** to breeder parents and point to **Optimizer → Breeder / Tree**.

## v0.4.15.011 - Settings mass apply + lab toggle fix + Think Tank log hygiene - 2026-04-29

- **Frontend (`SettingsOverlay.tsx`):** **Mass apply** under Simulation labs — select Labs A–E, choose action (engines on/off, uniform paper, copy sizing from active tab, copy patient stop from a source lab, auto-reset on/off), confirm once; uses **`PUT /api/config/lab-branches`**.
- **Frontend (`App.tsx`):** Lab engine **Turn A/B/C/D/E on|off** now persists via **`PUT /api/config/lab-branches`** (same as Mass apply) instead of **`POST /api/engine/toggle?*_running=`**, so Lab **E** (and consistency across labs) works even when the API build predates **`lab_e_running`** on the toggle route.
- **Backend (`main.py`):** Dashboard **`lab_*_engine_on`** / Live uses **`_coerce_engine_running_flag`** so stringly-typed config matches **`dual_engine_loop`** coercion.
- **Backend (`lab_communication.py`, `settings_env.py`):** **`think_tank_message`** logs default to **DEBUG**; optional **`LAB_THINK_TANK_LOG_INFO=1`** restores **INFO** per line.
- **Docs:** [`.env.example`](.env.example) documents **`LAB_THINK_TANK_LOG_INFO`**; **README** Configuration section expanded.

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

