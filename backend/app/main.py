import asyncio
import sys
import traceback
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.limiter import limiter
from app.observability import init_sentry

from app.routers import (
    analytics,
    auth,
    cost,
    flags,
    health,
    keys,
    logs,
    models,
    pricing,
    reports,
    safety,
    users,
)
from config import secret_key_is_weak, settings
from database import AsyncSessionLocal
from services.pricing_sync import pricing_sync_service
from services.safety_checker import safety_checker


async def _run_sync() -> None:
    async with AsyncSessionLocal() as db:
        try:
            await pricing_sync_service.sync_all(db)
        except Exception as exc:
            print(f"[pricing] scheduled sync failed: {exc}", file=sys.stderr)


async def _run_sync_with_timeout(timeout_seconds: float) -> None:
    """Startup wrapper. Never raises — a slow upstream catalog must not block boot."""
    try:
        await asyncio.wait_for(_run_sync(), timeout=timeout_seconds)
        print("[pricing] startup sync complete", file=sys.stderr)
    except asyncio.TimeoutError:
        print(
            f"[pricing] startup sync timed out after {timeout_seconds}s — "
            "will retry in 24h via scheduler",
            file=sys.stderr,
        )
    except Exception as exc:
        print(
            f"[pricing] startup sync failed: {exc} — will retry in 24h",
            file=sys.stderr,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.DEBUG and secret_key_is_weak(settings.SECRET_KEY):
        print(
            "[security] WARNING: SECRET_KEY is set to a known weak value "
            "(allowed only because DEBUG=true). "
            "Generate one with `openssl rand -hex 32` before going to production.",
            file=sys.stderr,
        )

    # Presidio + spaCy load lazily on first PII flag — see SafetyChecker
    # docstring. Render's 512 MB free tier can't afford an eager warmup.
    app.state.safety_checker = safety_checker

    await _run_sync_with_timeout(timeout_seconds=10.0)
    scheduler = AsyncIOScheduler()
    scheduler.add_job(_run_sync, "interval", hours=24, id="pricing_sync")
    scheduler.start()
    app.state.scheduler = scheduler
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


init_sentry()

app = FastAPI(title="AI Governance Dashboard", version="0.1.0", lifespan=lifespan)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

_cors_origins = ["http://localhost:3000", "http://localhost:5173"]
for raw in (settings.FRONTEND_URL or "").split(","):
    origin = raw.strip().rstrip("/")
    if origin and origin not in _cors_origins:
        _cors_origins.append(origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # FastAPI handles HTTPException + RequestValidationError before reaching here,
    # so anything that arrives is genuinely unexpected.
    print(f"[error] {request.method} {request.url.path}: {exc!r}", file=sys.stderr)
    if settings.DEBUG:
        traceback.print_exc()

    body: dict = {
        "detail": "Internal server error",
        "type": exc.__class__.__name__,
    }
    if settings.DEBUG:
        body["message"] = str(exc)
    return JSONResponse(status_code=500, content=body)


app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(models.router, prefix="/api/models", tags=["models"])
app.include_router(keys.router, prefix="/api/keys", tags=["keys"])
app.include_router(logs.router, prefix="/api/logs", tags=["logs"])
app.include_router(logs.ingest_router, prefix="/api/logs", tags=["logs-ingest"])
app.include_router(pricing.router, prefix="/api/pricing", tags=["pricing"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["analytics"])
app.include_router(flags.router, prefix="/api/flags", tags=["flags"])
app.include_router(reports.router, prefix="/api/reports", tags=["reports"])
app.include_router(safety.router, prefix="/api/safety", tags=["safety"])
app.include_router(cost.router, prefix="/api/cost", tags=["cost"])
app.include_router(health.router, tags=["health"])
