import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.db import SessionLocal
from app.services.gmail_oauth import google_client_configured, google_refresh_token_value

_log = logging.getLogger(__name__)


class RoutesLoadingMiddleware(BaseHTTPMiddleware):
    """Until background route registration finishes, return 503 (not 404) for API paths."""

    async def dispatch(self, request, call_next):
        path = request.url.path
        if path in ("/health", "/ready") or path.startswith("/docs") or path.startswith("/redoc"):
            return await call_next(request)
        if path in ("/openapi.json", "/favicon.ico"):
            return await call_next(request)
        rt = getattr(request.app.state, "routes_task", None)
        if rt is not None and not rt.done():
            return JSONResponse(
                status_code=503,
                content={"detail": "API routes are still loading; retry shortly."},
                headers={"Retry-After": "1"},
            )
        return await call_next(request)


async def _gmail_background_sync_loop(interval_sec: int) -> None:
    from app.services.gmail_tracking_sync_service import sync_gmail_all_open_runs

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


async def _ensure_schema_task() -> None:
    """Idempotent DB migrations. Skipped when Docker entrypoint already ran ``ensure_schema()``."""
    if os.environ.get("AI_BIZ_OS_SCHEMA_ALREADY_APPLIED") == "1":
        return
    from app.init_db import ensure_schema

    await asyncio.to_thread(ensure_schema)


async def _register_routes_task(app: FastAPI) -> None:
    from app.routes_register import attach_api_routers, import_api_routers

    routers = await asyncio.to_thread(import_api_routers)
    attach_api_routers(app, routers)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    schema_task = asyncio.create_task(_ensure_schema_task())
    _app.state.schema_task = schema_task
    routes_task = asyncio.create_task(_register_routes_task(_app))
    _app.state.routes_task = routes_task

    interval = int(getattr(settings, "GMAIL_SYNC_INTERVAL_SECONDS", 0) or 0)
    gmail_task: asyncio.Task | None = None
    if interval > 0:
        gmail_task = asyncio.create_task(_gmail_background_sync_loop(interval))
    yield
    if gmail_task:
        gmail_task.cancel()
        try:
            await gmail_task
        except asyncio.CancelledError:
            pass
    if routes_task and not routes_task.done():
        routes_task.cancel()
        try:
            await routes_task
        except asyncio.CancelledError:
            pass
    if schema_task and not schema_task.done():
        schema_task.cancel()
        try:
            await schema_task
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
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RoutesLoadingMiddleware)


@app.get("/health")
async def health():
    return {"status": "ok", "app": settings.APP_NAME}


@app.get("/ready")
async def ready():
    """Process up, DB schema applied, and API routers registered (what deploy-local.sh waits for)."""
    t = getattr(app.state, "schema_task", None)
    if t is None:
        return JSONResponse(status_code=503, content={"ready": False, "reason": "no_task"})
    if not t.done():
        return JSONResponse(status_code=503, content={"ready": False, "reason": "schema_pending"})
    if t.cancelled():
        return JSONResponse(status_code=503, content={"ready": False, "reason": "cancelled"})
    exc = t.exception()
    if exc is not None:
        return JSONResponse(status_code=503, content={"ready": False, "reason": "schema_failed"})
    rt = getattr(app.state, "routes_task", None)
    if rt is None:
        return JSONResponse(status_code=503, content={"ready": False, "reason": "no_routes_task"})
    if not rt.done():
        return JSONResponse(status_code=503, content={"ready": False, "reason": "routes_pending"})
    if rt.cancelled():
        return JSONResponse(status_code=503, content={"ready": False, "reason": "routes_cancelled"})
    rex = rt.exception()
    if rex is not None:
        return JSONResponse(status_code=503, content={"ready": False, "reason": "routes_failed"})
    return {"ready": True, "database": True, "routes": True}
