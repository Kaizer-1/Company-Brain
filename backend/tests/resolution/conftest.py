"""Fixtures for resolution tests: a real Neo4j container with migrations applied.

Mirrors the extraction conftest. Skips gracefully when Docker/testcontainers is unavailable.
Postgres fixtures (``migrated_engine``, ``db_session``) come from the root conftest.
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
def res_neo4j_container() -> Iterator[object]:
    """Start one Neo4j container for the whole resolution test session."""
    if not _NEO4J_AVAILABLE:
        pytest.skip("testcontainers/Docker not available — skipping Neo4j tests")
    with Neo4jContainer(_NEO4J_IMAGE) as container:
        yield container


@pytest_asyncio.fixture
async def neo4j_driver(res_neo4j_container: object) -> AsyncIterator[object]:
    """Yield a connected AsyncDriver with migrations applied and a clean graph."""
    from neo4j import AsyncGraphDatabase

    from app.db.migrations import apply_migrations

    url = res_neo4j_container.get_connection_url()  # type: ignore[attr-defined]
    password = res_neo4j_container.password  # type: ignore[attr-defined]
    driver = AsyncGraphDatabase.driver(url, auth=("neo4j", password))
    await apply_migrations(driver)
    async with driver.session() as s:
        await (await s.run("MATCH (n) WHERE NOT n:_Migration DETACH DELETE n")).consume()
    try:
        yield driver
    finally:
        await driver.close()
