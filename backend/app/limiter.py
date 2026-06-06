"""Shared slowapi limiter — Redis-backed so it survives reloads and shards."""

import hashlib

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from config import settings

limiter = Limiter(key_func=get_remote_address, storage_uri=settings.REDIS_URL)


def api_key_rate_limit_key(request: Request) -> str:
    """Key function for ingest endpoints — buckets by API key, not by client IP.

    Hashes the raw key so it never lands in the limiter's Redis storage in
    plaintext. Falls back to the remote address when the header is absent so
    unauthenticated floods can't escape rate limiting entirely.
    """
    raw_key = request.headers.get("X-API-Key")
    if raw_key:
        digest = hashlib.sha256(raw_key.encode()).hexdigest()
        return f"apikey:{digest}"
    return f"ip:{get_remote_address(request)}"
