"""Pipeline failure path: malformed LLM JSON marks the run failed and leaves graph clean."""

from __future__ import annotations

from typing import Any

import pytest

from app.extraction.client import CompletionResult
from app.extraction.pipeline import ExtractionPipeline
from app.models.enums import ExtractionStatus

pytestmark = pytest.mark.asyncio


class _BadClient:
    async def complete(self, **_kwargs: Any) -> CompletionResult:
        return CompletionResult(
            content="this is not json", model="fake/model",
            cost_usd=0.0001, prompt_tokens=100, completion_tokens=5,
        )


async def test_malformed_json_marks_failed_and_does_not_write_graph(
    pg_session_factory: Any, neo4j_driver: Any, inserted_event: Any
) -> None:
    pipeline = ExtractionPipeline(
        session_factory=pg_session_factory,
        neo4j_driver=neo4j_driver,
        client=_BadClient(),  # type: ignore[arg-type]
        model="fake/model",
    )
    run = await pipeline.extract_event(inserted_event)

    assert run.status == ExtractionStatus.failed
    assert run.error_message is not None
    assert run.extracted_node_count == 0
    assert run.extracted_edge_count == 0

    # Graph untouched: no nodes were written for this event.
    async with neo4j_driver.session() as s:
        record = await (
            await s.run(
                "MATCH (n) WHERE $eid IN n.source_event_ids RETURN count(n) AS c",
                eid=str(inserted_event.id),
            )
        ).single()
    assert record["c"] == 0
