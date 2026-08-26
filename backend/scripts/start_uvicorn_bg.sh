#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PORT="${PORT:-8001}"
LOG="${LOG:-/tmp/ai-biz-os-backend-${PORT}.log}"
PID_FILE="/tmp/ai-biz-os-backend-${PORT}.pid"

if [[ -x "$ROOT/.venv/bin/uvicorn" ]]; then
  UV="$ROOT/.venv/bin/uvicorn"
else
  echo "Нет $ROOT/.venv/bin/uvicorn — создайте venv и поставьте зависимости:"
  echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Порт $PORT уже занят. Остановка:"
  echo "  PORT=$PORT $ROOT/scripts/stop_uvicorn_bg.sh"
  exit 1
fi

nohup "$UV" app.main:app --reload --host 127.0.0.1 --port "$PORT" >>"$LOG" 2>&1 &
echo $! >"$PID_FILE"
echo "Uvicorn в фоне: http://127.0.0.1:${PORT}/health"
echo "Лог: $LOG"
echo "PID (reloader): $(cat "$PID_FILE") — дочерний worker тоже на порту $PORT"
echo "Стоп: PORT=$PORT $ROOT/scripts/stop_uvicorn_bg.sh"
