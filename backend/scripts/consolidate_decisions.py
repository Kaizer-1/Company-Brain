"""CLI: multi-source Decision consolidation (Phase 3B; ADR 0017).

    uv run python backend/scripts/consolidate_decisions.py
    uv run python backend/scripts/consolidate_decisions.py --dry-run

Runs after entity resolution. Merges duplicate Decision nodes on content-embedding similarity
(reusing the 3A MERGE_INTO mechanism) and projects schema edges onto canonical winners so the
killer queries see a complete resolved view. ``--dry-run`` decides + logs but writes nothing.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import structlog  # noqa: E402

from app.config import settings  # noqa: E402
from app.db.migrations import apply_migrations  # noqa: E402
from app.db.neo4j_client import Neo4jClient  # noqa: E402
from app.db.session import build_engine, build_session_factory  # noqa: E402
from app.logging_config import configure_logging  # noqa: E402
from app.resolution.consolidator import consolidate_decisions  # noqa: E402
from app.resolution.projection import project_resolved_edges  # noqa: E402

log = structlog.get_logger(__name__)


async def _run(dry_run: bool) -> None:
    engine = build_engine(settings.postgres_dsn)
    session_factory = build_session_factory(engine)
    neo4j = Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
    try:
        await apply_migrations(neo4j.driver)
        async with session_factory() as session:
            counts = await consolidate_decisions(neo4j.driver, session, dry_run=dry_run)
            if not dry_run:
                await session.commit()
        projected = 0 if dry_run else await project_resolved_edges(neo4j.driver)
        mode = "DRY RUN — nothing written" if dry_run else "applied"
        print(  # noqa: T201 - CLI summary
            f"Consolidation {mode}: {counts['decisions']} decisions, "
            f"{counts['candidate_pairs']} pairs, {counts['merges']} content-merges; "
            f"{projected} edges projected to canonical winners."
        )
    finally:
        await neo4j.close()
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Consolidate duplicate Decision nodes.")
    parser.add_argument("--dry-run", action="store_true", help="Decide + log; write nothing.")
    args = parser.parse_args()
    configure_logging(debug=settings.debug)
    asyncio.run(_run(args.dry_run))


if __name__ == "__main__":
    main()
