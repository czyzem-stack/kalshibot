/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BEARER_TOKEN?: string;
  readonly VITE_API_ORIGIN?: string;
  /** Dev server port (default 5174 develop; main worktree uses 5173 — see frontend/.env.example). */
  readonly VITE_DEV_PORT?: string;
  /** Optional: `dev` | `main` | `live` — shown next to the app title. If unset, inferred from API port (8770 => main). */
  readonly VITE_UI_TRACK?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
