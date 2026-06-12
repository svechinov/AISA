from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.services.env_bootstrap import env_files_for_pydantic

_env_tuple = env_files_for_pydantic()
_model_cfg: dict = {
    "env_file_encoding": "utf-8",
    "extra": "ignore",
}
if _env_tuple:
    _model_cfg["env_file"] = _env_tuple


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/ai_biz_os"
    REDIS_URL: str = "redis://localhost:6379/0"
    APP_NAME: str = "AI Biz OS"
    APP_ENV: str = "dev"
    GLOBAL_PASSWORD: str = ""
    HTTP_PROXY: str = ""

    # LLM (at least one required for full operation; see /setup flow)
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    PERPLEXITY_API_KEY: str = ""
    XAI_API_KEY: str = ""
    LLM_PROVIDER_PRIORITY: str = "claude,openai,perplexity,grok"
    # Optional model ids (provider defaults are in llm_gateway if unset)
    ANTHROPIC_MODEL: str = "claude-3-5-sonnet-20241022"
    OPENAI_MODEL: str = "gpt-4o"
    PERPLEXITY_MODEL: str = "sonar"
    XAI_MODEL: str = "grok-2-latest"

    # CDN / object storage integration (provider-specific credentials may need extra vars; see .env.example)
    CDN_PROVIDER: str = ""
    CDN_API_KEY: str = ""
    # Cloudflare R2 (S3-compatible) — file uploads from Human UI «Add file»
    CDN_ACCOUNT_ID: str = ""
    CDN_R2_BUCKET: str = ""
    CDN_R2_ACCESS_KEY_ID: str = ""
    CDN_R2_SECRET_ACCESS_KEY: str = ""
    # Public URL prefix for R2 objects (custom domain or *.r2.dev), no trailing slash
    CDN_R2_PUBLIC_BASE_URL: str = ""
    CDN_UPLOAD_MAX_BYTES_MB: int = 50

    # Allow POST /setup/bootstrap to write backend/.env (never enable in production)
    ALLOW_SETUP_ENV_WRITE: bool = False

    # Gmail API (single mailbox for outreach + replies; optional GOOGLE_REDIRECT_URI overrides auto callback URL)
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = ""
    GOOGLE_REFRESH_TOKEN: str = ""
    # Optional "From" for Gmail API — must be listed under Gmail → Settings → Accounts → Send mail as.
    # Empty = primary address of the OAuth mailbox.
    GMAIL_SEND_AS_EMAIL: str = ""
    # HMAC for OAuth state (fallback: derived from DATABASE_URL if empty — stable per DB URL)
    OAUTH_STATE_SECRET: str = ""

    # Outbound mail: when False, missing Gmail credentials raise instead of fake "mock" delivery (recommended).
    EMAIL_ALLOW_MOCK: bool = False
    # Optional override for Drafts «Send test copy». If empty, uses OAuth mailbox (users/me/profile).
    GMAIL_PREVIEW_RECIPIENT_EMAIL: str = ""
    # Background Gmail sync: poll threads + bounces (seconds). 0 = disabled (use POST /gmail-sync/*).
    GMAIL_SYNC_INTERVAL_SECONDS: int = 120

    # collect_companies: drop LLM rows whose website does not respond (GET + stream prefix, concurrent).
    COLLECT_COMPANIES_HTTP_CHECK_ENABLED: bool = True
    COLLECT_COMPANIES_HTTP_TIMEOUT_SEC: float = 8.0
    COLLECT_COMPANIES_HTTP_MAX_WORKERS: int = 8

    # Apollo.io — company + people search (optional). APOLLO_KEY in .env is the same key (older name).
    APOLLO_API_KEY: str = Field(
        default="",
        validation_alias=AliasChoices("APOLLO_API_KEY", "APOLLO_KEY"),
        description="Apollo API key; env may use APOLLO_API_KEY or APOLLO_KEY.",
    )
    APOLLO_HTTP_TIMEOUT_SEC: float = 45.0
    APOLLO_MAX_ORG_PAGE_SIZE: int = 50
    APOLLO_MAX_PEOPLE_PER_COMPANY: int = 8
    APOLLO_MAX_PEOPLE_TOTAL: int = 120

    # Dadata — firmographics (employee_count from FNS ССЧ, OKVED, INN). Optional; gates the
    # deterministic ICP size-filter (Phase 6). Free find-party fallback (egrul.itsoft) needs no key.
    DADATA_API_KEY: str = Field(default="", description="Dadata API token (Расширенный tier for employee_count).")
    DADATA_HTTP_TIMEOUT_SEC: float = 10.0
    FIRMOGRAPHICS_PROVIDER_PRIORITY: str = Field(
        default="dadata,egrul_free",
        description="Comma-ordered firmographics providers; first configured+answering wins.",
    )

    # Web search provider (R4). Yandex Cloud Search API = real yandex.ru index (sees VK/Telegram/
    # regional RU press that the US-indexed Tavily misses). Yandex primary for RU, Tavily fallback.
    YANDEX_SEARCH_API_KEY: str = Field(default="", description="Yandex Cloud Search API key (Api-Key auth).")
    YANDEX_FOLDER_ID: str = Field(default="", description="Yandex Cloud folder id (required on every request).")
    YANDEX_SEARCH_REGION: str = Field(default="225", description="Yandex search region (225 = Russia).")
    YANDEX_HTTP_TIMEOUT_SEC: float = 40.0
    SEARCH_PROVIDER_PRIORITY: str = Field(
        default="yandex,tavily",
        description="Comma-ordered web-search providers; first configured+answering wins.",
    )

    model_config = SettingsConfigDict(**_model_cfg)


settings = Settings()
