"""The extraction orchestrator: event -> LLM -> graph, with a full audit trail.

``ExtractionPipeline`` ties the four pieces together (prompt, client, parser, graph
writer) and wraps each event in the ``extraction_runs`` lifecycle from Phase 1C: a row is
created in the *failed* status up front, so a crash anywhere leaves a failed row rather
than a phantom in-flight one. Only a clean parse-and-write flips it to *success*.

The shared ``run_extraction`` coroutine (prompt -> client -> parse, no DB, no graph) is
the seam the eval harness reuses: the eval judges this exact output without paying for
graph writes or audit rows.

Concurrency note: unlike the seeder (which flushes into a caller-owned transaction), the
pipeline opens its **own session per event and commits per event**. A 111-event batch
must not lose all progress because event #97 failed, and bounded-concurrency writes
require independent sessions (an ``AsyncSession`` is not safe to share across tasks).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from app.db.repositories.extraction import ExtractionRunRepository
from app.extraction.client import CompletionResult, OpenRouterClient, OpenRouterError
from app.extraction.graph_writer import write_extraction
from app.extraction.parser import ExtractionParseError, parse_extraction
from app.extraction.prompts import PROMPT_VERSION, build_messages, prompt_fingerprint
from app.schemas.postgres import EventDTO, ExtractionRunCreate, ExtractionRunDTO

if TYPE_CHECKING:
    from neo4j import AsyncDriver
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.extraction.models import ExtractionResult

log = structlog.get_logger(__name__)

_JSON_RESPONSE_FORMAT = {"type": "json_object"}
_CONCURRENCY_LIMIT = 5
_PROGRESS_EVERY = 10


async def run_extraction(
    client: OpenRouterClient,
    event_content: str,
    model: str,
) -> tuple[ExtractionResult, CompletionResult]:
    """Prompt the model for one event and return the parsed result + call telemetry.

    No DB, no graph: this is the pure extractor seam shared by the pipeline and the eval
    harness. Raises ``ExtractionParseError`` (bad/empty/wrong-shape JSON) or
    ``OpenRouterError`` (transport) — both surfaced, never swallowed.
    """
    completion = await client.complete(
        messages=build_messages(event_content),
        model=model,
        response_format=_JSON_RESPONSE_FORMAT,
    )
    result = parse_extraction(completion.content)
    return result, completion


class ExtractionPipeline:
    """Runs extraction for one event or a corpus, writing graph + audit rows."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        neo4j_driver: AsyncDriver,
        client: OpenRouterClient,
        model: str,
    ) -> None:
        self._session_factory = session_factory
        self._driver = neo4j_driver
        self._client = client
        self._model = model
        self._extracted_by = f"{model}@{PROMPT_VERSION}"
        self._prompt_hash = prompt_fingerprint()

    async def extract_event(self, event: EventDTO) -> ExtractionRunDTO:
        """Full lifecycle for one event; returns the completed audit DTO.

        Creates the audit row (failed-by-default), calls the model, parses, writes the
        graph, then marks the run success or failed. On any failure the graph is left
        untouched and the row carries the error message.
        """
        async with self._session_factory() as session:
            repo = ExtractionRunRepository(session)
            run = await repo.create_pending(
                ExtractionRunCreate(
                    event_id=event.id,
                    model_name=self._model,
                    model_version=PROMPT_VERSION,
                    prompt_hash=self._prompt_hash,
                    started_at=datetime.now(UTC),
                )
            )
            try:
                result, _completion = await run_extraction(
                    self._client, event.content, self._model
                )
            except (ExtractionParseError, OpenRouterError) as exc:
                final = await repo.mark_failed(run.id, error_message=str(exc)[:1000])
                await session.commit()
                log.warning("extraction_failed", event_id=str(event.id), error=str(exc)[:200])
                return final if final is not None else run

            summary = await write_extraction(
                self._driver,
                event.id,
                result,
                extracted_by=self._extracted_by,
                event_created_at=event.created_at,
            )
            final = await repo.mark_success(
                run.id,
                extracted_node_count=summary.nodes_written,
                extracted_edge_count=summary.edges_written,
            )
            await session.commit()
            return final if final is not None else run

    async def extract_all(self, events: list[EventDTO]) -> list[ExtractionRunDTO]:
        """Extract a corpus with bounded concurrency; logs progress every 10 events.

        The semaphore caps in-flight LLM calls at ``_CONCURRENCY_LIMIT`` so a large batch
        does not rate-limit itself. Each event has its own session (see module docstring).
        """
        semaphore = asyncio.Semaphore(_CONCURRENCY_LIMIT)
        completed = 0
        total = len(events)
        results: list[ExtractionRunDTO] = [None] * total  # type: ignore[list-item]

        async def _one(index: int, event: EventDTO) -> None:
            nonlocal completed
            async with semaphore:
                results[index] = await self.extract_event(event)
            completed += 1
            if completed % _PROGRESS_EVERY == 0 or completed == total:
                log.info("extraction_progress", completed=completed, total=total)

        await asyncio.gather(*(_one(i, e) for i, e in enumerate(events)))
        return results
