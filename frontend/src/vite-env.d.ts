/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BEARER_TOKEN?: string;
  readonly VITE_API_ORIGIN?: string;
  /** Optional: `dev` | `main` | `live` — shown next to the app title. If unset, inferred from API port (8770 => main). */
  readonly VITE_UI_TRACK?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
