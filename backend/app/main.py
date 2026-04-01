import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.gmail_sync import router as gmail_sync_router
from app.api.contact_analyzer import router as contact_analyzer_router
from app.api.contacts import router as contacts_router
from app.api.email_drafts import router as email_drafts_router
from app.api.email_events import router as email_events_router
from app.api.email_threads import router as email_threads_router
from app.api.follow_up_tasks import router as follow_up_tasks_router
from app.api.inbox import router as inbox_router
from app.api.asset_packets import router as asset_packets_router
from app.api.assets import router as assets_router
from app.api.projects import router as projects_router
from app.api.reminders import router as reminders_router
from app.api.reply_drafts import router as reply_drafts_router
from app.api.research_tasks import router as research_tasks_router
from app.api.sending import router as sending_router
from app.api.setup import router as setup_router
from app.api.oauth_google import router as oauth_google_router
from app.api.rules import router as rules_router
from app.api.tracking import router as tracking_router
from app.api.runs import router as runs_router
from app.api.steps import router as steps_router
from app.api.templates import router as templates_router
from app.config import settings
from app.db import SessionLocal
from app.init_db import ensure_schema
from app.services.gmail_oauth import google_client_configured, google_refresh_token_value
from app.services.gmail_tracking_sync_service import sync_gmail_all_open_runs

_log = logging.getLogger(__name__)


async def _gmail_background_sync_loop(interval_sec: int) -> None:
    await asyncio.sleep(8.0)
    while True:
        if not google_client_configured() or not google_refresh_token_value():
            await asyncio.sleep(float(interval_sec))
            continue
        db = SessionLocal()
        try:
            sync_gmail_all_open_runs(db)
        except Exception:
            _log.exception("Background Gmail sync failed")
        finally:
            db.close()
        await asyncio.sleep(float(interval_sec))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_schema()
    interval = int(getattr(settings, "GMAIL_SYNC_INTERVAL_SECONDS", 0) or 0)
    task: asyncio.Task | None = None
    if interval > 0:
        task = asyncio.create_task(_gmail_background_sync_loop(interval))
    yield
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://[::1]:5173",
        "http://[::1]:3000",
    ],
    # Любой порт на loopback — иначе Vite/IDE на другом порту даёт в браузере «Failed to fetch»
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(setup_router)
app.include_router(oauth_google_router)
app.include_router(projects_router)
app.include_router(assets_router)
app.include_router(asset_packets_router)
app.include_router(rules_router)
app.include_router(templates_router)
app.include_router(contacts_router)
app.include_router(email_drafts_router)
app.include_router(email_events_router)
app.include_router(email_threads_router)
app.include_router(follow_up_tasks_router)
app.include_router(reminders_router)
app.include_router(reply_drafts_router)
app.include_router(sending_router)
app.include_router(inbox_router)
app.include_router(tracking_router)
app.include_router(research_tasks_router)
app.include_router(runs_router)
app.include_router(contact_analyzer_router)
app.include_router(gmail_sync_router)
app.include_router(steps_router)


@app.get("/health")
def health():
    return {"status": "ok", "app": settings.APP_NAME}
