/**
 * Which git-style track this UI build talks to (local: develop / main / test worktrees).
 * Set `VITE_UI_TRACK` in frontend/.env to `dev`, `main`, `test`, or `live`.
 * If unset, infers from VITE_API_ORIGIN port (8775 = test, 8770 = main), else `dev`.
 */
export type UiTrackKind = "dev" | "main" | "test" | "live";

export function resolveUiTrack(): { kind: UiTrackKind; label: string } {
  const raw = String((import.meta.env.VITE_UI_TRACK as string | undefined) ?? "")
    .trim()
    .toLowerCase();
  if (raw === "dev" || raw === "main" || raw === "test" || raw === "live") {
    return { kind: raw as UiTrackKind, label: raw };
  }
  const origin = String((import.meta.env.VITE_API_ORIGIN as string | undefined) ?? "").toLowerCase();
  if (origin.includes(":8775")) return { kind: "test", label: "test" };
  if (origin.includes(":8770")) return { kind: "main", label: "main" };
  return { kind: "dev", label: "dev" };
}

/** Browser tab title: develop vs main vs test (see VITE_UI_TRACK / API origin port). */
export function resolveDocumentTitle(): string {
  const t = resolveUiTrack();
  if (t.kind === "dev") return "Chomp's Diner beta";
  if (t.kind === "test") return "Chomp's Diner test";
  return "Chomp's Diner live";
}
