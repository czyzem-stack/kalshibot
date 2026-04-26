import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";

type AnyObj = Record<string, any>;

type BranchKey = "live" | "lab_a" | "lab_b" | "lab_c" | "lab_d";

type Tone = "pos" | "neg" | "yes" | "no" | "muted" | "warn";

type TickerSeg = { text: string; tone?: Tone };

function seg(text: string, tone?: Tone): TickerSeg {
  return { text, tone };
}

function dot(): TickerSeg {
  return { text: " · ", tone: "muted" };
}

function fmt$(n: number) {
  const sign = n < 0 ? "-" : "";
  return `${sign}$${Math.abs(n).toFixed(2)}`;
}

function fmtNum$(v: unknown): string {
  if (v == null || v === "") return "—";
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  return fmt$(n);
}

function ReturnBadge({ metrics }: { metrics: AnyObj }): ReactNode {
  const rawMtm = metrics?.return_mtm_vs_start_pct;
  const x =
    rawMtm != null && Number.isFinite(Number(rawMtm)) ? Number(rawMtm) : Number(metrics?.return_vs_start_pct);
  if (!Number.isFinite(x)) return null;
  const arrow = x > 0 ? "▲" : x < 0 ? "▼" : "—";
  const sign = x > 0 ? "+" : "";
  const tone: Tone = x > 0 ? "pos" : x < 0 ? "neg" : "muted";
  return (
    <span className={`branch-ticker-portfolio-ret ticker-seg--${tone}`}>
      <span className="branch-ticker-portfolio-ret-arrow" aria-hidden>
        {arrow}
      </span>
      <span>
        {sign}
        {x.toFixed(1)}%
      </span>
    </span>
  );
}

function isNoiseBlob(raw: string): boolean {
  const s = raw.toLowerCase();
  return (
    s.includes("no_contract") ||
    s.includes("no open rows") ||
    s.includes("raw open rows") ||
    s.includes("after filters") ||
    s.includes("returned no markets")
  );
}

/** Config/credential messages — headline already shows “keys off”; do not scroll in marquee. */
function isCredentialOrEnvMarqueeNoise(raw: string): boolean {
  const s = String(raw).toLowerCase();
  if (isNoiseBlob(raw)) return true;
  if (s.includes("kalshi_api") || s.includes("api_key") || s.includes("api key")) return true;
  if (s.includes("is not set") || s.includes("not set") || s.includes("missing key")) return true;
  if (s.includes("private key") || s.includes("pem") || s.includes("rsa private")) return true;
  if (s.includes(".env") && (s.includes("missing") || s.includes("not set") || s.includes("read"))) return true;
  return false;
}

function snapIsUseful(snap: AnyObj): boolean {
  if (!snap?.ok) return false;
  const blob = `${snap.reason || ""} ${snap.note || ""}`;
  if (isNoiseBlob(blob)) return false;
  const book = Boolean(snap.has_orderbook);
  const y = snap.implied_prob != null && Number.isFinite(Number(snap.implied_prob)) ? Number(snap.implied_prob) : NaN;
  const bid = snap.yes_bid != null ? Number(snap.yes_bid) : NaN;
  const ask = snap.yes_ask != null ? Number(snap.yes_ask) : NaN;
  if (!book) {
    if (!Number.isFinite(y) || y < 0.02) return false;
    return true;
  }
  const deadBook = (Number.isFinite(bid) && Number.isFinite(ask) && bid <= 0 && ask <= 0) || (!Number.isFinite(y) && !Number.isFinite(bid));
  if (deadBook && (!Number.isFinite(y) || y < 0.02)) return false;
  return true;
}

function orderedAssets(assetsObj: AnyObj | undefined): [string, AnyObj][] {
  const entries = Object.entries(assetsObj || {}) as [string, AnyObj][];
  const rank = (id: string) => (id === "btc" ? 0 : id === "eth" ? 1 : 2);
  return [...entries].sort((a, b) => {
    const d = rank(a[0]) - rank(b[0]);
    if (d !== 0) return d;
    return String(a[0]).localeCompare(String(b[0]));
  });
}

/** One asset line: label + ticker + YES% (green/red vs 50%) + bid/ask + time — only if useful data. */
function monitoringSegments(assets: [string, AnyObj][], snaps: Record<string, AnyObj>): TickerSeg[] {
  const out: TickerSeg[] = [];
  for (const [assetId, acfg] of assets) {
    if (!acfg?.enabled) continue;
    const label = String(acfg.label || assetId).toUpperCase();
    const s = snaps[assetId];
    if (!s || !snapIsUseful(s)) continue;
    if (out.length) out.push(dot());
    const tick = String(s.ticker || "").slice(0, 28);
    const y =
      s.implied_prob != null && Number.isFinite(Number(s.implied_prob)) ? Math.round(Number(s.implied_prob) * 100) : null;
    const bid = s.yes_bid != null && Number.isFinite(Number(s.yes_bid)) ? Number(s.yes_bid).toFixed(2) : "—";
    const ask = s.yes_ask != null && Number.isFinite(Number(s.yes_ask)) ? Number(s.yes_ask).toFixed(2) : "—";
    const mins =
      s.minutes_left != null && Number.isFinite(Number(s.minutes_left))
        ? `${Number(s.minutes_left).toFixed(1)}m`
        : "—";
    const rules = Array.isArray(s.rules_matched) ? (s.rules_matched as string[]).filter(Boolean) : [];
    const askN = Number(ask);
    const bidN = Number(bid);
    const bookTone: Tone = Number.isFinite(askN) && Number.isFinite(bidN) && askN > 0 && bidN > 0 ? "pos" : "muted";
    out.push(seg(`${label} `, "warn"), seg(tick || "—", "muted"), seg(" YES ", "muted"));
    if (y != null) {
      const lean: Tone = y >= 50 ? "yes" : "no";
      out.push(seg(`${y}%`, lean));
    } else out.push(seg("—%", "muted"));
    out.push(seg(` bid ${bid} ask ${ask} `, bookTone), seg(mins, "muted"));
    if (rules.length) {
      out.push(seg(" rules ", "muted"), seg(rules.join(", "), "yes"));
    }
  }
  return out;
}

function parsePulseFields(lines: unknown): Record<string, string> {
  const out: Record<string, string> = {};
  if (!Array.isArray(lines)) return out;
  for (const raw of lines as unknown[]) {
    const s = String(raw || "");
    const chunks = s.split("|").map((x) => x.trim()).filter(Boolean);
    for (const c of chunks) {
      const i = c.indexOf("=");
      if (i <= 0) continue;
      const k = c.slice(0, i).trim();
      const v = c.slice(i + 1).trim();
      if (!k) continue;
      out[k] = v;
    }
  }
  return out;
}

function toneForPct(raw: string): Tone {
  const n = Number(String(raw || "").replace("%", "").trim());
  if (!Number.isFinite(n)) return "muted";
  if (n > 0) return "pos";
  if (n < 0) return "neg";
  return "muted";
}

function toneForYes(raw: string): Tone {
  const n = Number(String(raw || "").replace("%", "").trim());
  if (!Number.isFinite(n)) return "muted";
  return n >= 50 ? "yes" : "no";
}

function labPulseFallbackSegments(branch: BranchKey, labThoughts: AnyObj | undefined): TickerSeg[] {
  const lt = labThoughts && typeof labThoughts === "object" ? labThoughts : {};
  const key = branch === "lab_a" ? "lab_a" : branch === "lab_b" ? "lab_b" : branch === "lab_c" ? "lab_c" : branch === "lab_d" ? "lab_d" : "lab_a";
  const rows = Array.isArray((lt as AnyObj)[key]) ? ((lt as AnyObj)[key] as unknown[]) : [];
  const f = parsePulseFields(rows);
  if (!Object.keys(f).length) return [seg("No market update yet.", "muted")];
  const tag =
    branch === "live" ? "Lab pulse (A)" : branch === "lab_a" ? "Lab pulse (A)" : branch === "lab_b" ? "Lab pulse (B)" : branch === "lab_c" ? "Lab pulse (C)" : "Lab pulse (D)";
  const yes = f.implied_yes_latest || "na";
  const ret = f.return || "na";
  const streak = f.streak || "0";
  const trig = f.trigger_remaining || "na";
  const pnl = f.last_settle_pnl_cents || "na";
  const pnlN = Number(pnl);
  const pnlTone: Tone = Number.isFinite(pnlN) ? (pnlN > 0 ? "pos" : pnlN < 0 ? "neg" : "muted") : "muted";
  return [
    seg(`${tag} | no market feed `, "warn"),
    seg("YES ", "muted"),
    seg(yes, toneForYes(yes)),
    seg(" · Return ", "muted"),
    seg(ret, toneForPct(ret)),
    seg(" · Streak ", "muted"),
    seg(streak, Number(streak) >= 2 ? "warn" : "muted"),
    seg(" · Trigger ", "muted"),
    seg(trig, Number(trig) === 0 ? "warn" : "muted"),
    seg(" · LastPnL ", "muted"),
    seg(pnl, pnlTone),
  ];
}

function qtyTone(q: number): Tone {
  if (q > 0) return "yes";
  if (q < 0) return "no";
  return "muted";
}

function kalshiOpenSegments(rows: unknown, assetLabel: string): TickerSeg[] {
  const arr = Array.isArray(rows) ? (rows as AnyObj[]) : [];
  if (!arr.length) return [];
  const out: TickerSeg[] = [seg(`${assetLabel} `, "muted"), seg("Kalshi ", "muted")];
  for (let i = 0; i < arr.length; i++) {
    const r = arr[i];
    if (i) out.push(seg(" · ", "muted"));
    const t = String(r.ticker || "").slice(0, 26);
    const q = Number(r.position != null ? r.position : (r.position_fp ?? 0));
    out.push(seg(t, "muted"), seg(" ×", "muted"), seg(String(Math.abs(q) || 0), qtyTone(q)));
  }
  return out;
}

function simOpenSegments(rows: unknown, assetLabel: string, tag: string): TickerSeg[] {
  const arr = Array.isArray(rows) ? (rows as AnyObj[]) : [];
  if (!arr.length) return [];
  const prefix: TickerSeg[] =
    tag === "Lab A" || tag === "Lab B"
      ? [seg(`${assetLabel} `, "muted")]
      : tag === "Live"
        ? [seg(`${assetLabel} `, "muted"), seg("paper ", "muted")]
        : [seg(`${assetLabel} `, "muted"), seg(`${tag} `, "muted")];
  const out: TickerSeg[] = [...prefix];
  for (let i = 0; i < arr.length; i++) {
    const r = arr[i];
    if (i) out.push(seg(" · ", "muted"));
    const t = String(r.ticker || "").slice(0, 26);
    const q = Number(r.contracts_fp ?? r.contracts ?? 0);
    out.push(seg(t, "muted"), seg(" ", "muted"), seg(`${q > 0 ? "+" : ""}${q.toFixed(2)}`, qtyTone(q)));
  }
  return out;
}

function positionSegmentsForBranch(
  positionByAsset: AnyObj | undefined,
  branch: BranchKey,
  kalshiOk: boolean,
): TickerSeg[] {
  const pb = positionByAsset && typeof positionByAsset === "object" ? positionByAsset : {};
  const blocks: TickerSeg[][] = [];
  for (const [, row] of Object.entries(pb)) {
    if (!row || typeof row !== "object") continue;
    const r = row as AnyObj;
    const lab = String(r.label || "");
    if (branch === "live") {
      if (kalshiOk && Array.isArray(r.kalshi_open) && r.kalshi_open.length) {
        blocks.push(kalshiOpenSegments(r.kalshi_open, lab));
      }
      if (Array.isArray(r.bot_sim_open_live) && r.bot_sim_open_live.length) {
        blocks.push(simOpenSegments(r.bot_sim_open_live, lab, "Live"));
      }
    } else if (branch === "lab_a") {
      const rows = r.bot_sim_open_lab_a || r.bot_sim_open_lab;
      if (Array.isArray(rows) && rows.length) blocks.push(simOpenSegments(rows, lab, "Lab A"));
    } else if (branch === "lab_b" && Array.isArray(r.bot_sim_open_lab_b) && r.bot_sim_open_lab_b.length) {
      blocks.push(simOpenSegments(r.bot_sim_open_lab_b, lab, "Lab B"));
    } else if (branch === "lab_c" && Array.isArray(r.bot_sim_open_lab_c) && r.bot_sim_open_lab_c.length) {
      blocks.push(simOpenSegments(r.bot_sim_open_lab_c, lab, "Lab C"));
    } else if (branch === "lab_d" && Array.isArray(r.bot_sim_open_lab_d) && r.bot_sim_open_lab_d.length) {
      blocks.push(simOpenSegments(r.bot_sim_open_lab_d, lab, "Lab D"));
    }
  }
  if (!blocks.length) return [];
  const out: TickerSeg[] = [];
  for (const b of blocks) {
    if (out.length) out.push(dot());
    out.push(...b);
  }
  return out;
}

function normBranch(b: unknown): BranchKey {
  const s = String(b ?? "live").trim().toLowerCase();
  if (s === "lab_a" || s === "sim_lab") return "lab_a";
  if (s === "lab_b") return "lab_b";
  if (s === "lab_c") return "lab_c";
  if (s === "lab_d") return "lab_d";
  return "live";
}

function tradeSegments(t: AnyObj): TickerSeg[] {
  const tick = String(t.ticker || "").slice(0, 26);
  const side = String(t.side || "").toLowerCase();
  const st = String(t.status || "").toLowerCase();
  const sideTone: Tone = side === "yes" ? "yes" : side === "no" ? "no" : "muted";
  const amt =
    t.amount_cents != null && Number.isFinite(Number(t.amount_cents))
      ? fmt$(Number(t.amount_cents) / 100)
      : "";
  const lim =
    t.limit_yes_dollars != null && Number.isFinite(Number(t.limit_yes_dollars))
      ? `@${Number(t.limit_yes_dollars).toFixed(2)}`
      : "";
  const pnlC = t.pnl_cents != null && Number.isFinite(Number(t.pnl_cents)) ? Number(t.pnl_cents) / 100 : null;
  const out: TickerSeg[] = [];
  if (st && st !== "settled") out.push(seg(st, "muted"), seg(" ", "muted"));
  out.push(seg(side.toUpperCase() || "—", sideTone), seg(" ", "muted"), seg(tick, "muted"));
  if (amt) {
    out.push(seg(" ", "muted"), seg(amt, "muted"));
  }
  if (lim) out.push(seg(" ", "muted"), seg(lim, "muted"));
  if (st === "settled" && pnlC != null) {
    const pt: Tone = pnlC > 0 ? "pos" : pnlC < 0 ? "neg" : "muted";
    out.push(seg(" PnL ", "muted"), seg(fmt$(pnlC), pt));
  }
  return out;
}

function headlineSegments(branch: BranchKey, cfg: AnyObj, metrics: AnyObj, kalshiPrivateOk: boolean): TickerSeg[] {
  if (branch === "live" && !cfg.simulate) {
    const bal = metrics.exchange_balance_dollars;
    const pv = metrics.exchange_portfolio_value_dollars;
    const balS = bal != null && Number.isFinite(Number(bal)) ? fmt$(Number(bal)) : "—";
    const pvS = pv != null && Number.isFinite(Number(pv)) ? fmt$(Number(pv)) : "—";
    const out: TickerSeg[] = [seg("Live · ", "muted")];
    if (kalshiPrivateOk) {
      out.push(seg("pv ", "muted"), seg(pvS, "pos"), seg(" cash ", "muted"), seg(balS, "pos"));
    } else out.push(seg("keys off", "warn"));
    out.push(
      seg(" · ", "muted"),
      seg(`settled ${metrics.settled_trades ?? 0}`, "muted"),
      seg(" · ", "muted"),
      seg(`sim assets ${metrics.open_sim_trades ?? 0}`, "muted"),
    );
    return out;
  }
  const dollars = metrics.current_mtm_dollars ?? metrics.current_equity_dollars;
  const eqS = dollars != null && Number.isFinite(Number(dollars)) ? fmt$(Number(dollars)) : "—";
  const pnl = Number(metrics.total_pnl_dollars || 0);
  const ret = metrics.return_mtm_vs_start_pct ?? metrics.return_vs_start_pct;
  const retN = ret != null && Number.isFinite(Number(ret)) ? Number(ret) : NaN;
  const lab = branch === "lab_a" ? "Lab A" : branch === "lab_b" ? "Lab B" : branch === "lab_c" ? "Lab C" : branch === "lab_d" ? "Lab D" : "Live";
  const rt: Tone = !Number.isFinite(retN) ? "muted" : retN > 0 ? "pos" : retN < 0 ? "neg" : "muted";
  return [
    seg(`${lab} · `, "muted"),
    seg(eqS, "pos"),
    seg(" · settled PnL ", "muted"),
    seg(fmt$(pnl), pnl > 0 ? "pos" : pnl < 0 ? "neg" : "muted"),
    seg(" · ", "muted"),
    seg(!Number.isFinite(retN) ? "—" : `${retN >= 0 ? "+" : ""}${retN.toFixed(1)}%`, rt),
    seg(" · sim assets ", "muted"),
    seg(String(metrics.open_sim_trades ?? 0), "muted"),
  ];
}

function buildBranchSegments(args: {
  branch: BranchKey;
  cfg: AnyObj;
  metrics: AnyObj;
  snaps: Record<string, AnyObj>;
  engineBlock: AnyObj | undefined;
  recentTrades: AnyObj[];
  positionByAsset: AnyObj | undefined;
  kalshiPrivateOk: boolean;
  labThoughts: AnyObj | undefined;
}): TickerSeg[] {
  const { branch, cfg, metrics, snaps, engineBlock, recentTrades, positionByAsset, kalshiPrivateOk, labThoughts } = args;
  const parts: TickerSeg[][] = [];

  parts.push(headlineSegments(branch, cfg, metrics, kalshiPrivateOk));

  const tickAt = engineBlock?.last_tick_at ? String(engineBlock.last_tick_at) : "";
  if (tickAt) {
    parts.push([dot(), seg(`${tickAt.replace("T", " ").slice(5, 19)}`, "muted")]);
  }

  const err = engineBlock?.last_error ? String(engineBlock.last_error) : "";
  if (err && !isCredentialOrEnvMarqueeNoise(err)) {
    parts.push([dot(), seg(err.slice(0, 100), "warn")]);
  }

  const mon = monitoringSegments(orderedAssets(cfg.assets), snaps);
  if (mon.length) {
    parts.push([dot(), ...mon]);
  } else {
    parts.push([dot(), ...labPulseFallbackSegments(branch, labThoughts)]);
  }

  const pos = positionSegmentsForBranch(positionByAsset, branch, kalshiPrivateOk);
  if (pos.length) parts.push([dot(), ...pos]);

  const trades = recentTrades.filter((t) => normBranch(t.branch) === branch).slice(0, 5);
  for (const t of trades) {
    parts.push([dot(), ...tradeSegments(t)]);
  }

  const flat: TickerSeg[] = [];
  for (const p of parts) {
    if (!p.length) continue;
    for (const s of p) flat.push(s);
  }
  return flat.length ? flat : [seg("Waiting for activity…", "muted")];
}

/** Hero strip: BTC/ETH YES% + book health only (no tickers, rules, or timestamps). */
function compactBtcEthSegments(cfg: AnyObj, snaps: Record<string, AnyObj>): TickerSeg[] {
  const pri = ["btc", "eth"] as const;
  const assets = orderedAssets(cfg.assets);
  const out: TickerSeg[] = [];
  for (const id of pri) {
    const entry = assets.find(([k]) => k === id);
    if (!entry) continue;
    const [, acfg] = entry;
    if (!acfg?.enabled) continue;
    const s = snaps[id];
    if (!s || !snapIsUseful(s)) continue;
    const lab = String(acfg.label || id).toUpperCase();
    const y =
      s.implied_prob != null && Number.isFinite(Number(s.implied_prob)) ? Math.round(Number(s.implied_prob) * 100) : null;
    const bid = s.yes_bid != null ? Number(s.yes_bid) : NaN;
    const ask = s.yes_ask != null ? Number(s.yes_ask) : NaN;
    const okBook = Number.isFinite(bid) && Number.isFinite(ask) && ask > 0 && bid > 0;
    if (out.length) out.push(dot());
    out.push(seg(`${lab} `, "warn"));
    if (y != null) {
      const lean: Tone = y >= 50 ? "yes" : "no";
      const arr = y >= 50 ? "▲" : "▼";
      out.push(seg(`${arr} `, lean), seg(`${y}%`, lean));
    } else {
      out.push(seg("—", "muted"));
    }
    out.push(seg(okBook ? " liq+" : " liq-", okBook ? "pos" : "warn"));
  }
  return out;
}

/** MTM vs start (or fallback) as explicit ▲/▼ + signed % — always readable at a glance in the hero strip. */
function mtmArrowSegments(r: number): TickerSeg[] {
  if (!Number.isFinite(r)) {
    return [seg("—", "muted"), seg(" MTM?", "warn")];
  }
  const t: Tone = r > 0 ? "pos" : r < 0 ? "neg" : "muted";
  const arrow = r > 0 ? "▲" : r < 0 ? "▼" : "—";
  const sign = r > 0 ? "+" : r < 0 ? "" : "";
  const dir = r > 0 ? "UP " : r < 0 ? "DOWN " : "flat ";
  return [seg(`${arrow} `, t), seg(dir, t), seg(`${sign}${r.toFixed(1)}%`, t)];
}

function compactPositionVerdict(
  branch: BranchKey,
  metrics: AnyObj,
  positionByAsset: AnyObj | undefined,
  kalshiPrivateOk: boolean,
): TickerSeg[] {
  const posSecs = positionSegmentsForBranch(positionByAsset, branch, kalshiPrivateOk);
  const hasBook = posSecs.length > 0;
  const openN = Number(metrics.open_sim_trades ?? 0);
  const rawMtm = metrics?.return_mtm_vs_start_pct;
  const r =
    rawMtm != null && Number.isFinite(Number(rawMtm)) ? Number(rawMtm) : Number(metrics?.return_vs_start_pct);
  const retOk = Number.isFinite(r);
  const exposed = hasBook || openN > 0;

  if (!exposed) {
    if (retOk) {
      return [seg("P/L ", "muted"), seg("bench ", "muted"), ...mtmArrowSegments(r)];
    }
    return [seg("P/L ", "muted"), seg("bench — no MTM", "muted")];
  }
  if (!retOk) {
    const bits = [openN ? `${openN} sim` : null, hasBook ? "live" : null].filter(Boolean) as string[];
    const head = bits.length ? `${bits.join(" · ")} · ` : "";
    return [seg("P/L ", "muted"), seg(head, "muted"), seg("open · ", "warn"), seg("— MTM?", "warn")];
  }
  const meta: string[] = [];
  if (openN > 0) meta.push(`${openN} sim`);
  if (hasBook) meta.push("live");
  const pre = meta.length ? `${meta.join(" · ")} · ` : "";
  return [seg("P/L ", "muted"), seg(pre, "muted"), seg("open ", "muted"), ...mtmArrowSegments(r)];
}

function buildHeroCompactSegments(args: {
  branch: BranchKey;
  cfg: AnyObj;
  metrics: AnyObj;
  snaps: Record<string, AnyObj>;
  engineBlock: AnyObj | undefined;
  positionByAsset: AnyObj | undefined;
  kalshiPrivateOk: boolean;
}): TickerSeg[] {
  const { branch, cfg, metrics, snaps, engineBlock, positionByAsset, kalshiPrivateOk } = args;
  const flat: TickerSeg[] = [];
  const mon = compactBtcEthSegments(cfg, snaps);
  if (mon.length) {
    flat.push(...mon);
  } else {
    flat.push(seg("BTC/ETH —", "muted"));
  }
  flat.push(dot(), ...compactPositionVerdict(branch, metrics, positionByAsset, kalshiPrivateOk));
  const err = engineBlock?.last_error ? String(engineBlock.last_error) : "";
  if (err && !isCredentialOrEnvMarqueeNoise(err)) {
    flat.push(dot(), seg(err.slice(0, 52), "warn"));
  }
  return flat.length ? flat : [seg("…", "muted")];
}

function TickerSegRun({ segments }: { segments: TickerSeg[] }) {
  return (
    <>
      {segments.map((s, i) => (
        <span key={i} className={s.tone ? `ticker-seg ticker-seg--${s.tone}` : "ticker-seg"}>
          {s.text}
        </span>
      ))}
    </>
  );
}

const HERO_BRANCH_ORDER: BranchKey[] = ["live", "lab_a", "lab_b", "lab_c", "lab_d"];

const HERO_BRANCH_TAG: Record<BranchKey, string> = {
  live: "Live",
  lab_a: "Lab A",
  lab_b: "Lab B",
  lab_c: "Lab C",
  lab_d: "Lab D",
};

const HERO_BRANCH_ACCENT: Record<BranchKey, string> = {
  live: "#6ee7ff",
  lab_a: "#c4b5fd",
  lab_b: "#fdba74",
  lab_c: "#f9a8d4",
  lab_d: "#fca5a5",
};

function combineHeroMarqueeSegments(bundles: Record<BranchKey, TickerSeg[]>): TickerSeg[] {
  const diamond = seg("  ◆  ", "muted");
  const out: TickerSeg[] = [];
  for (const b of HERO_BRANCH_ORDER) {
    if (out.length) out.push(diamond);
    out.push(seg(`${HERO_BRANCH_TAG[b]} · `, "warn"));
    const body = bundles[b].length ? bundles[b] : [seg("—", "muted")];
    out.push(...body);
  }
  return out.length ? out : [seg("—", "muted")];
}

function heroMarqueeDurationSec(segments: TickerSeg[]): number {
  const len = segments.reduce((n, s) => n + s.text.length, 0);
  /** Seconds for one full loop at 1x — short so direction arrows and branch copy stay glanceable while scrolling. */
  return Math.min(36, Math.max(6, Math.round(len / 8.2)));
}

/** Autoplay pixels/sec vs baseline; 0.7 ≈ 30% slower horizontal marquee (drag/throw unchanged). */
const HERO_MARQUEE_SCROLL_PACE = 0.7;

/** Fixed slide height for vertical rotor (fits Live $ + % + optional cash line). */
const HERO_SLIDE_PX = 78;

/** Single scrolling strip for all branches + rotating balance column (hero, between title and Kalshi orbs). */
export function BranchHeroMarquee({ dash, cfg }: { dash: AnyObj; cfg: AnyObj }): ReactNode {
  const kalshiPrivateOk = Boolean((dash?.kalshi as AnyObj | undefined)?.private_ok);
  const acct = dash?.account_snapshot as AnyObj | undefined;
  const posBy = acct?.position_by_asset as AnyObj | undefined;
  const assetSnaps = (dash?.asset_snapshots || {}) as AnyObj;
  const snapsLive = (assetSnaps.live || {}) as Record<string, AnyObj>;
  const snapsA = ((assetSnaps.lab_a || assetSnaps.sim_lab) || {}) as Record<string, AnyObj>;
  const snapsB = (assetSnaps.lab_b || {}) as Record<string, AnyObj>;
  const snapsC = (assetSnaps.lab_c || {}) as Record<string, AnyObj>;
  const snapsD = (assetSnaps.lab_d || {}) as Record<string, AnyObj>;
  const eng = dash?.engine || {};
  const mLive = (dash?.metrics || {}) as AnyObj;
  const mA = ((dash?.metrics_lab_a || dash?.metrics_sim_lab) || {}) as AnyObj;
  const mB = (dash?.metrics_lab_b || {}) as AnyObj;
  const mC = (dash?.metrics_lab_c || {}) as AnyObj;
  const mD = (dash?.metrics_lab_d || {}) as AnyObj;

  const segBundles = useMemo(() => {
    const live = buildHeroCompactSegments({
      branch: "live",
      cfg,
      metrics: mLive,
      snaps: snapsLive,
      engineBlock: eng.live,
      positionByAsset: posBy,
      kalshiPrivateOk,
    });
    const a = buildHeroCompactSegments({
      branch: "lab_a",
      cfg,
      metrics: mA,
      snaps: snapsA,
      engineBlock: eng.lab_a ?? eng.sim_lab,
      positionByAsset: posBy,
      kalshiPrivateOk,
    });
    const b = buildHeroCompactSegments({
      branch: "lab_b",
      cfg,
      metrics: mB,
      snaps: snapsB,
      engineBlock: eng.lab_b,
      positionByAsset: posBy,
      kalshiPrivateOk,
    });
    const c = buildHeroCompactSegments({
      branch: "lab_c",
      cfg,
      metrics: mC,
      snaps: snapsC,
      engineBlock: eng.lab_c,
      positionByAsset: posBy,
      kalshiPrivateOk,
    });
    const d = buildHeroCompactSegments({
      branch: "lab_d",
      cfg,
      metrics: mD,
      snaps: snapsD,
      engineBlock: eng.lab_d,
      positionByAsset: posBy,
      kalshiPrivateOk,
    });
    return { live, lab_a: a, lab_b: b, lab_c: c, lab_d: d };
  }, [cfg, mLive, mA, mB, mC, mD, snapsLive, snapsA, snapsB, snapsC, snapsD, eng, posBy, kalshiPrivateOk]);

  const combined = useMemo(() => combineHeroMarqueeSegments(segBundles), [segBundles]);
  const speedMult = Number(cfg?.hero_marquee_speed_mult);
  const speedScale = Number.isFinite(speedMult) && speedMult > 0 ? Math.min(4, Math.max(0.35, speedMult)) : 1;
  const dur = useMemo(() => heroMarqueeDurationSec(combined) / speedScale, [combined, speedScale]);

  const rotateSecRaw = Number(cfg?.hero_marquee_rotate_sec);
  const rotateMs = Math.round(
    1000 * (Number.isFinite(rotateSecRaw) && rotateSecRaw > 0 ? Math.min(6, Math.max(0.8, rotateSecRaw)) : 1.8),
  );

  const rb = dash?.remote_balance as AnyObj | undefined;
  const keys = Boolean((dash?.kalshi as AnyObj | undefined)?.private_ok);
  const livePaper = Boolean(cfg.simulate);
  const portfolioLive = livePaper
    ? fmtNum$(mLive.current_mtm_dollars ?? mLive.current_equity_dollars)
    : fmtNum$(mLive.exchange_portfolio_value_dollars ?? (rb?.portfolio_value != null ? Number(rb.portfolio_value) / 100 : null));
  const cashLive =
    livePaper || !keys
      ? null
      : fmtNum$(mLive.exchange_balance_dollars ?? (rb?.balance != null ? Number(rb.balance) / 100 : null));
  const labAeq = fmtNum$(mA.current_mtm_dollars ?? mA.current_equity_dollars);
  const labBeq = fmtNum$(mB.current_mtm_dollars ?? mB.current_equity_dollars);
  const labCeq = fmtNum$(mC.current_mtm_dollars ?? mC.current_equity_dollars);
  const labDeq = fmtNum$(mD.current_mtm_dollars ?? mD.current_equity_dollars);
  const tipLive = livePaper
    ? "Live paper: headline $ is mark-to-market total (last equity snapshot); % uses MTM vs bankroll when available."
    : "Exchange portfolio value (and cash when available) from last dashboard refresh.";

  const slides = [
    {
      key: "live" as const,
      label: "Live",
      accent: HERO_BRANCH_ACCENT.live,
      value: portfolioLive,
      metrics: mLive,
      title: tipLive,
    },
    {
      key: "lab_a" as const,
      label: "Lab A",
      accent: HERO_BRANCH_ACCENT.lab_a,
      value: labAeq,
      metrics: mA,
      title: "Lab A: $ = MTM or cost-basis equity; % = MTM vs bankroll when present.",
    },
    {
      key: "lab_b" as const,
      label: "Lab B",
      accent: HERO_BRANCH_ACCENT.lab_b,
      value: labBeq,
      metrics: mB,
      title: "Lab B: $ = MTM or cost-basis equity; % = MTM vs bankroll when present.",
    },
    {
      key: "lab_c" as const,
      label: "Lab C",
      accent: HERO_BRANCH_ACCENT.lab_c,
      value: labCeq,
      metrics: mC,
      title: "Lab C: $ = MTM or cost-basis equity; % = MTM vs bankroll when present.",
    },
    {
      key: "lab_d" as const,
      label: "Lab D",
      accent: HERO_BRANCH_ACCENT.lab_d,
      value: labDeq,
      metrics: mD,
      title: "Lab D: $ = MTM or cost-basis equity; % = MTM vs bankroll when present.",
    },
  ];

  const slideCount = slides.length;
  const [rotateIx, setRotateIx] = useState(0);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const firstHalfRef = useRef<HTMLSpanElement | null>(null);
  const markerRefs = useRef<Record<BranchKey, HTMLSpanElement | null>>({
    live: null,
    lab_a: null,
    lab_b: null,
    lab_c: null,
    lab_d: null,
  });
  const offsetRef = useRef(0);
  const velocityRef = useRef(0);
  const dragRef = useRef<{ active: boolean; startX: number; startOffset: number; lastX: number; lastT: number }>({
    active: false,
    startX: 0,
    startOffset: 0,
    lastX: 0,
    lastT: 0,
  });
  const rafRef = useRef<number>(0);
  const [trackX, setTrackX] = useState(0);
  const [manualDrag, setManualDrag] = useState(false);
  const [halfWidth, setHalfWidth] = useState(0);

  const normalizeOffset = useCallback((x: number, w: number): number => {
    if (w <= 0) return 0;
    let v = x % w;
    if (v > 0) v -= w;
    return v;
  }, []);

  const jumpToBranch = useCallback(
    (branch: BranchKey) => {
      const vp = viewportRef.current;
      const marker = markerRefs.current[branch];
      const half = firstHalfRef.current;
      if (!vp || !marker || !half) return;
      const w = half.scrollWidth || halfWidth;
      const next = normalizeOffset(-marker.offsetLeft, w || 1);
      offsetRef.current = next;
      velocityRef.current = 0;
      setTrackX(next);
    },
    [halfWidth, normalizeOffset],
  );

  const advanceRotor = useCallback(() => {
    setRotateIx((i) => {
      const next = (i + 1) % slideCount;
      const key = slides[next]?.key;
      if (key) jumpToBranch(key);
      return next;
    });
  }, [jumpToBranch, slideCount, slides]);

  useEffect(() => {
    const id = window.setInterval(() => setRotateIx((i) => (i + 1) % slideCount), rotateMs);
    return () => window.clearInterval(id);
  }, [slideCount, rotateMs]);

  const active = slides[rotateIx] ?? slides[0];

  useLayoutEffect(() => {
    const vp = viewportRef.current;
    const half = firstHalfRef.current;
    if (!vp || !half) return;
    const measure = () => {
      const w = Math.max(1, half.scrollWidth);
      setHalfWidth(w);
      offsetRef.current = normalizeOffset(offsetRef.current, w);
      setTrackX(offsetRef.current);
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(vp);
    ro.observe(half);
    return () => ro.disconnect();
  }, [combined, normalizeOffset]);

  useEffect(() => {
    let last = performance.now();
    const tick = (now: number) => {
      const dt = Math.min(0.04, (now - last) / 1000);
      last = now;
      const w = halfWidth;
      if (w > 1) {
        let next = offsetRef.current;
        if (!manualDrag) {
          if (Math.abs(velocityRef.current) > 4) {
            next += velocityRef.current * dt;
            velocityRef.current *= Math.pow(0.92, dt * 60);
          } else {
            const pxPerSec = (w / Math.max(3.8, dur)) * 2.25 * HERO_MARQUEE_SCROLL_PACE;
            next -= pxPerSec * dt;
            velocityRef.current = 0;
          }
        }
        next = normalizeOffset(next, w);
        if (next !== offsetRef.current) {
          offsetRef.current = next;
          setTrackX(next);
        }
      }
      rafRef.current = window.requestAnimationFrame(tick);
    };
    rafRef.current = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(rafRef.current);
  }, [dur, halfWidth, manualDrag, normalizeOffset]);

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    const el = e.currentTarget;
    el.setPointerCapture(e.pointerId);
    setManualDrag(true);
    dragRef.current = {
      active: true,
      startX: e.clientX,
      startOffset: offsetRef.current,
      lastX: e.clientX,
      lastT: performance.now(),
    };
    velocityRef.current = 0;
  };

  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragRef.current.active) return;
    const now = performance.now();
    const dx = e.clientX - dragRef.current.startX;
    const next = dragRef.current.startOffset + dx;
    offsetRef.current = normalizeOffset(next, Math.max(1, halfWidth));
    setTrackX(offsetRef.current);
    const dtMs = Math.max(8, now - dragRef.current.lastT);
    velocityRef.current = ((e.clientX - dragRef.current.lastX) / dtMs) * 1000;
    dragRef.current.lastX = e.clientX;
    dragRef.current.lastT = now;
  };

  const onPointerEnd = () => {
    dragRef.current.active = false;
    setManualDrag(false);
  };

  const renderHalf = (copy: "a" | "b") => (
    <span ref={copy === "a" ? firstHalfRef : undefined} className="branch-hero-marquee__chunk branch-ticker-chunk--rich">
      {HERO_BRANCH_ORDER.map((b, i) => (
        <span key={`${copy}-${b}`} className="branch-hero-marquee__branch">
          <span ref={copy === "a" ? (el) => (markerRefs.current[b] = el) : undefined} className="branch-hero-marquee__marker" />
          {i > 0 ? <span className="ticker-seg ticker-seg--muted">  ◆  </span> : null}
          <span className="ticker-seg ticker-seg--warn">{`${HERO_BRANCH_TAG[b]} · `}</span>
          <TickerSegRun segments={segBundles[b]} />
        </span>
      ))}
      <span className="ticker-seg ticker-seg--muted">  ◆  </span>
    </span>
  );

  return (
    <div
      className="branch-hero-marquee section-tip"
      title="All-branch market readout. Drag to throw; click right tile to rotate branches and snap marquee."
      aria-label="Combined Live and lab market ticker with rotating portfolio snapshot"
    >
      <div className="branch-hero-marquee__scroll" role="presentation">
        <div
          ref={viewportRef}
          className={`branch-hero-marquee__marquee${manualDrag ? " branch-hero-marquee__marquee--dragging" : ""}`}
          aria-hidden="true"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerEnd}
          onPointerCancel={onPointerEnd}
        >
          <div className="branch-ticker-track-inner branch-hero-marquee__track-inner" style={{ transform: `translateX(${trackX}px)` }}>
            {renderHalf("a")}
            {renderHalf("b")}
          </div>
        </div>
      </div>
      <aside
        className="branch-hero-marquee__rotor section-tip branch-hero-marquee__rotor--interactive"
        title={`${active.title} — click anywhere ($, %, or cash) or press Space/Enter for next branch (Live → Lab A → …).`}
        aria-live="polite"
        aria-label={`${active.label} balance and return vs start. Button: cycle to next branch.`}
        role="button"
        tabIndex={0}
        onClick={advanceRotor}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            advanceRotor();
          }
        }}
      >
        <div
          className="branch-hero-marquee__rotor-track"
          style={{
            transform: `translateY(-${rotateIx * HERO_SLIDE_PX}px)`,
          }}
        >
          {slides.map((s) => (
            <div
              key={s.key}
              className="branch-hero-marquee__slide"
              style={{ minHeight: HERO_SLIDE_PX, borderColor: `${s.accent}55` }}
              onClick={(e) => {
                e.stopPropagation();
                advanceRotor();
              }}
              role="presentation"
            >
              <div className="branch-hero-marquee__slide-label" style={{ color: s.accent }}>
                {s.label}
              </div>
              <div className="branch-hero-marquee__slide-row">
                <span className="branch-hero-marquee__slide-val" style={{ color: s.accent }}>
                  {s.value}
                </span>
                <ReturnBadge metrics={s.metrics} />
              </div>
              {s.key === "live" && !livePaper && cashLive ? (
                <div className="branch-hero-marquee__cash" title="Cash balance from Kalshi.">
                  <span className="branch-hero-marquee__cash-k">Cash</span>
                  <span>{cashLive}</span>
                </div>
              ) : null}
            </div>
          ))}
        </div>
      </aside>
    </div>
  );
}
