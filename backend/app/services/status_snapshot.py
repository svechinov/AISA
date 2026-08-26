"""Periodic read-only status.json for the Telegram General-topic dialog agent (general_agent/).

That agent runs in a separate, read-only-mounted container with no DB/API access — it only sees
files under telegram_inbox/. This writes a JSON snapshot there so it can answer "how's the queue"
without needing Bash/SQL access. Reuses the same aggregation as GET /ops/summary (app.api.ops) —
no separate business logic, just a periodic dump of that same view.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

_log = logging.getLogger(__name__)


def _active_runs_summary(db: Session) -> dict:
    from app.models.run import Run
    from app.models.run_company import RunCompany

    active_runs = db.query(Run).filter(Run.finished_at.is_(None)).all()
    run_ids = [r.id for r in active_runs]
    companies_by_run: dict[int, int] = {}
    if run_ids:
        companies_by_run = dict(
            db.query(RunCompany.run_id, func.count(RunCompany.id))
            .filter(RunCompany.run_id.in_(run_ids))
            .group_by(RunCompany.run_id)
            .all(),
        )
    return {
        "active_count": len(active_runs),
        "runs": [
            {
                "id": r.id,
                "name": r.name,
                "status": r.status,
                "companies": companies_by_run.get(r.id, 0),
            }
            for r in active_runs
        ],
    }


def build_status_snapshot(db: Session) -> dict:
    from app.api.ops import ops_summary_route

    snapshot = ops_summary_route(db)  # same aggregation as GET /ops/summary — no duplicate logic
    snapshot["active_runs"] = _active_runs_summary(db)
    snapshot["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return snapshot


def write_status_snapshot(db: Session, path: Path) -> None:
    """Build the snapshot and write it atomically (tmp file + rename) to ``path``."""
    data = build_status_snapshot(db)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def run_status_snapshot_tick_in_thread() -> None:
    """One tick: open a session, write status.json into the poller's inbox dir. Never raises."""
    from app.db import SessionLocal
    from app.services.telegram_poller import inbox_dir

    db = SessionLocal()
    try:
        write_status_snapshot(db, inbox_dir() / "status.json")
    except Exception:
        _log.exception("status snapshot tick failed")
    finally:
        db.close()
