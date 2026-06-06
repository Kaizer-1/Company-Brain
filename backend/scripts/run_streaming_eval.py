"""Run the Phase-4B perceived-latency eval and write a Markdown report.

    uv run python backend/scripts/run_streaming_eval.py \
        --output docs/eval/phase-4b-streaming-results.md

Samples 10 questions from the existing 30-question agent eval set (3 KQs + 5 search +
2 unknown) and measures time-to-first-synthesis-token for each. Requires a live backend
(docker compose up + full pipeline) and OPENROUTER_API_KEY in .env.

Cost: ~10 questions × ~$0.003 = ~$0.03. Latency: ~60–90s depending on model/network.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import structlog  # noqa: E402

from app.config import settings  # noqa: E402
from app.db.neo4j_client import Neo4jClient  # noqa: E402
from app.db.session import build_engine, build_session_factory  # noqa: E402
from app.eval.streaming_eval import render_streaming_report, run_streaming_eval  # noqa: E402
from app.logging_config import configure_logging  # noqa: E402

log = structlog.get_logger(__name__)

_QUESTIONS_FILE = Path(__file__).resolve().parents[1] / "data" / "agent_eval_questions.json"

# Sample indices into the 30-question eval set: 3 KQ questions + 5 search + 2 unknown.
# Chosen to exercise all route types without running the full 30-question set.
_SAMPLE_INDICES = [0, 5, 10, 15, 20, 21, 22, 23, 24, 25]  # 0-indexed

_DEFAULT_OUTPUT = (
    Path(__file__).resolve().parents[2] / "docs" / "eval" / "phase-4b-streaming-results.md"
)


def _load_sample_questions(questions_file: Path) -> list[str]:
    """Load a sample of questions from the eval questions JSON file."""
    with questions_file.open() as f:
        all_questions = json.load(f)
    sampled = [all_questions[i]["question"] for i in _SAMPLE_INDICES if i < len(all_questions)]
    if not sampled:
        # Fallback to the first 10 questions
        sampled = [q["question"] for q in all_questions[:10]]
    return sampled


async def main(output: Path, questions_file: Path) -> None:
    configure_logging(dev=True)

    if not settings.openrouter_api_key:
        log.error("OPENROUTER_API_KEY not set — cannot run streaming eval")
        sys.exit(1)

    questions = _load_sample_questions(questions_file)
    log.info("streaming_eval_start", questions=len(questions))

    engine = build_engine(settings.postgres_dsn)
    session_factory = build_session_factory(engine)
    neo4j = Neo4jClient(uri=settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))

    try:
        await neo4j.connect()
        report = await run_streaming_eval(
            questions,
            neo4j_driver=neo4j.driver,
            session_factory=session_factory,
        )
    finally:
        await neo4j.close()
        await engine.dispose()

    md = render_streaming_report(report, questions_source=str(questions_file))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(md, encoding="utf-8")
    log.info("streaming_eval_done", output=str(output))

    mean_ft = report.mean_first_token_ms
    if mean_ft is not None:
        status = "✓ target met" if mean_ft <= 3000 else "✗ target missed"
        print(f"{status} (mean first-token: {mean_ft:.0f}ms)")
    print(f"Report written to {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase-4B perceived-latency streaming eval")
    parser.add_argument(
        "--output",
        type=Path,
        default=_DEFAULT_OUTPUT,
        help="Path to write the Markdown report",
    )
    parser.add_argument(
        "--questions",
        type=Path,
        default=_QUESTIONS_FILE,
        help="Path to the agent eval questions JSON file",
    )
    args = parser.parse_args()
    asyncio.run(main(args.output, args.questions))
