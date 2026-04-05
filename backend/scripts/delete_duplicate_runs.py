#!/usr/bin/env python3
"""
Drop duplicate runs in a project (same outreach fingerprint). Keeps one run per group.

Fingerprint = project_id + workflow_name + normalized name + JSON keys of brief-related fields.
Rows are deleted with delete_run_cascade (contacts, drafts, threads, steps, etc.).

From the backend directory:

  python3 scripts/delete_duplicate_runs.py --project-id 1
  python3 scripts/delete_duplicate_runs.py --project-id 1 --dry-run
  python3 scripts/delete_duplicate_runs.py --project-id 1 --keep newest

  Same display name (when fingerprints differ, e.g. double-submit):

  python3 scripts/delete_duplicate_runs.py --project-id 2 --run-name "Mr. Freeman backpacks" --dry-run
  python3 scripts/delete_duplicate_runs.py --project-id 2 --run-name "Mr. Freeman backpacks" --keep oldest

  Explicit ids (must belong to the project):

  python3 scripts/delete_duplicate_runs.py --project-id 2 --delete-run-ids 21,22

Loads DATABASE_URL from backend/.env (same as wipe_all_data.py).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
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
    from sqlalchemy.orm import Session, selectinload

    from app.db import SessionLocal
    from app.models.run import Run
    from app.services.run_context_service import get_sender_signature_html
    from app.services.run_deletion_service import delete_run_cascade
except ModuleNotFoundError as e:
    print(e, file=sys.stderr)
    raise SystemExit(1) from None


def _fingerprint(run: Run) -> tuple:
    name = (run.name or "").strip().lower()
    ctx = json.dumps(run.context_json or {}, sort_keys=True, default=str)
    ij = json.dumps(run.input_json or {}, sort_keys=True, default=str)
    mp = (run.master_prompt or "").strip()
    seg = (run.segment or "").strip()
    notes = (run.notes or "").strip()
    me = json.dumps(run.master_email or {}, sort_keys=True, default=str)
    me_sub = (run.master_email_subject or "").strip()
    me_body = (run.master_email_body or "").strip()
    sig = (get_sender_signature_html(run) or "").strip()
    return (
        run.project_id,
        run.workflow_name,
        name,
        ctx,
        ij,
        mp,
        seg,
        notes,
        me,
        me_sub,
        me_body,
        sig,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Delete duplicate runs in a project.")
    ap.add_argument("--project-id", type=int, required=True)
    ap.add_argument(
        "--keep",
        choices=("oldest", "newest"),
        default="oldest",
        help="Which run id to keep in each duplicate group (default: smallest id).",
    )
    ap.add_argument("--dry-run", action="store_true", help="Only print what would be deleted.")
    ap.add_argument(
        "--run-name",
        type=str,
        default=None,
        help="Match run.name case-insensitively (trimmed). If 2+ runs match, delete all but one (--keep oldest|newest).",
    )
    ap.add_argument(
        "--delete-run-ids",
        type=str,
        default=None,
        help="Comma-separated run ids to hard-delete (each must belong to --project-id).",
    )
    args = ap.parse_args()

    db: Session = SessionLocal()
    try:
        runs = (
            db.query(Run)
            .options(selectinload(Run.run_setup))
            .filter(Run.project_id == args.project_id)
            .order_by(Run.id.asc())
            .all()
        )
        to_delete: list[int] = []

        if args.delete_run_ids:
            want = [int(x.strip()) for x in args.delete_run_ids.split(",") if x.strip()]
            by_id = {r.id: r for r in runs}
            for rid in want:
                if rid not in by_id:
                    print(f"Skip run_id={rid}: not in project {args.project_id}", file=sys.stderr)
                    continue
                to_delete.append(rid)
            if to_delete:
                print(f"--delete-run-ids → will remove: {to_delete}")
        elif args.run_name:
            norm = args.run_name.strip().lower()
            matching = [r for r in runs if (r.name or "").strip().lower() == norm]
            if len(matching) < 2:
                print(
                    f"Only {len(matching)} run(s) match name {args.run_name!r} in project {args.project_id}: "
                    f"{[r.id for r in matching]}. Nothing to delete.",
                )
                return
            ms = sorted(matching, key=lambda r: r.id)
            keeper = ms[0].id if args.keep == "oldest" else ms[-1].id
            to_delete = [r.id for r in ms if r.id != keeper]
            print(f"Mode --run-name: keep run_id={keeper}, delete {to_delete}")
        else:
            groups: dict[tuple, list[Run]] = defaultdict(list)
            for r in runs:
                groups[_fingerprint(r)].append(r)

            for _key, grp in sorted(groups.items(), key=lambda x: min(r.id for r in x[1])):
                if len(grp) < 2:
                    continue
                grp_sorted = sorted(grp, key=lambda r: r.id)
                if args.keep == "oldest":
                    survivors = {grp_sorted[0].id}
                else:
                    survivors = {grp_sorted[-1].id}
                for r in grp_sorted:
                    if r.id not in survivors:
                        to_delete.append(r.id)

            if not to_delete:
                print("No duplicate groups found (fingerprint mode).")
                return

            print(f"Duplicate groups: {sum(1 for g in groups.values() if len(g) > 1)}")
            print(f"Runs to delete: {len(to_delete)} -> {to_delete}")

        if not to_delete:
            print("Nothing to delete.")
            return

        if args.dry_run:
            print("Dry run; no changes.")
            return

        for rid in to_delete:
            delete_run_cascade(db, rid, commit=True)
            print(f"Deleted run_id={rid}")

        print("Done.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
