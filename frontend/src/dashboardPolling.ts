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
export const DASHBOARD_EQUITY_POLL_MS = 3_000;
/** Labs B/C/D hive chat (`GET /labs/chat`). */
export const LAB_CHAT_POLL_MS = 2_500;

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
