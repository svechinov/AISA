import logging

from sqlalchemy import inspect, text

from app.db import Base, SessionLocal, engine

_logger = logging.getLogger(__name__)
from app.models.project import Project
from app.models.run import Run
from app.models.rule import Rule
from app.models.contact import Contact
from app.models.template import Template
from app.models.email_draft import EmailDraft
from app.models.email_event import EmailEvent  # noqa: F401 — register email_events with Base.metadata
from app.models.email_message import EmailMessage  # noqa: F401 — register email_messages
from app.models.gmail_processed_message import GmailProcessedMessage  # noqa: F401
from app.models.email_thread import EmailThread  # noqa: F401 — register email_threads
from app.models.reply_draft import ReplyDraft  # noqa: F401 — register reply_drafts
from app.models.research_task import ResearchTask  # noqa: F401 — register research_tasks with Base.metadata
from app.models.follow_up_task import FollowUpTask  # noqa: F401 — register follow_up_tasks
from app.models.reminder import Reminder  # noqa: F401 — register reminders
from app.models.asset import Asset  # noqa: F401 — register assets
from app.models.asset_packet import AssetPacket  # noqa: F401 — register asset_packets
from app.models.asset_packet_asset import AssetPacketAsset  # noqa: F401 — register asset_packet_assets
from app.models.email_draft import EmailDraft  # noqa: F401
from app.models.email_draft_asset import EmailDraftAsset  # noqa: F401
from app.models.reply_draft import ReplyDraft  # noqa: F401
from app.models.reply_draft_asset import ReplyDraftAsset  # noqa: F401
from app.models.email_attachment import EmailAttachment  # noqa: F401 — register email_attachments
from app.models.run_setup import RunSetup  # noqa: F401 — register run_setups
from app.models.run_company import RunCompany  # noqa: F401 — register run_companies
from app.models.run_event_chain_collapse import RunEventChainCollapse  # noqa: F401 — register table
from app.models.entity_json_kv import EntityJsonKV  # noqa: F401 — register entity_json_kv
from app.models.run_outreach_context import RunOutreachContext  # noqa: F401
from app.models.run_master_email_variant import RunMasterEmailVariant  # noqa: F401
from app.models.contact_personalization import ContactPersonalization, ContactPersonalizationFact  # noqa: F401
from app.models.template_variable import TemplateVariable  # noqa: F401
from app.models.training_program import TrainingProgram  # noqa: F401 — register training_programs
from app.models.company_evidence import CompanyEvidence  # noqa: F401 — register company_evidence
# Explicit imports so create_all covers these on a FRESH database: without them the tables
# are registered with Base.metadata only when service modules happen to be imported first
# (separate asyncio task at startup — no ordering guarantee; masked by existing DBs).
from app.models.system_setting import SystemSetting  # noqa: F401 — register system_settings
from app.models.smtp_account import SmtpAccount  # noqa: F401 — register smtp_accounts
from app.models.sending_policy import SendingPolicy  # noqa: F401 — register sending_policies
from app.models.send_queue import SendQueueItem  # noqa: F401 — register send_queue
from app.models.suppression_entry import SuppressionEntry  # noqa: F401 — register suppression_list
from app.models.excluded_company import ExcludedCompany  # noqa: F401 — register excluded_companies (B-264)
from app.models.draft_instruct_log import DraftInstructLog  # noqa: F401 — register draft_instruct_log (B-018)
from app.models.persona import Persona  # noqa: F401 — register personas (B-071)


def _ensure_contacts_gmail_history_columns() -> None:
    insp = inspect(engine)
    if "contacts" not in insp.get_table_names():
        return
    columns = {c["name"] for c in insp.get_columns("contacts")}
    with engine.begin() as conn:
        if "gmail_history_status" not in columns:
            conn.execute(text("ALTER TABLE contacts ADD COLUMN gmail_history_status VARCHAR(32)"))
        if "gmail_history_checked_at" not in columns:
            if engine.dialect.name == "sqlite":
                conn.execute(text("ALTER TABLE contacts ADD COLUMN gmail_history_checked_at DATETIME"))
            else:
                conn.execute(text("ALTER TABLE contacts ADD COLUMN gmail_history_checked_at TIMESTAMP"))
        if "gmail_inbox_imported_at" not in columns:
            if engine.dialect.name == "sqlite":
                conn.execute(text("ALTER TABLE contacts ADD COLUMN gmail_inbox_imported_at DATETIME"))
            else:
                conn.execute(text("ALTER TABLE contacts ADD COLUMN gmail_inbox_imported_at TIMESTAMP"))

def _ensure_contacts_leadgen_columns() -> None:
    insp = inspect(engine)
    if "contacts" not in insp.get_table_names():
        return
    columns = {c["name"] for c in insp.get_columns("contacts")}
    with engine.begin() as conn:
        if "ai_pipeline_status" not in columns:
            conn.execute(text("ALTER TABLE contacts ADD COLUMN ai_pipeline_status VARCHAR(50) NOT NULL DEFAULT 'new'"))
        if "deep_dossier" not in columns:
            conn.execute(text("ALTER TABLE contacts ADD COLUMN deep_dossier TEXT"))

def _ensure_contacts_email_health_columns() -> None:
    insp = inspect(engine)
    if "contacts" not in insp.get_table_names():
        return
    columns = {c["name"] for c in insp.get_columns("contacts")}
    with engine.begin() as conn:
        if "email_health" not in columns:
            conn.execute(
                text(
                    "ALTER TABLE contacts ADD COLUMN email_health "
                    "VARCHAR(50) NOT NULL DEFAULT 'unknown'",
                ),
            )
        if "last_contact_event_at" not in columns:
            if engine.dialect.name == "sqlite":
                conn.execute(text("ALTER TABLE contacts ADD COLUMN last_contact_event_at DATETIME"))
            else:
                conn.execute(
                    text("ALTER TABLE contacts ADD COLUMN last_contact_event_at TIMESTAMP"),
                )


def _ensure_contacts_email_verification_columns() -> None:
    insp = inspect(engine)
    if "contacts" not in insp.get_table_names():
        return
    columns = {c["name"] for c in insp.get_columns("contacts")}
    with engine.begin() as conn:
        if "email_verification_status" not in columns:
            conn.execute(
                text(
                    "ALTER TABLE contacts ADD COLUMN email_verification_status "
                    "VARCHAR(50) NOT NULL DEFAULT 'unknown'",
                ),
            )
        if "email_verified_at" not in columns:
            if engine.dialect.name == "sqlite":
                conn.execute(text("ALTER TABLE contacts ADD COLUMN email_verified_at DATETIME"))
            else:
                conn.execute(text("ALTER TABLE contacts ADD COLUMN email_verified_at TIMESTAMP"))
        if "email_verification_source" not in columns:
            conn.execute(text("ALTER TABLE contacts ADD COLUMN email_verification_source VARCHAR(50)"))


def _seed_default_sending_policy() -> None:
    """Insert the alex@ mailbox policy on a fresh DB (idempotent). Warm-up: 5/day → +5/week → cap 25.

    daily_cap is the *ceiling* the ramp grows into (effective_daily_cap = min(daily_cap, ramp_cap) in
    sending_gates.py) — it must be seeded at 25, not 5, or the ramp is dead code and sending never
    exceeds 5/day (backlog B-013 §3, was wrong before 2026-07-08).
    """
    from datetime import date

    from app.config import settings
    from app.models.sending_policy import SendingPolicy

    insp = inspect(engine)
    if "sending_policies" not in insp.get_table_names():
        return
    mailbox = (settings.GMAIL_SEND_AS_EMAIL or "alex@alexstaff.agency").strip().lower()
    db = SessionLocal()
    try:
        if db.query(SendingPolicy).filter(SendingPolicy.mailbox_email == mailbox).first():
            return
        db.add(
            SendingPolicy(
                mailbox_email=mailbox,
                daily_cap=25,
                hourly_cap=2,
                min_gap_minutes=45,
                gap_jitter_minutes=45,
                send_days_first_touch="tue,wed,thu",
                send_days_follow_up="mon,tue,wed,thu",
                window_start="09:00",
                window_end="12:30",
                timezone="Asia/Nicosia",
                warmup_ramp_json={
                    "start": 5,
                    "step_per_week": 5,
                    "cap": 25,
                    "started_on": date.today().isoformat(),
                },
                follow_up_after_business_days=4,
                max_touches=2,
                enabled=True,
            ),
        )
        db.commit()
        _logger.info("sending_policies: seeded default policy for %s", mailbox)
    except Exception:
        _logger.exception("seed default sending policy failed")
        db.rollback()
    finally:
        db.close()


def _fix_stale_warmup_daily_cap() -> None:
    """One-time repair for rows written before 2026-07-08 with the old (wrong) seed: daily_cap=5
    while warmup_ramp_json targets cap=25. Since effective_daily_cap = min(daily_cap, ramp_cap), that
    combination permanently clamps sending at 5/day — the ramp never had any effect. Only bumps rows
    that still hold that exact stale pair, so a deliberately-lowered cap is left alone."""
    from app.models.sending_policy import SendingPolicy

    insp = inspect(engine)
    if "sending_policies" not in insp.get_table_names():
        return
    db = SessionLocal()
    try:
        rows = db.query(SendingPolicy).filter(SendingPolicy.daily_cap == 5).all()
        fixed = 0
        for row in rows:
            ramp = row.warmup_ramp_json or {}
            if isinstance(ramp, dict) and int(ramp.get("cap", 0) or 0) == 25:
                row.daily_cap = 25
                db.add(row)
                fixed += 1
        if fixed:
            db.commit()
            _logger.info("sending_policies: fixed stale warm-up daily_cap on %d row(s)", fixed)
    except Exception:
        _logger.exception("fix stale warm-up daily_cap failed")
        db.rollback()
    finally:
        db.close()


def _reset_stale_running_after_restart() -> None:
    """Startup recovery: run_workflow (backend/app/services/orchestrator.py) executes synchronously
    inside POST /runs/{id}/start, so a process restart (deploy, OOM, proxy timeout) mid-run never
    reaches the except block that would call mark_step_failed/update_run_status(..., "failed") —
    the run/step is left at status='running' forever, since nothing else transitions it out. Fail
    anything still 'running' at startup. Never lets a bad row block app boot."""
    from app.repositories.run_repo import reset_stale_running_runs
    from app.repositories.step_repo import reset_stale_running_steps

    db = SessionLocal()
    try:
        n_steps = reset_stale_running_steps(db)
        n_runs = reset_stale_running_runs(db)
        if n_steps or n_runs:
            _logger.info(
                "startup recovery: reset stale running steps=%d runs=%d", n_steps, n_runs,
            )
    except Exception:
        _logger.exception("startup recovery for stale running steps/runs failed")
        db.rollback()
    finally:
        db.close()


def _ensure_email_drafts_feature1_columns() -> None:
    """reasoning_problem / reasoning_solution / matched_program_json (Feature 1 + 5-slot meta)."""
    insp = inspect(engine)
    if "email_drafts" not in insp.get_table_names():
        return
    columns = {c["name"] for c in insp.get_columns("email_drafts")}
    with engine.begin() as conn:
        if "reasoning_problem" not in columns:
            conn.execute(text("ALTER TABLE email_drafts ADD COLUMN reasoning_problem TEXT"))
        if "reasoning_solution" not in columns:
            conn.execute(text("ALTER TABLE email_drafts ADD COLUMN reasoning_solution TEXT"))
        if "matched_program_json" not in columns:
            conn.execute(text("ALTER TABLE email_drafts ADD COLUMN matched_program_json JSON"))


def _ensure_email_drafts_alex_verdict_columns() -> None:
    """Alex's verdict on a draft (B-077 etap 2: critic <-> Alex calibration)."""
    insp = inspect(engine)
    if "email_drafts" not in insp.get_table_names():
        return
    columns = {c["name"] for c in insp.get_columns("email_drafts")}
    with engine.begin() as conn:
        if "alex_verdict" not in columns:
            conn.execute(text("ALTER TABLE email_drafts ADD COLUMN alex_verdict VARCHAR(20)"))
        if "alex_verdict_why" not in columns:
            conn.execute(text("ALTER TABLE email_drafts ADD COLUMN alex_verdict_why TEXT"))
        if "alex_verdict_at" not in columns:
            if engine.dialect.name == "sqlite":
                conn.execute(text("ALTER TABLE email_drafts ADD COLUMN alex_verdict_at DATETIME"))
            else:
                conn.execute(text("ALTER TABLE email_drafts ADD COLUMN alex_verdict_at TIMESTAMP"))


def _ensure_email_drafts_critic_taste_columns() -> None:
    """LLM taste-rubric outcome, separated from mechanics (B-077 etap 2: calibration matrix)."""
    insp = inspect(engine)
    if "email_drafts" not in insp.get_table_names():
        return
    columns = {c["name"] for c in insp.get_columns("email_drafts")}
    with engine.begin() as conn:
        if "critic_taste_pass" not in columns:
            conn.execute(text("ALTER TABLE email_drafts ADD COLUMN critic_taste_pass BOOLEAN"))
        if "critic_relevance_score" not in columns:
            conn.execute(text("ALTER TABLE email_drafts ADD COLUMN critic_relevance_score INTEGER"))
        if "critic_specificity_score" not in columns:
            conn.execute(text("ALTER TABLE email_drafts ADD COLUMN critic_specificity_score INTEGER"))
        if "critic_non_spam_score" not in columns:
            conn.execute(text("ALTER TABLE email_drafts ADD COLUMN critic_non_spam_score INTEGER"))
        if "critic_cta_score" not in columns:
            conn.execute(text("ALTER TABLE email_drafts ADD COLUMN critic_cta_score INTEGER"))
        if "critic_clarity_score" not in columns:
            conn.execute(text("ALTER TABLE email_drafts ADD COLUMN critic_clarity_score INTEGER"))
        if "critic_hook_grounded" not in columns:
            conn.execute(text("ALTER TABLE email_drafts ADD COLUMN critic_hook_grounded BOOLEAN"))
        if "critic_canon_used" not in columns:
            conn.execute(text("ALTER TABLE email_drafts ADD COLUMN critic_canon_used TEXT"))
        if "critic_evidence_json" not in columns:
            conn.execute(text("ALTER TABLE email_drafts ADD COLUMN critic_evidence_json JSON"))


def _ensure_email_drafts_finale_variant_column() -> None:
    """B-147: which verbatim closing-paragraph variant (0-based index) this draft was generated
    with, for A/B/C rotation reply-rate analysis (Persona.finales_json segment -> list of options)."""
    insp = inspect(engine)
    if "email_drafts" not in insp.get_table_names():
        return
    columns = {c["name"] for c in insp.get_columns("email_drafts")}
    with engine.begin() as conn:
        if "finale_variant" not in columns:
            conn.execute(text("ALTER TABLE email_drafts ADD COLUMN finale_variant INTEGER"))


def _ensure_email_drafts_tracking_columns() -> None:
    insp = inspect(engine)
    if "email_drafts" not in insp.get_table_names():
        return
    columns = {c["name"] for c in insp.get_columns("email_drafts")}
    with engine.begin() as conn:
        if "tracking_status" not in columns:
            conn.execute(
                text(
                    "ALTER TABLE email_drafts ADD COLUMN tracking_status "
                    "VARCHAR(50) NOT NULL DEFAULT 'draft'",
                ),
            )
        if "provider_message_id" not in columns:
            conn.execute(
                text("ALTER TABLE email_drafts ADD COLUMN provider_message_id VARCHAR(255)"),
            )
        if "thread_id" not in columns:
            conn.execute(text("ALTER TABLE email_drafts ADD COLUMN thread_id VARCHAR(255)"))
        if "last_event_at" not in columns:
            if engine.dialect.name == "sqlite":
                conn.execute(text("ALTER TABLE email_drafts ADD COLUMN last_event_at DATETIME"))
            else:
                conn.execute(
                    text("ALTER TABLE email_drafts ADD COLUMN last_event_at TIMESTAMP"),
                )


def _ensure_email_drafts_error_message_column() -> None:
    insp = inspect(engine)
    if "email_drafts" not in insp.get_table_names():
        return
    columns = {c["name"] for c in insp.get_columns("email_drafts")}
    if "error_message" in columns:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE email_drafts ADD COLUMN error_message TEXT"))


def _ensure_projects_is_archived_column() -> None:
    """create_all() does not add new columns to existing tables — migrate here."""
    insp = inspect(engine)
    if "projects" not in insp.get_table_names():
        return
    columns = {c["name"] for c in insp.get_columns("projects")}
    if "is_archived" in columns:
        return
    dialect = engine.dialect.name
    with engine.begin() as conn:
        if dialect == "sqlite":
            conn.execute(
                text("ALTER TABLE projects ADD COLUMN is_archived BOOLEAN NOT NULL DEFAULT 0"),
            )
        else:
            conn.execute(
                text(
                    "ALTER TABLE projects ADD COLUMN is_archived BOOLEAN NOT NULL DEFAULT FALSE",
                ),
            )


def _ensure_runs_persona_id_column() -> None:
    """create_all() does not add new columns to existing tables — migrate here (B-071). Nullable,
    no NOT NULL: empty persona_id is the "alexey" default at the code level (persona_service.py),
    not a DB-level default."""
    insp = inspect(engine)
    if "runs" not in insp.get_table_names():
        return
    columns = {c["name"] for c in insp.get_columns("runs")}
    if "persona_id" in columns:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE runs ADD COLUMN persona_id INTEGER"))


def _ensure_assets_extended_columns() -> None:
    insp = inspect(engine)
    if "assets" not in insp.get_table_names():
        return
    columns = {c["name"] for c in insp.get_columns("assets")}
    with engine.begin() as conn:
        if "download_url" not in columns:
            conn.execute(text("ALTER TABLE assets ADD COLUMN download_url VARCHAR(2000)"))
        if "storage_key" not in columns:
            conn.execute(text("ALTER TABLE assets ADD COLUMN storage_key VARCHAR(1000)"))
        if "filename" not in columns:
            conn.execute(text("ALTER TABLE assets ADD COLUMN filename VARCHAR(500)"))
        if "mime_type" not in columns:
            conn.execute(text("ALTER TABLE assets ADD COLUMN mime_type VARCHAR(255)"))
        if "file_size_bytes" not in columns:
            if engine.dialect.name == "sqlite":
                conn.execute(text("ALTER TABLE assets ADD COLUMN file_size_bytes INTEGER"))
            else:
                conn.execute(text("ALTER TABLE assets ADD COLUMN file_size_bytes BIGINT"))


def _ensure_run_input_goal_column() -> None:
    """Canonical goal string extracted from input_json.goal (relational path)."""
    insp = inspect(engine)
    if "runs" not in insp.get_table_names():
        return
    columns = {c["name"] for c in insp.get_columns("runs")}
    if "input_goal" in columns:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE runs ADD COLUMN input_goal TEXT"))


def _run_domain_json_migration() -> None:
    import logging

    from app.migrate_domain_json import migrate_domain_json_to_relational

    log = logging.getLogger(__name__)
    db = SessionLocal()
    try:
        migrate_domain_json_to_relational(db)
    except Exception:
        log.exception("domain JSON migration failed")
        db.rollback()
    finally:
        db.close()


def _ensure_run_outreach_context_columns() -> None:
    insp = inspect(engine)
    if "runs" not in insp.get_table_names():
        return
    columns = {c["name"] for c in insp.get_columns("runs")}
    dialect = engine.dialect.name
    with engine.begin() as conn:
        if "context_json" not in columns:
            if dialect == "sqlite":
                conn.execute(
                    text("ALTER TABLE runs ADD COLUMN context_json TEXT NOT NULL DEFAULT '{}'"),
                )
            else:
                conn.execute(
                    text("ALTER TABLE runs ADD COLUMN context_json JSONB NOT NULL DEFAULT '{}'::jsonb"),
                )
        if "master_prompt" not in columns:
            conn.execute(text("ALTER TABLE runs ADD COLUMN master_prompt TEXT"))
        if "master_email_subject" not in columns:
            conn.execute(text("ALTER TABLE runs ADD COLUMN master_email_subject VARCHAR(500)"))
        if "master_email_body" not in columns:
            conn.execute(text("ALTER TABLE runs ADD COLUMN master_email_body TEXT"))
        if "master_email" not in columns:
            if dialect == "sqlite":
                conn.execute(text("ALTER TABLE runs ADD COLUMN master_email TEXT"))
            else:
                conn.execute(text("ALTER TABLE runs ADD COLUMN master_email JSONB"))


def _ensure_runs_metadata_columns() -> None:
    insp = inspect(engine)
    if "runs" not in insp.get_table_names():
        return
    columns = {c["name"] for c in insp.get_columns("runs")}
    dialect = engine.dialect.name
    with engine.begin() as conn:
        if "name" not in columns:
            conn.execute(text("ALTER TABLE runs ADD COLUMN name VARCHAR(255)"))
        if "notes" not in columns:
            conn.execute(text("ALTER TABLE runs ADD COLUMN notes TEXT"))
        if "segment" not in columns:
            conn.execute(text("ALTER TABLE runs ADD COLUMN segment VARCHAR(500)"))
        if "closed_at" not in columns:
            if dialect == "sqlite":
                conn.execute(text("ALTER TABLE runs ADD COLUMN closed_at DATETIME"))
            else:
                conn.execute(text("ALTER TABLE runs ADD COLUMN closed_at TIMESTAMP"))
        if "sender_signature_html" not in columns:
            conn.execute(text("ALTER TABLE runs ADD COLUMN sender_signature_html TEXT"))


def _ensure_drafts_attached_asset_ids_columns() -> None:
    insp = inspect(engine)
    dialect = engine.dialect.name
    for table in ("email_drafts", "reply_drafts"):
        if table not in insp.get_table_names():
            continue
        columns = {c["name"] for c in insp.get_columns(table)}
        if "attached_asset_ids" in columns:
            continue
        with engine.begin() as conn:
            if dialect == "sqlite":
                conn.execute(
                    text(
                        f"ALTER TABLE {table} ADD COLUMN attached_asset_ids "
                        "TEXT NOT NULL DEFAULT '[]'",
                    ),
                )
            else:
                conn.execute(
                    text(
                        f"ALTER TABLE {table} ADD COLUMN attached_asset_ids "
                        "JSONB NOT NULL DEFAULT '[]'::jsonb",
                    ),
                )


def _ensure_asset_packets_reply_draft_id_unique() -> None:
    """At most one packet per non-null reply_draft_id (SQL NULLs may repeat)."""
    insp = inspect(engine)
    if "asset_packets" not in insp.get_table_names():
        return
    for ix in insp.get_indexes("asset_packets"):
        cols = list(ix.get("column_names") or [])
        if ix.get("unique") and cols == ["reply_draft_id"]:
            return
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_asset_packets_reply_draft_id "
                "ON asset_packets (reply_draft_id)",
            ),
        )


def _ensure_email_messages_rfc_message_id_column() -> None:
    insp = inspect(engine)
    if "email_messages" not in insp.get_table_names():
        return
    columns = {c["name"] for c in insp.get_columns("email_messages")}
    if "rfc_message_id" in columns:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE email_messages ADD COLUMN rfc_message_id VARCHAR(500)"))
    with engine.begin() as conn:
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_email_messages_rfc_message_id ON email_messages (rfc_message_id)"),
        )


def _ensure_gmail_processed_messages_table() -> None:
    """Idempotency for bounce / Gmail notification processing."""
    insp = inspect(engine)
    if "gmail_processed_messages" in insp.get_table_names():
        return
    dialect = engine.dialect.name
    with engine.begin() as conn:
        if dialect == "sqlite":
            conn.execute(
                text(
                    """
                    CREATE TABLE gmail_processed_messages (
                        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                        provider_message_id VARCHAR(255) NOT NULL,
                        kind VARCHAR(32) NOT NULL,
                        created_at DATETIME NOT NULL,
                        CONSTRAINT uq_gmail_processed_provider_id UNIQUE (provider_message_id)
                    )
                    """
                ),
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_gmail_processed_kind "
                    "ON gmail_processed_messages (kind)",
                ),
            )
        else:
            conn.execute(
                text(
                    """
                    CREATE TABLE gmail_processed_messages (
                        id SERIAL PRIMARY KEY,
                        provider_message_id VARCHAR(255) NOT NULL UNIQUE,
                        kind VARCHAR(32) NOT NULL,
                        created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
                    )
                    """
                ),
            )
            conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_gmail_processed_kind ON gmail_processed_messages (kind)"),
            )


def _ensure_email_threads_classification_columns() -> None:
    insp = inspect(engine)
    if "email_threads" not in insp.get_table_names():
        return
    columns = {c["name"] for c in insp.get_columns("email_threads")}
    with engine.begin() as conn:
        if "classification" not in columns:
            conn.execute(text("ALTER TABLE email_threads ADD COLUMN classification VARCHAR(50)"))
        if "classification_confidence" not in columns:
            conn.execute(text("ALTER TABLE email_threads ADD COLUMN classification_confidence VARCHAR(20)"))
        if "classification_reason" not in columns:
            conn.execute(text("ALTER TABLE email_threads ADD COLUMN classification_reason VARCHAR(500)"))


def _ensure_suppression_list_expires_at_column() -> None:
    """B-138: not_interested suppression is a 6-month cooldown, not permanent — NULL stays forever
    (unsubscribe/dead_mailbox/bounced/manual keep their existing forever semantics)."""
    insp = inspect(engine)
    if "suppression_list" not in insp.get_table_names():
        return
    columns = {c["name"] for c in insp.get_columns("suppression_list")}
    with engine.begin() as conn:
        if "expires_at" not in columns:
            if engine.dialect.name == "sqlite":
                conn.execute(text("ALTER TABLE suppression_list ADD COLUMN expires_at DATETIME"))
            else:
                conn.execute(text("ALTER TABLE suppression_list ADD COLUMN expires_at TIMESTAMP"))


def _ensure_personalization_and_generation_meta_columns() -> None:
    """contacts.personalization_json, runs.email_style_mode, email_drafts.generation_meta_json."""
    insp = inspect(engine)
    dialect = engine.dialect.name

    if "contacts" in insp.get_table_names():
        columns = {c["name"] for c in insp.get_columns("contacts")}
        if "personalization_json" not in columns:
            with engine.begin() as conn:
                if dialect == "sqlite":
                    conn.execute(
                        text(
                            "ALTER TABLE contacts ADD COLUMN personalization_json "
                            "TEXT NOT NULL DEFAULT '{}'",
                        ),
                    )
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE contacts ADD COLUMN personalization_json "
                            "JSONB NOT NULL DEFAULT '{}'::jsonb",
                        ),
                    )

    if "runs" in insp.get_table_names():
        columns = {c["name"] for c in insp.get_columns("runs")}
        if "email_style_mode" not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE runs ADD COLUMN email_style_mode VARCHAR(48)"))

    if "email_drafts" in insp.get_table_names():
        columns = {c["name"] for c in insp.get_columns("email_drafts")}
        if "generation_meta_json" not in columns:
            with engine.begin() as conn:
                if dialect == "sqlite":
                    conn.execute(text("ALTER TABLE email_drafts ADD COLUMN generation_meta_json TEXT"))
                else:
                    conn.execute(text("ALTER TABLE email_drafts ADD COLUMN generation_meta_json JSONB"))


def _ensure_email_drafts_generation_meta_columns() -> None:
    """Typed columns for outreach generation metadata (Phase 1)."""
    insp = inspect(engine)
    if "email_drafts" not in insp.get_table_names():
        return
    dialect = engine.dialect.name
    columns = {c["name"] for c in insp.get_columns("email_drafts")}
    with engine.begin() as conn:
        if "prompt_setup_text_used" not in columns:
            conn.execute(text("ALTER TABLE email_drafts ADD COLUMN prompt_setup_text_used TEXT"))
        if "generation_style_mode" not in columns:
            conn.execute(text("ALTER TABLE email_drafts ADD COLUMN generation_style_mode VARCHAR(80)"))
        if "validation_score" not in columns:
            conn.execute(text("ALTER TABLE email_drafts ADD COLUMN validation_score REAL"))
        if "validation_issues_json" not in columns:
            if dialect == "sqlite":
                conn.execute(text("ALTER TABLE email_drafts ADD COLUMN validation_issues_json TEXT"))
            else:
                conn.execute(text("ALTER TABLE email_drafts ADD COLUMN validation_issues_json JSONB"))
        if "generation_is_valid" not in columns:
            if dialect == "sqlite":
                conn.execute(text("ALTER TABLE email_drafts ADD COLUMN generation_is_valid INTEGER"))
            else:
                conn.execute(text("ALTER TABLE email_drafts ADD COLUMN generation_is_valid BOOLEAN"))
        if "peer_similarity_max" not in columns:
            conn.execute(text("ALTER TABLE email_drafts ADD COLUMN peer_similarity_max REAL"))
        if "validation_retries" not in columns:
            conn.execute(text("ALTER TABLE email_drafts ADD COLUMN validation_retries INTEGER"))
        if "pipeline_source" not in columns:
            conn.execute(text("ALTER TABLE email_drafts ADD COLUMN pipeline_source VARCHAR(80)"))
        if "reasoning_hook" not in columns:
            conn.execute(text("ALTER TABLE email_drafts ADD COLUMN reasoning_hook TEXT"))
        if "reasoning_angle" not in columns:
            conn.execute(text("ALTER TABLE email_drafts ADD COLUMN reasoning_angle TEXT"))
        if "reasoning_cta_type" not in columns:
            conn.execute(text("ALTER TABLE email_drafts ADD COLUMN reasoning_cta_type TEXT"))
        if "reasoning_key_point" not in columns:
            conn.execute(text("ALTER TABLE email_drafts ADD COLUMN reasoning_key_point TEXT"))


def _backfill_email_drafts_generation_meta_columns_from_json() -> None:
    """Copy generation_meta_json into typed columns for existing rows."""
    import logging

    from app.utils.email_draft_generation_meta import apply_generation_meta_to_draft

    log = logging.getLogger(__name__)
    db = SessionLocal()
    try:
        touched = 0
        for d in db.query(EmailDraft).order_by(EmailDraft.id.asc()).all():
            meta = d.generation_meta_json
            if not isinstance(meta, dict) or not meta:
                continue
            if getattr(d, "pipeline_source", None) is not None:
                continue
            apply_generation_meta_to_draft(d, meta)
            db.add(d)
            touched += 1
        db.commit()
        if touched:
            log.info("email_drafts: backfilled generation meta columns rows=%s", touched)
    except Exception:
        log.exception("backfill email_drafts generation meta columns failed")
        db.rollback()
    finally:
        db.close()


def _ensure_email_events_payload_columns() -> None:
    """Typed columns for email_events payload (Phase 2); payload_json holds extras only."""
    insp = inspect(engine)
    if "email_events" not in insp.get_table_names():
        return
    dialect = engine.dialect.name
    columns = {c["name"] for c in insp.get_columns("email_events")}
    with engine.begin() as conn:
        if "payload_source" not in columns:
            conn.execute(text("ALTER TABLE email_events ADD COLUMN payload_source VARCHAR(80)"))
        if "gmail_message_id" not in columns:
            conn.execute(text("ALTER TABLE email_events ADD COLUMN gmail_message_id VARCHAR(255)"))
        if "email_thread_id" not in columns:
            conn.execute(text("ALTER TABLE email_events ADD COLUMN email_thread_id INTEGER"))
        if "reply_draft_id" not in columns:
            conn.execute(text("ALTER TABLE email_events ADD COLUMN reply_draft_id INTEGER"))
        if "notification_excerpt" not in columns:
            conn.execute(text("ALTER TABLE email_events ADD COLUMN notification_excerpt TEXT"))
        if "inbound_from_email" not in columns:
            conn.execute(text("ALTER TABLE email_events ADD COLUMN inbound_from_email VARCHAR(255)"))
        if "inbound_to_email" not in columns:
            conn.execute(text("ALTER TABLE email_events ADD COLUMN inbound_to_email VARCHAR(255)"))
        if "inbound_subject" not in columns:
            conn.execute(text("ALTER TABLE email_events ADD COLUMN inbound_subject VARCHAR(500)"))
        if "llm_delivery_issue" not in columns:
            conn.execute(text("ALTER TABLE email_events ADD COLUMN llm_delivery_issue VARCHAR(50)"))
        if "llm_reason" not in columns:
            conn.execute(text("ALTER TABLE email_events ADD COLUMN llm_reason TEXT"))
        if "send_provider" not in columns:
            conn.execute(text("ALTER TABLE email_events ADD COLUMN send_provider VARCHAR(32)"))
        if "send_provider_thread_id" not in columns:
            conn.execute(text("ALTER TABLE email_events ADD COLUMN send_provider_thread_id VARCHAR(255)"))
        if "send_rfc_message_id" not in columns:
            conn.execute(text("ALTER TABLE email_events ADD COLUMN send_rfc_message_id VARCHAR(500)"))
        if "send_to_email" not in columns:
            conn.execute(text("ALTER TABLE email_events ADD COLUMN send_to_email VARCHAR(255)"))
        if "send_subject" not in columns:
            conn.execute(text("ALTER TABLE email_events ADD COLUMN send_subject VARCHAR(500)"))
        if "send_from_email" not in columns:
            conn.execute(text("ALTER TABLE email_events ADD COLUMN send_from_email VARCHAR(255)"))
        if "send_attachment_count" not in columns:
            conn.execute(text("ALTER TABLE email_events ADD COLUMN send_attachment_count INTEGER"))
        if "reply_attachment_count" not in columns:
            conn.execute(text("ALTER TABLE email_events ADD COLUMN reply_attachment_count INTEGER"))
        if "reply_attached_asset_ids_json" not in columns:
            if dialect == "sqlite":
                conn.execute(text("ALTER TABLE email_events ADD COLUMN reply_attached_asset_ids_json TEXT"))
            else:
                conn.execute(text("ALTER TABLE email_events ADD COLUMN reply_attached_asset_ids_json JSONB"))


def _backfill_email_events_payload_columns_from_json() -> None:
    import logging

    from app.utils.email_event_payload import apply_split_payload_to_event, should_skip_payload_backfill

    log = logging.getLogger(__name__)
    db = SessionLocal()
    try:
        touched = 0
        for e in db.query(EmailEvent).order_by(EmailEvent.id.asc()).all():
            merged = dict(e.payload_json or {})
            if should_skip_payload_backfill(e, merged):
                continue
            apply_split_payload_to_event(e, merged, e.event_type)
            db.add(e)
            touched += 1
        db.commit()
        if touched:
            log.info("email_events: backfilled payload columns rows=%s", touched)
    except Exception:
        log.exception("backfill email_events payload columns failed")
        db.rollback()
    finally:
        db.close()


def _ensure_reminders_typed_columns() -> None:
    """Typed columns for reminders (Phase 3); source_json / output_json hold extras only."""
    insp = inspect(engine)
    if "reminders" not in insp.get_table_names():
        return
    columns = {c["name"] for c in insp.get_columns("reminders")}
    with engine.begin() as conn:
        if "source_kind" not in columns:
            conn.execute(text("ALTER TABLE reminders ADD COLUMN source_kind VARCHAR(50)"))
        if "task_type_snapshot" not in columns:
            conn.execute(text("ALTER TABLE reminders ADD COLUMN task_type_snapshot VARCHAR(80)"))
        if "output_triggered_by" not in columns:
            conn.execute(text("ALTER TABLE reminders ADD COLUMN output_triggered_by VARCHAR(80)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_reminders_source_kind ON reminders (source_kind)"))


def _normalize_reminders_typed_columns() -> None:
    import logging

    from app.utils.reminder_payload import normalize_reminder_typed_columns

    log = logging.getLogger(__name__)
    db = SessionLocal()
    try:
        touched = 0
        for r in db.query(Reminder).order_by(Reminder.id.asc()).all():
            if normalize_reminder_typed_columns(r):
                db.add(r)
                touched += 1
        db.commit()
        if touched:
            log.info("reminders: normalized typed columns rows=%s", touched)
    except Exception:
        log.exception("normalize reminders typed columns failed")
        db.rollback()
    finally:
        db.close()


def _strip_email_drafts_generation_meta_json_blob() -> None:
    """Clear legacy generation_meta_json where typed columns are authoritative."""
    import logging

    from sqlalchemy.orm.attributes import flag_modified

    log = logging.getLogger(__name__)
    db = SessionLocal()
    try:
        n = 0
        for d in db.query(EmailDraft).filter(EmailDraft.pipeline_source.isnot(None)).all():
            if d.generation_meta_json is None:
                continue
            d.generation_meta_json = None
            flag_modified(d, "generation_meta_json")
            db.add(d)
            n += 1
        if n:
            db.commit()
            log.info("email_drafts: cleared generation_meta_json blob rows=%s", n)
        else:
            db.commit()
    except Exception:
        log.exception("strip email_drafts generation_meta_json failed")
        db.rollback()
    finally:
        db.close()


def _ensure_run_scoped_performance_indexes() -> None:
    """Composite indexes for frequent run-scoped filters (workspace lite, display counts, list runs).

    Single-column FK indexes from models help point lookups; these cover multi-column predicates
    from run_display_service, step_repo, contact/draft repos, and list_runs_by_project ordering.
    """
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    specs: list[tuple[str, str, str]] = [
        ("email_drafts", "ix_email_drafts_run_status_sent_at", "(run_id, status, sent_at)"),
        ("email_drafts", "ix_email_drafts_run_review_status", "(run_id, review_status)"),
        ("reply_drafts", "ix_reply_drafts_run_status_sent_at", "(run_id, status, sent_at)"),
        ("email_events", "ix_email_events_run_event_type", "(run_id, event_type)"),
        ("email_threads", "ix_email_threads_run_classification", "(run_id, classification)"),
        ("steps", "ix_steps_run_step_name", "(run_id, step_name)"),
        ("contacts", "ix_contacts_run_review_status", "(run_id, review_status)"),
        ("contacts", "ix_contacts_run_status", "(run_id, status)"),
        ("runs", "ix_runs_project_id_id", "(project_id, id)"),
    ]
    with engine.begin() as conn:
        for table, ix_name, columns in specs:
            if table not in tables:
                continue
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS {ix_name} ON {table} {columns}"))


def _ensure_run_setups_icp_columns() -> None:
    """ICP filter columns (Phase 6): icp_min_employees / icp_max_employees / icp_criteria_json."""
    insp = inspect(engine)
    if "run_setups" not in insp.get_table_names():
        return
    columns = {c["name"] for c in insp.get_columns("run_setups")}
    with engine.begin() as conn:
        if "icp_min_employees" not in columns:
            conn.execute(text("ALTER TABLE run_setups ADD COLUMN icp_min_employees INTEGER"))
        if "icp_max_employees" not in columns:
            conn.execute(text("ALTER TABLE run_setups ADD COLUMN icp_max_employees INTEGER"))
        if "icp_criteria_json" not in columns:
            conn.execute(text("ALTER TABLE run_setups ADD COLUMN icp_criteria_json JSON"))


def _ensure_personas_no_signal_template_column() -> None:
    """Fork-transition Phase 1, Task 5: personas.no_signal_template_enabled. NULL on every
    pre-existing row (AlexStaff's alexey/stepan/anastasia) resolves to True in application code —
    identical to today's forced no_vacancy behavior."""
    insp = inspect(engine)
    if "personas" not in insp.get_table_names():
        return
    columns = {c["name"] for c in insp.get_columns("personas")}
    if "no_signal_template_enabled" in columns:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE personas ADD COLUMN no_signal_template_enabled BOOLEAN"))


def _ensure_send_queue_reschedule_reason_column() -> None:
    """Why the last transient reschedule pushed this item to a new slot (B-026)."""
    insp = inspect(engine)
    if "send_queue" not in insp.get_table_names():
        return
    columns = {c["name"] for c in insp.get_columns("send_queue")}
    if "last_reschedule_reason" in columns:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE send_queue ADD COLUMN last_reschedule_reason VARCHAR(255)"))


def _ensure_run_setups_critic_canon_column() -> None:
    """Canon of judgement (B-077 etap 2): critic_canon_text, editable without a deploy."""
    insp = inspect(engine)
    if "run_setups" not in insp.get_table_names():
        return
    columns = {c["name"] for c in insp.get_columns("run_setups")}
    if "critic_canon_text" in columns:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE run_setups ADD COLUMN critic_canon_text TEXT"))


def _ensure_run_setups_fit_exclusion_rules_column() -> None:
    """Fork-transition Phase 1, Task 6: per-run override of the AI-fit judge's competitor rule."""
    insp = inspect(engine)
    if "run_setups" not in insp.get_table_names():
        return
    columns = {c["name"] for c in insp.get_columns("run_setups")}
    if "fit_exclusion_rules_text" in columns:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE run_setups ADD COLUMN fit_exclusion_rules_text TEXT"))


def _migrate_run_setups_from_legacy() -> None:
    """Merge prompt/signature into run_setups only; strip context_json.prompt_setup_text and runs.sender_signature_html."""
    import logging

    from app.models.run import Run
    from app.models.run_setup import RunSetup

    log = logging.getLogger(__name__)
    db = SessionLocal()
    try:
        insp = inspect(engine)
        if "run_setups" not in insp.get_table_names():
            return
        runs = db.query(Run).order_by(Run.id.asc()).all()
        touched = 0
        for run in runs:
            ctx = dict(run.context_json or {})
            prompt_from_json = None
            if "prompt_setup_text" in ctx:
                raw = ctx.pop("prompt_setup_text")
                if isinstance(raw, str) and raw.strip():
                    prompt_from_json = raw.strip()
            sig_from_col = None
            if run.sender_signature_html is not None:
                s = (run.sender_signature_html or "").strip()
                run.sender_signature_html = None
                if s:
                    sig_from_col = s
            run.context_json = ctx
            db.add(run)
            if not prompt_from_json and not sig_from_col:
                continue
            row = db.query(RunSetup).filter(RunSetup.run_id == run.id).first()
            if row is None:
                db.add(
                    RunSetup(
                        run_id=run.id,
                        prompt_setup_text=prompt_from_json,
                        sender_signature_html=sig_from_col,
                    ),
                )
                touched += 1
            else:
                if prompt_from_json and not (row.prompt_setup_text or "").strip():
                    row.prompt_setup_text = prompt_from_json
                    touched += 1
                if sig_from_col and not (row.sender_signature_html or "").strip():
                    row.sender_signature_html = sig_from_col
                    touched += 1
        db.commit()
        if touched:
            log.info("run_setups: merged legacy prompt/signature touches=%s", touched)
    except Exception:
        log.exception("run_setups legacy migration failed")
        db.rollback()
    finally:
        db.close()


def _backfill_draft_attached_assets_from_json() -> None:
    """Move email_drafts.attached_asset_ids / reply_drafts.attached_asset_ids into junction tables."""
    import logging

    from app.repositories.draft_attachment_repo import (
        replace_email_draft_assets,
        replace_reply_draft_assets,
    )
    from app.utils.attached_asset_ids import normalize_attached_asset_ids

    log = logging.getLogger(__name__)
    db = SessionLocal()
    try:
        for d in db.query(EmailDraft).order_by(EmailDraft.id.asc()).all():
            raw = normalize_attached_asset_ids(d.attached_asset_ids)
            if not raw:
                continue
            replace_email_draft_assets(db, d.id, raw)
            d.attached_asset_ids = []
        for r in db.query(ReplyDraft).order_by(ReplyDraft.id.asc()).all():
            raw = normalize_attached_asset_ids(r.attached_asset_ids)
            if not raw:
                continue
            replace_reply_draft_assets(db, r.id, raw)
            r.attached_asset_ids = []
        db.commit()
    except Exception:
        log.exception("draft_attached_assets backfill failed")
        db.rollback()
    finally:
        db.close()


def _strip_assets_key_from_asset_packet_json() -> None:
    """Remove legacy assets blob from packet_json after asset_packet_assets backfill."""
    import logging

    from sqlalchemy.orm.attributes import flag_modified

    from app.models.asset_packet import AssetPacket

    log = logging.getLogger(__name__)
    db = SessionLocal()
    try:
        n = 0
        for p in db.query(AssetPacket).all():
            pj = dict(p.packet_json or {})
            if "assets" not in pj:
                continue
            pj.pop("assets", None)
            p.packet_json = pj
            flag_modified(p, "packet_json")
            n += 1
        if n:
            db.commit()
            log.info("asset_packets: stripped assets key from packet_json on %s row(s)", n)
    except Exception:
        log.exception("strip packet_json.assets failed")
        db.rollback()
    finally:
        db.close()


def _backfill_asset_packet_assets_from_json() -> None:
    """Move packet membership from packet_json.assets only into asset_packet_assets (idempotent)."""
    import logging

    from app.models.asset_packet import AssetPacket
    from app.repositories.asset_packet_asset_repo import (
        count_rows_for_packet,
        replace_asset_packet_asset_rows,
    )

    log = logging.getLogger(__name__)
    db = SessionLocal()
    try:
        for p in db.query(AssetPacket).order_by(AssetPacket.id.asc()).all():
            if count_rows_for_packet(db, p.id) > 0:
                continue
            assets = (p.packet_json or {}).get("assets") or []
            if not isinstance(assets, list) or not assets:
                continue
            replace_asset_packet_asset_rows(db, p.id, assets)
        db.commit()
    except Exception:
        log.exception("asset_packet_assets backfill failed")
        db.rollback()
    finally:
        db.close()


def _migrate_steps_trim_contacts_json_blob() -> None:
    """Replace large find_contacts/validate_contacts output_json blobs with counts (canonical: contacts table)."""
    import logging

    from app.models.step import Step

    log = logging.getLogger(__name__)
    db = SessionLocal()
    try:
        for st in (
            db.query(Step)
            .filter(Step.step_name.in_(["find_contacts", "validate_contacts"]))
            .all()
        ):
            oj = st.output_json if isinstance(st.output_json, dict) else {}
            if not oj:
                continue
            changed = False
            if st.step_name == "find_contacts" and "contacts" in oj:
                raw = oj.get("contacts")
                n = len(raw) if isinstance(raw, list) else 0
                new_oj = {k: v for k, v in oj.items() if k != "contacts"}
                new_oj["contacts_count"] = n
                st.output_json = new_oj
                changed = True
            elif st.step_name == "validate_contacts" and (
                "valid_contacts" in oj or "invalid_contacts" in oj
            ):
                vc = oj.get("valid_contacts")
                ic = oj.get("invalid_contacts")
                new_oj = {
                    k: v for k, v in oj.items() if k not in ("valid_contacts", "invalid_contacts")
                }
                new_oj["valid_count"] = len(vc) if isinstance(vc, list) else 0
                new_oj["invalid_count"] = len(ic) if isinstance(ic, list) else 0
                st.output_json = new_oj
                changed = True
            if changed:
                db.add(st)
        db.commit()
    except Exception:
        log.exception("migrating steps: trim contacts JSON blob failed")
        db.rollback()
    finally:
        db.close()


def _backfill_run_event_chain_from_context_json() -> None:
    """Move legacy context_json._human_ui.event_chain_collapsed into run_event_chain_collapse."""
    import logging

    from app.models.run import Run
    from app.repositories.run_human_ui_repo import (
        delete_human_ui_from_context_json,
        merge_event_chain_collapsed,
    )

    log = logging.getLogger(__name__)
    db = SessionLocal()
    try:
        for run in db.query(Run).all():
            ctx = dict(run.context_json or {})
            ui = ctx.get("_human_ui") or {}
            chain = ui.get("event_chain_collapsed") if isinstance(ui, dict) else None
            if not isinstance(chain, dict) or not chain:
                continue
            merge_event_chain_collapsed(
                db,
                run.id,
                event_chain_collapsed={str(k): bool(v) for k, v in chain.items()},
            )
            run.context_json = delete_human_ui_from_context_json(ctx)
            db.add(run)
        db.commit()
    except Exception:
        log.exception("backfill run_event_chain_collapse from context_json failed")
        db.rollback()
    finally:
        db.close()


def _backfill_personalization_json() -> None:
    """Existing rows after ADD COLUMN get default {}; fill rule-based personalization on startup."""
    import logging

    from app.services.personalization_service import backfill_empty_personalization_json

    log = logging.getLogger(__name__)
    db = SessionLocal()
    try:
        backfill_empty_personalization_json(db)
    except Exception:
        log.exception("personalization_json backfill failed")
    finally:
        db.close()


def _strip_template_variables_json_blob_columns() -> None:
    """Clear templates.variables_json when template_variables rows exist (canonical store)."""
    import logging

    from sqlalchemy.orm.attributes import flag_modified

    log = logging.getLogger(__name__)
    db = SessionLocal()
    try:
        n = 0
        for t in db.query(Template).order_by(Template.id.asc()).all():
            if not dict(t.variables_json or {}):
                continue
            if not db.query(TemplateVariable).filter(TemplateVariable.template_id == t.id).first():
                continue
            t.variables_json = {}
            flag_modified(t, "variables_json")
            db.add(t)
            n += 1
        if n:
            db.commit()
            log.info("templates: cleared legacy variables_json rows=%s", n)
        else:
            db.commit()
    except Exception:
        log.exception("strip templates variables_json failed")
        db.rollback()
    finally:
        db.close()


def _strip_json_blob_when_kv_populated(scope: str, model_cls, blob_attr: str, log_line: str) -> None:
    """Clear a JSON blob column when entity_json_kv already holds data for that entity (KV is canonical)."""
    import logging

    from sqlalchemy.orm.attributes import flag_modified

    from app.utils.entity_kv_storage import get_kv_dict

    log = logging.getLogger(__name__)
    db = SessionLocal()
    try:
        n = 0
        for row in db.query(model_cls).order_by(model_cls.id.asc()).all():
            if not get_kv_dict(db, scope, row.id):
                continue
            if not dict(getattr(row, blob_attr) or {}):
                continue
            setattr(row, blob_attr, {})
            flag_modified(row, blob_attr)
            db.add(row)
            n += 1
        if n:
            db.commit()
            log.info(log_line, n)
        else:
            db.commit()
    except Exception:
        log.exception("strip %s failed", blob_attr)
        db.rollback()
    finally:
        db.close()


def _strip_asset_packet_packet_json_after_kv() -> None:
    """Clear packet_json when entity_json_kv holds metadata (after packet_json.assets backfill)."""
    from app.constants.entity_kv_scope import SCOPE_ASSET_PACKET

    _strip_json_blob_when_kv_populated(
        SCOPE_ASSET_PACKET,
        AssetPacket,
        "packet_json",
        "asset_packets: cleared legacy packet_json rows=%s (KV canonical)",
    )


def _strip_asset_metadata_json_blob_if_kv() -> None:
    """Clear assets.metadata_json when entity_json_kv scope asset_metadata is populated."""
    from app.constants.entity_kv_scope import SCOPE_ASSET_METADATA

    _strip_json_blob_when_kv_populated(
        SCOPE_ASSET_METADATA,
        Asset,
        "metadata_json",
        "assets: cleared legacy metadata_json rows=%s (KV canonical)",
    )


def _ensure_run_company_contact_status_column() -> None:
    """Add relational ``run_companies.contact_status`` if missing (must run before domain JSON migration)."""
    insp = inspect(engine)
    if "run_companies" not in insp.get_table_names():
        return
    columns = {c["name"] for c in insp.get_columns("run_companies")}
    if "contact_status" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE run_companies ADD COLUMN contact_status VARCHAR(32)"))


def _ensure_run_company_ai_fit_columns() -> None:
    """Add LLM campaign-fit columns on ``run_companies`` if missing."""
    insp = inspect(engine)
    if "run_companies" not in insp.get_table_names():
        return
    columns = {c["name"] for c in insp.get_columns("run_companies")}
    with engine.begin() as conn:
        if "ai_fit_status" not in columns:
            conn.execute(text("ALTER TABLE run_companies ADD COLUMN ai_fit_status VARCHAR(16)"))
        if "ai_fit_reason" not in columns:
            conn.execute(text("ALTER TABLE run_companies ADD COLUMN ai_fit_reason TEXT"))
        if "ai_fit_checked_at" not in columns:
            conn.execute(text("ALTER TABLE run_companies ADD COLUMN ai_fit_checked_at TIMESTAMP"))


def _backfill_run_company_contact_status_from_legacy_storage() -> None:
    """Fill NULL ``contact_status`` from extra_json or entity_kv — never clears other fields."""
    from app.constants.entity_kv_scope import SCOPE_RUN_COMPANY_EXTRA
    from app.constants.run_company_contact_status import PERSISTED_CONTACT_STATUSES
    from app.utils.entity_kv_storage import get_kv_maps_for_entities

    insp = inspect(engine)
    if "run_companies" not in insp.get_table_names():
        return
    columns = {c["name"] for c in insp.get_columns("run_companies")}
    if "contact_status" not in columns:
        return
    db = SessionLocal()
    try:
        pending = (
            db.query(RunCompany)
            .filter(RunCompany.contact_status.is_(None))
            .order_by(RunCompany.id.asc())
            .all()
        )
        if not pending:
            return
        ids = [r.id for r in pending]
        kv_by_id = get_kv_maps_for_entities(db, SCOPE_RUN_COMPANY_EXTRA, ids)
        touched = 0
        for r in pending:
            cs = None
            ej = dict(r.extra_json or {})
            v = ej.get("contact_status")
            if isinstance(v, str) and v in PERSISTED_CONTACT_STATUSES:
                cs = v
            if cs is None:
                kv = kv_by_id.get(r.id) or {}
                v2 = kv.get("contact_status")
                if isinstance(v2, str) and v2 in PERSISTED_CONTACT_STATUSES:
                    cs = v2
            if cs is not None:
                r.contact_status = cs
                db.add(r)
                touched += 1
        if touched:
            db.commit()
    except Exception:
        _logger.exception("ensure_schema: run_companies.contact_status backfill failed")
        db.rollback()
    finally:
        db.close()


def ensure_schema() -> None:
    _logger.info("ensure_schema: start")
    Base.metadata.create_all(bind=engine)
    _ensure_runs_metadata_columns()
    _ensure_run_outreach_context_columns()
    _ensure_run_input_goal_column()
    _migrate_run_setups_from_legacy()
    _ensure_run_setups_icp_columns()
    _ensure_run_setups_critic_canon_column()
    _ensure_run_setups_fit_exclusion_rules_column()
    _ensure_personas_no_signal_template_column()
    _ensure_send_queue_reschedule_reason_column()
    _ensure_email_drafts_error_message_column()
    _ensure_email_drafts_tracking_columns()
    _ensure_email_drafts_finale_variant_column()
    _ensure_email_drafts_feature1_columns()
    _ensure_email_drafts_alex_verdict_columns()
    _ensure_email_drafts_critic_taste_columns()
    _ensure_contacts_email_health_columns()
    _ensure_contacts_email_verification_columns()
    _ensure_contacts_gmail_history_columns()
    _ensure_contacts_leadgen_columns()
    _ensure_projects_is_archived_column()
    _ensure_runs_persona_id_column()
    _ensure_email_threads_classification_columns()
    _ensure_email_messages_rfc_message_id_column()
    _ensure_gmail_processed_messages_table()
    _ensure_assets_extended_columns()
    _ensure_drafts_attached_asset_ids_columns()
    _ensure_asset_packets_reply_draft_id_unique()
    _ensure_personalization_and_generation_meta_columns()
    _ensure_email_drafts_generation_meta_columns()
    _backfill_email_drafts_generation_meta_columns_from_json()
    _ensure_email_events_payload_columns()
    _backfill_email_events_payload_columns_from_json()
    _ensure_reminders_typed_columns()
    _normalize_reminders_typed_columns()
    # Before clearing runs.context_json into KV: move event_chain into relational tables.
    _backfill_run_event_chain_from_context_json()
    _ensure_run_company_contact_status_column()
    _ensure_run_company_ai_fit_columns()
    _run_domain_json_migration()
    _backfill_run_company_contact_status_from_legacy_storage()
    _strip_template_variables_json_blob_columns()
    _strip_email_drafts_generation_meta_json_blob()
    _backfill_asset_packet_assets_from_json()
    _strip_assets_key_from_asset_packet_json()
    _strip_asset_packet_packet_json_after_kv()
    _strip_asset_metadata_json_blob_if_kv()
    _backfill_draft_attached_assets_from_json()
    _backfill_personalization_json()
    _migrate_steps_trim_contacts_json_blob()
    _ensure_run_scoped_performance_indexes()
    _ensure_suppression_list_expires_at_column()
    _seed_default_sending_policy()
    _fix_stale_warmup_daily_cap()
    _reset_stale_running_after_restart()
    _logger.info("ensure_schema: done")


def init_db():
    ensure_schema()


if __name__ == "__main__":
    init_db()
