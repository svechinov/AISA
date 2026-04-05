"""Background execution of POST /runs/:id/restart so the API thread returns immediately."""

from __future__ import annotations

import logging
import threading

from app.db import SessionLocal

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_restart_in_progress: set[int] = set()


def is_restart_in_progress(run_id: int) -> bool:
    with _lock:
        return run_id in _restart_in_progress


def schedule_restart_background(run_id: int) -> bool:
    """
    Start restart_run_workflow in a daemon thread with its own DB session.
    Returns False if this run_id already has a restart in flight.
    """
    with _lock:
        if run_id in _restart_in_progress:
            return False
        _restart_in_progress.add(run_id)

    def _worker() -> None:
        db = SessionLocal()
        try:
            from app.services.run_restart_service import restart_run_workflow

            restart_run_workflow(db, run_id)
        except Exception:
            logger.exception("Background restart failed for run_id=%s", run_id)
        finally:
            db.close()
            with _lock:
                _restart_in_progress.discard(run_id)

    t = threading.Thread(
        target=_worker,
        name=f"restart-run-{run_id}",
        daemon=True,
    )
    t.start()
    return True
