"""Shared fixtures. One throwaway COPY of the realrun prod-DB snapshot per test process:
DATABASE_URL is set BEFORE the first `app.*` import (app.db builds the engine at import time),
exactly like the ad-hoc stub-test scripts did. Tests share the copy — create uniquely named
rows instead of asserting on global counts.

All tests run offline (0 tokens): LLM/Tavily/SMTP calls are stubbed per-test via monkeypatch.
Requires backend/ai_biz_os_realrun.db (a prod backup copy — see session handoff runbook).
"""

import os
import shutil
import tempfile
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
SNAPSHOT = BACKEND / "ai_biz_os_realrun.db"

_db_dir = tempfile.mkdtemp(prefix="aibizos_tests_")
_db_path = Path(_db_dir) / "test.db"
if SNAPSHOT.exists():
    shutil.copy(SNAPSHOT, _db_path)
    os.environ["DATABASE_URL"] = f"sqlite:///{_db_path.as_posix()}"

_schema_ready = False


@pytest.fixture()
def db():
    """SQLAlchemy session over the process-wide prod-snapshot copy (schema migrated once)."""
    global _schema_ready
    if not SNAPSHOT.exists():
        pytest.skip("ai_biz_os_realrun.db snapshot missing")
    if not _schema_ready:
        from app.init_db import ensure_schema

        ensure_schema()
        _schema_ready = True

    from app.db import SessionLocal

    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
