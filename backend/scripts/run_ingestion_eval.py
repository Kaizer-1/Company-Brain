"""Run the Phase 5A ingestion eval against the live stack and write the results report.

Usage (from the repo root, against the running docker DBs):

    PYTHONPATH=backend python backend/scripts/run_ingestion_eval.py \
        --output docs/eval/phase-5a-ingestion-results.md

Connects to Postgres + Neo4j via ``app.config.settings`` (defaults target the docker host
ports), reconciles each curated case against the *populated* graph, reverts each, and writes a
Markdown report. Requires ``OPENROUTER_API_KEY`` in ``.env`` (extraction + adjudication).
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
from pathlib import Path

import structlog

from app.config import settings
from app.db.neo4j_client import Neo4jClient
from app.db.session import build_engine, build_session_factory
from app.eval.ingestion_eval import render_report, run_ingestion_eval
from app.extraction.client import OpenRouterClient

log = structlog.get_logger(__name__)


async def _main(output: Path | None) -> None:
    engine = build_engine(settings.postgres_dsn)
    session_factory = build_session_factory(engine)
    neo4j = Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
    client = OpenRouterClient()
    try:
        result = await run_ingestion_eval(
            session_factory, neo4j.driver, client=client
        )
    finally:
        await client.aclose()
        await neo4j.close()
        await engine.dispose()

    generated_at = datetime.now(UTC).isoformat(timespec="seconds")
    report = render_report(result, generated_at=generated_at)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        existing = output.read_text() if output.exists() else ""
        # Preserve a hand-written Discussion block across re-runs.
        marker = "## Discussion"
        if marker in existing and marker in report:
            kept = existing.split(marker, 1)[1]
            report = report.split(marker, 1)[0] + marker + kept
        output.write_text(report)
        log.info("ingestion_eval_report_written", path=str(output))
    else:
        print(report)  # noqa: T201 — CLI output

    print(  # noqa: T201
        f"\nsuccess_rate={result.success_rate:.2%} pass_rate={result.pass_rate:.2%} "
        f"mean_latency={result.mean_latency_ms:.0f}ms mean_cost=${result.mean_cost_usd:.4f}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Phase 5A ingestion eval.")
    parser.add_argument(
        "--output", type=Path, default=None, help="Markdown report path (prints to stdout if omitted)."
    )
    args = parser.parse_args()
    asyncio.run(_main(args.output))


if __name__ == "__main__":
    main()
