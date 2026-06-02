"""The one real-API smoke test.

Hits OpenRouter for a single event, asserts the response parses, cost is reported, and at
least one entity is extracted. Skipped when ``OPENROUTER_API_KEY`` is unset (so CI without
a key is green). On a successful run it records the raw response to a committed cassette so
``test_openrouter_replay.py`` can replay the parse offline (the vcrpy "record once, replay
in CI" pattern, implemented without the extra dependency).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import settings
from app.extraction.client import OpenRouterClient
from app.extraction.parser import parse_extraction
from app.extraction.prompts import build_messages

pytestmark = pytest.mark.asyncio

_CASSETTE = Path(__file__).parent / "cassettes" / "openrouter_decision.json"

_EVENT = (
    "[decision_record] ADR D-0042 — Adopt event-bus for async billing events\n"
    "Status: active\n"
    "Approvers: Dana Lopez (@dana)\n\n"
    "billing-service will publish invoice events to event-bus instead of writing "
    "directly to primary-db. Approved by Dana Lopez."
)


@pytest.mark.skipif(not settings.openrouter_api_key, reason="OPENROUTER_API_KEY not set")
async def test_real_openrouter_extraction_smoke() -> None:
    async with OpenRouterClient() as client:
        completion = await client.complete(
            messages=build_messages(_EVENT),
            model=settings.extraction_model,
            response_format={"type": "json_object"},
        )

    # Cost is reported as a non-negative float (logged by the client on every call).
    assert isinstance(completion.cost_usd, float)
    assert completion.cost_usd >= 0.0

    result = parse_extraction(completion.content)
    assert len(result.entities) >= 1, "expected at least one entity from a decision record"

    # Record the raw response for offline replay (committed cassette).
    _CASSETTE.parent.mkdir(parents=True, exist_ok=True)
    _CASSETTE.write_text(
        json.dumps({"event": _EVENT, "content": completion.content}, indent=2),
        encoding="utf-8",
    )
