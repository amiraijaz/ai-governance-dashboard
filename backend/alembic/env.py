import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context

from config import settings
from database import Base, _is_local_dsn, _normalize_dsn
import models  # noqa: F401  -- ensure all models are imported

# DSN handling matches the app exactly so migrations against Supabase's
# pgbouncer pooler don't trip prepared-statement errors or asyncpg's
# sslmode rejection.
_clean_url, _connect_args = _normalize_dsn(settings.DATABASE_URL)
if _is_local_dsn(_clean_url):
    _connect_args.pop("ssl", None)

# IMPORTANT: do NOT route _clean_url through config.set_main_option /
# config.get_section. Alembic stores those values in a ConfigParser
# section that performs %-interpolation, and a URL-encoded password
# (e.g. "pa%40ss" for "pa@ss") raises "invalid interpolation syntax".
# Pass the URL directly to create_async_engine and context.configure
# instead — asyncpg sees the real single-%-encoded password verbatim.
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=_clean_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = create_async_engine(
        _clean_url,
        poolclass=pool.NullPool,
        connect_args=_connect_args,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
