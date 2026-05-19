"""Shared slowapi limiter — Redis-backed so it survives reloads and shards."""

from slowapi import Limiter
from slowapi.util import get_remote_address

from config import settings

limiter = Limiter(key_func=get_remote_address, storage_uri=settings.REDIS_URL)
