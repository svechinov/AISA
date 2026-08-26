#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${PORT:-8001}"
PID_FILE="/tmp/ai-biz-os-backend-${PORT}.pid"

if [[ -f "$PID_FILE" ]]; then
  PID="$(cat "$PID_FILE" || true)"
  if [[ -n "${PID:-}" ]] && kill -0 "$PID" 2>/dev/null; then
    kill "$PID" 2>/dev/null || true
  fi
  rm -f "$PID_FILE"
fi

# На :8001 при --reload часто два процесса Python — убираем всё, что слушает порт
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  lsof -ti "TCP:$PORT" | xargs kill 2>/dev/null || true
  sleep 0.5
  lsof -ti "TCP:$PORT" | xargs kill -9 2>/dev/null || true
fi

echo "Порт $PORT освобождён (если процесс был только uvicorn на этом порту)."
