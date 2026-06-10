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

    yield
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
            
        _log.warning(f"AuthMiddleware checking path: {full_path} (normalized: {path})")
        
        # Paths that bypass auth (normalized)
        skip_paths = [
            "/health", "/ready", "/docs", "/redoc", "/openapi.json", "/favicon.ico",
            "/setup/status", "/auth/login"
        ]
        
        if any(path.startswith(p) for p in skip_paths):
            return await call_next(request)
            
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            _log.warning(f"AuthMiddleware missing or invalid header for {full_path}")
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
            
        token = auth_header.split(" ")[1]
        if token != settings.GLOBAL_PASSWORD:
            _log.warning(f"AuthMiddleware invalid token for {full_path}. Got: {token[:4]}..., Expected: {settings.GLOBAL_PASSWORD[:4]}...")
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
