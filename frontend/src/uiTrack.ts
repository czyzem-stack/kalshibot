/**
 * Which git-style track this UI build talks to (dual local: develop vs main worktree).
 * Set `VITE_UI_TRACK` in frontend/.env to `dev`, `main`, or `live`.
 * If unset, infers `main` when VITE_API_ORIGIN points at port 8770 (main sidecar), else `dev`.
 */
export type UiTrackKind = "dev" | "main" | "live";

export function resolveUiTrack(): { kind: UiTrackKind; label: string } {
  const raw = String((import.meta.env.VITE_UI_TRACK as string | undefined) ?? "")
    .trim()
    .toLowerCase();
  if (raw === "dev" || raw === "main" || raw === "live") {
    return { kind: raw as UiTrackKind, label: raw };
  }
  const origin = String((import.meta.env.VITE_API_ORIGIN as string | undefined) ?? "").toLowerCase();
  if (origin.includes(":8770")) return { kind: "main", label: "main" };
  return { kind: "dev", label: "dev" };
}

/** Browser tab title: develop-style stack vs main sidecar (see VITE_UI_TRACK / port 8770). */
export function resolveDocumentTitle(): string {
  const t = resolveUiTrack();
  if (t.kind === "dev") return "Chomp's Diner beta";
  return "Chomp's Diner live";
}
