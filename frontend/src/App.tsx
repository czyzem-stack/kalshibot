import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import SettingsOverlay from "./SettingsOverlay";
import HistoricalExplorerOverlay from "./HistoricalExplorerOverlay";
import { BranchHeroMarquee, BranchHeroSnapshotHeader } from "./BranchMarketTickers";
import { KalshiSetupOrbRow } from "./KalshiSetupOrbRow";

type AnyObj = Record<string, any>;

/** Stable empty lab when config has no lab object yet — avoids `new {}` every render breaking PUT payloads. */
const EMPTY_LAB: AnyObj = Object.freeze({});

function branchLabelForTradeToast(branch: unknown): string {
  const s = String(branch || "live").trim().toLowerCase();
  if (s === "lab_a" || s === "sim_lab") return "Lab A";
  if (s === "lab_b") return "Lab B";
  if (s === "lab_c") return "Lab C";
  if (s === "lab_d") return "Lab D";
  return "Live";
}

async function apiGet<T>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path} ${r.status}`);
  return (await r.json()) as T;
}

async function apiPut(path: string, body: AnyObj) {
  const r = await fetch(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    let detail = "";
    try {
      const j = (await r.json()) as AnyObj;
      detail = typeof j?.detail === "string" ? j.detail : JSON.stringify(j?.detail ?? j);
    } catch {
      /* ignore */
    }
    throw new Error(detail ? `${path} ${r.status}: ${detail}` : `${path} ${r.status}`);
  }
  return await r.json();
}

async function apiPutLabBranches(body: AnyObj): Promise<AnyObj> {
  const path = "/api/config/lab-branches";
  const r = await fetch(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    let detail = "";
    try {
      const j = (await r.json()) as AnyObj;
      detail = typeof j?.detail === "string" ? j.detail : JSON.stringify(j?.detail ?? j);
    } catch {
      /* ignore */
    }
    throw new Error(detail ? `${path} ${r.status}: ${detail}` : `${path} ${r.status}`);
  }
  return (await r.json()) as AnyObj;
}

async function apiPost(path: string) {
  const r = await fetch(path, { method: "POST" });
  if (!r.ok) throw new Error(`${path} ${r.status}`);
  return await r.json();
}

async function apiPostJson(path: string, body: AnyObj = {}): Promise<AnyObj> {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    let detail = "";
    try {
      const j = (await r.json()) as AnyObj;
      detail = typeof j?.detail === "string" ? j.detail : JSON.stringify(j?.detail ?? j);
    } catch {
      /* ignore */
    }
    throw new Error(detail ? `${path} ${r.status}: ${detail}` : `${path} ${r.status}`);
  }
  return (await r.json()) as AnyObj;
}

function labThoughtsToSentence(lines: unknown): string {
  if (!Array.isArray(lines) || lines.length === 0) return "Watching paper metrics and recent settles.";
  const parts = (lines as string[]).map((s) => String(s).trim()).filter(Boolean);
  return parts.join(" · ").replace(/\s+/g, " ").trim();
}

function formatActiveTradeMarqueeLine(t: AnyObj): string {
  const tick = String(t.ticker || "").slice(0, 44) || "—";
  const side = String(t.side || "").toUpperCase() || "—";
  const st = String(t.status || "").trim() || "—";
  const sim = Boolean(Number(t.simulated));
  const tag = sim ? "sim" : "real";
  const cost = Number(t.amount_cents || 0) / 100;
  const costStr = Number.isFinite(cost) && cost > 0 ? ` ~${fmtMoney(cost)}` : "";
  return `${tick} ${side} · ${st}${costStr} (${tag})`;
}

/** Branch performance footer: scrolling list of non-settled trades for the selected branch tab. */
function BranchPerfActiveTradesMarquee({ branchLabel, activeRows }: { branchLabel: string; activeRows: AnyObj[] }) {
  const segments = useMemo(
    () =>
      activeRows.map((t, i) => ({
        key: tradeToastRowKey(t) || `row-${i}`,
        text: formatActiveTradeMarqueeLine(t),
      })),
    [activeRows],
  );

  const viewportRef = useRef<HTMLDivElement>(null);
  const firstHalfRef = useRef<HTMLDivElement>(null);
  const [needsScroll, setNeedsScroll] = useState(false);

  const fullTitle = segments.length
    ? `${branchLabel} active: ` + segments.map((s) => s.text).join(" · ")
    : `${branchLabel}: no active trades in the current feed.`;

  useLayoutEffect(() => {
    const vp = viewportRef.current;
    const half = firstHalfRef.current;
    if (!vp || !half) return;
    const measure = () => {
      setNeedsScroll(segments.length > 0 && half.scrollWidth > vp.clientWidth + 2);
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(vp);
    ro.observe(half);
    return () => ro.disconnect();
  }, [segments]);

  const charCount = segments.reduce((n, s) => n + s.text.length, 0);
  const durSec = Math.max(18, Math.min(120, Math.round(charCount * 0.07)));

  const renderHalf = (suffix: string) => (
    <>
      {segments.map((s, i) => (
        <span key={`${s.key}-${suffix}`} className="branch-perf-active-marquee__item">
          <span className="branch-perf-active-marquee__trade">{s.text}</span>
          {i < segments.length - 1 ? <span className="branch-perf-active-marquee__sep"> · </span> : null}
        </span>
      ))}
    </>
  );

  if (!segments.length) {
    return (
      <div
        className="branch-performance-bottom__ticker branch-perf-active-marquee branch-perf-active-marquee--empty"
        title={fullTitle}
      >
        <span className="branch-perf-active-marquee__label">{branchLabel}</span>
        <span className="branch-perf-active-marquee__muted"> — no active trades in feed</span>
      </div>
    );
  }

  return (
    <div
      className="branch-performance-bottom__ticker branch-perf-active-marquee section-tip"
      role="region"
      aria-label={`${branchLabel} active trades`}
      title={fullTitle}
    >
      <span className="branch-perf-active-marquee__label">{branchLabel}</span>
      <div ref={viewportRef} className="branch-perf-active-marquee__viewport">
        <div
          className={`branch-perf-active-marquee__track${needsScroll ? " branch-perf-active-marquee__track--scroll" : " branch-perf-active-marquee__track--static"}`}
          style={needsScroll ? { animationDuration: `${durSec}s` } : undefined}
        >
          <div ref={firstHalfRef} className="branch-perf-active-marquee__half">
            {renderHalf("a")}
          </div>
          {needsScroll ? (
            <div className="branch-perf-active-marquee__half" aria-hidden>
              {renderHalf("b")}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

/** Optimizer footer: all labs in one horizontal strip (marquee when wide, scroll on reduced motion). */
function LabPulseWideTicker({ thoughts }: { thoughts: AnyObj | undefined }) {
  const segments = useMemo(() => {
    const t = thoughts && typeof thoughts === "object" ? (thoughts as AnyObj) : {};
    return [
      { lab: "Lab A", key: "lab_a", accent: "#c4b5fd" },
      { lab: "Lab B", key: "lab_b", accent: "#fdba74" },
      { lab: "Lab C", key: "lab_c", accent: "#f9a8d4" },
      { lab: "Lab D", key: "lab_d", accent: "#fca5a5" },
    ].map(({ lab, key, accent }) => ({
      lab,
      key,
      accent,
      text: labThoughtsToSentence(t[key]),
    }));
  }, [thoughts]);

  const viewportRef = useRef<HTMLDivElement>(null);
  const firstHalfRef = useRef<HTMLDivElement>(null);
  const [needsScroll, setNeedsScroll] = useState(false);

  const fullTitle = segments.map((s) => `${s.lab}: ${s.text}`).join(" · ");

  useLayoutEffect(() => {
    const vp = viewportRef.current;
    const half = firstHalfRef.current;
    if (!vp || !half) return;
    const measure = () => {
      setNeedsScroll(half.scrollWidth > vp.clientWidth + 2);
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(vp);
    ro.observe(half);
    return () => ro.disconnect();
  }, [segments]);

  const charCount = segments.reduce((n, s) => n + s.lab.length + s.text.length, 0);
  const durSec = Math.max(22, Math.min(140, Math.round(charCount * 0.055)));

  const renderChunks = (suffix: string) => (
    <>
      {segments.map((s, i) => (
        <span key={`${s.key}-${suffix}`} className="lab-pulse-ticker__chunk">
          <span className="lab-pulse-ticker__lab" style={{ color: s.accent }}>
            {s.lab}
          </span>
          <span className="lab-pulse-ticker__dash"> — </span>
          <span className="lab-pulse-ticker__text">{s.text}</span>
          {i < segments.length - 1 ? <span className="lab-pulse-ticker__sep"> · </span> : null}
        </span>
      ))}
    </>
  );

  return (
    <div
      className="lab-pulse-ticker section-tip"
      role="region"
      aria-label="Lab pulse — all labs from the latest poll"
      title={fullTitle}
    >
      <div className="lab-pulse-ticker__head">Lab pulse</div>
      <div ref={viewportRef} className="lab-pulse-ticker__viewport">
        <div
          className={`lab-pulse-ticker__track${needsScroll ? " lab-pulse-ticker__track--scroll" : " lab-pulse-ticker__track--static"}`}
          style={needsScroll ? { animationDuration: `${durSec}s` } : undefined}
        >
          <div ref={firstHalfRef} className="lab-pulse-ticker__half">
            {renderChunks("a")}
          </div>
          {needsScroll ? <div className="lab-pulse-ticker__half" aria-hidden>{renderChunks("b")}</div> : null}
        </div>
      </div>
    </div>
  );
}

/** Aligns with backend ``_optimizer_change_stable_id`` intent: same row must keep one id across polls (no legacy-* index drift). */
function stableOptimizerChangeId(h: AnyObj): string {
  const raw = String(h?.id || "").trim();
  if (raw && !raw.startsWith("legacy-")) return raw;
  const parts = [
    String(h?.created_at || ""),
    String(h?.branch || h?.lab_label || ""),
    String(h?.style || ""),
    String(h?.summary || "").slice(0, 160),
    String(h?.reason || "").slice(0, 160),
  ].join("|");
  let a = 5381;
  for (let i = 0; i < parts.length; i++) a = (Math.imul(a, 33) + parts.charCodeAt(i)) | 0;
  let b = 2166136261;
  for (let i = 0; i < parts.length; i++) {
    b ^= parts.charCodeAt(i);
    b = Math.imul(b, 16777619) | 0;
  }
  const tag = `${(a >>> 0).toString(16).padStart(8, "0")}${(b >>> 0).toString(16).padStart(8, "0")}`.slice(0, 20);
  return `ch-${tag}`;
}

function fmtMoney(n: number) {
  const sign = n < 0 ? "-" : "";
  const v = Math.abs(n);
  return `${sign}$${v.toFixed(2)}`;
}

const HERO_MARQUEE_SPEED_KEY = "kalshibot_hero_marquee_speed_mult_v1";

function readHeroMarqueeSpeedMult(): number {
  try {
    const raw = window.localStorage.getItem(HERO_MARQUEE_SPEED_KEY);
    if (!raw) return 2;
    const n = Number(raw);
    if (!Number.isFinite(n)) return 2;
    return Math.min(4, Math.max(0.35, n));
  } catch {
    return 2;
  }
}

function persistHeroMarqueeSpeedMult(mult: number) {
  try {
    window.localStorage.setItem(HERO_MARQUEE_SPEED_KEY, String(Math.min(4, Math.max(0.35, mult))));
  } catch {
    // ignore
  }
}

const TRADE_POPUP_TOASTS_KEY = "kalshibot_trade_popup_toasts_v1";

function readTradePopupToastsEnabled(): boolean {
  try {
    const v = window.localStorage.getItem(TRADE_POPUP_TOASTS_KEY);
    if (v === null || v === "") return true;
    return v !== "0" && v !== "false";
  } catch {
    return true;
  }
}

function persistTradePopupToastsEnabled(on: boolean) {
  try {
    window.localStorage.setItem(TRADE_POPUP_TOASTS_KEY, on ? "1" : "0");
  } catch {
    // ignore
  }
}

const DISMISSED_TRADE_TOAST_IDS_CAP = 360;

/** Remember toast ids the user dismissed so dashboard/poll effect merges cannot resurrect them. */
function rememberDismissedTradeToastIds(set: Set<string>, ids: Iterable<string>) {
  for (const raw of ids) {
    const id = String(raw || "").trim();
    if (id) set.add(id);
  }
  while (set.size > DISMISSED_TRADE_TOAST_IDS_CAP) {
    const first = set.values().next().value as string | undefined;
    if (first == null) break;
    set.delete(first);
  }
}

function fmtPct(n: unknown, digits = 2): string {
  if (n == null || n === "") return "—";
  const x = Number(n);
  if (!Number.isFinite(x)) return "—";
  const sign = x > 0 ? "+" : "";
  return `${sign}${x.toFixed(digits)}%`;
}

const BRAIN_MTM_LINES: { dataKey: string; name: string; stroke: string; strokeWidth: number }[] = [
  { dataKey: "live", name: "Live", stroke: "#22d3ee", strokeWidth: 1.35 },
  { dataKey: "a", name: "Lab A", stroke: "#a855f7", strokeWidth: 1.2 },
  { dataKey: "b", name: "Lab B", stroke: "#f97316", strokeWidth: 1.15 },
  { dataKey: "c", name: "Lab C", stroke: "#ec4899", strokeWidth: 1.1 },
  { dataKey: "d", name: "Lab D", stroke: "#ef4444", strokeWidth: 1.05 },
];

function BranchExperimentPathsTooltip(props: AnyObj) {
  const { active, payload } = props;
  if (!active || !payload?.length) return null;
  const p = payload[0]?.payload as AnyObj | undefined;
  if (!p) return null;
  return (
    <div
      style={{
        background: "#0b1228",
        border: "1px solid #243055",
        borderRadius: 8,
        padding: "6px 10px",
        fontSize: 10,
        maxWidth: 300,
        color: "#e2e8f0",
      }}
    >
      <div style={{ fontWeight: 600, marginBottom: 4, fontSize: 11 }}>{String(p.t)}</div>
      {BRAIN_MTM_LINES.map(({ dataKey, name, stroke }) => {
        const idx = p[dataKey];
        const raw = p[`${dataKey}$`];
        if (idx == null || !Number.isFinite(Number(idx))) return null;
        const rawLine =
          raw != null && Number.isFinite(Number(raw)) ? <span style={{ opacity: 0.88 }}> · {fmtMoney(Number(raw))}</span> : null;
        return (
          <div key={dataKey} style={{ marginTop: 3 }}>
            <span style={{ color: stroke, fontWeight: 600 }}>{name}:</span> {Number(idx).toFixed(2)} index
            {rawLine}
          </div>
        );
      })}
    </div>
  );
}

function BranchExperimentPathsMini({
  data,
  revision,
  chartHeight = 172,
}: {
  data: AnyObj[];
  revision: string;
  chartHeight?: number;
}) {
  if (!data.length) {
    return <p className="sub" style={{ margin: "8px 6px", fontSize: 11 }}>No equity history yet for overlaid paths.</p>;
  }
  return (
    <ResponsiveContainer width="100%" height={chartHeight} key={revision || "brain-lines"}>
      <LineChart data={data} margin={{ left: 2, right: 6, top: 2, bottom: 22 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1a2544" vertical={false} />
        <XAxis dataKey="idx" tick={false} axisLine={{ stroke: "#223056" }} height={8} />
        <YAxis domain={["auto", "auto"]} tick={{ fontSize: 9 }} width={34} tickFormatter={(v) => Number(v).toFixed(0)} />
        <Tooltip content={(tp: AnyObj) => <BranchExperimentPathsTooltip {...tp} />} />
        <Legend wrapperStyle={{ fontSize: 9, paddingTop: 2 }} iconSize={8} iconType="line" verticalAlign="bottom" height={22} />
        {BRAIN_MTM_LINES.map((ln) => (
          <Line
            key={ln.dataKey}
            type="monotone"
            dataKey={ln.dataKey}
            name={ln.name}
            stroke={ln.stroke}
            strokeWidth={ln.strokeWidth}
            dot={false}
            connectNulls
            isAnimationActive={false}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

function nextTickBodyPlain(preview: string): string {
  const t = preview.trim();
  if (!t) return "";
  return t.replace(/^\s*next\s*tick\s*:\s*/i, "").trim() || t;
}

function BranchOptimizerVisualizer({
  labThoughts,
  lineRows,
  lineRevision,
}: {
  labThoughts: AnyObj | undefined;
  lineRows: AnyObj[];
  lineRevision: string;
}) {
  return (
    <div className="branch-brain-optimizer-stack" role="region" aria-label="Optimizer: experiments and lab pulse">
      <div className="branch-brain-experiments-pulse-row">
        <div className="branch-brain-experiments-col">
          <div className="branch-brain-chart-wrap branch-brain-chart-wrap--lines branch-brain-chart-wrap--experiments-tall">
            <div className="branch-brain-chart__title">Experiments — MTM (indexed to window start)</div>
            <BranchExperimentPathsMini data={lineRows} revision={lineRevision} chartHeight={268} />
          </div>
        </div>
        <div className="branch-brain-pulse-col">
          <div className="branch-brain-chart-wrap branch-brain-chart-wrap--pulse-ticker">
            <LabPulseWideTicker thoughts={labThoughts} />
          </div>
        </div>
      </div>
    </div>
  );
}

type MetricValueTone = "pos" | "neg" | "neu";

function metricSignedTone(n: unknown): MetricValueTone {
  const x = Number(n);
  if (!Number.isFinite(x)) return "neu";
  if (x > 0.0005) return "pos";
  if (x < -0.0005) return "neg";
  return "neu";
}

function metricEquityVsBankroll(eq: unknown, bank: unknown): MetricValueTone {
  const e = Number(eq);
  const b = Number(bank);
  if (!Number.isFinite(e) || !Number.isFinite(b) || b <= 0) return "neu";
  return metricSignedTone(e - b);
}

/** Headline $ on MTM tiles: last snapshot MTM when API sends it, else cost-basis equity. */
function dashboardMtmDollars(m: AnyObj): number {
  const v = m.current_mtm_dollars ?? m.current_equity_dollars;
  return Number(v ?? 0);
}

function dashboardMtmReturnPct(m: AnyObj): unknown {
  return m.return_mtm_vs_start_pct ?? m.return_vs_start_pct;
}

function dashboardChartLastMtmOrEq(m: AnyObj): number | null {
  const x = m.latest_mtm_snapshot_dollars ?? m.latest_equity_snapshot_dollars;
  if (x == null || x === "") return null;
  const n = Number(x);
  return Number.isFinite(n) ? n : null;
}

/** PnL not yet in ``total_pnl_dollars`` (settled): MTM vs bankroll with realized taken out = open/marks drag. */
function paperUnrealizedPnlDollars(m: AnyObj): number | null {
  const rawMtm = m.current_mtm_dollars;
  if (rawMtm == null || rawMtm === "" || !Number.isFinite(Number(rawMtm))) return null;
  const mtmN = Number(rawMtm);
  const st = Number(m.paper_start_dollars ?? NaN);
  if (!Number.isFinite(st) || st <= 0) return null;
  const r = Number(m.total_pnl_dollars ?? 0);
  if (!Number.isFinite(r)) return null;
  return mtmN - st - r;
}

function metricWinRateTone(pct: unknown): MetricValueTone {
  const x = Number(pct);
  if (!Number.isFinite(x)) return "neu";
  return metricSignedTone(x - 50);
}

function decisiveWinRatePct(m: AnyObj): unknown {
  const decisive = Number(m.wins ?? 0) + Number(m.losses ?? 0) > 0;
  return decisive ? m.win_rate_decisive_pct : m.win_rate_pct;
}

function decisiveLossRatePct(m: AnyObj): unknown {
  const decisive = Number(m.wins ?? 0) + Number(m.losses ?? 0) > 0;
  return decisive ? m.loss_rate_decisive_pct : m.loss_rate_pct;
}

function metricValClass(t: MetricValueTone | undefined): string {
  if (!t || t === "neu") return "v";
  return `v metric-val--${t}`;
}

function metricSubClass(t: MetricValueTone | undefined): string {
  if (!t || t === "neu") return "metric-sub";
  return `metric-sub metric-sub--${t}`;
}

function MetricTile({
  label,
  value,
  title,
  sub,
  valueTone,
  subTone,
}: {
  label: string;
  value: ReactNode;
  title: string;
  sub?: ReactNode;
  valueTone?: MetricValueTone;
  subTone?: MetricValueTone;
}) {
  return (
    <div className="metric" title={title}>
      <div className="k" title={title}>
        {label}
      </div>
      <div className={metricValClass(valueTone)} title={title}>
        {value}
      </div>
      {sub != null && sub !== "" ? (
        <div className={metricSubClass(subTone)} title={title}>
          {sub}
        </div>
      ) : null}
    </div>
  );
}

const WIN_LOSS_RECORD_TITLE =
  "Wins and losses use settled PnL sign; flat = exactly $0 (not counted as win or loss). " +
  "Win % and loss % share the same denominator: wins ÷ (wins + losses) and losses ÷ (wins + losses) when there is at least one decisive outcome; otherwise wins ÷ settled and losses ÷ settled. Same SQL scope as Total PnL.";

/** Replaces separate Win/loss, Win rate, and Loss rate tiles. */
function WinLossRecordTile({ label, metrics }: { label: string; metrics: AnyObj }) {
  const wr = decisiveWinRatePct(metrics);
  const lr = decisiveLossRatePct(metrics);
  const scratches = Number(metrics.scratch_trades) > 0 ? ` · ${String(metrics.scratch_trades)} flat` : "";
  const sub = (
    <>
      <span className={metricSubClass(metricWinRateTone(wr))}>Win {fmtPct(wr)}</span>
      <span style={{ color: "var(--muted)" }}> · </span>
      <span className={metricSubClass(metricSignedTone(50 - Number(lr)))}>Loss {fmtPct(lr)}</span>
    </>
  );
  return (
    <MetricTile
      label={label}
      value={`${String(metrics.wins ?? 0)} / ${String(metrics.losses ?? 0)}${scratches}`}
      title={WIN_LOSS_RECORD_TITLE}
      sub={sub}
    />
  );
}

/** Dashboard shows `kalshi.env` from the backend — demo/stage hosts are not production order books. */
function kalshiIsNonProd(env: unknown): boolean {
  const e = String(env ?? "").trim().toLowerCase();
  return Boolean(e) && !["prod", "production", "live"].includes(e);
}

/** Backend ISO strings are UTC; show in the viewer's local timezone. */
function fmtIsoLocal(iso: string | undefined | null, withSeconds = true) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso).replace("T", " ").slice(0, 19);
  return d.toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    ...(withSeconds ? { second: "2-digit" } : {}),
    hour12: true,
  });
}

function formatBranchRollupLine(label: string, m: AnyObj): string {
  const settled = Number(m.settled_trades ?? 0) || 0;
  const w = Number(m.wins ?? 0) || 0;
  const l = Number(m.losses ?? 0) || 0;
  const sc = Number(m.scratch_trades ?? 0) || 0;
  const open = Number(m.open_sim_trades ?? 0) || 0;
  const pnl = Number(m.total_pnl_dollars ?? 0);
  const wls = `${w}W/${l}L${sc ? `/${sc} flat` : ""}`;
  const pnlPart = settled ? ` · Σ ${pnl >= 0 ? "+" : ""}$${pnl.toFixed(2)}` : "";
  const openPart = open ? ` · ${open} open` : "";
  return `${label}: ${settled} settled (${wls})${pnlPart}${openPart}`;
}

/** Short note: how this branch’s fills relate to the internal pulse / Claude optimizer (paper lab lookback). */
function tradeBranchOptimizerLens(branchRaw: unknown): string {
  const s = String(branchRaw || "live").trim().toLowerCase();
  if (s === "lab_a" || s === "sim_lab") {
    return "  ↳ Lab A settled row: feeds adaptive YES-floor / min-left (loss streak at floor + replay gate), optional win-relax, and bet pulse (last ~40 settled mean).";
  }
  if (s === "lab_b") {
    return "  ↳ Lab B: reference arm — counts toward min settled / wins gates and bet-pulse context; thresholds are not auto-written here.";
  }
  if (s === "lab_c") {
    return "  ↳ Lab C: same as B (aggressive reference).";
  }
  if (s === "lab_d") {
    return "  ↳ Lab D: reference + “wild” can widen/narrow bet pulse step from B/C short-run momentum.";
  }
  return "  ↳ Live: shown for your book; optimizer pulses use paper lab trades in their lookback, not Live branch rows.";
}

function recentSettledResolutionLinesWithLens(rows: AnyObj[], max = 10): string {
  const settled = rows.filter((t) => String(t.status || "").toLowerCase() === "settled");
  settled.sort((a, b) => Number(b.id) - Number(a.id));
  const slice = settled.slice(0, max);
  if (!slice.length) return "";
  return slice
    .map((t) => {
      const br = branchLabelForTradeToast(t.branch);
      const tick = String(t.ticker || "").slice(0, 40);
      const side = String(t.side || "").toUpperCase() || "—";
      const rawP = t.pnl_cents;
      let pnlPart = "";
      if (rawP != null && rawP !== "") {
        const n = Number(rawP);
        if (Number.isFinite(n)) {
          const d = n / 100;
          pnlPart = ` · ${d >= 0 ? "+" : ""}$${d.toFixed(2)}`;
        }
      }
      const res = t.result ? ` · ${String(t.result)}` : "";
      const head = `${br} · ${tick} ${side}${pnlPart}${res}`;
      return `${head}\n${tradeBranchOptimizerLens(t.branch)}`;
    })
    .join("\n\n");
}

function optimizerTradesContextExplainer(dash: AnyObj): string {
  const cfg = (dash?.config || {}) as AnyObj;
  const oc = (cfg?.optimizer || {}) as AnyObj;
  const minTr = Number(oc.min_trades_for_optimize ?? 8) || 8;
  const minProf = Number(oc.min_profitable_trades ?? 2) || 2;
  const trig = Number(oc.loss_streak_trigger ?? 3) || 3;
  const floor = Number(oc.lab_a_yes_floor_pct ?? 57) || 57;
  const adapt = oc.adaptive_enabled !== false;
  const sched = Boolean(oc.enabled);
  const betOpt = oc.optimize_bet_size !== false;
  return [
    "What the optimizer does with trades (paper labs in its lookback):",
    `• Gates: needs enough settled paper trades (≥${minTr} total with PnL, ≥${minProf} winners across the check) before nudging Lab A.`,
    `• Adaptive (Lab A): stacks losing settles whose entry matched the YES implied floor (~${floor}%). At ${trig} such losses it may tighten YES floor / min minutes left if a rule replay shows better PnL; can ease after a clean win path.`,
    `• Bet pulse (Lab A): last ~40 Lab A settled mean PnL moves balance_fraction_per_window; B/C/D help pass the same gates; Lab D “wild” can change step size from B/C tails.`,
    `• Claude scheduler ${sched ? "on" : "off"} · adaptive ${adapt ? "on" : "off"} · optimize bet ${betOpt ? "on" : "off"} — model sees all labs; persisted auto-tuning targets Lab A only.`,
  ].join("\n");
}

function recentOptimizerActionsText(dash: AnyObj, maxItems = 3): string {
  const oa = (dash?.optimizer_activity || {}) as AnyObj;
  const cfg = (dash?.config || {}) as AnyObj;
  const oc = (cfg?.optimizer || {}) as AnyObj;
  const lists = [
    ...(Array.isArray(oa.change_history) ? (oa.change_history as AnyObj[]) : []),
    ...(Array.isArray(oc.change_history) ? (oc.change_history as AnyObj[]) : []),
  ];
  lists.sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")));
  const seen = new Set<string>();
  const items: AnyObj[] = [];
  for (const h of lists) {
    if (!h || typeof h !== "object") continue;
    const id = stableOptimizerChangeId(h as AnyObj);
    if (seen.has(id)) continue;
    seen.add(id);
    items.push(h as AnyObj);
    if (items.length >= maxItems) break;
  }
  if (!items.length) {
    return "Recent persisted changes: none in change_history yet (scheduler/adaptive may still be evaluating).";
  }
  return (
    "Recent persisted changes:\n" +
    items
      .map((h, i) => {
        const lab = String(h.lab_label || h.branch || "lab");
        const style = String(h.style || "—");
        const sum = String(h.summary || "").slice(0, 200);
        const hint = String(h.tick_hint || "").trim().slice(0, 140);
        const at = h.created_at ? fmtIsoLocal(String(h.created_at)) : "—";
        return `${i + 1}. ${at} · ${lab} · ${style}\n   ${sum}${hint ? `\n   Watch: ${hint}${hint.length >= 140 ? "…" : ""}` : ""}`;
      })
      .join("\n\n")
  );
}

function pulseTraceLines(dash: AnyObj): string {
  const oa = (dash?.optimizer_activity || {}) as AnyObj;
  const pt = Array.isArray(oa.pulse_trace) ? (oa.pulse_trace as AnyObj[]) : [];
  if (!pt.length) return "Pulse trace: (empty — no internal pulse messages stored yet.)";
  return (
    "Pulse trace (newest first in payload):\n" +
    pt
      .slice(0, 4)
      .map((p) => `• ${String(p.kind || "pulse")}: ${String(p.message || "").slice(0, 130)}${String(p.message || "").length > 130 ? "…" : ""}`)
      .join("\n")
  );
}

/** Manual toast from Optimizer radar: rollups, optimizer lens on trades, activity + previews. */
function buildTradesByLabSnapshotToast(dash: AnyObj): {
  title: string;
  tone: "green" | "yellow" | "red";
  segments: { tier: "green" | "yellow" | "red" | "neutral"; text: string }[];
  body: string;
} {
  const metricsLive = (dash?.metrics || {}) as AnyObj;
  const ma = (dash?.metrics_lab_a || dash?.metrics_sim_lab || {}) as AnyObj;
  const mb = (dash?.metrics_lab_b || {}) as AnyObj;
  const mc = (dash?.metrics_lab_c || {}) as AnyObj;
  const md = (dash?.metrics_lab_d || {}) as AnyObj;
  const roll = [
    formatBranchRollupLine("Live", metricsLive),
    formatBranchRollupLine("Lab A", ma),
    formatBranchRollupLine("Lab B", mb),
    formatBranchRollupLine("Lab C", mc),
    formatBranchRollupLine("Lab D", md),
  ].join("\n");
  const recent = (dash?.recent_trades || []) as AnyObj[];
  const settledBlock = recentSettledResolutionLinesWithLens(recent, 10);
  const oa = (dash?.optimizer_activity || {}) as AnyObj;
  const preview = String(oa.next_tick_preview || "").trim();
  const previewSeg =
    preview.length > 0
      ? ({ tier: "yellow" as const, text: `Next tick preview:\n${preview.slice(0, 520)}${preview.length > 520 ? "…" : ""}` })
      : ({ tier: "neutral" as const, text: "Next tick preview: (not set yet — run the optimizer / adaptive pulse once.)" });

  const segments: { tier: "green" | "yellow" | "red" | "neutral"; text: string }[] = [
    { tier: "neutral", text: `Trades / labs · ${fmtIsoLocal(new Date().toISOString(), true)}` },
    { tier: "neutral", text: roll },
    { tier: "neutral", text: optimizerTradesContextExplainer(dash) },
    previewSeg,
    { tier: "neutral", text: recentOptimizerActionsText(dash, 1) },
    { tier: "neutral", text: pulseTraceLines(dash) },
    {
      tier: "neutral",
      text: settledBlock
        ? `Recent settlements (with per-row optimizer meaning, up to 10):\n\n${settledBlock}`
        : "Recent settlements: none in the current recent_trades feed.",
    },
  ];
  const body = segments.map((s) => s.text).join("\n\n");
  return { title: "Trades by lab", tone: "yellow", segments, body };
}

function optimizerGateProgress(dash: AnyObj) {
  const cfg = (dash?.config || {}) as AnyObj;
  const oc = (cfg?.optimizer || {}) as AnyObj;
  const minTr = Math.max(2, Number(oc.min_trades_for_optimize) || 8);
  const minProf = Math.max(0, Number(oc.min_profitable_trades) || 2);
  const ma = (dash?.metrics_lab_a || dash?.metrics_sim_lab || {}) as AnyObj;
  const settled = Math.max(0, Math.floor(Number(ma.settled_trades ?? 0)));
  const wins = Math.max(0, Math.floor(Number(ma.wins ?? 0)));
  const needSettled = Math.max(0, minTr - settled);
  const needWins = Math.max(0, minProf - wins);
  const schedulerOn = Boolean(oc.enabled);
  const intervalM = Math.max(5, Math.min(24 * 60, Number(oc.interval_minutes) || 20));
  return { settled, minTr, wins, minProf, needSettled, needWins, schedulerOn, intervalM };
}

function optimizerNextMovementHero(dash: AnyObj): { title: string; sub: string } {
  const g = optimizerGateProgress(dash);
  if (g.needSettled > 0 || g.needWins > 0) {
    const parts: string[] = [];
    if (g.needSettled > 0) {
      parts.push(`~${g.needSettled} more Lab A settle${g.needSettled === 1 ? "" : "s"}`);
    }
    if (g.needWins > 0) {
      parts.push(`~${g.needWins} more decisive win${g.needWins === 1 ? "" : "s"}`);
    }
    const title = `Next movement: ${parts.join(" · ")}`;
    const sub = `Lab A is at ${g.settled} / ${g.minTr} settled (with PnL) and ${g.wins} / ${g.minProf} decisive wins — then bet pulse / adaptive / scheduler can nudge knobs.`;
    return { title, sub };
  }
  const oa = (dash?.optimizer_activity || {}) as AnyObj;
  const preview = String(oa.next_tick_preview || "").trim();
  const plain = nextTickBodyPlain(preview);
  if (plain) {
    return {
      title: "Gates met — engine is watching the next tick",
      sub: plain.length > 220 ? `${plain.slice(0, 220)}…` : plain,
    };
  }
  return {
    title: "Gates met — waiting for next optimizer pulse",
    sub: g.schedulerOn
      ? `Scheduled loop on · about every ${g.intervalM} min. Open paper trades so pulses have fresh context.`
      : "Scheduled optimizer is off — turn it on in Settings → Optimizer for automatic cadence.",
  };
}

/** Single overlay: movement hero + condensed rollups, schedule, pulse, settlements, UI hints. */
function optimizerReportOverlayBody(dash: AnyObj): ReactNode {
  const snap = buildTradesByLabSnapshotToast(dash);
  const segs = snap.segments;
  const roll = String(segs[1]?.text || "");
  const tuning = String(segs[2]?.text || "");
  const nextTickBlock = String(segs[3]?.text || "");
  const recentCh = String(segs[4]?.text || "");
  const pulseBlock = String(segs[5]?.text || "");
  const settledBlock = String(segs[6]?.text || "");
  const movement = optimizerNextMovementHero(dash);
  const g = optimizerGateProgress(dash);
  const oa = (dash?.optimizer_activity || {}) as AnyObj;
  const lastEval = String(oa.last_pulse_eval_at || "");

  return (
    <div className="optimizer-report">
      <div className="optimizer-report-hero">
        <div className="optimizer-report-hero__title">{movement.title}</div>
        <p className="optimizer-report-hero__sub">{movement.sub}</p>
      </div>

      <div className="optimizer-report-section">
        <h3 className="optimizer-report-section__h">{"Schedule & last pulse"}</h3>
        <p className="optimizer-report-line">
          {g.schedulerOn ? (
            <>
              Scheduled optimizer <strong>on</strong> · about every {g.intervalM} min
            </>
          ) : (
            <>
              Scheduled optimizer <strong>off</strong>
            </>
          )}
          {lastEval ? (
            <>
              {" "}
              · last eval {fmtIsoLocal(lastEval)}
            </>
          ) : null}
        </p>
      </div>

      <div className="optimizer-report-section">
        <h3 className="optimizer-report-section__h">Next tick (server)</h3>
        <pre className="optimizer-report-pre optimizer-report-pre--tight">{nextTickBlock}</pre>
      </div>

      <div className="optimizer-report-section">
        <h3 className="optimizer-report-section__h">Branch rollups</h3>
        <pre className="optimizer-report-pre">{roll}</pre>
      </div>

      <div className="optimizer-report-section">
        <h3 className="optimizer-report-section__h">How tuning uses trades</h3>
        <pre className="optimizer-report-pre optimizer-report-pre--muted">{tuning}</pre>
      </div>

      <div className="optimizer-report-section">
        <h3 className="optimizer-report-section__h">Recent persisted change</h3>
        <pre className="optimizer-report-pre">{recentCh}</pre>
      </div>

      <div className="optimizer-report-section">
        <h3 className="optimizer-report-section__h">Pulse trace (log)</h3>
        <pre className="optimizer-report-pre optimizer-report-pre--muted">{pulseBlock}</pre>
      </div>

      <div className="optimizer-report-section">
        <h3 className="optimizer-report-section__h">Recent settlements</h3>
        <pre className="optimizer-report-pre">{settledBlock}</pre>
      </div>

      <div className="optimizer-report-section optimizer-report-section--hint">
        <p className="optimizer-report-line">
          <strong>Experiments</strong> compares Live + Lab A–D MTM from the same window start. <strong>Lab pulse</strong> is the
          scrolling ticker under the chart.
        </p>
      </div>
    </div>
  );
}

function optimizerBriefInfoBody(): ReactNode {
  return (
    <div className="dash-section__legend" style={{ fontSize: 13, lineHeight: 1.55 }}>
      <p>
        <strong>What this panel is for.</strong> The Optimizer block is your at-a-glance view of <em>adaptive paper tuning</em> and
        experiment comparison. The large chart (Experiments) does not place trades by itself; it visualizes how each branch’s
        mark-to-market path evolved from a common reference window. Use it to see whether Lab A (staging) is diverging from B/C/D
        reference arms before you promote anything to Live.
      </p>
      <p>
        <strong>Experiments (mini chart).</strong> Each colored line is indexed MTM (or a blended MTM / cost-basis readout, depending
        on backend rollups) for Live vs Lab A–D, starting from the same time bucket so the curves are comparable. Flatter or smoother
        lines are not “better” by default: high volatility can mean the book is open and marked often. Crossovers mean branches took
        different fills or risk because rules, sizing, or paper bankrolls differ. Zoom mentally with the time-scale tabs in Equity
        curves for longer history; this block is a short window.
      </p>
      <p>
        <strong>Lab pulse (scrolling line below the chart).</strong> This is a dense, tick-by-tick-style digest of the last engine
        poll: implied probabilities, which rules matched, minutes to close, skip reasons, and small KPI snippets the backend
        attached. It scrolls for legibility, not because time is “moving” faster. If pulse shows many{" "}
        <code>series_has_open_sim</code> skips, you still have an open sim blocking new entries in that series—resolve or
        time-out close stale rows (see auto-close behavior on the server) before expecting new paper fills.
      </p>
      <p>
        <strong>Adaptive / scheduled optimizer (backend).</strong> When enabled, the server can adjust thresholds, bet fraction,
        and related knobs using recent <em>settled</em> paper history, with guardrails (minimum trades, no wild jumps during drawdowns,
        etc.). By design, <strong>only Lab A</strong> receives auto-applied fraction/threshold writes unless you explicitly use other
        APIs; B/C/D stay reference paths. The dashboard shows recommendations and pulse traces, but the source of truth is the API
        response and SQLite change log.
      </p>
      <p>
        <strong>“report” (button next to this Info).</strong> Opens the full-page optimizer report overlay: last persisted change
        records, next-movement heuristics, schedule windows, paper settlement rollups, and raw pulse traces pulled from the same
        dashboard object. Use that overlay when you need to copy IDs, verify timestamps, or read the unabbreviated log lines that
        do not fit in the small chart.
      </p>
      <p>
        <strong>What to ignore / misread.</strong> (1) A spike in one branch line while another is flat often means a fill or
        exit happened in that branch only. (2) If Live is in real-cash mode, only Live is tied to the exchange; labs remain paper.
        (3) Empty or stale pulse lines usually mean engines are off, Kalshi 429/timeout, or the tick did not run—check the Engine
        strip under Account, not this panel alone. (4) PnL on the main tiles is rollups; this chart is experimental visualization—
        reconcile against Branch performance and Activity log.
      </p>
      <p>
        <strong>Operational workflow.</strong> (1) Confirm engines and rules in Settings. (2) Watch Experiments for divergence.
        (3) Read Lab pulse for concrete skip reasons. (4) If satisfied with Lab A, use promote-to-Live (separate action, gated) not
        this Info dialog. (5) If numbers look wrong, export SQLite or open “report” before changing rules, so you have a before/
        after snapshot in the overlay.
      </p>
    </div>
  );
}

/** Same instant as 24h UTC clock (for a second line or tooltip). */
function fmtIsoUtcTime(iso: string | undefined | null) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${hh}:${mm} UTC`;
}

/** Market settlement instant — primary label is local; Kalshi ISO often ends with Z/+00:00. */
function fmtMarketSettle(iso: string | undefined | null) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso).slice(0, 19);
  const local = d.toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
  const utc = fmtIsoUtcTime(iso);
  return utc ? `${local} (${utc})` : local;
}

/** One line per raw open row (for tooltips / debugging). */
function summarizePositionRowsRaw(rows: unknown): string {
  const arr = Array.isArray(rows) ? (rows as AnyObj[]) : [];
  if (!arr.length) return "";
  return arr
    .map((r) => {
      const t = String(r.ticker || "").trim();
      const q = r.position != null ? String(r.position) : String(r.contracts_fp ?? "");
      return `${t} (${q} contracts)`;
    })
    .join("\n");
}

function _parsePositionQty(r: AnyObj): number {
  const raw = r.position != null ? r.position : r.contracts_fp;
  if (raw == null || raw === "") return 0;
  const n = typeof raw === "number" ? raw : Number(String(raw).replace(/,/g, ""));
  return Number.isFinite(n) ? n : 0;
}

function _fmtPositionQty(qty: number): string {
  if (!Number.isFinite(qty)) return "0";
  const r = Math.round(qty * 100) / 100;
  if (Math.abs(r - Math.round(r)) < 1e-5) return String(Math.round(r));
  return r.toFixed(2);
}

/**
 * Holdings cell: merge multiple SQLite open rows on the **same** ticker into one **position size** (sum of
 * Kalshi **contracts**, i.e. YES/NO units), plus “N tickets” when N&gt;1. **Market lines** = distinct tickers
 * after merge (how many markets have exposure), not the same as total contracts.
 */
function summarizePositionRows(rows: unknown): { text: string; title: string } {
  const arr = Array.isArray(rows) ? (rows as AnyObj[]) : [];
  if (!arr.length) return { text: "—", title: "" };
  const seenIds = new Set<string>();
  const deduped: AnyObj[] = [];
  for (const r of arr) {
    const idRaw = r.id;
    if (idRaw != null && String(idRaw).trim() !== "") {
      const idk = String(idRaw);
      if (seenIds.has(idk)) continue;
      seenIds.add(idk);
    }
    deduped.push(r);
  }
  const rawTitle = summarizePositionRowsRaw(deduped);
  const byTicker = new Map<string, { qty: number; n: number }>();
  for (const r of deduped) {
    const tKey = String(r.ticker || "").trim().toUpperCase();
    if (!tKey) continue;
    const q = _parsePositionQty(r);
    const merged = Number((r as AnyObj).ticket_count);
    const nInc = Number.isFinite(merged) && merged >= 1 ? merged : 1;
    const cur = byTicker.get(tKey) || { qty: 0, n: 0 };
    cur.qty += q;
    cur.n += nInc;
    byTicker.set(tKey, cur);
  }
  const parts = [...byTicker.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([tKey, { qty, n }]) => {
      const short = tKey.length > 40 ? `${tKey.slice(0, 37)}…` : tKey;
      const ticketNote = n > 1 ? ` · ${n} tickets` : "";
      return `${short} · ${_fmtPositionQty(qty)} contracts${ticketNote}`;
    });
  const detailJoined = parts.join("; ");
  const nMkts = byTicker.size;
  if (nMkts > 1) {
    const totalQty = [...byTicker.values()].reduce((acc, v) => acc + v.qty, 0);
    const summary = `${nMkts} market lines · ${_fmtPositionQty(totalQty)} contracts total (size)`;
    const titleBody = [rawTitle, detailJoined].filter(Boolean).join("\n\n");
    return { text: summary, title: titleBody || detailJoined };
  }
  return { text: detailJoined, title: rawTitle };
}

/** Drop duplicate ticker rows (same contract listed twice); first row wins. */
function dedupeAssetWatchOpenRowsByTicker(rows: AnyObj[]): AnyObj[] {
  const seen = new Set<string>();
  const out: AnyObj[] = [];
  for (const r of rows) {
    const t = String(r.ticker || "").trim().toUpperCase();
    if (!t) {
      out.push(r);
      continue;
    }
    if (seen.has(t)) continue;
    seen.add(t);
    out.push(r);
  }
  return out;
}

/** Open rows for the Assets-to-watch branch tab only (avoids Lab exposure highlighting on Live tab, etc.). */
function assetWatchOpenRowsForTab(row: unknown, tab: "live" | "a" | "b" | "c" | "d"): AnyObj[] {
  if (!row || typeof row !== "object") return [];
  const o = row as AnyObj;
  const out: AnyObj[] = [];
  const seen = new Set<string>();
  const push = (arr: unknown, source: string) => {
    if (!Array.isArray(arr)) return;
    for (const raw of arr) {
      if (!raw || typeof raw !== "object") continue;
      const r = raw as AnyObj;
      const tick = String(r.ticker || "");
      const key = `${source}::${tick}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({ ...r, _source: source });
    }
  };
  if (tab === "live") {
    push(o.kalshi_open, "Kalshi");
    push(o.bot_sim_open_live, "Sim · Live");
  } else if (tab === "a") {
    push(o.bot_sim_open_lab_a, "Sim · Lab A");
  } else if (tab === "b") {
    push(o.bot_sim_open_lab_b, "Sim · Lab B");
  } else if (tab === "c") {
    push(o.bot_sim_open_lab_c, "Sim · Lab C");
  } else {
    push(o.bot_sim_open_lab_d, "Sim · Lab D");
  }
  return out;
}

function positionTabHasOpenExposure(row: unknown, tab: "live" | "a" | "b" | "c" | "d"): boolean {
  return assetWatchOpenRowsForTab(row, tab).length > 0;
}

function exposureLabelsForAssetWatchTab(row: unknown, tab: "live" | "a" | "b" | "c" | "d"): string[] {
  const rows = assetWatchOpenRowsForTab(row, tab);
  const uniq: string[] = [];
  for (const r of rows) {
    const s = String(r._source || "");
    if (s && !uniq.includes(s)) uniq.push(s);
  }
  return uniq;
}

function formatYesDollarPx(v: unknown): string | null {
  if (v == null || v === "") return null;
  const n = Number(v);
  if (!Number.isFinite(n) || n <= 0 || n > 1) return null;
  return n.toFixed(3);
}

function firstKalshiAvgYesPx(row: AnyObj): string | null {
  for (const k of [
    "average_yes_price_dollars",
    "average_price_dollars",
    "yes_average_price_dollars",
    "average_price",
  ]) {
    const s = formatYesDollarPx(row[k]);
    if (s) return s;
  }
  return null;
}

function _shortTickerLabel(t: string, max = 40): string {
  const s = String(t || "").trim();
  if (!s) return "—";
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}

/** One line per open row: entry/limit vs headline contract YES bid when tickers match. */
function OpenExposureLinesForWatch({
  rows,
  headlineSnap,
  seriesTicker,
}: {
  rows: AnyObj[];
  headlineSnap: AnyObj | undefined;
  seriesTicker?: string;
}) {
  if (!rows.length) return null;
  const headOk = Boolean(headlineSnap && headlineSnap.ok !== false);
  const headTicker = headOk ? String(headlineSnap!.ticker || "") : "";
  const st = String(seriesTicker || "").trim();
  return (
    <div
      className="sub"
      style={{ marginTop: 6, fontSize: 11, lineHeight: 1.55 }}
      title={
        "Open positions on the tab you selected. The card above is the engine’s headline market for this asset " +
        "(often the next 15m window); your opens can be other tickers in the same series — we only compare entry " +
        "to the live YES bid when the ticker matches the headline."
      }
    >
      <strong>Open in this tab</strong>
      {rows.length > 1 ? (
        <div
          style={{
            fontSize: 10,
            color: "var(--muted)",
            marginTop: 4,
            marginBottom: 2,
            lineHeight: 1.45,
          }}
          title={
            "The engine allows at most one new open sim per series prefix per branch until it settles. Multiple lines here usually means older windows not settled yet; new overlaps are blocked."
          }
        >
          {rows.length} open under {st || "this series"} — only one new sim per series is allowed; extra lines are
          existing tickets until they settle.
        </div>
      ) : null}
      {rows.map((r, i) => {
        const tick = String(r.ticker || "");
        const side = String(r.side || "yes").toLowerCase() === "no" ? "NO" : "YES";
        const entrySim = formatYesDollarPx(r.entry_yes_dollars);
        const entryKal = firstKalshiAvgYesPx(r);
        const entryStr = entrySim || entryKal;
        const same = Boolean(headTicker && tick && tick === headTicker);
        const bidRaw = same && headOk && headlineSnap ? headlineSnap.yes_bid : null;
        const bidNow = formatYesDollarPx(bidRaw);
        let line: string;
        if (same && entryStr && bidNow) {
          line = `${side} bid @ ${entryStr} → now ${bidNow}`;
        } else if (same && bidNow) {
          line = `${side} bid now ${bidNow}` + (entryStr ? ` (avg/limit ${entryStr})` : "");
        } else if (same && entryStr) {
          line = `${side} @ ${entryStr} (headline contract — no usable YES bid in snapshot)`;
        } else if (entryStr) {
          line = headTicker
            ? `${side} @ ${entryStr} · open ${_shortTickerLabel(tick)} (card above: ${_shortTickerLabel(headTicker)})`
            : `${side} @ ${entryStr} · ${_shortTickerLabel(tick)}`;
        } else {
          line = `${side} ${_shortTickerLabel(tick, 56)} · size ${String(r.contracts_fp ?? r.position ?? "—")}`;
        }
        const rid = r.id != null && String(r.id).trim() !== "" ? String(r.id) : `i${i}`;
        return (
          <div key={`${rid}-${tick.toUpperCase()}`} style={{ marginTop: 4 }}>
            <span style={{ color: "var(--muted)" }}>{String(r._source || "")}:</span> {line}
          </div>
        );
      })}
    </div>
  );
}

/** Normalize SQLite `branch` onto dashboard tabs (legacy sim_lab → Lab A). */
type ActivityBranchKey = "live" | "lab_a" | "lab_b" | "lab_c" | "lab_d";
type PerfBranchKey = "live" | "lab_a" | "lab_b" | "lab_c" | "lab_d";

function normalizeSignalTradeBranch(b: unknown): ActivityBranchKey {
  const s = String(b ?? "live").trim().toLowerCase();
  if (s === "lab_a" || s === "sim_lab") return "lab_a";
  if (s === "lab_b") return "lab_b";
  if (s === "lab_c") return "lab_c";
  if (s === "lab_d") return "lab_d";
  return "live";
}

const BRANCH_SWATCH: Record<ActivityBranchKey, string> = {
  live: "#6ee7ff",
  lab_a: "#c4b5fd",
  lab_b: "#fdba74",
  lab_c: "#f9a8d4",
  lab_d: "#fca5a5",
};

function branchToastSwatch(branchRaw: unknown): string {
  return BRANCH_SWATCH[normalizeSignalTradeBranch(branchRaw)];
}

/** Open / resting sim rows plus common Kalshi in-flight order states (see engine ``insert_trade``). */
function tradeStatusIsActiveBid(st: string): boolean {
  const s = st.trim().toLowerCase();
  return (
    s === "open" ||
    s === "resting" ||
    s === "pending" ||
    s === "active" ||
    s === "executed" ||
    s === "partial" ||
    s === "partially_filled" ||
    s === "submitted" ||
    s === "processing" ||
    s === "queued" ||
    s === "filled" ||
    s === "matched"
  );
}

function tradeToastRowKey(t: AnyObj): string {
  const idStr = String(t?.id ?? "").trim();
  if (idStr) return idStr;
  const orderId = String(t?.order_id ?? "").trim();
  if (orderId) return `oid:${orderId}`;
  const clientOrderId = String(t?.client_order_id ?? "").trim();
  if (clientOrderId) return `cid:${clientOrderId}`;
  const ca = String(t?.created_at ?? "").trim();
  const tk = String(t?.ticker ?? "").trim();
  const side = String(t?.side ?? "").trim();
  const amt = String(t?.amount_cents ?? "").trim();
  const mode = String(t?.mode ?? "").trim();
  return `row:${ca}|${tk}|${side}|${amt}|${mode}`;
}

/** Union dashboard + poll rows by stable key so new trades on ``recent_trades`` are not dropped when /api/trades is non-empty but stale. */
function mergeTradeRowsForToastEffect(dashRows: unknown, pollRows: AnyObj[] | null): AnyObj[] {
  const byKey = new Map<string, AnyObj>();
  const fromDash = Array.isArray(dashRows) ? (dashRows as AnyObj[]) : [];
  const fromPoll = Array.isArray(pollRows) ? pollRows : [];
  for (const t of fromDash) {
    const k = tradeToastRowKey(t);
    if (k) byKey.set(k, t);
  }
  for (const t of fromPoll) {
    const k = tradeToastRowKey(t);
    if (k) byKey.set(k, t);
  }
  return Array.from(byKey.values());
}

function tradeRowLooksResolved(t: AnyObj): boolean {
  const st = String(t?.status || "").trim().toLowerCase();
  if (
    st === "settled" ||
    st === "closed" ||
    st === "finalized" ||
    st === "determined" ||
    st === "complete" ||
    st === "inactive" ||
    st === "resolved"
  ) {
    return true;
  }
  if (t?.pnl_cents != null && String(t.pnl_cents).trim() !== "") return true;
  if (t?.settled_at != null && String(t.settled_at).trim() !== "") return true;
  if (t?.result != null && String(t.result).trim() !== "") return true;
  return false;
}

/** Kalshi market outcome (``yes``/``no``) vs paper sim exit before finalization. */
function tradeResolutionLines(t: AnyObj): { title: string; resolutionTier: "green" | "yellow" | "red" | "neutral"; lines: string[] } {
  const r = String(t?.result ?? "").trim().toLowerCase();
  const side = String(t?.side ?? "yes").trim().toLowerCase();
  if (r === "yes" || r === "no") {
    const won = (side === "yes" && r === "yes") || (side === "no" && r === "no");
    return {
      title: "Purchase resolved",
      resolutionTier: won ? "green" : "red",
      lines: [
        `Contract settled · market ${r.toUpperCase()} · your ${side.toUpperCase()} ${won ? "won" : "lost"}`,
        "Held until Kalshi resolution",
      ],
    };
  }
  if (r === "swing_exit") {
    return {
      title: "Purchase resolved",
      resolutionTier: "yellow",
      lines: ["Sold before contract expiry · swing exit (bid)", "Early close — not final market settlement"],
    };
  }
  if (r === "patient_stop_loss") {
    return {
      title: "Purchase resolved",
      resolutionTier: "yellow",
      lines: ["Sold before contract expiry · patient stop-loss", "Early close — not final market settlement"],
    };
  }
  if (r === "auto_timeout") {
    return {
      title: "Purchase resolved",
      resolutionTier: "yellow",
      lines: ["Sold before contract expiry · auto timeout", "Early close — not final market settlement"],
    };
  }
  if (r) {
    return {
      title: "Purchase resolved",
      resolutionTier: "neutral",
      lines: [
        `Sold before contract expiry · ${r.replace(/_/g, " ")}`,
        "Early close — not final market settlement",
      ],
    };
  }
  return {
    title: "Purchase resolved",
    resolutionTier: "neutral",
    lines: ["Settled", "Outcome details not on this row"],
  };
}

function activityBranchTabLabel(b: ActivityBranchKey): string {
  if (b === "live") return "Live";
  if (b === "lab_a") return "Lab A";
  if (b === "lab_b") return "Lab B";
  if (b === "lab_c") return "Lab C";
  return "Lab D";
}

/** BTC first, ETH second, then remaining asset ids A–Z. */
function orderedAssetEntries(assetsObj: AnyObj | undefined): [string, AnyObj][] {
  const entries = Object.entries(assetsObj || {}) as [string, AnyObj][];
  const rank = (id: string) => (id === "btc" ? 0 : id === "eth" ? 1 : 2);
  return [...entries].sort((a, b) => {
    const d = rank(a[0]) - rank(b[0]);
    if (d !== 0) return d;
    return String(a[0]).localeCompare(String(b[0]));
  });
}

type EquityGranularity = "intraday" | "dd" | "ww" | "mm" | "yy";

type EquityChartRow = { t: string; tsMs: number; equity: number; mtm: number | null; synthetic?: boolean };

function mondayUtcKey(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const y = d.getUTCFullYear();
  const m = d.getUTCMonth();
  const day = d.getUTCDate();
  const dow = d.getUTCDay();
  const mondayOffset = dow === 0 ? -6 : 1 - dow;
  const mon = new Date(Date.UTC(y, m, day + mondayOffset));
  return `${mon.getUTCFullYear()}-${String(mon.getUTCMonth() + 1).padStart(2, "0")}-${String(mon.getUTCDate()).padStart(2, "0")}`;
}

function buildEquityChartSeries(
  snaps: AnyObj[],
  mode: EquityGranularity,
  fmtIsoLocalFn: (iso: string, withSeconds: boolean) => string,
): EquityChartRow[] {
  const rows = snaps
    .map((s) => {
      const raw = s.mtm_equity_cents;
      let mtm: number | null = null;
      if (raw != null && raw !== "") {
        const n = Number(raw);
        if (Number.isFinite(n)) mtm = n / 100.0;
      }
      return {
        at: String(s.created_at || ""),
        eq: Number(s.equity_cents || 0) / 100.0,
        mtm,
        ts: new Date(String(s.created_at || "")).getTime(),
      };
    })
    .filter((r) => r.at && Number.isFinite(r.ts));
  rows.sort((a, b) => a.ts - b.ts);

  if (mode === "intraday") {
    return rows.slice(-400).map((r) => ({
      t: fmtIsoLocalFn(r.at, false),
      tsMs: r.ts,
      equity: r.eq,
      mtm: r.mtm,
    }));
  }

  const bucketKey = (iso: string): string => {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
    const y = d.getUTCFullYear();
    const mo = d.getUTCMonth();
    const day = d.getUTCDate();
    if (mode === "dd") return `${y}-${String(mo + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    if (mode === "mm") return `${y}-${String(mo + 1).padStart(2, "0")}`;
    if (mode === "yy") return `${y}`;
    if (mode === "ww") return mondayUtcKey(iso);
    return iso.slice(0, 10);
  };

  const best = new Map<string, { ts: number; eq: number; mtm: number | null; sampleIso: string }>();
  for (const r of rows) {
    const b = bucketKey(r.at);
    if (!b) continue;
    const cur = best.get(b);
    if (!cur || r.ts >= cur.ts) best.set(b, { ts: r.ts, eq: r.eq, mtm: r.mtm, sampleIso: r.at });
  }

  const keys = [...best.keys()].sort();
  return keys.map((k) => {
    const cell = best.get(k)!;
    let t = k;
    if (mode === "dd") {
      t = fmtIsoLocalFn(cell.sampleIso, false);
      const comma = t.indexOf(",");
      if (comma > 0) t = t.slice(0, comma).trim();
    } else if (mode === "mm") {
      const d = new Date(cell.sampleIso);
      t = d.toLocaleString(undefined, { month: "short", year: "numeric", timeZone: "UTC" });
    } else if (mode === "ww") {
      const parts = k.split("-").map((x) => Number(x));
      if (parts.length === 3 && parts.every((n) => Number.isFinite(n))) {
        const mon = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
        t = `Week of ${mon.toLocaleDateString(undefined, {
          weekday: "short",
          month: "short",
          day: "numeric",
          year: "numeric",
          timeZone: "UTC",
        })}`;
      }
    }
    return { t, tsMs: cell.ts, equity: cell.eq, mtm: cell.mtm };
  });
}

/** Intraday: append one point from latest dashboard metrics so the curve moves on every /api/dashboard poll. */
function equitySeriesWithLiveTail(
  snaps: AnyObj[],
  mode: EquityGranularity,
  metrics: AnyObj,
  fmtIsoLocalFn: (iso: string, withSeconds: boolean) => string,
): EquityChartRow[] {
  const base = buildEquityChartSeries(snaps, mode, fmtIsoLocalFn);
  if (mode !== "intraday") return base;

  const ce = metrics?.current_equity_dollars;
  let equity: number | null = ce != null && Number.isFinite(Number(ce)) ? Number(ce) : null;
  if (equity == null && snaps.length) {
    const n = Number((snaps[snaps.length - 1] as AnyObj).equity_cents || 0);
    equity = Number.isFinite(n) ? n / 100.0 : null;
  }
  if (equity == null || !Number.isFinite(equity)) return base;

  const cm = metrics?.current_mtm_dollars;
  let mtm: number | null = cm != null && Number.isFinite(Number(cm)) ? Number(cm) : null;
  if (mtm == null && snaps.length) {
    const raw = (snaps[snaps.length - 1] as AnyObj).mtm_equity_cents;
    if (raw != null && raw !== "") {
      const n = Number(raw);
      if (Number.isFinite(n)) mtm = n / 100.0;
    }
  }
  if (mtm == null) mtm = equity;

  const tailT = fmtIsoLocalFn(new Date().toISOString(), true);
  if (base.length === 0) {
    // New labs can start with no snapshot history; add an anchor point so a 2-point flat line is visible.
    const anchorIso = new Date(Date.now() - 60_000).toISOString();
    const anchorT = fmtIsoLocalFn(anchorIso, true);
    const anchorMs = new Date(anchorIso).getTime();
    const tailMs = Date.now();
    return [
      { t: anchorT, tsMs: anchorMs, equity, mtm, synthetic: true },
      { t: tailT, tsMs: tailMs, equity, mtm, synthetic: true },
    ];
  }
  const tailMs = Date.now();
  return [...base, { t: tailT, tsMs: tailMs, equity, mtm, synthetic: true }];
}

/** Stable fingerprint so Recharts remounts whenever snapshots, tail time, metrics, or values change. */
function equityChartRevision(snaps: AnyObj[], rows: EquityChartRow[], metrics?: AnyObj): string {
  const tailSnap =
    snaps && snaps.length
      ? `${String((snaps[snaps.length - 1] as AnyObj).id ?? "")}:${String((snaps[snaps.length - 1] as AnyObj).created_at ?? "")}`
      : "";
  const m = metrics
    ? `liveMtm=${String(metrics.current_mtm_dollars ?? "")}:liveEq=${String(metrics.current_equity_dollars ?? "")}`
    : "";
  if (!rows.length) return `0|${tailSnap}|${m}`;
  const L = rows[rows.length - 1];
  return `${tailSnap}|n=${rows.length}|t=${L.t}|ts=${L.tsMs}|eq=${L.equity}|mtm=${L.mtm ?? ""}|syn=${L.synthetic ? 1 : 0}|${m}`;
}

function equityRowMtmOrEq(row: EquityChartRow): number | null {
  const m = row.mtm;
  if (m != null && Number.isFinite(Number(m))) return Number(m);
  const e = row.equity;
  return Number.isFinite(Number(e)) ? Number(e) : null;
}

type OverlayBranchKey = "live" | "a" | "b" | "c" | "d";

/** Chronological union of branch snapshots with forward-filled values so overlay lines share one true time axis. */
function mergeEquityOverlayRows(
  live: EquityChartRow[],
  labA: EquityChartRow[],
  labB: EquityChartRow[],
  labC: EquityChartRow[],
  labD: EquityChartRow[],
): AnyObj[] {
  type Pt = { tsMs: number; t: string; branch: OverlayBranchKey; equity: number; mtm: number };
  const pts: Pt[] = [];
  const push = (rows: EquityChartRow[], branch: OverlayBranchKey) => {
    for (const row of rows) {
      if (!Number.isFinite(row.tsMs)) continue;
      const mtm = row.mtm != null && Number.isFinite(Number(row.mtm)) ? Number(row.mtm) : row.equity;
      pts.push({ tsMs: row.tsMs, t: row.t, branch, equity: row.equity, mtm });
    }
  };
  push(live, "live");
  push(labA, "a");
  push(labB, "b");
  push(labC, "c");
  push(labD, "d");
  if (!pts.length) return [];
  pts.sort((x, y) => x.tsMs - y.tsMs);

  const byTs = new Map<number, Pt[]>();
  for (const p of pts) {
    const g = byTs.get(p.tsMs);
    if (g) g.push(p);
    else byTs.set(p.tsMs, [p]);
  }
  const uniqTs = [...byTs.keys()].sort((a, b) => a - b);

  const last: Record<OverlayBranchKey, { eq: number; mtm: number } | null> = { live: null, a: null, b: null, c: null, d: null };
  const branches: OverlayBranchKey[] = ["live", "a", "b", "c", "d"];
  const out: AnyObj[] = [];

  for (const tsMs of uniqTs) {
    const hits = byTs.get(tsMs)!;
    let tLabel = "";
    for (const h of hits) {
      last[h.branch] = { eq: h.equity, mtm: h.mtm };
      if (h.branch === "live") tLabel = h.t;
    }
    if (!tLabel) tLabel = hits[0].t;

    const row: AnyObj = { tsMs, t: tLabel };
    for (const br of branches) {
      const L = last[br];
      if (!L) continue;
      row[`${br}Eq`] = L.eq;
      row[`${br}Mtm`] = L.mtm;
      row[`${br}Blend`] = (L.eq + L.mtm) / 2;
      row[`${br}Pot`] = L.mtm - L.eq;
    }
    out.push(row);
  }
  return out;
}

/** Align branches on snapshot timestamps; normalize MTM (or book) to index 100 at first in-window point per series. */
function buildExperimentBrainLineRows(
  live: EquityChartRow[],
  labA: EquityChartRow[],
  labB: EquityChartRow[],
  labC: EquityChartRow[],
  labD: EquityChartRow[],
  maxPoints: number,
): AnyObj[] {
  type Col = "live" | "a" | "b" | "c" | "d";
  type Pt = { tsMs: number; t: string; branch: Col; v: number };
  const pts: Pt[] = [];
  const add = (rows: EquityChartRow[], branch: Col) => {
    for (const row of rows) {
      const v = equityRowMtmOrEq(row);
      if (v == null || !Number.isFinite(row.tsMs)) continue;
      pts.push({ tsMs: row.tsMs, t: row.t, branch, v });
    }
  };
  add(live, "live");
  add(labA, "a");
  add(labB, "b");
  add(labC, "c");
  add(labD, "d");
  if (!pts.length) return [];
  pts.sort((x, y) => x.tsMs - y.tsMs);
  const byTs = new Map<number, Pt[]>();
  for (const p of pts) {
    const g = byTs.get(p.tsMs);
    if (g) g.push(p);
    else byTs.set(p.tsMs, [p]);
  }
  const uniqTs = [...byTs.keys()].sort((a, b) => a - b);
  const tailTs = uniqTs.slice(-Math.max(12, Math.min(maxPoints, 200)));

  const last: Record<Col, number | null> = { live: null, a: null, b: null, c: null, d: null };
  const cols: Col[] = ["live", "a", "b", "c", "d"];
  const rawRows: AnyObj[] = [];
  for (const tsMs of tailTs) {
    const hits = byTs.get(tsMs)!;
    let tLabel = "";
    for (const h of hits) {
      last[h.branch] = h.v;
      if (h.branch === "live") tLabel = h.t;
    }
    if (!tLabel) tLabel = hits[0].t;
    const row: AnyObj = { t: tLabel, tsMs, idx: rawRows.length };
    for (const c of cols) row[c] = last[c];
    rawRows.push(row);
  }
  const baseline: Partial<Record<Col, number>> = {};
  for (const c of cols) {
    for (const r of rawRows) {
      const v = r[c] as number | null;
      if (v != null && Number.isFinite(v) && Math.abs(v) > 1e-9) {
        baseline[c] = v;
        break;
      }
    }
  }
  return rawRows.map((r) => {
    const out: AnyObj = { t: r.t, idx: r.idx };
    for (const c of cols) {
      const v = r[c] as number | null;
      const b = baseline[c];
      out[`${c}$`] = v;
      out[c] = v != null && b != null && b !== 0 ? (100 * v) / b : null;
    }
    return out;
  });
}

function EquityDualLineChart({
  data,
  equityStroke,
  mtmStroke,
  revision = "",
}: {
  data: EquityChartRow[];
  equityStroke: string;
  mtmStroke: string;
  /** Bumps when the live tail values change so Recharts redraws after each dashboard poll. */
  revision?: string;
}) {
  // Recharts ignores null/undefined for Line points — synthesize a numeric series so MTM always draws.
  const plotData = useMemo(
    () =>
      data.map((d) => ({
        ...d,
        mtmPlot: d.mtm != null && Number.isFinite(Number(d.mtm)) ? Number(d.mtm) : d.equity,
      })),
    [data, revision],
  );
  return (
    <ResponsiveContainer key={revision || "eq"} width="100%" height="100%">
      <LineChart key={revision || "lc"} data={plotData} margin={{ left: 6, right: 10, top: 8, bottom: 32 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#223056" />
        <XAxis dataKey="t" stroke="#7f8ab5" tick={{ fontSize: 11 }} />
        <YAxis stroke="#7f8ab5" tick={{ fontSize: 11 }} domain={["auto", "auto"]} />
        <Tooltip
          contentStyle={{ background: "#0b1228", border: "1px solid #243055" }}
          formatter={(value: number, name: string) => [`$${Number(value).toFixed(2)}`, name]}
        />
        <Legend
          verticalAlign="bottom"
          height={28}
          wrapperStyle={{ fontSize: 11, paddingTop: 6 }}
          formatter={(value) => <span style={{ color: "var(--muted)" }}>{String(value)}</span>}
        />
        <Line type="monotone" dataKey="equity" name="Book value (cost basis)" stroke={equityStroke} strokeWidth={2} dot={false} />
        <Line
          type="monotone"
          dataKey="mtmPlot"
          name="Current worth (MTM)"
          stroke={mtmStroke}
          strokeWidth={2}
          strokeDasharray="6 4"
          dot={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

function SnapSentimentBar({ impliedYes01 }: { impliedYes01: number }) {
  const pct = Math.min(100, Math.max(0, impliedYes01 * 100));
  return (
    <div className="snap-sentiment-wrap">
      <div
        className="snap-sentiment-track"
        role="img"
        aria-label={`Implied YES about ${Math.round(pct)} percent; bar runs from NO on the left to YES on the right.`}
      >
        <span className="snap-sentiment-midline" title="50% implied YES" />
        <span className="snap-sentiment-marker" style={{ left: `${pct}%` }} title={`~${Math.round(pct)}% implied YES`} />
      </div>
      <div className="snap-sentiment-labels" aria-hidden="true">
        <span style={{ color: "var(--danger)" }}>NO</span>
        <span style={{ color: "var(--ok)" }}>YES</span>
      </div>
    </div>
  );
}

function EngineAssetSnapBlock({
  snap,
  lastTick,
  engineOn,
  label,
}: {
  snap: AnyObj | undefined;
  lastTick: string | undefined;
  engineOn: boolean;
  label: string;
}) {
  const asOf = lastTick
    ? `Tick ${fmtIsoLocal(String(lastTick))} (${fmtIsoUtcTime(String(lastTick)) || "UTC"})`
    : "No tick time yet";
  const stale = !engineOn ? (
    <span className="sub" title="Engine is off; snapshot may be from the last tick.">
      {" "}
      · engine off (snapshot may be stale)
    </span>
  ) : null;
  if (!snap) {
    return (
      <span title={`${label}: no snapshot yet for this asset on this branch.`}>
        <span style={{ color: "var(--muted)" }}>{label}:</span> No snapshot — turn this branch on and wait for
        poll.{stale}
      </span>
    );
  }
  if (!snap.ok) {
    return (
      <span title={`${label}: snapshot error — ${String(snap.reason || "")} ${String(snap.note || "")}`}>
        <span style={{ color: "var(--muted)" }}>{label}:</span> {String(snap.reason || "—")}: {String(snap.note || "")}{" "}
        <span className="sub" title="Last engine tick timestamp for this branch.">
          ({asOf})
        </span>
        {stale}
      </span>
    );
  }
  const hasBook = Boolean(snap.has_orderbook);
  const implied01 =
    snap.implied_prob != null && Number.isFinite(Number(snap.implied_prob))
      ? Math.min(1, Math.max(0, Number(snap.implied_prob)))
      : null;
  const bidN = snap.yes_bid != null && snap.yes_bid !== "" ? Number(snap.yes_bid) : NaN;
  const askN = snap.yes_ask != null && snap.yes_ask !== "" ? Number(snap.yes_ask) : NaN;
  const bidOk = Number.isFinite(bidN) && bidN > 0 && bidN <= 1;
  const askOk = Number.isFinite(askN) && askN > 0 && askN <= 1;
  const midFromBook = bidOk && askOk ? (bidN + askN) / 2 : askOk ? askN : bidOk ? bidN : null;
  const barYes01 = implied01 ?? midFromBook;
  const fromBookOnly = implied01 == null && midFromBook != null;
  const pYes = barYes01;
  const lean: "yes" | "no" | "neutral" =
    pYes == null ? "neutral" : pYes >= 0.5 ? "yes" : "no";
  const fmtPx = (v: unknown) => {
    if (v == null || v === "") return "—";
    const n = Number(v);
    if (!Number.isFinite(n) || n <= 0) return "—";
    return n.toFixed(3);
  };
  const yesPctStr = pYes != null ? `${Math.round(pYes * 100)}%` : hasBook ? "—" : "no book";
  const noPctStr = pYes != null ? `${Math.round((1 - pYes) * 100)}%` : "—";
  const bid = fmtPx(snap.yes_bid);
  const ask = fmtPx(snap.yes_ask);
  const rules = Array.isArray(snap.rules_matched) ? (snap.rules_matched as string[]) : [];
  const none = rules.length === 0;
  const mins = snap.minutes_left != null ? `${Number(snap.minutes_left).toFixed(1)}m to close` : "—";
  const target = snap.target_hint ? String(snap.target_hint) : null;
  const lastRaw = snap.last_price_dollars != null ? String(snap.last_price_dollars) : "";
  const lastPx = lastRaw && Number(lastRaw) > 0 ? lastRaw : null;
  const strikeBits = [snap.floor_strike_dollars, snap.cap_strike_dollars].filter(Boolean).join(" – ");
  const leanClass =
    lean === "yes" ? "engine-snap-block--yes" : lean === "no" ? "engine-snap-block--no" : "engine-snap-block--neutral";

  return (
    <div
      className={`engine-snap-block ${leanClass}`}
      style={{ display: "flex", flexDirection: "column", gap: 4 }}
      title={`${label}: best headline market for this asset on the last tick — implied YES from book, bid/ask, rules matched.`}
    >
      <div>
        <span style={{ color: "var(--muted)" }} title="Live vs sim lab branch.">
          {label}:
        </span>{" "}
        {pYes != null ? (
          <>
            {lean === "yes" ? (
              <>
                <strong className="snap-lean-yes" title="Order book leans YES (implied YES ≥ 50%).">
                  YES
                </strong>{" "}
                <span
                  title={
                    fromBookOnly
                      ? "YES probability estimated from bid/ask mid (no implied_prob on this row)."
                      : "Implied YES probability from order book (mid / bid-ask when both exist)."
                  }
                >
                  ~{yesPctStr}
                </span>
                <span style={{ color: "var(--muted)" }} title="Implied NO for the same contract.">
                  {" "}
                  · NO ~{noPctStr}
                </span>
              </>
            ) : (
              <>
                <strong className="snap-lean-no" title="Order book leans NO (implied YES &lt; 50%).">
                  NO
                </strong>{" "}
                <span title="Implied NO from the same mid (1 − implied YES).">~{noPctStr}</span>
                <span style={{ color: "var(--muted)" }} title="Implied YES from order book.">
                  {" "}
                  · YES ~{yesPctStr}
                </span>
              </>
            )}
          </>
        ) : (
          <>
            <strong title="No usable two-sided YES book on this row.">YES</strong> {yesPctStr}
          </>
        )}{" "}
        · bid/ask{" "}
        <code title="Best YES bid dollars.">{bid}</code>/
        <code title="Best YES ask dollars (limit price used for sizing).">{ask}</code>
        {lastPx ? (
          <>
            {" "}
            · last <code title="Last traded price on Kalshi if present.">{lastPx}</code>
          </>
        ) : null}
        {target ? (
          <>
            {" "}
            ·{" "}
            <span style={{ color: "#a5f3fc" }} title="Strike or target parsed from the YES subtitle.">
              {target}
            </span>
          </>
        ) : null}
        {strikeBits ? (
          <>
            {" "}
            · strikes <code title="Floor/cap strike from market metadata.">{strikeBits}</code>
          </>
        ) : null}
      </div>
      {barYes01 != null ? (
        <SnapSentimentBar impliedYes01={barYes01} />
      ) : (
        <div className="snap-sentiment-wrap" title="No implied probability or usable YES bid/ask on this row yet.">
          <div className="snap-sentiment-track" style={{ opacity: 0.35 }}>
            <span className="snap-sentiment-midline" title="50% implied YES" />
            <span className="snap-sentiment-marker" style={{ left: "50%" }} title="No book mid" />
          </div>
          <div className="snap-sentiment-labels" aria-hidden="true">
            <span style={{ color: "var(--danger)" }}>NO</span>
            <span style={{ color: "var(--ok)" }}>YES</span>
          </div>
        </div>
      )}
      <div title="Contract ticker and time to market close.">
        <span className="sub">Contract</span> <code title="Market ticker.">{String(snap.ticker || "")}</code> ·{" "}
        <span title="Minutes until close from engine clock.">{mins}</span>
        {snap.close_time ? (
          <>
            {" "}
            · settle{" "}
            <span title={String(snap.close_time)}>{fmtMarketSettle(snap.close_time)}</span>
          </>
        ) : null}
      </div>
      <div title="Which configured rule bands matched implied prob and time left (or DEV bypass when enabled).">
        <span className="sub">Rules matched</span>:{" "}
        {none ? (
          <strong
            style={{ color: "#ffc878" }}
            title="No trade: every rule needs implied prob on the rule’s axis AND minutes-to-close inside that rule’s windows together. Gaps between rules (e.g. 52–55% YES) are normal until you widen bands."
          >
            NONE
          </strong>
        ) : (
          <span style={{ color: "var(--ok)", fontWeight: 600 }} title="Matched rule names from the engine.">
            {rules.join(", ")}
          </span>
        )}
        {stale}
      </div>
      {none && snap.rule_match_hint ? (
        <div
          className="sub"
          style={{ marginTop: 4, color: "#a5c4ff", fontSize: 11, lineHeight: 1.5 }}
          title="Engine-side explanation when the book is usable but no rule’s prob×time window matched."
        >
          {String(snap.rule_match_hint)}
        </div>
      ) : null}
      <div className="sub" style={{ fontSize: 11, opacity: 0.9 }} title="As-of time for this snapshot.">
        {asOf}
      </div>
      {snap.snapshot_note ? (
        <div
          className="sub"
          style={{ marginTop: 4, color: "#ffc878", fontSize: 11, lineHeight: 1.45 }}
          title="Optional note from the backend for this snapshot."
        >
          {String(snap.snapshot_note)}
        </div>
      ) : null}
    </div>
  );
}

export default function App() {
  const OPTIMIZER_SEEN_IDS_KEY = "optimizer_seen_ids_v1";
  const OPTIMIZER_DISMISSED_IDS_KEY = "optimizer_dismissed_ids_v1";
  const DASHBOARD_REQUEST_TIMEOUT_MS = 90_000;
  const DASHBOARD_STALE_INFLIGHT_MS = DASHBOARD_REQUEST_TIMEOUT_MS + 5_000;
  const [dash, setDash] = useState<AnyObj | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [heroMarqueeSpeedMult, setHeroMarqueeSpeedMult] = useState(readHeroMarqueeSpeedMult);
  const tradeToastsBootstrappedRef = useRef(false);
  const seenTradeInitRef = useRef<Set<string>>(new Set());
  const seenTradeSettleRef = useRef<Set<string>>(new Set());
  /** User-dismissed trade toast ids (``trade-initiated-*`` / ``trade-resolved-*``); survives effect re-runs. */
  const dismissedTradeToastIdsRef = useRef<Set<string>>(new Set());
  const [optimizerNotifs, setOptimizerNotifs] = useState<AnyObj[]>([]);
  const [tradePopupToastsEnabled, setTradePopupToastsEnabled] = useState(() => readTradePopupToastsEnabled());
  const [optimizerRows, setOptimizerRows] = useState<AnyObj[]>([]);
  const [optimizerCfg, setOptimizerCfg] = useState<AnyObj>({});
  const [optimizerOpen, setOptimizerOpen] = useState(false);
  const [optimizerSaving, setOptimizerSaving] = useState(false);
  const [toastTradeRows, setToastTradeRows] = useState<AnyObj[] | null>(null);
  const seenOptimizerEventIds = useRef<Set<string>>(new Set());
  const dismissedOptimizerEventIds = useRef<Set<string>>(new Set());
  const optimizerHistoryBootstrapped = useRef(false);
  const [assetWatchLab, setAssetWatchLab] = useState<"live" | "a" | "b" | "c" | "d">("live");
  const [holdingsBranchTab, setHoldingsBranchTab] = useState<"live" | "a" | "b" | "c" | "d">("live");
  const [accountActivityView, setAccountActivityView] = useState<"signals" | "trades" | "not_traded">("signals");
  const [perfBranch, setPerfBranch] = useState<PerfBranchKey>("live");
  const [equityGranularity, setEquityGranularity] = useState<EquityGranularity>("intraday");
  const [equityVisible, setEquityVisible] = useState<Record<"live" | "a" | "b" | "c" | "d", boolean>>({
    live: true,
    a: true,
    b: true,
    c: true,
    d: true,
  });
  const [equityCompareOpen, setEquityCompareOpen] = useState(false);
  const [equityCompareMode, setEquityCompareMode] = useState<"blended" | "potential">("blended");
  const [infoPopup, setInfoPopup] = useState<{ title: string; body: ReactNode } | null>(null);
  /** Last loaded dashboard JSON — used for optimizer report overlay if current ``dash`` is briefly null. */
  const dashSnapshotRef = useRef<AnyObj | null>(null);

  /**
   * Dashboard fetch coordination:
   * - reuse one in-flight refresh Promise for non-forced callers (polls, startup, passive refreshes)
   * - force refresh explicitly aborts and supersedes
   * A monotonic epoch still lets superseded/unmount-aborted fetches skip stale setState.
   */
  const dashboardAbortRef = useRef<AbortController | null>(null);
  const dashboardFetchEpoch = useRef(0);
  const dashboardInFlightRef = useRef<Promise<AnyObj | null> | null>(null);
  const dashboardInFlightStartedAtRef = useRef(0);
  const firstDashLoadedRef = useRef(false);
  const refresh = useCallback((opts?: { force?: boolean }): Promise<AnyObj | null> => {
    const force = Boolean(opts?.force);
    const inFlight = dashboardInFlightRef.current;
    const hasFreshInFlight =
      inFlight &&
      Date.now() - dashboardInFlightStartedAtRef.current < DASHBOARD_STALE_INFLIGHT_MS;
    if (hasFreshInFlight && !force) {
      return inFlight;
    }
    if (dashboardInFlightRef.current && !hasFreshInFlight) {
      // Recovery path for wedged Promises: stop reusing stale in-flight work.
      dashboardAbortRef.current?.abort();
      dashboardInFlightRef.current = null;
      dashboardInFlightStartedAtRef.current = 0;
    }
    if (force) {
      dashboardAbortRef.current?.abort();
    }
    const req = (async (): Promise<AnyObj | null> => {
      const myEpoch = ++dashboardFetchEpoch.current;
      const ac = new AbortController();
      dashboardAbortRef.current = ac;
      const maxMs = DASHBOARD_REQUEST_TIMEOUT_MS;
      const tid = window.setTimeout(() => ac.abort(), maxMs);
      let payload: AnyObj | null = null;
      try {
        // Do not clear errors on every poll: a slow /api/dashboard would otherwise flip the UI to
        // the loading screen (!dash && !err) until the request finishes or times out.
        if (force) setErr(null);
        const r = await fetch("/api/dashboard", { signal: ac.signal });
        if (myEpoch !== dashboardFetchEpoch.current) return null;
        if (!r.ok) throw new Error(`/api/dashboard ${r.status}`);
        const text = await r.text();
        if (myEpoch !== dashboardFetchEpoch.current) return null;
        const d: AnyObj = (() => {
          try {
            return JSON.parse(text) as AnyObj;
          } catch {
            throw new Error("Invalid JSON from /api/dashboard");
          }
        })();
        if (myEpoch !== dashboardFetchEpoch.current) return null;
        setErr(null);
        setDash(d);
        firstDashLoadedRef.current = true;
        payload = d;
      } catch (e: any) {
        if (myEpoch !== dashboardFetchEpoch.current) return null;
        const msg = String(e?.message || e);
        const aborted =
          String(e?.name || "") === "AbortError" || /aborted|AbortError/i.test(msg);
        if (aborted) {
          setErr(
            `Dashboard request timed out after ${maxMs / 1000}s. The API is running but /api/dashboard is very slow (often Kalshi order books for open paper positions). Try turning engines off, reduce open sim trades, or check backend logs.`,
          );
        } else if (/Failed to fetch|NetworkError|network error|Load failed|ECONNREFUSED/i.test(msg)) {
          setErr(
            "Cannot reach the backend. Run the API first (e.g. .\\scripts\\run_backend.ps1 or .\\scripts\\launch_local.ps1), then open this app at http://localhost:5173 — not the API port alone.",
          );
        } else if (/\b404\b/.test(msg)) {
          setErr(
            "Got 404 from /api — use the Vite URL http://localhost:5173 so /api is proxied to the Python server.",
          );
        } else {
          setErr(msg);
        }
      } finally {
        window.clearTimeout(tid);
        if (dashboardAbortRef.current === ac) {
          dashboardAbortRef.current = null;
        }
      }
      return payload;
    })();

    dashboardInFlightRef.current = req;
    dashboardInFlightStartedAtRef.current = Date.now();
    return req.finally(() => {
      if (dashboardInFlightRef.current === req) {
        dashboardInFlightRef.current = null;
        dashboardInFlightStartedAtRef.current = 0;
      }
    });
  }, [DASHBOARD_REQUEST_TIMEOUT_MS, DASHBOARD_STALE_INFLIGHT_MS]);

  /** Merge saved bot config into dashboard state without waiting on slow ``/api/dashboard`` (MTM, order books). */
  const applyDashboardConfig = useCallback((nextConfig: AnyObj) => {
    setDash((prev) => {
      if (!prev) return prev;
      const sim = Boolean(nextConfig.simulate);
      const la = (nextConfig.lab_a || {}) as AnyObj;
      const lb = (nextConfig.lab_b || {}) as AnyObj;
      const lc = (nextConfig.lab_c || {}) as AnyObj;
      const ld = (nextConfig.lab_d || {}) as AnyObj;
      const liveOn = Boolean(nextConfig.engine_running);
      const labAOn = Boolean(la.engine_running);
      const labBOn = Boolean(lb.engine_running);
      const labCOn = Boolean(lc.engine_running);
      const labDOn = Boolean(ld.engine_running);

      const engine = { ...((prev.engine || {}) as AnyObj) };
      const live = { ...((engine.live || {}) as AnyObj) };
      live.engine_running = liveOn;
      live.simulate_orders = sim;
      engine.live = live;
      const patchBranch = (key: string, on: boolean) => {
        const cur = engine[key];
        if (cur && typeof cur === "object") {
          engine[key] = { ...cur, engine_running: on, simulate_orders: true };
        }
      };
      patchBranch("lab_a", labAOn);
      patchBranch("lab_b", labBOn);
      patchBranch("lab_c", labCOn);
      patchBranch("lab_d", labDOn);
      if (engine.sim_lab && typeof engine.sim_lab === "object") {
        engine.sim_lab = { ...engine.sim_lab, engine_running: labAOn, simulate_orders: true };
      }

      const kalshi = { ...((prev.kalshi || {}) as AnyObj) };
      kalshi.simulate_live = sim;
      kalshi.polling_enabled = liveOn || labAOn || labBOn || labCOn;
      if ("private_ok" in kalshi) {
        kalshi.order_writes_live = Boolean(kalshi.private_ok) && !sim;
      }

      return { ...prev, config: nextConfig, engine, kalshi };
    });
  }, []);

  useEffect(() => {
    void refresh();
    // Slower than before so a slow dashboard (MTM for Live + 3 labs) can finish before the next poll stacks up.
    const id = window.setInterval(() => void refresh(), 8000);
    return () => {
      window.clearInterval(id);
      dashboardFetchEpoch.current += 1;
      dashboardAbortRef.current?.abort();
    };
  }, [refresh]);

  const loadOptimizer = useCallback(async () => {
    try {
      const d = await apiGet<AnyObj>("/api/optimizer/recommendations?limit=10");
      setOptimizerRows(Array.isArray(d?.rows) ? d.rows : []);
      setOptimizerCfg((d?.config || {}) as AnyObj);
    } catch {
      setOptimizerRows([]);
    }
  }, []);

  useEffect(() => {
    if (!optimizerOpen) return;
    void loadOptimizer();
    const id = window.setInterval(() => void loadOptimizer(), 20000);
    return () => window.clearInterval(id);
  }, [optimizerOpen, loadOptimizer]);

  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const d = await apiGet<AnyObj>("/api/trades?limit=160");
        if (!alive) return;
        const rows = Array.isArray(d) ? d : Array.isArray((d as AnyObj)?.rows) ? ((d as AnyObj).rows as AnyObj[]) : [];
        setToastTradeRows(rows);
      } catch {
        if (!alive) return;
        // First completed attempt (even on failure) unblocks toast bootstrap so we do not treat
        // the full merged history as "new" when /api/trades is slow or errors once.
        setToastTradeRows((prev) => (prev === null ? [] : prev));
      }
    };
    void poll();
    const id = window.setInterval(() => void poll(), 10000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  const cfg = dash?.config || {};
  const setHeroMarqueeSpeedMultPersist = useCallback((mult: number) => {
    const clamped = Math.min(4, Math.max(0.35, mult));
    persistHeroMarqueeSpeedMult(clamped);
    setHeroMarqueeSpeedMult(clamped);
  }, []);

  const setTradePopupToastsEnabledPersist = useCallback((on: boolean) => {
    persistTradePopupToastsEnabled(on);
    setTradePopupToastsEnabled(on);
  }, []);

  useEffect(() => {
    if (dash) dashSnapshotRef.current = dash as AnyObj;
  }, [dash]);

  useEffect(() => {
    if (tradePopupToastsEnabled) return;
    setOptimizerNotifs((prev) =>
      prev.filter((n) => {
        const id = String(n.id || "");
        return !id.startsWith("trade-initiated-") && !id.startsWith("trade-resolved-");
      }),
    );
  }, [tradePopupToastsEnabled]);

  const visibleOptimizerNotifs = useMemo(() => {
    return optimizerNotifs.filter((n) => {
      const id = String(n.id || "");
      if (id.startsWith("trade-initiated-") || id.startsWith("trade-resolved-")) return tradePopupToastsEnabled;
      return true;
    });
  }, [optimizerNotifs, tradePopupToastsEnabled]);

  /**
   * Bottom-right cards when a sim/live trade row first appears or settles.
   * Bootstrap runs only after **both** the dashboard snapshot and at least one ``/api/trades`` response
   * (success or empty/error fallback). That way a later poll cannot merge hundreds of “new” ids vs
   * an early partial seed and spam toasts on load.
   */
  useEffect(() => {
    const rows = mergeTradeRowsForToastEffect(dash?.recent_trades, toastTradeRows);
    const dashReady = dash != null;
    const tradesPollCompleted = toastTradeRows !== null;
    if (!tradeToastsBootstrappedRef.current) {
      if (!dashReady || !tradesPollCompleted) return;
      for (const t of rows) {
        const idStr = tradeToastRowKey(t);
        if (!idStr) continue;
        const st = String(t.status || "").toLowerCase();
        const resolved = tradeRowLooksResolved(t);
        if (resolved) {
          seenTradeSettleRef.current.add(idStr);
          seenTradeInitRef.current.add(idStr);
        } else if (tradeStatusIsActiveBid(st)) {
          seenTradeInitRef.current.add(idStr);
        }
      }
      tradeToastsBootstrappedRef.current = true;
      return;
    }
    if (!rows.length) return;
    if (!tradePopupToastsEnabled) return;
    const toAdd: AnyObj[] = [];
    for (const t of rows) {
      const idStr = tradeToastRowKey(t);
      if (!idStr) continue;
      const st = String(t.status || "").toLowerCase();
      const resolved = tradeRowLooksResolved(t);
      const branch = branchLabelForTradeToast(t.branch);
      const tick = String(t.ticker || "").slice(0, 48);
      const side = String(t.side || "").toUpperCase() || "—";
      const sim = Boolean(Number(t.simulated));
      if (resolved) {
        if (seenTradeSettleRef.current.has(idStr)) continue;
        seenTradeSettleRef.current.add(idStr);
        if (!seenTradeInitRef.current.has(idStr)) {
          seenTradeInitRef.current.add(idStr);
        }
        const rawP = t.pnl_cents;
        const pnl =
          rawP == null || rawP === ""
            ? null
            : (() => {
                const n = Number(rawP);
                return Number.isFinite(n) ? n / 100.0 : null;
              })();
        let lineTier: "green" | "red" | "yellow" | "neutral" = "neutral";
        if (pnl != null) {
          if (pnl > 0) lineTier = "green";
          else if (pnl < 0) lineTier = "red";
          else lineTier = "yellow";
        }
        const resMeta = tradeResolutionLines(t);
        const cardTone = pnl != null && pnl < 0 ? "red" : pnl != null && pnl > 0 ? "green" : "yellow";
        const pnlText = pnl == null ? "PnL —" : `PnL ${pnl >= 0 ? "+" : ""}$${pnl.toFixed(2)}`;
        const toastId = `trade-resolved-${idStr}`;
        if (!dismissedTradeToastIdsRef.current.has(toastId)) {
          toAdd.push({
            id: toastId,
            title: sim ? resMeta.title : resMeta.title.replace(/^Purchase /, "Trade "),
            body: "",
            tone: cardTone,
            branch_swatch: branchToastSwatch(t.branch),
            branch_tip: branch,
            segments: [
              { tier: "neutral", text: `${branch} · ${tick} ${side}` },
              { tier: lineTier, text: pnlText },
              { tier: resMeta.resolutionTier, text: resMeta.lines[0] ?? "" },
              ...(resMeta.lines[1] ? [{ tier: "neutral" as const, text: resMeta.lines[1] }] : []),
            ],
            created_at: new Date().toISOString(),
          });
        }
        continue;
      }
      if (tradeStatusIsActiveBid(st)) {
        if (seenTradeInitRef.current.has(idStr)) continue;
        seenTradeInitRef.current.add(idStr);
        const toastId = `trade-initiated-${idStr}`;
        if (dismissedTradeToastIdsRef.current.has(toastId)) continue;
        const cost = Number(t.amount_cents || 0) / 100.0;
        toAdd.push({
          id: toastId,
          title: sim ? "Sim purchase" : "Purchase / order active",
          body: "",
          tone: "green",
          branch_swatch: branchToastSwatch(t.branch),
          branch_tip: branch,
          segments: [
            { tier: "neutral", text: `${branch} · ${tick} ${side}` },
            { tier: "green", text: `≈ $${cost.toFixed(2)} debit · ${st}` },
            { tier: "neutral", text: "Awaiting resolution (settle or early exit)" },
          ],
          created_at: new Date().toISOString(),
        });
      }
    }
    if (!toAdd.length) return;
    setOptimizerNotifs((prev) => {
      const byId = new Map<string, AnyObj>();
      for (const n of prev) {
        const pid = String(n.id || "");
        if (dismissedTradeToastIdsRef.current.has(pid)) continue;
        byId.set(pid, n);
      }
      for (const n of toAdd) {
        const nid = String(n.id || "");
        if (dismissedTradeToastIdsRef.current.has(nid)) continue;
        byId.set(nid, n);
      }
      const merged = Array.from(byId.values());
      merged.sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")));
      return merged.slice(0, 28);
    });
  }, [dash, toastTradeRows, tradePopupToastsEnabled]);

  const optimizerChangeHistoryMerged = useMemo(() => {
    const oc = (cfg as AnyObj)?.optimizer;
    const fromDash = Array.isArray(oc?.change_history) ? (oc.change_history as AnyObj[]) : [];
    const fromActivity = Array.isArray((dash as AnyObj | null)?.optimizer_activity?.change_history)
      ? ((dash as AnyObj).optimizer_activity.change_history as AnyObj[])
      : [];
    const fromPanel = Array.isArray(optimizerCfg?.change_history) ? (optimizerCfg.change_history as AnyObj[]) : [];
    const byId = new Map<string, AnyObj>();
    // Prefer dashboard activity rows first so stable ``ch-*`` ids from the API win over panel-only copies.
    for (const row of [...fromActivity, ...fromDash, ...fromPanel]) {
      if (!row || typeof row !== "object") continue;
      const id = stableOptimizerChangeId(row as AnyObj);
      const normalized = { ...(row as AnyObj), id };
      if (!byId.has(id)) byId.set(id, normalized);
    }
    const merged = Array.from(byId.values());
    merged.sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")));
    return merged;
  }, [cfg, dash, optimizerCfg?.change_history]);

  useEffect(() => {
    try {
      const rawSeen = window.sessionStorage.getItem(OPTIMIZER_SEEN_IDS_KEY);
      if (rawSeen) {
        const arr = JSON.parse(rawSeen);
        if (Array.isArray(arr)) {
          for (const id of arr) {
            const s = String(id || "");
            if (s) seenOptimizerEventIds.current.add(s);
          }
        }
      }
      const rawDismissed = window.sessionStorage.getItem(OPTIMIZER_DISMISSED_IDS_KEY);
      if (rawDismissed) {
        const arr = JSON.parse(rawDismissed);
        if (Array.isArray(arr)) {
          for (const id of arr) {
            const s = String(id || "");
            if (s) dismissedOptimizerEventIds.current.add(s);
          }
        }
      }
    } catch {
      // Ignore storage parsing errors.
    }
  }, []);

  useEffect(() => {
    const history = optimizerChangeHistoryMerged;
    // Bootstrap: mark existing history as seen so the Optimizer panel stays the place for a full audit trail;
    // trade toasts use a separate bootstrap for ``recent_trades``; new optimizer rows are not toasts here.
    if (!optimizerHistoryBootstrapped.current) {
      optimizerHistoryBootstrapped.current = true;
      for (const h of history) {
        const id = stableOptimizerChangeId(h);
        if (id) seenOptimizerEventIds.current.add(id);
      }
      try {
        window.sessionStorage.setItem(
          OPTIMIZER_SEEN_IDS_KEY,
          JSON.stringify(Array.from(seenOptimizerEventIds.current).slice(-600)),
        );
      } catch {
        // Ignore storage errors.
      }
      return;
    }
    if (!history.length) return;
    const fresh = history.filter((h) => {
      const id = stableOptimizerChangeId(h);
      return id && !seenOptimizerEventIds.current.has(id) && !dismissedOptimizerEventIds.current.has(id);
    });
    if (!fresh.length) return;
    for (const h of fresh) {
      const id = stableOptimizerChangeId(h);
      if (!id) continue;
      seenOptimizerEventIds.current.add(id);
    }
    try {
      window.sessionStorage.setItem(
        OPTIMIZER_SEEN_IDS_KEY,
        JSON.stringify(Array.from(seenOptimizerEventIds.current).slice(-600)),
      );
    } catch {
      // Ignore storage errors.
    }
  }, [optimizerChangeHistoryMerged]);

  const openOptimizerReportOverlay = useCallback(() => {
    const source = (dash || dashSnapshotRef.current) as AnyObj | null;
    if (!source) return;
    setInfoPopup({
      title: "Optimizer report",
      body: optimizerReportOverlayBody(source),
    });
  }, [dash]);

  const metrics = dash?.metrics || {};
  const metricsLabA = (dash?.metrics_lab_a || dash?.metrics_sim_lab || {}) as AnyObj;
  const metricsLabB = (dash?.metrics_lab_b || {}) as AnyObj;
  const metricsLabC = (dash?.metrics_lab_c || {}) as AnyObj;
  const metricsLabD = (dash?.metrics_lab_d || {}) as AnyObj;

  const promoteLabAToLive = async () => {
    const pnlA = Number(metricsLabA.total_pnl_dollars ?? 0);
    const pnlB = Number(metricsLabB.total_pnl_dollars ?? 0);
    const pnlC = Number(metricsLabC.total_pnl_dollars ?? 0);
    const pnlD = Number(metricsLabD.total_pnl_dollars ?? 0);
    const ahead = pnlA > pnlB && pnlA > pnlC && pnlA > pnlD;
    if (!ahead) {
      setErr("Lab A settled PnL must exceed Lab B, Lab C, and Lab D before promoting to Live.");
      return;
    }
    const sim = Boolean(cfg.simulate);
    const msg = sim
      ? `Copy Lab A trading settings (rules, window, bet fraction, filters, fees) to the Live branch?\n\nLab A $${pnlA.toFixed(2)} vs B $${pnlB.toFixed(2)} vs C $${pnlC.toFixed(2)} vs D $${pnlD.toFixed(2)} settled PnL.`
      : `LIVE / REAL MONEY: Copy Lab A settings onto the Live branch. Live uses Real $ when the engine is on.\n\nYou will be asked to type APPLY_LIVE next.\n\nLab A $${pnlA.toFixed(2)} vs B $${pnlB.toFixed(2)} vs C $${pnlC.toFixed(2)} vs D $${pnlD.toFixed(2)} settled PnL.`;
    if (!window.confirm(msg)) return;
    let ack = "";
    if (!sim) {
      ack = String(window.prompt('Confirm by typing APPLY_LIVE (exactly) to copy Lab A into Live while in "Real $" mode.', "") || "").trim();
      if (ack !== "APPLY_LIVE") {
        setErr("Promote cancelled — ack phrase did not match.");
        return;
      }
    }
    setBusy(true);
    try {
      await apiPostJson("/api/config/promote-lab-a-to-live", {
        confirm: true,
        ack_live: ack,
      });
      await refresh();
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  };

  const snaps = (dash?.equity_snapshots || []) as AnyObj[];
  const equitySnapsLabA = (dash?.equity_snapshots_lab_a || dash?.equity_snapshots_sim_lab || []) as AnyObj[];
  const equitySnapsLabB = (dash?.equity_snapshots_lab_b || []) as AnyObj[];
  const equitySnapsLabC = (dash?.equity_snapshots_lab_c || []) as AnyObj[];
  const equitySnapsLabD = (dash?.equity_snapshots_lab_d || []) as AnyObj[];
  const labA = useMemo((): AnyObj => {
    const a = cfg.lab_a;
    if (a && typeof a === "object") return a as AnyObj;
    const s = cfg.sim_lab;
    if (s && typeof s === "object") return s as AnyObj;
    return EMPTY_LAB;
  }, [cfg.lab_a, cfg.sim_lab]);
  const labB = useMemo((): AnyObj => {
    const b = cfg.lab_b;
    if (b && typeof b === "object") return b as AnyObj;
    return EMPTY_LAB;
  }, [cfg.lab_b]);
  const labC = useMemo((): AnyObj => {
    const c = cfg.lab_c;
    if (c && typeof c === "object") return c as AnyObj;
    return EMPTY_LAB;
  }, [cfg.lab_c]);
  const labD = useMemo((): AnyObj => {
    const d = cfg.lab_d;
    if (d && typeof d === "object") return d as AnyObj;
    return EMPTY_LAB;
  }, [cfg.lab_d]);
  // Backward-compatible aliases while we expand UI sections incrementally.
  const simLab = labA;
  const perfBranchMeta = useMemo(() => {
    const map: Record<
      PerfBranchKey,
      { label: string; shortLabel: string; metrics: AnyObj; bankNoun: string; reconcileLabel: string; isLive: boolean }
    > = {
      live: { label: "Live", shortLabel: "Live", metrics: metrics as AnyObj, bankNoun: "bankroll", reconcileLabel: "paper", isLive: true },
      lab_a: { label: "Lab A", shortLabel: "A", metrics: metricsLabA, bankNoun: "lab bankroll", reconcileLabel: "Lab A", isLive: false },
      lab_b: { label: "Lab B", shortLabel: "B", metrics: metricsLabB, bankNoun: "lab bankroll", reconcileLabel: "Lab B", isLive: false },
      lab_c: { label: "Lab C", shortLabel: "C", metrics: metricsLabC, bankNoun: "lab bankroll", reconcileLabel: "Lab C", isLive: false },
      lab_d: { label: "Lab D", shortLabel: "D", metrics: metricsLabD, bankNoun: "lab bankroll", reconcileLabel: "Lab D", isLive: false },
    };
    return map[perfBranch];
  }, [perfBranch, metrics, metricsLabA, metricsLabB, metricsLabC, metricsLabD]);

  const activeTradesForPerfBranch = useMemo(() => {
    const rows = mergeTradeRowsForToastEffect(dash?.recent_trades, toastTradeRows);
    const list: AnyObj[] = [];
    for (const r of rows) {
      if (normalizeSignalTradeBranch(r.branch) !== perfBranch) continue;
      if (tradeRowLooksResolved(r)) continue;
      const st = String(r.status || "").toLowerCase();
      if (!tradeStatusIsActiveBid(st)) continue;
      list.push(r);
    }
    list.sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")));
    return list;
  }, [dash?.recent_trades, toastTradeRows, perfBranch]);

  const canPromoteLabAToLive =
    Number(metricsLabA.total_pnl_dollars ?? 0) > Number(metricsLabB.total_pnl_dollars ?? 0) &&
    Number(metricsLabA.total_pnl_dollars ?? 0) > Number(metricsLabC.total_pnl_dollars ?? 0) &&
    Number(metricsLabA.total_pnl_dollars ?? 0) > Number(metricsLabD.total_pnl_dollars ?? 0);

  const chartData = useMemo(
    () => equitySeriesWithLiveTail(snaps, equityGranularity, metrics, fmtIsoLocal),
    [snaps, equityGranularity, metrics, fmtIsoLocal],
  );

  const chartDataLabA = useMemo(
    () => equitySeriesWithLiveTail(equitySnapsLabA, equityGranularity, metricsLabA, fmtIsoLocal),
    [equitySnapsLabA, equityGranularity, metricsLabA, fmtIsoLocal],
  );
  const chartDataLabB = useMemo(
    () => equitySeriesWithLiveTail(equitySnapsLabB, equityGranularity, metricsLabB, fmtIsoLocal),
    [equitySnapsLabB, equityGranularity, metricsLabB, fmtIsoLocal],
  );
  const chartDataLabC = useMemo(
    () => equitySeriesWithLiveTail(equitySnapsLabC, equityGranularity, metricsLabC, fmtIsoLocal),
    [equitySnapsLabC, equityGranularity, metricsLabC, fmtIsoLocal],
  );
  const chartDataLabD = useMemo(
    () => equitySeriesWithLiveTail(equitySnapsLabD, equityGranularity, metricsLabD, fmtIsoLocal),
    [equitySnapsLabD, equityGranularity, metricsLabD, fmtIsoLocal],
  );
  const equityOverlayData = useMemo(
    () => mergeEquityOverlayRows(chartData, chartDataLabA, chartDataLabB, chartDataLabC, chartDataLabD),
    [chartData, chartDataLabA, chartDataLabB, chartDataLabC, chartDataLabD],
  );
  const equityOverlayRevision = `${equityChartRevision(snaps, chartData, metrics)}|${equityChartRevision(equitySnapsLabA, chartDataLabA, metricsLabA)}|${equityChartRevision(equitySnapsLabB, chartDataLabB, metricsLabB)}|${equityChartRevision(equitySnapsLabC, chartDataLabC, metricsLabC)}|${equityChartRevision(equitySnapsLabD, chartDataLabD, metricsLabD)}`;

  const branchBrainLineRows = useMemo(
    () => buildExperimentBrainLineRows(chartData, chartDataLabA, chartDataLabB, chartDataLabC, chartDataLabD, 96),
    [chartData, chartDataLabA, chartDataLabB, chartDataLabC, chartDataLabD],
  );

  const assets = (cfg.assets || {}) as AnyObj;
  const assetSnaps = (dash?.asset_snapshots || {}) as AnyObj;
  const engineSnapsLive = (assetSnaps.live || {}) as AnyObj;
  const engineSnapsLabA = ((assetSnaps.lab_a || assetSnaps.sim_lab) || {}) as AnyObj;
  const engineSnapsLabB = (assetSnaps.lab_b || {}) as AnyObj;
  const engineSnapsLabC = (assetSnaps.lab_c || {}) as AnyObj;
  const engineSnapsLabD = (assetSnaps.lab_d || {}) as AnyObj;
  const engineLabA = (dash?.engine?.lab_a ?? dash?.engine?.sim_lab) as AnyObj | undefined;
  const engineLabB = dash?.engine?.lab_b as AnyObj | undefined;
  const engineLabC = dash?.engine?.lab_c as AnyObj | undefined;
  const engineLabD = dash?.engine?.lab_d as AnyObj | undefined;
  /** Dashboard ``engine.*`` can lag; fall back to config (same idea as Lab A toolbar toggle). */
  const liveBranchEngineOn = Boolean((dash?.engine?.live as AnyObj | undefined)?.engine_running ?? cfg.engine_running);
  const labABranchEngineOn = Boolean(engineLabA?.engine_running ?? simLab.engine_running);
  const labBBranchEngineOn = Boolean(engineLabB?.engine_running ?? labB.engine_running);
  const labCBranchEngineOn = Boolean(engineLabC?.engine_running ?? labC.engine_running);
  const labDBranchEngineOn = Boolean(engineLabD?.engine_running ?? labD.engine_running);

  const accountActivityBranch: ActivityBranchKey =
    holdingsBranchTab === "live"
      ? "live"
      : holdingsBranchTab === "a"
        ? "lab_a"
        : holdingsBranchTab === "b"
          ? "lab_b"
          : holdingsBranchTab === "c"
            ? "lab_c"
            : "lab_d";

  const recentSignalsFiltered = useMemo(() => {
    const rs = (dash?.recent_signals || []) as AnyObj[];
    return rs.filter((r) => normalizeSignalTradeBranch(r.branch) === accountActivityBranch);
  }, [dash?.recent_signals, accountActivityBranch]);

  const recentTradesFiltered = useMemo(() => {
    const rt = (dash?.recent_trades || []) as AnyObj[];
    return rt.filter((r) => normalizeSignalTradeBranch(r.branch) === accountActivityBranch);
  }, [dash?.recent_trades, accountActivityBranch]);

  const notTradedFiltered = useMemo(() => {
    const nt = (dash?.not_traded_signals || []) as AnyObj[];
    return nt.filter((r) => normalizeSignalTradeBranch(r.branch) === accountActivityBranch);
  }, [dash?.not_traded_signals, accountActivityBranch]);

  const saveRules = async (rules: AnyObj[]) => {
    setBusy(true);
    try {
      await apiPut("/api/config", { rules });
      await refresh();
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  };

  const validateRulesOnServer = async (rules: AnyObj[]) => {
    const out = (await apiPostJson("/api/config/validate-rules", { rules })) as AnyObj;
    return { ok: Boolean(out?.ok), count: Number(out?.count ?? rules.length) };
  };

  const saveNoBetWhenYesBelow = async (pct: number | null) => {
    setBusy(true);
    try {
      await apiPut("/api/config", { no_bet_when_yes_below_pct: pct });
      await refresh();
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  };

  const setSimulate = async (simulate: boolean) => {
    if (!simulate && cfg.simulate) {
      const ok = window.confirm(
        "Switch Live mode to Real $? When the Live engine is on and a rule matches, the bot will place real limit orders on Kalshi (not paper). Sim lab always stays simulated.",
      );
      if (!ok) return;
    }
    const prevDash = dash;
    if (prevDash) applyDashboardConfig({ ...cfg, simulate });
    setBusy(true);
    try {
      const out = (await apiPost(`/api/engine/toggle?simulate=${simulate ? "true" : "false"}`)) as AnyObj;
      const cfgNext = out?.config;
      if (cfgNext && typeof cfgNext === "object") applyDashboardConfig(cfgNext as AnyObj);
      void refresh();
    } catch (e: any) {
      if (prevDash) setDash(prevDash);
      setErr(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  };

  const setRunning = async (running: boolean) => {
    const prevDash = dash;
    if (prevDash) applyDashboardConfig({ ...cfg, engine_running: running });
    setBusy(true);
    try {
      const out = (await apiPost(`/api/engine/toggle?running=${running ? "true" : "false"}`)) as AnyObj;
      const cfgNext = out?.config;
      if (cfgNext && typeof cfgNext === "object") applyDashboardConfig(cfgNext as AnyObj);
      void refresh();
    } catch (e: any) {
      if (prevDash) setDash(prevDash);
      setErr(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  };

  const setLabRunning = async (lab: "a" | "b" | "c" | "d", running: boolean) => {
    const prevDash = dash;
    if (prevDash) {
      const patch = { ...cfg } as AnyObj;
      if (lab === "a") patch.lab_a = { ...(cfg.lab_a || EMPTY_LAB), engine_running: running };
      else if (lab === "b") patch.lab_b = { ...(cfg.lab_b || EMPTY_LAB), engine_running: running };
      else if (lab === "c") patch.lab_c = { ...(cfg.lab_c || EMPTY_LAB), engine_running: running };
      else patch.lab_d = { ...(cfg.lab_d || EMPTY_LAB), engine_running: running };
      applyDashboardConfig(patch);
    }
    setBusy(true);
    try {
      const key = lab === "a" ? "lab_a_running" : lab === "b" ? "lab_b_running" : lab === "c" ? "lab_c_running" : "lab_d_running";
      const out = (await apiPost(`/api/engine/toggle?${key}=${running ? "true" : "false"}`)) as AnyObj;
      const cfgNext = out?.config;
      if (cfgNext && typeof cfgNext === "object") applyDashboardConfig(cfgNext as AnyObj);
      void refresh();
    } catch (e: any) {
      if (prevDash) setDash(prevDash);
      setErr(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  };
  const setSimLabRunning = async (running: boolean) => setLabRunning("a", running);

  const saveLabFromSliders = async (lab: "a" | "b" | "c" | "d") => {
    const p = lab === "a" ? "lab_a" : lab === "b" ? "lab_b" : lab === "c" ? "lab_c" : "lab_d";
    const fracRaw = (document.getElementById(`${p}_frac`) as HTMLInputElement | null)?.value;
    const winRaw = (document.getElementById(`${p}_win`) as HTMLInputElement | null)?.value;
    const paperRaw = (document.getElementById(`${p}_paper`) as HTMLInputElement | null)?.value;
    const frac = Number(String(fracRaw ?? "").replace(/,/g, "").trim());
    const win = Math.round(Number(String(winRaw ?? "").replace(/,/g, "").trim()));
    const paper = Math.round(Number(String(paperRaw ?? "").replace(/,/g, "").trim()));
    const autoReset = Boolean((document.getElementById(`${p}_auto_reset_failure`) as HTMLInputElement | null)?.checked);
    if (!Number.isFinite(frac) || frac < 0.0001 || frac > 1) {
      setErr("Lab balance fraction must be between 0.0001 and 1 (e.g. 0.055).");
      return;
    }
    if (!Number.isFinite(win) || win < 1 || win > 1440 || !Number.isInteger(win)) {
      setErr("Lab window length must be a whole number of minutes from 1 to 1440.");
      return;
    }
    if (!Number.isFinite(paper) || paper < 0 || !Number.isInteger(paper)) {
      setErr("Lab paper balance must be a non-negative whole number of cents (digits only, or use commas as thousands separators).");
      return;
    }
    setBusy(true);
    try {
      const patch = {
        balance_fraction_per_window: frac,
        window_minutes: win,
        paper_balance_cents: paper,
        auto_reset_paper_on_tick_failure: autoReset,
      };
      await apiPutLabBranches({
        reset_data: "none",
        ...(lab === "a" ? { lab_a: patch } : lab === "b" ? { lab_b: patch } : lab === "c" ? { lab_c: patch } : { lab_d: patch }),
      });
      await refresh();
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  };
  const saveSimLabFromSliders = async () => saveLabFromSliders("a");
  const saveLabAFromSliders = async () => saveLabFromSliders("a");
  const saveLabBFromSliders = async () => saveLabFromSliders("b");
  const saveLabCFromSliders = async () => saveLabFromSliders("c");
  const saveLabDFromSliders = async () => saveLabFromSliders("d");

  const saveLabRules = async (lab: "a" | "b" | "c" | "d", rules: AnyObj[]) => {
    setBusy(true);
    try {
      await apiPutLabBranches({
        reset_data: "none",
        ...(lab === "a" ? { lab_a: { rules } } : lab === "b" ? { lab_b: { rules } } : lab === "c" ? { lab_c: { rules } } : { lab_d: { rules } }),
      });
      await refresh();
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  };
  const saveLabARules = async (rules: AnyObj[]) => saveLabRules("a", rules);
  const saveLabBRules = async (rules: AnyObj[]) => saveLabRules("b", rules);
  const saveLabCRules = async (rules: AnyObj[]) => saveLabRules("c", rules);
  const saveLabDRules = async (rules: AnyObj[]) => saveLabRules("d", rules);

  const saveSizing = async () => {
    const frac = Number((document.getElementById("frac") as HTMLInputElement)?.value);
    const win = Number((document.getElementById("winmin") as HTMLInputElement)?.value);
    const poll = Number((document.getElementById("poll") as HTMLInputElement)?.value);
    const paper = Number((document.getElementById("paper") as HTMLInputElement)?.value);
    if (!Number.isFinite(frac) || frac < 0.0001 || frac > 1) {
      setErr("Balance fraction must be between 0.0001 and 1 (e.g. 0.03).");
      return;
    }
    if (!Number.isFinite(win) || win < 1 || win > 1440 || !Number.isInteger(win)) {
      setErr("Window length must be a whole number of minutes from 1 to 1440.");
      return;
    }
    if (!Number.isFinite(poll) || poll < 2 || poll > 120) {
      setErr("Poll seconds must be between 2 and 120 (API limit).");
      return;
    }
    if (!Number.isFinite(paper) || paper < 0 || !Number.isInteger(paper)) {
      setErr("Paper balance must be a non-negative whole number of cents.");
      return;
    }
    setBusy(true);
    try {
      await apiPut("/api/config", {
        balance_fraction_per_window: frac,
        window_minutes: win,
        poll_seconds: poll,
        paper_balance_cents: paper,
      });
      await refresh();
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  };

  const saveYesSubtitleFilter = async () => {
    const raw = (document.getElementById("yes_sub_filter") as HTMLInputElement)?.value ?? "";
    setBusy(true);
    try {
      await apiPut("/api/config", { only_yes_subtitle_contains: raw });
      await refresh();
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  };

  const saveExcludeSubtitleFilter = async () => {
    const raw = (document.getElementById("exclude_sub_filter") as HTMLInputElement)?.value ?? "";
    setBusy(true);
    try {
      await apiPut("/api/config", { exclude_yes_subtitle_contains: raw });
      await refresh();
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  };

  const saveDevSimHighYesPct = async (pct: number | null) => {
    setBusy(true);
    try {
      await apiPut("/api/config", { dev_sim_yes_implied_ge_pct: pct });
      await refresh();
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  };

  const saveSwingExitImpliedDropPct = async (pct: number | null) => {
    setBusy(true);
    try {
      await apiPut("/api/config", { swing_exit_implied_drop_pct: pct });
      await refresh();
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  };

  const savePaperFees = async (patch: Record<string, unknown>) => {
    setBusy(true);
    try {
      await apiPut("/api/config", patch);
      await refresh();
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  };

  const savePatientStopLossLive = async (patch: Record<string, unknown>) => {
    setBusy(true);
    try {
      await apiPut("/api/config", patch);
      await refresh();
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  };

  const savePatientStopLossLab = async (lab: "a" | "b" | "c" | "d", patch: Record<string, unknown>) => {
    const key = lab === "a" ? "lab_a" : lab === "b" ? "lab_b" : lab === "c" ? "lab_c" : "lab_d";
    setBusy(true);
    try {
      await apiPutLabBranches({ reset_data: "none", [key]: patch });
      await refresh();
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  };

  const saveOptimizerConfig = async (patch: Record<string, unknown>) => {
    // Do not use global `busy` here — it disables the top-right Claude optimizer toggle and feels like a freeze.
    setOptimizerSaving(true);
    try {
      await apiPut("/api/optimizer/config", patch as AnyObj);
      await loadOptimizer();
      await refresh();
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally {
      setOptimizerSaving(false);
    }
  };

  const runOptimizerNow = useCallback(async () => {
    setOptimizerSaving(true);
    try {
      await apiPostJson("/api/optimizer/run", {});
      await loadOptimizer();
      await refresh({ force: true });
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally {
      setOptimizerSaving(false);
    }
  }, [loadOptimizer, refresh]);

  const applyLabBranchesBulk = async (body: AnyObj) => {
    setBusy(true);
    try {
      await apiPutLabBranches(body);
      await refresh();
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  };

  const resetTradingData = async (
    branch: "all" | "all_labs" | "live" | "lab_a" | "lab_b" | "lab_c" | "lab_d",
    backup: boolean,
    uniformPaperBalanceCents?: number | null,
  ) => {
    setBusy(true);
    setErr(null);
    try {
      const q = new URLSearchParams({
        confirm: "yes",
        backup: backup ? "true" : "false",
        branch,
      });
      if (
        (branch === "all" || branch === "all_labs") &&
        uniformPaperBalanceCents != null &&
        Number.isFinite(uniformPaperBalanceCents)
      ) {
        const c = Math.round(Number(uniformPaperBalanceCents));
        if (c >= 0 && c <= 100_000_000) {
          q.set("uniform_paper_balance_cents", String(c));
        }
      }
      const headers: Record<string, string> = {};
      if (dash?.storage?.data_reset_token_configured) {
        const el = document.getElementById("reset_token_field") as HTMLInputElement | null;
        const t = el?.value?.trim();
        if (t) headers["X-Reset-Token"] = t;
      }
      const r = await fetch(`/api/data/reset?${q.toString()}`, { method: "POST", headers });
      if (!r.ok) throw new Error((await r.text()) || `reset ${r.status}`);
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally {
      setBusy(false);
    }
    // Run after clearing busy so a slow /api/dashboard poll does not freeze the whole toolbar for tens of seconds.
    void refresh();
  };

  const addAllLabsPaperBankroll = async () => {
    if (
      !window.confirm(
        "Add $100.00 to Lab A, B, and C paper balance each?\n\nReturn % and other vs-start KPIs will treat the cumulative basis as your previous basis plus $100 per lab (where a lifetime basis is stored, it is increased by the same amount). Optimizer settings, rules, engines, and trade history are unchanged."
      )
    )
      return;
    setBusy(true);
    try {
      await apiPostJson("/api/config/labs/add-paper-bankroll", {});
      await refresh();
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  };

  const remoteBal = dash?.remote_balance;
  const kalshi = dash?.kalshi as AnyObj | undefined;
  const acctSnap = dash?.account_snapshot as AnyObj | undefined;
  const accountLinked = Boolean(kalshi?.private_ok);

  return (
    <div className={dash ? "page page--bottom-marquee" : "page"}>
      {visibleOptimizerNotifs.length ? (
        <div className="optimizer-toast-stack" aria-live="polite" aria-label="Trade notifications">
          {visibleOptimizerNotifs.map((n) => {
            const tier =
              String(n.tone || "") === "red" || String(n.tone) === "yellow" || String(n.tone) === "green" ? String(n.tone) : "";
            const cardTone = tier ? ` optimizer-toast--${tier}` : "";
            const segs = Array.isArray(n.segments) ? (n.segments as { tier?: string; text?: string }[]) : null;
            const swatch = typeof n.branch_swatch === "string" ? String(n.branch_swatch) : "";
            const branchTip = typeof n.branch_tip === "string" ? String(n.branch_tip) : "";
            return (
              <div key={String(n.id)} className={`panel optimizer-toast${cardTone}`} style={{ padding: "10px 12px" }}>
                <div className="optimizer-toast__body">
                  {swatch ? (
                    <span
                      className="optimizer-toast__branch-dot"
                      style={{ backgroundColor: swatch }}
                      title={branchTip || "Branch"}
                      aria-label={branchTip ? `${branchTip} branch` : "Branch color"}
                    />
                  ) : null}
                  <div className="optimizer-toast__main">
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
                      <div style={{ minWidth: 0 }}>
                        <strong style={{ fontSize: 12 }}>{String(n.title)}</strong>
                        {n.created_at ? (
                          <div className="sub" style={{ fontSize: 10, opacity: 0.88, marginTop: 3 }} title="Toast time (local)">
                            {fmtIsoLocal(String(n.created_at))}
                          </div>
                        ) : null}
                      </div>
                      <button
                        type="button"
                        style={{ padding: "2px 8px", fontSize: 11 }}
                        onClick={() => {
                          const id = String(n.id || "");
                          rememberDismissedTradeToastIds(dismissedTradeToastIdsRef.current, [id]);
                          setOptimizerNotifs((prev) => prev.filter((x) => String(x.id) !== id));
                        }}
                      >
                        ×
                      </button>
                    </div>
                    {segs && segs.length ? (
                      <div style={{ marginTop: 6 }}>
                        {segs.map((s, i) => {
                          const lt = String(s.tier || "neutral");
                          const lineClass =
                            lt === "green" || lt === "yellow" || lt === "red" || lt === "neutral"
                              ? `optimizer-toast__line optimizer-toast__line--${lt}`
                              : "optimizer-toast__line optimizer-toast__line--neutral";
                          return (
                            <div key={i} className={lineClass}>
                              {String(s.text || "")}
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <div className="sub optimizer-toast__line optimizer-toast__line--neutral" style={{ marginTop: 4 }}>
                        {String(n.body)}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
          <div className="optimizer-toast-stack__toolbar">
            <button
              type="button"
              className="optimizer-toast-stack__clear-all"
              onClick={() =>
                setOptimizerNotifs((prev) => {
                  rememberDismissedTradeToastIds(
                    dismissedTradeToastIdsRef.current,
                    prev.map((x) => String(x.id || "")),
                  );
                  return [];
                })
              }
              title="Dismiss every notification in this stack"
            >
              Clear all
            </button>
          </div>
        </div>
      ) : null}
      <div className="top">
        <div className="hero">
          <div className="hero-head">
            <div className="hero-head__main">
              <div className="hero-head__title-stack">
                <h1
                  className="title section-tip"
                  title="15-minute crypto series, rule-based entries. Simulate = paper on the Live branch; Real $ can POST limit orders when the Live engine runs and a rule matches. Sim lab is always paper and uses separate sizing."
                >
                  Chomp's Diner
                </h1>
              </div>
              <button
                type="button"
                className="primary hero-settings-icon-btn"
                style={{ marginLeft: "auto" }}
                aria-label="Open settings"
                title="Settings — rules, engines, lab sizing, Kalshi connection orbs, hero ticker"
                onClick={() => setSettingsOpen(true)}
              >
                ⚙
              </button>
            </div>
            {dash ? (
              <div className="hero-head__snapshot-center">
                <BranchHeroSnapshotHeader
                  dash={dash}
                  cfg={{
                    ...(cfg as AnyObj),
                    hero_marquee_speed_mult: heroMarqueeSpeedMult,
                  }}
                />
              </div>
            ) : null}
          </div>
        </div>
      </div>

      {!dash && err ? <ApiOfflineCallout message={err} /> : null}
      {!dash && !err ? <DashboardLoadingScreen /> : null}
      {dash && err ? (
        <div className="error" title="Last API or validation error from this browser session.">
          {err}
        </div>
      ) : null}

      {dash ? (
        <>
      <KalshiStatusBanner dash={dash} cfg={cfg} />

      <div className="dash-main-4grid">
        <div className="dash-split-row__col dash-split-row__col--metrics dash-split-metrics-stack">
      <div className="dash-split-card">
      <section className="dash-section dash-section--split-card" aria-labelledby="dash-heading-branch-performance">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
          <h2 id="dash-heading-branch-performance" className="dash-section__title" style={{ margin: 0 }}>
            Branch performance
          </h2>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginLeft: "auto" }}>
            <button
              type="button"
              className="chart-tab"
              style={{ padding: "4px 10px" }}
              title={
                "Branch performance is five independent per-branch rollups in SQLite, not one shared wallet. " +
                "The Live, Lab A, Lab B, Lab C, and Lab D tabs each show metrics for that branch only—switching tabs does not re-run " +
                "trades, it just changes which paper bankroll, fees, and open rows are displayed. " +
                "Settled PnL is realized only: it increments when a position is closed in SQLite with a final PnL after Kalshi (or the sim) " +
                "has settled the market; it does not move when MTM swings on an open sim. " +
                "Open / mark P&amp;L (est.) and MTM (est.) describe unrealized exposure from marks on still-open sim rows, using the " +
                "server’s last snapshot. " +
                "In Real $ on Live, Cash and portfolio tiles come from signed Kalshi balance APIs; labs always show paper bankrolls. " +
                "The bottom marquee shows active trades for the branch tab you selected; Apply Lab A to Live still uses settled PnL from the tiles (Lab A must beat B/C/D " +
                "on settled, not on MTM). " +
                "If two tiles seem contradictory, read settled vs open vs bankroll: book steps on fills, MTM wiggles on every poll, settled only " +
                "steps on final resolution."
              }
              onClick={() =>
                setInfoPopup({
                  title: "Branch performance",
                  body: (
                    <div className="dash-section__legend" style={{ fontSize: 13, lineHeight: 1.55 }}>
                      <p>
                        <strong>What you are looking at.</strong> This card is the canonical accounting view for a single
                        engine branch (Live, Lab A, Lab B, Lab C, or Lab D) at the moment of the last{" "}
                        <code>/api/dashboard</code> poll. Each branch has its own paper bankroll (except Live in Real $ mode, where
                        exchange-reported cash partially substitutes), its own list of sim trades, and its own rollups. Nothing here
                        “splits one wallet five ways” — the labs are real parallel experiments, not views on the same ledger.
                      </p>
                      <p>
                        <strong>Settled PnL (the headline realized number).</strong> This is the sum of PnL from rows that the
                        engine has marked closed and settled in SQLite, after Kalshi finalizes the contract in live mode, or
                        when the sim marks resolution in paper mode. It does <em>not</em> include open marks. A common confusion is
                        seeing green MTM and $0 settled: that means the position is open or not yet final in the sim. Only when
                        the row is closed and realized does it flow into this tile and into win/loss, avg hourly, and promote
                        gating. Skim the Activity log to match timestamps to what “settled” means for a given row.
                      </p>
                      <p>
                        <strong>MTM (est.) and open / mark P&amp;L (est.) on paper / lab branches.</strong> MTM is a mark-to-market
                        or blended snapshot total for that branch, derived from the last engine tick and stored metrics.
                        <strong> Open / mark P&amp;L</strong> is the unrealized component: how much the open book is up or down
                        versus bankroll and realized PnL combined. Reconcile mentally as: MTM (est.) &asymp; bankroll + settled +
                        mark on opens; the exact numbers follow backend helpers that may coalesce with cost-basis when marks are
                        missing.
                      </p>
                      <p>
                        <strong>Live in Real $.</strong> When simulation is off and API keys are valid, <strong>Cash (Kalshi)</strong> and{" "}
                        <strong>Portfolio value</strong> come from signed GET portfolio/balance (and related) responses, not from
                        SQLite paper. Bot settled PnL, fees, and “settled (bot)” counts still refer to what this bot’s Live branch
                        has recorded, which should align with exchange fills but is not a duplicate of the exchange P&amp;L report.
                        If keys are wrong or expired, you will see “public data only” in Account; these tiles will show placeholders.
                      </p>
                      <p>
                        <strong>Other tiles on this card.</strong> <strong>Total fees</strong> is modeled Kalshi entry/exit
                        frictions accumulated for the branch. <strong>Avg hourly</strong> divides realized PnL by the wall-clock
                        span of settled activity—useful for intensity, not for annualizing. <strong>Win/loss and %</strong> count
                        settled rows only. <strong>Sim assets</strong> and <strong>committed</strong> describe how many
                        open rows span configured assets and how much premium is locked in the book; high committed% means less
                        headroom for new entries. Cross-check with Holdings under Account and with “Assets to watch” snapshots.
                      </p>
                      <p>
                        <strong>Active trades marquee and Apply Lab A to Live.</strong> The scrolling strip lists open / in-flight
                        trades from the recent feed for whichever branch tab is selected (Live, Lab A–D). Promote gating still uses
                        settled PnL sums from the tiles above, not this strip. “Apply Lab A to Live” copies Lab A’s trading overlays
                        into the Live config only when Lab A’s settled PnL strictly exceeds B, C, and D, plus extra confirmation when
                        not in sim mode. It does <em>not</em> merge bankrolls; it is a config promotion, not a money transfer.
                      </p>
                      <p>
                        <strong>When numbers look “wrong.”</strong> (1) Refresh: metrics come from the last dashboard payload; after
                        a big fill, wait a tick. (2) Branch mismatch: ensure the tab you read matches the Activity log filter. (3) Open
                        sim blocking: a stuck open row can depress new entries—see not-traded and engine skip reasons. (4) Compare to
                        Equity curves (book vs MTM) for the same branch for a time-series check; compare Branch performance to the
                        Optimizer’s Experiments chart for experiment divergence, not for identical dollar values (different
                        baselines/indices). (5) Export or inspect SQLite for forensic reconciliation if the UI and the exchange
                        disagree beyond latency.
                      </p>
                    </div>
                  ),
                })
              }
            >
              Info
            </button>
          </div>
        </div>
        <div className="chart-tabs dash-split-panel__tabs" role="tablist" aria-label="Performance branch tabs">
          {[
            { id: "live", label: "Live" },
            { id: "lab_a", label: "Lab A" },
            { id: "lab_b", label: "Lab B" },
            { id: "lab_c", label: "Lab C" },
              { id: "lab_d", label: "Lab D (Wild)" },
          ].map((t) => (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={perfBranch === t.id}
              className={`chart-tab ${perfBranch === t.id ? "chart-tab--active" : ""}`}
              onClick={() => setPerfBranch(t.id as PerfBranchKey)}
            >
              {t.label}
            </button>
          ))}
        </div>
        <div className="metrics metrics--in-split-card" style={{ marginBottom: 14 }}>
          {(!cfg.simulate && perfBranchMeta.isLive) ? (
            <>
              <MetricTile
                label="Cash (Kalshi)"
                value={
                  perfBranchMeta.metrics.exchange_balance_dollars != null
                    ? fmtMoney(Number(perfBranchMeta.metrics.exchange_balance_dollars))
                    : "—"
                }
                title="Signed GET /portfolio/balance — balance field as dollars (cents ÷ 100)."
              />
              <MetricTile
                label="Portfolio value"
                value={
                  perfBranchMeta.metrics.exchange_portfolio_value_dollars != null
                    ? fmtMoney(Number(perfBranchMeta.metrics.exchange_portfolio_value_dollars))
                    : "—"
                }
                title="Portfolio value from signed balance response when provided."
              />
            </>
          ) : (
            <>
              <MetricTile
                label={`${perfBranchMeta.label} bankroll (start)`}
                value={fmtMoney(Number(perfBranchMeta.metrics.paper_start_dollars ?? 0))}
                title="Starting/cumulative paper basis used for return percentages."
              />
              <MetricTile
                label={`${perfBranchMeta.label} MTM (est.)`}
                value={fmtMoney(dashboardMtmDollars(perfBranchMeta.metrics))}
                title="Mark-to-market from latest snapshot; falls back to cost-basis equity when needed."
                sub={`Return vs start ${fmtPct(dashboardMtmReturnPct(perfBranchMeta.metrics))} · chart last ${
                  dashboardChartLastMtmOrEq(perfBranchMeta.metrics) != null
                    ? fmtMoney(Number(dashboardChartLastMtmOrEq(perfBranchMeta.metrics)))
                    : "—"
                }`}
                valueTone={metricEquityVsBankroll(dashboardMtmDollars(perfBranchMeta.metrics), perfBranchMeta.metrics.paper_start_dollars)}
                subTone={metricSignedTone(dashboardMtmReturnPct(perfBranchMeta.metrics))}
              />
            </>
          )}
          {(!cfg.simulate && perfBranchMeta.isLive) ? null : (() => {
            const u = paperUnrealizedPnlDollars(perfBranchMeta.metrics);
            return (
            <MetricTile
              label={`${perfBranchMeta.label} open / mark P&L (est.)`}
              value={u == null || !Number.isFinite(u) ? "—" : fmtMoney(u)}
              title="MTM (est.) minus bankroll minus settled PnL — unrealized: open sims and marks, not in realized PnL until settlement."
              valueTone={metricSignedTone(u ?? 0)}
            />
            );
          })()}
          <MetricTile
            label={perfBranchMeta.isLive && !cfg.simulate ? "Bot settled PnL" : `${perfBranchMeta.label} settled PnL`}
            value={fmtMoney(Number(perfBranchMeta.metrics.total_pnl_dollars || 0))}
            title="Realized PnL only: sum from settled trades in this branch. Unchanged until a contract finalizes in SQLite."
            sub={!perfBranchMeta.isLive || cfg.simulate ? `${fmtPct(perfBranchMeta.metrics.realized_pnl_pct_of_start)} of ${perfBranchMeta.bankNoun}` : undefined}
            valueTone={metricSignedTone(perfBranchMeta.metrics.total_pnl_dollars)}
            subTone={metricSignedTone(perfBranchMeta.metrics.realized_pnl_pct_of_start)}
          />
          <MetricTile
            label={perfBranchMeta.isLive && !cfg.simulate ? "Total Kalshi fees" : `${perfBranchMeta.label} fees`}
            value={fmtMoney(Number(perfBranchMeta.metrics.total_kalshi_fees_dollars || 0))}
            title="Modeled entry + exit fees accumulated for this branch."
            valueTone="neg"
          />
          <MetricTile
            label={perfBranchMeta.isLive && !cfg.simulate ? "Avg hourly (bot)" : `${perfBranchMeta.label} avg hourly`}
            value={fmtMoney(Number(perfBranchMeta.metrics.avg_hourly_pnl_dollars || 0))}
            title="Realized PnL divided by elapsed hours spanned by settled trades."
            valueTone={metricSignedTone(perfBranchMeta.metrics.avg_hourly_pnl_dollars)}
          />
          <MetricTile
            label={perfBranchMeta.isLive && !cfg.simulate ? "Settled (bot)" : `${perfBranchMeta.label} settled`}
            value={String(perfBranchMeta.metrics.settled_trades ?? 0)}
            title="Count of settled trades in this branch."
          />
          <WinLossRecordTile label={`${perfBranchMeta.label} win / loss · %`} metrics={perfBranchMeta.metrics} />
          <MetricTile
            label={`${perfBranchMeta.label} avg / settled`}
            value={
              perfBranchMeta.metrics.avg_realized_per_settled_dollars != null
                ? fmtMoney(Number(perfBranchMeta.metrics.avg_realized_per_settled_dollars))
                : "—"
            }
            title="Mean realized dollars per settled trade."
            valueTone={metricSignedTone(perfBranchMeta.metrics.avg_realized_per_settled_dollars)}
          />
          <MetricTile
            label={`${perfBranchMeta.label} · sim assets`}
            value={String(perfBranchMeta.metrics.open_sim_trades ?? 0)}
            title="Holdings: configured assets with any open sim in this branch (one per asset row; a cell can list several market tickers)."
          />
          <MetricTile
            label={`${perfBranchMeta.label} committed`}
            value={fmtMoney(Number(perfBranchMeta.metrics.open_sim_committed_dollars || 0))}
            title="Premium tied up in open positions."
            sub={fmtPct(perfBranchMeta.metrics.committed_pct_of_start) + ` of ${perfBranchMeta.bankNoun}`}
            subTone={metricSignedTone(-Number(perfBranchMeta.metrics.committed_pct_of_start))}
          />
        </div>
        <div className="branch-performance-bottom">
          <BranchPerfActiveTradesMarquee branchLabel={perfBranchMeta.label} activeRows={activeTradesForPerfBranch} />
          <button
            type="button"
            className="primary"
            disabled={busy || !canPromoteLabAToLive}
            title="Copies Lab A overlays (rules, window, bet fraction, filters, fees, assets) to top-level Live when Lab A settled PnL exceeds B/C/D. Extra confirmation when Live is in Real $ mode."
            onClick={() => void promoteLabAToLive()}
          >
            Apply Lab A to Live
          </button>
        </div>
      </section>
      </div>

      <div className="dash-split-card dash-optimizer-panel">
        <section className="dash-section dash-section--split-card" aria-labelledby="dash-heading-optimizer">
          <div className="branch-brain-inline">
            <div className="branch-brain-inline__head">
              <h2 id="dash-heading-optimizer" className="dash-section__title" style={{ margin: 0 }}>
                Optimizer
              </h2>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginLeft: "auto" }}>
                <button
                  type="button"
                  className="primary"
                  disabled={busy}
                  title="Open optimizer report: next movement vs gates, schedule, pulse, rollups, and settlements."
                  onClick={openOptimizerReportOverlay}
                >
                  report
                </button>
                <button
                  type="button"
                  className="chart-tab"
                  style={{ padding: "4px 10px" }}
                  title={
                    "Optimizer: Experiments multi-line chart = indexed MTM (or similar) for Live + Lab A–D from a shared window, for comparing paths; " +
                    "it does not submit orders. Lab pulse = scrolling digest of the last engine tick (fills, skips, minutes-to-close, rule hints). " +
                    "The report button opens a full overlay (schedule, next movement, rollups, raw pulse). Adaptive tuning on the server may adjust " +
                    "Lab A parameters from settled paper history with guardrails; B/C/D stay reference. If pulse is empty, check engine on/off and " +
                    "API health in Account, not just this card."
                  }
                  onClick={() => setInfoPopup({ title: "Optimizer", body: optimizerBriefInfoBody() })}
                >
                  Info
                </button>
              </div>
            </div>
            <BranchOptimizerVisualizer
              labThoughts={(dash?.lab_thoughts ?? dash?.optimizer_activity?.lab_thoughts) as AnyObj | undefined}
              lineRows={branchBrainLineRows}
              lineRevision={equityOverlayRevision}
            />
          </div>
        </section>
      </div>

        </div>

        <div className="dash-split-row__col dash-split-row__col--equity dash-split-card dash-equity-panel">
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
            <h2
              id="dash-heading-equity-curves"
              className="dash-section__title dash-equity-panel__title"
              style={{ margin: 0 }}
              title="Solid = book value (cost basis from rollups). Dashed = current worth (MTM). Intraday adds a trailing point on each dashboard refresh from latest metrics; paper MTM is recomputed on the server from current Kalshi mids between snapshot writes."
            >
              Equity curves
            </h2>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginLeft: "auto" }}>
              <button
                type="button"
                className="chart-tab"
                title="Open combined comparison popup with branch toggles."
                onClick={() => setEquityCompareOpen(true)}
              >
                Compare
              </button>
              <button
                type="button"
                className="chart-tab"
                style={{ padding: "4px 10px" }}
                title={
                  "Equity: five small-multiple charts (Live + Lab A–D), each with solid = book (cost-ledger) and dashed = mark-to-market. " +
                  "Book steps only on ledger events; dashed updates every tick with market mids so it can wiggle while solid is flat. " +
                  "Time-scale tabs re-bucket the same stored snapshots: Intraday = last 400 points in time order; D/W/M/Y = last snapshot " +
                  "per calendar bucket (day/week start UTC/month/year). Use Compare to overlay branches in one frame. " +
                  "A jump in dashed without solid moving usually means marks moved, not a fill; a step in solid is a fill, exit, or settlement."
                }
                onClick={() =>
                  setInfoPopup({
                    title: "Equity curves",
                    body: (
                      <div className="dash-section__legend dash-equity-panel__legend" style={{ fontSize: 13, lineHeight: 1.55 }}>
                        <p>
                          <strong>What each chart shows.</strong> You get <strong>five</strong> independent panels, one per branch. Each
                          panel has two series over time: a <strong>solid</strong> line (book or cost-basis / cash-ledger path) and a{" "}
                          <strong>dashed</strong> line (mark-to-market “total worth” that includes the fair value of open positions on top
                          of the same ledger). All branches use the <em>same</em> time-scale control so you can line up “what the market
                          did to my marks” (dashed) against “what my ledger actually recorded” (solid). This is the right place to spot
                          drift, stuck marks, or one lab taking different fills than another.
                        </p>
                        <p>
                          <strong>Book (solid), precisely.</strong> Book is built from: starting paper bankroll (for labs) or
                          reconciled start for Live, plus <strong>realized</strong> PnL from settled / closed rows, <strong>minus</strong>{" "}
                          premium and fees still committed in open sim rows (or Live analogs) until those rows close. So when you <em>open</em> a
                          new sim, the solid line typically <strong>steps down</strong> by the price you paid; it does <em>not</em> get a
                          “free” mark-to-market offset on that same event—unrealized PnL is the dashed line’s job. When you exit or settle, solid
                          steps by the full realized PnL including fees. If you see a flat solid and a wiggly dashed, that is usually open risk
                          being marked; if both jump together, a settlement or large exit probably landed.
                        </p>
                        <p>
                          <strong>MTM (dashed), precisely.</strong> Dashed = book-ledger <strong>plus</strong> the current fair value
                          (mid-based in paper, same signal chain as the engine’s last tick) of everything still open. It should hug book when
                          there is no open risk. After an open, dashed may sit near the pre-open level if the position is near cost, while
                          solid is lower—<strong>that gap is the premium you paid, not a bug</strong>. Intraday mode may append a trailing point
                          on every dashboard refresh so the tail tracks “right now” more closely than a sparse historical series.
                        </p>
                        <p>
                          <strong>Time-scale tabs (Intraday, D, W, M, Y).</strong> All four labels apply to <em>all</em> five charts.{" "}
                          <strong>Intraday</strong> plots raw snapshot order (up to the last 400 points) for responsive debugging. <strong>
                            D / W / M / Y
                          </strong>{" "}
                          collapse to the last point in each UTC calendar day, week (Monday start), month, or year so you can de-noise. Labels on
                          day view use the snapshot’s <em>local</em> calendar date, not a synthetic “end of day” you might expect from
                          equities—this is a Kalshi 24/7 world clock.
                        </p>
                        <p>
                          <strong>Compare (separate button).</strong> That overlay puts multiple branch curves in one frame with toggles so you
                          can eyeball <em>shape</em> and divergence, not to sum dollars (each bankroll differs). Use it when Optimizer
                          “Experiments” and these equity charts disagree on <em>direction</em>—one might be an indexed or shorter window, the
                          other raw dollars over long history.
                        </p>
                        <p>
                          <strong>Failure modes to read correctly.</strong> (1) Flatlines everywhere: no snapshots yet, engines off, or
                          no trades in that branch. (2) Dashed &gt; solid persistently: material open positions marked above cost, or
                          stale mark not caught up. (3) Dashed &lt; solid: marks below cost, or a bug in mid; compare “Assets to watch” for
                          broken quotes. (4) Mismatch with Branch performance: performance tiles are one instant; these charts are
                          time-series—always compare the same branch tab and the same time window mentally.
                        </p>
                        <p>
                          <strong>How to work with the rest of the UI.</strong> After a trade, expect dashed to move first, solid to move on
                          fill/settlement. Use Activity log for the exact event order. Use Account holdings for per-asset exposure, not
                          the chart’s y-axis, when reconciling. Use Branch performance for headline settled/realized numbers in dollars;
                          use Equity curves for path and stress shape.
                        </p>
                      </div>
                    ),
                  })
                }
              >
                Info
              </button>
            </div>
          </div>
          <div className="chart-tabs dash-split-panel__tabs dash-equity-panel__tabs" role="tablist" aria-label="Equity time scale (all branches)">
            {(
              [
                ["intraday", "Intraday", "Raw snapshots in time order (last 400 points)."],
                ["dd", "D / D", "Last snapshot per UTC calendar day; label uses that snapshot’s local date."],
                ["ww", "W / W", "Last snapshot per week bucket (Monday UTC week start)."],
                ["mm", "M / M", "Last snapshot per UTC calendar month."],
                ["yy", "Y / Y", "Last snapshot per UTC calendar year."],
              ] as const
            ).map(([id, label, tip]) => (
              <button
                key={id}
                type="button"
                role="tab"
                aria-selected={equityGranularity === id}
                className={`chart-tab ${equityGranularity === id ? "chart-tab--active" : ""}`}
                title={tip}
                onClick={() => setEquityGranularity(id)}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="dash-equity-charts">
            <div className="dash-equity-chart-block">
              <h3 className="dash-equity-branch-head section-tip" title={`${activityBranchTabLabel("live")}: book value (solid) vs current worth / MTM (dashed).`}>
                {activityBranchTabLabel("live")}
              </h3>
              <div className="chart chart--equity-stack" title={`${activityBranchTabLabel("live")} equity over time.`}>
                <EquityDualLineChart data={chartData} equityStroke="#6ee7ff" mtmStroke="#38bdf8" revision={`${equityChartRevision(snaps, chartData, metrics)}|tick=${String(dash?.engine?.live?.last_tick_at || "")}`} />
              </div>
            </div>
            <div className="dash-equity-chart-block">
              <h3 className="dash-equity-branch-head section-tip" title={`${activityBranchTabLabel("lab_a")}: book value (solid) vs current worth (dashed).`}>
                {activityBranchTabLabel("lab_a")}
              </h3>
              <div className="chart chart--equity-stack" title={`${activityBranchTabLabel("lab_a")} equity over time.`}>
                <EquityDualLineChart data={chartDataLabA} equityStroke="#a78bfa" mtmStroke="#c4b5fd" revision={`${equityChartRevision(equitySnapsLabA, chartDataLabA, metricsLabA)}|tick=${String(engineLabA?.last_tick_at || "")}`} />
              </div>
            </div>
            <div className="dash-equity-chart-block">
              <h3 className="dash-equity-branch-head section-tip" title={`${activityBranchTabLabel("lab_b")}: book value (solid) vs current worth (dashed).`}>
                {activityBranchTabLabel("lab_b")}
              </h3>
              <div className="chart chart--equity-stack" title={`${activityBranchTabLabel("lab_b")} equity over time.`}>
                <EquityDualLineChart data={chartDataLabB} equityStroke="#f59e0b" mtmStroke="#fcd34d" revision={`${equityChartRevision(equitySnapsLabB, chartDataLabB, metricsLabB)}|tick=${String(engineLabB?.last_tick_at || "")}`} />
              </div>
            </div>
            <div className="dash-equity-chart-block">
              <h3 className="dash-equity-branch-head section-tip" title={`${activityBranchTabLabel("lab_c")}: book value (solid) vs current worth (dashed).`}>
                {activityBranchTabLabel("lab_c")}
              </h3>
              <div className="chart chart--equity-stack" title={`${activityBranchTabLabel("lab_c")} equity over time.`}>
                <EquityDualLineChart data={chartDataLabC} equityStroke="#f472b6" mtmStroke="#fbcfe8" revision={`${equityChartRevision(equitySnapsLabC, chartDataLabC, metricsLabC)}|tick=${String(engineLabC?.last_tick_at || "")}`} />
              </div>
            </div>
            <div className="dash-equity-chart-block">
              <h3 className="dash-equity-branch-head section-tip" title={`${activityBranchTabLabel("lab_d")}: book value (solid) vs current worth (dashed).`}>
                {activityBranchTabLabel("lab_d")}
              </h3>
              <div className="chart chart--equity-stack" title={`${activityBranchTabLabel("lab_d")} equity over time.`}>
                <EquityDualLineChart data={chartDataLabD} equityStroke="#fca5a5" mtmStroke="#fecaca" revision={`${equityChartRevision(equitySnapsLabD, chartDataLabD, metricsLabD)}|tick=${String(engineLabD?.last_tick_at || "")}`} />
              </div>
            </div>
          </div>
        </div>

        <div className="panel dashboard-grid-panel dashboard-grid-panel--assets">
          <div className="dashboard-grid-panel__head">
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, width: "100%" }}>
              <h2
                id="dash-heading-assets"
                className="dash-section__title dashboard-grid-panel__title"
                title="Snapshots per series (BTC first, ETH second, then A-Z). Which series the engine scans is controlled by each asset's enabled flag in bot config."
              >
                Assets to watch
              </h2>
              <button
                type="button"
                className="chart-tab"
                style={{ padding: "4px 10px" }}
                title={
                  "Per-asset engine snapshot cards: Live vs Lab A–D select which branch’s last tick view you read; config is unchanged. " +
                  "Rows are ordered (e.g. BTC before ETH, then A–Z). Each card shows what the scanner saw for that series: implied, " +
                  "window, target, and open-sim hints. If “No snapshot”, the engine may be off, the series has no active 15m row yet, " +
                  "or Kalshi returned no book. On sandbox/draft hosts, TBD or 0.00 bid/ask often means missing books, not a bug in your " +
                  "rules. Enable/disable assets in Settings; this panel is read-only telemetry."
                }
                onClick={() =>
                  setInfoPopup({
                    title: "Assets to watch",
                    body: (
                      <div className="dash-section__legend" style={{ fontSize: 13, lineHeight: 1.55 }}>
                        <p>
                          <strong>Purpose.</strong> This grid is a <em>telemetry heat map</em> of what the engine last knew about each
                          configured asset (BTC, ETH, …) for a <em>single branch at a time</em> (Live, Lab A, Lab B, Lab C, Lab D). It
                          answers: “Is there a current 15-minute (or configured) market row? What were the mids or implieds? Are we
                          blocked from new entries in this series because of an open sim?” It does <strong>not</strong> edit rules;
                          it reflects the product of config + engine + Kalshi feed.
                        </p>
                        <p>
                          <strong>Branch tabs vs config.</strong> Switching Live / Lab A / Lab B / Lab C / Lab D only swaps which
                          branch’s <code>asset_snapshots</code> (or equivalent) object the UI reads from the dashboard payload. Your
                          SQLite config and environment files are untouched. If two branches show different numbers, that is expected:
                          they may have different paper positions, different rule packs, or different last-tick times.
                        </p>
                        <p>
                          <strong>Which assets appear.</strong> Only assets present in bot config with reasonable keys are listed. Order
                          is stable (for example headline crypto first, then alphabetical). If you add a new asset in Settings, you may
                          need a save + engine tick before a card appears. An asset with <code>enabled: false</code> is typically omitted
                          or shown as inactive—check Settings for the authoritative flag; the UI may still show a stub for visibility.
                        </p>
                        <p>
                          <strong>“No snapshot” and empty fields.</strong> Common causes: branch engine toggled off for that run; Kalshi
                          API rate limit or outage; no market row in the series for the current clock; first tick after startup not
                          completed yet. Distinguish “no data yet” from “data is zero”—read the Engine section under Account for{" "}
                          <code>last_tick_at</code> and error strings. If <code>last_tick</code> is fresh but the card is empty, the
                          series might not have a tradable row in this environment.
                        </p>
                        <p>
                          <strong>Non-production and draft Kalshi hosts.</strong> Sandbox and internal hosts often show{" "}
                          <code>Target price: TBD</code>, <code>0.00</code> bid/ask, or obviously stale books for many 15m contracts. That
                          is a feed limitation, not your filter string. Do not tune rules against those numbers; use production-like
                          markets or verify on the official site. The yellow “non-production feed” banner (if present) calls this out.
                        </p>
                        <p>
                          <strong>How this ties to trades and skips.</strong> If a card shows an open sim or a series lock, cross-check
                          Activity log and “Bets not traded” for <code>series_has_open_sim</code> or similar. If implieds look
                          nonsensical (e.g. 0% or 100% with no book), the engine may still skip entries for safety. Use Optimizer Lab
                          pulse for the same tick’s narrative; use Branch performance for money impact, not this panel.
                        </p>
                        <p>
                          <strong>Operational checklist.</strong> (1) Confirm each engine is on for the branch you are reading. (2) Confirm
                          each asset you care about is enabled. (3) If only one branch is stale, restart or inspect that branch’s engine
                          state in the dashboard JSON. (4) If all branches are stale, the backend or Kalshi connectivity is the prime
                          suspect before you change strategy.
                        </p>
                      </div>
                    ),
                  })
                }
              >
                Info
              </button>
            </div>
            <div
              className="chart-tabs dashboard-grid-panel__tabs"
              role="tablist"
              aria-label="Asset snapshot branch"
              style={{ width: "100%" }}
            >
              <button
                type="button"
                role="tab"
                aria-selected={assetWatchLab === "live"}
                className={`chart-tab ${assetWatchLab === "live" ? "chart-tab--active" : ""}`}
                title="Per-asset engine snapshot for the Live branch."
                onClick={() => setAssetWatchLab("live")}
              >
                Live
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={assetWatchLab === "a"}
                className={`chart-tab ${assetWatchLab === "a" ? "chart-tab--active" : ""}`}
                title="Per-asset engine snapshot for Lab A (same branch as legacy sim_lab in SQLite)."
                onClick={() => setAssetWatchLab("a")}
              >
                Lab A
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={assetWatchLab === "b"}
                className={`chart-tab ${assetWatchLab === "b" ? "chart-tab--active" : ""}`}
                title="Per-asset engine snapshot for Lab B (conservative reference)."
                onClick={() => setAssetWatchLab("b")}
              >
                Lab B
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={assetWatchLab === "c"}
                className={`chart-tab ${assetWatchLab === "c" ? "chart-tab--active" : ""}`}
                title="Per-asset engine snapshot for Lab C (aggressive reference)."
                onClick={() => setAssetWatchLab("c")}
              >
                Lab C
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={assetWatchLab === "d"}
                className={`chart-tab ${assetWatchLab === "d" ? "chart-tab--active" : ""}`}
                title="Per-asset engine snapshot for Lab D (wild reference)."
                onClick={() => setAssetWatchLab("d")}
              >
                Lab D
              </button>
            </div>
          </div>
          <div className="dashboard-grid-panel__body dashboard-grid-panel__body--assets">
          {kalshiIsNonProd(kalshi?.env) ? (
            <div className="sub" style={{ marginBottom: 8, fontSize: 12 }} title="Non-production feed detected. Use Info for full notes.">
              Non-production host detected: <code>{String(kalshi?.env || "—")}</code>.
            </div>
          ) : null}
          {Object.keys(assets).length === 0 ? (
            <div className="sub" title="Add assets under Settings → JSON or defaults in backend config.">
              No assets configured.
            </div>
          ) : (
            <div className="asset-watch-scroll">
              {(() => {
                const entries = orderedAssetEntries(assets as AnyObj);
                const enriched = entries.map(([id, a], idx) => {
                  const posRow = (acctSnap?.position_by_asset as AnyObj | undefined)?.[id] as AnyObj | undefined;
                  const openRowsTab = dedupeAssetWatchOpenRowsByTicker(assetWatchOpenRowsForTab(posRow, assetWatchLab));
                  const headlineSnap =
                    assetWatchLab === "live"
                      ? (engineSnapsLive[id] as AnyObj | undefined)
                      : assetWatchLab === "a"
                        ? (engineSnapsLabA[id] as AnyObj | undefined)
                        : assetWatchLab === "b"
                          ? (engineSnapsLabB[id] as AnyObj | undefined)
                          : assetWatchLab === "c"
                            ? (engineSnapsLabC[id] as AnyObj | undefined)
                            : (engineSnapsLabD[id] as AnyObj | undefined);
                  const implied = Number(headlineSnap?.implied_prob);
                  const impliedMove = Number.isFinite(implied) ? Math.abs(implied - 0.5) : 0;
                  const rulesCount = Array.isArray(headlineSnap?.rules_matched) ? headlineSnap.rules_matched.length : 0;
                  const movementScore = impliedMove + (rulesCount > 0 ? 0.15 : 0) + (headlineSnap?.has_orderbook ? 0.05 : 0);
                  return { id, a, idx, posRow, openRowsTab, headlineSnap, hasExposureTab: openRowsTab.length > 0, movementScore };
                });
                enriched.sort((x, y) => {
                  if (x.hasExposureTab !== y.hasExposureTab) return x.hasExposureTab ? -1 : 1;
                  if (y.movementScore !== x.movementScore) return y.movementScore - x.movementScore;
                  return x.idx - y.idx;
                });
                return enriched.map(({ id, a, posRow, openRowsTab, headlineSnap, hasExposureTab }) => {
                  const exposureLabelsTab = exposureLabelsForAssetWatchTab(posRow, assetWatchLab);
                  return (
                    <div
                      key={id}
                      className={hasExposureTab ? "asset-watch-row asset-watch-row--invested" : "asset-watch-row"}
                      title={
                        hasExposureTab
                          ? `Open exposure for the “${assetWatchLab === "live" ? "Live" : assetWatchLab === "a" ? "Lab A" : assetWatchLab === "b" ? "Lab B" : assetWatchLab === "c" ? "Lab C" : "Lab D"}” tab: ${exposureLabelsTab.join(", ")}. Other branches may still be flat.`
                          : `Asset ${id}: series ${String(a.series_ticker || "")}.`
                      }
                    >
                      <div
                        className="asset-watch-heading"
                        style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "6px 10px", marginBottom: 4 }}
                        title={`${String(a.series_ticker || "")} · engine scans this series only if enabled in Settings.`}
                      >
                        <strong title="Display label for this asset.">{a.label || id}</strong>
                        <span style={{ color: "var(--muted)" }}>·</span>
                        <code title="Kalshi series ticker for open markets.">{a.series_ticker}</code>
                        {a.enabled === false ? (
                          <span
                            className="sub"
                            style={{ fontSize: 11, color: "#ffc878" }}
                            title="Disabled in config — set assets.{id}.enabled true via PUT /api/config or edit backend bot_config JSON."
                          >
                            (engine off for this series)
                          </span>
                        ) : null}
                        {hasExposureTab ? (
                          <span
                            className="asset-watch-exposure-badge"
                            title={`Open in this tab only: ${exposureLabelsTab.join(" · ")}.`}
                          >
                            Open ({assetWatchLab === "live" ? "Live" : assetWatchLab === "a" ? "Lab A" : assetWatchLab === "b" ? "Lab B" : assetWatchLab === "c" ? "Lab C" : "Lab D"}):{" "}
                            {exposureLabelsTab.join(" · ")}
                          </span>
                        ) : null}
                      </div>
                      <div
                        className="sub"
                        style={{
                          marginLeft: 28,
                          marginTop: 6,
                          fontSize: 12,
                          lineHeight: 1.45,
                        }}
                      >
                        {assetWatchLab === "live" ? (
                          <EngineAssetSnapBlock
                            label="Live"
                            snap={engineSnapsLive[id]}
                            lastTick={dash?.engine?.live?.last_tick_at}
                            engineOn={Boolean(cfg.engine_running)}
                          />
                        ) : assetWatchLab === "a" ? (
                          labABranchEngineOn ? (
                            <EngineAssetSnapBlock
                              label="Sim · Lab A"
                              snap={engineSnapsLabA[id]}
                              lastTick={engineLabA?.last_tick_at}
                              engineOn={labABranchEngineOn}
                            />
                          ) : (
                            <div className="sub" style={{ fontSize: 12 }} title="Turn Lab A on in the toolbar to populate lab snapshots.">
                              <strong>Sim · Lab A</strong> — engine off (no snapshot for this series).
                            </div>
                          )
                        ) : assetWatchLab === "b" ? (
                          labBBranchEngineOn ? (
                            <EngineAssetSnapBlock
                              label="Sim · Lab B"
                              snap={engineSnapsLabB[id]}
                              lastTick={engineLabB?.last_tick_at}
                              engineOn={labBBranchEngineOn}
                            />
                          ) : (
                            <div className="sub" style={{ fontSize: 12 }} title="Turn Lab B on in the toolbar to populate lab snapshots.">
                              <strong>Sim · Lab B</strong> — engine off (no snapshot for this series).
                            </div>
                          )
                        ) : assetWatchLab === "c" ? (
                          labCBranchEngineOn ? (
                            <EngineAssetSnapBlock
                              label="Sim · Lab C"
                              snap={engineSnapsLabC[id]}
                              lastTick={engineLabC?.last_tick_at}
                              engineOn={labCBranchEngineOn}
                            />
                          ) : (
                            <div className="sub" style={{ fontSize: 12 }} title="Turn Lab C on in the toolbar to populate lab snapshots.">
                              <strong>Sim · Lab C</strong> — engine off (no snapshot for this series).
                            </div>
                          )
                        ) : assetWatchLab === "d" ? (
                          labDBranchEngineOn ? (
                            <EngineAssetSnapBlock
                              label="Sim · Lab D"
                              snap={engineSnapsLabD[id]}
                              lastTick={engineLabD?.last_tick_at}
                              engineOn={labDBranchEngineOn}
                            />
                          ) : (
                            <div className="sub" style={{ fontSize: 12 }} title="Turn Lab D on in the toolbar to populate lab snapshots.">
                              <strong>Sim · Lab D</strong> — engine off (no snapshot for this series).
                            </div>
                          )
                        ) : null}
                        <OpenExposureLinesForWatch
                          rows={openRowsTab}
                          headlineSnap={headlineSnap}
                          seriesTicker={String(a.series_ticker || "")}
                        />
                      </div>
                    </div>
                  );
                });
              })()}
            </div>
          )}
          </div>

        </div>

        <div className="panel dashboard-grid-panel dashboard-grid-panel--account">
          <div className="dashboard-grid-panel__head">
            <h2
              id="dash-heading-account"
              className="dash-section__title dashboard-grid-panel__title"
              title={
                accountLinked
                  ? "Balance/positions from signed Kalshi portfolio reads. Writes: Live branch POSTs orders only in Real $ mode when a rule fires."
                  : "No signed portfolio access - markets and engine use public Kalshi data; sim trades stay in local SQLite."
              }
            >
              Account
            </h2>
            <div className="dashboard-grid-panel__meta" aria-label="Kalshi link status" style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
              <span
                className={`dashboard-grid-panel__badge${accountLinked ? " dashboard-grid-panel__badge--ok" : ""}`}
                title={accountLinked ? "Signed portfolio reads enabled for this backend." : "No exchange credentials on this backend; public market data only."}
              >
                {accountLinked ? "Kalshi linked" : "Public data only"}
              </span>
              <button
                type="button"
                className="chart-tab"
                style={{ padding: "4px 10px" }}
                title={
                  "Account: optional signed Kalshi balance/positions when API keys are set; otherwise public market data only. " +
                  "Holdings table merges per-asset rows: exchange-open columns vs per-branch sim-open columns. Paper and live can diverge " +
                  "by design. Engine status below is polled from the dashboard, not the exchange. " +
                  "Set KALSHI_API_KEY_ID and private key in .env, restart the API, reload. " +
                  "Glossary: market lines = distinct tickers in a cell; contracts = summed YES/NO size on those tickers."
                }
                onClick={() =>
                  setInfoPopup({
                    title: "Account and holdings",
                    body: (
                      <div className="dash-section__legend" style={{ fontSize: 13, lineHeight: 1.55 }}>
                        <p>
                          <strong>What this block is for.</strong> The Account area is the bridge between <em>this bot’s SQLite
                          universe</em> and <em>Kalshi’s exchange state</em> when (and only when) you have provided API credentials on
                          the backend. It shows: aggregate balance and portfolio value (in cents) from signed endpoints, counts of
                          open positions and resting orders, and a <strong>per-asset</strong> table that lines up your configured
                          assets (BTC, ETH, …) with (a) what Kalshi says you hold and (b) what each branch’s sim engine thinks is open
                          in SQLite.
                        </p>
                        <p>
                          <strong>“Kalshi linked” vs “Public data only”.</strong> The badge is an integration summary, not a strategy
                          toggle. <strong>Linked</strong> means the backend completed at least one successful private read recently
                          enough that the UI can show exchange-backed numbers. <strong>Public data only</strong> means you still get
                          market discovery and the bot can run paper, but you will not see real balance, real fills in Live without
                          keys, and some tiles (Cash on Branch performance) may stay empty. Never assume paper PnL equals your actual
                          exchange PnL when the badge is not linked.
                        </p>
                        <p>
                          <strong>Per-branch holdings columns.</strong> The Live, Lab A, Lab B, Lab C, and Lab D tabs switch which
                          branch’s <code>bot_sim_open_*</code> arrays feed the “sim” side of the table. Live shows{" "}
                          <code>bot_sim_open_live</code>; Lab A also accepts legacy <code>bot_sim_open_lab</code> for older rows. Each
                          cell summarizes many tickers into: <em>market lines</em> (count of distinct market_ids / tickers with
                          exposure) and a short text of tickers, plus <em>contracts</em> (summed size in exchange units, not
                          “number of markets”). If Kalshi and sim disagree, the engine may not have written the close yet, you may
                          be looking at a different branch, or a manual trade happened outside the bot.
                        </p>
                        <p>
                          <strong>When balance is missing or partial.</strong> Set <code>KALSHI_API_KEY_ID</code> and the RSA private
                          key (path or PEM) in the backend <code>.env</code> as documented in the repo, restart the API process, and
                          hard-reload the dashboard. If you see a <code>private_error</code> line, read it literally—signature/clock
                          issues and rate limits are common. The UI will surface whatever error string the backend last captured; open
                          server logs for stack traces. Remember: the frontend never stores your private key; only the server process
                          you control should.
                        </p>
                        <p>
                          <strong>How this pairs with the Engine strip below.</strong> The Engine subsection shows, for the{" "}
                          <em>same</em> branch tab, whether that branch’s engine loop is on, last tick time, and scan breadth. A
                          healthy <code>last_tick_at</code> with linked Kalshi and strange holdings usually means a logic issue; a very
                          old tick means you are staring at static UI while the world moved—refresh dashboard or restart the process
                          on the host. Engine “simulate orders” on Live in sim mode is expected; in Real $ it should reflect
                          real posting when rules fire.
                        </p>
                        <p>
                          <strong>Privacy and scope.</strong> All numbers here are whatever your backend fetches. If you self-host, you
                          are the custodian. If you use a shared binary, know that the same data appears in logs; treat API keys and
                          screenshots as secret. The Activity log and trade JSONL on disk are separate but related—delete old logs on
                          shared machines.
                        </p>
                        <p>
                          <strong>Reconciliation workflow.</strong> (1) Confirm badge linked. (2) Match one open position in Kalshi UI
                          to a row in this table. (3) For each branch, check sim column vs Activity log. (4) If Branch performance PnL
                          disagrees, trace settled trades, not this snapshot alone—this is exposure, not full PnL.
                        </p>
                      </div>
                    ),
                  })
                }
              >
                Info
              </button>
            </div>
          </div>
          <div className="dashboard-grid-panel__body dashboard-grid-panel__body--assets">
          {!remoteBal ? (
            <div
              className="sub"
              title="Configure KALSHI_API_KEY_ID and private key in repo .env, restart API, reload dashboard."
            >
              {kalshi?.public_ok ? "No linked Kalshi account on this backend." : "Balance unavailable right now."}
              {kalshi?.private_error ? (
                <div className="sub" style={{ marginTop: 10, fontSize: 12, opacity: 0.9 }} title="Last private API error from the backend.">
                  Detail: {String(kalshi.private_error)}
                </div>
              ) : null}
            </div>
          ) : (
            <div className="sub" title="Signed-in portfolio snapshot from Kalshi.">
              <div title="Account balance in cents from Kalshi balance API.">
                Balance (cents): <code title="Raw balance integer from Kalshi.">{String(remoteBal.balance ?? "")}</code>
              </div>
              {remoteBal.portfolio_value != null ? (
                <div style={{ marginTop: 8 }} title="Optional portfolio value field when returned by API.">
                  Portfolio value (cents):{" "}
                  <code title="Portfolio value cents.">{String(remoteBal.portfolio_value)}</code>
                </div>
              ) : null}
              <div style={{ marginTop: 12, display: "flex", gap: "14px", flexWrap: "wrap" }} title="Counts from portfolio snapshot.">
                <span className="pill" title="Open positions reported by Kalshi.">
                  Positions <strong title="Position count.">{String(acctSnap?.position_count ?? "—")}</strong>
                </span>
                <span className="pill" title="Resting orders on the exchange.">
                  Resting orders <strong title="Order count.">{String(acctSnap?.resting_order_count ?? "—")}</strong>
                </span>
              </div>
              {acctSnap?.portfolio_error && remoteBal ? (
                <div className="error" style={{ marginTop: 10 }} title="Partial failure loading portfolio details.">
                  Some portfolio calls failed: {String(acctSnap.portfolio_error)}
                </div>
              ) : null}
            </div>
          )}

          <div className="chart-tabs" role="tablist" aria-label="Account branch tabs" style={{ marginTop: 14, marginBottom: 8 }}>
            {[
              { id: "live", label: "Live" },
              { id: "a", label: "Lab A" },
              { id: "b", label: "Lab B" },
              { id: "c", label: "Lab C" },
              { id: "d", label: "Lab D" },
            ].map((t) => (
              <button
                key={t.id}
                type="button"
                role="tab"
                aria-selected={holdingsBranchTab === t.id}
                className={`chart-tab ${holdingsBranchTab === t.id ? "chart-tab--active" : ""}`}
                onClick={() => setHoldingsBranchTab(t.id as "live" | "a" | "b" | "c" | "d")}
              >
                {t.label}
              </button>
            ))}
          </div>

          <div className="account-section-box" style={{ marginTop: 8 }}>
            {acctSnap?.position_by_asset && Object.keys(acctSnap.position_by_asset).length > 0 ? (
              <div className="account-section-scroll account-section-scroll--holdings" style={{ overflowX: "auto" }} title="Per configured asset: where exposure shows up.">
                <table className="table">
                  <thead>
                    <tr>
                      <th title="Config asset id.">Asset</th>
                      <th title="Kalshi series_ticker from config.">Series</th>
                      {accountLinked ? (
                        <th title="Open positions returned by GET /portfolio/positions for this series.">Kalshi open</th>
                      ) : null}
                      <th
                        title={
                          holdingsBranchTab === "live"
                            ? "Live-branch open sim rows in SQLite. Cell text: market lines = distinct tickers with exposure; contracts = Kalshi YES/NO size (summed when merged)."
                            : `Lab ${holdingsBranchTab.toUpperCase()} open sim rows. Market lines = distinct tickers; contracts = position size (Kalshi units), not how many markets.`
                        }
                      >
                        {holdingsBranchTab === "live"
                          ? "Live"
                          : holdingsBranchTab === "a"
                            ? "Lab A"
                            : holdingsBranchTab === "b"
                              ? "Lab B"
                              : holdingsBranchTab === "c"
                                ? "Lab C"
                                : "Lab D"}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {orderedAssetEntries(acctSnap.position_by_asset as AnyObj).map(([aid, row]: [string, AnyObj]) => {
                      const kal = summarizePositionRows(row.kalshi_open);
                      const simByTab =
                        holdingsBranchTab === "live"
                          ? summarizePositionRows(row.bot_sim_open_live)
                          : holdingsBranchTab === "a"
                            ? summarizePositionRows(
                                Array.isArray(row.bot_sim_open_lab_a) ? row.bot_sim_open_lab_a : row.bot_sim_open_lab,
                              )
                            : holdingsBranchTab === "b"
                              ? summarizePositionRows(row.bot_sim_open_lab_b)
                              : holdingsBranchTab === "c"
                                ? summarizePositionRows(row.bot_sim_open_lab_c)
                                : summarizePositionRows(row.bot_sim_open_lab_d);
                      return (
                      <tr key={aid} title={`Configured asset ${aid}`}>
                        <td title="Label from config.">{String(row.label || aid)}</td>
                        <td>
                          <code title="Series used for prefix match.">{String(row.series_ticker || "")}</code>
                        </td>
                        {accountLinked ? (
                          <td
                            className="sub"
                            style={{ fontSize: 12, maxWidth: 280, wordBreak: "break-word" }}
                            title={kal.title || kal.text}
                          >
                            {kal.text}
                          </td>
                        ) : null}
                        <td
                          className="sub"
                          style={{ fontSize: 12, maxWidth: 280, wordBreak: "break-word" }}
                          title={simByTab.title || simByTab.text}
                        >
                          {simByTab.text}
                        </td>
                      </tr>
                    );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="sub" style={{ marginTop: 4 }}>No holdings rows for this account view yet.</div>
            )}
          </div>

          <div className="account-section-box account-section-box--activity" style={{ marginTop: 16 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
              <h3 className="section-tip" style={{ margin: 0, fontSize: 16 }} title="Recent signal/trade rows from SQLite logs.">
                Activity log
              </h3>
              <button
                type="button"
                className="chart-tab"
                style={{ padding: "4px 10px" }}
                title={
                  "Activity log: server sends capped recent signal + trade history (e.g. up to 500 each); the Live/Lab tabs filter " +
                  "by branch (legacy sim_lab = Lab A). “Recent trade/signal” tables share one filter; the “Bets not traded” block below " +
                  "has its own independent branch pickers. Timestamps are log order; for forensics, pair with JSONL on disk. " +
                  "Skips, fills, and rule names appear as returned by the API—if a row is missing, it may have been truncated by the cap."
                }
                onClick={() =>
                  setInfoPopup({
                    title: "Activity log",
                    body: (
                      <div className="dash-section__legend" style={{ fontSize: 13, lineHeight: 1.55 }}>
                        <p>
                          <strong>What this is.</strong> The Activity log is a read-only, reverse-chronological view of the bot’s
                          recent <strong>signals</strong> (rule evaluations and intent) and <strong>trades</strong> (rows the engine
                          created or the exchange returned, depending on mode). The backend reads SQLite (and sometimes hydrates
                          with Kalshi) and returns a bounded list so the UI stays snappy. It is the first place to look after “why
                          did / didn’t a trade land?”
                        </p>
                        <p>
                          <strong>Limits and truncation.</strong> The API typically caps each stream (for example, the last 500
                          signals and 500 trades <em>combined across branches in the response shape you have</em>—treat the exact
                          number as implementation detail). If you do not see an old fill, it may have rolled off; check on-disk
                          JSONL in <code>data/logs</code> or run SQL against the local DB. Truncation is normal for long runs.
                        </p>
                        <p>
                          <strong>Branch tabs (Live, Lab A, Lab B, Lab C, Lab D) for “Recent” tables.</strong> These tabs are a
                          <em>row filter on the in-memory list</em>. Only rows whose <code>branch</code> (or historical{" "}
                          <code>sim_lab</code> for Lab A) match are shown. Switching tabs does not refetch; it re-slices. If you
                          expect a Lab C row and see nothing, either the event never had <code>branch=lab_c</code> or it fell out
                          of the cap, not because the filter is broken.
                        </p>
                        <p>
                          <strong>Legacy <code>sim_lab</code>.</strong> Older rows may only carry a generic lab bit; the UI still
                          maps them into the Lab A bucket for display consistency. When correlating to SQLite, use ids and
                          market tickers, not only the human label in the first column.
                        </p>
                        <p>
                          <strong>“Bets not traded” (separate card below).</strong> That block is its <em>own</em> branch filter and
                          query path: it lists situations where a rule pattern matched the market state but the engine did not
                          place an order—risk caps, <code>series_has_open_sim</code>, time-to-close, fee floors, or hard skips.
                          Do not expect that tab to match the count of the ordinary signals tab: different semantics entirely.
                        </p>
                        <p>
                          <strong>Interpreting columns.</strong> You will see rule names, market tickers, side, notional, skip
                          reason codes, and engine timestamps. A row with <em>no</em> trade in the “Trades” sub-tab is expected when
                          the log line was a pure signal. A trade row with <code>error</code> or empty exchange id in Live mode
                          requires cross-checking Kalshi; in paper, check SQLite for duplicate sims or post failures. Color and
                          badges, if any, follow the table component— they are not legal settlement records.
                        </p>
                        <p>
                          <strong>When things look out of order.</strong> (1) Clock skew: server logs use UTC/ISO; your browser
                          localizes. (2) Batch latency: a signal may preface a trade by seconds. (3) Engine off: you may only see
                          stale items until tick resumes. (4) Multi-branch tests: the same market can produce five rows; always read
                          the branch column. (5) Compare to Optimizer Lab pulse: narrative vs structured rows here.
                        </p>
                        <p>
                          <strong>Operational use.</strong> (1) Debug skips before changing rules. (2) After deploy, verify a single
                          expected fill path end-to-end. (3) Before promoting Lab A, scan all labs’ activity for unintended live-only
                          paths. (4) If support asks for “logs”, export the JSONL plus a screenshot of this table with branch visible.
                        </p>
                        <p style={{ fontSize: 12, color: "#9aa6cc", marginTop: 8 }}>
                          <strong>Reminder.</strong> Recent signals and recent trades (above) use the branch tab in this header.{" "}
                          <strong>Bets not traded</strong> uses a separate set of branch tabs in its own sub-panel; keep both
                          consistent when you are debugging a single market.
                        </p>
                      </div>
                    ),
                  })
                }
              >
                Info
              </button>
            </div>
            <div className="account-activity-fill account-section-scroll account-section-scroll--activity" style={{ marginTop: 10 }}>
              <div className="account-activity-sticky-head">
                <div className="chart-tabs" role="tablist" aria-label="Account activity view" style={{ marginBottom: 10 }}>
                  <button
                    type="button"
                    role="tab"
                    aria-selected={accountActivityView === "signals"}
                    className={`chart-tab ${accountActivityView === "signals" ? "chart-tab--active" : ""}`}
                    onClick={() => setAccountActivityView("signals")}
                  >
                    Recent signals
                  </button>
                  <button
                    type="button"
                    role="tab"
                    aria-selected={accountActivityView === "trades"}
                    className={`chart-tab ${accountActivityView === "trades" ? "chart-tab--active" : ""}`}
                    onClick={() => setAccountActivityView("trades")}
                  >
                    Recent trades
                  </button>
                  <button
                    type="button"
                    role="tab"
                    aria-selected={accountActivityView === "not_traded"}
                    className={`chart-tab ${accountActivityView === "not_traded" ? "chart-tab--active" : ""}`}
                    onClick={() => setAccountActivityView("not_traded")}
                  >
                    Bets not traded
                  </button>
                </div>
                <p className="sub section-tip" style={{ margin: "0 0 10px 0", fontSize: 12, lineHeight: 1.45 }}>
                  Showing <strong>{activityBranchTabLabel(accountActivityBranch)}</strong> only (follows Account branch tabs).
                </p>
              </div>
              <div className="account-activity-scroll-content">

              {accountActivityView === "signals" ? (
                <div className="panel account-activity-tab-panel">
                  <h3
                    className="section-tip"
                    style={{ marginTop: 0, marginBottom: 10, fontSize: 14, color: "var(--text)" }}
                    title="SQLite log when the engine evaluates a logged path (sizing, sim fill, live order attempt). Most silent skips are not rows here - use tick log and asset snapshots."
                  >
                    Recent signals — {activityBranchTabLabel(accountActivityBranch)}
                  </h3>
                  <SignalsTable
                    rows={recentSignalsFiltered}
                    emptyTitle={`No signals for ${activityBranchTabLabel(accountActivityBranch)} yet.`}
                  />
                  <ActivityHints
                    kind="signals"
                    dash={dash}
                    cfg={cfg}
                    simLab={simLab}
                    activityBranch={accountActivityBranch}
                    branchRowCount={recentSignalsFiltered.length}
                    totalRowCount={(dash?.recent_signals || []).length}
                  />
                </div>
              ) : null}

              {accountActivityView === "trades" ? (
                <div className="panel account-activity-tab-panel">
                  <h3
                    className="section-tip"
                    style={{ marginTop: 0, marginBottom: 10, fontSize: 14, color: "var(--text)" }}
                    title="Fills and simulated orders from the engine for the selected branch."
                  >
                    Recent trades — {activityBranchTabLabel(accountActivityBranch)}
                  </h3>
                  <TradesTable
                    rows={recentTradesFiltered}
                    emptyTitle={`No trades for ${activityBranchTabLabel(accountActivityBranch)} yet.`}
                  />
                  <ActivityHints
                    kind="trades"
                    dash={dash}
                    cfg={cfg}
                    simLab={simLab}
                    activityBranch={accountActivityBranch}
                    branchRowCount={recentTradesFiltered.length}
                    totalRowCount={(dash?.recent_trades || []).length}
                  />
                </div>
              ) : null}

              {accountActivityView === "not_traded" ? (
                <div className="panel account-activity-tab-panel">
                  <h3
                    className="section-tip"
                    style={{ marginTop: 0, marginBottom: 10, fontSize: 14, color: "var(--text)" }}
                    title="Subset of signals where a rule matched but execution did not run (for selected branch)."
                  >
                    Bets not traded — {activityBranchTabLabel(accountActivityBranch)}
                  </h3>
                  <SignalsTable
                    rows={notTradedFiltered}
                    emptyTitle={`No matched-but-not-executed signals for ${activityBranchTabLabel(accountActivityBranch)} yet.`}
                  />
                  <ActivityHints
                    kind="not_traded"
                    dash={dash}
                    cfg={cfg}
                    simLab={simLab}
                    activityBranch={accountActivityBranch}
                    branchRowCount={notTradedFiltered.length}
                    totalRowCount={(dash?.not_traded_signals || []).length}
                    totalSignalsCount={(dash?.recent_signals || []).length}
                  />
                </div>
              ) : null}
              </div>
            </div>
          </div>

          <div className="account-section-box" style={{ marginTop: 16 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
              <h3 className="section-tip" style={{ margin: 0, fontSize: 16 }} title="Branch engine status for the selected account tab.">
                Engine
              </h3>
            </div>
            <div className="sub account-section-scroll account-section-scroll--engine" style={{ marginTop: 10 }} title="Engine polling status from /api/dashboard.">
              {(() => {
                const selectedIsLive = holdingsBranchTab === "live";
                const label =
                  holdingsBranchTab === "live"
                    ? "Live"
                    : holdingsBranchTab === "a"
                      ? "Lab A"
                      : holdingsBranchTab === "b"
                        ? "Lab B"
                        : holdingsBranchTab === "c"
                          ? "Lab C"
                          : "Lab D";
                const engineObj =
                  holdingsBranchTab === "live"
                    ? (dash?.engine?.live as AnyObj | undefined)
                    : holdingsBranchTab === "a"
                      ? engineLabA
                      : holdingsBranchTab === "b"
                        ? engineLabB
                        : holdingsBranchTab === "c"
                          ? engineLabC
                          : engineLabD;
                const on =
                  holdingsBranchTab === "live"
                    ? Boolean(dash?.engine?.live?.engine_running)
                    : holdingsBranchTab === "a"
                      ? labABranchEngineOn
                      : holdingsBranchTab === "b"
                        ? labBBranchEngineOn
                        : holdingsBranchTab === "c"
                          ? labCBranchEngineOn
                          : labDBranchEngineOn;
                const lastTick = engineObj?.last_tick_at;
                const scanned = engineObj?.markets_scanned;
                const errMsg = String(engineObj?.last_error || "");
                return (
                  <>
                    <div title={`${label} branch engine status from /api/dashboard.`}>
                      <strong>{label}</strong> engine {on ? "on" : "off"} ·{" "}
                      {selectedIsLive
                        ? `orders ${dash?.engine?.live?.simulate_orders ? "simulated (paper)" : "real limit posts"}`
                        : "always simulated"}{" "}
                      · last tick: {lastTick ? fmtIsoLocal(String(lastTick)) : "—"} · scanned {String(scanned ?? "—")}
                    </div>
                    {errMsg ? (
                      <div className="error" style={{ marginTop: 6 }} title={`Last ${label} engine error string.`}>
                        {label}: {errMsg}
                      </div>
                    ) : null}
                  </>
                );
              })()}
              <EngineTickTrace
                title={
                  holdingsBranchTab === "live"
                    ? "Live — last tick log"
                    : holdingsBranchTab === "a"
                      ? "Lab A — last tick log"
                      : holdingsBranchTab === "b"
                        ? "Lab B — last tick log"
                        : holdingsBranchTab === "c"
                          ? "Lab C — last tick log"
                          : "Lab D — last tick log"
                }
                lines={
                  holdingsBranchTab === "live"
                    ? dash?.engine?.live?.last_tick_trace
                    : holdingsBranchTab === "a"
                      ? engineLabA?.last_tick_trace
                      : holdingsBranchTab === "b"
                        ? engineLabB?.last_tick_trace
                        : holdingsBranchTab === "c"
                          ? engineLabC?.last_tick_trace
                          : engineLabD?.last_tick_trace
                }
              />
            </div>
          </div>
          </div>
        </div>
      </div>

      <SettingsOverlay
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        dash={dash}
        cfg={cfg}
        labA={labA}
        labB={labB}
        labC={labC}
        labD={labD}
        busy={busy}
        onSaveRules={saveRules}
        onValidateRulesJson={validateRulesOnServer}
        onSaveYesSubtitleFilter={saveYesSubtitleFilter}
        onSaveExcludeSubtitleFilter={saveExcludeSubtitleFilter}
        onSaveSizing={saveSizing}
        onSaveLabAFromSliders={saveLabAFromSliders}
        onSaveLabBFromSliders={saveLabBFromSliders}
        onSaveLabCFromSliders={saveLabCFromSliders}
        onSaveLabDFromSliders={saveLabDFromSliders}
        onSaveLabARules={saveLabARules}
        onSaveLabBRules={saveLabBRules}
        onSaveLabCRules={saveLabCRules}
        onSaveLabDRules={saveLabDRules}
        onSaveDevSimHighYesPct={saveDevSimHighYesPct}
        onSaveNoBetWhenYesBelow={saveNoBetWhenYesBelow}
        onSaveSwingExitImpliedDropPct={saveSwingExitImpliedDropPct}
        onSavePatientStopLossLive={savePatientStopLossLive}
        onSavePatientStopLossLab={savePatientStopLossLab}
        onSavePaperFees={savePaperFees}
        optimizerCfg={(cfg?.optimizer || optimizerCfg || {}) as AnyObj}
        onSaveOptimizerConfig={saveOptimizerConfig}
        optimizerSaving={optimizerSaving}
        onRunOptimizerNow={runOptimizerNow}
        onResetTradingData={resetTradingData}
        onApplyLabBranches={applyLabBranchesBulk}
        liveEngineOn={liveBranchEngineOn}
        onToggleLive={() => void setRunning(!liveBranchEngineOn)}
        labEngineAOn={labABranchEngineOn}
        labEngineBOn={labBBranchEngineOn}
        labEngineCOn={labCBranchEngineOn}
        labEngineDOn={labDBranchEngineOn}
        onToggleLabA={() => void setSimLabRunning(!labABranchEngineOn)}
        onToggleLabB={() => void setLabRunning("b", !labBBranchEngineOn)}
        onToggleLabC={() => void setLabRunning("c", !labCBranchEngineOn)}
        onToggleLabD={() => void setLabRunning("d", !labDBranchEngineOn)}
        onAddAllLabsPaper={() => void addAllLabsPaperBankroll()}
        onRefresh={() => void refresh({ force: true })}
        onOpenHistory={() => setHistoryOpen(true)}
        kalshi={kalshi as AnyObj}
        heroMarqueeSpeedMult={heroMarqueeSpeedMult}
        onHeroMarqueeSpeedMultChange={setHeroMarqueeSpeedMultPersist}
        tradePopupToastsEnabled={tradePopupToastsEnabled}
        onTradePopupToastsEnabledChange={setTradePopupToastsEnabledPersist}
      />
      <HistoricalExplorerOverlay open={historyOpen} onClose={() => setHistoryOpen(false)} />
      {equityCompareOpen ? (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Equity comparison chart"
          style={{ position: "fixed", inset: 0, zIndex: 1200, display: "flex", alignItems: "center", justifyContent: "center", padding: 16, background: "rgba(3, 8, 24, 0.72)" }}
          onClick={() => setEquityCompareOpen(false)}
        >
          <div className="panel" style={{ width: "min(1200px, 97vw)", maxHeight: "92vh", overflow: "auto", padding: "14px 16px" }} onClick={(e) => e.stopPropagation()}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, marginBottom: 8 }}>
              <h2 style={{ margin: 0, fontSize: 18 }}>Compare equity (one graph)</h2>
              <button type="button" className="chart-tab" onClick={() => setEquityCompareOpen(false)}>Close</button>
            </div>
            <div className="dash-equity-view-toggle" role="group" aria-label="Compare chart mode">
              <button
                type="button"
                className={`chart-tab ${equityCompareMode === "blended" ? "chart-tab--active" : ""}`}
                title="One blended line per branch: average of book and MTM."
                onClick={() => setEquityCompareMode("blended")}
              >
                Blended
              </button>
              <button
                type="button"
                className={`chart-tab ${equityCompareMode === "potential" ? "chart-tab--active" : ""}`}
                title="Potential spread per branch: MTM minus book."
                onClick={() => setEquityCompareMode("potential")}
              >
                Potential
              </button>
            </div>
            <div className="dash-equity-overlay-controls" role="group" aria-label="Toggle branch overlays">
              {([
                { key: "live", label: "Live", color: "#38bdf8" },
                { key: "a", label: "Lab A", color: "#a78bfa" },
                { key: "b", label: "Lab B", color: "#f59e0b" },
                { key: "c", label: "Lab C", color: "#f472b6" },
                { key: "d", label: "Lab D", color: "#fca5a5" },
              ] as const).map((opt) => (
                <label key={opt.key} className="dash-equity-overlay-toggle" title={`Show or hide ${opt.label} on the combined chart.`}>
                  <input
                    type="checkbox"
                    checked={equityVisible[opt.key]}
                    onChange={(e) => setEquityVisible((prev) => ({ ...prev, [opt.key]: e.target.checked }))}
                  />
                  <span className="dash-equity-overlay-dot" style={{ background: opt.color }} />
                  <span>{opt.label}</span>
                </label>
              ))}
            </div>
            <div
              className="chart chart--equity-overlay"
              title={
                equityCompareMode === "blended"
                  ? "Combined comparison using one blended line per branch (average of book and MTM)."
                  : "Combined comparison using potential spread per branch (MTM minus book)."
              }
            >
              <ResponsiveContainer key={equityOverlayRevision} width="100%" height="100%">
                <LineChart data={equityOverlayData} margin={{ left: 6, right: 10, top: 8, bottom: 32 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#223056" />
                  <XAxis dataKey="t" stroke="#7f8ab5" tick={{ fontSize: 11 }} minTickGap={28} interval="preserveStartEnd" />
                  <YAxis stroke="#7f8ab5" tick={{ fontSize: 11 }} domain={["auto", "auto"]} />
                  <Tooltip contentStyle={{ background: "#0b1228", border: "1px solid #243055" }} formatter={(value: number, name: string) => [`$${Number(value).toFixed(2)}`, name]} />
                  <Legend verticalAlign="bottom" height={28} wrapperStyle={{ fontSize: 11, paddingTop: 6 }} formatter={(value) => <span style={{ color: "var(--muted)" }}>{String(value)}</span>} />
                  {equityVisible.live ? <Line type="monotone" dataKey={equityCompareMode === "blended" ? "liveBlend" : "livePot"} name={equityCompareMode === "blended" ? "Live blended" : "Live potential"} stroke="#38bdf8" strokeWidth={2.4} dot={false} /> : null}
                  {equityVisible.a ? <Line type="monotone" dataKey={equityCompareMode === "blended" ? "aBlend" : "aPot"} name={equityCompareMode === "blended" ? "Lab A blended" : "Lab A potential"} stroke="#a78bfa" strokeWidth={2.4} dot={false} /> : null}
                  {equityVisible.b ? <Line type="monotone" dataKey={equityCompareMode === "blended" ? "bBlend" : "bPot"} name={equityCompareMode === "blended" ? "Lab B blended" : "Lab B potential"} stroke="#f59e0b" strokeWidth={2.4} dot={false} /> : null}
                  {equityVisible.c ? <Line type="monotone" dataKey={equityCompareMode === "blended" ? "cBlend" : "cPot"} name={equityCompareMode === "blended" ? "Lab C blended" : "Lab C potential"} stroke="#f472b6" strokeWidth={2.4} dot={false} /> : null}
                  {equityVisible.d ? <Line type="monotone" dataKey={equityCompareMode === "blended" ? "dBlend" : "dPot"} name={equityCompareMode === "blended" ? "Lab D blended" : "Lab D potential"} stroke="#fca5a5" strokeWidth={2.4} dot={false} /> : null}
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      ) : null}
      {infoPopup ? (
        <div
          role="dialog"
          aria-modal="true"
          aria-label={`${infoPopup.title} information`}
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 1200,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 16,
            background: "rgba(3, 8, 24, 0.72)",
          }}
          onClick={() => setInfoPopup(null)}
        >
          <div
            className="panel"
            style={{ width: "min(760px, 96vw)", maxHeight: "min(78vh, 760px)", overflow: "auto", padding: "14px 16px" }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 8 }}>
              <h3 style={{ margin: 0 }}>{infoPopup.title}</h3>
              <button type="button" className="chart-tab" style={{ padding: "4px 10px" }} onClick={() => setInfoPopup(null)}>
                Close
              </button>
            </div>
            {infoPopup.body}
          </div>
        </div>
      ) : null}
      <div className="app-bottom-marquee" aria-label="Live and lab branch tickers (persistent)">
        <BranchHeroMarquee
          dash={dash}
          cfg={{
            ...(cfg as AnyObj),
            hero_marquee_speed_mult: heroMarqueeSpeedMult,
          }}
          showSnapshot={false}
        />
      </div>
        </>
      ) : null}
    </div>
  );
}

function ActivityHints({
  kind,
  dash,
  cfg,
  simLab,
  activityBranch,
  branchRowCount,
  totalRowCount,
  totalSignalsCount,
}: {
  kind: "signals" | "trades" | "not_traded";
  dash: AnyObj;
  cfg: AnyObj;
  simLab: AnyObj;
  activityBranch: ActivityBranchKey;
  branchRowCount: number;
  totalRowCount: number;
  /** For not_traded: total signals table size (any branch). */
  totalSignalsCount?: number;
}) {
  if (branchRowCount > 0) return null;

  const liveOn = Boolean(cfg.engine_running);
  const labAOn = Boolean(dash?.engine?.lab_a?.engine_running ?? dash?.engine?.sim_lab?.engine_running ?? simLab.engine_running);
  const labBOn = Boolean(dash?.engine?.lab_b?.engine_running ?? (cfg.lab_b as AnyObj | undefined)?.engine_running);
  const labCOn = Boolean(dash?.engine?.lab_c?.engine_running ?? (cfg.lab_c as AnyObj | undefined)?.engine_running);
  const liveTick = dash?.engine?.live?.last_tick_at;
  const labATick = dash?.engine?.lab_a?.last_tick_at ?? dash?.engine?.sim_lab?.last_tick_at;
  const labBTick = dash?.engine?.lab_b?.last_tick_at;
  const labCTick = dash?.engine?.lab_c?.last_tick_at;
  const scannedLive = dash?.engine?.live?.markets_scanned;
  const scannedLabA = dash?.engine?.lab_a?.markets_scanned ?? dash?.engine?.sim_lab?.markets_scanned;
  const scannedLabB = dash?.engine?.lab_b?.markets_scanned;
  const scannedLabC = dash?.engine?.lab_c?.markets_scanned;

  const lines: string[] = [];
  const branchName = activityBranchTabLabel(activityBranch);

  if (kind !== "not_traded" && totalRowCount > 0) {
    lines.push(
      `No ${kind === "trades" ? "trades" : "signals"} for ${branchName} in the current dashboard sample — try another branch tab.`,
    );
  }

  if (kind === "not_traded") {
    lines.push(
      "This table only shows signal rows that matched a rule but were not executed. It does not list markets that never matched.",
    );
    const ts = totalSignalsCount ?? 0;
    if (ts === 0) {
      lines.push("You currently have no signal rows at all (any branch), so nothing can appear here yet.");
    } else if (totalRowCount === 0) {
      lines.push("No matched-but-not-executed rows on any branch yet (or none in the recent sample).");
    } else {
      lines.push(`No rows for ${branchName} in this sample — switch tabs to see Live / other labs.`);
    }
  }
  if (kind === "signals" || kind === "trades") {
    lines.push("Engines only write here when they take a logged path (e.g. rule + sizing evaluation, sim fill).");
    const needLive = activityBranch === "live";
    const needA = activityBranch === "lab_a";
    const needB = activityBranch === "lab_b";
    const needC = activityBranch === "lab_c";
    if ((needLive && !liveOn) || (needA && !labAOn) || (needB && !labBOn) || (needC && !labCOn)) {
      lines.push(`Turn the ${branchName} engine on in the toolbar — otherwise this branch’s ticks (and rows) stay idle.`);
    } else {
      if (needLive && liveOn) {
        lines.push(
          `Live last tick: ${liveTick ? fmtIsoLocal(String(liveTick)) : "—"} · markets scanned: ${scannedLive ?? "—"}.`,
        );
      }
      if (needA && labAOn) {
        lines.push(
          `Lab A last tick: ${labATick ? fmtIsoLocal(String(labATick)) : "—"} · markets scanned: ${scannedLabA ?? "—"}.`,
        );
      }
      if (needB && labBOn) {
        lines.push(
          `Lab B last tick: ${labBTick ? fmtIsoLocal(String(labBTick)) : "—"} · markets scanned: ${scannedLabB ?? "—"}.`,
        );
      }
      if (needC && labCOn) {
        lines.push(
          `Lab C last tick: ${labCTick ? fmtIsoLocal(String(labCTick)) : "—"} · markets scanned: ${scannedLabC ?? "—"}.`,
        );
      }
      lines.push(
        "For sim trades: a rule must match implied YES % and minutes-left, stake must reach min contracts, and you must not have already traded that ticker+rule this budget window (dedupe).",
      );
      lines.push(
        "If Kalshi returns HTTP 429, increase poll seconds (e.g. 12–20s) and rely on the shared market cache between engine ticks.",
      );
      lines.push(
        "If assets always show Rules matched: NONE, widen bands (see “Rule band experiments” in Settings).",
      );
    }
  }

  const hint = lines.join("\n\n");
  return (
    <div
      className="sub section-tip"
      style={{
        marginTop: 10,
        padding: "8px 10px",
        borderRadius: 8,
        border: "1px dashed var(--border)",
        fontSize: 12,
      }}
      title={hint}
      aria-label={hint}
      role="note"
    >
      <span aria-hidden="true">ⓘ</span> Why empty — hover for details
    </div>
  );
}

function ApiOfflineCallout({ message }: { message: string }) {
  return (
    <div className="callout callout-bad" role="alert" title={message}>
      <h2 className="callout-title" title="The dashboard JSON endpoint is unreachable from the browser.">
        Dashboard cannot load
      </h2>
      <p className="callout-body">{message}</p>
      <ol className="callout-steps">
        <li>
          In a terminal at the project folder, run: <code>.\scripts\run_backend.ps1</code> (or{" "}
          <code>.\scripts\launch_local.ps1</code> for API + UI together).
        </li>
        <li>
          Open the UI at <strong>http://localhost:5173</strong> (Vite). Do not use port 8765 in the browser for
          the dashboard; that URL is JSON only.
        </li>
        <li>
          If the API uses another port, set <code>KALSHI_BOT_PORT</code> and match it in{" "}
          <code>frontend/vite.config.ts</code> proxy <code>target</code>.
        </li>
      </ol>
    </div>
  );
}

/** First dashboard fetch: spinner + honest copy. Elapsed time is the only “progress” the UI can know. */
function DashboardLoadingScreen() {
  const [elapsedSec, setElapsedSec] = useState(0);
  useEffect(() => {
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const id = window.setInterval(() => setElapsedSec((n) => n + 1), 1000);
    return () => {
      window.clearInterval(id);
      document.body.style.overflow = prevOverflow;
    };
  }, []);

  return (
    <div
      className="app-loading-screen"
      role="status"
      aria-live="polite"
      aria-busy="true"
      aria-label="Loading dashboard, waiting for the API"
    >
      <div className="app-loading-screen__panel">
        <div className="app-loading-screen__spinner" aria-hidden />
        <h1 className="app-loading-screen__title">Chomp's Diner</h1>
        <p className="app-loading-screen__line">Loading dashboard</p>
        <p
          className="app-loading-screen__sub"
          title="The browser has no way to know how long the server will take. Only the clock below is real."
        >
          Waiting on the first <code className="app-loading-screen__code">/api/dashboard</code> response. There is no real
          percent-complete—if this runs long, the slow work is on the server or network, not a stuck animation.
        </p>
        <p className="app-loading-screen__elapsed" aria-live="off">
          Elapsed: {elapsedSec}s
        </p>
        <p className="app-loading-screen__hint">
          Use <code className="app-loading-screen__code">http://localhost:5173</code> so <code className="app-loading-screen__code">/api</code> proxies
          to the Python app. The browser times out the request after 90s with an error if it never returns.
        </p>
      </div>
    </div>
  );
}

function EngineTickTrace({ title, lines }: { title: string; lines: unknown }) {
  const arr = Array.isArray(lines) ? (lines as string[]) : [];
  if (!arr.length) {
    return (
      <div
        className="sub section-tip"
        style={{ marginTop: 8, fontSize: 12 }}
        title={`${title}: turn this engine on and wait for the next poll interval.`}
      >
        {title}: no trace yet
      </div>
    );
  }
  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 4 }}>{title}</div>
      <pre
        title="Last engine tick log lines (truncated in memory). Scroll for full output."
        style={{
          margin: 0,
          padding: "10px 12px",
          borderRadius: 8,
          border: "1px solid var(--border)",
          background: "#070d1c",
          fontSize: 11,
          lineHeight: 1.45,
          maxHeight: 220,
          overflow: "auto",
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
        }}
      >
        {arr.join("\n")}
      </pre>
    </div>
  );
}

function KalshiStatusBanner({ dash, cfg }: { dash: AnyObj | null; cfg: AnyObj }) {
  const k = dash?.kalshi as AnyObj | undefined;
  if (!k) return null;

  const blocks: { tone: "bad" | "warn" | "info"; text: string; detail?: string }[] = [];
  if (!k.public_ok) {
    blocks.push({
      tone: "bad",
      text: `Cannot reach Kalshi (${String(k.api_base || "")}, env=${String(k.env || "")}). ${k.public_error ? String(k.public_error) : ""}`,
    });
  }
  /* Public-only / missing keys: full copy lives on Settings → Kalshi & connection orb 4 (red ☐) — avoid duplicating here. */
  const polling = Boolean(k.polling_enabled);
  if (!polling && k.public_ok) {
    blocks.push({
      tone: "info",
      text: "No engine polling yet — turn Live and/or Lab A / Lab B on in the toolbar for ticks.",
      detail:
        "At least one branch engine must be running so the dual loop scans markets and writes signals. Labs use the same Kalshi feed as Live but keep separate paper ledgers.",
    });
  }

  if (!blocks.length) return null;

  return (
    <div style={{ marginBottom: 12 }}>
      {blocks.map((b, i) => (
        <div
          key={i}
          className={b.tone === "bad" ? "error" : "sub"}
          style={{
            marginTop: i ? 8 : 0,
            padding: "10px 12px",
            borderRadius: 10,
            border: "1px solid var(--border)",
            background: b.tone === "bad" ? undefined : b.tone === "warn" ? "#1a1530" : "#0f1a30",
            color: b.tone === "bad" ? undefined : "var(--text)",
            lineHeight: 1.45,
          }}
          title={b.detail || b.text}
        >
          {b.text}
        </div>
      ))}
    </div>
  );
}

function SignalsTable({
  rows,
  emptyTitle,
  scrollStyle,
}: {
  rows: AnyObj[];
  emptyTitle?: string;
  scrollStyle?: React.CSSProperties;
}) {
  if (!rows.length)
    return (
      <div className="sub" title="No signal rows for this branch in the current sample; engines only write signals on certain paths.">
        {emptyTitle ?? "No signals yet."}
      </div>
    );
  return (
    <div className="table-scroll" style={scrollStyle} title="Scroll vertically for older rows; header stays visible.">
      <table className="table">
        <thead>
          <tr>
            <th title="Signal creation time (local).">Time</th>
            <th title="live, lab_a (legacy sim_lab), lab_b, or lab_c.">Br</th>
            <th title="Configured asset id.">Asset</th>
            <th title="Market ticker.">Ticker</th>
            <th title="Matched rule name (or DEV bypass).">Rule</th>
            <th title="Implied YES probability at signal time.">Prob</th>
            <th title="Minutes to close at signal time.">Mins</th>
            <th title="Whether the engine executed a trade or order attempt.">Exec</th>
            <th title="Skip reason when not executed.">Skip</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => (
            <tr
              key={String(s.id)}
              title={`${String(s.ticker)} · ${String(s.rule_name || "")} · exec=${Number(s.executed) ? "yes" : "no"}`}
            >
              <td title={s.created_at ? String(s.created_at) : undefined}>{fmtIsoLocal(String(s.created_at || ""))}</td>
              <td title="Branch.">{String(s.branch || "live")}</td>
              <td title="Asset id.">{String(s.asset_id)}</td>
              <td style={{ maxWidth: 220, wordBreak: "break-all" }} title="Ticker.">
                {String(s.ticker)}
              </td>
              <td title="Rule name.">{String(s.rule_name || "")}</td>
              <td title="Implied probability.">{s.implied_prob == null ? "" : `${Math.round(Number(s.implied_prob) * 100)}%`}</td>
              <td title="Minutes left.">{s.minutes_left == null ? "" : Number(s.minutes_left).toFixed(1)}</td>
              <td title="Executed flag.">{Number(s.executed) ? "yes" : "no"}</td>
              <td title="Skip reason.">{String(s.skip_reason || "")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TradesTable({
  rows,
  emptyTitle,
  scrollStyle,
}: {
  rows: AnyObj[];
  emptyTitle?: string;
  scrollStyle?: React.CSSProperties;
}) {
  if (!rows.length)
    return (
      <div className="sub" title="No trades for this branch in the current sample; engine creates trades on fills or sim orders.">
        {emptyTitle ?? "No trades yet."}
      </div>
    );
  return (
    <div className="table-scroll" style={scrollStyle} title="Scroll vertically for older rows; header stays visible.">
      <table className="table">
        <thead>
          <tr>
            <th title="Trade or order creation time.">Time</th>
            <th title="live, lab_a (legacy sim_lab), lab_b, or lab_c.">Branch</th>
            <th title="simulate vs live trade mode.">Mode</th>
            <th title="Market ticker.">Ticker</th>
            <th title="Whether the fill was simulated.">Sim</th>
            <th title="Notional cost in dollars.">Cost</th>
            <th title="Order status from Kalshi or sim.">Status</th>
            <th title="Settlement result when closed.">Result</th>
            <th title="Realized PnL when settled.">PnL</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((t) => (
            <tr key={String(t.id)} title={`${String(t.ticker)} · ${String(t.status)} · sim=${Number(t.simulated) ? "yes" : "no"}`}>
              <td title={t.created_at ? String(t.created_at) : undefined}>{fmtIsoLocal(String(t.created_at || ""))}</td>
              <td title="Branch.">{String(t.branch || "live")}</td>
              <td title="Trade mode.">{String(t.mode)}</td>
              <td style={{ maxWidth: 220, wordBreak: "break-all" }} title="Ticker.">
                {String(t.ticker)}
              </td>
              <td title="Simulated flag.">{Number(t.simulated) ? "yes" : "no"}</td>
              <td title="Amount in dollars.">{fmtMoney(Number(t.amount_cents || 0) / 100.0)}</td>
              <td title="Status.">{String(t.status)}</td>
              <td title="Result.">{String(t.result || "")}</td>
              <td title="PnL dollars.">{t.pnl_cents == null ? "" : fmtMoney(Number(t.pnl_cents) / 100.0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

