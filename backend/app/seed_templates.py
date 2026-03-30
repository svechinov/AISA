from app.db import SessionLocal
from app.repositories.template_repo import create_template, get_template_by_type


def seed():
    db = SessionLocal()
    try:
        subject = get_template_by_type(db, "outreach_subject", project_id=None)
        if not subject:
            create_template(
                db=db,
                project_id=None,
                template_type="outreach_subject",
                name="Default outreach subject",
                content="Collaboration — {{company}}",
                variables_json={
                    "variables": ["company", "website", "name", "role", "email"]
                },
            )

        body = get_template_by_type(db, "outreach_body", project_id=None)
        if not body:
            create_template(
                db=db,
                project_id=None,
                template_type="outreach_body",
                name="Default outreach body",
                content=(
                    "Hi {{name}},\n\n"
                    "We're reaching out with a short note that may be relevant to {{company}}.\n\n"
                    "Best regards"
                ),
                variables_json={
                    "variables": ["company", "website", "name", "role", "email"]
                },
            )
    finally:
        db.close()


if __name__ == "__main__":
    seed()
