#!/usr/bin/env python3
"""
One-off: copy legacy collect_companies.output_json["companies"] into run_companies, then remove the key.

The app never reads companies from step JSON at runtime; run this once on DBs that still have pre-table data.

  cd backend && python scripts/migrate_run_companies_from_legacy_step_json.py

Loads DATABASE_URL via env_bootstrap (same as other scripts).
"""

from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from app.services.env_bootstrap import load_env_from_file

load_env_from_file()


def main() -> None:
    from sqlalchemy import inspect
    from sqlalchemy.orm.attributes import flag_modified

    import app.init_db  # noqa: F401 — register models on Base.metadata

    from app.db import Base, SessionLocal, engine
    from app.models.run import Run
    from app.models.run_company import RunCompany
    from app.models.step import Step
    from app.repositories.run_company_repo import sync_run_companies_from_dicts
    from app.repositories.step_repo import get_step_by_run_and_name

    Base.metadata.create_all(bind=engine)

    insp = inspect(engine)
    if "run_companies" not in insp.get_table_names():
        print("run_companies table missing — run ensure_schema first.")
        raise SystemExit(1)

    db = SessionLocal()
    migrated = 0
    try:
        for run in db.query(Run).order_by(Run.id.asc()).all():
            if db.query(RunCompany).filter(RunCompany.run_id == run.id).count() > 0:
                continue
            step = get_step_by_run_and_name(db, run.id, "collect_companies")
            if not step:
                continue
            out = step.output_json if isinstance(step.output_json, dict) else {}
            companies = out.get("companies")
            if not isinstance(companies, list) or not companies:
                continue
            if not any(isinstance(c, dict) for c in companies):
                continue
            sync_run_companies_from_dicts(db, run.id, companies, commit=False)
            step.output_json = {k: v for k, v in out.items() if k != "companies"}
            flag_modified(step, "output_json")
            db.add(step)
            db.commit()
            migrated += 1
        print(f"Copied companies into run_companies for {migrated} run(s).")

        n = 0
        for step in db.query(Step).filter(Step.step_name == "collect_companies").all():
            out = step.output_json if isinstance(step.output_json, dict) else {}
            if "companies" not in out:
                continue
            step.output_json = {k: v for k, v in out.items() if k != "companies"}
            flag_modified(step, "output_json")
            db.add(step)
            n += 1
        if n:
            db.commit()
            print(f"Removed output_json['companies'] from {n} collect step(s).")
        else:
            db.rollback()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
