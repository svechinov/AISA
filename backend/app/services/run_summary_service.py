from sqlalchemy.orm import Session

from app.repositories.asset_packet_repo import list_asset_packets_by_run
from app.repositories.contact_repo import list_contacts_by_run
from app.repositories.email_draft_repo import list_email_drafts_by_run
from app.repositories.email_event_repo import list_email_events_by_run
from app.repositories.email_message_repo import list_email_messages_by_run
from app.repositories.email_thread_repo import list_email_threads_by_run
from app.repositories.follow_up_task_repo import list_follow_up_tasks_by_run
from app.repositories.reminder_repo import list_reminders_by_run
from app.repositories.reply_draft_repo import list_reply_drafts_by_run
from app.repositories.research_task_repo import list_research_tasks_by_run


def get_run_summary(db: Session, run_id: int) -> dict:
    contacts = list_contacts_by_run(db, run_id)
    drafts = list_email_drafts_by_run(db, run_id)
    events = list_email_events_by_run(db, run_id)
    tasks = list_research_tasks_by_run(db, run_id)

    def count_contacts(status=None, review_status=None):
        items = contacts
        if status is not None:
            items = [c for c in items if c.status == status]
        if review_status is not None:
            items = [c for c in items if c.review_status == review_status]
        return len(items)

    def count_drafts(status=None, review_status=None):
        items = drafts
        if status is not None:
            items = [d for d in items if d.status == status]
        if review_status is not None:
            items = [d for d in items if d.review_status == review_status]
        return len(items)

    def count_events(event_type: str):
        return len([e for e in events if e.event_type == event_type])

    def count_tasks(task_type=None, status=None):
        items = tasks
        if task_type is not None:
            items = [t for t in items if t.task_type == task_type]
        if status is not None:
            items = [t for t in items if t.status == status]
        return len(items)

    replacement_contact_ids = {
        c.id
        for c in contacts
        if (c.source_json or {}).get("source") == "replacement_search"
    }

    replacement_drafts = [d for d in drafts if d.contact_id in replacement_contact_ids]
    replacement_drafts_sent = [d for d in replacement_drafts if d.status == "sent"]

    threads = list_email_threads_by_run(db, run_id)
    messages = list_email_messages_by_run(db, run_id)

    inbound_messages = [m for m in messages if m.direction == "inbound"]
    outbound_messages = [m for m in messages if m.direction == "outbound"]
    replied_threads = [t for t in threads if t.status == "replied"]

    threads_interested = [t for t in threads if t.classification == "interested"]
    threads_not_interested = [t for t in threads if t.classification == "not_interested"]
    threads_need_info = [t for t in threads if t.classification == "need_more_info"]

    reply_drafts = list_reply_drafts_by_run(db, run_id)
    reply_drafts_generated = len(reply_drafts)
    reply_drafts_approved = len([d for d in reply_drafts if d.review_status == "approved"])
    reply_drafts_edited = len([d for d in reply_drafts if d.review_status == "edited"])
    reply_drafts_sent = len([d for d in reply_drafts if d.status == "sent"])

    follow_up_tasks = list_follow_up_tasks_by_run(db, run_id)

    follow_up_open = [t for t in follow_up_tasks if t.status == "open"]
    follow_up_in_progress = [t for t in follow_up_tasks if t.status == "in_progress"]
    follow_up_completed = [t for t in follow_up_tasks if t.status == "completed"]

    follow_up_interested = [t for t in follow_up_tasks if t.task_type == "reply_to_interested"]
    follow_up_need_info = [t for t in follow_up_tasks if t.task_type == "send_more_info"]
    follow_up_later = [t for t in follow_up_tasks if t.task_type == "follow_up_later"]
    follow_up_close = [t for t in follow_up_tasks if t.task_type == "close_thread"]

    reminders = list_reminders_by_run(db, run_id)

    reminders_scheduled = [r for r in reminders if r.status == "scheduled"]
    reminders_triggered = [r for r in reminders if r.status == "triggered"]
    reminders_completed = [r for r in reminders if r.status == "completed"]
    reminders_cancelled = [r for r in reminders if r.status == "cancelled"]
    reminders_snoozed = [r for r in reminders if r.status == "snoozed"]

    asset_packets = list_asset_packets_by_run(db, run_id)

    asset_packets_draft = [p for p in asset_packets if p.status == "draft"]
    asset_packets_approved = [p for p in asset_packets if p.status == "approved"]
    asset_packets_sent = [p for p in asset_packets if p.status == "sent"]

    return {
        "contacts_found": len(contacts),
        "valid_contacts": count_contacts(status="valid"),
        "invalid_contacts": count_contacts(status="invalid"),
        "approved_contacts": count_contacts(review_status="approved"),
        "edited_contacts": count_contacts(review_status="edited"),
        "rejected_contacts": count_contacts(review_status="rejected"),
        "pending_contact_reviews": count_contacts(review_status="pending"),
        "drafts_generated": len(drafts),
        "approved_drafts": count_drafts(review_status="approved"),
        "edited_drafts": count_drafts(review_status="edited"),
        "rejected_drafts": count_drafts(review_status="rejected"),
        "pending_draft_reviews": count_drafts(review_status="pending"),
        "drafts_sent": count_drafts(status="sent"),
        "drafts_failed": count_drafts(status="failed"),
        "events_queued": count_events("queued"),
        "events_sent": count_events("sent"),
        "events_failed": count_events("failed"),
        "events_replied": count_events("replied"),
        "events_bounced": count_events("bounced"),
        "events_dead_mailbox": count_events("dead_mailbox"),
        "research_tasks_open": count_tasks(status="open"),
        "replacement_email_tasks_open": count_tasks(
            task_type="find_replacement_email",
            status="open",
        ),
        "replacement_drafts_generated": len(replacement_drafts),
        "replacement_drafts_sent": len(replacement_drafts_sent),
        "threads_total": len(threads),
        "threads_replied": len(replied_threads),
        "messages_outbound": len(outbound_messages),
        "messages_inbound": len(inbound_messages),
        "threads_interested": len(threads_interested),
        "threads_not_interested": len(threads_not_interested),
        "threads_need_info": len(threads_need_info),
        "reply_drafts_generated": reply_drafts_generated,
        "reply_drafts_approved": reply_drafts_approved,
        "reply_drafts_edited": reply_drafts_edited,
        "reply_drafts_sent": reply_drafts_sent,
        "follow_up_tasks_total": len(follow_up_tasks),
        "follow_up_tasks_open": len(follow_up_open),
        "follow_up_tasks_in_progress": len(follow_up_in_progress),
        "follow_up_tasks_completed": len(follow_up_completed),
        "follow_up_tasks_interested": len(follow_up_interested),
        "follow_up_tasks_need_info": len(follow_up_need_info),
        "follow_up_tasks_later": len(follow_up_later),
        "follow_up_tasks_close": len(follow_up_close),
        "reminders_total": len(reminders),
        "reminders_scheduled": len(reminders_scheduled),
        "reminders_triggered": len(reminders_triggered),
        "reminders_completed": len(reminders_completed),
        "reminders_cancelled": len(reminders_cancelled),
        "reminders_snoozed": len(reminders_snoozed),
        "asset_packets_total": len(asset_packets),
        "asset_packets_draft": len(asset_packets_draft),
        "asset_packets_approved": len(asset_packets_approved),
        "asset_packets_sent": len(asset_packets_sent),
    }
