// Single source of truth for the backend base URL.
// Dev: requests go to /api and Vite proxies to the backend. Prod build: same-origin /api too —
// the server's nginx-ui.conf proxies /api/* to the backend container, so the UI works from any
// device reaching the ui container's origin (SSH tunnel, or Tailscale from a phone), not just
// localhost with both ports forwarded. Override with VITE_API_BASE. Keep every component
// importing this, so changing the port/host is a one-file edit.
const ENV_API = import.meta.env.VITE_API_BASE?.trim();

export const API_BASE =
  ENV_API && ENV_API.length > 0 ? ENV_API.replace(/\/$/, "") : "/api";
