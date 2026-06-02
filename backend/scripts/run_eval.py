"""Run the extraction eval across one or more models and write a Markdown report.

    uv run python backend/scripts/run_eval.py \\
      --models openai/gpt-4o-mini,anthropic/claude-3.5-haiku,google/gemini-2.0-flash \\
      --output docs/eval/phase-2b-results.md

The corpus is built **deterministically from the generator** (seed=42), not read from
Postgres: the eval judges extractor quality on the exact known corpus, and not requiring a
running database keeps the numbers reproducible on any machine with just an API key. Each
event is assigned a stable UUID so provenance/caching are well-defined. Per-event responses
are cached on disk, so re-running (or adding a model) only pays for what is new;
``--no-cache`` forces fresh calls.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import structlog  # noqa: E402

from app.config import settings  # noqa: E402
from app.eval.report import render_report  # noqa: E402
from app.eval.runner import EvalResult, ExtractionCache, run_eval  # noqa: E402
from app.extraction.client import OpenRouterClient  # noqa: E402
from app.logging_config import configure_logging  # noqa: E402
from app.schemas.postgres import EventCreate, EventDTO  # noqa: E402
from app.synthetic.generator import SyntheticDataGenerator  # noqa: E402

log = structlog.get_logger(__name__)

# Three cheap, capable models compared via OpenRouter (ADR 0012). Note: the originally
# specced `google/gemini-2.0-flash` has been retired on OpenRouter, so we use its
# cheap-tier successor `google/gemini-2.5-flash-lite`.
_DEFAULT_MODELS = "openai/gpt-4o-mini,anthropic/claude-3.5-haiku,google/gemini-2.5-flash-lite"
# Fixed namespace so a given event content always maps to the same eval UUID.
_EVAL_NS = uuid.UUID("11111111-2222-3333-4444-555555555555")


def _to_dto(event: EventCreate) -> EventDTO:
    """Assign a deterministic UUID to a generated event so it has stable provenance."""
    event_id = uuid.uuid5(_EVAL_NS, event.source_external_id)
    return EventDTO(
        id=event_id,
        source_type=event.source_type,
        source_external_id=event.source_external_id,
        content=event.content,
        source_metadata=event.source_metadata,
        created_at=event.created_at,
        ingested_at=event.created_at,
        content_hash=event.content_hash,
    )


def corpus_event_dtos(limit: int | None = None) -> list[EventDTO]:
    """The deterministic seed=42 corpus as ``EventDTO``s (no database required)."""
    events = [_to_dto(e) for e in SyntheticDataGenerator(seed=42).generate()]
    return events[:limit] if limit is not None else events


async def _run(models: list[str], output: Path, use_cache: bool, limit: int | None) -> None:
    events = corpus_event_dtos(limit)
    cache = ExtractionCache()
    client = OpenRouterClient()
    if not client.has_api_key:
        raise SystemExit("OPENROUTER_API_KEY is not set; cannot run the eval. See .env.example.")

    results: list[EvalResult] = []
    try:
        for model in models:
            log.info("eval_model_start", model=model, events=len(events))
            try:
                result = await run_eval(
                    model, events, client=client, cache=cache, use_cache=use_cache
                )
            except Exception as exc:  # noqa: BLE001 - one bad model must not lose the report
                log.error("eval_model_failed", model=model, error=str(exc)[:300])
                print(f"WARNING: model {model} failed ({exc}); skipping it.")  # noqa: T201
                continue
            results.append(result)
    finally:
        await client.aclose()

    if not results:
        raise SystemExit("All models failed; no report written.")

    report = render_report(results, generated_at=datetime.now().date().isoformat())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")

    total_cost = sum(r.total_cost_usd for r in results)
    fresh = sum(r.fresh_cost_usd for r in results)
    log.info("eval_all_done", models=len(models), total_cost_usd=round(total_cost, 4), fresh_cost_usd=round(fresh, 4))
    print(  # noqa: T201 - CLI summary
        f"Wrote {output} — {len(models)} models, total cost ${total_cost:.4f} "
        f"(fresh ${fresh:.4f}). Remember to fill in the Discussion section."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the extraction eval and write a Markdown report.")
    parser.add_argument("--models", default=_DEFAULT_MODELS, help="Comma-separated OpenRouter model ids.")
    parser.add_argument("--output", default="docs/eval/phase-2b-results.md", help="Report path.")
    parser.add_argument("--no-cache", action="store_true", help="Force fresh API calls (ignore cache).")
    parser.add_argument("--limit", type=int, default=None, help="Only evaluate the first N events.")
    args = parser.parse_args()

    configure_logging(debug=settings.debug)
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    asyncio.run(_run(models, Path(args.output), not args.no_cache, args.limit))


if __name__ == "__main__":
    main()
