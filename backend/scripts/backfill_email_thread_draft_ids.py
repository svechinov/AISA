#!/usr/bin/env python3
"""
Set email_threads.draft_id when it is NULL but the outreach draft can be inferred.

Uses the same rules as resolve_thread_outbound_draft_id() (repo): outbound message draft_id,
Gmail thread id on draft, Gmail message id, then normalized subject on sent drafts.

Run from the backend directory:

  python3 scripts/backfill_email_thread_draft_ids.py --dry-run
  python3 scripts/backfill_email_thread_draft_ids.py
  python3 scripts/backfill_email_thread_draft_ids.py --run-id 12
  python3 scripts/backfill_email_thread_draft_ids.py --thread-id 106 --dry-run

Loads DATABASE_URL from backend/.env (see other scripts).
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

try:
    from app.db import SessionLocal
    from app.models.email_thread import EmailThread
    from app.repositories.email_thread_repo import resolve_thread_outbound_draft_id
except ModuleNotFoundError as e:
    print(e, file=sys.stderr)
    raise SystemExit(1) from None


def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill email_threads.draft_id from inferred outreach draft.")
    ap.add_argument("--dry-run", action="store_true", help="Print actions only; do not commit.")
    ap.add_argument("--run-id", type=int, default=None, help="Only threads in this run.")
    ap.add_argument("--thread-id", type=int, default=None, help="Only this thread row.")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        q = db.query(EmailThread).filter(EmailThread.draft_id.is_(None))
        if args.run_id is not None:
            q = q.filter(EmailThread.run_id == args.run_id)
        if args.thread_id is not None:
            q = q.filter(EmailThread.id == args.thread_id)
        threads = q.order_by(EmailThread.id.asc()).all()

        updated = 0
        unresolved = 0
        for t in threads:
            resolved = resolve_thread_outbound_draft_id(db, t)
            if not resolved:
                unresolved += 1
                print(f"skip thread id={t.id} run={t.run_id} contact={t.contact_id} — cannot infer draft")
                continue
            print(
                f"{'would set' if args.dry_run else 'set'} thread id={t.id} "
                f"run={t.run_id} contact={t.contact_id} draft_id={resolved}"
            )
            if not args.dry_run:
                t.draft_id = resolved
                db.add(t)
                updated += 1
        if not args.dry_run and updated:
            db.commit()
            print(f"Committed {updated} row(s).")
        elif args.dry_run:
            print(f"Dry-run: {len(threads) - unresolved} linkable, {unresolved} unresolved.")
        else:
            print("No rows updated.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
