from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
from app.api.rules import router as rules_router
from app.api.tracking import router as tracking_router
from app.api.runs import router as runs_router
from app.api.steps import router as steps_router
from app.api.templates import router as templates_router
from app.config import settings
from app.init_db import ensure_schema


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_schema()
    yield


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
app.include_router(steps_router)


@app.get("/health")
def health():
    return {"status": "ok", "app": settings.APP_NAME}
