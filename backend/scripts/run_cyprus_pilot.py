"""Bounded pilot driver: 5-10 Cyprus game studios end-to-end, drafts only (no send).

Why a driver instead of the normal accumulation loop: the fork's Apollo org search does not
filter by location (only keyword tags + <=100 employees, hardcoded), so it cannot geo-target
Cyprus. Here we source a Cyprus-filtered company list directly via Apollo (organization_locations),
seed run_companies, then run the standard steps (Apollo find_contacts -> OSINT enrich + vacancy
radar -> validate -> generate) through the orchestrator so persistence matches production.

Run from backend/:  ./venv/bin/python scripts/run_cyprus_pilot.py
Requires APOLLO_API_KEY + TAVILY_API_KEY + LLM keys in .env, and the AlexStaff seed
(scripts/seed_alexstaff_preset.py) already applied (run 'Cyprus pilot').
"""

from __future__ import annotations

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

# --- load .env into os.environ (Tavily/Apollo read os.environ directly) ---
_envf = pathlib.Path(__file__).resolve().parents[1] / ".env"
for line in _envf.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

# --- pilot budget caps ---
os.environ["APOLLO_MAX_PEOPLE_PER_COMPANY"] = "3"
os.environ["APOLLO_MAX_PEOPLE_TOTAL"] = "24"
os.environ["OSINT_MAX_COMPANIES"] = "10"
os.environ["VACANCY_RADAR_MAX_COMPANIES"] = "10"

TARGET_COMPANIES = 8

from app.db import SessionLocal  # noqa: E402
from app.init_db import ensure_schema  # noqa: E402 — registers every model mapper
from app.models.contact import Contact  # noqa: E402
from app.models.run import Run  # noqa: E402
from app.models.run_company import RunCompany  # noqa: E402
from app.models.email_draft import EmailDraft  # noqa: E402
from app.repositories.run_company_repo import sync_run_companies_from_dicts  # noqa: E402
from app.repositories.step_repo import create_step, get_step_by_run_and_name, mark_step_completed  # noqa: E402
from app.services.apollo_service import _apollo_post_json, organization_row_to_company  # noqa: E402
from app.services.orchestrator import execute_step  # noqa: E402


def cyprus_studios(limit: int) -> list[dict]:
    """Apollo org search WITH Cyprus location filter (the pipeline's own search omits location)."""
    body = {
        "page": 1,
        "per_page": 25,
        "organization_locations": ["Cyprus"],
        "q_organization_keyword_tags": ["game development", "video games", "mobile games", "game studio"],
        "organization_num_employees_ranges": ["1,10", "11,20", "21,50", "51,100", "101,200", "201,500"],
    }
    data = _apollo_post_json("/organizations/search", json_body=body)
    orgs = data.get("organizations", []) or data.get("accounts", [])
    rows: list[dict] = []
    seen: set[str] = set()
    for org in orgs:
        row = organization_row_to_company(org) if isinstance(org, dict) else None
        if not row or not row.get("website"):
            continue
        key = row["website"].lower()
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)
        if len(rows) >= limit:
            break
    return rows


def main() -> None:
    ensure_schema()
    db = SessionLocal()
    try:
        run = db.query(Run).filter(Run.name == "Cyprus pilot").first()
        if not run:
            print("Run 'Cyprus pilot' not found — run scripts/seed_alexstaff_preset.py first.")
            return
        run_id = run.id

        print(f"[1/6] Sourcing Cyprus game studios via Apollo (target {TARGET_COMPANIES})…")
        have_companies = db.query(RunCompany).filter(RunCompany.run_id == run_id).count()
        if not have_companies:
            companies = cyprus_studios(TARGET_COMPANIES)
            if not companies:
                print("  Apollo returned no Cyprus studios — aborting.")
                return
            for c in companies:
                print(f"   - {c.get('name')}  ({c.get('website')})")
            sync_run_companies_from_dicts(db, run_id, companies, commit=False)
            db.commit()
        else:
            print(f"    companies already sourced ({have_companies}) — skipping Apollo org search.")

        # Mark collect_companies complete so the orchestrator's step-ordering is satisfied
        # (we sourced companies out-of-band with a Cyprus location filter).
        step_c = get_step_by_run_and_name(db, run_id, "collect_companies") or create_step(
            db, run_id, "collect_companies", {}
        )
        mark_step_completed(db, step_c, {"source": "apollo_cyprus"})
        db.commit()

        have_contacts = db.query(Contact).filter(Contact.run_id == run_id).count()
        if not have_contacts:
            print("[2/6] Finding decision-makers + emails via Apollo (find_contacts)…")
            execute_step(db, run_id, "find_contacts")
        else:
            print(f"[2/6] Contacts already found ({have_contacts}) — skipping Apollo people search.")

        print("[3/6] OSINT enrichment: company dossier + person OSINT + vacancy radar…")
        execute_step(db, run_id, "enrich_crm_data")

        print("[4/6] Validating contacts…")
        execute_step(db, run_id, "validate_contacts")

        # Auto-approve valid contacts so generate_emails drafts for them. In production this is
        # the human reviewer clicking "approve" in the UI; for the pilot we approve all valid rows.
        approved = (
            db.query(Contact)
            .filter(Contact.run_id == run_id, Contact.status == "valid")
            .all()
        )
        for c in approved:
            if c.review_status not in ("approved", "edited"):
                c.review_status = "approved"
        db.commit()
        print(f"    auto-approved {len(approved)} valid contact(s) for drafting.")

        print("[5/6] Master email draft…")
        execute_step(db, run_id, "generate_master_email_draft")

        print("[6/6] Generating personalized emails (5-slot skeleton + critic)…")
        execute_step(db, run_id, "generate_emails")

        import json as _json

        drafts = db.query(EmailDraft).filter(EmailDraft.run_id == run_id).all()
        print(f"\n===== {len(drafts)} DRAFT(S) GENERATED (not sent) =====\n")
        for d in drafts:
            meta = d.generation_meta_json
            if isinstance(meta, str):
                try:
                    meta = _json.loads(meta)
                except Exception:
                    meta = {}
            meta = meta or {}
            print("=" * 78)
            print(f"TO: {d.to_email}   ({d.company})")
            print(f"SUBJECT: {d.subject}")
            print(f"CRITIC: score={meta.get('validation_score')} valid={meta.get('is_valid')} "
                  f"retries={meta.get('validation_retries')} source={meta.get('pipeline_source')}")
            issues = meta.get("validation_issues") or []
            if issues:
                print(f"ISSUES: {issues}")
            print("-" * 78)
            print(d.body)
            print()
    finally:
        db.close()


if __name__ == "__main__":
    main()
