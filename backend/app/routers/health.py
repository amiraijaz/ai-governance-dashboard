"""Liveness/readiness probe for load balancers and uptime monitors.

Open (no auth) by design — load balancers can't authenticate. Each downstream
check is wrapped in a 2s timeout so a stalled dependency cannot make the probe
itself hang. The endpoint always returns 200 even when degraded so monitors can
parse the body to decide what's wrong instead of getting a generic 503.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Literal

import redis.asyncio as redis_asyncio
from fastapi import APIRouter
from sqlalchemy import func, select, text

from config import settings
from database import AsyncSessionLocal
from models import ModelPricing

router = APIRouter()

CHECK_TIMEOUT_SECONDS = 2.0
PRICING_STALE_AFTER = timedelta(hours=48)
VERSION = "0.1.0"


async def _check_database() -> Literal["up", "down"]:
    # NOTE: this SELECT 1 is intentional and load-bearing. An external
    # pinger (UptimeRobot / GitHub Actions cron) hits /health every ~10 min,
    # and that round-trip serves two purposes:
    #   1. keeps Render's free web service from spinning down after 15 min idle
    #   2. counts as DB activity on Supabase free, preventing the 7-day pause
    # Do not "optimize" this to a no-op — the DB round trip is the point.
    try:
        async def _run() -> None:
            async with AsyncSessionLocal() as db:
                await db.execute(text("SELECT 1"))
        await asyncio.wait_for(_run(), timeout=CHECK_TIMEOUT_SECONDS)
        return "up"
    except Exception:
        return "down"


async def _check_redis() -> Literal["up", "down"]:
    client = None
    try:
        async def _run() -> None:
            nonlocal client
            client = redis_asyncio.from_url(
                settings.REDIS_URL, socket_timeout=CHECK_TIMEOUT_SECONDS
            )
            await client.ping()
        await asyncio.wait_for(_run(), timeout=CHECK_TIMEOUT_SECONDS)
        return "up"
    except Exception:
        return "down"
    finally:
        if client is not None:
            try:
                await client.aclose()
            except Exception:
                pass


async def _check_pricing_freshness() -> Literal["fresh", "stale"]:
    try:
        async def _run() -> Literal["fresh", "stale"]:
            async with AsyncSessionLocal() as db:
                latest = await db.scalar(select(func.max(ModelPricing.last_synced_at)))
            if latest is None:
                return "stale"
            age = datetime.now(timezone.utc) - latest
            return "fresh" if age < PRICING_STALE_AFTER else "stale"
        return await asyncio.wait_for(_run(), timeout=CHECK_TIMEOUT_SECONDS)
    except Exception:
        return "stale"


@router.get("/health")
async def health() -> dict:
    database, redis_status, pricing = await asyncio.gather(
        _check_database(),
        _check_redis(),
        _check_pricing_freshness(),
    )
    services = {
        "database": database,
        "redis": redis_status,
        "pricing_sync": pricing,
    }
    degraded = database == "down" or redis_status == "down" or pricing == "stale"
    return {
        "status": "degraded" if degraded else "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": services,
        "version": VERSION,
    }
