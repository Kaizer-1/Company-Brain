"""Run the Phase-3D search quality eval and write a Markdown report.

    uv run python backend/scripts/run_search_eval.py --output docs/eval/phase-3d-search-results.md

Assumes:
  - Postgres is running with events seeded (docker compose up).
  - event_embeddings table is populated (run embed_events.py or run_query_eval.py first).
  - Neo4j is running (graph entity counts are used for reranking; empty graph returns
    zero entity counts which degrades to pure vector search but does not fail).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import structlog  # noqa: E402

from app.config import settings  # noqa: E402
from app.db.neo4j_client import Neo4jClient  # noqa: E402
from app.db.session import build_engine, build_session_factory  # noqa: E402
from app.eval.search_eval import render_search_report, run_search_eval  # noqa: E402
from app.logging_config import configure_logging  # noqa: E402

log = structlog.get_logger(__name__)


async def _run(output: Path) -> None:
    engine = build_engine(settings.postgres_dsn)
    session_factory = build_session_factory(engine)
    neo4j = Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
    try:
        async with session_factory() as session:
            result = await run_search_eval(session, neo4j.driver)
    finally:
        await neo4j.close()
        await engine.dispose()

    report = render_search_report(result, generated_at=datetime.now().date().isoformat())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    status = "PASS" if result.passed else "FAIL"
    print(  # noqa: T201
        f"Wrote {output} — {status}. "
        f"Recall@10={result.mean_recall_at_10:.3f}, "
        f"MRR={result.mean_mrr:.3f}, "
        f"Latency={result.mean_latency_ms:.0f}ms"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Phase-3D search quality eval.")
    parser.add_argument(
        "--output",
        default="docs/eval/phase-3d-search-results.md",
        help="Path to write the Markdown report.",
    )
    args = parser.parse_args()
    configure_logging(debug=settings.debug)
    asyncio.run(_run(Path(args.output)))


if __name__ == "__main__":
    main()
