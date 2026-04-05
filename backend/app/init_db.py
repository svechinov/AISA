from sqlalchemy import inspect, text

from app.db import Base, SessionLocal, engine
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
                conn.execute(text("ALTER TABLE runs ADD COLUMN email_style_mode VARCHAR(32)"))

    if "email_drafts" in insp.get_table_names():
        columns = {c["name"] for c in insp.get_columns("email_drafts")}
        if "generation_meta_json" not in columns:
            with engine.begin() as conn:
                if dialect == "sqlite":
                    conn.execute(text("ALTER TABLE email_drafts ADD COLUMN generation_meta_json TEXT"))
                else:
                    conn.execute(text("ALTER TABLE email_drafts ADD COLUMN generation_meta_json JSONB"))


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


def ensure_schema() -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_runs_metadata_columns()
    _ensure_run_outreach_context_columns()
    _migrate_run_setups_from_legacy()
    _ensure_email_drafts_error_message_column()
    _ensure_email_drafts_tracking_columns()
    _ensure_contacts_email_health_columns()
    _ensure_contacts_gmail_history_columns()
    _ensure_projects_is_archived_column()
    _ensure_email_threads_classification_columns()
    _ensure_email_messages_rfc_message_id_column()
    _ensure_gmail_processed_messages_table()
    _ensure_assets_extended_columns()
    _ensure_drafts_attached_asset_ids_columns()
    _ensure_asset_packets_reply_draft_id_unique()
    _ensure_personalization_and_generation_meta_columns()
    _backfill_asset_packet_assets_from_json()
    _strip_assets_key_from_asset_packet_json()
    _backfill_draft_attached_assets_from_json()
    _backfill_personalization_json()
    _ensure_run_scoped_performance_indexes()


def init_db():
    ensure_schema()


if __name__ == "__main__":
    init_db()
