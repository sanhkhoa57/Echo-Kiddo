"""Main FastAPI Application for OGK-Server."""
import asyncio
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from server.models.database import init_db, SessionLocal
from server.auth.dependencies import limiter
from server.routers import (
    auth,
    enroll,
    policy,
    heartbeat,
    events,
    commands,
    ws,
    reports,
    audit,
    family,
)
from server.auth.security import decode_jwt_token, verify_csrf_token


async def retention_cleanup_worker():
    """Background worker periodically purging events older than 90 days (FR-F3-04)."""
    while True:
        try:
            with SessionLocal() as db:
                events.purge_events_older_than_90_days(db)
        except Exception:
            pass
        # Run every 6 hours
        await asyncio.sleep(6 * 3600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Ensure database tables are created
    init_db()
    cleanup_task = None
    if not os.getenv("OGK_TESTING"):
        cleanup_task = asyncio.create_task(retention_cleanup_worker())
    yield
    # Shutdown
    if cleanup_task:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="OGK Server API (Open Guardian for Kids)",
    description="Centralized administration server for Open Guardian for Kids (Windows 10/11 x64)",
    version="1.0.0",
    lifespan=lifespan,
)

# Attach rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# Custom validation error handler for strict 422 HTTP responses
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    # Format user-friendly error message
    msg = errors[0].get("msg") if errors else "Dữ liệu yêu cầu không hợp lệ."
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": msg, "errors": jsonable_encoder(errors)},
    )


# CORS: the dashboard is served from this same origin, so no cross-origin access is
# needed by default. Extra origins can be listed in OGK_CORS_ORIGINS (comma separated).
_cors_origins = [o.strip() for o in os.getenv("OGK_CORS_ORIGINS", "").split(",") if o.strip()]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

CSRF_EXEMPT_PATHS = {"/api/v1/auth/login", "/api/v1/auth/register"}


@app.middleware("http")
async def csrf_protection(request: Request, call_next):
    """Anti-CSRF for every write that is authenticated by the session cookie (F5).

    Devices and scripts authenticate with a Bearer header and carry no cookie, so they
    are not affected. A browser session must echo the token in X-CSRF-Token.
    """
    if (
        request.method in ("POST", "PUT", "PATCH", "DELETE")
        and request.url.path.startswith("/api/")
        and request.url.path not in CSRF_EXEMPT_PATHS
    ):
        session_cookie = request.cookies.get("ogk_session")
        if session_cookie:
            try:
                user_id = decode_jwt_token(session_cookie).get("sub") or ""
            except Exception:
                user_id = ""
            token = request.headers.get("X-CSRF-Token", "")
            if not user_id or not token or not verify_csrf_token(user_id, token):
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"detail": "CSRF token không hợp lệ hoặc bị thiếu."},
                )
    return await call_next(request)

# Mount static files and web router
STATIC_DIR = Path(__file__).resolve().parent.parent / "dashboard" / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

from server.routers.web import web_router
app.include_router(web_router)

# Register routers
app.include_router(auth.router)
app.include_router(enroll.router)
app.include_router(policy.router)
app.include_router(heartbeat.router)
app.include_router(events.router)
app.include_router(commands.router)
app.include_router(ws.router)
app.include_router(reports.router)
app.include_router(audit.router)
app.include_router(family.router)


@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "ok", "service": "OGK-Server", "version": "1.0.0"}
