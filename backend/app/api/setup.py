"""First-run integration: LLM + CDN keys (optional .env write when explicitly allowed)."""

import os
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

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
from app.services.gmail_oauth import (
    GmailOAuthError,
    google_client_configured,
    google_refresh_token_value,
    gmail_profile_email,
    list_send_as_rows,
    refresh_access_token,
    summarize_send_as_rows,
)

router = APIRouter(prefix="/setup", tags=["setup"])


@router.get("/gmail-send-as-list")
def setup_gmail_send_as_list() -> dict:
    """Verified «Send mail as» addresses for the connected Gmail account (debug GMAIL_SEND_AS_EMAIL)."""
    if not google_client_configured() or not google_refresh_token_value():
        raise HTTPException(
            status_code=400,
            detail="Gmail not configured in this process (see GET /setup/status).",
        )
    try:
        access = refresh_access_token()
        rows = list_send_as_rows(access)
        load_env_from_file()
        env_as = (os.environ.get("GMAIL_SEND_AS_EMAIL") or "").strip().strip('"').strip("'")
        return {
            "profileEmail": gmail_profile_email(access),
            "gmailSendAsFromEnv": env_as or None,
            "sendAs": summarize_send_as_rows(rows),
        }
    except GmailOAuthError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/gmail-mailbox")
def setup_gmail_mailbox() -> dict:
    """Which Gmail account this API sends as (matches users/me/profile). Use when mail seems to disappear."""
    if not google_client_configured() or not google_refresh_token_value():
        raise HTTPException(
            status_code=400,
            detail="Gmail not configured in this process (see GET /setup/status).",
        )
    try:
        access = refresh_access_token()
        return {"emailAddress": gmail_profile_email(access)}
    except GmailOAuthError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


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


class GmailCredentialsIn(BaseModel):
    client_id: str = Field(..., min_length=1)
    client_secret: str = Field(..., min_length=1)
    redirect_uri: str = Field(
        "",
        description="Optional; if empty, callback URL is built from the browser origin when you click Connect Gmail.",
    )


@router.post("/gmail-credentials")
def setup_gmail_credentials(body: GmailCredentialsIn) -> dict:
    if not bootstrap_env_write_allowed():
        raise HTTPException(
            status_code=403,
            detail=(
                "Saving to .env is disabled. Set ALLOW_SETUP_ENV_WRITE=true for local development "
                "(never in production), or edit backend/.env manually."
            ),
        )
    updates: dict[str, str] = {
        "GOOGLE_CLIENT_ID": body.client_id.strip(),
        "GOOGLE_CLIENT_SECRET": body.client_secret.strip(),
    }
    ruri = (body.redirect_uri or "").strip()
    if ruri:
        updates["GOOGLE_REDIRECT_URI"] = ruri
    if not ENV_FILE_PATH.is_file():
        upsert_env_file(
            {
                "APP_ENV": settings.APP_ENV,
                "DATABASE_URL": settings.DATABASE_URL,
                "REDIS_URL": settings.REDIS_URL,
            },
        )
    upsert_env_files_everywhere(updates)
    return {
        "ok": True,
        "message": "Gmail OAuth client saved to .env file(s) listed in GET /setup/status. Restart the API only if values are not picked up.",
    }
