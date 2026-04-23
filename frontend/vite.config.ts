import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

/** Backend origin for dev proxy; must match KALSHI_BOT_PORT (default 8765). Set in frontend/.env: VITE_API_ORIGIN */
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const origin = (env.VITE_API_ORIGIN || "http://127.0.0.1:8765").replace(/\/$/, "");
  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        "/api": {
          target: origin,
          changeOrigin: true,
        },
      },
    },
  };
});
