"""Tier 2 adjudicator: prompt construction, robust parsing, and the safe no-merge fallback."""

from __future__ import annotations

import os

import pytest

from app.extraction.client import CompletionResult
from app.models.enums import NodeType
from app.resolution.adjudicator import (
    Adjudicator,
    build_adjudication_messages,
    parse_verdict,
)
from app.resolution.models import CandidatePair, ResolvableNode


def _pair() -> CandidatePair:
    a = ResolvableNode(
        node_type=NodeType.Service, node_id="notifications-api",
        properties={"description": "accepts notification requests"},
    )
    b = ResolvableNode(
        node_type=NodeType.Service, node_id="notification-worker",
        properties={"description": "delivers notifications off event-bus"},
    )
    return CandidatePair(node_a=a, node_b=b, similarity=0.88)


class _FakeClient:
    """Minimal stand-in for OpenRouterClient.complete."""

    def __init__(self, *, content: str | None = None, raise_exc: Exception | None = None) -> None:
        self._content = content
        self._raise = raise_exc
        self.calls: list[dict[str, object]] = []

    async def complete(self, *, messages, model, response_format=None, **_):  # type: ignore[no-untyped-def]
        self.calls.append({"messages": messages, "model": model})
        if self._raise is not None:
            raise self._raise
        assert self._content is not None
        return CompletionResult(
            content=self._content, model=model, cost_usd=0.001,
            prompt_tokens=10, completion_tokens=5,
        )


def test_prompt_contains_node_type_similarity_and_json_instruction() -> None:
    messages = build_adjudication_messages(_pair(), snippets_a=["accepts requests"], snippets_b=["delivers"])
    assert messages[0]["role"] == "system"
    user = messages[1]["content"]
    assert "same real-world Service" in user
    assert "0.880" in user
    assert "Respond with JSON" in user
    assert "accepts requests" in user and "delivers" in user


def test_parse_verdict_valid() -> None:
    verdict = parse_verdict('{"same": true, "confidence": 0.9, "reasoning": "same service"}')
    assert verdict.same is True
    assert verdict.confidence == 0.9


def test_parse_verdict_strips_code_fence() -> None:
    verdict = parse_verdict('```json\n{"same": false, "confidence": 0.7, "reasoning": "different"}\n```')
    assert verdict.same is False


def test_parse_verdict_garbage_falls_back_to_no_merge() -> None:
    verdict = parse_verdict("not json at all")
    assert verdict.same is False
    assert verdict.confidence == 0.0


def test_parse_verdict_schema_violation_falls_back() -> None:
    # confidence out of range -> validation error -> safe no-merge.
    verdict = parse_verdict('{"same": true, "confidence": 5, "reasoning": "x"}')
    assert verdict.same is False


async def test_adjudicate_returns_parsed_verdict_and_accumulates_cost() -> None:
    client = _FakeClient(content='{"same": true, "confidence": 0.85, "reasoning": "ok"}')
    adj = Adjudicator(client)  # type: ignore[arg-type]
    verdict = await adj.adjudicate(_pair(), snippets_a=[], snippets_b=[])
    assert verdict.same is True
    assert adj.cost_usd == pytest.approx(0.001)
    assert client.calls[0]["model"] == "anthropic/claude-3.5-haiku"


async def test_adjudicate_call_failure_falls_back_to_no_merge() -> None:
    client = _FakeClient(raise_exc=RuntimeError("boom"))
    adj = Adjudicator(client)  # type: ignore[arg-type]
    verdict = await adj.adjudicate(_pair(), snippets_a=[], snippets_b=[])
    assert verdict.same is False


@pytest.mark.skipif(not os.getenv("OPENROUTER_API_KEY"), reason="no OPENROUTER_API_KEY")
async def test_real_adjudication_smoke() -> None:
    from app.extraction.client import OpenRouterClient

    client = OpenRouterClient()
    try:
        adj = Adjudicator(client)
        verdict = await adj.adjudicate(
            _pair(),
            snippets_a=["notifications-api accepts notification requests from clients"],
            snippets_b=["notification-worker consumes event-bus and delivers notifications"],
        )
        assert isinstance(verdict.same, bool)
    finally:
        await client.aclose()
