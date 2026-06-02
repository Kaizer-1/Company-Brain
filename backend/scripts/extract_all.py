"""One-shot CLI to run the extraction pipeline over the Postgres corpus into Neo4j.

This is NOT startup work (ADR 0012 / spec): extraction is expensive and idempotent, so it
runs on demand, never in the FastAPI lifespan. Run it against a seeded stack:

    uv run python backend/scripts/extract_all.py --model openai/gpt-4o-mini
    uv run python backend/scripts/extract_all.py --limit 10   # cheap dev subset

It reads events from Postgres, applies the graph migrations (so MERGE is constraint-backed
and idempotent), extracts each event, writes nodes/edges with provenance, records an
``extraction_runs`` row per attempt, and prints a success/failure summary.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import structlog  # noqa: E402

from app.config import settings  # noqa: E402
from app.db.migrations import apply_migrations  # noqa: E402
from app.db.neo4j_client import Neo4jClient  # noqa: E402
from app.db.repositories.events import EventRepository  # noqa: E402
from app.db.session import build_engine, build_session_factory  # noqa: E402
from app.extraction.client import OpenRouterClient  # noqa: E402
from app.extraction.pipeline import ExtractionPipeline  # noqa: E402
from app.logging_config import configure_logging  # noqa: E402
from app.models.enums import ExtractionStatus  # noqa: E402

log = structlog.get_logger(__name__)

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


async def _run(model: str, limit: int | None) -> None:
    engine = build_engine(settings.postgres_dsn)
    session_factory = build_session_factory(engine)
    neo4j = Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
    client = OpenRouterClient()

    try:
        await apply_migrations(neo4j.driver)

        async with session_factory() as session:
            events = await EventRepository(session).list_since(_EPOCH)
        if limit is not None:
            events = events[:limit]
        log.info("extract_all_start", model=model, event_count=len(events))

        pipeline = ExtractionPipeline(
            session_factory=session_factory,
            neo4j_driver=neo4j.driver,
            client=client,
            model=model,
        )
        runs = await pipeline.extract_all(events)

        succeeded = sum(1 for r in runs if r.status == ExtractionStatus.success)
        failed = len(runs) - succeeded
        nodes = sum(r.extracted_node_count for r in runs)
        edges = sum(r.extracted_edge_count for r in runs)
        log.info(
            "extract_all_done",
            model=model,
            succeeded=succeeded,
            failed=failed,
            nodes=nodes,
            edges=edges,
        )
        print(  # noqa: T201 - CLI summary
            f"Extraction complete: {succeeded} ok, {failed} failed, "
            f"{nodes} nodes, {edges} edges written by {model}."
        )
    finally:
        await client.aclose()
        await neo4j.close()
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the LLM extraction pipeline over Postgres events.")
    parser.add_argument("--model", default=settings.extraction_model, help="OpenRouter model id.")
    parser.add_argument("--limit", type=int, default=None, help="Only extract the first N events.")
    args = parser.parse_args()

    configure_logging(debug=settings.debug)
    asyncio.run(_run(args.model, args.limit))


if __name__ == "__main__":
    main()
