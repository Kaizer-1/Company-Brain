"""Run the Phase-4A agent eval and write a Markdown report.

    uv run python backend/scripts/run_agent_eval.py --output docs/eval/phase-4a-agent-results.md

Assumes:
  - Postgres + Neo4j are running with the populated graph (docker compose up + pipeline run).
  - event_embeddings is populated (general_search needs it).
  - OPENROUTER_API_KEY is set in .env (the agent makes real LLM calls).

The agent makes ~2 LLM calls per question; 30 questions is a few cents. Costs are logged.
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
from app.eval.agent_eval import (  # noqa: E402
    load_questions,
    render_agent_report,
    run_agent_eval,
)
from app.extraction.client import OpenRouterClient  # noqa: E402
from app.logging_config import configure_logging  # noqa: E402

log = structlog.get_logger(__name__)

_DEFAULT_QUESTIONS = Path(__file__).resolve().parents[1] / "data" / "agent_eval_questions.json"


async def _run(output: Path, questions_path: Path) -> None:
    questions = load_questions(questions_path)
    engine = build_engine(settings.postgres_dsn)
    session_factory = build_session_factory(engine)
    neo4j = Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
    client = OpenRouterClient()
    try:
        report = await run_agent_eval(
            questions,
            neo4j_driver=neo4j.driver,
            session_factory=session_factory,
            client=client,
        )
    finally:
        await client.aclose()
        await neo4j.close()
        await engine.dispose()

    md = render_agent_report(report)
    md += f"\n_Generated {datetime.now().date().isoformat()} against the live populated graph._\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(md, encoding="utf-8")
    print(  # noqa: T201
        f"Wrote {output}\n"
        f"  route_accuracy={report.route_accuracy:.3f}  "
        f"citation_overlap={report.citation_overlap_mean:.3f}  "
        f"verify_rate={report.provenance_verification_rate:.3f}  "
        f"refusal={report.refusal_correctness:.3f}\n"
        f"  mean_cost=${report.mean_cost_usd:.5f}  mean_latency={report.mean_latency_ms:.0f}ms"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Phase-4A agent eval.")
    parser.add_argument("--output", default="docs/eval/phase-4a-agent-results.md")
    parser.add_argument("--questions", default=str(_DEFAULT_QUESTIONS))
    args = parser.parse_args()

    configure_logging(debug=False)
    asyncio.run(_run(Path(args.output), Path(args.questions)))


if __name__ == "__main__":
    main()
