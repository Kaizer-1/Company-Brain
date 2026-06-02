"""Run the entity-resolution eval and write a Markdown report (Phase 3A).

    uv run python backend/scripts/run_resolution_eval.py \\
      --output docs/eval/phase-3a-resolution-results.md

Seeds a deterministic fragmented graph from `ALIAS_GROUPS` + `LOOK_ALIKE_PAIRS`, runs the
resolver, scores the merges against ground truth, and writes the report. Needs a reachable
Neo4j and Postgres (it seeds and queries the graph and records audit rows). Tier 2
adjudication runs only if `OPENROUTER_API_KEY` is set; without it, ambiguous pairs (the
look-alikes) are conservatively left unmerged — which is the correct outcome for them.
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
from app.db.migrations import apply_migrations  # noqa: E402
from app.db.neo4j_client import Neo4jClient  # noqa: E402
from app.db.session import build_engine, build_session_factory  # noqa: E402
from app.eval.resolution_eval import render_resolution_report, run_resolution_eval  # noqa: E402
from app.extraction.client import OpenRouterClient  # noqa: E402
from app.logging_config import configure_logging  # noqa: E402

log = structlog.get_logger(__name__)


async def _run(output: Path) -> None:
    engine = build_engine(settings.postgres_dsn)
    session_factory = build_session_factory(engine)
    neo4j = Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
    client = OpenRouterClient() if settings.openrouter_api_key else None

    try:
        await apply_migrations(neo4j.driver)
        async with session_factory() as session:
            result = await run_resolution_eval(neo4j.driver, session, client=client)
    finally:
        if client is not None:
            await client.aclose()
        await neo4j.close()
        await engine.dispose()

    report = render_resolution_report(result, generated_at=datetime.now().date().isoformat())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(  # noqa: T201 - CLI summary
        f"Wrote {output} — precision {result.overall.precision:.2f}, "
        f"recall {result.overall.recall:.2f}, F1 {result.overall.f1:.2f}, "
        f"false-merge {result.false_merge_rate:.2f}, missed-merge {result.missed_merge_rate:.2f}. "
        f"LLM cost ${result.llm_cost_usd:.4f}. Remember to fill in the Discussion section."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the entity-resolution eval and write a report.")
    parser.add_argument(
        "--output",
        default="docs/eval/phase-3a-resolution-results.md",
        help="Report path.",
    )
    args = parser.parse_args()

    configure_logging(debug=settings.debug)
    asyncio.run(_run(Path(args.output)))


if __name__ == "__main__":
    main()
