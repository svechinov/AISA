#!/usr/bin/env bash
# One-shot local deploy: rebuild & restart backend (Docker, detached), rebuild frontend, Vite dev in background.
# Safe to close the terminal — API stays on :8000, UI on :5173 until you docker compose down / npm run dev:stop.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> Backend: docker compose build + up -d (backend)"
docker compose -f infra/docker-compose.yml build backend
docker compose -f infra/docker-compose.yml up -d backend

echo "==> Frontend: npm run build"
(cd frontend && npm run build)

echo "==> Frontend: restart Vite dev (background, :5173)"
(cd frontend && (npm run dev:stop 2>/dev/null || true) && npm run dev)

echo "Done. UI: http://localhost:5173/  |  API docs: http://localhost:8000/docs#/"
