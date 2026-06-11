"""Phase 4 endpoints: pull companies into a run from external sources (ratings / tenders)."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.repositories.run_company_repo import append_companies_to_run
from app.repositories.run_repo import run_exists
from app.services.company_source_extractor import (
    extract_companies_by_criterion,
    extract_companies_from_tenders,
    extract_companies_from_url,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/company-sources", tags=["company-sources"])


class ExtractUrlBody(BaseModel):
    url: str
    hint: str = ""


class ExtractCriterionBody(BaseModel):
    criterion: str
    max_urls: int = 2


class ExtractTendersBody(BaseModel):
    query: str = ""
    max_results: int = 8


def _append(db: Session, run_id: int, companies: list[dict], source: dict) -> dict:
    if not run_exists(db, run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    result = append_companies_to_run(db, run_id, companies, source=source)
    return {
        "extracted": len(companies),
        "added": result["added"],
        "added_count": len(result["added"]),
        "skipped_duplicates": result["skipped_duplicates"],
    }


@router.post("/run/{run_id}/extract-url")
def extract_url_route(run_id: int, payload: ExtractUrlBody, db: Session = Depends(get_db)):
    """«Дан URL»: extract the companies listed on a rating/list page and append them to the run."""
    try:
        companies = extract_companies_from_url(payload.url, hint=payload.hint)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("extract-url failed")
        raise HTTPException(status_code=502, detail=f"Extraction failed: {e}") from e
    out = _append(db, run_id, companies, {"type": "rating_url", "url": payload.url})
    return out


@router.post("/run/{run_id}/extract-criterion")
def extract_criterion_route(run_id: int, payload: ExtractCriterionBody, db: Session = Depends(get_db)):
    """«Дан критерий»: search for rating/list pages, extract them, append companies."""
    try:
        data = extract_companies_by_criterion(payload.criterion, max_urls=payload.max_urls)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("extract-criterion failed")
        raise HTTPException(status_code=502, detail=f"Extraction failed: {e}") from e
    out = _append(
        db, run_id, data["companies"],
        {"type": "criterion", "criterion": payload.criterion, "urls": data["urls"]},
    )
    out["source_urls"] = data["urls"]
    return out


@router.post("/run/{run_id}/extract-tenders")
def extract_tenders_route(run_id: int, payload: ExtractTendersBody, db: Session = Depends(get_db)):
    """Tender intent: companies that are purchasing training right now (заказчики закупок)."""
    try:
        data = extract_companies_from_tenders(payload.query, max_results=payload.max_results)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("extract-tenders failed")
        raise HTTPException(status_code=502, detail=f"Extraction failed: {e}") from e
    out = _append(
        db, run_id, data["companies"],
        {"type": "tender_intent", "query": payload.query, "urls": data["urls"]},
    )
    out["source_urls"] = data["urls"]
    return out
