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


@pytest.fixture()
def fresh_db(tmp_path):
    """Empty SQLite with the full schema, bound to its own engine — independent of the
    prod-snapshot copy above. The dist does not ship ai_biz_os_realrun.db (gitignored), so any
    test that must run in a clean checkout (not just on a machine with a leftover snapshot) needs
    this instead of `db`. Every model is imported explicitly before create_all(), same reason as
    init_db.py's own explicit import block: SQLAlchemy only registers tables for modules that have
    actually been imported."""
    import importlib
    import pkgutil

    import app.models as models_pkg
    from app.db import Base
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    for _, name, _ in pkgutil.iter_modules(models_pkg.__path__):
        importlib.import_module(f"app.models.{name}")

    engine = create_engine(f"sqlite:///{(tmp_path / 'fresh.db').as_posix()}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
