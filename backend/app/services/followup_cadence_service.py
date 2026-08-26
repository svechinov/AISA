"""Follow-up cadence: after N business days of silence, generate a second-touch draft for review.

Runs once per day (guarded via a system setting). It never sends: every generated follow-up is
``review_status='pending'`` so Alexey reviews it (RU+EN) exactly like a first touch; on approval it
enters the send queue as touch 2. Any reply/bounce/dead/suppression stops the cadence — those set the
original draft's tracking_status away from 'sent', so it simply drops out of the candidate query.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.contact import Contact
from app.models.email_draft import EmailDraft
from app.models.system_setting import SystemSetting
from app.repositories.email_draft_repo import create_email_draft
from app.repositories.sending_policy_repo import get_default_policy
from app.services.contactability import is_contactable
from app.utils.business_days import subtract_business_days

_log = logging.getLogger(__name__)

_LAST_RUN_KEY = "followup_cadence_last_run_date"


def find_followup_candidates(db: Session, policy, now_utc: datetime) -> list[dict]:
    """Contacts whose most recent touch went silent past the cadence window and can take another touch.

    Grouped queries (no per-contact N+1): candidate contact ids → all their sent touches in one query,
    then contacts / pending drafts / suppression each in one IN-query, filtered in memory.
    """
    cutoff = subtract_business_days(now_utc, int(policy.follow_up_after_business_days))
    max_touches = int(policy.max_touches)

    # Candidate contacts: those with a sent, un-replied touch old enough to follow up.
    candidate_ids = {
        cid
        for (cid,) in db.query(EmailDraft.contact_id)
        .filter(
            EmailDraft.status == "sent",
            EmailDraft.tracking_status == "sent",
            EmailDraft.sent_at.isnot(None),
            EmailDraft.sent_at <= cutoff,
        )
        .distinct()
        if cid is not None
    }
    if not candidate_ids:
        return []

    # All sent touches for those contacts, grouped and ordered by sent_at.
    touches_by_contact: dict[int, list[EmailDraft]] = defaultdict(list)
    for d in (
        db.query(EmailDraft)
        .filter(EmailDraft.contact_id.in_(candidate_ids), EmailDraft.status == "sent")
        .order_by(EmailDraft.sent_at.asc())
        .all()
    ):
        touches_by_contact[d.contact_id].append(d)

    # Contacts with a not-yet-sent draft (queued first touch or an already-generated follow-up).
    contacts_with_pending = {
        cid
        for (cid,) in db.query(EmailDraft.contact_id)
        .filter(
            EmailDraft.contact_id.in_(candidate_ids),
            EmailDraft.status.in_(("draft", "sending", "failed")),
        )
        .distinct()
    }

    contacts_by_id = {
        c.id: c for c in db.query(Contact).filter(Contact.id.in_(candidate_ids)).all()
    }

    out: list[dict] = []
    for cid in candidate_ids:
        touches = touches_by_contact.get(cid, [])
        touch_count = len(touches)
        if touch_count == 0 or touch_count >= max_touches:
            continue
        latest = touches[-1]
        if latest.tracking_status != "sent" or latest.sent_at is None or latest.sent_at > cutoff:
            continue
        if cid in contacts_with_pending:
            continue
        contact = contacts_by_id.get(cid)
        if contact is None:
            continue
        # Same do-not-contact rule as the send gate and the manual send path (suppression list +
        # confirmed-dead) — was a locally re-implemented, out-of-sync copy (backlog B-013 §5).
        if not is_contactable(db, contact.email, contact).ok:
            continue
        out.append({"contact": contact, "original": latest, "next_touch": touch_count + 1})
    return out


def _build_followup_content(original: EmailDraft, contact, next_touch: int) -> tuple[str, str]:
    """Short follow-up referencing the first email. LLM when configured, template fallback otherwise."""
    name = (getattr(contact, "name", "") or "there").split(" ")[0]
    orig_subject = original.subject or "my note"
    template_subject = f"Re: {orig_subject}"
    template_body = (
        f"Hi {name},\n\n"
        f"Circling back on my earlier note about {orig_subject.lower()}. I know inboxes get busy — "
        f"if helping with these roles is worth a short look, I'm happy to send a couple of relevant "
        f"profiles or set up a quick call.\n\n"
        f"If the timing isn't right, just let me know and I'll leave it there."
    )

    try:
        from app.services.llm_gateway import generate_json, llm_configured

        if not llm_configured():
            return template_subject, template_body
        prompt = (
            "Write a SHORT, warm follow-up email (2nd touch) to a cold outreach that got no reply. "
            "Reference the first email without repeating it; one clear, low-friction CTA; give an easy "
            "opt-out. No pressure, no guilt. Return JSON {\"subject\": str, \"body\": str}. "
            f"Recipient first name: {name}. Company: {contact.company or 'their studio'}. "
            f"First email subject: {orig_subject!r}. First email body:\n{(original.body or '')[:1200]}"
        )
        data = generate_json(prompt, task_kind="followup_draft")
        subject = str(data.get("subject") or "").strip() or template_subject
        body = str(data.get("body") or "").strip() or template_body
        return subject, body
    except Exception:
        _log.exception("follow-up LLM generation failed; using template (contact=%s)", getattr(contact, "id", None))
        return template_subject, template_body


def generate_followup_draft(db: Session, contact, original: EmailDraft, next_touch: int) -> EmailDraft:
    subject, body = _build_followup_content(original, contact, next_touch)
    draft = create_email_draft(
        db=db,
        run_id=original.run_id,
        contact_id=contact.id,
        company=original.company or contact.company,
        to_email=original.to_email or contact.email,
        subject=subject,
        body=body,
        status="draft",
        review_status="pending",
        review_notes=f"Auto-generated follow-up (touch {next_touch}) — review before approving.",
    )
    _log.info("generated follow-up draft %s for contact %s (touch %s)", draft.id, contact.id, next_touch)
    return draft


def run_followup_cadence(db: Session, now_utc: datetime | None = None) -> dict:
    """Generate follow-up drafts for all eligible contacts. Returns a small summary."""
    now_utc = now_utc or datetime.utcnow()
    policy = get_default_policy(db)
    if policy is None:
        return {"generated": 0, "reason": "no policy"}
    candidates = find_followup_candidates(db, policy, now_utc)
    generated = 0
    for c in candidates:
        try:
            generate_followup_draft(db, c["contact"], c["original"], c["next_touch"])
            generated += 1
        except Exception:
            _log.exception("follow-up generation failed for contact %s", c["contact"].id)
    return {"generated": generated, "candidates": len(candidates)}


def maybe_run_daily_cadence(db: Session, now_utc: datetime | None = None) -> dict:
    """Run the cadence at most once per calendar day (UTC). Cheap no-op on repeat ticks."""
    now_utc = now_utc or datetime.utcnow()
    today = now_utc.date().isoformat()
    row = db.query(SystemSetting).filter(SystemSetting.key == _LAST_RUN_KEY).first()
    if row is not None and (row.value or "") == today:
        return {"ran": False}
    result = run_followup_cadence(db, now_utc)
    if row is None:
        db.add(SystemSetting(key=_LAST_RUN_KEY, value=today))
    else:
        row.value = today
        db.add(row)
    db.commit()
    return {"ran": True, **result}
