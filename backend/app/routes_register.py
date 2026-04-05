"""Register all API routers (sync import — must complete before any client hits /projects, /runs, …)."""

from __future__ import annotations

from fastapi import FastAPI


def import_api_routers():
    """Import all route modules; returns router instances in attach order."""
    from app.api.asset_packets import router as asset_packets_router
    from app.api.assets import router as assets_router
    from app.api.contact_analyzer import router as contact_analyzer_router
    from app.api.contacts import router as contacts_router
    from app.api.email_drafts import router as email_drafts_router
    from app.api.email_events import router as email_events_router
    from app.api.email_threads import router as email_threads_router
    from app.api.follow_up_tasks import router as follow_up_tasks_router
    from app.api.gmail_sync import router as gmail_sync_router
    from app.api.inbox import router as inbox_router
    from app.api.oauth_google import router as oauth_google_router
    from app.api.projects import router as projects_router
    from app.api.reminders import router as reminders_router
    from app.api.reply_drafts import router as reply_drafts_router
    from app.api.research_tasks import router as research_tasks_router
    from app.api.rules import router as rules_router
    from app.api.runs import router as runs_router
    from app.api.sending import router as sending_router
    from app.api.setup import router as setup_router
    from app.api.steps import router as steps_router
    from app.api.templates import router as templates_router
    from app.api.tracking import router as tracking_router

    return (
        setup_router,
        oauth_google_router,
        projects_router,
        assets_router,
        asset_packets_router,
        rules_router,
        templates_router,
        contacts_router,
        email_drafts_router,
        email_events_router,
        email_threads_router,
        follow_up_tasks_router,
        reminders_router,
        reply_drafts_router,
        sending_router,
        inbox_router,
        tracking_router,
        research_tasks_router,
        runs_router,
        contact_analyzer_router,
        gmail_sync_router,
        steps_router,
    )


def attach_api_routers(app: FastAPI, routers: tuple) -> None:
    for r in routers:
        app.include_router(r)
