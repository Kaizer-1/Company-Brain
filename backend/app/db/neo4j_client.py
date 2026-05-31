"""Async Neo4j driver wrapper.

Provides a thin context-managed session helper and a connectivity probe
used by the health endpoint. All Cypher execution happens via the session
helper — never via ad-hoc driver references elsewhere in the codebase.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncSession


class Neo4jClient:
    """Thin wrapper around the official Neo4j async driver."""

    def __init__(self, uri: str, user: str, password: str) -> None:
        self._driver: AsyncDriver = AsyncGraphDatabase.driver(uri, auth=(user, password))

    async def close(self) -> None:
        """Release all driver connections."""
        await self._driver.close()

    @property
    def driver(self) -> AsyncDriver:
        """Expose the underlying driver for the migration runner (ADR 0008).

        The runner takes an ``AsyncDriver`` by contract and needs driver-level
        session control. This is the one sanctioned use of the raw driver
        outside this class; all *query* execution still goes through session().
        """
        return self._driver

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Yield a managed Neo4j session that closes on exit."""
        async with self._driver.session() as s:
            yield s

    async def verify_connectivity(self) -> bool:
        """Return True if Neo4j responds to RETURN 1, False otherwise."""
        try:
            async with self.session() as s:
                result = await s.run("RETURN 1 AS check")
                await result.consume()
            return True
        except Exception:
            return False
