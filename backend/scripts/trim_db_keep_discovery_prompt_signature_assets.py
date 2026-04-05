#!/usr/bin/env python3
"""
Remove most run-related data; keep companies, contacts (review/health reset), Prompt setup,
Signature, assets, and asset packets.

Keeps:
  - Step rows collect_companies + find_contacts (companies live in run_companies; find output_json has contacts).
  - contacts (same rows; review + delivery fields reset)
  - runs — trimmed: prompt/signature preserved in ``run_setups`` (legacy context_json key + runs.sender_signature_html
    merged in); master email / master_prompt cleared; status set to needs_review if the run has contacts
  - assets, asset_packets (packet FKs to threads/contacts/reply_drafts nulled first)

Deletes:
  - email_events, email_messages, email_threads, email_drafts, reply_drafts
  - reminders, follow_up_tasks, research_tasks
  - steps other than collect_companies, find_contacts

Does not truncate: projects, rules, templates.

Run from backend/ (folder with app/ and requirements.txt):

    python3 scripts/trim_db_keep_discovery_prompt_signature_assets.py

Loads DATABASE_URL from backend/.env (and repo-root .env when present) via env_bootstrap.
Works without python-dotenv (minimal KEY=VAL parser); install python-dotenv for full .env features.
"""

from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from app.services.env_bootstrap import load_env_from_file

load_env_from_file()

try:
    from sqlalchemy import text

    import app.init_db  # noqa: F401 — register all models

    from app.db import SessionLocal
    from app.models.asset_packet import AssetPacket
    from app.models.contact import Contact
    from app.models.email_draft import EmailDraft
    from app.models.email_event import EmailEvent
    from app.models.email_message import EmailMessage
    from app.models.email_thread import EmailThread
    from app.models.follow_up_task import FollowUpTask
    from app.models.reminder import Reminder
    from app.models.reply_draft import ReplyDraft
    from app.models.research_task import ResearchTask
    from app.models.run import Run
    from app.models.run_setup import RunSetup
    from app.models.step import Step
except ModuleNotFoundError as e:
    print(f"{e}\nUse a venv and pip install -r requirements.txt", file=sys.stderr)
    raise SystemExit(1) from e

# Legacy context_json key (merged into run_setups during trim).
PROMPT_SETUP_TEXT_KEY = "prompt_setup_text"

KEEP_STEP_NAMES = frozenset({"collect_companies", "find_contacts"})


def trim_db() -> None:
    db = SessionLocal()
    try:
        # 1) Detach packets from entities we are about to delete
        db.query(AssetPacket).update(
            {AssetPacket.thread_id: None, AssetPacket.contact_id: None, AssetPacket.reply_draft_id: None},
            synchronize_session=False,
        )

        db.query(EmailEvent).delete(synchronize_session=False)
        db.query(EmailMessage).delete(synchronize_session=False)

        db.query(FollowUpTask).delete(synchronize_session=False)
        db.query(Reminder).delete(synchronize_session=False)
        db.query(ReplyDraft).delete(synchronize_session=False)

        db.query(EmailThread).delete(synchronize_session=False)

        db.query(ResearchTask).delete(synchronize_session=False)
        db.query(EmailDraft).delete(synchronize_session=False)

        db.query(Step).filter(~Step.step_name.in_(KEEP_STEP_NAMES)).delete(synchronize_session=False)

        db.query(Contact).update(
            {
                Contact.review_status: "pending",
                Contact.review_notes: None,
                Contact.reviewed_at: None,
                Contact.email_health: "unknown",
                Contact.last_contact_event_at: None,
            },
            synchronize_session=False,
        )

        for run in db.query(Run).all():
            cj = run.context_json if isinstance(run.context_json, dict) else {}
            legacy_prompt = cj.get(PROMPT_SETUP_TEXT_KEY)
            rs = db.query(RunSetup).filter(RunSetup.run_id == run.id).first()
            prompt = (rs.prompt_setup_text.strip() if rs and rs.prompt_setup_text else None) or (
                legacy_prompt.strip() if isinstance(legacy_prompt, str) and legacy_prompt.strip() else None
            )
            sig_raw = (rs.sender_signature_html if rs else None) or run.sender_signature_html
            sig = (sig_raw or "").strip() or None

            run.context_json = {}
            run.sender_signature_html = None

            run.master_prompt = None
            run.master_email = None
            run.master_email_subject = None
            run.master_email_body = None
            run.finished_at = None

            n_contacts = db.query(Contact).filter(Contact.run_id == run.id).count()
            run.status = "needs_review" if n_contacts else "pending"

            if prompt or sig:
                if rs is None:
                    rs = RunSetup(run_id=run.id)
                    db.add(rs)
                rs.prompt_setup_text = prompt
                rs.sender_signature_html = sig
            elif rs is not None:
                db.delete(rs)

            db.add(run)

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    # Optional: vacuum sqlite
    from app.db import engine

    if engine.dialect.name == "sqlite":
        with engine.begin() as conn:
            conn.execute(text("VACUUM"))


if __name__ == "__main__":
    trim_db()
    print(
        "Trim complete: kept collect/find steps, contacts (review reset), "
        "prompt_setup_text + signature per run, assets & packets. "
        "Removed drafts, threads, other steps, reminders/tasks/research.",
    )
