#!/usr/bin/env python3
"""
Backfill `llm_hallucination` on rows in the `run_companies` table (runs with no rows are skipped).

Uses the same rules as live collect (basic URL checks + optional HTTP reachability).

Run from the backend directory **with the same Python env as uvicorn** (venv or Docker), after:

  pip install -r requirements.txt

Example (one-time venv):

  cd backend
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -r requirements.txt
  python scripts/mark_collect_company_llm_flags.py --dry-run --all-runs

Loads DATABASE_URL from backend/.env (see other scripts).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))


def _die_missing_deps(missing: str) -> None:
    print(
        f"Error: {missing}\n\n"
        "This script needs the backend virtualenv (same packages as the API).\n"
        f"From {_root} run:\n"
        "  python3 -m venv .venv\n"
        "  source .venv/bin/activate\n"
        "  pip install -r requirements.txt\n"
        "  python scripts/mark_collect_company_llm_flags.py ...\n",
        file=sys.stderr,
    )
    raise SystemExit(1)


try:
    import sqlalchemy  # noqa: F401
except ModuleNotFoundError:
    _die_missing_deps("No module named 'sqlalchemy'")

try:
    from app.services.env_bootstrap import load_env_from_file
except ModuleNotFoundError as e:
    _die_missing_deps(str(e))

load_env_from_file()

try:
    from app.db import SessionLocal
    from app.models.run import Run
    from app.models.run_company import RunCompany
    from app.repositories.run_company_repo import (
        count_run_companies,
        run_company_orm_to_dict,
        sync_run_companies_from_dicts,
    )
    from app.services.company_website_check import annotate_companies_list_with_llm_flags
except ModuleNotFoundError as e:
    _die_missing_deps(str(e))


def main() -> None:
    ap = argparse.ArgumentParser(description="Set llm_hallucination on collect_companies company rows.")
    ap.add_argument("--run-id", type=int, default=None, help="Only this run id.")
    ap.add_argument("--all-runs", action="store_true", help="Process every run that has a collect_companies step.")
    ap.add_argument("--dry-run", action="store_true", help="Log counts only; do not write the database.")
    ap.add_argument(
        "--no-http",
        action="store_true",
        help="Only basic URL checks (same as COLLECT_COMPANIES_HTTP_CHECK_ENABLED=false).",
    )
    args = ap.parse_args()

    if not args.run_id and not args.all_runs:
        print("Specify --run-id N or --all-runs", file=sys.stderr)
        raise SystemExit(2)

    db = SessionLocal()
    try:
        q = db.query(Run)
        if args.run_id is not None:
            q = q.filter(Run.id == args.run_id)
        runs = q.order_by(Run.id.asc()).all()
        total_updated = 0
        for run in runs:
            if count_run_companies(db, run.id) == 0:
                print(f"run_id={run.id}: no run_companies rows — skip")
                continue
            rows = (
                db.query(RunCompany)
                .filter(RunCompany.run_id == run.id)
                .order_by(RunCompany.collect_index.asc())
                .all()
            )
            list_in = [run_company_orm_to_dict(db, r) for r in rows]
            new_list = annotate_companies_list_with_llm_flags(
                list_in,
                run_id=run.id,
                http_check_enabled=False if args.no_http else None,
            )
            max_i = max(r.collect_index for r in rows)
            full: list = [None] * (max_i + 1)
            for r, ann in zip(rows, new_list):
                full[r.collect_index] = ann
            n_hall = sum(1 for x in new_list if isinstance(x, dict) and x.get("llm_hallucination"))
            print(
                f"run_id={run.id}: companies={len(new_list)} llm_hallucination={n_hall} "
                f"dry_run={args.dry_run}",
            )
            if args.dry_run:
                continue
            sync_run_companies_from_dicts(db, run.id, full, commit=True)
            total_updated += 1
        print(f"Done. Runs written: {total_updated}.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
