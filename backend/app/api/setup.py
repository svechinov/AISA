"""First-run integration: LLM + CDN keys (optional .env write when explicitly allowed)."""

import os
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
from app.db import get_db
from app.models.system_setting import SystemSetting
from fastapi import APIRouter, HTTPException, Depends

from app.config import settings
from app.services.env_bootstrap import (
    ENV_FILE_PATH,
    LLM_KEY_BY_PROVIDER,
    VALID_LLM,
    bootstrap_env_write_allowed,
    load_env_from_file,
    upsert_env_file,
    upsert_env_files_everywhere,
)


router = APIRouter(prefix="/setup", tags=["setup"])





class LLMRowIn(BaseModel):
    provider: Literal["claude", "openai", "perplexity", "grok"]
    api_key: str = ""


class SetupBootstrapIn(BaseModel):
    """llm_rows preserves UI order (first = highest priority among providers with keys)."""

    llm_rows: list[LLMRowIn] = Field(..., min_length=4, max_length=4)
    cdn_provider: Literal["cloudflare", "akamai", "cloudfront", "gcp_cdn"]
    cdn_api_key: str

    @field_validator("llm_rows")
    @classmethod
    def llm_rows_unique_providers(cls, rows: list[LLMRowIn]) -> list[LLMRowIn]:
        ids = [r.provider for r in rows]
        if len(set(ids)) != len(ids):
            raise ValueError("Each LLM provider must appear exactly once")
        if set(ids) != VALID_LLM:
            raise ValueError("Must include all four LLM providers once")
        return rows


@router.post("/bootstrap")
def setup_bootstrap(body: SetupBootstrapIn) -> dict:
    if not bootstrap_env_write_allowed():
        raise HTTPException(
            status_code=403,
            detail=(
                "Saving to .env is disabled. Set ALLOW_SETUP_ENV_WRITE=true for local development "
                "(never in production), ensure APP_ENV is not production, or edit backend/.env manually."
            ),
        )

    keys_trimmed = {r.provider: (r.api_key or "").strip() for r in body.llm_rows}
    if not any(keys_trimmed.values()):
        raise HTTPException(status_code=422, detail="Provide at least one LLM API key")

    cdn_key = (body.cdn_api_key or "").strip()
    if not cdn_key:
        raise HTTPException(status_code=422, detail="CDN API key is required")

    priority = [p for p in (r.provider for r in body.llm_rows) if keys_trimmed.get(p)]
    priority_csv = ",".join(priority)

    updates: dict[str, str] = {
        "LLM_PROVIDER_PRIORITY": priority_csv,
        "CDN_PROVIDER": body.cdn_provider,
        "CDN_API_KEY": cdn_key,
    }
    for row in body.llm_rows:
        env_key = LLM_KEY_BY_PROVIDER[row.provider]
        updates[env_key] = keys_trimmed[row.provider]

    if not ENV_FILE_PATH.is_file():
        upsert_env_file(
            {
                "APP_ENV": settings.APP_ENV,
                "DATABASE_URL": settings.DATABASE_URL,
                "REDIS_URL": settings.REDIS_URL,
            },
        )

    upsert_env_file(updates)

    return {
        "ok": True,
        "message": "Configuration saved to backend/.env. Reload the page; restart the API if values are not picked up.",
    }


class YandexSetupIn(BaseModel):
    yandex_email: str
    yandex_password: str


@router.post("/yandex")
def setup_yandex(body: YandexSetupIn, db: Session = Depends(get_db)):
    if not body.yandex_email or "@" not in body.yandex_email:
        raise HTTPException(status_code=400, detail="Invalid Yandex email")
    if not body.yandex_password:
        raise HTTPException(status_code=400, detail="Password cannot be empty")

    for key, value in {"yandex_email": body.yandex_email, "yandex_password": body.yandex_password}.items():
        setting = db.query(SystemSetting).filter_by(key=key).first()
        if setting:
            setting.value = value
        else:
            db.add(SystemSetting(key=key, value=value))
    
    db.commit()

    return {"ok": True, "message": "Yandex credentials saved to database."}

class AiModelSetupIn(BaseModel):
    ai_model: str

@router.post("/ai_model")
def setup_ai_model(body: AiModelSetupIn, db: Session = Depends(get_db)):
    if not body.ai_model:
        raise HTTPException(status_code=400, detail="AI Model cannot be empty")

    setting = db.query(SystemSetting).filter_by(key="ai_model").first()
    if setting:
        setting.value = body.ai_model
    else:
        db.add(SystemSetting(key="ai_model", value=body.ai_model))
    
    db.commit()

    return {"ok": True, "message": "AI Model saved to database."}
