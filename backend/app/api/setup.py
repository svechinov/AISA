"""First-run integration: LLM + CDN keys (optional .env write when explicitly allowed)."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field, field_validator

from app.config import settings
from app.services.env_bootstrap import (
    ENV_FILE_PATH,
    LLM_KEY_BY_PROVIDER,
    VALID_LLM,
    bootstrap_env_write_allowed,
    build_setup_hints,
    cdn_configured_from_environ,
    cdn_provider_id_from_environ,
    discover_env_files,
    llm_configured_from_environ,
    llm_providers_ready_from_environ,
    load_env_from_file,
    upsert_env_file,
)

router = APIRouter(prefix="/setup", tags=["setup"])


class SetupStatus(BaseModel):
    llm_configured: bool
    cdn_configured: bool
    allow_env_write: bool
    env_paths_found: list[str] = []
    hints: list[str] = []
    llm_providers_ready: list[str] = Field(
        default_factory=list,
        description="LLM provider ids with keys (priority order), e.g. claude, openai.",
    )
    cdn_provider: str = Field(
        "",
        description="CDN_PROVIDER id when set, e.g. cloudflare (empty if unset).",
    )


@router.get("/status", response_model=SetupStatus)
def setup_status(response: Response) -> SetupStatus:
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    load_env_from_file()
    llm_ok = llm_configured_from_environ()
    cdn_ok = cdn_configured_from_environ()
    allow = bootstrap_env_write_allowed()
    paths = [str(p.resolve()) for p in discover_env_files()]
    hints = build_setup_hints(llm_ok=llm_ok, cdn_ok=cdn_ok, allow_write=allow)
    return SetupStatus(
        llm_configured=llm_ok,
        cdn_configured=cdn_ok,
        allow_env_write=allow,
        env_paths_found=paths,
        hints=hints,
        llm_providers_ready=llm_providers_ready_from_environ(),
        cdn_provider=cdn_provider_id_from_environ(),
    )


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
