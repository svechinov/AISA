import io
import math
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session
import pandas as pd

from app.db import get_db
from app.repositories.run_repo import create_run
from app.repositories.run_company_repo import sync_run_companies_from_dicts
from app.repositories.step_repo import create_step, mark_step_completed
from app.repositories.contact_repo import create_contact
from app.schemas.run import RunRead, run_read_from_orm

router = APIRouter(prefix="/runs", tags=["runs"])


@router.post("/import-amocrm", response_model=RunRead)
async def import_amocrm_route(
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
        # Do NOT put "CRM Import" into goal/master_prompt: the email generator treated it as the
        # product being sold (emails pitched "внедрение CRM" instead of FG consulting). The offer
        # must come from the editable prompt_setup_text (FG persona), not from the import mechanics.
        input_json={"goal": "Импортированная база контактов (AmoCRM)"},
        name=run_name,
        notes="Imported from AmoCRM",
        master_prompt="",
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

    # Manual pipeline model (debug phase): the run is left at collect/find done with contacts
    # loaded. The user advances OSINT enrichment / validation explicitly per step
    # (POST /steps/run/{id}/execute/...) so progress is transparent. Auto-advance will be added
    # later behind a setting. See engine_reconciliation_plan Фаза 1.
    return run_read_from_orm(run)
