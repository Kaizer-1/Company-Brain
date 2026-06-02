"""One-shot CLI to resolve duplicate entities in the graph (Phase 3A).

Walks the existing Neo4j graph, merges duplicate nodes with reversible ``MERGE_INTO`` edges,
and records every decision in the Postgres ``merge_decisions`` table:

    uv run python backend/scripts/resolve_entities.py
    uv run python backend/scripts/resolve_entities.py --node-type Person
    uv run python backend/scripts/resolve_entities.py --dry-run    # decide + log, write nothing

``--dry-run`` runs the full pipeline (load, embed, rules, tiering) but writes nothing to the
graph or the audit table — the safe iteration mode. Tier 2 adjudication is skipped unless
``OPENROUTER_API_KEY`` is set; without it, ambiguous pairs are conservatively left unmerged.
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
from app.extraction.client import OpenRouterClient  # noqa: E402
from app.logging_config import configure_logging  # noqa: E402
from app.resolution.resolver import resolve_graph  # noqa: E402

log = structlog.get_logger(__name__)


async def _run(node_type: str | None, dry_run: bool) -> None:
    engine = build_engine(settings.postgres_dsn)
    session_factory = build_session_factory(engine)
    neo4j = Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
    client = OpenRouterClient() if settings.openrouter_api_key else None

    try:
        await apply_migrations(neo4j.driver)
        node_types = [node_type] if node_type else None
        async with session_factory() as session:
            report = await resolve_graph(
                neo4j.driver, session, node_types=node_types, client=client, dry_run=dry_run
            )
            if not dry_run:
                await session.commit()

        mode = "DRY RUN — nothing written" if dry_run else "applied"
        print(  # noqa: T201 - CLI summary
            f"Resolution {mode}: {report.total_candidates} candidate pairs, "
            f"{report.total_merges} merges "
            f"(LLM cost ${report.llm_cost_usd:.4f})."
        )
        for type_name, b in report.by_type.items():
            print(  # noqa: T201
                f"  {type_name}: {b.node_count} nodes, {b.candidate_pairs} pairs → "
                f"auto={b.auto_merges} llm_merge={b.llm_merges} "
                f"llm_no_merge={b.llm_no_merges} below_threshold={b.below_threshold}"
            )
    finally:
        if client is not None:
            await client.aclose()
        await neo4j.close()
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve duplicate entities in the graph.")
    parser.add_argument(
        "--node-type",
        choices=["Person", "Service", "System", "Team", "Decision"],
        default=None,
        help="Resolve only this node type (default: all).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the full pipeline but write nothing (log decisions only).",
    )
    args = parser.parse_args()

    configure_logging(debug=settings.debug)
    asyncio.run(_run(args.node_type, args.dry_run))


if __name__ == "__main__":
    main()
