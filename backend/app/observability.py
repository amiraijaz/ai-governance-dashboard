"""Optional Sentry integration. Inert when SENTRY_DSN is unset."""

import sys
from typing import Any

from config import settings

INGEST_PATH = "/api/logs"


def _scrub_event(event: dict, hint: dict) -> dict | None:
    """Strip request body for ingest paths.

    Audit-log ingest bodies contain raw prompts / completions. Those must never
    leave our infrastructure — Sentry would be a stealth exfil channel.
    """
    request = event.get("request") or {}
    url = request.get("url") or ""
    if INGEST_PATH in url:
        request.pop("data", None)
        event["request"] = request
    return event


def init_sentry() -> bool:
    """Initialize Sentry if a DSN is configured. Returns whether init ran."""
    dsn = settings.SENTRY_DSN
    if not dsn:
        return False
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
    except ImportError as exc:
        print(f"[sentry] sentry-sdk not installed — skipping init ({exc})", file=sys.stderr)
        return False

    sentry_sdk.init(
        dsn=dsn,
        environment=settings.ENVIRONMENT,
        traces_sample_rate=0.1,
        before_send=_scrub_event,
        integrations=[StarletteIntegration(), FastApiIntegration()],
        release=f"ai-governance-dashboard@0.1.0",
    )
    return True
