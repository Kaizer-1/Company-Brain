"""Shared pytest fixtures for the backend test suite."""

import asyncio
from collections.abc import AsyncIterator, Generator, Iterator
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

if TYPE_CHECKING:
    from alembic.config import Config as AlembicConfig

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.main import app

# ---------------------------------------------------------------------------
# Docker / testcontainers availability guard
# ---------------------------------------------------------------------------
try:
    from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]

    _DOCKER_AVAILABLE = True
except Exception:
    _DOCKER_AVAILABLE = False

_POSTGRES_IMAGE = "pgvector/pgvector:pg16"
_ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


# ---------------------------------------------------------------------------
# Postgres testcontainer fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def postgres_container():  # type: ignore[return]
    """Start a pgvector Postgres container once per test session."""
    if not _DOCKER_AVAILABLE:
        pytest.skip("testcontainers or Docker not available — skipping real-DB tests")
    with PostgresContainer(
        image=_POSTGRES_IMAGE,
        username="test",
        password="test",
        dbname="test_company_brain",
    ) as container:
        yield container


@pytest.fixture(scope="session")
def pg_test_dsn(postgres_container: "PostgresContainer") -> str:  # type: ignore[name-defined]
    """Return the asyncpg DSN for the running container."""
    sync_url: str = postgres_container.get_connection_url()
    dsn = sync_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
    if not dsn.startswith("postgresql+asyncpg://"):
        dsn = dsn.replace("postgresql://", "postgresql+asyncpg://")
    return dsn


@pytest.fixture(scope="session")
def run_migrations(pg_test_dsn: str) -> None:
    """Apply Alembic migrations once per test session, synchronously.

    Running migrations in a fresh asyncio event loop (via asyncio.run) keeps
    migration I/O completely separate from each test's per-function event loop,
    avoiding asyncpg 'cannot use Connection.transaction() in a manually started
    transaction' errors that arise when session-scoped and function-scoped async
    fixtures share asyncpg connections across different event loops.
    """
    from alembic import command as alembic_command
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", pg_test_dsn)
    # asyncio.run() creates an isolated event loop — safe from a sync fixture.
    asyncio.run(_upgrade_async(cfg))


async def _upgrade_async(cfg: "AlembicConfig") -> None:  # type: ignore[name-defined]
    from alembic import command as alembic_command

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, alembic_command.upgrade, cfg, "head")


@pytest_asyncio.fixture()
async def migrated_engine(pg_test_dsn: str, run_migrations: None) -> AsyncIterator[AsyncEngine]:
    """Yield a fresh async engine per test, disposed within the same event loop.

    Engine setup, use, and disposal all happen inside a single pytest-asyncio
    function-scoped event loop, avoiding asyncpg 'Event loop is closed' errors
    that arise when session-scoped and function-scoped async fixtures share
    connections across different event loop lifetimes.

    Uses ``build_engine`` (not bare ``create_async_engine``) so that the
    pgvector codec is registered on every connection — consistent with the
    production engine.
    """
    from app.db.session import build_engine

    engine = build_engine(pg_test_dsn)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture()
async def db_session(pg_test_dsn: str, run_migrations: None) -> AsyncIterator[AsyncSession]:
    """Yield a session that rolls back all changes after each test.

    Engine and session are created and torn down within the same event loop
    invocation (function scope) so asyncpg connections are never used across
    different event loops.  Repositories call ``flush()`` (not ``commit()``),
    so rolling back the open transaction restores a clean DB state.

    Uses ``build_engine`` so the pgvector codec is registered — required for
    raw-SQL vector queries to return native arrays rather than text strings.
    """
    from app.db.session import build_engine

    engine = build_engine(pg_test_dsn)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            try:
                yield session
            finally:
                await session.rollback()
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Neo4j testcontainer fixtures (shared by queries/temporal/contradiction tests)
# ---------------------------------------------------------------------------
try:
    from testcontainers.neo4j import Neo4jContainer  # type: ignore[import-untyped]

    _NEO4J_AVAILABLE = True
except Exception:  # pragma: no cover - import guard
    _NEO4J_AVAILABLE = False

_NEO4J_IMAGE = "neo4j:5.26-community"


@pytest.fixture(scope="session")
def shared_neo4j_container() -> Iterator[object]:
    """Start one Neo4j container for the whole (non-resolution) test session."""
    if not _NEO4J_AVAILABLE:
        pytest.skip("testcontainers/Docker not available — skipping Neo4j tests")
    with Neo4jContainer(_NEO4J_IMAGE) as container:
        yield container


@pytest_asyncio.fixture()
async def neo4j_driver(shared_neo4j_container: object) -> AsyncIterator[object]:
    """Yield a connected AsyncDriver with migrations applied and a clean graph."""
    from neo4j import AsyncGraphDatabase

    from app.db.migrations import apply_migrations

    url = shared_neo4j_container.get_connection_url()  # type: ignore[attr-defined]
    password = shared_neo4j_container.password  # type: ignore[attr-defined]
    driver = AsyncGraphDatabase.driver(url, auth=("neo4j", password))
    await apply_migrations(driver)
    async with driver.session() as s:
        await (await s.run("MATCH (n) WHERE NOT n:_Migration DETACH DELETE n")).consume()
    try:
        yield driver
    finally:
        await driver.close()


@pytest.fixture
def healthy_state() -> Generator[None, None, None]:
    """Inject mocks reporting both Neo4j and Postgres as connected."""
    neo4j_mock = AsyncMock()
    neo4j_mock.verify_connectivity.return_value = True
    postgres_mock = AsyncMock()
    postgres_mock.verify_connectivity.return_value = True
    app.state.neo4j = neo4j_mock
    app.state.postgres = postgres_mock
    yield
    del app.state.neo4j
    del app.state.postgres


@pytest.fixture
def neo4j_down_state() -> Generator[None, None, None]:
    """Inject mocks with Neo4j reporting as disconnected."""
    neo4j_mock = AsyncMock()
    neo4j_mock.verify_connectivity.return_value = False
    postgres_mock = AsyncMock()
    postgres_mock.verify_connectivity.return_value = True
    app.state.neo4j = neo4j_mock
    app.state.postgres = postgres_mock
    yield
    del app.state.neo4j
    del app.state.postgres


@pytest.fixture
def postgres_down_state() -> Generator[None, None, None]:
    """Inject mocks with Postgres reporting as disconnected."""
    neo4j_mock = AsyncMock()
    neo4j_mock.verify_connectivity.return_value = True
    postgres_mock = AsyncMock()
    postgres_mock.verify_connectivity.return_value = False
    app.state.neo4j = neo4j_mock
    app.state.postgres = postgres_mock
    yield
    del app.state.neo4j
    del app.state.postgres
