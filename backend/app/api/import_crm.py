import io
import logging
import math
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session
import pandas as pd

from app.db import SessionLocal, get_db
from app.repositories.run_repo import create_run, get_run, update_run_status
from app.repositories.run_company_repo import sync_run_companies_from_dicts
from app.repositories.step_repo import create_step, mark_step_completed
from app.repositories.contact_repo import create_contact
from app.schemas.run import RunRead, run_read_from_orm

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/runs", tags=["runs"])


def _advance_imported_run(run_id: int) -> None:
    """After an AmoCRM import, advance the run through OSINT enrichment + validation to review.

    collect_companies / find_contacts are already completed by the import (contacts are known),
    so we do NOT re-run discovery. We only enrich (company dossier + missing-email OSINT) and
    validate, then park the run at ``needs_review`` for the user — same review gate as a normal run.
    Runs in a background task with its own DB session (request session is closed by then).
    """
    db = SessionLocal()
    try:
        from app.services.orchestrator import execute_step

        execute_step(db, run_id, "enrich_crm_data")
        execute_step(db, run_id, "validate_contacts")
        run = get_run(db, run_id)
        if run:
            update_run_status(db, run, "needs_review")
    except Exception:
        logger.exception("Post-import advance failed for run_id=%s", run_id)
        run = get_run(db, run_id)
        if run:
            update_run_status(db, run, "failed")
    finally:
        db.close()


@router.post("/import-amocrm", response_model=RunRead)
async def import_amocrm_route(
    background_tasks: BackgroundTasks,
    run_name: str = Form(...),
    project_id: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(
            status_code=400, detail="Invalid file type. Please upload an Excel file."
        )

    contents = await file.read()
    try:
        df = pd.read_excel(io.BytesIO(contents))
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Failed to parse Excel file: {str(e)}"
        )

    run = create_run(
        db=db,
        project_id=project_id,
        workflow_name="generic_outreach",
        input_json={"goal": "CRM Import"},
        name=run_name,
        notes="Imported from AmoCRM",
        master_prompt="CRM Import",
    )

    # ensure it starts directly at the right place.
    # Let's set it as "running" as per goal
    run.status = "running"

    # mark steps completed
    s1 = create_step(db, run.id, "collect_companies", {"source": "amocrm_import"})
    mark_step_completed(db, s1, {})
    s2 = create_step(db, run.id, "find_contacts", {"source": "amocrm_import"})
    mark_step_completed(db, s2, {})

    companies_to_sync = []

    for i, row in df.iterrows():
        name = row.get("Наименование", row.get("Компания"))
        if pd.isna(name) or not str(name).strip():
            continue

        website = row.get("Web (компания)", row.get("Web"))
        if pd.isna(website):
            website = None

        companies_to_sync.append(
            {
                "name": str(name).strip(),
                "website": str(website).strip() if website else None,
                "status": "valid",
                "contact_status": "found",
            }
        )

    sync_run_companies_from_dicts(db, run.id, companies_to_sync)

    for i, row in df.iterrows():
        name = row.get("Наименование", row.get("Компания"))
        if pd.isna(name) or not str(name).strip():
            continue

        website = row.get("Web (компания)", row.get("Web"))
        if pd.isna(website):
            website = None

        contact_name = f"{row.get('Имя', '')} {row.get('Фамилия', '')}".strip()
        role = row.get("Должность (контакт)")
        if pd.isna(role):
            role = None

        email = row.get("Рабочий email")
        if pd.isna(email):
            email = row.get("Личный email")
        if pd.isna(email):
            email = row.get("Другой email")
        if pd.isna(email):
            email = None

        status = "valid" if email and "@" in str(email) else "needs_discovery"

        create_contact(
            db=db,
            run_id=run.id,
            company=str(name).strip(),
            website=str(website).strip() if website else None,
            name=contact_name if contact_name else None,
            role=str(role).strip() if role else None,
            email=str(email).strip() if email else None,
            status=status,
            source_json={"source": "amocrm_import"},
        )

    db.commit()

    # Advance the imported run through enrichment + validation to review (background).
    # NOTE: this triggers OSINT (Tavily per company) automatically after import — for large
    # imports a per-run company/token budget (Q19) should gate this before unattended use.
    background_tasks.add_task(_advance_imported_run, run.id)

    return run_read_from_orm(run)
