/**
 * Which track this UI build targets (local: develop vs main worktrees).
 * Set `VITE_UI_TRACK` in `frontend/.env` to `dev`, `main`, `test` (rare/legacy), or `live`.
 * If unset, infers from the dev server URL port (5173 = main, 5174 = develop), then `VITE_API_ORIGIN` (8770 = main), else `dev`.
 */
export type UiTrackKind = "dev" | "main" | "test" | "live";

function inferTrackFromViteUrlPort(): UiTrackKind | null {
  if (typeof window === "undefined") return null;
  const p = String(window.location.port || "");
  if (p === "5173") return "main";
  if (p === "5174") return "dev";
  return null;
}

export function resolveUiTrack(): { kind: UiTrackKind; label: string } {
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
