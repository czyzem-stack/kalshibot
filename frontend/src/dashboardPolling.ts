/**
 * Dashboard polling helpers.
 *
 * Browsers throttle ``setInterval`` heavily in background tabs (Chrome often ≥1/min). The UI then looks
 * “frozen” until something forces a remount — e.g. Vite Fast Refresh while editing. Subscribing to
 * visibility / pageshow / online fires an immediate catch-up when the tab is active again.
 *
 * **Lab E parity:** fast equity refresh in ``App.tsx`` merges ``FAST_POLL_EQ_KEYS`` /
 * ``FAST_POLL_METRIC_KEYS`` (includes ``equity_snapshots_lab_e`` and ``metrics_lab_e``). When adding
 * branches, extend those tuples so partial ``GET /api/dashboard/equity`` payloads never leave Lab E
 * as ``undefined`` (which caused hero / chart code to hit ``NoneType``-style ``.get`` errors in TS).
 */

export const DASHBOARD_FULL_POLL_MS = 12_000;
/** Partial dashboard (`GET /api/dashboard/equity`) — faster than full poll but avoid hammering uvicorn access logs. */
export const DASHBOARD_EQUITY_POLL_MS = 6_000;
/** When Equity “Live” (6h dense window + live tail) tab is selected — snappier hero / marquee / chart alignment. */
export const DASHBOARD_EQUITY_POLL_MS_LIVE_TAB = 2_500;
/** Think Tank transcript (`GET /labs/chat`) — cosmetic strip; no need for sub‑5s cadence. */
export const LAB_CHAT_POLL_MS = 12_000;

/** After time-window filter for D/D, W/W, M/M, Y/Y — same SQLite tick density as Intraday; cap for chart perf. */
export const EQUITY_DENSE_CHART_MAX_POINTS = 280;

/** One parsed snapshot row (chronological) before label formatting. */
export type EquityDenseTickRow = { at: string; ts: number; eq: number; mtm: number | null };

/** Rolling wall-clock windows for calendar tabs — dense ticks, no period “resolution”. */
export const EQUITY_GRANULAR_ROLLING_WINDOW_MS: Record<"dd" | "ww" | "mm" | "yy", number> = {
  /** ~4 months of daily-ish ticks */
  dd: 120 * 24 * 60 * 60 * 1000,
  /** ~18 months */
  ww: 78 * 7 * 24 * 60 * 60 * 1000,
  /** ~4 years (month tab = long horizon) */
  mm: 1460 * 24 * 60 * 60 * 1000,
  /** ~12 years */
  yy: 12 * 365 * 24 * 60 * 60 * 1000,
};

/** Evenly spaced indices along time; keeps first and last points of the window. */
export function downsampleEquityDenseTicks(rows: EquityDenseTickRow[], maxPoints: number): EquityDenseTickRow[] {
  const cap = Math.max(3, Math.min(500, Math.floor(maxPoints)));
  if (rows.length <= cap) return rows;
  const n = rows.length;
  const out: EquityDenseTickRow[] = [];
  const step = (n - 1) / (cap - 1);
  let prevIdx = -1;
  for (let i = 0; i < cap; i++) {
    const idx = Math.min(n - 1, Math.round(i * step));
    if (idx !== prevIdx) {
      out.push(rows[idx]!);
      prevIdx = idx;
    }
  }
  const last = rows[n - 1]!;
  if (out.length === 0 || out[out.length - 1]!.ts !== last.ts) out.push(last);
  return out;
}

/** True for tabs that use rolling dense SQLite history (not bucket-per-period). */
export function equityTabUsesDenseRollingHistory(g: string): boolean {
  return g === "dd" || g === "ww" || g === "mm" || g === "yy";
}

/** Run ``fn`` when the document becomes usable again (tab visible, back/forward cache, network back). */
export function subscribeDashboardCatchUp(fn: () => void): () => void {
  const runIfVisible = () => {
    if (typeof document === "undefined" || document.visibilityState !== "visible") return;
    fn();
  };

  const onVis = () => runIfVisible();
  /** ``pageshow`` covers bfcache restore where timers may not have fired for a long time. */
  const onPageShow = () => runIfVisible();

  document.addEventListener("visibilitychange", onVis);
  window.addEventListener("pageshow", onPageShow);
  window.addEventListener("online", runIfVisible);

  return () => {
    document.removeEventListener("visibilitychange", onVis);
    window.removeEventListener("pageshow", onPageShow);
    window.removeEventListener("online", runIfVisible);
  };
}
