/**
 * Which track this UI build targets (local: develop vs main worktrees).
 * Set `VITE_UI_TRACK` in `frontend/.env` to `dev`, `main`, `test` (rare/legacy), or `live`.
 * In `vite dev`, a known local port wins over `VITE_UI_TRACK` so :5174 and :5175 are not both labeled `dev`.
 * Otherwise: explicit `VITE_UI_TRACK`, then port (5173 = main, 5174 = develop, 5175 = test), then `VITE_API_ORIGIN` (:8770 = main), else `dev`.
 */
export type UiTrackKind = "dev" | "main" | "test" | "live";

function inferTrackFromViteUrlPort(): UiTrackKind | null {
  if (typeof window === "undefined") return null;
  const p = String(window.location.port || "");
  if (p === "5173") return "main";
  if (p === "5174") return "dev";
  if (p === "5175") return "test";
  return null;
}

export function resolveUiTrack(): { kind: UiTrackKind; label: string } {
  // Prefer URL port in dev so two Vite instances (e.g. 5174 + 5175) don't share one pinned `VITE_UI_TRACK=dev` label.
  if (import.meta.env.DEV) {
    const fromPort = inferTrackFromViteUrlPort();
    if (fromPort) return { kind: fromPort, label: fromPort };
  }
  const raw = String((import.meta.env.VITE_UI_TRACK as string | undefined) ?? "")
    .trim()
    .toLowerCase();
  if (raw === "dev" || raw === "main" || raw === "test" || raw === "live") {
    return { kind: raw as UiTrackKind, label: raw };
  }
  const fromPort = inferTrackFromViteUrlPort();
  if (fromPort) return { kind: fromPort, label: fromPort };
  const origin = String((import.meta.env.VITE_API_ORIGIN as string | undefined) ?? "").toLowerCase();
  if (origin.includes(":8770")) return { kind: "main", label: "main" };
  return { kind: "dev", label: "dev" };
}

/** Browser tab title: develop vs main (see VITE_UI_TRACK / API origin port). */
export function resolveDocumentTitle(): string {
  const t = resolveUiTrack();
  if (t.kind === "dev") return "Chomp's Diner beta";
  if (t.kind === "test") return "Chomp's Diner test";
  return "Chomp's Diner live";
}
