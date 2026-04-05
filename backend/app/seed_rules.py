"""
Idempotent seed of default workflow rules. Run: PYTHONPATH=. python -m app.seed_rules
"""

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.rule import Rule
from app.repositories.rule_repo import create_rule

WF = "generic_outreach"

SEED_SPECS: list[dict] = [
    {
        "scope": "global",
        "content": "Return concise structured business-ready output.",
    },
    {
        "scope": "workflow",
        "workflow_name": WF,
        "content": "Match companies and contacts to the campaign brief; do not assume a single industry.",
    },
    {
        "scope": "step",
        "workflow_name": WF,
        "step_name": "collect_companies",
        "content": (
            "Return only company name and website per row; no prose. "
            "Never fabricate organizations: every row must be a real company the user could look up; "
            "omit uncertain names instead of inventing them."
        ),
    },
    {
        "scope": "step",
        "workflow_name": WF,
        "step_name": "find_contacts",
        "content": "Prefer roles described in the campaign brief (target roles / decision-makers).",
    },
    {
        "scope": "step",
        "workflow_name": WF,
        "step_name": "generate_master_email_draft",
        "content": "One subject line and one email body; match tone from brief; no markdown.",
    },
    {
        "scope": "step",
        "workflow_name": WF,
        "step_name": "generate_emails",
        "content": "Keep tone professional, concise, and business-friendly.",
    },
]

# Legacy workflow name in DB / API — same rules as generic_outreach
for spec in list(SEED_SPECS):
    if spec.get("workflow_name") == WF:
        dup = dict(spec)
        dup["workflow_name"] = "vod_outreach"
        SEED_SPECS.append(dup)


def _already_have(db: Session, spec: dict) -> bool:
    q = db.query(Rule).filter(
        Rule.scope == spec["scope"],
        Rule.content == spec["content"],
        Rule.active.is_(True),
    )
    if spec.get("workflow_name") is not None:
        q = q.filter(Rule.workflow_name == spec["workflow_name"])
    else:
        q = q.filter(Rule.workflow_name.is_(None))
    if spec.get("step_name") is not None:
        q = q.filter(Rule.step_name == spec["step_name"])
    else:
        q = q.filter(Rule.step_name.is_(None))
    return q.first() is not None


def seed_default_rules(db: Session) -> int:
    created = 0
    for spec in SEED_SPECS:
        if _already_have(db, spec):
            continue
        create_rule(
            db,
            scope=spec["scope"],
            content=spec["content"],
            project_id=spec.get("project_id"),
            workflow_name=spec.get("workflow_name"),
            step_name=spec.get("step_name"),
            active=True,
        )
        created += 1
    return created


def main():
    db = SessionLocal()
    try:
        n = seed_default_rules(db)
        print(f"seed_default_rules: created {n} new rule(s)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
