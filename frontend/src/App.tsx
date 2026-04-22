import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import SettingsOverlay from "./SettingsOverlay";
import HistoricalExplorerOverlay from "./HistoricalExplorerOverlay";
import { BranchMarketTickers } from "./BranchMarketTickers";

type AnyObj = Record<string, any>;

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
  if (!r.ok) throw new Error(`${path} ${r.status}`);
  return await r.json();
}

async function apiPost(path: string) {
  const r = await fetch(path, { method: "POST" });
  if (!r.ok) throw new Error(`${path} ${r.status}`);
  return await r.json();
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

function MetricTile({
  label,
  value,
  title,
  sub,
}: {
  label: string;
  value: ReactNode;
  title: string;
  sub?: ReactNode;
}) {
  return (
    <div className="metric" title={title}>
      <div className="k" title={title}>
        {label}
      </div>
      <div className="v" title={title}>
        {value}
      </div>
      {sub != null && sub !== "" ? (
        <div className="metric-sub" title={title}>
          {sub}
        </div>
      ) : null}
    </div>
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

function summarizePositionRows(rows: unknown): string {
  const arr = Array.isArray(rows) ? (rows as AnyObj[]) : [];
  if (!arr.length) return "—";
  return arr
    .map((r) => {
      const t = String(r.ticker || "").slice(0, 40);
      const q = r.position != null ? String(r.position) : String(r.contracts_fp ?? "");
      return `${t} (${q})`;
    })
    .join("; ");
}

function positionRowHasOpenExposure(row: unknown): boolean {
  if (!row || typeof row !== "object") return false;
  const o = row as AnyObj;
  const nonempty = (x: unknown) => Array.isArray(x) && (x as AnyObj[]).length > 0;
  return (
    nonempty(o.kalshi_open) ||
    nonempty(o.bot_sim_open_live) ||
    nonempty(o.bot_sim_open_lab) ||
    nonempty(o.bot_sim_open_lab_a) ||
    nonempty(o.bot_sim_open_lab_b)
  );
}

function exposureChannelLabels(row: unknown): string[] {
  if (!row || typeof row !== "object") return [];
  const o = row as AnyObj;
  const out: string[] = [];
  if (Array.isArray(o.kalshi_open) && o.kalshi_open.length) out.push("Kalshi");
  if (Array.isArray(o.bot_sim_open_live) && o.bot_sim_open_live.length) out.push("Sim · Live");
  const labA =
    (Array.isArray(o.bot_sim_open_lab_a) && o.bot_sim_open_lab_a.length) ||
    (Array.isArray(o.bot_sim_open_lab) && o.bot_sim_open_lab.length);
  if (labA) out.push("Sim · Lab A");
  if (Array.isArray(o.bot_sim_open_lab_b) && o.bot_sim_open_lab_b.length) out.push("Sim · Lab B");
  return out;
}

/** Normalize SQLite `branch` onto dashboard tabs (legacy sim_lab → Lab A). */
type ActivityBranchKey = "live" | "lab_a" | "lab_b";

function normalizeSignalTradeBranch(b: unknown): ActivityBranchKey {
  const s = String(b ?? "live").trim().toLowerCase();
  if (s === "lab_a" || s === "sim_lab") return "lab_a";
  if (s === "lab_b") return "lab_b";
  return "live";
}

function activityBranchTabLabel(b: ActivityBranchKey): string {
  if (b === "live") return "Live";
  if (b === "lab_a") return "Lab A";
  return "Lab B";
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
): { t: string; equity: number }[] {
  const rows = snaps
    .map((s) => ({
      at: String(s.created_at || ""),
      eq: Number(s.equity_cents || 0) / 100.0,
      ts: new Date(String(s.created_at || "")).getTime(),
    }))
    .filter((r) => r.at && Number.isFinite(r.ts));
  rows.sort((a, b) => a.ts - b.ts);

  if (mode === "intraday") {
    return rows.slice(-400).map((r) => ({
      t: fmtIsoLocalFn(r.at, false),
      equity: r.eq,
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

  const best = new Map<string, { ts: number; eq: number; sampleIso: string }>();
  for (const r of rows) {
    const b = bucketKey(r.at);
    if (!b) continue;
    const cur = best.get(b);
    if (!cur || r.ts >= cur.ts) best.set(b, { ts: r.ts, eq: r.eq, sampleIso: r.at });
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
    return { t, equity: cell.eq };
  });
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
  const pYes =
    hasBook && snap.implied_prob != null && Number.isFinite(Number(snap.implied_prob))
      ? Math.min(1, Math.max(0, Number(snap.implied_prob)))
      : null;
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
                <span title="Implied YES probability from order book (mid / bid-ask when both exist).">~{yesPctStr}</span>
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
      {pYes != null ? <SnapSentimentBar impliedYes01={pYes} /> : null}
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
          <strong style={{ color: "#ffc878" }} title="No band matched this tick (or no book).">
            NONE
          </strong>
        ) : (
          <span style={{ color: "var(--ok)", fontWeight: 600 }} title="Matched rule names from the engine.">
            {rules.join(", ")}
          </span>
        )}
        {stale}
      </div>
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
  const [assetWatchLab, setAssetWatchLab] = useState<"live" | "a" | "b">("live");
  const [activityBranch, setActivityBranch] = useState<ActivityBranchKey>("live");
  const [equityGranularity, setEquityGranularity] = useState<EquityGranularity>("intraday");

  const refresh = async () => {
    try {
      setErr(null);
      const d = await apiGet<AnyObj>("/api/dashboard");
      setDash(d);
    } catch (e: any) {
      const msg = String(e?.message || e);
      if (/Failed to fetch|NetworkError|network error|Load failed|ECONNREFUSED/i.test(msg)) {
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
    }
  };

  useEffect(() => {
    refresh();
    const id = window.setInterval(refresh, 2500);
    return () => window.clearInterval(id);
  }, []);

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
    const history = Array.isArray(optimizerCfg?.change_history) ? (optimizerCfg.change_history as AnyObj[]) : [];
    if (!history.length) return;
    const fresh = history.filter((h) => {
      const id = String(h?.id || "");
      return id && !seenOptimizerEventIds.current.has(id);
    });
    if (!fresh.length) return;
    for (const h of fresh) {
      const id = String(h?.id || "");
      if (!id) continue;
      seenOptimizerEventIds.current.add(id);
      const title = String(h?.lab_label || h?.branch || "Lab optimizer");
      const body = String(h?.summary || "Optimizer updated thresholds.");
      setOptimizerNotifs((prev) => [{ id, title, body, created_at: h?.created_at }, ...prev].slice(0, 8));
      if ("Notification" in window) {
        if (Notification.permission === "granted") {
          void new Notification(`${title} optimizer update`, { body });
        } else if (Notification.permission === "default") {
          void Notification.requestPermission().then((p) => {
            if (p === "granted") void new Notification(`${title} optimizer update`, { body });
          });
        }
      }
    }
  }, [optimizerCfg?.change_history]);

  const cfg = dash?.config || {};
  const metrics = dash?.metrics || {};
  const metricsLabA = (dash?.metrics_lab_a || dash?.metrics_sim_lab || {}) as AnyObj;
  const metricsLabB = (dash?.metrics_lab_b || {}) as AnyObj;
  const snaps = (dash?.equity_snapshots || []) as AnyObj[];
  const equitySnapsLabA = (dash?.equity_snapshots_lab_a || dash?.equity_snapshots_sim_lab || []) as AnyObj[];
  const equitySnapsLabB = (dash?.equity_snapshots_lab_b || []) as AnyObj[];
  const labA = ((cfg.lab_a || cfg.sim_lab) || {}) as AnyObj;
  const labB = (cfg.lab_b || {}) as AnyObj;
  // Backward-compatible aliases while we expand UI sections incrementally.
  const simLab = labA;

  const chartData = useMemo(
    () => buildEquityChartSeries(snaps, equityGranularity, fmtIsoLocal),
    [snaps, equityGranularity],
  );

  const chartDataLabA = useMemo(
    () => buildEquityChartSeries(equitySnapsLabA, equityGranularity, fmtIsoLocal),
    [equitySnapsLabA, equityGranularity],
  );
  const chartDataLabB = useMemo(
    () => buildEquityChartSeries(equitySnapsLabB, equityGranularity, fmtIsoLocal),
    [equitySnapsLabB, equityGranularity],
  );

  const assets = (cfg.assets || {}) as AnyObj;
  const assetSnaps = (dash?.asset_snapshots || {}) as AnyObj;
  const engineSnapsLive = (assetSnaps.live || {}) as AnyObj;
  const engineSnapsLabA = ((assetSnaps.lab_a || assetSnaps.sim_lab) || {}) as AnyObj;
  const engineSnapsLabB = (assetSnaps.lab_b || {}) as AnyObj;
  const engineLabA = (dash?.engine?.lab_a ?? dash?.engine?.sim_lab) as AnyObj | undefined;
  const engineLabB = dash?.engine?.lab_b as AnyObj | undefined;

  const recentSignalsFiltered = useMemo(() => {
    const rs = (dash?.recent_signals || []) as AnyObj[];
    return rs.filter((r) => normalizeSignalTradeBranch(r.branch) === activityBranch);
  }, [dash?.recent_signals, activityBranch]);

  const recentTradesFiltered = useMemo(() => {
    const rt = (dash?.recent_trades || []) as AnyObj[];
    return rt.filter((r) => normalizeSignalTradeBranch(r.branch) === activityBranch);
  }, [dash?.recent_trades, activityBranch]);

  const notTradedFiltered = useMemo(() => {
    const nt = (dash?.not_traded_signals || []) as AnyObj[];
    return nt.filter((r) => normalizeSignalTradeBranch(r.branch) === activityBranch);
  }, [dash?.not_traded_signals, activityBranch]);

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
    setBusy(true);
    try {
      await apiPost(`/api/engine/toggle?simulate=${simulate ? "true" : "false"}`);
      await refresh();
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  };

  const setRunning = async (running: boolean) => {
    setBusy(true);
    try {
      await apiPost(`/api/engine/toggle?running=${running ? "true" : "false"}`);
      await refresh();
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  };

  const setLabRunning = async (lab: "a" | "b", running: boolean) => {
    setBusy(true);
    try {
      const key = lab === "a" ? "lab_a_running" : "lab_b_running";
      await apiPost(`/api/engine/toggle?${key}=${running ? "true" : "false"}`);
      await refresh();
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  };
  const setSimLabRunning = async (running: boolean) => setLabRunning("a", running);

  const saveLabFromSliders = async (lab: "a" | "b") => {
    const p = `lab_${lab}`;
    const frac = Number((document.getElementById(`${p}_frac`) as HTMLInputElement)?.value);
    const win = Number((document.getElementById(`${p}_win`) as HTMLInputElement)?.value);
    const paper = Number((document.getElementById(`${p}_paper`) as HTMLInputElement)?.value);
    const opt = Boolean((document.getElementById(`${p}_opt`) as HTMLInputElement)?.checked);
    const autoReset = Boolean((document.getElementById(`${p}_auto_reset_failure`) as HTMLInputElement)?.checked);
    setBusy(true);
    try {
      await apiPut("/api/config", {
        [lab === "a" ? "lab_a" : "lab_b"]: {
          ...(lab === "a" ? labA : labB),
          balance_fraction_per_window: frac,
          window_minutes: win,
          paper_balance_cents: paper,
          auto_optimize: opt,
          auto_reset_paper_on_tick_failure: autoReset,
        },
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

  const saveLabRules = async (lab: "a" | "b", rules: AnyObj[]) => {
    setBusy(true);
    try {
      await apiPut("/api/config", {
        [lab === "a" ? "lab_a" : "lab_b"]: {
          ...(lab === "a" ? labA : labB),
          rules,
        },
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

  const resetTradingData = async (branch: "all" | "live" | "lab_a" | "lab_b", backup: boolean) => {
    setBusy(true);
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
    <div className="page" title="Kalshi 15m bot — main dashboard. Hover controls for details.">
      {optimizerNotifs.length ? (
        <div style={{ position: "fixed", top: 14, right: 14, zIndex: 1200, width: "min(360px, 92vw)", display: "grid", gap: 8 }}>
          {optimizerNotifs.map((n) => (
            <div key={String(n.id)} className="panel" style={{ padding: "10px 12px", borderColor: "#355091" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                <strong style={{ fontSize: 12 }}>{String(n.title)}</strong>
                <button
                  type="button"
                  style={{ padding: "2px 8px", fontSize: 11 }}
                  onClick={() => setOptimizerNotifs((prev) => prev.filter((x) => String(x.id) !== String(n.id)))}
                >
                  x
                </button>
              </div>
              <div className="sub" style={{ marginTop: 4, fontSize: 12, lineHeight: 1.35 }}>
                {String(n.body)}
              </div>
            </div>
          ))}
        </div>
      ) : null}
      <div className="top">
        <div className="hero">
          <h1
            className="title section-tip"
            title="15-minute crypto series, rule-based entries. Simulate = paper on the Live branch; Real $ can POST limit orders when the Live engine runs and a rule matches. Sim lab is always paper and uses separate sizing."
          >
            Kalshi 15m crypto bot
          </h1>
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
        </div>
        <div className="toolbar-panel">
          <div className="toolbar toolbar--dock">
            <div className="toolbar-block" title="Refresh dashboard data and open full settings.">
              <div className="toolbar-label">Controls</div>
              <div className="toolbar-group">
                <button
                  className="primary"
                  disabled={busy}
                  title="Fetch /api/dashboard now (this page also auto-refreshes every ~2.5s)."
                  onClick={() => refresh()}
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
            <div className="toolbar-block" title="Always-paper engines with their own parameters.">
              <div className="toolbar-label">Labs</div>
              <div className="toolbar-group">
                <button
                  className="primary"
                  disabled={busy}
                  title="Parallel paper engine with its own sizing/window; uses the same market data as Live. Always simulated."
                  onClick={() => setSimLabRunning(!Boolean(engineLabA?.engine_running ?? simLab.engine_running))}
                >
                  A {engineLabA?.engine_running ? "on" : "off"}
                </button>
                <button
                  className="primary"
                  disabled={busy}
                  title="Second parallel paper engine for A/B testing."
                  onClick={() => setLabRunning("b", !Boolean(labB.engine_running))}
                >
                  B {engineLabB?.engine_running ? "on" : "off"}
                </button>
              </div>
            </div>
          </div>
          <div className="toolbar-optimizer-foot" title="Anthropic-backed recommendations from Lab A/B data only.">
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
                          interval_minutes: Number(optimizerCfg?.interval_minutes || 120),
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
      <ConnectionStrip kalshi={kalshi} />
      <SetupChecklist dash={dash} cfg={cfg} />
      <KalshiStatusBanner dash={dash} cfg={cfg} />

      <div className="metrics" style={{ marginBottom: 8 }}>
        <div
          className="section-tip"
          style={{ gridColumn: "1 / -1", color: "var(--muted)", fontSize: 12, marginBottom: 6 }}
          title={
            cfg.simulate
              ? "Live branch is paper: simulated fills only. Equity = starting bankroll + realized settled PnL − premium tied up in open sim positions."
              : "Live branch posts real limit orders when the engine runs and rules match. Cash / portfolio value come from Kalshi signed portfolio reads."
          }
        >
          Live strategy ({cfg.simulate ? "paper" : "real fills"})
        </div>
        <p
          className="sub section-tip"
          style={{ gridColumn: "1 / -1", fontSize: 11, lineHeight: 1.45, margin: "0 0 8px 0" }}
          title="Paper: settled = Kalshi finalized the contract; open = still waiting. Real: bot PnL is still from this app’s trade log for the Live branch."
        >
          <strong>Settled</strong> = closed in SQLite with realized PnL (Kalshi must finalize the contract for sim).{" "}
          <strong>Open (paper)</strong> = premium held in open sim rows (subtracted from estimated equity).{" "}
          {!cfg.simulate ? (
            <>
              <strong>Cash / portfolio</strong> = Kalshi balance API (needs linked keys).
            </>
          ) : null}
        </p>
        {cfg.simulate ? (
          <p
            className="sub section-tip"
            style={{ gridColumn: "1 / -1", fontSize: 11, lineHeight: 1.45, margin: "-4px 0 8px 0" }}
            title="Metrics use every row in SQLite for this branch (not just the Recent trades table). Equity = bankroll + realized PnL − committed open premium."
          >
            <strong>Reconcile paper:</strong> <em>Equity (est.)</em> = bankroll + <em>Total PnL (realized)</em> −{" "}
            <em>Committed</em>. Large realized PnL with negative return means a lot of premium is still tied up in open
            contracts until they settle or swing-exit.
          </p>
        ) : null}
        {metrics.equity_snap_vs_calc_diff_dollars != null &&
        Number.isFinite(Number(metrics.equity_snap_vs_calc_diff_dollars)) &&
        Math.abs(Number(metrics.equity_snap_vs_calc_diff_dollars)) > 0.001 ? (
          <p
            className="sub section-tip"
            style={{ gridColumn: "1 / -1", fontSize: 11, color: "#ffc878", margin: "0 0 8px 0" }}
            title="The last equity snapshot row differs from bankroll + PnL − committed; usually timing between ticks."
          >
            Note: last equity snapshot differs from estimated equity by{" "}
            {fmtMoney(Number(metrics.equity_snap_vs_calc_diff_dollars))}.
          </p>
        ) : null}

        {cfg.simulate ? (
          <>
            <MetricTile
              label="Bankroll (start)"
              value={fmtMoney(Number(metrics.paper_start_dollars ?? 0))}
              title="cfg.paper_balance_cents ÷ 100 — notional starting stack for the Live branch in simulate mode (Settings)."
            />
            <MetricTile
              label="Equity (est.)"
              value={fmtMoney(Number(metrics.current_equity_dollars ?? 0))}
              title="paper_start + total settled PnL − open sim committed premium. Same formula the engine uses for paper equity snapshots."
              sub={`Return vs start ${fmtPct(metrics.return_vs_start_pct)} · chart last ${metrics.latest_equity_snapshot_dollars != null ? fmtMoney(Number(metrics.latest_equity_snapshot_dollars)) : "—"}`}
            />
            <MetricTile
              label="Total PnL (realized)"
              value={fmtMoney(Number(metrics.total_pnl_dollars || 0))}
              title="Sum of pnl_cents / 100 for Live-branch trades with status settled and mode matching Live (simulate)."
              sub={`${fmtPct(metrics.realized_pnl_pct_of_start)} of starting bankroll`}
            />
            <MetricTile
              label="Total Kalshi fees"
              value={fmtMoney(Number(metrics.total_kalshi_fees_dollars || 0))}
              title="Modeled entry + exit fees accumulated from trade extra_json for this branch/mode."
            />
            <MetricTile
              label="Avg hourly (realized)"
              value={fmtMoney(Number(metrics.avg_hourly_pnl_dollars || 0))}
              title="total realized PnL divided by hours between first and last settled trade timestamps on this branch (min ~1h denominator)."
            />
            <MetricTile
              label="Settled trades"
              value={String(metrics.settled_trades ?? 0)}
              title="Count of Live-branch settled rows in SQLite (simulated fills after Kalshi finalization)."
            />
            <MetricTile
              label="Win / loss"
              value={`${String(metrics.wins ?? 0)} / ${String(metrics.losses ?? 0)}${
                Number(metrics.scratch_trades) > 0 ? ` · ${String(metrics.scratch_trades)} flat` : ""
              }`}
              title="Wins and losses use settled PnL sign. Flat = settled at exactly $0 (swing scratch or even money); not counted in win/loss columns."
            />
            <MetricTile
              label="Win rate"
              value={fmtPct(
                Number(metrics.wins ?? 0) + Number(metrics.losses ?? 0) > 0
                  ? metrics.win_rate_decisive_pct
                  : metrics.win_rate_pct,
              )}
              title="wins ÷ (wins + losses) when there is at least one decisive outcome; otherwise wins ÷ settled. Full-table SQL, same scope as Total PnL."
            />
            <MetricTile
              label="Avg PnL / settled"
              value={
                metrics.avg_realized_per_settled_dollars != null
                  ? fmtMoney(Number(metrics.avg_realized_per_settled_dollars))
                  : "—"
              }
              title="total_pnl_dollars ÷ settled_trades — mean realized dollars per closed trade."
            />
            <MetricTile
              label="Loss rate"
              value={fmtPct(
                Number(metrics.wins ?? 0) + Number(metrics.losses ?? 0) > 0
                  ? metrics.loss_rate_decisive_pct
                  : metrics.loss_rate_pct,
              )}
              title="losses ÷ (wins + losses) when decisive outcomes exist; else losses ÷ settled."
            />
            <MetricTile
              label="Open (paper)"
              value={String(metrics.open_sim_trades ?? 0)}
              title="Simulated Live-branch trades still status open/resting until Kalshi market is finalized."
            />
            <MetricTile
              label="Committed"
              value={fmtMoney(Number(metrics.open_sim_committed_dollars || 0))}
              title="Sum of amount_cents for those open sim trades ÷ 100 — premium tied up until settlement."
              sub={fmtPct(metrics.committed_pct_of_start) + " of bankroll"}
            />
          </>
        ) : (
          <>
            <MetricTile
              label="Cash (Kalshi)"
              value={
                metrics.exchange_balance_dollars != null
                  ? fmtMoney(Number(metrics.exchange_balance_dollars))
                  : "—"
              }
              title="Signed GET /portfolio/balance — balance field as dollars (cents ÷ 100). Requires prod/demo keys matching KALSHI_ENV."
            />
            <MetricTile
              label="Portfolio value"
              value={
                metrics.exchange_portfolio_value_dollars != null
                  ? fmtMoney(Number(metrics.exchange_portfolio_value_dollars))
                  : "—"
              }
              title="Same balance response: portfolio_value when Kalshi returns it (optional field; may be — if absent)."
            />
            <MetricTile
              label="Bot settled PnL"
              value={fmtMoney(Number(metrics.total_pnl_dollars || 0))}
              title="Sum of realized pnl from this bot’s logged Live-branch live-mode fills (SQLite), not the entire exchange account."
            />
            <MetricTile
              label="Total Kalshi fees"
              value={fmtMoney(Number(metrics.total_kalshi_fees_dollars || 0))}
              title="Modeled entry + exit fees accumulated from trade extra_json for this branch/mode."
            />
            <MetricTile
              label="Avg hourly (bot)"
              value={fmtMoney(Number(metrics.avg_hourly_pnl_dollars || 0))}
              title="Bot realized PnL per wall-clock hour between first and last settled trade on Live live mode."
            />
            <MetricTile
              label="Settled (bot)"
              value={String(metrics.settled_trades ?? 0)}
              title="Closed trades this bot recorded for Live branch, live mode."
            />
            <MetricTile
              label="Win / loss"
              value={`${String(metrics.wins ?? 0)} / ${String(metrics.losses ?? 0)}${
                Number(metrics.scratch_trades) > 0 ? ` · ${String(metrics.scratch_trades)} flat` : ""
              }`}
              title="Among bot-settled trades on Live live mode; flat = $0 PnL."
            />
            <MetricTile
              label="Win rate"
              value={fmtPct(
                Number(metrics.wins ?? 0) + Number(metrics.losses ?? 0) > 0
                  ? metrics.win_rate_decisive_pct
                  : metrics.win_rate_pct,
              )}
              title="wins ÷ (wins + losses) when decisive; else wins ÷ settled (full-table SQL)."
            />
            <MetricTile
              label="Avg PnL / settled"
              value={
                metrics.avg_realized_per_settled_dollars != null
                  ? fmtMoney(Number(metrics.avg_realized_per_settled_dollars))
                  : "—"
              }
              title="Mean realized dollars per closed bot trade."
            />
            <MetricTile
              label="Open (paper)"
              value={String(metrics.open_sim_trades ?? 0)}
              title="Usually 0 in real mode; any leftover simulated opens if you switched modes mid-session."
            />
            <MetricTile
              label="Committed"
              value={fmtMoney(Number(metrics.open_sim_committed_dollars || 0))}
              title="Open sim premium if any (see tooltip on Open)."
            />
          </>
        )}
      </div>

      <div
        className="section-tip"
        style={{ marginBottom: 8, color: "var(--muted)", fontSize: 12 }}
        title="Paper-only A/B engines: separate SQLite branches, sizing, rules, and bankrolls. No real order posts."
      >
        Simulation labs overview
      </div>
      <p
        className="sub section-tip"
        style={{ margin: "0 0 14px 0", fontSize: 11, lineHeight: 1.45 }}
        title="Each block below is scoped to one branch only, same layout idea as Live strategy metrics."
      >
        Metrics below are <strong>not mixed</strong>: Lab A uses only <code>branch=lab_a</code> (legacy <code>sim_lab</code> counts as Lab A); Lab B uses only{" "}
        <code>branch=lab_b</code>. Unset per-lab paper balance falls back to global paper balance.
      </p>

      <div className="metrics" style={{ marginBottom: 14 }}>
        <div
          className="section-tip"
          style={{ gridColumn: "1 / -1", color: "var(--muted)", fontSize: 12, marginBottom: 6 }}
          title="Lab A paper branch: lab_a (legacy sim_lab rollups align here)."
        >
          Lab A (always paper, branch lab_a)
        </div>
        <p
          className="sub section-tip"
          style={{ gridColumn: "1 / -1", fontSize: 11, lineHeight: 1.45, margin: "0 0 8px 0" }}
          title="Lab A equity uses full SQLite rollups for lab_a, not only the Recent tables."
        >
          <strong>Reconcile Lab A:</strong> <em>Equity (est.)</em> = bankroll + <em>Total PnL (realized)</em> −{" "}
          <em>Committed</em>. Positive realized PnL with a down return usually means premium still tied up in open Lab A
          positions.
        </p>
        <MetricTile
          label="Lab A bankroll (start)"
          value={fmtMoney(Number(metricsLabA.paper_start_dollars ?? 0))}
          title="lab_a.paper_balance_cents if set, else cfg.paper_balance_cents."
        />
        <MetricTile
          label="Lab A equity (est.)"
          value={fmtMoney(Number(metricsLabA.current_equity_dollars ?? 0))}
          title="Lab A bankroll + settled PnL − open committed."
          sub={`Return vs start ${fmtPct(metricsLabA.return_vs_start_pct)} · chart last ${metricsLabA.latest_equity_snapshot_dollars != null ? fmtMoney(Number(metricsLabA.latest_equity_snapshot_dollars)) : "—"}`}
        />
        <MetricTile
          label="Lab A total PnL"
          value={fmtMoney(Number(metricsLabA.total_pnl_dollars || 0))}
          title="Realized PnL for branch lab_a, mode simulate, status settled."
          sub={`${fmtPct(metricsLabA.realized_pnl_pct_of_start)} of lab bankroll`}
        />
        <MetricTile
          label="Lab A fees"
          value={fmtMoney(Number(metricsLabA.total_kalshi_fees_dollars || 0))}
          title="Modeled entry + exit fees accumulated for Lab A."
        />
        <MetricTile
          label="Lab A avg hourly"
          value={fmtMoney(Number(metricsLabA.avg_hourly_pnl_dollars || 0))}
          title="Lab A realized PnL divided by hours spanned by settled lab_a trades (min ~1h denominator)."
        />
        <MetricTile
          label="Lab A settled"
          value={String(metricsLabA.settled_trades ?? 0)}
          title="Count of settled lab_a simulated trades."
        />
        <MetricTile
          label="Lab A W / L"
          value={`${String(metricsLabA.wins ?? 0)} / ${String(metricsLabA.losses ?? 0)}${
            Number(metricsLabA.scratch_trades) > 0 ? ` · ${String(metricsLabA.scratch_trades)} flat` : ""
          }`}
          title="Wins and losses among settled lab_a rows."
        />
        <MetricTile
          label="Lab A win rate"
          value={fmtPct(
            Number(metricsLabA.wins ?? 0) + Number(metricsLabA.losses ?? 0) > 0
              ? metricsLabA.win_rate_decisive_pct
              : metricsLabA.win_rate_pct,
          )}
          title="Lab A wins ÷ (wins + losses) when decisive outcomes exist."
        />
        <MetricTile
          label="Lab A avg / settled"
          value={
            metricsLabA.avg_realized_per_settled_dollars != null
              ? fmtMoney(Number(metricsLabA.avg_realized_per_settled_dollars))
              : "—"
          }
          title="Lab A total realized PnL ÷ Lab A settled count."
        />
        <MetricTile
          label="Lab A loss rate"
          value={fmtPct(
            Number(metricsLabA.wins ?? 0) + Number(metricsLabA.losses ?? 0) > 0
              ? metricsLabA.loss_rate_decisive_pct
              : metricsLabA.loss_rate_pct,
          )}
          title="Lab A losses ÷ (wins + losses) when decisive outcomes exist."
        />
        <MetricTile
          label="Lab A open"
          value={String(metricsLabA.open_sim_trades ?? 0)}
          title="Open lab_a rows awaiting settlement."
        />
        <MetricTile
          label="Lab A committed"
          value={fmtMoney(Number(metricsLabA.open_sim_committed_dollars || 0))}
          title="Premium tied up in open lab_a positions."
          sub={fmtPct(metricsLabA.committed_pct_of_start) + " of lab bankroll"}
        />
      </div>

      <div className="metrics" style={{ marginBottom: 14 }}>
        <div
          className="section-tip"
          style={{ gridColumn: "1 / -1", color: "var(--muted)", fontSize: 12, marginBottom: 6 }}
          title="Lab B paper branch: lab_b only."
        >
          Lab B (always paper, branch lab_b)
        </div>
        <p
          className="sub section-tip"
          style={{ gridColumn: "1 / -1", fontSize: 11, lineHeight: 1.45, margin: "0 0 8px 0" }}
          title="Lab B equity uses full SQLite rollups for lab_b, not only the Recent tables."
        >
          <strong>Reconcile Lab B:</strong> <em>Equity (est.)</em> = bankroll + <em>Total PnL (realized)</em> −{" "}
          <em>Committed</em>. Positive realized PnL with a down return usually means premium still tied up in open Lab B
          positions.
        </p>
        <MetricTile
          label="Lab B bankroll (start)"
          value={fmtMoney(Number(metricsLabB.paper_start_dollars ?? 0))}
          title="lab_b.paper_balance_cents if set, else cfg.paper_balance_cents."
        />
        <MetricTile
          label="Lab B equity (est.)"
          value={fmtMoney(Number(metricsLabB.current_equity_dollars ?? 0))}
          title="Lab B bankroll + settled PnL − open committed."
          sub={`Return vs start ${fmtPct(metricsLabB.return_vs_start_pct)} · chart last ${metricsLabB.latest_equity_snapshot_dollars != null ? fmtMoney(Number(metricsLabB.latest_equity_snapshot_dollars)) : "—"}`}
        />
        <MetricTile
          label="Lab B total PnL"
          value={fmtMoney(Number(metricsLabB.total_pnl_dollars || 0))}
          title="Realized PnL for branch lab_b, mode simulate, status settled."
          sub={`${fmtPct(metricsLabB.realized_pnl_pct_of_start)} of lab bankroll`}
        />
        <MetricTile
          label="Lab B fees"
          value={fmtMoney(Number(metricsLabB.total_kalshi_fees_dollars || 0))}
          title="Modeled entry + exit fees accumulated for Lab B."
        />
        <MetricTile
          label="Lab B avg hourly"
          value={fmtMoney(Number(metricsLabB.avg_hourly_pnl_dollars || 0))}
          title="Lab B realized PnL divided by hours spanned by settled lab_b trades (min ~1h denominator)."
        />
        <MetricTile
          label="Lab B settled"
          value={String(metricsLabB.settled_trades ?? 0)}
          title="Count of settled lab_b simulated trades."
        />
        <MetricTile
          label="Lab B W / L"
          value={`${String(metricsLabB.wins ?? 0)} / ${String(metricsLabB.losses ?? 0)}${
            Number(metricsLabB.scratch_trades) > 0 ? ` · ${String(metricsLabB.scratch_trades)} flat` : ""
          }`}
          title="Wins and losses among settled lab_b rows."
        />
        <MetricTile
          label="Lab B win rate"
          value={fmtPct(
            Number(metricsLabB.wins ?? 0) + Number(metricsLabB.losses ?? 0) > 0
              ? metricsLabB.win_rate_decisive_pct
              : metricsLabB.win_rate_pct,
          )}
          title="Lab B wins ÷ (wins + losses) when decisive outcomes exist."
        />
        <MetricTile
          label="Lab B avg / settled"
          value={
            metricsLabB.avg_realized_per_settled_dollars != null
              ? fmtMoney(Number(metricsLabB.avg_realized_per_settled_dollars))
              : "—"
          }
          title="Lab B total realized PnL ÷ Lab B settled count."
        />
        <MetricTile
          label="Lab B loss rate"
          value={fmtPct(
            Number(metricsLabB.wins ?? 0) + Number(metricsLabB.losses ?? 0) > 0
              ? metricsLabB.loss_rate_decisive_pct
              : metricsLabB.loss_rate_pct,
          )}
          title="Lab B losses ÷ (wins + losses) when decisive outcomes exist."
        />
        <MetricTile
          label="Lab B open"
          value={String(metricsLabB.open_sim_trades ?? 0)}
          title="Open lab_b rows awaiting settlement."
        />
        <MetricTile
          label="Lab B committed"
          value={fmtMoney(Number(metricsLabB.open_sim_committed_dollars || 0))}
          title="Premium tied up in open lab_b positions."
          sub={fmtPct(metricsLabB.committed_pct_of_start) + " of lab bankroll"}
        />
      </div>

      {cfg.simulate ? (
        <div
          className="panel section-tip"
          style={{ marginBottom: 12, padding: "12px 14px" }}
          title="Live branch is in paper mode. Use Assets to watch (sentiment bar + implied YES) for how markets look; turn the Live engine on to log simulated trades and grow PnL over time."
        >
          <strong title="Configured paper bankroll for Live branch when in simulate mode.">Paper bankroll (Live simulate)</strong>:{" "}
          <span title="cfg.paper_balance_cents / 100.">{fmtMoney(Number(cfg.paper_balance_cents || 0) / 100)}</span>
        </div>
      ) : null}

      <div className="grid">
        <div className="panel">
          <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
            <h2
              className="section-tip"
              style={{ margin: 0 }}
              title="Snapshots per series (BTC first, ETH second, then A–Z). Which series the engine scans is controlled by each asset’s enabled flag in bot config (PUT /api/config); dashboard toggles were removed to avoid glitchy reloads. NONE = no rule band matched this tick."
            >
              Assets to watch
            </h2>
            <div className="chart-tabs" role="tablist" aria-label="Asset snapshot branch" style={{ margin: 0 }}>
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
                title="Per-asset engine snapshot for Lab B."
                onClick={() => setAssetWatchLab("b")}
              >
                Lab B
              </button>
            </div>
          </div>
          {kalshiIsNonProd(kalshi?.env) ? (
            <p
              className="sub"
              style={{ marginBottom: 12, lineHeight: 1.5, fontSize: 12 }}
              title="Kalshi demo/stage feeds often omit YES bid/ask on smaller 15m series even when the contract exists."
            >
              You are on a <strong>non-production</strong> Kalshi host (<code>{String(kalshi?.env || "—")}</code>). Demo
              feeds often omit or delay YES bid/ask on many 15m crypto rows, so you may see <code>0.00</code> bid/ask with
              &quot;Target price: TBD&quot; — <strong>no book</strong> means Kalshi has not published quotes for that
              contract on this environment yet, not that this app ignores that asset. Production (with matching keys)
              usually shows books across all configured series where Kalshi lists them.
            </p>
          ) : null}
          {Object.keys(assets).length === 0 ? (
            <div className="sub" title="Add assets under Settings → JSON or defaults in backend config.">
              No assets configured.
            </div>
          ) : (
            orderedAssetEntries(assets as AnyObj).map(([id, a]: [string, AnyObj]) => {
              const posRow = (acctSnap?.position_by_asset as AnyObj | undefined)?.[id] as AnyObj | undefined;
              const hasExposure = positionRowHasOpenExposure(posRow);
              const exposureLabels = exposureChannelLabels(posRow);
              return (
              <div
                key={id}
                className={hasExposure ? "asset-watch-row asset-watch-row--invested" : "asset-watch-row"}
                title={
                  hasExposure
                    ? `You have open exposure on this series (${exposureLabels.join(", ")}). Same highlight for every asset with positions or open sim trades.`
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
                  {hasExposure ? (
                    <span
                      className="asset-watch-exposure-badge"
                      title={`Open positions / contracts: ${exposureLabels.join(" · ")}.`}
                    >
                      Open: {exposureLabels.join(" · ")}
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
                    Boolean(engineLabA?.engine_running) ? (
                      <EngineAssetSnapBlock
                        label="Sim · Lab A"
                        snap={engineSnapsLabA[id]}
                        lastTick={engineLabA?.last_tick_at}
                        engineOn={Boolean(engineLabA?.engine_running)}
                      />
                    ) : (
                      <div className="sub" style={{ fontSize: 12 }} title="Turn Lab A on in the toolbar to populate lab snapshots.">
                        <strong>Sim · Lab A</strong> — engine off (no snapshot for this series).
                      </div>
                    )
                  ) : Boolean(engineLabB?.engine_running) ? (
                    <EngineAssetSnapBlock
                      label="Sim · Lab B"
                      snap={engineSnapsLabB[id]}
                      lastTick={engineLabB?.last_tick_at}
                      engineOn={Boolean(engineLabB?.engine_running)}
                    />
                  ) : (
                    <div className="sub" style={{ fontSize: 12 }} title="Turn Lab B on in the toolbar to populate lab snapshots.">
                      <strong>Sim · Lab B</strong> — engine off (no snapshot for this series).
                    </div>
                  )}
                </div>
              </div>
            );
            })
          )}

        </div>

        <div className="panel">
          <h2
            className="section-tip"
            style={{ marginTop: 0 }}
            title="Equity from stored snapshots. Use the tabs to change bucketing; intraday shows raw points (last 400)."
          >
            Equity curves
          </h2>
          <div className="chart-tabs" role="tablist" aria-label="Equity time scale">
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

          <h3
            className="sub section-tip"
            style={{ marginTop: 14, marginBottom: 6, fontSize: 14, color: "var(--text)" }}
            title="Live branch equity (paper or real balance depending on mode)."
          >
            Live branch
          </h3>
          <div className="chart" title="Live branch equity over time (tab controls bucketing). Hover points for values.">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData} margin={{ left: 6, right: 10, top: 10, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#223056" />
                <XAxis dataKey="t" stroke="#7f8ab5" tick={{ fontSize: 11 }} />
                <YAxis stroke="#7f8ab5" tick={{ fontSize: 11 }} domain={["auto", "auto"]} />
                <Tooltip
                  contentStyle={{ background: "#0b1228", border: "1px solid #243055" }}
                  formatter={(v: any) => [`$${Number(v).toFixed(2)}`, "equity"]}
                />
                <Line type="monotone" dataKey="equity" stroke="#6ee7ff" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>

          <h3
            className="sub section-tip"
            style={{ marginTop: 16, marginBottom: 6, fontSize: 14, color: "var(--text)" }}
            title="Lab A paper equity curve (separate from Live)."
          >
            Lab A
          </h3>
          <div className="chart" title="Lab A equity over time (same tab as Live).">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartDataLabA} margin={{ left: 6, right: 10, top: 10, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#223056" />
                <XAxis dataKey="t" stroke="#7f8ab5" tick={{ fontSize: 11 }} />
                <YAxis stroke="#7f8ab5" tick={{ fontSize: 11 }} domain={["auto", "auto"]} />
                <Tooltip
                  contentStyle={{ background: "#0b1228", border: "1px solid #243055" }}
                  formatter={(v: any) => [`$${Number(v).toFixed(2)}`, "lab_a"]}
                />
                <Line type="monotone" dataKey="equity" stroke="#a78bfa" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <h3
            className="sub section-tip"
            style={{ marginTop: 16, marginBottom: 6, fontSize: 14, color: "var(--text)" }}
            title="Lab B paper equity curve (separate from Live)."
          >
            Lab B
          </h3>
          <div className="chart" title="Lab B equity over time (same tab as Live).">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartDataLabB} margin={{ left: 6, right: 10, top: 10, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#223056" />
                <XAxis dataKey="t" stroke="#7f8ab5" tick={{ fontSize: 11 }} />
                <YAxis stroke="#7f8ab5" tick={{ fontSize: 11 }} domain={["auto", "auto"]} />
                <Tooltip
                  contentStyle={{ background: "#0b1228", border: "1px solid #243055" }}
                  formatter={(v: any) => [`$${Number(v).toFixed(2)}`, "lab_b"]}
                />
                <Line type="monotone" dataKey="equity" stroke="#f59e0b" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>

          <h2
            className="section-tip"
            style={{ marginTop: 22 }}
            title={
              accountLinked
                ? "Balance/positions from signed Kalshi portfolio reads. Writes: Live branch POSTs orders only in Real $ mode when a rule fires."
                : "No signed portfolio access — markets and engine use public Kalshi data; sim trades stay in local SQLite."
            }
          >
            {accountLinked ? "Account (Kalshi linked)" : "Account (public data only)"}
          </h2>
          {!remoteBal ? (
            <div
              className="sub"
              title="Configure KALSHI_API_KEY_ID and private key in repo .env, restart API, reload dashboard."
            >
              {kalshi?.public_ok ? (
                <>
                  No Kalshi account is linked on this backend. The dashboard still uses <strong>public</strong> market
                  data (quotes, series, engine ticks). Balance and exchange-held positions are unavailable until you add
                  credentials. Simulated fills remain in the local database.
                </>
              ) : (
                <>
                  Balance unavailable (and public API may be down). Add{" "}
                  <code title="Env var: API key id.">KALSHI_API_KEY_ID</code> and a private key to{" "}
                  <code title="Environment file in repo root.">.env</code> (see{" "}
                  <code title="Example env file.">.env.example</code>
                  ), then restart the backend.
                </>
              )}
              {kalshi?.private_error ? (
                <div className="sub" style={{ marginTop: 10, fontSize: 12, opacity: 0.9 }} title="Last private API error from the backend.">
                  Detail: {String(kalshi.private_error)}
                </div>
              ) : null}
              {kalshi?.public_ok ? (
                <div style={{ marginTop: 10 }} title="Optional: link Kalshi for portfolio reads and real order posting.">
                  To link: set <code>KALSHI_API_KEY_ID</code> and your RSA private key in <code>.env</code>, restart the
                  API, reload.
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

          {acctSnap?.position_by_asset && Object.keys(acctSnap.position_by_asset).length > 0 ? (
            <div style={{ marginTop: 16 }}>
              <h3
                className="sub section-tip"
                style={{ fontSize: 14, color: "var(--text)", marginBottom: 6 }}
                title={
                  accountLinked
                    ? "Rows match Kalshi portfolio positions and local open simulated trades whose tickers start with each asset’s series_ticker (e.g. KXDOGE15M)."
                    : "Sim columns only — Kalshi exchange positions need a linked account."
                }
              >
                Holdings by asset (series prefix)
              </h3>
              {accountLinked ? (
                <p className="sub" style={{ marginBottom: 8 }} title="Why some assets have data and others show dashes.">
                  <strong>Kalshi</strong> = rows from <code>/portfolio/positions</code> (market + event tickers) whose
                  identifier starts with that asset&apos;s <code>series_ticker</code>.{" "}
                  <strong>Sim (Live / Lab A / Lab B)</strong> = open simulated trades in SQLite for that series per branch.{" "}
                  <strong>No asset is special-cased in code</strong> — a row shows data when Kalshi returns matching
                  positions and/or the bot has open sim trades for that asset&apos;s <code>series_ticker</code> prefix.
                  Symbols with tighter books tend to fill first; others stay &quot;—&quot; until the same is true, or
                  appear under <strong>Recent trades</strong> after sim fills.
                </p>
              ) : (
                <p className="sub" style={{ marginBottom: 8 }} title="Public-only mode: no signed portfolio reads.">
                  <strong>Sim (Live / Lab A / Lab B)</strong> = open simulated trades in SQLite for each asset&apos;s{" "}
                  <code>series_ticker</code>. The Kalshi column is omitted because the account is not linked; empty cells
                  here are not evidence that you have no positions on the exchange.
                </p>
              )}
              <div style={{ overflowX: "auto" }} title="Per configured asset: where exposure shows up.">
                <table className="table">
                  <thead>
                    <tr>
                      <th title="Config asset id.">Asset</th>
                      <th title="Kalshi series_ticker from config.">Series</th>
                      {accountLinked ? (
                        <th title="Open positions returned by GET /portfolio/positions for this series.">Kalshi open</th>
                      ) : null}
                      <th title="Open simulated trades (branch live) in SQLite.">Sim open (Live)</th>
                      <th title="Open simulated trades (branch lab_a / sim_lab) in SQLite.">Sim open (Lab A)</th>
                      <th title="Open simulated trades (branch lab_b) in SQLite.">Sim open (Lab B)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {orderedAssetEntries(acctSnap.position_by_asset as AnyObj).map(([aid, row]: [string, AnyObj]) => (
                      <tr key={aid} title={`Configured asset ${aid}`}>
                        <td title="Label from config.">{String(row.label || aid)}</td>
                        <td>
                          <code title="Series used for prefix match.">{String(row.series_ticker || "")}</code>
                        </td>
                        {accountLinked ? (
                          <td
                            className="sub"
                            style={{ fontSize: 12, maxWidth: 280, wordBreak: "break-word" }}
                            title={summarizePositionRows(row.kalshi_open)}
                          >
                            {summarizePositionRows(row.kalshi_open)}
                          </td>
                        ) : null}
                        <td
                          className="sub"
                          style={{ fontSize: 12, maxWidth: 280, wordBreak: "break-word" }}
                          title={summarizePositionRows(row.bot_sim_open_live)}
                        >
                          {summarizePositionRows(row.bot_sim_open_live)}
                        </td>
                        <td
                          className="sub"
                          style={{ fontSize: 12, maxWidth: 280, wordBreak: "break-word" }}
                          title={summarizePositionRows(
                            Array.isArray(row.bot_sim_open_lab_a) ? row.bot_sim_open_lab_a : row.bot_sim_open_lab,
                          )}
                        >
                          {summarizePositionRows(
                            Array.isArray(row.bot_sim_open_lab_a) ? row.bot_sim_open_lab_a : row.bot_sim_open_lab,
                          )}
                        </td>
                        <td
                          className="sub"
                          style={{ fontSize: 12, maxWidth: 280, wordBreak: "break-word" }}
                          title={summarizePositionRows(row.bot_sim_open_lab_b)}
                        >
                          {summarizePositionRows(row.bot_sim_open_lab_b)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : null}

          <h2 className="section-tip" style={{ marginTop: 16 }} title="Polling engines: market scan, rules, logging. Tick traces show the last engine loop output.">
            Engines
          </h2>
          <div className="sub" title="Engine polling status from /api/dashboard.">
            <div title="Live branch: engine on/off, paper vs real orders, last tick time, markets scanned this tick.">
              <strong title="Main trading branch tied to Live mode.">Live</strong> engine {dash?.engine?.live?.engine_running ? "on" : "off"} ·
              orders{" "}
              {dash?.engine?.live?.simulate_orders ? "simulated (paper)" : "real limit posts"} · last tick:{" "}
              {dash?.engine?.live?.last_tick_at
                ? fmtIsoLocal(String(dash?.engine?.live?.last_tick_at))
                : "—"}{" "}
              · scanned{" "}
              {String(dash?.engine?.live?.markets_scanned ?? "—")}
            </div>
            {dash?.engine?.live?.last_error ? (
              <div className="error" style={{ marginTop: 6 }} title="Last Live engine error string.">
                Live: {String(dash?.engine?.live?.last_error)}
              </div>
            ) : null}
            <EngineTickTrace title="Live — last tick log" lines={dash?.engine?.live?.last_tick_trace} />
            <div
              style={{ marginTop: 10 }}
              title="Sim lab branch: always simulated; last tick and scan count."
            >
              <strong title="Paper-only experimental branch.">Sim lab</strong> engine {dash?.engine?.sim_lab?.engine_running ? "on" : "off"} · always
              simulated · last tick:{" "}
              {dash?.engine?.sim_lab?.last_tick_at
                ? fmtIsoLocal(String(dash?.engine?.sim_lab?.last_tick_at))
                : "—"}{" "}
              · scanned{" "}
              {String(dash?.engine?.sim_lab?.markets_scanned ?? "—")}
            </div>
            {dash?.engine?.sim_lab?.last_error ? (
              <div className="error" style={{ marginTop: 6 }} title="Last Sim lab engine error string.">
                Lab: {String(dash?.engine?.sim_lab?.last_error)}
              </div>
            ) : null}
            <EngineTickTrace title="Sim lab — last tick log" lines={dash?.engine?.sim_lab?.last_tick_trace} />
          </div>
        </div>
      </div>

      <div style={{ marginTop: 14 }}>
        <div className="panel" style={{ marginBottom: 14, padding: "12px 14px" }}>
          <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
            <h2
              className="section-tip"
              style={{ margin: 0 }}
              title="Filter recent signals, trades, and matched-but-not-executed rows by SQLite branch (live vs paper labs)."
            >
              Activity log
            </h2>
            <div className="chart-tabs" role="tablist" aria-label="Activity log branch" style={{ margin: 0 }}>
              <button
                type="button"
                role="tab"
                aria-selected={activityBranch === "live"}
                className={`chart-tab ${activityBranch === "live" ? "chart-tab--active" : ""}`}
                title="Rows where branch is live (or unset legacy rows treated as Live)."
                onClick={() => setActivityBranch("live")}
              >
                Live
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={activityBranch === "lab_a"}
                className={`chart-tab ${activityBranch === "lab_a" ? "chart-tab--active" : ""}`}
                title="Rows where branch is lab_a or legacy sim_lab."
                onClick={() => setActivityBranch("lab_a")}
              >
                Lab A
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={activityBranch === "lab_b"}
                className={`chart-tab ${activityBranch === "lab_b" ? "chart-tab--active" : ""}`}
                title="Rows where branch is lab_b."
                onClick={() => setActivityBranch("lab_b")}
              >
                Lab B
              </button>
            </div>
          </div>
          <p className="sub section-tip" style={{ marginTop: 8, marginBottom: 0, fontSize: 12, lineHeight: 1.45 }}>
            Showing <strong>{activityBranchTabLabel(activityBranch)}</strong> only — each row&apos;s <code>branch</code> field
            must match (legacy <code>sim_lab</code> counts as Lab A).
          </p>
        </div>

        <div className="grid">
          <div className="panel">
            <h3
              className="section-tip"
              style={{ marginTop: 0, marginBottom: 10, fontSize: 14, color: "var(--text)" }}
              title="SQLite log when the engine evaluates a logged path (sizing, sim fill, live order attempt). Most silent skips are not rows here — use tick log and asset snapshots."
            >
              Recent signals — {activityBranchTabLabel(activityBranch)}
            </h3>
            <SignalsTable
              rows={recentSignalsFiltered}
              emptyTitle={`No signals for ${activityBranchTabLabel(activityBranch)} yet.`}
            />
            <ActivityHints
              kind="signals"
              dash={dash}
              cfg={cfg}
              simLab={simLab}
              activityBranch={activityBranch}
              branchRowCount={recentSignalsFiltered.length}
              totalRowCount={(dash?.recent_signals || []).length}
            />
          </div>
          <div className="panel">
            <h3
              className="section-tip"
              style={{ marginTop: 0, marginBottom: 10, fontSize: 14, color: "var(--text)" }}
              title="Fills and simulated orders from the engine for the selected branch."
            >
              Recent trades — {activityBranchTabLabel(activityBranch)}
            </h3>
            <TradesTable
              rows={recentTradesFiltered}
              emptyTitle={`No trades for ${activityBranchTabLabel(activityBranch)} yet.`}
            />
            <ActivityHints
              kind="trades"
              dash={dash}
              cfg={cfg}
              simLab={simLab}
              activityBranch={activityBranch}
              branchRowCount={recentTradesFiltered.length}
              totalRowCount={(dash?.recent_trades || []).length}
            />
          </div>
        </div>

        <div className="panel" style={{ marginTop: 14 }}>
          <h2
            className="section-tip"
            title="Subset of Recent signals where a rule matched but execution did not run (e.g. over budget), for the selected branch only."
          >
            Bets not traded — {activityBranchTabLabel(activityBranch)}
          </h2>
          <SignalsTable
            rows={notTradedFiltered}
            emptyTitle={`No matched-but-not-executed signals for ${activityBranchTabLabel(activityBranch)} yet.`}
          />
          <ActivityHints
            kind="not_traded"
            dash={dash}
            cfg={cfg}
            simLab={simLab}
            activityBranch={activityBranch}
            branchRowCount={notTradedFiltered.length}
            totalRowCount={(dash?.not_traded_signals || []).length}
            totalSignalsCount={(dash?.recent_signals || []).length}
          />
        </div>
      </div>

      <SettingsOverlay
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        dash={dash}
        cfg={cfg}
        labA={labA}
        labB={labB}
        busy={busy}
        onSaveRules={saveRules}
        onSaveYesSubtitleFilter={saveYesSubtitleFilter}
        onSaveExcludeSubtitleFilter={saveExcludeSubtitleFilter}
        onSaveSizing={saveSizing}
        onSaveLabAFromSliders={saveLabAFromSliders}
        onSaveLabBFromSliders={saveLabBFromSliders}
        onSaveLabARules={saveLabARules}
        onSaveLabBRules={saveLabBRules}
        onSaveDevSimHighYesPct={saveDevSimHighYesPct}
        onSaveNoBetWhenYesBelow={saveNoBetWhenYesBelow}
        onSaveSwingExitImpliedDropPct={saveSwingExitImpliedDropPct}
        onSavePaperFees={savePaperFees}
        optimizerCfg={(cfg?.optimizer || optimizerCfg || {}) as AnyObj}
        onSaveOptimizerConfig={saveOptimizerConfig}
        optimizerSaving={optimizerSaving}
        onResetTradingData={resetTradingData}
      />
      <HistoricalExplorerOverlay open={historyOpen} onClose={() => setHistoryOpen(false)} />
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
  const labBOn = Boolean(dash?.engine?.lab_b?.engine_running);
  const liveTick = dash?.engine?.live?.last_tick_at;
  const labATick = dash?.engine?.lab_a?.last_tick_at ?? dash?.engine?.sim_lab?.last_tick_at;
  const labBTick = dash?.engine?.lab_b?.last_tick_at;
  const scannedLive = dash?.engine?.live?.markets_scanned;
  const scannedLabA = dash?.engine?.lab_a?.markets_scanned ?? dash?.engine?.sim_lab?.markets_scanned;
  const scannedLabB = dash?.engine?.lab_b?.markets_scanned;

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
    if ((needLive && !liveOn) || (needA && !labAOn) || (needB && !labBOn)) {
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
        Contacting the local API at /api/dashboard. If this stays here, the backend is not responding.
      </p>
    </div>
  );
}

function ConnectionStrip({ kalshi }: { kalshi: AnyObj | undefined }) {
  if (!kalshi) return null;
  const pub = Boolean(kalshi.public_ok);
  const priv = Boolean(kalshi.private_ok);
  const sim = Boolean(kalshi.simulate_live);
  const writes = Boolean(kalshi.order_writes_live);
  const pos = Number(kalshi.position_count ?? 0);
  const ord = Number(kalshi.resting_order_count ?? 0);

  const writeHint = sim
    ? "Live branch uses paper fills; Kalshi does not receive orders from Live."
    : writes
      ? "Live branch can POST limit orders when the Live engine is on and a rule matches."
      : "Fix authentication before enabling real orders.";

  return (
    <div className="panel" style={{ marginBottom: 14 }}>
      <h2 className="section-tip" title="Health of public market reads, signed portfolio reads, and whether the Live branch may POST orders. Hover each card for detail.">
        Kalshi API (read / write)
      </h2>
      <div className="chip-row" style={{ marginTop: 10 }}>
        <div
          className={`chip chip--${pub ? "ok" : "bad"} section-tip`}
          title="No API key required. Used for quotes, series, and sim settlement checks."
        >
          <div className="chip-title" title="Public REST health.">
            Markets (public read)
          </div>
          <div className="chip-value" title={pub ? "Kalshi public API responded OK." : "Cannot reach public Kalshi API."}>
            {pub ? "Reachable" : "Unreachable"}
          </div>
        </div>
        <div
          className={`chip chip--${priv ? "ok" : pub ? "warn" : "bad"} section-tip`}
          title={
            priv
              ? `Signed portfolio API. Loaded ${pos} position(s), ${ord} resting order(s).`
              : "Needs KALSHI_API_KEY_ID + RSA private key in .env (restart backend)."
          }
        >
          <div className="chip-title" title="Signed portfolio endpoints.">
            Portfolio (private read)
          </div>
          <div className="chip-value" title={priv ? "Private RSA auth succeeded." : "Private auth failed or not configured."}>
            {priv ? "Signed in" : pub ? "Public only" : "Not signed in"}
          </div>
        </div>
        <div className={`chip chip--${sim ? "neutral" : writes ? "ok" : priv ? "warn" : "bad"} section-tip`} title={writeHint}>
          <div className="chip-title" title="Whether Live branch may POST orders to Kalshi.">
            Live orders (write)
          </div>
          <div className="chip-value" title={writeHint}>
            {sim ? "Simulated" : writes ? "Real posts on" : "Blocked"}
          </div>
        </div>
      </div>
      {kalshi.portfolio_notes ? (
        <div className="sub" style={{ marginTop: 10, color: "#ffc878" }}>
          Note: {String(kalshi.portfolio_notes)}
        </div>
      ) : null}
    </div>
  );
}

function SetupChecklist({ dash, cfg }: { dash: AnyObj | null; cfg: AnyObj }) {
  const k = dash?.kalshi as AnyObj | undefined;
  if (!k) return null;
  const cred = (k.credentials || {}) as AnyObj;
  const credOk = Boolean(cred.api_key_id_configured) && Boolean(cred.private_key_configured);
  const steps: { ok: boolean; mid: "ok" | "warn" | "bad"; title: string; hint: string }[] = [
    {
      ok: Boolean(dash),
      mid: dash ? "ok" : "bad",
      title: "Backend and this page are running",
      hint: "You already loaded the dashboard from npm run dev with the API proxy.",
    },
    {
      ok: credOk,
      mid: credOk ? "ok" : "warn",
      title: "Configure .env for Kalshi",
      hint:
        cred.private_key_source === "file_missing"
          ? "KALSHI_PRIVATE_KEY_PATH points to a file that was not found."
          : "Copy .env.example to .env in the repo root; set KALSHI_API_KEY_ID and PEM path or KALSHI_PRIVATE_KEY_PEM.",
    },
    {
      ok: Boolean(k.public_ok),
      mid: k.public_ok ? "ok" : "bad",
      title: "Reach Kalshi REST (correct KALSHI_ENV)",
      hint: "Demo uses demo-api.kalshi.co; prod uses api.elections.kalshi.com. Keys must match the environment.",
    },
    {
      ok: Boolean(k.private_ok),
      mid: k.private_ok ? "ok" : k.public_ok ? "warn" : "bad",
      title: "Authenticate (read portfolio)",
      hint: k.private_ok
        ? "Portfolio reads succeeded."
        : k.public_ok
          ? "Optional for public-only use — add keys if you want balance, Kalshi positions, or real order posting."
          : "If this fails, check key id, PEM format, and that the key belongs to this environment.",
    },
    {
      ok: Boolean(k.polling_enabled),
      mid: k.polling_enabled ? "ok" : "warn",
      title: "Turn on an engine to stream markets into the bot",
      hint: "Enable Live engine and/or Sim lab so ticks run and markets_scanned updates.",
    },
    {
      ok: Boolean(cfg.simulate),
      mid: cfg.simulate ? "ok" : "warn",
      title: "Live mode (simulate vs real)",
      hint: cfg.simulate
        ? "Simulate is on — Live branch will not POST orders to Kalshi."
        : "Real $ is on — Live branch can POST limit orders when the Live engine runs and a rule matches.",
    },
  ];

  return (
    <div className="setup-card">
      <h2 className="section-tip" title="Quick readiness checklist. Hover each step for more detail.">
        Getting started
      </h2>
      <ul className="checklist">
        {steps.map((s, i) => (
          <li key={i} className="section-tip" title={s.hint} aria-label={`${s.title}. ${s.hint}`}>
            <span className={`step-mark ${s.ok ? "ok" : s.mid}`} title={s.hint}>
              {s.ok ? "✓" : i + 1}
            </span>
            <div className="step-body">
              <strong>{s.title}</strong>
            </div>
          </li>
        ))}
      </ul>
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
      text: "No engine polling yet — turn Live or Sim lab on for ticks.",
      detail:
        "Turn Live engine or Sim lab on so markets_scanned and signals update.",
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
            <th title="live, lab_a (legacy sim_lab), or lab_b.">Br</th>
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
            <th title="live, lab_a (legacy sim_lab), or lab_b.">Branch</th>
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

