/**
 * Dashboard polling helpers.
 *
 * Browsers throttle ``setInterval`` heavily in background tabs (Chrome often ≥1/min). The UI then looks
 * “frozen” until something forces a remount — e.g. Vite Fast Refresh while editing. Subscribing to
 * visibility / pageshow / online fires an immediate catch-up when the tab is active again.
 */

export const DASHBOARD_FULL_POLL_MS = 12_000;
export const DASHBOARD_EQUITY_POLL_MS = 3_000;

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
