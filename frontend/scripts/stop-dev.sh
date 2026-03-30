#!/usr/bin/env bash
cd "$(dirname "$0")/.."
PIDFILE="${PWD}/vite-dev.pid"
if [[ ! -f "$PIDFILE" ]]; then
  echo "No vite-dev.pid file — background dev may not have been started."
  exit 0
fi
pid=$(cat "$PIDFILE")
if kill -0 "$pid" 2>/dev/null; then
  kill "$pid"
  echo "Stopped process $pid"
else
  echo "Process $pid is not running"
fi
rm -f "$PIDFILE"
