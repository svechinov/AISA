from sqlalchemy.orm import Session

from app.repositories.email_draft_repo import list_sendable_replacement_email_drafts_by_run
from app.repositories.run_repo import get_run
from app.services.email_sender import send_one_draft


def send_approved_replacement_drafts(db: Session, run_id: int) -> dict:
    run = get_run(db, run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found")

    drafts = list_sendable_replacement_email_drafts_by_run(db, run_id)

    results = []
    sent_count = 0
    failed_count = 0

    for draft in drafts:
        try:
            result = send_one_draft(db, draft.id)
        except ValueError as e:
            result = {"draft_id": draft.id, "status": "failed", "error": str(e)}

        results.append(result)

        if result.get("status") == "sent":
            sent_count += 1
        else:
            failed_count += 1

    return {
        "run_id": run_id,
        "replacement_drafts_found": len(drafts),
        "sent": sent_count,
        "failed": failed_count,
        "results": results,
    }
