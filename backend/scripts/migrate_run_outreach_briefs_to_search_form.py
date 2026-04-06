#!/usr/bin/env python3
"""
Rewrite every run's outreach brief into the search form (labeled sections) and normalize master_prompt.

Also maps legacy runs.email_style_mode values (direct/warm/sharp/executive) → auto.

Usage (from repo):
  cd backend && python scripts/migrate_run_outreach_briefs_to_search_form.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.db import SessionLocal  # noqa: E402
from app.models.run import Run  # noqa: E402
from app.repositories.run_repo import get_run, update_run_outreach_fields  # noqa: E402
from app.services.email_style_service import LEGACY_EMAIL_VOICE_MODES  # noqa: E402
from app.services.run_context_service import (  # noqa: E402
    build_master_prompt_text,
    format_search_brief_from_inner,
    get_effective_context,
    merge_inner_from_legacy_fields,
    parse_outreach_brief_text,
)


def main() -> int:
    db = SessionLocal()
    touched_brief = 0
    touched_style = 0
    try:
        ids = [r.id for r in db.query(Run.id).order_by(Run.id.asc()).all()]
        for rid in ids:
            run = get_run(db, rid)
            if not run:
                continue
            inner = get_effective_context(run)
            new_text = format_search_brief_from_inner(inner)
            parsed = parse_outreach_brief_text(new_text)
            inner2 = merge_inner_from_legacy_fields(
                parsed,
                product="",
                target_entities="",
                target_roles="",
                outreach_goal="",
                tone="Professional",
                extra_context="",
            )
            if not inner2.get("notes") and run.notes:
                inner2["notes"] = str(run.notes).strip()
            master = build_master_prompt_text(inner2)
            seg = (run.segment or "").strip() or "—"
            update_run_outreach_fields(
                db,
                rid,
                notes=run.notes,
                segment=seg,
                inner=inner2,
                master_prompt=master,
            )
            touched_brief += 1

        for run in db.query(Run).order_by(Run.id.asc()).all():
            m = run.email_style_mode
            if isinstance(m, str) and m.strip().lower() in LEGACY_EMAIL_VOICE_MODES:
                run.email_style_mode = "auto"
                db.add(run)
                touched_style += 1
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    print(f"migrate_run_outreach_briefs_to_search_form: updated outreach for {touched_brief} run(s).")
    print(f"Legacy email_style_mode → auto: {touched_style} run(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
