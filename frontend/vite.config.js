import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  // Where to proxy /api in dev/preview. Docker often binds :8000 with an old image; local uvicorn may use :8001.
  const apiProxyTarget =
    env.VITE_API_PROXY_TARGET?.trim() || "http://127.0.0.1:8000";
  /** Must be ≥ longest client `timeoutMs` (POST /runs/:id/restart can run many minutes). Default 30s caused Failed to fetch; 180s still cut long restarts. */
  const apiProxyTimeoutMs = Number(env.VITE_API_PROXY_TIMEOUT_MS) || 660000;

  return {
    plugins: [react()],
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src"),
      },
    },
    server: {
      port: 5173,
      strictPort: true,
      proxy: {
        "/api": {
          target: apiProxyTarget,
          changeOrigin: true,
          timeout: apiProxyTimeoutMs,
          proxyTimeout: apiProxyTimeoutMs,
          rewrite: (p) => p.replace(/^\/api/, ""),
        },
      },
    },
    preview: {
      port: 4173,
      proxy: {
        "/api": {
          target: apiProxyTarget,
          changeOrigin: true,
          timeout: apiProxyTimeoutMs,
          proxyTimeout: apiProxyTimeoutMs,
          rewrite: (p) => p.replace(/^\/api/, ""),
        },
      },
    },
  };
});
