import http from "node:http";
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

/**
 * Pooled keep-alive toward the FastAPI host cuts random ``ECONNRESET`` on Windows when the dev proxy
 * opens many parallel /api/* sockets (dashboard + equity + trades). Does **not** survive uvicorn
 * ``--reload`` restarts or API crashes — those still reset the peer.
 */
const apiUpstreamAgent = new http.Agent({ keepAlive: true, maxSockets: 80 });

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
      agent: apiUpstreamAgent,
      // Slow first dashboard + large payloads. Peer ``ECONNRESET`` = API process closed socket (reload/crash/OOM).
      timeout: 120_000,
      proxyTimeout: 120_000,
    },
    "/labs": {
      target: origin,
      changeOrigin: true,
      agent: apiUpstreamAgent,
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
