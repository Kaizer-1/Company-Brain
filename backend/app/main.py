"""FastAPI application entry point.

Logging is configured at module import time so that lifespan startup logs
are structured. The lifespan context manager handles DB client construction
on startup and graceful shutdown. RequestIDMiddleware is added so every
request carries a unique ID through the log context.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from fastapi import FastAPI
from sqlalchemy import text

from app.api.health import router as health_router
from app.api.queries import router as queries_router
from app.config import settings
from app.db.migrations import apply_migrations
from app.db.neo4j_client import Neo4jClient
from app.db.postgres import PostgresClient
from app.db.session import build_engine, build_session_factory
from app.logging_config import configure_logging
from app.middleware import RequestIDMiddleware

configure_logging(debug=settings.debug)

log = structlog.get_logger(__name__)

# alembic.ini lives at backend/alembic.ini, one level above this file's package.
_ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


def _run_alembic_upgrade(dsn: str) -> str:
    """Run ``alembic upgrade head`` synchronously and return the head revision.

    This is called via ``asyncio.get_event_loop().run_in_executor`` or directly
    in a sync context from within ``run_sync``.  Alembic's command API is
    synchronous; we wrap it here so it can be called from an async lifespan.
    """
    cfg = AlembicConfig(str(_ALEMBIC_INI))
    # Override the URL from settings so alembic.ini's placeholder is never used.
    cfg.set_main_option("sqlalchemy.url", dsn)
    alembic_command.upgrade(cfg, "head")

    # Determine the head revision that was applied.
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    return heads[0] if heads else "unknown"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Connect to databases on startup; close cleanly on shutdown."""
    log.info("startup", neo4j_uri=settings.neo4j_uri)
    neo4j = Neo4jClient(
        settings.neo4j_uri,
        settings.neo4j_user,
        settings.neo4j_password,
    )
    postgres = PostgresClient(settings.postgres_dsn)

    # Verify Neo4j is reachable before attempting schema migrations.
    if not await neo4j.verify_connectivity():
        log.error("neo4j_unreachable", neo4j_uri=settings.neo4j_uri)
        raise RuntimeError("Neo4j is unreachable; cannot apply graph migrations")

    # Apply graph schema migrations idempotently. A failure here must abort
    # startup rather than silently serve against an unmigrated graph.
    try:
        applied = await apply_migrations(neo4j.driver)
    except Exception:
        log.exception("migrations_failed")
        raise
    log.info("migrations_applied", migrations=applied)

    # Verify Postgres connectivity before attempting Alembic migrations.
    if not await postgres.verify_connectivity():
        log.error("postgres_unreachable")
        raise RuntimeError("Postgres is unreachable; cannot apply schema migrations")

    # Run Alembic migrations synchronously in a thread so we don't block the
    # event loop.  Failure here aborts startup.
    try:
        loop = asyncio.get_event_loop()
        head_revision = await loop.run_in_executor(
            None, _run_alembic_upgrade, settings.postgres_dsn
        )
    except Exception:
        log.exception("postgres_migrations_failed")
        raise
    log.info("postgres_migrations_applied", head_revision=head_revision)

    # Build the async session factory and attach it to app state so routes
    # and the health endpoint can access it.
    engine = build_engine(settings.postgres_dsn)
    session_factory = build_session_factory(engine)

    app.state.neo4j = neo4j
    app.state.postgres = postgres
    app.state.pg_engine = engine
    app.state.session_factory = session_factory
    log.info("startup_complete")
    yield

    await neo4j.close()
    await engine.dispose()
    log.info("shutdown_complete")


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(RequestIDMiddleware)
app.include_router(health_router)
app.include_router(queries_router)
