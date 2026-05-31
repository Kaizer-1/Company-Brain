"""Alembic environment configuration for Company Brain.

Uses SQLAlchemy 2.x async engine (asyncpg driver) with the ``run_sync`` pattern
recommended for async-native projects.

The DB URL comes from the Alembic config object — set by the caller:
  - ``app/main.py`` calls ``cfg.set_main_option("sqlalchemy.url", settings.postgres_dsn)``
    before ``command.upgrade(cfg, "head")``
  - Tests' conftest sets ``cfg.set_main_option("sqlalchemy.url", pg_test_dsn)``
  - Direct CLI use reads the URL from ``alembic.ini``

This means ``env.py`` must NOT override the URL from app settings; doing so
would cause test invocations to connect to the wrong database.

``target_metadata`` is populated from ``app.models.Base.metadata``, which
enables ``alembic revision --autogenerate`` to detect schema drift.
"""

import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Import all models so their tables are registered on Base.metadata.
from app.models import Base  # noqa: F401 — side effect: registers all tables

config = context.config

# Deliberately do NOT call fileConfig here. The stock Alembic template calls
# fileConfig(config.config_file_name), which invokes logging.config.fileConfig
# with disable_existing_loggers=True and destroys the structlog handler chain
# set up in app.logging_config. Alembic's own log output routes through the
# existing stdlib root handler as structured JSON instead.

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (generate SQL without a DB connection).

    Used by ``alembic upgrade --sql`` to produce a migration script.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Execute migrations against an open synchronous connection.

    Called from the async runner below via ``connection.run_sync``.
    """
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=False,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations via ``run_sync``."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point called by Alembic for online (connected) migrations."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
