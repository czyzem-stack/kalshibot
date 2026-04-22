import { useMemo, type ReactNode } from "react";

type AnyObj = Record<string, any>;

type BranchKey = "live" | "lab_a" | "lab_b";

type Tone = "pos" | "neg" | "yes" | "no" | "muted" | "warn";

type TickerSeg = { text: string; tone?: Tone };

function seg(text: string, tone?: Tone): TickerSeg {
  return { text, tone };
}

function dot(): TickerSeg {
  return { text: "   ·   ", tone: "muted" };
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
  const x = Number(metrics?.return_vs_start_pct);
  if (!Number.isFinite(x)) return null;
  const arrow = x > 0 ? "▲" : x < 0 ? "▼" : "—";
  const sign = x > 0 ? "+" : "";
  const tone: Tone = x > 0 ? "pos" : x < 0 ? "neg" : "muted";
  return (
    <span className={`branch-ticker-portfolio-ret ticker-seg--${tone}`}>
      {arrow} {sign}
      {x.toFixed(1)}%
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
  let any = false;
  for (const [assetId, acfg] of assets) {
    if (!acfg?.enabled) continue;
    const label = String(acfg.label || assetId).toUpperCase();
    const s = snaps[assetId];
    if (!s || !snapIsUseful(s)) continue;
    any = true;
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
    out.push(seg(`${label} `, "muted"), seg(tick || "—", "muted"), seg(" YES ", "muted"));
    if (y != null) {
      const lean: Tone = y >= 50 ? "yes" : "no";
      out.push(seg(`${y}%`, lean));
    } else out.push(seg("—%", "muted"));
    out.push(seg(` bid ${bid} ask ${ask} `, "muted"), seg(mins, "muted"));
    if (rules.length) {
      out.push(seg(" rules ", "muted"), seg(rules.join(", "), "muted"));
    }
  }
  if (!any) return [seg("Markets: scanning…", "muted")];
  return out;
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
  const out: TickerSeg[] = [seg(`${assetLabel} `, "muted"), seg(`${tag} open `, "muted")];
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
    } else if (Array.isArray(r.bot_sim_open_lab_b) && r.bot_sim_open_lab_b.length) {
      blocks.push(simOpenSegments(r.bot_sim_open_lab_b, lab, "Lab B"));
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
  const out: TickerSeg[] = [
    seg(st, "muted"),
    seg(" ", "muted"),
    seg(side.toUpperCase() || "—", sideTone),
    seg(" ", "muted"),
    seg(tick, "muted"),
  ];
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
    const out: TickerSeg[] = [seg("Live ", "muted"), seg("real · ", "muted")];
    if (kalshiPrivateOk) {
      out.push(seg("pv ", "muted"), seg(pvS, "pos"), seg(" cash ", "muted"), seg(balS, "pos"));
    } else out.push(seg("keys off", "warn"));
    out.push(
      seg(" · ", "muted"),
      seg(`settled ${metrics.settled_trades ?? 0}`, "muted"),
      seg(" · ", "muted"),
      seg(`open ${metrics.open_sim_trades ?? 0}`, "muted"),
    );
    return out;
  }
  const eq = metrics.current_equity_dollars;
  const eqS = eq != null && Number.isFinite(Number(eq)) ? fmt$(Number(eq)) : "—";
  const pnl = Number(metrics.total_pnl_dollars || 0);
  const ret = metrics.return_vs_start_pct;
  const retN = ret != null && Number.isFinite(Number(ret)) ? Number(ret) : NaN;
  const lab = branch === "lab_a" ? "Lab A" : branch === "lab_b" ? "Lab B" : "Live";
  const rt: Tone = !Number.isFinite(retN) ? "muted" : retN > 0 ? "pos" : retN < 0 ? "neg" : "muted";
  return [
    seg(`${lab} paper `, "muted"),
    seg(eqS, "pos"),
    seg(" · PnL ", "muted"),
    seg(fmt$(pnl), pnl > 0 ? "pos" : pnl < 0 ? "neg" : "muted"),
    seg(" · ", "muted"),
    seg(!Number.isFinite(retN) ? "—" : `${retN >= 0 ? "+" : ""}${retN.toFixed(1)}%`, rt),
    seg(" · open ", "muted"),
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
}): TickerSeg[] {
  const { branch, cfg, metrics, snaps, engineBlock, recentTrades, positionByAsset, kalshiPrivateOk } = args;
  const parts: TickerSeg[][] = [];

  parts.push(headlineSegments(branch, cfg, metrics, kalshiPrivateOk));

  const tickAt = engineBlock?.last_tick_at ? String(engineBlock.last_tick_at) : "";
  if (tickAt) {
    parts.push([dot(), seg(`tick ${tickAt.replace("T", " ").slice(5, 19)}`, "muted")]);
  }

  const err = engineBlock?.last_error ? String(engineBlock.last_error) : "";
  if (err && !isNoiseBlob(err)) {
    parts.push([dot(), seg(err.slice(0, 100), "warn")]);
  }

  const mon = monitoringSegments(orderedAssets(cfg.assets), snaps);
  if (mon.length) parts.push([dot(), ...mon]);

  const pos = positionSegmentsForBranch(positionByAsset, branch, kalshiPrivateOk);
  if (pos.length) parts.push([dot(), ...pos]);

  const trades = recentTrades.filter((t) => normBranch(t.branch) === branch).slice(0, 5);
  for (const t of trades) {
    parts.push([dot(), seg("Trade ", "muted"), ...tradeSegments(t)]);
  }

  const flat: TickerSeg[] = [];
  for (const p of parts) {
    if (!p.length) continue;
    for (const s of p) flat.push(s);
  }
  return flat.length ? flat : [seg("Waiting for activity…", "muted")];
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

function TickerRow({
  label,
  accent,
  segments,
  durationSec,
}: {
  label: string;
  accent: string;
  segments: TickerSeg[];
  durationSec: number;
}) {
  const textLen = segments.reduce((n, s) => n + s.text.length, 0);
  const body = textLen ? segments : [{ text: "—", tone: "muted" as const }];
  const sep: TickerSeg[] = [seg("          ◆          ", "muted")];
  return (
    <div className="branch-ticker-row" style={{ borderLeftColor: accent }}>
      <div className="branch-ticker-label" style={{ color: accent }}>
        {label}
      </div>
      <div className="branch-ticker-marquee" role="presentation" aria-hidden="true">
        <div className="branch-ticker-track-inner" style={{ animationDuration: `${durationSec}s` }}>
          <span className="branch-ticker-chunk branch-ticker-chunk--rich">
            <TickerSegRun segments={[...body, ...sep]} />
          </span>
          <span className="branch-ticker-chunk branch-ticker-chunk--rich">
            <TickerSegRun segments={[...body, ...sep]} />
          </span>
        </div>
      </div>
    </div>
  );
}

function PortfolioSnapshotPanel({ dash, cfg }: { dash: AnyObj; cfg: AnyObj }) {
  const mLive = (dash?.metrics || {}) as AnyObj;
  const mA = ((dash?.metrics_lab_a || dash?.metrics_sim_lab) || {}) as AnyObj;
  const mB = (dash?.metrics_lab_b || {}) as AnyObj;
  const rb = dash?.remote_balance as AnyObj | undefined;
  const keys = Boolean((dash?.kalshi as AnyObj | undefined)?.private_ok);
  const livePaper = Boolean(cfg.simulate);

  const portfolioLive = livePaper
    ? fmtNum$(mLive.current_equity_dollars)
    : fmtNum$(mLive.exchange_portfolio_value_dollars ?? (rb?.portfolio_value != null ? Number(rb.portfolio_value) / 100 : null));
  const cashLive =
    livePaper || !keys
      ? null
      : fmtNum$(mLive.exchange_balance_dollars ?? (rb?.balance != null ? Number(rb.balance) / 100 : null));

  const labAeq = fmtNum$(mA.current_equity_dollars);
  const labBeq = fmtNum$(mB.current_equity_dollars);

  const tipLive = livePaper
    ? "Live paper equity (est.) from dashboard metrics."
    : "Exchange portfolio value (and cash when available) from last dashboard refresh.";

  return (
    <aside
      className="branch-ticker-portfolio section-tip"
      title={`Snapshot: ${tipLive} Lab A/B paper equity.`}
      aria-label="Portfolio snapshot"
    >
      <div className="branch-ticker-portfolio-title">Snapshot</div>
      <div className="branch-ticker-portfolio-row" title={tipLive}>
        <span className="branch-ticker-portfolio-k">{livePaper ? "Live" : "Portfolio"}</span>
        <span className="branch-ticker-portfolio-v" style={{ color: "#6ee7ff" }}>
          {portfolioLive}
        </span>
        <ReturnBadge metrics={mLive} />
      </div>
      {!livePaper && cashLive ? (
        <div className="branch-ticker-portfolio-row" title="Cash balance from Kalshi.">
          <span className="branch-ticker-portfolio-k">Cash</span>
          <span className="branch-ticker-portfolio-v">{cashLive}</span>
        </div>
      ) : null}
      <div className="branch-ticker-portfolio-divider" />
      <div className="branch-ticker-portfolio-row" title="Lab A paper equity (est.).">
        <span className="branch-ticker-portfolio-k">Lab A</span>
        <span className="branch-ticker-portfolio-v" style={{ color: "#c4b5fd" }}>
          {labAeq}
        </span>
        <ReturnBadge metrics={mA} />
      </div>
      <div className="branch-ticker-portfolio-row" title="Lab B paper equity (est.).">
        <span className="branch-ticker-portfolio-k">Lab B</span>
        <span className="branch-ticker-portfolio-v" style={{ color: "#fdba74" }}>
          {labBeq}
        </span>
        <ReturnBadge metrics={mB} />
      </div>
    </aside>
  );
}

export function BranchMarketTickers({ dash, cfg }: { dash: AnyObj; cfg: AnyObj }): ReactNode {
  const kalshiPrivateOk = Boolean((dash?.kalshi as AnyObj | undefined)?.private_ok);
  const acct = dash?.account_snapshot as AnyObj | undefined;
  const posBy = acct?.position_by_asset as AnyObj | undefined;
  const recentTrades = (Array.isArray(dash?.recent_trades) ? dash.recent_trades : []) as AnyObj[];
  const assetSnaps = (dash?.asset_snapshots || {}) as AnyObj;
  const snapsLive = (assetSnaps.live || {}) as Record<string, AnyObj>;
  const snapsA = ((assetSnaps.lab_a || assetSnaps.sim_lab) || {}) as Record<string, AnyObj>;
  const snapsB = (assetSnaps.lab_b || {}) as Record<string, AnyObj>;
  const eng = dash?.engine || {};
  const mLive = (dash?.metrics || {}) as AnyObj;
  const mA = ((dash?.metrics_lab_a || dash?.metrics_sim_lab) || {}) as AnyObj;
  const mB = (dash?.metrics_lab_b || {}) as AnyObj;

  const segBundles = useMemo(() => {
    const live = buildBranchSegments({
      branch: "live",
      cfg,
      metrics: mLive,
      snaps: snapsLive,
      engineBlock: eng.live,
      recentTrades,
      positionByAsset: posBy,
      kalshiPrivateOk,
    });
    const a = buildBranchSegments({
      branch: "lab_a",
      cfg,
      metrics: mA,
      snaps: snapsA,
      engineBlock: eng.lab_a ?? eng.sim_lab,
      recentTrades,
      positionByAsset: posBy,
      kalshiPrivateOk,
    });
    const b = buildBranchSegments({
      branch: "lab_b",
      cfg,
      metrics: mB,
      snaps: snapsB,
      engineBlock: eng.lab_b,
      recentTrades,
      positionByAsset: posBy,
      kalshiPrivateOk,
    });
    return { live, lab_a: a, lab_b: b };
  }, [cfg, mLive, mA, mB, snapsLive, snapsA, snapsB, eng, recentTrades, posBy, kalshiPrivateOk]);

  const dur = (segs: TickerSeg[]) => {
    const len = segs.reduce((n, s) => n + s.text.length, 0);
    return Math.min(120, Math.max(28, Math.round(len / 3.5)));
  };

  return (
    <div className="branch-ticker-outer">
      <div
        className="branch-ticker-stack section-tip"
        title="Scrolling readouts: markets with real quotes, open positions, recent trades. Green/red = direction or PnL."
        aria-label="Live, Lab A, and Lab B tickers"
      >
        <TickerRow label="LIVE" accent="#6ee7ff" segments={segBundles.live} durationSec={dur(segBundles.live)} />
        <TickerRow label="LAB A" accent="#c4b5fd" segments={segBundles.lab_a} durationSec={dur(segBundles.lab_a)} />
        <TickerRow label="LAB B" accent="#fdba74" segments={segBundles.lab_b} durationSec={dur(segBundles.lab_b)} />
      </div>
      <PortfolioSnapshotPanel dash={dash} cfg={cfg} />
    </div>
  );
}
