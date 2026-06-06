from typing import AsyncGenerator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from config import settings


def _normalize_dsn(url: str) -> tuple[str, dict]:
    """Normalize an inbound DATABASE_URL for asyncpg + the Supabase pooler.

    Handles three things at once:

    1. Scheme: `postgres://` (Heroku/Railway legacy) and `postgresql://`
       both become `postgresql+asyncpg://`. URLs that already use the
       asyncpg driver are left alone.
    2. SSL: Supabase requires TLS. `?sslmode=...` is a libpq parameter
       and is rejected by asyncpg, so we strip it from the query string
       and pass `ssl=True` via connect_args instead.
    3. pgbouncer transaction mode (Supabase's "pooler" on :6543) does
       not support server-side prepared statements. asyncpg's default
       statement cache prepares everything, which raises
       "prepared statement \"__asyncpg_stmt_X__\" already exists"
       under load. We disable both caches via connect_args so the
       cache pressure is gone regardless of which port the DSN uses
       (it's also harmless on direct connections).

    Returns (clean_url, connect_args).
    """
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]
    # If it already starts with postgresql+asyncpg:// we leave it alone.

    parts = urlsplit(url)
    query_pairs = [(k, v) for k, v in parse_qsl(parts.query) if k.lower() != "sslmode"]
    cleaned = urlunsplit(parts._replace(query=urlencode(query_pairs)))

    # Same connect_args every time — both safe on direct connections and
    # required on the pgbouncer pooler. Cheap to set unconditionally.
    connect_args = {
        "ssl": True,
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
    }
    return cleaned, connect_args


def _is_local_dsn(url: str) -> bool:
    """True when the DSN points at a local container/postgres host.

    Local docker compose runs the DB unencrypted on the `postgres` service
    name — passing ssl=True there would refuse the connection.
    """
    host = urlsplit(url).hostname or ""
    return host in {"postgres", "localhost", "127.0.0.1", "::1", ""}


_url, _connect_args = _normalize_dsn(settings.DATABASE_URL)
if _is_local_dsn(_url):
    _connect_args.pop("ssl", None)

engine = create_async_engine(
    _url,
    echo=False,
    future=True,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=2,
    connect_args=_connect_args,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
