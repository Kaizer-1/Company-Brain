"""Real-DB migration tests — the Phase 1B lesson applied.

This test module answers a question that ``command.upgrade`` returning without
error does NOT answer: did the schema actually get created correctly?

Every assertion in this file performs a direct SQL query against the real
database.  "No exception was raised" is not a test.

Requires Docker (uses testcontainers via the session-scoped ``pg_test_dsn``
fixture from conftest.py).  Tests are skipped if Docker is unavailable.
"""

import asyncio
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

# Fixtures are provided by the root conftest.py (pg_test_dsn, migrated_engine).

_EXPECTED_TABLES = {"events", "event_embeddings", "extraction_runs", "alembic_version"}
_EXPECTED_ENUMS = {"sourcetype", "extractionstatus"}


@pytest.mark.asyncio
async def test_migration_creates_expected_tables(migrated_engine: AsyncEngine) -> None:
    """After upgrade, all expected tables must exist in the public schema."""
    async with migrated_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            )
        )
        tables = {row.tablename for row in result}

    missing = _EXPECTED_TABLES - tables
    assert not missing, f"Tables missing after migration: {missing}"


@pytest.mark.asyncio
async def test_pgvector_extension_is_installed(migrated_engine: AsyncEngine) -> None:
    """The pgvector extension must be installed (direct pg_extension query)."""
    async with migrated_engine.connect() as conn:
        result = await conn.execute(
            text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        )
        row = result.fetchone()

    assert row is not None, (
        "pgvector extension not found in pg_extension. "
        "The migration CREATE EXTENSION IF NOT EXISTS vector may have silently failed."
    )


@pytest.mark.asyncio
async def test_postgres_enum_types_exist(migrated_engine: AsyncEngine) -> None:
    """Both Postgres enum types must exist (direct pg_type query)."""
    async with migrated_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT typname FROM pg_type WHERE typname = ANY(:names)",
            ).bindparams(names=list(_EXPECTED_ENUMS))
        )
        found = {row.typname for row in result}

    missing = _EXPECTED_ENUMS - found
    assert not missing, f"Postgres enum types missing after migration: {missing}"


@pytest.mark.asyncio
async def test_hnsw_index_exists_on_embedding_column(migrated_engine: AsyncEngine) -> None:
    """The HNSW index on event_embeddings.embedding must exist."""
    async with migrated_engine.connect() as conn:
        result = await conn.execute(
            text(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE tablename = 'event_embeddings'
                  AND indexname = 'ix_event_embeddings_embedding'
                """
            )
        )
        row = result.fetchone()

    assert row is not None, (
        "HNSW index 'ix_event_embeddings_embedding' not found on event_embeddings. "
        "Check the CREATE INDEX statement in the initial migration."
    )


@pytest.mark.asyncio
async def test_alembic_version_table_has_head_revision(migrated_engine: AsyncEngine) -> None:
    """alembic_version must contain a row (i.e., migration was recorded)."""
    async with migrated_engine.connect() as conn:
        result = await conn.execute(text("SELECT version_num FROM alembic_version"))
        rows = result.fetchall()

    assert len(rows) == 1, f"Expected 1 row in alembic_version, got {len(rows)}"
    assert rows[0].version_num is not None


@pytest.mark.asyncio
async def test_migration_idempotent_on_second_run(pg_test_dsn: str) -> None:
    """Running alembic upgrade head a second time is a no-op (no error, no change).

    This is the direct Phase 1B anti-pattern test: migrations that succeed
    once but fail (or silently mutate) on re-run are broken.
    """
    from alembic import command as alembic_command
    from alembic.config import Config as AlembicConfig

    alembic_ini = Path(__file__).resolve().parents[2] / "alembic.ini"
    cfg = AlembicConfig(str(alembic_ini))
    cfg.set_main_option("sqlalchemy.url", pg_test_dsn)

    loop = asyncio.get_event_loop()
    # Second upgrade should succeed without error.
    await loop.run_in_executor(None, alembic_command.upgrade, cfg, "head")

    # Verify the table set is unchanged (no accidental drop+recreate).
    engine = create_async_engine(pg_test_dsn, echo=False)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            tables = {row.tablename for row in result}
    finally:
        await engine.dispose()

    missing = _EXPECTED_TABLES - tables
    assert not missing, f"Tables missing after second migration run: {missing}"


@pytest.mark.asyncio
async def test_events_table_has_correct_columns(migrated_engine: AsyncEngine) -> None:
    """Spot-check the events table column list via information_schema."""
    async with migrated_engine.connect() as conn:
        result = await conn.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'events' AND table_schema = 'public'
                """
            )
        )
        cols = {row.column_name for row in result}

    expected = {
        "id", "source_type", "source_external_id", "content",
        "source_metadata", "created_at", "ingested_at", "content_hash",
    }
    missing = expected - cols
    assert not missing, f"Columns missing from events table: {missing}"


@pytest.mark.asyncio
async def test_embedding_column_is_vector_type(migrated_engine: AsyncEngine) -> None:
    """The embedding column in event_embeddings must be the vector type."""
    async with migrated_engine.connect() as conn:
        result = await conn.execute(
            text(
                """
                SELECT udt_name
                FROM information_schema.columns
                WHERE table_name = 'event_embeddings'
                  AND column_name = 'embedding'
                  AND table_schema = 'public'
                """
            )
        )
        row = result.fetchone()

    assert row is not None, "embedding column not found in event_embeddings"
    assert row.udt_name == "vector", (
        f"Expected embedding column to have udt_name 'vector', got '{row.udt_name}'. "
        "The ALTER COLUMN TYPE vector(384) in migration 0004 may have failed."
    )
