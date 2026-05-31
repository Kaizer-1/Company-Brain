"""FastAPI application entry point.

Logging is configured at module import time so that lifespan startup logs
are structured. The lifespan context manager handles DB client construction
on startup and graceful shutdown. RequestIDMiddleware is added so every
request carries a unique ID through the log context.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from app.api.health import router as health_router
from app.config import settings
from app.db.migrations import apply_migrations
from app.db.neo4j_client import Neo4jClient
from app.db.postgres import PostgresClient
from app.logging_config import configure_logging
from app.middleware import RequestIDMiddleware

configure_logging(debug=settings.debug)

log = structlog.get_logger(__name__)


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

    await postgres.ensure_pgvector()
    app.state.neo4j = neo4j
    app.state.postgres = postgres
    log.info("startup_complete")
    yield
    await neo4j.close()
    log.info("shutdown_complete")


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(RequestIDMiddleware)
app.include_router(health_router)
