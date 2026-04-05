from sqlalchemy.orm import Session

from app.repositories.contact_repo import (
    create_replacement_contact,
    find_replacement_contact_for_source,
)
from app.repositories.research_task_repo import (
    get_research_task_by_id,
    mark_research_task_completed,
    mark_research_task_failed,
    mark_research_task_no_result,
    mark_research_task_running,
)
from app.services.replacement_worker import find_replacement_candidate
from app.utils.research_task_payload import effective_research_output_json


def run_replacement_task(db: Session, task_id: int) -> dict:
    task = get_research_task_by_id(db, task_id)
    if not task:
        raise ValueError(f"Research task {task_id} not found")

    if task.task_type != "find_replacement_email":
        raise ValueError(f"Task {task_id} is not a replacement task")

    if task.status == "completed":
        return {
            "task_id": task.id,
            "status": "completed",
            "replacement_contact_id": (effective_research_output_json(db, task) or {}).get(
                "replacement_contact_id"
            ),
            "deduplicated": True,
            "message": "Task already completed",
        }

    mark_research_task_running(db, task)

    try:
        existing = None
        if task.contact_id:
            existing = find_replacement_contact_for_source(db, task.run_id, task.contact_id)

        if existing:
            mark_research_task_completed(
                db,
                task,
                {
                    "message": "Replacement already exists",
                    "replacement_contact_id": existing.id,
                },
            )
            return {
                "task_id": task.id,
                "status": "completed",
                "replacement_contact_id": existing.id,
                "deduplicated": True,
            }

        candidate = find_replacement_candidate(db, task)

        if not candidate:
            mark_research_task_no_result(
                db,
                task,
                {
                    "message": "No replacement candidate found",
                },
            )
            return {
                "task_id": task.id,
                "status": "no_result",
            }

        replacement = create_replacement_contact(
            db=db,
            run_id=task.run_id,
            source_contact_id=task.contact_id,
            research_task_id=task.id,
            company=candidate.get("company"),
            website=candidate.get("website"),
            name=candidate.get("name"),
            role=candidate.get("role"),
            email=candidate.get("email"),
            linkedin=candidate.get("linkedin"),
            confidence=candidate.get("confidence"),
        )

        mark_research_task_completed(
            db,
            task,
            {
                "message": "Replacement contact created",
                "replacement_contact_id": replacement.id,
                "candidate": candidate,
            },
        )

        return {
            "task_id": task.id,
            "status": "completed",
            "replacement_contact_id": replacement.id,
        }

    except Exception as e:
        mark_research_task_failed(
            db,
            task,
            {
                "message": "Replacement task failed",
                "error": str(e),
            },
        )
        return {
            "task_id": task.id,
            "status": "failed",
            "error": str(e),
        }
