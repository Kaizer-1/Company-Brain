"""Full pipeline test with a mocked LLM: audit row + graph populated on success."""

from __future__ import annotations

from typing import Any

import pytest

from app.extraction.client import CompletionResult
from app.extraction.pipeline import ExtractionPipeline
from app.models.enums import ExtractionStatus

pytestmark = pytest.mark.asyncio

_VALID = (
    '{"entities": ['
    '{"type": "Service", "canonical_name": "checkout-service", "properties": {}, '
    '"evidence_quote": "checkout-service", "confidence": 0.9},'
    '{"type": "Service", "canonical_name": "payments-api", "properties": {}, '
    '"evidence_quote": "payments-api", "confidence": 0.9}], '
    '"relationships": ['
    '{"type": "DEPENDS_ON", "source_canonical_name": "checkout-service", '
    '"target_canonical_name": "payments-api", '
    '"evidence_quote": "checkout-service depends on payments-api", "confidence": 0.9}]}'
)


class _FakeClient:
    def __init__(self, content: str) -> None:
        self._content = content

    async def complete(self, **_kwargs: Any) -> CompletionResult:
        return CompletionResult(
            content=self._content, model="fake/model",
            cost_usd=0.0001, prompt_tokens=100, completion_tokens=20,
        )


async def test_successful_extraction_writes_audit_and_graph(
    pg_session_factory: Any, neo4j_driver: Any, inserted_event: Any
) -> None:
    pipeline = ExtractionPipeline(
        session_factory=pg_session_factory,
        neo4j_driver=neo4j_driver,
        client=_FakeClient(_VALID),  # type: ignore[arg-type]
        model="fake/model",
    )
    run = await pipeline.extract_event(inserted_event)

    assert run.status == ExtractionStatus.success
    assert run.extracted_node_count == 2
    assert run.extracted_edge_count == 1
    assert run.error_message is None

    # Graph populated.
    async with neo4j_driver.session() as s:
        record = await (
            await s.run(
                "MATCH (:Service {canonical_name:'checkout-service'})-[:DEPENDS_ON]->"
                "(:Service {canonical_name:'payments-api'}) RETURN count(*) AS c"
            )
        ).single()
    assert record["c"] == 1

    # Audit row persisted with success status.
    from app.db.repositories.extraction import ExtractionRunRepository

    async with pg_session_factory() as session:
        latest = await ExtractionRunRepository(session).latest_for_event(inserted_event.id)
    assert latest is not None
    assert latest.status == ExtractionStatus.success
