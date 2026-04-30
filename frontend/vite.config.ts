import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

/** Backend origin for dev + preview proxy; must match uvicorn (develop default 8765; main worktree / Kalshibot-main often 8770). Set `VITE_API_ORIGIN` in frontend/.env — see frontend/.env.example */
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const origin = (env.VITE_API_ORIGIN || "http://127.0.0.1:8765").replace(/\/$/, "");
  /** Prefer `VITE_DEV_PORT` so main vs develop worktrees never both default to 5174 when run manually (see bootstrap scripts). */
  const devPort = Math.min(65535, Math.max(1024, Number.parseInt(String(env.VITE_DEV_PORT || "5174"), 10) || 5174));
  const apiProxy = {
    "/api": {
      target: origin,
      changeOrigin: true,
      // Slow first dashboard + large payloads; does not fix ECONNRESET (peer closed = API died/restarted).
      timeout: 120_000,
      proxyTimeout: 120_000,
    },
    "/labs": {
      target: origin,
      changeOrigin: true,
      timeout: 120_000,
      proxyTimeout: 120_000,
    },
  } as const;

  return {
    plugins: [react()],
    server: {
      port: devPort,
      strictPort: false,
      proxy: { ...apiProxy },
    },
    // ``vite preview`` does not inherit ``server.proxy`` — without this, /api/* requests hit the preview
    // server (404 / connection errors → "Failed to fetch" on Optimizer + Breeding panels).
    preview: {
      port: devPort,
      proxy: { ...apiProxy },
    },
  };
});
