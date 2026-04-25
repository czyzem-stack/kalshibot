import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import SettingsOverlay from "./SettingsOverlay";
import HistoricalExplorerOverlay from "./HistoricalExplorerOverlay";
import { BranchMarketTickers } from "./BranchMarketTickers";

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

/** When text is wider than the strip, scroll horizontally (marquee); otherwise show static one line. */
function LabThoughtScrollingLine({ text }: { text: string }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const firstRef = useRef<HTMLSpanElement>(null);
  const [needsScroll, setNeedsScroll] = useState(false);

  useLayoutEffect(() => {
    const wrap = wrapRef.current;
    const first = firstRef.current;
    if (!wrap || !first) return;
    const measure = () => {
      setNeedsScroll(first.getBoundingClientRect().width > wrap.clientWidth + 1);
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(wrap);
    ro.observe(first);
    return () => ro.disconnect();
  }, [text]);

  const durSec = Math.max(16, Math.min(100, Math.round(text.length * 0.065)));

  return (
    <div ref={wrapRef} className="lab-thoughts-strip__marquee" title={text}>
      <div
        className={`lab-thoughts-strip__track${needsScroll ? " lab-thoughts-strip__track--scroll" : " lab-thoughts-strip__track--static"}`}
        style={needsScroll ? { animationDuration: `${durSec}s` } : undefined}
      >
        <span ref={firstRef} className="lab-thoughts-strip__seg">
          {text}
        </span>
        {needsScroll ? (
          <span className="lab-thoughts-strip__seg" aria-hidden>
            {text}
          </span>
        ) : null}
      </div>
    </div>
  );
}

/** All labs at once (no rotation) — avoids skipping / overwriting a single rotating line. */
function LabThoughtsStrip({ thoughts }: { thoughts: AnyObj | undefined }) {
  const rows = useMemo(() => {
    const t = thoughts && typeof thoughts === "object" ? (thoughts as AnyObj) : {};
    return [
      { lab: "Lab A", key: "lab_a", accent: "#c4b5fd" },
      { lab: "Lab B", key: "lab_b", accent: "#fdba74" },
      { lab: "Lab C", key: "lab_c", accent: "#f9a8d4" },
      { lab: "Lab D", key: "lab_d", accent: "#fca5a5" },
    ].map(({ lab, key, accent }) => ({
      lab,
      accent,
      text: labThoughtsToSentence(t[key]),
    }));
  }, [thoughts]);

  return (
    <div
      className="lab-thoughts-stack section-tip"
      role="region"
      aria-label="Lab pulse — Live reasoning per lab from the latest dashboard poll"
      title="Each row is one lab; text updates every dashboard refresh. No rotation, so nothing gets skipped between polls."
    >
      <div className="lab-thoughts-stack__head">Lab pulse</div>
      {rows.map((row) => (
        <div key={row.lab} className="lab-thoughts-stack__row" title={row.text}>
          <span className="lab-thoughts-stack__badge" style={{ color: row.accent }}>
            {row.lab}
          </span>
          <div className="lab-thoughts-stack__marquee">
            <LabThoughtScrollingLine text={row.text} />
          </div>
        </div>
      ))}
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

/** Seen change_history stable ids for the “Toast: trades by lab” unread blip (separate from optimizer panel seen ids). */
const TRADE_LAB_SNAPSHOT_SEEN_CH_KEY = "trade_lab_snapshot_seen_ch_v1";
const TRADE_LAB_SNAPSHOT_BOOT_KEY = "trade_lab_snapshot_boot_v1";

function readTradeLabSnapshotSeenChSet(): Set<string> {
  try {
    const raw = window.sessionStorage.getItem(TRADE_LAB_SNAPSHOT_SEEN_CH_KEY);
    if (!raw) return new Set();
    const arr = JSON.parse(raw) as unknown;
    if (!Array.isArray(arr)) return new Set();
    return new Set(arr.map((x) => String(x)).filter(Boolean));
  } catch {
    return new Set();
  }
}

function persistTradeLabSnapshotSeenChSet(ids: Set<string>) {
  try {
    window.sessionStorage.setItem(TRADE_LAB_SNAPSHOT_SEEN_CH_KEY, JSON.stringify([...ids].slice(-500)));
  } catch {
    // ignore
  }
}

/** Backend ``optimizer_activity.radar`` → Recharts rows (one row per axis, all branches). */
/** Draw order: back → front so Lab A sits on top. */
const BRANCH_RADAR_LAYERS: { dataKey: string; label: string; stroke: string; fill: string; fillOpacity: number; strokeWidth: number }[] = [
  { dataKey: "live", label: "Live", stroke: "#3b82f6", fill: "#3b82f6", fillOpacity: 0.06, strokeWidth: 1 },
  { dataKey: "lab_d", label: "Lab D", stroke: "#ef4444", fill: "#ef4444", fillOpacity: 0.07, strokeWidth: 1.05 },
  { dataKey: "lab_b", label: "Lab B", stroke: "#f97316", fill: "#f97316", fillOpacity: 0.07, strokeWidth: 1.05 },
  { dataKey: "lab_c", label: "Lab C", stroke: "#ec4899", fill: "#ec4899", fillOpacity: 0.078, strokeWidth: 1.1 },
  { dataKey: "lab_a", label: "Lab A", stroke: "#a855f7", fill: "#a855f7", fillOpacity: 0.1, strokeWidth: 1.35 },
];

const BRANCH_RADAR_LEGEND = [BRANCH_RADAR_LAYERS[0], BRANCH_RADAR_LAYERS[4], BRANCH_RADAR_LAYERS[2], BRANCH_RADAR_LAYERS[3], BRANCH_RADAR_LAYERS[1]];

function buildBranchRadarRows(radar: AnyObj | null | undefined): AnyObj[] {
  if (!radar || typeof radar !== "object") return [];
  const axes = Array.isArray(radar.axes) ? (radar.axes as AnyObj[]) : [];
  const norm = (radar.profiles_norm || {}) as AnyObj;
  const raw = (radar.profiles_raw || {}) as AnyObj;
  const focus = (radar.axis_focus || {}) as AnyObj;
  return axes.map((ax) => {
    const k = String(ax.key);
    const row: AnyObj = {
      subject: String(ax.label),
      axisKey: k,
      focus: Number(focus[k]) || 0,
    };
    for (const br of ["live", "lab_a", "lab_b", "lab_c", "lab_d"]) {
      row[br] = Number((norm[br] as AnyObj)?.[k]) || 0;
      row[`${br}_raw`] = (raw[br] as AnyObj)?.[k];
    }
    return row;
  });
}

function fmtRadarAxisRaw(axisKey: string, value: unknown): string {
  if (value == null || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  if (axisKey === "bet_frac") return `${(n * 100).toFixed(2)}%`;
  if (axisKey === "bank_log") return `${n.toFixed(2)} (log10 cents)`;
  if (axisKey === "fee_mult") return `${n.toFixed(2)}×`;
  if (axisKey.startsWith("opt_")) return String(Math.round(n));
  if (axisKey === "window_min" || axisKey === "poll_sec" || axisKey === "min_contracts" || axisKey === "fee_bps") return String(Math.round(n));
  if (axisKey === "rule_min_m") return `${n.toFixed(1)} min`;
  if (axisKey === "yes_floor" || axisKey === "no_bet_cut" || axisKey === "dev_yes_pct" || axisKey === "swing_drop") {
    const r = Math.round(n);
    return axisKey === "dev_yes_pct" && r === 0 ? "off" : `${r}%`;
  }
  const r = Math.round(n * 10) / 10;
  return Number.isInteger(r) ? String(r) : String(r);
}

function OptimizerBranchRadarTooltip(props: AnyObj) {
  const { active, payload } = props;
  if (!active || !payload?.length) return null;
  const p = payload[0]?.payload as AnyObj | undefined;
  if (!p) return null;
  const ak = String(p.axisKey || "");
  const f = Number(p.focus) || 0;
  return (
    <div
      style={{
        background: "#0b1228",
        border: "1px solid #243055",
        borderRadius: 8,
        padding: "8px 10px",
        fontSize: 11,
        maxWidth: 300,
        color: "#e2e8f0",
      }}
    >
      <div style={{ fontWeight: 600, marginBottom: 6 }}>{String(p.subject)}</div>
      {f > 0.08 ? (
        <div style={{ fontSize: 10, color: "#fde047", marginBottom: 6 }} title="Recent optimizer / pulse activity weighted this spoke">
          Pulse focus: {(f * 100).toFixed(0)}%
        </div>
      ) : null}
      {BRANCH_RADAR_LAYERS.map(({ dataKey, label, stroke }) => (
        <div key={dataKey} style={{ marginTop: 2 }}>
          <span style={{ color: stroke, fontWeight: 600 }}>{label}:</span> {fmtRadarAxisRaw(ak, p[`${dataKey}_raw`])}
        </div>
      ))}
    </div>
  );
}

/** Watch-style second hand: advances on each persisted ``run_optimizer_once`` (internal pulse / Claude). */
function OptimizerRadarWatchHand({ evalCount, lastEvalAt }: { evalCount: number; lastEvalAt: string }) {
  const n = Math.floor(Number(evalCount) || 0);
  const sec = ((n % 60) + 60) % 60;
  const deg = -90 + sec * 6;
  const tip =
    lastEvalAt.trim() !== ""
      ? `Last optimizer evaluation: ${lastEvalAt} · ${n} total (hand = ${sec}/60 per revolution)`
      : `${n} optimizer evaluations (hand = ${sec}/60 per revolution)`;
  return (
    <div className="optimizer-radar-watch-hand" title={tip} aria-hidden>
      <div className="optimizer-radar-watch-hand__pivot">
        <div className="optimizer-radar-watch-hand__arm" style={{ transform: `rotate(${deg}deg)` }} />
        <div className="optimizer-radar-watch-hand__cap" />
      </div>
    </div>
  );
}

function OptimizerRadarAngleTick(rows: AnyObj[]) {
  return (tickProps: AnyObj) => {
    const { x, y, payload, textAnchor, index } = tickProps;
    const row = rows[index] as AnyObj | undefined;
    const f = row ? Number(row.focus) || 0 : 0;
    const fill = f > 0.55 ? "#fef08a" : f > 0.28 ? "#cbd5f5" : "#7c86b8";
    const fontWeight = f > 0.45 ? 700 : f > 0.18 ? 600 : 400;
    const fs = f > 0.35 ? 9 : 8;
    return (
      <text x={x} y={y} textAnchor={textAnchor} fill={fill} fontSize={fs} fontWeight={fontWeight} dominantBaseline="central">
        {String(payload?.value ?? "")}
      </text>
    );
  };
}

function OptimizerActivitySection({
  activity,
  onTradeLabSnapshot,
  tradeSnapshotDisabled,
  snapshotUnseenChangeCount = 0,
  onOpenInfo,
}: {
  activity: AnyObj | undefined;
  onTradeLabSnapshot?: () => void;
  tradeSnapshotDisabled?: boolean;
  /** Optimizer change_history rows not yet acknowledged via the trades-by-lab toast. */
  snapshotUnseenChangeCount?: number;
  onOpenInfo?: (title: string, body: ReactNode) => void;
}) {
  const ch = Array.isArray(activity?.change_history) ? (activity!.change_history as AnyObj[]) : [];
  const preview = String(activity?.next_tick_preview || "").trim();
  const pulseTrace = Array.isArray(activity?.pulse_trace) ? (activity!.pulse_trace as AnyObj[]) : [];
  const radarPayload = activity?.radar && typeof activity.radar === "object" ? (activity.radar as AnyObj) : null;
  const rows = useMemo(() => buildBranchRadarRows(radarPayload), [radarPayload]);
  const angleTick = useMemo(() => OptimizerRadarAngleTick(rows), [rows]);
  const pulseEvalCount = Number(activity?.pulse_eval_count) || 0;
  const lastPulseEvalAt = String(activity?.last_pulse_eval_at || "");

  const hasPulseContent = Boolean(rows.length || preview || pulseTrace.length || ch.length);

  const snapshotBtn =
    onTradeLabSnapshot != null ? (
      <span style={{ position: "relative", display: "inline-block" }}>
        <button
          type="button"
          className="secondary"
          style={{ fontSize: 11, padding: "4px 10px", whiteSpace: "nowrap" }}
          disabled={Boolean(tradeSnapshotDisabled)}
          title={
            snapshotUnseenChangeCount > 0
              ? `${snapshotUnseenChangeCount} new optimizer change(s) since you last opened this snapshot. Click to view and clear the badge.`
              : "Open a toast with Live + Lab A–D rollups, optimizer context, and the newest settled rows from the dashboard feed."
          }
          aria-label={
            snapshotUnseenChangeCount > 0
              ? `Trades by lab snapshot, ${snapshotUnseenChangeCount} unread optimizer changes`
              : "Trades by lab snapshot toast"
          }
          onClick={() => onTradeLabSnapshot()}
        >
          Toast: trades by lab
        </button>
        {snapshotUnseenChangeCount > 0 ? (
          <span
            className="trade-lab-snapshot-badge"
            style={{
              position: "absolute",
              top: -5,
              right: -6,
              minWidth: 17,
              height: 17,
              padding: "0 4px",
              borderRadius: 999,
              background: "#dc2626",
              color: "#fff",
              fontSize: 10,
              fontWeight: 700,
              lineHeight: "17px",
              textAlign: "center",
              boxShadow: "0 0 0 2px var(--panel-bg, #0f172a)",
              pointerEvents: "none",
            }}
            aria-hidden
          >
            {snapshotUnseenChangeCount > 99 ? "99+" : String(snapshotUnseenChangeCount)}
          </span>
        ) : null}
      </span>
    ) : null;
  const infoBtn = onOpenInfo ? (
    <button
      type="button"
      className="chart-tab"
      style={{ padding: "4px 10px" }}
      title="How to read optimizer radar and pulse."
      onClick={() =>
        onOpenInfo(
          "Optimizer radar",
          <>
            <p>
              Radar overlays show effective branch posture across key dimensions (risk, sizing, thresholds, cadence). The
              watch hand advances with each optimizer evaluation.
            </p>
            <p>
              Pulse chips and next-tick text summarize what the optimizer is currently watching. Adaptive writes target Lab A
              only; Labs B/C/D remain context/reference arms.
            </p>
            <p>
              If no snapshot exists yet: enable Adaptive, run paper trades, then wait for scheduled cadence or run optimizer
              once.
            </p>
          </>,
        )
      }
    >
      Info
    </button>
  ) : null;

  if (!hasPulseContent) {
    return (
      <section className="dash-section optimizer-activity optimizer-pulse-wrap" aria-labelledby="dash-heading-opt-act">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
          <h2 id="dash-heading-opt-act" className="dash-section__title" style={{ marginBottom: 0 }}>
            Optimizer radar
          </h2>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginLeft: "auto" }}>
            {snapshotBtn}
            {infoBtn}
          </div>
        </div>
        <p className="sub" style={{ marginLeft: 2 }}>
          No optimizer snapshot yet.
        </p>
      </section>
    );
  }

  return (
    <section className="dash-section optimizer-activity optimizer-pulse-wrap" aria-labelledby="dash-heading-opt-act">
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <h2 id="dash-heading-opt-act" className="dash-section__title" style={{ marginBottom: 0 }}>
          Optimizer radar
        </h2>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginLeft: "auto" }}>
          {snapshotBtn}
          {infoBtn}
        </div>
      </div>
      {preview ? (
        <div className="optimizer-pulse-preview" title="What the internal engine will evaluate on the next scheduled tick">
          <strong>Next tick:</strong> {preview}
        </div>
      ) : null}
      {pulseTrace.length ? (
        <div className="optimizer-pulse-trace" aria-label="Recent pulse events">
          {pulseTrace.slice(0, 4).map((p, idx) => (
            <span key={String(p.change_id || p.at || idx)} className="optimizer-pulse-trace__chip" title={String(p.message || "")}>
              {String(p.kind || "pulse")}: {String(p.message || "").slice(0, 72)}
              {String(p.message || "").length > 72 ? "…" : ""}
            </span>
          ))}
        </div>
      ) : null}
      <div
        className="dash-section__legend optimizer-pulse-legend optimizer-pulse-legend--branches"
        title="Four overlays: effective trading config per branch (live base vs lab overlays). Brighter spoke labels = recent optimizer / pulse attention on that dimension."
      >
        {BRANCH_RADAR_LEGEND.map(({ dataKey, label, stroke }) => (
          <span key={dataKey} className="optimizer-pulse-legend__item">
            <span className="optimizer-pulse-legend__swatch" style={{ background: stroke }} /> {label}
          </span>
        ))}
      </div>
      {rows.length ? (
        <div
          className="optimizer-activity-chart optimizer-pulse-radar optimizer-pulse-radar--multi optimizer-radar-watch"
          title="Each branch is its own color. Yellow hand advances once per optimizer engine evaluation (internal pulse or scheduled run)."
        >
          <ResponsiveContainer width="100%" height={268}>
            <RadarChart cx="50%" cy="51%" outerRadius="74%" data={rows} margin={{ top: 8, right: 20, bottom: 10, left: 20 }}>
              <PolarGrid stroke="#223056" radialLines strokeOpacity={0.88} />
              <PolarAngleAxis dataKey="subject" tick={angleTick} tickLine={false} />
              <PolarRadiusAxis angle={90} domain={[0, 100]} tick={false} axisLine={false} />
              <Tooltip content={(tp: AnyObj) => <OptimizerBranchRadarTooltip {...tp} />} />
              {BRANCH_RADAR_LAYERS.map(({ dataKey, stroke, fill, fillOpacity, strokeWidth }) => (
                <Radar
                  key={dataKey}
                  name={dataKey}
                  dataKey={dataKey}
                  stroke={stroke}
                  strokeWidth={strokeWidth}
                  fill={fill}
                  fillOpacity={fillOpacity}
                  isAnimationActive={false}
                />
              ))}
            </RadarChart>
          </ResponsiveContainer>
          <OptimizerRadarWatchHand evalCount={pulseEvalCount} lastEvalAt={lastPulseEvalAt} />
        </div>
      ) : (
        <p className="sub" style={{ marginLeft: 4, fontSize: 12 }}>
          Radar payload missing — update the backend and refresh the dashboard.
        </p>
      )}
    </section>
  );
}

function fmtMoney(n: number) {
  const sign = n < 0 ? "-" : "";
  const v = Math.abs(n);
  return `${sign}$${v.toFixed(2)}`;
}

function fmtPct(n: unknown, digits = 2): string {
  if (n == null || n === "") return "—";
  const x = Number(n);
  if (!Number.isFinite(x)) return "—";
  const sign = x > 0 ? "+" : "";
  return `${sign}${x.toFixed(digits)}%`;
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

/** Stable signature for unresolved snap deltas (avoids resetting rotation on every poll when values unchanged). */
function branchSnapStripSignature(m: AnyObj): string {
  const cost = m.equity_snap_vs_calc_diff_dollars;
  const mtmEdge = m.last_snap_mtm_minus_equity_dollars;
  const c =
    cost != null && Number.isFinite(Number(cost)) && Math.abs(Number(cost)) > 0.001 ? Number(cost) : null;
  const e =
    mtmEdge != null && Number.isFinite(Number(mtmEdge)) && Math.abs(Number(mtmEdge)) > 0.001
      ? Number(mtmEdge)
      : null;
  if (c == null && e == null) return "";
  return `${c ?? ""}\t${e ?? ""}`;
}

/** Absolute dollar gap under this is colored “good” (green); at or above → red. */
const SNAP_RECON_AMOUNT_OK_UNDER = 1;

const SNAP_RECON_GLOSSARY =
  "Snap — Equity snapshot: one frozen row the engine saved (cost-basis equity, and sometimes MTM) for a tick; it is a point-in-time accounting capture, not a live quote. " +
  "Cost snap off calc: dollars between that snapshot’s cost-basis total and the dashboard model (bankroll + realized PnL − committed open premium); differences are often tick timing or what was written vs what the UI recomputes. " +
  "MTM — Mark-to-market: fair value of open positions at mids/marks vs cost on the same snapshot row when both columns exist; the gap is how much marking moved versus booked cost at that instant. " +
  "Amount colors: green when |gap| is under $1 (minor); red when $1 or more (worth a closer look).";

function snapReconAmountStyle(absDollars: number): CSSProperties {
  const ok = Math.abs(absDollars) < SNAP_RECON_AMOUNT_OK_UNDER;
  return {
    color: ok ? "var(--ok)" : "var(--danger)",
    fontVariantNumeric: "tabular-nums",
    fontWeight: 600,
  };
}

function snapReconAmountTitle(absDollars: number): string {
  const mag = Math.abs(absDollars);
  const ok = mag < SNAP_RECON_AMOUNT_OK_UNDER;
  return ok
    ? `Magnitude ${fmtMoney(mag)} (under $${SNAP_RECON_AMOUNT_OK_UNDER}) — treated as minor.`
    : `Magnitude ${fmtMoney(mag)} is $${SNAP_RECON_AMOUNT_OK_UNDER} or more — worth verifying timing or open marks.`;
}

/** One branch line for the snap-reconcile strip (paper only); only dollar amounts are color-coded. */
function renderBranchSnapLine(name: string, m: AnyObj): ReactNode | null {
  const cost = m.equity_snap_vs_calc_diff_dollars;
  const mtmEdge = m.last_snap_mtm_minus_equity_dollars;
  const hasCost = cost != null && Number.isFinite(Number(cost)) && Math.abs(Number(cost)) > 0.001;
  const hasMtm = mtmEdge != null && Number.isFinite(Number(mtmEdge)) && Math.abs(Number(mtmEdge)) > 0.001;
  if (!hasCost && !hasMtm) return null;

  const costN = hasCost ? Number(cost) : 0;
  const mtmN = hasMtm ? Number(mtmEdge) : 0;

  const pieces: ReactNode[] = [];
  if (hasCost) {
    pieces.push(
      <span key="c1">cost snap </span>,
      <span key="c2" style={snapReconAmountStyle(costN)} title={snapReconAmountTitle(costN)}>
        {fmtMoney(costN)}
      </span>,
      <span key="c3"> off calc</span>,
    );
  }
  if (hasMtm) {
    if (pieces.length) pieces.push(<span key="dot"> · </span>);
    pieces.push(
      <span key="m1">MTM </span>,
      <span key="m2" style={snapReconAmountStyle(mtmN)} title={snapReconAmountTitle(mtmN)}>
        {fmtMoney(mtmN)}
      </span>,
      <span key="m3"> vs cost snap</span>,
    );
  }

  return (
    <>
      {name} — {pieces}
    </>
  );
}

function SnapReconcileStrip({
  cfg,
  metrics,
  metricsLabA,
  metricsLabB,
  metricsLabC,
  metricsLabD,
}: {
  cfg: AnyObj;
  metrics: AnyObj;
  metricsLabA: AnyObj;
  metricsLabB: AnyObj;
  metricsLabC: AnyObj;
  metricsLabD: AnyObj;
}) {
  const stripSig = `${branchSnapStripSignature(metrics)}|${branchSnapStripSignature(metricsLabA)}|${branchSnapStripSignature(metricsLabB)}|${branchSnapStripSignature(metricsLabC)}|${branchSnapStripSignature(metricsLabD)}`;

  // stripSig encodes unresolved deltas so we do not rebuild bits every poll when values are unchanged.
  const bits = useMemo(() => {
    if (!cfg.simulate) return [] as ReactNode[];
    return [
      renderBranchSnapLine("Live", metrics),
      renderBranchSnapLine("Lab A", metricsLabA),
      renderBranchSnapLine("Lab B", metricsLabB),
      renderBranchSnapLine("Lab C", metricsLabC),
      renderBranchSnapLine("Lab D", metricsLabD),
    ].filter(Boolean) as ReactNode[];
  }, [cfg.simulate, stripSig]);

  const [idx, setIdx] = useState(0);

  useEffect(() => {
    setIdx(0);
  }, [stripSig]);

  useEffect(() => {
    if (bits.length <= 1) return;
    const id = window.setInterval(() => setIdx((i) => (i + 1) % bits.length), 4500);
    return () => window.clearInterval(id);
  }, [bits.length, stripSig]);

  if (!cfg.simulate || !bits.length) return null;

  const line = bits[idx % bits.length];

  return (
    <div
      className="section-tip"
      style={{
        marginTop: 10,
        padding: "6px 12px",
        borderRadius: 10,
        border: "1px solid rgba(255, 200, 120, 0.38)",
        background: "rgba(255, 200, 120, 0.09)",
        color: "#ffc878",
        fontSize: 12,
        lineHeight: 1.35,
        display: "flex",
        alignItems: "center",
        gap: 8,
        minWidth: 0,
      }}
      title="Rotates between branches when more than one still has a snap gap above the hide threshold."
    >
      <strong style={{ fontWeight: 700, flexShrink: 0 }}>Snap reconcile</strong>
      <button
        type="button"
        className="snap-recon-info"
        aria-label="What snap reconcile and MTM mean"
        title={SNAP_RECON_GLOSSARY}
      >
        i
      </button>
      <span
        style={{
          flex: 1,
          minWidth: 0,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {line}
      </span>
    </div>
  );
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
    { tier: "neutral", text: recentOptimizerActionsText(dash, 3) },
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

type EquityChartRow = { t: string; equity: number; mtm: number | null; synthetic?: boolean };

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
    return { t, equity: cell.eq, mtm: cell.mtm };
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
    return [
      { t: anchorT, equity, mtm, synthetic: true },
      { t: tailT, equity, mtm, synthetic: true },
    ];
  }
  return [...base, { t: tailT, equity, mtm, synthetic: true }];
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
  return `${tailSnap}|n=${rows.length}|t=${L.t}|eq=${L.equity}|mtm=${L.mtm ?? ""}|syn=${L.synthetic ? 1 : 0}|${m}`;
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
  const TRADE_LAB_SNAPSHOT_TOAST_ID = "manual-trade-lab-snapshot";
  const tradeToastsBootstrappedRef = useRef(false);
  const seenTradeInitRef = useRef<Set<string>>(new Set());
  const seenTradeSettleRef = useRef<Set<string>>(new Set());
  const [dash, setDash] = useState<AnyObj | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [optimizerRows, setOptimizerRows] = useState<AnyObj[]>([]);
  const [optimizerCfg, setOptimizerCfg] = useState<AnyObj>({});
  const [optimizerOpen, setOptimizerOpen] = useState(false);
  const [optimizerNotifs, setOptimizerNotifs] = useState<AnyObj[]>([]);
  const [optimizerSaving, setOptimizerSaving] = useState(false);
  const seenOptimizerEventIds = useRef<Set<string>>(new Set());
  const dismissedOptimizerEventIds = useRef<Set<string>>(new Set());
  const optimizerHistoryBootstrapped = useRef(false);
  const [assetWatchLab, setAssetWatchLab] = useState<"live" | "a" | "b" | "c" | "d">("live");
  const [holdingsBranchTab, setHoldingsBranchTab] = useState<"live" | "a" | "b" | "c" | "d">("live");
  const [accountActivityView, setAccountActivityView] = useState<"signals" | "trades" | "not_traded">("signals");
  const [perfBranch, setPerfBranch] = useState<PerfBranchKey>("live");
  const [equityGranularity, setEquityGranularity] = useState<EquityGranularity>("intraday");
  const [infoPopup, setInfoPopup] = useState<{ title: string; body: ReactNode } | null>(null);
  /** Last loaded dashboard JSON — used for manual trade snapshot toast if current ``dash`` is briefly null. */
  const dashSnapshotRef = useRef<AnyObj | null>(null);
  /** Stable ids of optimizer changes the user acknowledged by opening the trades-by-lab toast (sessionStorage-backed). */
  const tradeLabSnapshotSeenChRef = useRef<Set<string>>(readTradeLabSnapshotSeenChSet());
  const [tradeLabSnapshotBadgeEpoch, setTradeLabSnapshotBadgeEpoch] = useState(0);
  const optimizerChangeHistoryMergedRef = useRef<AnyObj[]>([]);

  /**
   * Latest dashboard fetch only: aborts the previous request so a slow poll cannot finish after a newer one
   * (avoids stale ``setDash`` overwriting optimistic engine toggles). A monotonic epoch lets superseded or
   * unmount-aborted fetches skip ``setDash``/``setErr`` so React Strict Mode and rapid Refresh clicks cannot strand
   * the UI with no data and no error.
   *
   * **Overlapping polls:** the 8s interval used to call ``refresh()`` while the prior fetch was still running;
   * each call aborted the previous request. Aborted handlers return without setting ``err``, so if every poll
   * arrived before the prior response (slow Kalshi + MTM), ``dash`` never loaded — endless "Loading dashboard…".
   * Scheduled polls therefore skip when a flight is already active; use ``refresh({ force: true })`` from the
   * Refresh button or after mutations to abort and supersede.
   */
  const dashboardAbortRef = useRef<AbortController | null>(null);
  const dashboardFetchEpoch = useRef(0);
  const dashboardFlightSerialRef = useRef(0);
  const dashboardActiveFlightRef = useRef(0);

  const refresh = useCallback(async (opts?: { force?: boolean }): Promise<AnyObj | null> => {
    const force = Boolean(opts?.force);
    if (dashboardActiveFlightRef.current !== 0 && !force) {
      return null;
    }
    dashboardAbortRef.current?.abort();
    const myEpoch = ++dashboardFetchEpoch.current;
    const myFlight = ++dashboardFlightSerialRef.current;
    dashboardActiveFlightRef.current = myFlight;
    const ac = new AbortController();
    dashboardAbortRef.current = ac;
    const maxMs = 90_000;
    const tid = window.setTimeout(() => ac.abort(), maxMs);
    let payload: AnyObj | null = null;
    try {
      setErr(null);
      const r = await fetch("/api/dashboard", { signal: ac.signal });
      if (!r.ok) throw new Error(`/api/dashboard ${r.status}`);
      const d = (await r.json()) as AnyObj;
      if (myEpoch !== dashboardFetchEpoch.current) return null;
      setDash(d);
      payload = d;
    } catch (e: any) {
      if (myEpoch !== dashboardFetchEpoch.current) return null;
      const msg = String(e?.message || e);
      const aborted =
        String(e?.name || "") === "AbortError" || /aborted|AbortError/i.test(msg);
      if (aborted) {
        // Superseded fetch (force refresh / new poll) also aborts — do not show the slow-dashboard error for that.
        if (dashboardActiveFlightRef.current !== myFlight) {
          return null;
        }
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
      if (dashboardActiveFlightRef.current === myFlight) {
        dashboardActiveFlightRef.current = 0;
      }
      if (dashboardAbortRef.current === ac) {
        dashboardAbortRef.current = null;
      }
    }
    return payload;
  }, []);

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

  const cfg = dash?.config || {};

  useEffect(() => {
    if (dash) dashSnapshotRef.current = dash as AnyObj;
  }, [dash]);

  /**
   * Toast when a sim/live trade row first appears (opened/resting) or when it settles. Bootstraps from
   * current ``recent_trades`` on first run so a page load does not flash old rows.
   */
  useEffect(() => {
    const rows = (dash?.recent_trades || []) as AnyObj[];
    if (!dash) return;
    if (!tradeToastsBootstrappedRef.current) {
      for (const t of rows) {
        const id = Number(t.id);
        if (!Number.isFinite(id)) continue;
        const idStr = String(id);
        const st = String(t.status || "").toLowerCase();
        if (st === "settled") {
          seenTradeSettleRef.current.add(idStr);
          seenTradeInitRef.current.add(idStr);
        } else if (st === "open" || st === "resting") {
          seenTradeInitRef.current.add(idStr);
        }
      }
      tradeToastsBootstrappedRef.current = true;
      return;
    }
    const toAdd: AnyObj[] = [];
    for (const t of rows) {
      const id = Number(t.id);
      if (!Number.isFinite(id)) continue;
      const idStr = String(id);
      const st = String(t.status || "").toLowerCase();
      const branch = branchLabelForTradeToast(t.branch);
      const tick = String(t.ticker || "").slice(0, 48);
      const side = String(t.side || "").toUpperCase() || "—";
      const sim = Boolean(Number(t.simulated));
      if (st === "settled") {
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
        const cardTone = pnl != null && pnl < 0 ? "red" : pnl != null && pnl > 0 ? "green" : "yellow";
        const pnlText =
          pnl == null ? "Settled" : `PnL ${pnl >= 0 ? "+" : ""}$${pnl.toFixed(2)}`;
        toAdd.push({
          id: `trade-resolved-${idStr}`,
          title: sim ? "Sim trade resolved" : "Trade resolved",
          body: "",
          tone: cardTone,
          segments: [
            { tier: "neutral", text: `${branch} · ${tick} ${side}` },
            { tier: lineTier, text: pnlText },
            ...(t.result ? [{ tier: "neutral" as const, text: `Result: ${String(t.result)}` }] : []),
          ],
          created_at: new Date().toISOString(),
        });
        continue;
      }
      if (st === "open" || st === "resting") {
        if (seenTradeInitRef.current.has(idStr)) continue;
        seenTradeInitRef.current.add(idStr);
        const cost = Number(t.amount_cents || 0) / 100.0;
        toAdd.push({
          id: `trade-initiated-${idStr}`,
          title: sim ? "Sim trade opened" : "Trade opened",
          body: "",
          tone: "green",
          segments: [
            { tier: "neutral", text: `${branch} · ${tick} ${side}` },
            { tier: "green", text: `≈ $${cost.toFixed(2)} at entry · ${st}` },
          ],
          created_at: new Date().toISOString(),
        });
      }
    }
    if (!toAdd.length) return;
    setOptimizerNotifs((prev) => {
      const byId = new Map<string, AnyObj>();
      for (const n of prev) byId.set(String(n.id), n);
      for (const n of toAdd) byId.set(String(n.id), n);
      const merged = Array.from(byId.values());
      merged.sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")));
      return merged.slice(0, 20);
    });
  }, [dash]);

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

  optimizerChangeHistoryMergedRef.current = optimizerChangeHistoryMerged;

  const tradeLabSnapshotUnseenCount = useMemo(() => {
    let n = 0;
    for (const h of optimizerChangeHistoryMerged) {
      const id = stableOptimizerChangeId(h);
      if (id && !tradeLabSnapshotSeenChRef.current.has(id)) n += 1;
    }
    return n;
  }, [optimizerChangeHistoryMerged, tradeLabSnapshotBadgeEpoch]);

  /** First session with real history: treat existing rows as already “read” so the blip only tracks new pulses. */
  useEffect(() => {
    const history = optimizerChangeHistoryMerged;
    try {
      if (window.sessionStorage.getItem(TRADE_LAB_SNAPSHOT_BOOT_KEY) !== "1" && history.length > 0) {
        for (const h of history) {
          const id = stableOptimizerChangeId(h);
          if (id) tradeLabSnapshotSeenChRef.current.add(id);
        }
        persistTradeLabSnapshotSeenChSet(tradeLabSnapshotSeenChRef.current);
        window.sessionStorage.setItem(TRADE_LAB_SNAPSHOT_BOOT_KEY, "1");
        setTradeLabSnapshotBadgeEpoch((e) => e + 1);
      }
    } catch {
      // ignore
    }
  }, [optimizerChangeHistoryMerged]);

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

  const pushTradeLabSnapshotToast = useCallback(() => {
    for (const h of optimizerChangeHistoryMergedRef.current) {
      const id = stableOptimizerChangeId(h);
      if (id) tradeLabSnapshotSeenChRef.current.add(id);
    }
    persistTradeLabSnapshotSeenChSet(tradeLabSnapshotSeenChRef.current);
    setTradeLabSnapshotBadgeEpoch((e) => e + 1);

    const source = (dash || dashSnapshotRef.current) as AnyObj | null;
    if (!source) return;
    const toast = buildTradesByLabSnapshotToast(source);
    const created = new Date().toISOString();
    setOptimizerNotifs((prev) => {
      const snap = {
        id: TRADE_LAB_SNAPSHOT_TOAST_ID,
        title: toast.title,
        body: toast.body,
        tone: toast.tone,
        segments: toast.segments,
        created_at: created,
      };
      const rest = prev.filter((p) => String(p.id) !== TRADE_LAB_SNAPSHOT_TOAST_ID);
      return [snap, ...rest].slice(0, 25);
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
      await refresh({ force: true });
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
      await refresh({ force: true });
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  };

  const saveNoBetWhenYesBelow = async (pct: number | null) => {
    setBusy(true);
    try {
      await apiPut("/api/config", { no_bet_when_yes_below_pct: pct });
      await refresh({ force: true });
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
    setBusy(true);
    try {
      const out = (await apiPost(`/api/engine/toggle?simulate=${simulate ? "true" : "false"}`)) as AnyObj;
      const cfgNext = out?.config;
      if (cfgNext && typeof cfgNext === "object") applyDashboardConfig(cfgNext as AnyObj);
      void refresh({ force: true });
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  };

  const setRunning = async (running: boolean) => {
    setBusy(true);
    try {
      const out = (await apiPost(`/api/engine/toggle?running=${running ? "true" : "false"}`)) as AnyObj;
      const cfgNext = out?.config;
      if (cfgNext && typeof cfgNext === "object") applyDashboardConfig(cfgNext as AnyObj);
      void refresh({ force: true });
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  };

  const setLabRunning = async (lab: "a" | "b" | "c" | "d", running: boolean) => {
    setBusy(true);
    try {
      const key = lab === "a" ? "lab_a_running" : lab === "b" ? "lab_b_running" : lab === "c" ? "lab_c_running" : "lab_d_running";
      const out = (await apiPost(`/api/engine/toggle?${key}=${running ? "true" : "false"}`)) as AnyObj;
      const cfgNext = out?.config;
      if (cfgNext && typeof cfgNext === "object") applyDashboardConfig(cfgNext as AnyObj);
      void refresh({ force: true });
    } catch (e: any) {
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
      await refresh({ force: true });
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
      await refresh({ force: true });
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
      await refresh({ force: true });
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
      await refresh({ force: true });
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
      await refresh({ force: true });
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
      await refresh({ force: true });
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
      await refresh({ force: true });
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
      await refresh({ force: true });
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
      await refresh({ force: true });
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally {
      setOptimizerSaving(false);
    }
  };

  const applyLabBranchesBulk = async (body: AnyObj) => {
    setBusy(true);
    try {
      await apiPutLabBranches(body);
      await refresh({ force: true });
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  };

  const resetTradingData = async (
    branch: "all" | "all_labs" | "live" | "lab_a" | "lab_b" | "lab_c" | "lab_d",
    backup: boolean,
  ) => {
    setBusy(true);
    setErr(null);
    try {
      const q = new URLSearchParams({
        confirm: "yes",
        backup: backup ? "true" : "false",
        branch,
      });
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
    void refresh({ force: true });
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
      await refresh({ force: true });
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
    <div className="page" title="Kalshi 15m bot — main dashboard. Hover controls for details.">
      {optimizerNotifs.length ? (
        <div
          style={{
            position: "fixed",
            bottom: 16,
            right: 16,
            top: "auto",
            zIndex: 1200,
            width: "min(400px, 94vw)",
            maxHeight: "72vh",
            overflowY: "auto",
            display: "flex",
            flexDirection: "column-reverse",
            gap: 8,
          }}
        >
          {optimizerNotifs.map((n) => {
            const tier = String(n.tone || "") === "red" || String(n.tone) === "yellow" || String(n.tone) === "green" ? String(n.tone) : "";
            const cardTone = tier ? ` optimizer-toast--${tier}` : "";
            const segs = Array.isArray(n.segments) ? (n.segments as { tier?: string; text?: string }[]) : null;
            return (
            <div key={String(n.id)} className={`panel optimizer-toast${cardTone}`} style={{ padding: "10px 12px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
                <div style={{ minWidth: 0 }}>
                  <strong style={{ fontSize: 12 }}>{String(n.title)}</strong>
                  {n.created_at ? (
                    <div className="sub" style={{ fontSize: 10, opacity: 0.88, marginTop: 3 }} title="Event or toast time (local)">
                      {fmtIsoLocal(String(n.created_at))}
                    </div>
                  ) : null}
                </div>
                <button
                  type="button"
                  style={{ padding: "2px 8px", fontSize: 11 }}
                  onClick={() => {
                    const id = String(n.id || "");
                    if (id) {
                      dismissedOptimizerEventIds.current.add(id);
                      try {
                        window.sessionStorage.setItem(
                          OPTIMIZER_DISMISSED_IDS_KEY,
                          JSON.stringify(Array.from(dismissedOptimizerEventIds.current).slice(-600)),
                        );
                      } catch {
                        // Ignore storage errors.
                      }
                    }
                    setOptimizerNotifs((prev) => prev.filter((x) => String(x.id) !== String(n.id)));
                  }}
                >
                  x
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
            );
          })}
        </div>
      ) : null}
      <div className="top">
        <div className="hero">
          <div className="hero-head">
            <h1
              className="title section-tip"
              title="15-minute crypto series, rule-based entries. Simulate = paper on the Live branch; Real $ can POST limit orders when the Live engine runs and a rule matches. Sim lab is always paper and uses separate sizing."
            >
              Kalshi 15m crypto bot
            </h1>
            {dash ? <KalshiSetupOrbRow dash={dash} cfg={cfg} /> : null}
          </div>
          <div className="hero-meta" title="Kalshi REST host and environment loaded by the backend from .env.">
            <span className="env-pill" title="Base URL the backend uses for Kalshi (demo vs prod).">
              API:{" "}
              <code>{kalshi?.api_base ? String(kalshi.api_base).replace("https://", "") : "—"}</code>
            </span>
            <span className="env-pill" title="KALSHI_ENV value (e.g. demo vs production).">
              Environment: <code>{String(kalshi?.env || "—")}</code>
            </span>
            <a
              className="muted-link"
              href="https://docs.kalshi.com/getting_started/api_keys"
              target="_blank"
              rel="noreferrer"
              title="Official Kalshi documentation for API keys."
            >
              Kalshi API keys (docs)
            </a>
          </div>
          {dash ? <BranchMarketTickers dash={dash} cfg={cfg} /> : null}
          {dash ? (
            <SnapReconcileStrip
              cfg={cfg}
              metrics={metrics}
              metricsLabA={metricsLabA}
              metricsLabB={metricsLabB}
              metricsLabC={metricsLabC}
              metricsLabD={metricsLabD}
            />
          ) : null}
        </div>
        <div className="toolbar-panel">
          <div className="toolbar toolbar--dock">
            <div className="toolbar-block" title="Refresh dashboard data and open full settings.">
              <div className="toolbar-label">Controls</div>
              <div className="toolbar-group">
                <button
                  className="primary"
                  disabled={busy}
                  title="Fetch /api/dashboard now (auto every ~8s). A new refresh aborts an older in-flight poll so the latest snapshot always wins."
                  onClick={() => void refresh({ force: true })}
                >
                  Refresh
                </button>
                <button
                  type="button"
                  disabled={busy}
                  title="Filters, subtitle rules, sizing, poll/window, rule bands, JSON rules, sim lab parameters."
                  onClick={() => setSettingsOpen(true)}
                >
                  Settings
                </button>
                <button type="button" disabled={busy} title="Explore saved historical rows and export CSV." onClick={() => setHistoryOpen(true)}>
                  History
                </button>
              </div>
            </div>
            <div className="toolbar-block" title="Paper vs real fills on the Live branch, and whether the Live engine loop runs.">
              <div className="toolbar-label">Live</div>
              <div className="toolbar-group">
                <button
                  className={cfg.simulate ? "primary" : "danger"}
                  disabled={busy}
                  title={
                    cfg.simulate
                      ? "Live branch uses simulated fills only — no orders sent to Kalshi. Click to switch to Real $ (you will be asked to confirm)."
                      : "Live branch can place real limit orders on Kalshi when the engine is on and a rule matches. Click to switch to Simulate (paper)."
                  }
                  onClick={() => setSimulate(!Boolean(cfg.simulate))}
                >
                  {cfg.simulate ? "Paper" : "Real $"}
                </button>
                <button
                  className="primary"
                  disabled={busy}
                  title="Starts/stops the Live engine loop (market scan, rules, trades on the Live branch)."
                  onClick={() => setRunning(!Boolean(cfg.engine_running))}
                >
                  Engine {cfg.engine_running ? "on" : "off"}
                </button>
              </div>
            </div>
          </div>
          <div className="toolbar-optimizer-foot" title="Anthropic-backed analysis on A/B/C paper data; auto-applied tuning targets Lab A only.">
            <div style={{ position: "relative", display: "flex", flexDirection: "column", alignItems: "flex-end" }}>
              <button
                type="button"
                className={optimizerOpen ? "primary" : ""}
                title="Open or close the Claude optimizer panel (labs-only data; stays clickable while other saves run)."
                onClick={() => setOptimizerOpen((o) => !o)}
              >
                Optimizer{optimizerOpen ? " ▾" : ""}
              </button>
            {optimizerOpen ? (
              <div
                className="panel"
                style={{
                  position: "absolute",
                  top: "100%",
                  right: 0,
                  zIndex: 50,
                  width: "min(360px, 92vw)",
                  maxHeight: "min(420px, 70vh)",
                  overflow: "auto",
                  marginTop: 8,
                  padding: "12px 14px",
                  boxShadow: "0 12px 40px rgba(0,0,0,0.45)",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, marginBottom: 8 }}>
                  <strong style={{ fontSize: 13 }}>Claude optimizer (labs only)</strong>
                  <button type="button" style={{ padding: "4px 10px" }} onClick={() => setOptimizerOpen(false)}>
                    Close
                  </button>
                </div>
                <div className="sub" style={{ marginTop: 4 }}>
                  Status: <strong>{String(optimizerCfg?.last_status || "idle")}</strong> · last run:{" "}
                  {optimizerCfg?.last_run_at ? fmtIsoLocal(String(optimizerCfg.last_run_at)) : "—"}
                </div>
                {optimizerCfg?.last_error ? (
                  <div className="error" style={{ marginTop: 8, fontSize: 12 }}>{String(optimizerCfg.last_error)}</div>
                ) : null}
                <div className="row" style={{ marginTop: 10 }}>
                  <button
                    className="primary"
                    disabled={busy}
                    onClick={async () => {
                      setBusy(true);
                      try {
                        await apiPost("/api/optimizer/run");
                        await loadOptimizer();
                      } catch (e: any) {
                        setErr(String(e?.message || e));
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    Run now
                  </button>
                  <button
                    disabled={busy}
                    onClick={async () => {
                      setBusy(true);
                      try {
                        await apiPut("/api/optimizer/config", {
                          enabled: !Boolean(optimizerCfg?.enabled),
                          interval_minutes: Number(optimizerCfg?.interval_minutes || 20),
                        });
                        await loadOptimizer();
                      } catch (e: any) {
                        setErr(String(e?.message || e));
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    Scheduler: {optimizerCfg?.enabled ? "On" : "Off"}
                  </button>
                </div>
                <div style={{ marginTop: 10 }}>
                  {(optimizerRows || []).slice(0, 5).map((r, i) => (
                    <div key={i} className="sub" style={{ marginTop: 8, fontSize: 12, lineHeight: 1.45 }}>
                      <strong>{fmtIsoLocal(String(r.created_at || ""))}</strong> — {String(r.summary || "")}
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
            </div>
          </div>
        </div>
      </div>

      {!dash && err ? <ApiOfflineCallout message={err} /> : null}
      {!dash && !err ? <ApiLoadingCallout /> : null}
      {dash && err ? (
        <div className="error" title="Last API or validation error from this browser session.">
          {err}
        </div>
      ) : null}

      {dash ? (
        <>
      <KalshiStatusBanner dash={dash} cfg={cfg} />

      <div className="dash-main-4grid">
        <div className="dash-split-row__col dash-split-row__col--metrics dash-split-card">
      <section className="dash-section dash-section--split-card" aria-labelledby="dash-heading-branch-performance">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
          <h2 id="dash-heading-branch-performance" className="dash-section__title" style={{ margin: 0 }}>
            Branch performance
          </h2>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginLeft: "auto" }}>
            <button
              type="button"
              className="primary"
              disabled={
                busy ||
                !(
                  Number(metricsLabA.total_pnl_dollars ?? 0) > Number(metricsLabB.total_pnl_dollars ?? 0) &&
                  Number(metricsLabA.total_pnl_dollars ?? 0) > Number(metricsLabC.total_pnl_dollars ?? 0) &&
                  Number(metricsLabA.total_pnl_dollars ?? 0) > Number(metricsLabD.total_pnl_dollars ?? 0)
                )
              }
              title="Copies Lab A overlays (rules, window, bet fraction, filters, fees, assets) to top-level Live when Lab A settled PnL exceeds both B and C. Extra confirmation when Live is in Real $ mode."
              onClick={() => void promoteLabAToLive()}
            >
              Apply Lab A to Live
            </button>
            <button
              type="button"
              className="chart-tab"
              style={{ padding: "4px 10px" }}
              title="How to read branch tiles and settled vs unrealized PnL."
              onClick={() =>
                setInfoPopup({
                  title: "Branch performance",
                  body: (
                    <div className="dash-section__legend">
                      <p>
                        Tiles follow the branch tab - each of Live / Lab A / B / C / D is a separate SQLite rollup.{" "}
                        <strong>Settled PnL</strong> is <em>only</em> from finalized/closed sim rows; it stays $0 until a
                        contract settles, even when MTM is up or down on open sims. Use <strong>open / mark P&amp;L</strong>{" "}
                        for the unrealized piece (MTM - start - settled).
                      </p>
                      <p>
                        Settled = closed in SQLite with realized PnL (Kalshi must finalize the contract for sim). Open
                        (paper) = premium held in open sim rows (subtracted from estimated equity).
                      </p>
                      {!cfg.simulate && perfBranchMeta.isLive ? (
                        <p>Cash / portfolio = Kalshi signed portfolio reads when API keys are configured.</p>
                      ) : null}
                      {cfg.simulate || !perfBranchMeta.isLive ? (
                        <p>
                          Reconcile {perfBranchMeta.reconcileLabel}: MTM (est.) below = last snapshot mark-to-market total.
                          Equity (cost basis) = bankroll + realized PnL - committed premium.
                        </p>
                      ) : null}
                    </div>
                  ),
                })
              }
            >
              Info
            </button>
          </div>
        </div>
        <div
          className="sub"
          style={{
            marginBottom: 12,
            display: "flex",
            flexWrap: "wrap",
            gap: "8px 14px",
            alignItems: "center",
            lineHeight: 1.45,
          }}
        >
          <span title="Settled closed trades in SQLite (same basis as the promote-to-Live API gate).">
            Settled PnL: <strong>Lab A</strong> {fmtMoney(Number(metricsLabA.total_pnl_dollars ?? 0))} · <strong>B</strong>{" "}
            {fmtMoney(Number(metricsLabB.total_pnl_dollars ?? 0))} · <strong>C</strong>{" "}
            {fmtMoney(Number(metricsLabC.total_pnl_dollars ?? 0))} · <strong>D</strong> {fmtMoney(Number(metricsLabD.total_pnl_dollars ?? 0))}
          </span>
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
      </section>

      <OptimizerActivitySection
        activity={dash.optimizer_activity as AnyObj | undefined}
        onTradeLabSnapshot={pushTradeLabSnapshotToast}
        tradeSnapshotDisabled={!dash}
        snapshotUnseenChangeCount={tradeLabSnapshotUnseenCount}
        onOpenInfo={(title, body) => setInfoPopup({ title, body })}
      />
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
            <button
              type="button"
              className="chart-tab"
              style={{ padding: "4px 10px" }}
              title="How to read book vs MTM equity lines."
              onClick={() =>
                setInfoPopup({
                  title: "Equity curves",
                  body: (
                    <div className="dash-section__legend dash-equity-panel__legend">
                      <p>
                        All four use the time-scale tabs. <strong>Book (solid)</strong> = cash-ledger: start + realized PnL,
                        minus premium still tied up in open sims (it <em>steps</em> on fill, exit, or settlement).{" "}
                        <strong>MTM (dashed)</strong> = that cash-ledger <em>plus</em> the current fair value of those open
                        sims. On a <strong>new open</strong>, book usually <em>drops</em> by what you paid, while total MTM
                        can <em>stay near</em> the line you had before if the position is marked close to cost - the two
                        series are from the same sim state but are <strong>not</strong> the same number. Dashed then wiggles
                        with every poll; solid stays flat until the next ledger event. That split is expected, not a bug.
                      </p>
                    </div>
                  ),
                })
              }
            >
              Info
            </button>
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
              <h3
                className="dash-equity-branch-head section-tip"
                title={`${activityBranchTabLabel("live")}: book value (solid) vs current worth / MTM (dashed). Intraday tail updates every dashboard poll; paper Live MTM is refreshed from Kalshi on each poll.`}
              >
                {activityBranchTabLabel("live")}
              </h3>
              <div
                className="chart chart--equity-stack"
                title={`${activityBranchTabLabel("live")} equity over time. Hover points for values.`}
              >
                <EquityDualLineChart
                  data={chartData}
                  equityStroke="#6ee7ff"
                  mtmStroke="#38bdf8"
                  revision={`${equityChartRevision(snaps, chartData, metrics)}|tick=${String(dash?.engine?.live?.last_tick_at || "")}`}
                />
              </div>
            </div>
            <div className="dash-equity-chart-block">
              <h3
                className="dash-equity-branch-head section-tip"
                title={`${activityBranchTabLabel("lab_a")}: book value (solid) vs current worth (dashed). MTM refreshed from Kalshi on each dashboard poll.`}
              >
                {activityBranchTabLabel("lab_a")}
              </h3>
              <div className="chart chart--equity-stack" title={`${activityBranchTabLabel("lab_a")} equity over time.`}>
                <EquityDualLineChart
                  data={chartDataLabA}
                  equityStroke="#a78bfa"
                  mtmStroke="#c4b5fd"
                  revision={`${equityChartRevision(equitySnapsLabA, chartDataLabA, metricsLabA)}|tick=${String(engineLabA?.last_tick_at || "")}`}
                />
              </div>
            </div>
            <div className="dash-equity-chart-block">
              <h3
                className="dash-equity-branch-head section-tip"
                title={`${activityBranchTabLabel("lab_b")}: book value (solid) vs current worth (dashed). MTM refreshed from Kalshi on each dashboard poll.`}
              >
                {activityBranchTabLabel("lab_b")}
              </h3>
              <div className="chart chart--equity-stack" title={`${activityBranchTabLabel("lab_b")} equity over time.`}>
                <EquityDualLineChart
                  data={chartDataLabB}
                  equityStroke="#f59e0b"
                  mtmStroke="#fcd34d"
                  revision={`${equityChartRevision(equitySnapsLabB, chartDataLabB, metricsLabB)}|tick=${String(engineLabB?.last_tick_at || "")}`}
                />
              </div>
            </div>
              <div className="dash-equity-chart-block">
              <h3
                className="dash-equity-branch-head section-tip"
                title={`${activityBranchTabLabel("lab_c")}: book value (solid) vs current worth (dashed). MTM refreshed from Kalshi on each dashboard poll.`}
              >
                {activityBranchTabLabel("lab_c")}
              </h3>
              <div className="chart chart--equity-stack" title={`${activityBranchTabLabel("lab_c")} equity over time.`}>
                <EquityDualLineChart
                  data={chartDataLabC}
                  equityStroke="#f472b6"
                  mtmStroke="#fbcfe8"
                  revision={`${equityChartRevision(equitySnapsLabC, chartDataLabC, metricsLabC)}|tick=${String(engineLabC?.last_tick_at || "")}`}
                />
              </div>
            </div>
            <div className="dash-equity-chart-block">
              <h3
                className="dash-equity-branch-head section-tip"
                title={`${activityBranchTabLabel("lab_d")}: book value (solid) vs current worth (dashed). MTM refreshed from Kalshi on each dashboard poll.`}
              >
                {activityBranchTabLabel("lab_d")}
              </h3>
              <div className="chart chart--equity-stack" title={`${activityBranchTabLabel("lab_d")} equity over time.`}>
                <EquityDualLineChart
                  data={chartDataLabD}
                  equityStroke="#fca5a5"
                  mtmStroke="#fecaca"
                  revision={`${equityChartRevision(equitySnapsLabD, chartDataLabD, metricsLabD)}|tick=${String(engineLabD?.last_tick_at || "")}`}
                />
              </div>
            </div>
          </div>
        </div>

        <div className="panel dashboard-grid-panel">
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
                title="How to read asset watch snapshots."
                onClick={() =>
                  setInfoPopup({
                    title: "Assets to watch",
                    body: (
                      <div className="dash-section__legend">
                        <p>
                          Snapshots are per-asset/per-branch engine reads. The branch tabs switch which branch snapshot is
                          shown; they do not change your underlying config.
                        </p>
                        <p>
                          Asset scanning is controlled by each asset&apos;s <code>enabled</code> flag in config. "No snapshot"
                          usually means the branch engine is off, Kalshi has not published quotes yet, or the branch has not
                          ticked since startup.
                        </p>
                        <p>
                          On non-production Kalshi hosts, many 15m rows can show delayed/missing books (for example 0.00
                          bid/ask or "Target price: TBD"). That indicates unavailable quotes on that environment, not an app
                          filter issue.
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
            orderedAssetEntries(assets as AnyObj).map(([id, a]: [string, AnyObj]) => {
              const posRow = (acctSnap?.position_by_asset as AnyObj | undefined)?.[id] as AnyObj | undefined;
              const openRowsTab = dedupeAssetWatchOpenRowsByTicker(assetWatchOpenRowsForTab(posRow, assetWatchLab));
              const hasExposureTab = openRowsTab.length > 0;
              const exposureLabelsTab = exposureLabelsForAssetWatchTab(posRow, assetWatchLab);
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
            })
          )}

        </div>

        <div className="panel dashboard-grid-panel">
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
                title="How account and holdings data are sourced."
                onClick={() =>
                  setInfoPopup({
                    title: "Account and holdings",
                    body: (
                      <div className="dash-section__legend">
                        <p>
                          When Kalshi credentials are linked, this section shows signed portfolio balance/positions from
                          exchange APIs. Without credentials, the dashboard still uses public market data but omits exchange
                          account details.
                        </p>
                        <p>
                          Sim columns are local SQLite paper rows by branch (Live/Lab A/B/C/D). Kalshi columns are exchange
                          positions; the two can differ during paper testing.
                        </p>
                        <p>
                          If account data is missing, set <code>KALSHI_API_KEY_ID</code> and your RSA private key in{" "}
                          <code>.env</code>, restart the backend, then reload.
                        </p>
                        <p>
                          Holdings table glossary: "market lines" = distinct exposed tickers in a cell; "contracts" = summed
                          YES/NO position size on those lines.
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

          <div style={{ marginTop: 8 }}>
            {acctSnap?.position_by_asset && Object.keys(acctSnap.position_by_asset).length > 0 ? (
              <div style={{ overflowX: "auto" }} title="Per configured asset: where exposure shows up.">
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

          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, marginTop: 14 }}>
            <h3 className="section-tip" style={{ margin: 0, fontSize: 14, color: "var(--muted)" }} title="Branch engine status for the selected account tab.">
              Engine
            </h3>
          </div>
          <div className="sub" title="Engine polling status from /api/dashboard.">
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

          <div style={{ marginTop: 16 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
              <h3 className="section-tip" style={{ margin: 0, fontSize: 16 }} title="Recent signal/trade rows from SQLite logs.">
                Activity log
              </h3>
              <button
                type="button"
                className="chart-tab"
                style={{ padding: "4px 10px" }}
                title="How branch filters apply in activity tables."
                onClick={() =>
                  setInfoPopup({
                    title: "Activity log",
                    body: (
                      <div className="dash-section__legend">
                        <p>
                          The API sends up to 500 recent signals and 500 trades across branches; each tab shows rows whose
                          branch matches (legacy sim_lab counts as Lab A). Use branch tabs for <code>lab_b</code>,{" "}
                          <code>lab_c</code>, and <code>lab_d</code> rows.
                        </p>
                        <p style={{ fontSize: 12, color: "#9aa6cc", marginTop: 8 }}>
                          Recent signals/trades use one branch filter; <strong>Bets not traded</strong> uses its own independent
                          branch tabs below.
                        </p>
                      </div>
                    ),
                  })
                }
              >
                Info
              </button>
            </div>
            <div style={{ marginTop: 10 }}>
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

              {accountActivityView === "signals" ? (
                <div className="panel">
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
                <div className="panel">
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
                <div className="panel">
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
        onSavePaperFees={savePaperFees}
        optimizerCfg={(cfg?.optimizer || optimizerCfg || {}) as AnyObj}
        onSaveOptimizerConfig={saveOptimizerConfig}
        optimizerSaving={optimizerSaving}
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
      />
      <HistoricalExplorerOverlay open={historyOpen} onClose={() => setHistoryOpen(false)} />
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

function ApiLoadingCallout() {
  return (
    <div className="callout callout-loading" title="Waiting for first successful /api/dashboard response.">
      <h2 className="callout-title" title="Initial load in progress.">
        Loading dashboard…
      </h2>
      <p className="callout-body" title="If this never clears, start the Python API and use the Vite dev URL (proxied /api).">
        Contacting the local API at /api/dashboard. The first response can take a long time when Kalshi portfolio / MTM
        work is heavy — wait up to about 90s before assuming the backend is down. If it never clears, start the Python
        API and open this app at <code>http://localhost:5173</code> (not the API port alone) so <code>/api</code> is
        proxied.
      </p>
    </div>
  );
}

/** One-row Kalshi API + getting-started status; hover each orb for the old card/checklist copy. */
function KalshiSetupOrbRow({ dash, cfg }: { dash: AnyObj | null; cfg: AnyObj }) {
  const k = dash?.kalshi as AnyObj | undefined;
  if (!dash || !k) return null;
  const cred = (k.credentials || {}) as AnyObj;
  const credOk = Boolean(cred.api_key_id_configured) && Boolean(cred.private_key_configured);
  const pub = Boolean(k.public_ok);
  const priv = Boolean(k.private_ok);
  const simLive = Boolean(k.simulate_live);
  const writes = Boolean(k.order_writes_live);
  const poll = Boolean(k.polling_enabled);
  const pos = Number(k.position_count ?? 0);
  const ord = Number(k.resting_order_count ?? 0);
  const notes = k.portfolio_notes ? String(k.portfolio_notes) : "";

  const writeDetail = simLive
    ? "Live branch uses paper fills; Kalshi does not receive orders from Live."
    : writes
      ? "Live branch can POST limit orders when the Live engine is on and a rule matches."
      : priv
        ? "Authenticated but order posting is not enabled for this configuration."
        : "Fix authentication before enabling real orders.";

  let writeState: "ok" | "warn" | "bad";
  if (simLive) writeState = "ok";
  else if (writes) writeState = "warn";
  else if (priv) writeState = "warn";
  else writeState = "bad";

  const orbs: {
    step: number;
    title: string;
    subtitle: string;
    hint: string;
    state: "ok" | "warn" | "bad";
  }[] = [
    {
      step: 1,
      title: "Backend and this page are running",
      subtitle: "Dashboard",
      hint: "You already loaded the dashboard from npm run dev with the API proxy.",
      state: dash ? "ok" : "bad",
    },
    {
      step: 2,
      title: "Configure .env for Kalshi",
      subtitle: "Keys in .env",
      hint:
        cred.private_key_source === "file_missing"
          ? "KALSHI_PRIVATE_KEY_PATH points to a file that was not found."
          : "Copy .env.example to .env in the repo root; set KALSHI_API_KEY_ID and PEM path or KALSHI_PRIVATE_KEY_PEM.",
      state: credOk ? "ok" : "warn",
    },
    {
      step: 3,
      title: "Markets (public read)",
      subtitle: pub ? "Reachable" : "Unreachable",
      hint: pub
        ? "Kalshi public API responded OK. Used for quotes, series, and sim settlement checks."
        : "Cannot reach public Kalshi API. Check KALSHI_ENV and network.",
      state: pub ? "ok" : "bad",
    },
    {
      step: 4,
      title: "Portfolio (private read)",
      subtitle: priv ? `Signed in · ${pos} pos, ${ord} orders` : pub ? "Public only" : "Not signed in",
      hint: priv
        ? `Signed portfolio API. Loaded ${pos} position(s), ${ord} resting order(s).`
        : "Needs KALSHI_API_KEY_ID + RSA private key in .env (restart backend). Optional for public-only paper.",
      state: priv ? "ok" : pub ? "warn" : "bad",
    },
    {
      step: 5,
      title: "Turn on an engine to stream markets into the bot",
      subtitle: poll ? "Polling on" : "Engines idle",
      hint: "Enable Live engine and/or labs so ticks run and markets_scanned updates.",
      state: poll ? "ok" : "warn",
    },
    {
      step: 6,
      title: "Live mode (simulate vs real)",
      subtitle: cfg.simulate ? "Paper (simulate)" : "Real $",
      hint: cfg.simulate
        ? "Simulate is on — Live branch will not POST orders to Kalshi."
        : "Real $ is on — Live branch can POST limit orders when the Live engine runs and a rule matches.",
      state: cfg.simulate ? "ok" : "warn",
    },
    {
      step: 7,
      title: "Live orders (write)",
      subtitle: simLive ? "Simulated" : writes ? "Real posts on" : "Blocked",
      hint: writeDetail,
      state: writeState,
    },
    {
      step: 8,
      title: "Portfolio notes",
      subtitle: notes ? "See tooltip" : "No warnings",
      hint: notes || "No extra portfolio notes from the last signed read.",
      state: notes ? "warn" : "ok",
    },
  ];

  return (
    <div
      className="kalshi-setup-orbs section-tip"
      role="list"
      title="Kalshi API (read / write) and getting started — hover each dot for status."
      aria-label="Kalshi connection and setup checklist as compact status dots"
    >
      {orbs.map((o) => {
        const fullTitle = `${o.step}. ${o.title} · ${o.subtitle} — ${o.hint}`;
        const tone = o.state;
        return (
          <span
            key={o.step}
            className={`kalshi-setup-orb kalshi-setup-orb--${tone} section-tip`}
            role="listitem"
            title={fullTitle}
            aria-label={`${o.title}. ${o.subtitle}. ${o.hint}`}
          >
            {o.state === "ok" ? "✓" : o.step}
          </span>
        );
      })}
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
  if (k.public_ok && !k.private_ok) {
    blocks.push({
      tone: "info",
      text: `Public data only — no Kalshi account linked. Quotes, series, and engine ticks use the public API; balance and exchange positions stay hidden until you add KALSHI_API_KEY_ID and your RSA private key to .env (optional for paper / signals).${k.private_error ? ` ${String(k.private_error)}` : ""}`,
      detail:
        "This is expected if you have not configured signing keys. Simulated trades are still stored locally.",
    });
  }
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

function SignalsTable({ rows, emptyTitle }: { rows: AnyObj[]; emptyTitle?: string }) {
  if (!rows.length)
    return (
      <div className="sub" title="No signal rows for this branch in the current sample; engines only write signals on certain paths.">
        {emptyTitle ?? "No signals yet."}
      </div>
    );
  return (
    <div className="table-scroll" title="Scroll vertically for older rows; header stays visible.">
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

function TradesTable({ rows, emptyTitle }: { rows: AnyObj[]; emptyTitle?: string }) {
  if (!rows.length)
    return (
      <div className="sub" title="No trades for this branch in the current sample; engine creates trades on fills or sim orders.">
        {emptyTitle ?? "No trades yet."}
      </div>
    );
  return (
    <div className="table-scroll" title="Scroll vertically for older rows; header stays visible.">
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

