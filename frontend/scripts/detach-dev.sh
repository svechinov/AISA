#!/usr/bin/env bash
# Run Vite in the background: you can close the terminal; :5173 stays up until stop-dev.sh.
set -euo pipefail
cd "$(dirname "$0")/.."
LOG="${PWD}/vite-dev.log"
PIDFILE="${PWD}/vite-dev.pid"

if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "Vite already running (PID $(cat "$PIDFILE")). Log: $LOG"
  exit 0
fi

nohup npx vite --host 127.0.0.1 --port 5173 >>"$LOG" 2>&1 &
echo $! >"$PIDFILE"
echo "Vite in background, PID $(cat "$PIDFILE"). Log: $LOG"
echo "Stop: npm run dev:stop  |  Foreground (attached TTY): npm run dev:foreground"
