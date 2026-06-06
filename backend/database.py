import ssl
from typing import AsyncGenerator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from config import settings


def _is_local_dsn(url: str) -> bool:
    """True when the DSN points at a local container/postgres host.

    Local docker compose runs the DB unencrypted on the `postgres` service
    name — passing any ssl context there would refuse the connection.
    """
    host = urlsplit(url).hostname or ""
    return host in {"postgres", "localhost", "127.0.0.1", "::1", ""}


def _make_ssl_context() -> ssl.SSLContext:
    """Encrypt-only TLS context for managed Postgres (Supabase et al.).

    asyncpg's default ``ssl=True`` builds a verifying SSL context, and
    Render's CA bundle does not validate Supabase's pooler intermediate
    chain ("self-signed certificate in certificate chain"). We still want
    the wire encrypted — we just need to skip chain verification, which
    is the standard approach for managed-Postgres providers that publish
    pooler certs outside the public CA system.
    """
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _normalize_dsn(url: str) -> tuple[str, dict]:
    """Normalize an inbound DATABASE_URL for asyncpg + the Supabase pooler.

    One source of truth — both the app's engine and alembic/env.py call
    this so migrations and runtime connect identically.

    Handles, in order:

    1. Scheme: ``postgres://`` (Heroku/Railway legacy) and ``postgresql://``
       both become ``postgresql+asyncpg://``. URLs already on the asyncpg
       driver are left alone.
    2. SSL query param: Supabase URLs ship ``?sslmode=require``, which is
       a libpq option that asyncpg rejects. We strip it.
    3. SSL context: for remote hosts we pass a non-verifying TLS context
       (see ``_make_ssl_context`` for why). For local hosts we omit the
       ssl key entirely so the local unencrypted Postgres still accepts
       the connection.
    4. pgbouncer transaction mode (Supabase's pooler on :6543) does not
       support server-side prepared statements. asyncpg's caches prepare
       everything by default, which raises
       ``prepared statement "__asyncpg_stmt_X__" already exists`` under
       load. We disable both caches unconditionally — harmless on direct
       connections, mandatory on the pooler.

    Returns ``(clean_url, connect_args)``.
    """
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]
    # If it already starts with postgresql+asyncpg:// we leave it alone.

    parts = urlsplit(url)
    query_pairs = [(k, v) for k, v in parse_qsl(parts.query) if k.lower() != "sslmode"]
    cleaned = urlunsplit(parts._replace(query=urlencode(query_pairs)))

    connect_args: dict = {
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
    }
    if not _is_local_dsn(cleaned):
        connect_args["ssl"] = _make_ssl_context()
    return cleaned, connect_args


_url, _connect_args = _normalize_dsn(settings.DATABASE_URL)

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
