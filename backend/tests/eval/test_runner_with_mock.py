"""Full eval against a mocked extractor — no network, no DB.

Verifies the runner wires extraction -> canonicalisation -> metrics -> report correctly,
using a fake client that returns a fixed extraction for every event.
"""

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.eval.report import DISCUSSION_MARKER, render_report
from app.eval.runner import ExtractionCache, run_eval
from app.extraction.client import CompletionResult
from app.models.enums import SourceType
from app.schemas.postgres import EventDTO

# A fixed, correct extraction: one known entity + one known relationship.
_FIXED_JSON = (
    '{"entities": ['
    '{"type": "Service", "canonical_name": "auth-service", "properties": {}, '
    '"evidence_quote": "auth-service", "confidence": 0.95}], '
    '"relationships": ['
    '{"type": "DEPENDS_ON", "source_canonical_name": "payments-api", '
    '"target_canonical_name": "auth-service", "evidence_quote": "x", "confidence": 0.9}]}'
)

# A fake that returns invalid JSON, to exercise the parse-failure counter.
_BAD_JSON = "not json at all"


class _FakeClient:
    def __init__(self, content: str) -> None:
        self._content = content

    async def complete(
        self,
        *,
        messages: list[dict[str, str]],
        model: str,
        response_format: dict[str, str] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> CompletionResult:
        return CompletionResult(
            content=self._content,
            model=model,
            cost_usd=0.0001,
            prompt_tokens=100,
            completion_tokens=20,
        )


def _events(n: int = 3) -> list[EventDTO]:
    now = datetime.now(UTC)
    return [
        EventDTO(
            id=uuid.uuid4(),
            source_type=SourceType.slack_message,
            source_external_id=f"C-{i}",
            content=f"event {i}",
            source_metadata={},
            created_at=now,
            ingested_at=now,
            content_hash=f"hash{i}",
        )
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_runner_computes_metrics_and_cost(tmp_path: Path) -> None:
    events = _events()
    cache = ExtractionCache(tmp_path)
    result = await run_eval(
        "fake/model", events, client=_FakeClient(_FIXED_JSON), cache=cache, use_cache=False  # type: ignore[arg-type]
    )

    # Exactly one correct entity is extracted (deduped across all events).
    assert result.entity_metrics.true_positives == 1
    assert result.entity_metrics.false_positives == 0
    assert result.entity_metrics.precision == pytest.approx(1.0)
    # Recall is low because only 1 of 45 ground-truth entities was produced.
    assert 0.0 < result.entity_metrics.recall < 0.1
    assert result.relationship_metrics.true_positives == 1
    # Cost is summed across the 3 events.
    assert result.total_cost_usd == pytest.approx(0.0003)
    assert result.parse_failures == 0


@pytest.mark.asyncio
async def test_runner_counts_parse_failures(tmp_path: Path) -> None:
    events = _events(2)
    result = await run_eval(
        "fake/model", events, client=_FakeClient(_BAD_JSON), cache=ExtractionCache(tmp_path), use_cache=False  # type: ignore[arg-type]
    )
    assert result.parse_failures == 2
    assert result.entity_metrics.true_positives == 0


@pytest.mark.asyncio
async def test_report_renders(tmp_path: Path) -> None:
    events = _events()
    result = await run_eval(
        "fake/model", events, client=_FakeClient(_FIXED_JSON), cache=ExtractionCache(tmp_path), use_cache=False  # type: ignore[arg-type]
    )
    report = render_report([result], generated_at="2026-06-01")
    assert "Phase 2B" in report
    assert "fake/model" in report
    assert DISCUSSION_MARKER in report
    assert "Entity F1" in report
