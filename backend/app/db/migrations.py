"""Idempotent Cypher migration runner for the Neo4j graph.

Reads numbered ``*.cypher`` files from ``backend/migrations/graph/`` in name
order and applies each one that has not yet been recorded. Applied migrations
are tracked as ``(:_Migration {name, applied_at})`` nodes, so re-running the
runner against an already-migrated graph is a no-op and never duplicates
records. Called from the FastAPI lifespan on startup, after Neo4j connectivity
is verified.

Rationale for a homemade runner over neo4j-migrations / Liquibase: see ADR 0008.
"""

from pathlib import Path

import structlog
from neo4j import AsyncDriver, AsyncSession

log = structlog.get_logger(__name__)

# backend/app/db/migrations.py -> parents[2] == backend/
MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations" / "graph"

_APPLIED_QUERY = "MATCH (m:_Migration) RETURN m.name AS name"
_RECORD_QUERY = "MERGE (m:_Migration {name: $name}) ON CREATE SET m.applied_at = datetime()"


def _split_statements(text: str) -> list[str]:
    """Split a Cypher file into individual executable statements.

    Full-line ``//`` comments and blank lines are stripped, the remainder is
    split on ``;``, and empty fragments are dropped. A file that is entirely
    comments (e.g. 003_existence_constraints.cypher on Community Edition)
    yields an empty list, which the runner records as an applied no-op.
    """
    code_lines = [line for line in text.splitlines() if not line.strip().startswith("//")]
    fragments = "\n".join(code_lines).split(";")
    return [stmt.strip() for stmt in fragments if stmt.strip()]


async def _applied_migration_names(session: AsyncSession) -> set[str]:
    """Return the names of migrations already recorded in the graph."""
    result = await session.run(_APPLIED_QUERY)
    rows = await result.data()
    return {str(row["name"]) for row in rows}


async def apply_migrations(driver: AsyncDriver, *, migrations_dir: Path | None = None) -> list[str]:
    """Apply all pending Cypher migrations in name order; return the new ones.

    Idempotent: migrations already recorded as ``:_Migration`` nodes are
    skipped. Each newly applied migration's statements run as auto-commit
    transactions (the correct path for schema DDL in Neo4j 5.x), after which a
    ``:_Migration`` record is written so the migration is never re-applied.

    Args:
        driver: a connected Neo4j async driver.
        migrations_dir: override the migrations directory (used by tests);
            defaults to ``backend/migrations/graph``.

    Returns:
        The names of the migrations applied by this call, in execution order.
    """
    directory = migrations_dir or MIGRATIONS_DIR
    if not directory.exists():
        raise RuntimeError(
            f"Migrations directory does not exist: {directory}. "
            "Check that backend/migrations/ is copied into the image."
        )
    migration_files = sorted(directory.glob("*.cypher"))
    if not migration_files:
        raise RuntimeError(
            f"No .cypher migration files found in {directory}. "
            "This is almost certainly a packaging bug — refusing to silently no-op."
        )
    files = sorted(directory.glob("*.cypher"))
    newly_applied: list[str] = []

    async with driver.session() as session:
        already_applied = await _applied_migration_names(session)

        for path in files:
            name = path.name
            if name in already_applied:
                continue

            statements = _split_statements(path.read_text(encoding="utf-8"))
            for statement in statements:
                result = await session.run(statement)
                await result.consume()

            record = await session.run(_RECORD_QUERY, name=name)
            await record.consume()

            newly_applied.append(name)
            log.info("migration_applied", name=name, statements=len(statements))

    return newly_applied
