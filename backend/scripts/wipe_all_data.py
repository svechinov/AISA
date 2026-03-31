#!/usr/bin/env python3
"""
Delete all application rows (keeps schema). Uses TRUNCATE ... CASCADE on Postgres.

Run from the backend directory (folder that contains requirements.txt and app/):

    python3 scripts/wipe_all_data.py

On macOS there is often no "python" command -- use python3.

Loads DATABASE_URL from backend/.env automatically (same as the API).

Install deps once (see MISSING_DEPS_MSG below if pip refuses on Homebrew Python).
"""

from __future__ import annotations

import sys
from pathlib import Path

_MISSING_DEPS = """\
Missing Python packages.

If you use Homebrew Python, PEP 668 blocks installing into the system interpreter.
Use a virtual environment (recommended):

  python3 -m venv .venv
  source .venv/bin/activate          # Windows: .venv\\Scripts\\activate
  pip install -r requirements.txt
  python scripts/wipe_all_data.py

Alternatives:
  python3 -m pip install --user -r requirements.txt
  # last resort (may confuse Homebrew): add --break-system-packages
"""

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

try:
    from app.services.env_bootstrap import load_env_from_file
except ModuleNotFoundError as e:
    print(f"{e}\n", file=sys.stderr)
    print(_MISSING_DEPS, file=sys.stderr)
    raise SystemExit(1) from None

load_env_from_file()

try:
    from sqlalchemy import text

    from app.db import Base, engine
except ModuleNotFoundError as e:
    print(f"{e}\n", file=sys.stderr)
    print(_MISSING_DEPS, file=sys.stderr)
    raise SystemExit(1) from None


def _register_models() -> None:
    # Populate Base.metadata with all tables
    import app.init_db  # noqa: F401 -- imports models for side effects


def wipe_all_data() -> None:
    _register_models()
    tables = list(Base.metadata.sorted_tables)
    if not tables:
        raise RuntimeError("No tables in metadata -- models not loaded?")

    dialect = engine.dialect.name
    with engine.begin() as conn:
        if dialect == "postgresql":
            names = ", ".join(f'"{t.name}"' for t in tables)
            conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
        elif dialect == "sqlite":
            for t in reversed(tables):
                conn.execute(text(f'DELETE FROM "{t.name}"'))
        else:
            for t in reversed(tables):
                conn.execute(text(f"DELETE FROM {t.name}"))


if __name__ == "__main__":
    wipe_all_data()
    print("All application data removed (tables still exist).")
