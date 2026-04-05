#!/usr/bin/env bash
# Move a run to another project (same as PATCH /runs/{id}/project in the UI).
# Usage:
#   API_BASE=http://127.0.0.1:8000 RUN_ID=19 PROJECT_ID=2 bash scripts/move_run_to_project.sh
set -euo pipefail
BASE="${API_BASE:-http://127.0.0.1:8000}"
RID="${RUN_ID:?set RUN_ID}"
PID="${PROJECT_ID:?set PROJECT_ID}"
curl -sS -X PATCH "${BASE}/runs/${RID}/project" \
  -H 'Content-Type: application/json' \
  -d "{\"project_id\": ${PID}}" | python3 -m json.tool
