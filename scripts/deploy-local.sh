#!/usr/bin/env bash
# One-shot local deploy: Postgres + Redis + backend (Docker), frontend production build, Vite dev (background).
# Prereq: run from the ai-biz-os directory (or use freeman-lab/scripts/deploy-local.sh from monorepo root).
#
# Proxy: Vite forwards /api → VITE_API_PROXY_TARGET (default http://127.0.0.1:8000). For this compose stack keep :8000.
#
# Gmail OAuth on host disk: set USE_BIND_ENV=1 so backend/.env is mounted at /app/.env (needs Docker File sharing for this path).
# Default (no mount): API still runs; OAuth refresh lives in the container until you copy it or use the overlay file.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ "${USE_BIND_ENV:-}" == "1" ]]; then
  COMPOSE=(docker compose -f infra/docker-compose.yml -f infra/docker-compose.bind-env.yml)
else
  COMPOSE=(docker compose -f infra/docker-compose.yml)
fi

echo "==> Backend: docker compose build (backend)"
"${COMPOSE[@]}" build backend

echo "==> Backend: up -d postgres redis backend"
"${COMPOSE[@]}" up -d postgres redis backend

echo "==> Backend: wait for /health (process listening, up to ~60s)"
for i in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:8000/health" >/dev/null; then
    echo "    health OK"
    break
  fi
  if (( i % 10 == 0 )); then
    echo "    ... still waiting (${i}s) — check: ${COMPOSE[*]} ps  and  ${COMPOSE[*]} logs backend"
  fi
  if [[ "$i" -eq 60 ]]; then
    echo "error: /health did not respond on :8000 — try: ${COMPOSE[*]} logs backend" >&2
    exit 1
  fi
  sleep 1
done

echo "==> Backend: wait for /ready (DB schema + API route imports; up to ~300s)"
echo "    (503 from /ready until then is normal — cold import can take 30–90s on first start)"
echo "    polling every 1s; status below every 5s if still not ready"
for i in $(seq 1 300); do
  if curl -sf "http://127.0.0.1:8000/ready" >/dev/null; then
    echo "    API ready (schema + routes)"
    break
  fi
  if (( i % 5 == 0 )); then
    body="$(curl -sS --max-time 2 "http://127.0.0.1:8000/ready" 2>/dev/null || true)"
    reason="$(printf '%s' "$body" | sed -n 's/.*"reason"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
    [[ -n "$reason" ]] || reason="(no JSON — check port / backend)"
    echo "    ... still waiting (${i}s) — /ready says: ${reason} — ${COMPOSE[*]} logs backend"
  fi
  if [[ "$i" -eq 300 ]]; then
    echo "error: /ready never returned 200 — check ensure_schema and route registration — try: ${COMPOSE[*]} logs backend" >&2
    exit 1
  fi
  sleep 1
done

echo "==> Frontend: npm run build"
(cd frontend && npm run build)

echo "==> Frontend: restart Vite dev (background, :5173)"
(cd frontend && (npm run dev:stop 2>/dev/null || true) && npm run dev)

echo "Done. UI: http://localhost:5173/  |  API: http://127.0.0.1:8000/docs#/"
