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
    GEMINI_API_KEY: str = ""
    LLM_PROVIDER_PRIORITY: str = "claude,gemini,openai,perplexity,grok"
    # Per-tier model ids. The gateway routes each task_kind to a tier (cheap|standard|strong|research)
    # and picks the provider model by tier (see llm_gateway.TASK_TIER). All overridable via .env
    # without a rebuild — keep the tier→model mapping tunable in server data/.env.
    ANTHROPIC_MODEL: str = "claude-sonnet-5"  # standard tier (default for unmarked tasks)
    ANTHROPIC_MODEL_STRONG: str = "claude-opus-4-8"  # strong tier: outreach reasoning/draft + critic
    ANTHROPIC_MODEL_CHEAP: str = "claude-haiku-4-5"  # cheap-tier fallback when Gemini is unavailable
    OPENAI_MODEL: str = "gpt-4o"
    PERPLEXITY_MODEL: str = "sonar"
    XAI_MODEL: str = "grok-2-latest"
    # Gemini (cheap tier primary). Verify the exact id against GET /v1beta/models with the key before
    # deploy; a wrong id degrades gracefully (gateway falls through to the Haiku cheap fallback).
    GEMINI_MODEL: str = "gemini-flash-latest"
    # Kimi via Ollama Cloud, Anthropic-compatible endpoint (B-372). Same contract as Content
    # (AlexStaff/Content/.env.example) — one key shared across the vault, names must not diverge.
    OLLAMA_ANTHROPIC_BASE_URL: str = "https://ollama.com"
    OLLAMA_ANTHROPIC_TOKEN: str = ""
    KIMI_MODEL: str = "kimi-k2.7-code"

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

    # Outbound transport: "gmail" (Gmail API via OAuth, primary for AlexStaff) or "smtp"
    # (rotator over smtp_accounts + SystemSetting Yandex fallback). The other transport
    # remains a fallback in email_provider.
    EMAIL_PROVIDER: str = "gmail"
    # Outbound mail: when False, missing Gmail credentials raise instead of fake "mock" delivery (recommended).
    EMAIL_ALLOW_MOCK: bool = False
    # Optional override for Drafts «Send test copy». If empty, uses OAuth mailbox (users/me/profile).
    GMAIL_PREVIEW_RECIPIENT_EMAIL: str = ""
    # Background Gmail sync: poll threads + bounces (seconds). 0 = disabled (use POST /gmail-sync/*).
    GMAIL_SYNC_INTERVAL_SECONDS: int = 120

    # Send-queue worker: release approved drafts on cadence/caps (seconds). 0 = disabled (kill-switch;
    # manual POST /sending/drafts/{id}/send still works). Keep 0 until the queue is verified end-to-end.
    SEND_QUEUE_INTERVAL_SECONDS: int = 0
    # Email address verification before send. Provider plug-in (millionverifier | zerobounce); empty =
    # MX-only (syntax + domain MX lookup, no paid API). Key required only for the paid provider.
    EMAIL_VERIFIER_PROVIDER: str = ""
    EMAIL_VERIFIER_API_KEY: str = ""
    EMAIL_VERIFIER_HTTP_TIMEOUT_SEC: float = 20.0

    # collect_companies: drop LLM rows whose website does not respond (GET + stream prefix, concurrent).
    COLLECT_COMPANIES_HTTP_CHECK_ENABLED: bool = True
    COLLECT_COMPANIES_HTTP_TIMEOUT_SEC: float = 8.0
    COLLECT_COMPANIES_HTTP_MAX_WORKERS: int = 8

    # Apollo.io — company + people search (optional). When APOLLO_API_KEY is set, collect_companies
    # and find_contacts try Apollo first and fall through to the LLM/OSINT path if it returns nothing.
    # APOLLO_KEY in .env is accepted as the same key (older name).
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
        default="tavily,yandex",
        description="Comma-ordered web-search providers; first configured+answering wins. "
        "Tavily first for global/English campaigns; put yandex first for RU-focused runs.",
    )

    # Telegram comms layer — one bot + one supergroup with forum topics (notifications per project +
    # inbound bridge that drops thoughts/docs/voice into per-project inbox files). Long-polling only,
    # no inbound ports. See services/telegram_notify.py + services/telegram_poller.py.
    # Token accepts the older OUTREACH_TG_BOT_TOKEN name so the report bot keeps working during migration.
    TELEGRAM_BOT_TOKEN: str = Field(
        default="",
        validation_alias=AliasChoices("TELEGRAM_BOT_TOKEN", "OUTREACH_TG_BOT_TOKEN"),
        description="Telegram bot token from @BotFather (env may use TELEGRAM_BOT_TOKEN or OUTREACH_TG_BOT_TOKEN).",
    )
    # Supergroup (forum) id, negative -100…; notifications go to its topics, poller accepts its messages.
    TELEGRAM_GROUP_CHAT_ID: str = ""
    # Owner DM chat id — fallback target for notifications and always-allowed sender for the poller.
    TELEGRAM_OWNER_CHAT_ID: str = Field(
        default="90016189",
        validation_alias=AliasChoices("TELEGRAM_OWNER_CHAT_ID", "OUTREACH_TG_CHAT_ID"),
        description="Owner personal chat id (env may use TELEGRAM_OWNER_CHAT_ID or OUTREACH_TG_CHAT_ID).",
    )
    # project→message_thread_id map, e.g. "AI-Biz-OS:2,Content:5,ReSpam:8,Общее:1".
    TELEGRAM_TOPICS: str = ""
    # Inbound poller: long-poll getUpdates and file incoming messages. False = disabled (kill-switch;
    # notifications via telegram_notify still work). Keep off until the bot+group are wired.
    TELEGRAM_POLLER_ENABLED: bool = False
    # Long-poll timeout (seconds) handed to getUpdates; the HTTP read timeout is this + a margin.
    TELEGRAM_POLL_TIMEOUT_SEC: int = 25
    # Where the poller writes inbox files/attachments. Empty = <data dir>/telegram_inbox
    # (data dir = parent of AI_BIZ_OS_DOTENV if set, else backend/data).
    TELEGRAM_INBOX_DIR: str = ""
    # Transcribe inbound voice/audio to text via OpenAI Whisper (needs OPENAI_API_KEY). When it
    # succeeds, the transcript becomes the inbox file body and is echoed in the bot's ack.
    TELEGRAM_VOICE_TRANSCRIBE: bool = True
    VOICE_TRANSCRIBE_MODEL: str = "whisper-1"
    # Language hint for transcription (ISO-639-1). Empty = auto-detect.
    VOICE_TRANSCRIBE_LANGUAGE: str = "ru"
    # Periodic status.json for the read-only General-topic dialog agent (general_agent/, separate
    # container, no DB access). Written into telegram_inbox/ so it stays inside that read-only mount.
    # Read-only aggregation (same as GET /ops/summary) — safe to leave on by default. 0 = disabled.
    STATUS_SNAPSHOT_INTERVAL_SECONDS: int = 180

    # CAN-SPAM: physical postal address substituted into personas whose signature references it
    # (see app.services.persona_service.CAN_SPAM_ADDRESS_PLACEHOLDER, currently only "stepan"/US
    # track). Empty until Алексей supplies the real address — sending_gates blocks send for any
    # persona whose signature needs it while this stays empty (B-128 Phase 1c).
    CAN_SPAM_POSTAL_ADDRESS: str = ""

    model_config = SettingsConfigDict(**_model_cfg)


settings = Settings()
