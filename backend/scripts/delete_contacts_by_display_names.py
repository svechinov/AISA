#!/usr/bin/env python3
"""
Remove contacts whose display name matches given strings (trim + case-insensitive).

Default targets: "John Doe", "Jane Smith" (LLM placeholder junk).

Uses delete_contacts_cascade (drafts, threads, messages, packets, etc.).

From the backend directory:

  python3 scripts/delete_contacts_by_display_names.py --dry-run
  python3 scripts/delete_contacts_by_display_names.py

Loads DATABASE_URL from backend/.env (same as other scripts).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

try:
    from app.services.env_bootstrap import load_env_from_file
except ModuleNotFoundError as e:
    print(e, file=sys.stderr)
    raise SystemExit(1) from None

load_env_from_file()

import app.init_db  # noqa: F401, E402 — register all models before ORM queries

from sqlalchemy import func  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models.contact import Contact  # noqa: E402
from app.services.run_deletion_service import delete_contacts_cascade  # noqa: E402

DEFAULT_NAMES = ("John Doe", "Jane Smith")


def _normalized_name_column():
    return func.lower(func.trim(Contact.name))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--names",
        default=",".join(DEFAULT_NAMES),
        help=f"Comma-separated display names (default: {','.join(DEFAULT_NAMES)})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print ids and counts; do not delete.",
    )
    args = parser.parse_args()
    targets = {n.strip().lower() for n in args.names.split(",") if n.strip()}
    if not targets:
        print("No names after parsing --names.", file=sys.stderr)
        raise SystemExit(1)

    db = SessionLocal()
    try:
        q = (
            db.query(Contact.id, Contact.run_id, Contact.name)
            .filter(Contact.name.isnot(None))
            .filter(_normalized_name_column().in_(targets))
            .order_by(Contact.id.asc())
        )
        rows = q.all()
        if not rows:
            print("No matching contacts.")
            return

        for cid, run_id, name in rows:
            print(f"  id={cid} run_id={run_id} name={name!r}")

        if args.dry_run:
            print(f"Dry-run: would delete {len(rows)} contact(s).")
            return

        ids = [r[0] for r in rows]
        n = delete_contacts_cascade(db, ids, commit=True)
        print(f"Deleted {n} contact(s) and dependent rows.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
