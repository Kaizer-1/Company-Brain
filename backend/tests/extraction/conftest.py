"""Fixtures for extraction tests: a real Neo4j container + a Postgres session factory.

Both skip gracefully when Docker is unavailable (consistent with the project's real-DB
test convention). The Neo4j driver fixture applies the graph migrations once so MERGE is
constraint-backed, and wipes the graph between tests for isolation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import pytest_asyncio

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

try:
    from testcontainers.neo4j import Neo4jContainer

    _NEO4J_AVAILABLE = True
except Exception:  # pragma: no cover - import guard
    _NEO4J_AVAILABLE = False

_NEO4J_IMAGE = "neo4j:5.26-community"


@pytest.fixture(scope="session")
def neo4j_container() -> Iterator[object]:
    """Start one Neo4j container for the whole test session."""
    if not _NEO4J_AVAILABLE:
        pytest.skip("testcontainers/Docker not available — skipping Neo4j tests")
    with Neo4jContainer(_NEO4J_IMAGE) as container:
        yield container


@pytest_asyncio.fixture
async def neo4j_driver(neo4j_container: object) -> AsyncIterator[object]:
    """Yield a connected AsyncDriver with migrations applied and a clean graph."""
    from neo4j import AsyncGraphDatabase

    from app.db.migrations import apply_migrations

    url = neo4j_container.get_connection_url()  # type: ignore[attr-defined]
    password = neo4j_container.password  # type: ignore[attr-defined]
    driver = AsyncGraphDatabase.driver(url, auth=("neo4j", password))
    await apply_migrations(driver)
    async with driver.session() as s:
        await (await s.run("MATCH (n) WHERE NOT n:_Migration DETACH DELETE n")).consume()
    try:
        yield driver
    finally:
        await driver.close()


@pytest_asyncio.fixture
async def pg_session_factory(migrated_engine: object) -> object:
    """An async session factory bound to the migrated Postgres test container.

    The pipeline opens (and commits) its own session per event, so it needs a factory,
    not the rollback-scoped ``db_session`` fixture.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    return async_sessionmaker(migrated_engine, expire_on_commit=False)  # type: ignore[arg-type]


@pytest_asyncio.fixture
async def inserted_event(pg_session_factory: object) -> AsyncIterator[object]:
    """Insert one event (FK target for extraction_runs) and return its EventDTO.

    The pipeline commits per event, so these rows persist in the shared container; we
    delete them (and any extraction_runs that reference them) on teardown to keep the
    events table clean for the seeder tests' exact-count assertions.
    """
    from datetime import UTC, datetime

    from sqlalchemy import delete, text

    from app.db.repositories.events import EventRepository
    from app.models.enums import SourceType
    from app.models.events import Event
    from app.schemas.postgres import EventCreate

    content = "checkout-service depends on payments-api"
    async with pg_session_factory() as session:  # type: ignore[operator]
        repo = EventRepository(session)
        created = await repo.create(
            EventCreate(
                source_type=SourceType.slack_message,
                source_external_id=f"C-PIPE-{datetime.now(UTC).timestamp()}",
                content=content,
                source_metadata={},
                created_at=datetime.now(UTC),
                content_hash=f"hash-pipe-{datetime.now(UTC).timestamp()}",
            )
        )
        await session.commit()

    try:
        yield created
    finally:
        async with pg_session_factory() as session:  # type: ignore[operator]
            await session.execute(
                text("DELETE FROM extraction_runs WHERE event_id = :eid"),
                {"eid": created.id},
            )
            await session.execute(delete(Event).where(Event.id == created.id))
            await session.commit()
