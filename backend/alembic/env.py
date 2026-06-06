import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from config import settings
from database import Base, _is_local_dsn, _normalize_dsn
import models  # noqa: F401  -- ensure all models are imported

# Reuse the exact same DSN handling as the app, so migrations against
# Supabase's pgbouncer pooler don't fail with "prepared statement already
# exists" or asyncpg's sslmode rejection. The clean URL goes into the
# Alembic config; the connect_args ride alongside via async_engine_from_config.
_clean_url, _connect_args = _normalize_dsn(settings.DATABASE_URL)
if _is_local_dsn(_clean_url):
    _connect_args.pop("ssl", None)

config = context.config
config.set_main_option("sqlalchemy.url", _clean_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
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
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
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
