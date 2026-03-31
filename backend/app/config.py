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

    model_config = SettingsConfigDict(**_model_cfg)


settings = Settings()
