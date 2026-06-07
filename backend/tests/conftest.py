"""Shared test fixtures.

Design
------
- One **separate** Postgres database (TEST_DATABASE_URL or "<DATABASE_URL with
  /aigov_test suffix>") is created at session start and dropped at session end.
- ``Base.metadata.create_all`` produces the schema; no Alembic round-trip
  because that would couple the test suite to migration history.
- Per-test isolation is via **TRUNCATE ... CASCADE** between tests instead of
  savepoint rollback. Truncate is two orders of magnitude faster than spinning
  up a fresh DB and far less brittle than the after_transaction_end recipe
  under async SQLAlchemy.
- The app's ``get_db`` dependency is overridden so every request inside a test
  uses the test session bound to the test engine. The module-level
  ``AsyncSessionLocal`` from ``database.py`` is never touched.
- ``ASGITransport`` deliberately bypasses the lifespan — no pricing sync, no
  APScheduler, no warmup. The endpoints themselves are what we're testing.
- The slowapi rate limiter is disabled globally for the test session because
  it would require a live Redis and we test the routes, not the limiter.
- External calls (LiteLLM pricing fetch, OpenAI Moderation, Presidio) are
  monkey-patched to deterministic stubs so the suite never touches the network.
"""

from __future__ import annotations

import os
import secrets
import uuid
from typing import AsyncGenerator
from urllib.parse import urlsplit, urlunsplit

# ---------------------------------------------------------------------------
# Env defaults — set BEFORE importing the app, otherwise `config.settings`
# will load the production guards and may refuse to boot.
# ---------------------------------------------------------------------------

os.environ.setdefault("SECRET_KEY", "test-" + secrets.token_hex(32))
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://aigov:aigov@postgres:5432/aigov")
os.environ.setdefault("REDIS_URL", "redis://redis:6379/0")
# Make sure the test DB env exists before app import so any code path that
# reads it directly sees a sensible value.
_default_test = os.environ["DATABASE_URL"]
_parts = urlsplit(_default_test.replace("postgresql+asyncpg://", "postgresql://", 1))
_default_test_url = urlunsplit(_parts._replace(path="/aigov_test"))
os.environ.setdefault("TEST_DATABASE_URL", _default_test_url)

import asyncpg  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool  # noqa: E402

# App imports come AFTER the env defaults above.
from app.main import app  # noqa: E402
from database import Base, get_db  # noqa: E402
from models import User  # noqa: E402


TEST_DATABASE_URL = os.environ["TEST_DATABASE_URL"]


def _split_db_name(url: str) -> tuple[str, str]:
    """Return (admin_url_pointing_at_postgres_db, target_db_name)."""
    parts = urlsplit(url.replace("postgresql+asyncpg://", "postgresql://", 1))
    db_name = parts.path.lstrip("/") or "postgres"
    admin = urlunsplit(parts._replace(path="/postgres"))
    return admin, db_name


async def _ensure_test_db_exists() -> None:
    """Idempotently create the test database. asyncpg CREATE DATABASE
    cannot run inside a transaction, so we use a single direct connection."""
    admin_url, db_name = _split_db_name(TEST_DATABASE_URL)
    conn = await asyncpg.connect(admin_url)
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", db_name
        )
        if not exists:
            # Identifier interpolation — db_name comes from a trusted env var.
            await conn.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Function-scoped engine + DDL bootstrap.
#
# pytest-asyncio 0.24 runs every test on its own event loop. asyncpg
# connections bind to the loop that created them, so a session-scoped
# engine would raise "got Future attached to a different loop" the first
# time a per-test fixture tried to use it. We pay a small per-test cost
# (create_async_engine + dispose) for a much simpler model: engine,
# session, and client all live on the same loop as the test that owns
# them. The schema is set up exactly once via a module-level flag.
# ---------------------------------------------------------------------------

_SCHEMA_READY = False


async def _ensure_schema(eng) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    _SCHEMA_READY = True


@pytest_asyncio.fixture
async def engine():
    await _ensure_test_db_exists()
    eng = create_async_engine(
        TEST_DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1),
        poolclass=NullPool,
        future=True,
    )
    await _ensure_schema(eng)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _bind_session_factory_to_test_engine(engine, monkeypatch):
    """Rebind ``AsyncSessionLocal`` to the test engine.

    Background tasks (safety check after ingest, report generation) open
    their OWN sessions because the request session has closed by the time
    they run. They do that via ``database.AsyncSessionLocal``, which at
    import time was bound to the production engine on the production DB.
    Without this fixture, those background writes land in the wrong DB and
    leave connections owned by a now-dead event loop, surfacing as
    ``RuntimeError: Event loop is closed`` at teardown.
    """
    test_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )
    import database
    monkeypatch.setattr(database, "AsyncSessionLocal", test_factory)
    # Modules that did `from database import AsyncSessionLocal` hold their
    # own reference — patch each binding site.
    from app.routers import (
        evals as _evals_mod,
        logs as _logs_mod,
        reports as _reports_mod,
    )
    monkeypatch.setattr(_logs_mod, "AsyncSessionLocal", test_factory)
    monkeypatch.setattr(_reports_mod, "AsyncSessionLocal", test_factory)
    monkeypatch.setattr(_evals_mod, "AsyncSessionLocal", test_factory)
    yield


@pytest_asyncio.fixture
async def db_session(engine) -> AsyncGenerator[AsyncSession, None]:
    """Per-test session + TRUNCATE-after-test isolation.

    All tables are truncated in reverse-FK order with RESTART IDENTITY CASCADE
    so the next test sees an empty schema. Tests that need pre-seeded data
    create it inside the test itself.
    """
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    session = session_factory()
    try:
        yield session
    finally:
        await session.close()
        async with engine.begin() as conn:
            table_names = ", ".join(f'"{t.name}"' for t in reversed(Base.metadata.sorted_tables))
            await conn.execute(text(f"TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE"))


# ---------------------------------------------------------------------------
# Global tweaks — limiter off, external services mocked
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True, scope="session")
def _disable_rate_limiter():
    """The slowapi limiter would hit Redis on every rate-limited endpoint.
    We test the routes, not the limiter, so disable it for the whole session.
    See test_auth.py for a note on the register rate-limit test."""
    from app.limiter import limiter
    prior = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = prior


@pytest.fixture(autouse=True)
def _mock_external_services(request, monkeypatch):
    """Pin every outbound call to a deterministic stub.

    - pricing_sync.sync_all → fake SyncSummary (never fetches LiteLLM)
    - safety_checker.check → clean GREEN result (overridable per test by
      another monkeypatch later in the same test)
    Tests that need REAL safety_checker behaviour set the
    ``real_safety_checker`` marker so the patch is skipped here.
    """
    from app.schemas.pricing import SyncSummary
    from services import pricing_sync as ps_mod

    async def _fake_sync(_db):
        return SyncSummary(synced=0, updated=0, errors=[])

    monkeypatch.setattr(ps_mod.pricing_sync_service, "sync_all", _fake_sync)

    if "real_safety_checker" in request.keywords:
        return

    from services import safety_checker as sc_mod

    async def _clean_check(_text: str):
        return {"flagged": False, "severity": "GREEN", "flags": []}

    monkeypatch.setattr(sc_mod.safety_checker, "check", _clean_check)


# ---------------------------------------------------------------------------
# HTTP client fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(db_session) -> AsyncGenerator[AsyncClient, None]:
    """Anonymous async client. Routes that require auth will return 401."""

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _register_and_login(
    ac: AsyncClient, email: str, password: str = "TestPass123!"
) -> str:
    r = await ac.post(
        "/api/auth/register",
        json={"email": email, "password": password, "organisation": "TestCo"},
    )
    assert r.status_code in (201, 409), f"register failed: {r.status_code} {r.text}"
    r = await ac.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest_asyncio.fixture
async def auth_client(client, db_session) -> AsyncClient:
    """Client pre-authenticated as a freshly-registered viewer."""
    email = f"viewer-{uuid.uuid4().hex[:8]}@example.com"
    token = await _register_and_login(client, email)
    client.headers["Authorization"] = f"Bearer {token}"
    client.test_user_email = email  # type: ignore[attr-defined]
    return client


# ---------------------------------------------------------------------------
# Pricing seed helper — used by logs-ingest, cost-calculator, and analytics
# tests. Mirrors a tiny slice of seeds/pricing.py.
# ---------------------------------------------------------------------------

DEMO_PRICES: list[tuple[str, str, str, str]] = [
    # (model_key, provider, prompt_cost_per_1k, completion_cost_per_1k)
    ("claude-haiku-4-5",  "Anthropic", "0.0008",  "0.004"),
    ("claude-sonnet-4-5", "Anthropic", "0.003",   "0.015"),
    ("gpt-4o",            "OpenAI",    "0.005",   "0.015"),
    ("gpt-4o-mini",       "OpenAI",    "0.00015", "0.0006"),
]


@pytest_asyncio.fixture
async def seeded_pricing(db_session):
    """Insert a tiny pricing table. Returns the same session for convenience."""
    from decimal import Decimal
    from models import ModelPricing

    for key, provider, prompt_c, completion_c in DEMO_PRICES:
        db_session.add(
            ModelPricing(
                model_key=key,
                provider=provider,
                prompt_cost_per_1k=Decimal(prompt_c),
                completion_cost_per_1k=Decimal(completion_c),
                is_active=True,
            )
        )
    await db_session.commit()
    return db_session


@pytest_asyncio.fixture
async def admin_client(client, db_session) -> AsyncClient:
    """Client pre-authenticated as a freshly-registered user whose role has
    been promoted to admin directly in the DB (the public API never lets a
    register call self-promote)."""
    email = f"admin-{uuid.uuid4().hex[:8]}@example.com"
    token = await _register_and_login(client, email)

    # Promote in the DB. The session has autoflush off; commit so the next
    # request (which uses the same session via the override) sees role=admin.
    from sqlalchemy import update
    await db_session.execute(update(User).where(User.email == email).values(role="admin"))
    await db_session.commit()

    client.headers["Authorization"] = f"Bearer {token}"
    client.test_user_email = email  # type: ignore[attr-defined]
    return client
