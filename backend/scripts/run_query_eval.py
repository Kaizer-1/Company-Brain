"""Run the Phase-3B killer-query integration eval and write a Markdown report.

    uv run python backend/scripts/run_query_eval.py --output docs/eval/phase-3b-query-results.md

Runs the whole pipeline against the live stack (seed → extract → resolve → consolidate →
project → messages+contradictions → temporal → query) and scores every KQ against the expected
answers from ``narrative.py``. Needs a reachable Neo4j and Postgres and ``OPENROUTER_API_KEY``
(extraction + adjudication are LLM calls). Defaults to ``claude-3.5-haiku`` for reliability.
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
from app.eval.query_eval import EVAL_MODEL, render_query_report, run_query_eval  # noqa: E402
from app.extraction.client import OpenRouterClient  # noqa: E402
from app.logging_config import configure_logging  # noqa: E402

log = structlog.get_logger(__name__)


async def _run(output: Path, model: str) -> None:
    engine = build_engine(settings.postgres_dsn)
    session_factory = build_session_factory(engine)
    neo4j = Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
    client = OpenRouterClient() if settings.openrouter_api_key else None
    try:
        await apply_migrations(neo4j.driver)
        result = await run_query_eval(neo4j.driver, session_factory, client=client, model=model)
    finally:
        if client is not None:
            await client.aclose()
        await neo4j.close()
        await engine.dispose()

    report = render_query_report(result, generated_at=datetime.now().date().isoformat())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    status = "ALL PASS" if result.all_passed else "FAILURES — see report"
    print(  # noqa: T201 - CLI summary
        f"Wrote {output} — {status}. "
        f"Cost ${result.total_cost_usd:.4f} (resolution+contradiction; extraction logged per call), "
        f"runtime {result.runtime_seconds:.1f}s. Remember to fill in the Discussion section."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the killer-query integration eval.")
    parser.add_argument("--output", default="docs/eval/phase-3b-query-results.md")
    parser.add_argument("--model", default=EVAL_MODEL, help="OpenRouter model for extraction.")
    args = parser.parse_args()
    configure_logging(debug=settings.debug)
    asyncio.run(_run(Path(args.output), args.model))


if __name__ == "__main__":
    main()
