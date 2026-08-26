import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.setup_gate import router as setup_gate_router
from app.config import settings
from app.db import SessionLocal
from app.services.env_bootstrap import load_env_from_file

# Populate os.environ from .env at startup so os.environ-based consumers work reliably
# (Tavily client, HTTP(S) proxy for httpx, OSINT_MAX_COMPANIES) — not just settings/pydantic readers.
load_env_from_file()

_log = logging.getLogger(__name__)


class RoutesLoadingMiddleware(BaseHTTPMiddleware):
    """Until background route registration finishes, return 503 (not 404) for API paths."""

    async def dispatch(self, request, call_next):
        path = request.url.path
        if path in ("/health", "/ready") or path.startswith("/docs") or path.startswith("/redoc"):
            return await call_next(request)
        if path in ("/openapi.json", "/favicon.ico"):
            return await call_next(request)
        # /setup is registered synchronously below; do not block it until the heavy async route import finishes.
        if path.startswith("/setup"):
            return await call_next(request)
        rt = getattr(request.app.state, "routes_task", None)
        if rt is not None:
            if not rt.done():
                return JSONResponse(
                    status_code=503,
                    content={"detail": "API routes are still loading; retry shortly."},
                    headers={"Retry-After": "1"},
                )
            rex = rt.exception()
            if rex is not None:
                return JSONResponse(
                    status_code=503,
                    content={
                        "detail": "routes_failed",
                        "error_type": type(rex).__name__,
                        "error_message": str(rex)[:2000],
                    },
                    headers={"Retry-After": "3"},
                )
        return await call_next(request)



async def _ensure_schema_task() -> None:
    """Idempotent DB migrations. Skipped when Docker entrypoint already ran ``ensure_schema()``."""
    if os.environ.get("AI_BIZ_OS_SCHEMA_ALREADY_APPLIED") == "1":
        return
    from app.init_db import ensure_schema

    await asyncio.to_thread(ensure_schema)

async def _run_leadgen_orchestrator() -> None:
    from app.workers.async_orchestrator import leadgen_background_orchestrator
    await leadgen_background_orchestrator()


async def _gmail_background_sync_loop(interval_sec: int) -> None:
    from app.services.gmail_oauth import google_client_configured, google_refresh_token_value
    from app.services.gmail_tracking_sync_service import sync_gmail_all_open_runs

    await asyncio.sleep(8.0)
    while True:
        if not google_client_configured() or not google_refresh_token_value():
            await asyncio.sleep(float(interval_sec))
            continue

        def _sync_once() -> None:
            db = SessionLocal()
            try:
                sync_gmail_all_open_runs(db)
            except Exception:
                _log.exception("Background Gmail sync failed")
            finally:
                db.close()

        # Must not block the asyncio loop — long Gmail I/O would stall every HTTP handler (e.g. GET /runs/:id/companies).
        await asyncio.to_thread(_sync_once)
        await asyncio.sleep(float(interval_sec))


async def _send_queue_worker_loop(interval_sec: int, schema_task: asyncio.Task | None = None) -> None:
    """Release due, gate-passing drafts on cadence. Disabled when SEND_QUEUE_INTERVAL_SECONDS=0."""
    from app.services.sending_scheduler import run_queue_tick_in_thread

    # Do not tick until migrations have created the send_queue tables (avoids "no such table" on cold DB).
    if schema_task is not None:
        try:
            await schema_task
        except Exception:
            _log.exception("schema task failed; send-queue worker will still start")
    await asyncio.sleep(10.0)
    while True:
        # DB + Gmail I/O off the event loop — same discipline as the Gmail sync worker.
        await asyncio.to_thread(run_queue_tick_in_thread)
        await asyncio.sleep(float(interval_sec))


async def _telegram_poller_loop(schema_task: asyncio.Task | None = None) -> None:
    """Long-poll Telegram getUpdates and file inbound messages. Off unless TELEGRAM_POLLER_ENABLED."""
    from app.services.telegram_poller import run_poll_tick_in_thread

    # Offset lives in system_settings — wait for schema so the first tick doesn't hit a cold DB.
    if schema_task is not None:
        try:
            await schema_task
        except Exception:
            _log.exception("schema task failed; telegram poller will still start")
    await asyncio.sleep(6.0)
    while True:
        try:
            # getUpdates long-polls (blocking up to TELEGRAM_POLL_TIMEOUT_SEC) — keep it off the loop.
            await asyncio.to_thread(run_poll_tick_in_thread)
        except Exception:
            _log.exception("telegram poller tick failed")
            await asyncio.sleep(5.0)
        await asyncio.sleep(1.0)


async def _status_snapshot_loop(interval_sec: int, schema_task: asyncio.Task | None = None) -> None:
    """Periodic status.json for the read-only General-topic agent. Off when interval is 0."""
    from app.services.status_snapshot import run_status_snapshot_tick_in_thread

    if schema_task is not None:
        try:
            await schema_task
        except Exception:
            _log.exception("schema task failed; status snapshot worker will still start")
    await asyncio.sleep(15.0)
    while True:
        await asyncio.to_thread(run_status_snapshot_tick_in_thread)
        await asyncio.sleep(float(interval_sec))


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
    orchestrator_task = asyncio.create_task(_run_leadgen_orchestrator())
    _app.state.orchestrator_task = orchestrator_task

    gmail_interval = int(getattr(settings, "GMAIL_SYNC_INTERVAL_SECONDS", 0) or 0)
    gmail_task: asyncio.Task | None = None
    if gmail_interval > 0:
        gmail_task = asyncio.create_task(_gmail_background_sync_loop(gmail_interval))
        _app.state.gmail_task = gmail_task

    send_queue_interval = int(getattr(settings, "SEND_QUEUE_INTERVAL_SECONDS", 0) or 0)
    send_queue_task: asyncio.Task | None = None
    if send_queue_interval > 0:
        send_queue_task = asyncio.create_task(
            _send_queue_worker_loop(send_queue_interval, schema_task),
        )
        _app.state.send_queue_task = send_queue_task

    telegram_poller_task: asyncio.Task | None = None
    if getattr(settings, "TELEGRAM_POLLER_ENABLED", False) and (settings.TELEGRAM_BOT_TOKEN or "").strip():
        telegram_poller_task = asyncio.create_task(_telegram_poller_loop(schema_task))
        _app.state.telegram_poller_task = telegram_poller_task

    status_snapshot_interval = int(getattr(settings, "STATUS_SNAPSHOT_INTERVAL_SECONDS", 0) or 0)
    status_snapshot_task: asyncio.Task | None = None
    if status_snapshot_interval > 0:
        status_snapshot_task = asyncio.create_task(
            _status_snapshot_loop(status_snapshot_interval, schema_task),
        )
        _app.state.status_snapshot_task = status_snapshot_task

    yield
    if status_snapshot_task and not status_snapshot_task.done():
        status_snapshot_task.cancel()
        try:
            await status_snapshot_task
        except asyncio.CancelledError:
            pass
    if telegram_poller_task and not telegram_poller_task.done():
        telegram_poller_task.cancel()
        try:
            await telegram_poller_task
        except asyncio.CancelledError:
            pass
    if send_queue_task and not send_queue_task.done():
        send_queue_task.cancel()
        try:
            await send_queue_task
        except asyncio.CancelledError:
            pass
    if gmail_task and not gmail_task.done():
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
    if orchestrator_task and not orchestrator_task.done():
        orchestrator_task.cancel()
        try:
            await orchestrator_task
        except asyncio.CancelledError:
            pass


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Skip if global password is not set
        if not settings.GLOBAL_PASSWORD:
            return await call_next(request)
            
        full_path = request.url.path
        # Normalize path: remove /api prefix if present for checking
        path = full_path
        if path.startswith("/api"):
            path = path[4:]
        if not path.startswith("/"):
            path = "/" + path
            
        _log.debug(f"AuthMiddleware checking path: {full_path} (normalized: {path})")
        
        # Paths that bypass auth (normalized)
        # /oauth/google: the browser is redirected here by Google — it can never carry
        # the app bearer token, so the OAuth flow must bypass auth.
        skip_paths = [
            "/health", "/ready", "/docs", "/redoc", "/openapi.json", "/favicon.ico",
            "/setup/status", "/auth/login", "/oauth/google"
        ]
        
        if any(path.startswith(p) for p in skip_paths):
            return await call_next(request)
            
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            _log.warning(f"AuthMiddleware missing or invalid header for {full_path}")
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
            
        token = auth_header.split(" ")[1]
        if token != settings.GLOBAL_PASSWORD:
            _log.warning(f"AuthMiddleware invalid token for {full_path}")
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
            
        return await call_next(request)

app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

# Lightweight GET /setup/status only — no boto3 at import time (see app.api.setup_gate).
app.include_router(setup_gate_router)

app.add_middleware(AuthMiddleware)
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
