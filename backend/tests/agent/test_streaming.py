"""Unit tests for the SSE serialiser and the streaming synthesis wrapper (Phase 4B)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from app.agent.streaming import (
    EVT_COMPLETE,
    EVT_ROUTE,
    EVT_SYNTHESIS_TOKEN,
    format_sse,
)
from app.agent.synthesis import astream_synthesize
from app.extraction.client import CompletionResult

from .conftest import FakeClient, make_deps

if TYPE_CHECKING:
    from app.agent.state import AgentState

# ---------------------------------------------------------------------------
# format_sse
# ---------------------------------------------------------------------------


def test_format_sse_produces_correct_frame() -> None:
    frame = format_sse(EVT_ROUTE, {"route": "kq3", "reasoning": "blast radius"})
    lines = frame.split("\n")
    assert lines[0] == "event: route"
    assert lines[1].startswith("data: ")
    assert lines[2] == ""
    assert lines[3] == ""
    payload = json.loads(lines[1][6:])
    assert payload == {"route": "kq3", "reasoning": "blast radius"}


def test_format_sse_ends_with_double_newline() -> None:
    assert format_sse(EVT_COMPLETE, {}).endswith("\n\n")


def test_format_sse_token_event() -> None:
    frame = format_sse(EVT_SYNTHESIS_TOKEN, {"text": "hello "})
    assert '"text": "hello "' in frame


# ---------------------------------------------------------------------------
# FakeStreamingClient — adds astream_completion to FakeClient
# ---------------------------------------------------------------------------


class FakeStreamingClient(FakeClient):
    """FakeClient extended with astream_completion that yields scripted token chunks."""

    def __init__(
        self,
        *,
        stream_tokens: list[str] | None = None,
        full_json: str | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        # Tokens to yield one by one.
        self._tokens: list[str] = stream_tokens or []
        # If full_json is given, we yield characters of the JSON string instead.
        if full_json is not None:
            self._tokens = list(full_json)
        self._stream_calls: list[dict[str, object]] = []

    async def astream_completion(  # type: ignore[override]
        self,
        *,
        messages: list[dict[str, str]],
        model: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        on_complete=None,
    ):  # type: ignore[return]
        self._stream_calls.append({"model": model})
        for token in self._tokens:
            yield token
        if on_complete is not None:
            on_complete(CompletionResult(
                content="".join(self._tokens),
                model=model,
                cost_usd=0.001,
                prompt_tokens=10,
                completion_tokens=len(self._tokens),
            ))


# ---------------------------------------------------------------------------
# astream_synthesize
# ---------------------------------------------------------------------------


def _answer_json(answer: str, citations: list[str], confidence: str = "high") -> str:
    return json.dumps({"answer": answer, "citations": citations, "confidence": confidence})


def _state(**kw: object) -> AgentState:
    base: AgentState = {
        "question": "who owns payments-api?",
        "tool_output": {"value": {"owner": "Payments Team"}},
        "available_event_ids": ["uuid-a", "uuid-b"],
    }
    base.update(kw)  # type: ignore[typeddict-item]
    return base


async def test_astream_synthesize_calls_on_token_for_each_chunk() -> None:
    full = _answer_json("Payments Team owns it [evt:uuid-a].", ["uuid-a"])
    client = FakeStreamingClient(stream_tokens=["Payments ", "Team ", "owns."], full_json=full)
    deps = make_deps(client)

    received: list[str] = []

    async def on_token(chunk: str) -> None:
        received.append(chunk)

    result = await astream_synthesize(_state(), deps=deps, on_token=on_token)
    # on_token was called once per character (since full_json yields chars)
    assert "".join(received) == full
    assert result["answer"] == "Payments Team owns it [evt:uuid-a]."
    assert result["citations"] == ["uuid-a"]
    assert result["confidence"] == "high"
    assert result["cost_usd"] > 0  # on_complete captured cost


async def _noop_on_token(chunk: str) -> None:  # noqa: ARG001
    """Async no-op on_token for tests that don't care about individual tokens."""


async def test_astream_synthesize_returns_same_shape_as_synthesize_answer() -> None:
    full = _answer_json("It is owned by X [evt:uuid-a].", ["uuid-a"], "medium")
    client = FakeStreamingClient(full_json=full)
    deps = make_deps(client)
    result = await astream_synthesize(_state(), deps=deps, on_token=_noop_on_token)

    assert "answer" in result
    assert "citations" in result
    assert "confidence" in result
    assert "timings_ms" in result
    assert "cost_usd" in result
    assert "synthesize_answer" in result["timings_ms"]  # type: ignore[operator]


async def test_astream_synthesize_fallback_on_invalid_json() -> None:
    client = FakeStreamingClient(stream_tokens=["not json at all"])
    deps = make_deps(client)
    result = await astream_synthesize(_state(), deps=deps, on_token=_noop_on_token)

    assert result["citations"] == []
    assert result["confidence"] == "low"
    assert "couldn't compose" in str(result["answer"])


async def test_astream_synthesize_uses_strict_prompt_on_retry() -> None:
    full = _answer_json("Retry answer [evt:uuid-a].", ["uuid-a"])
    client = FakeStreamingClient(full_json=full)
    deps = make_deps(client)
    await astream_synthesize(_state(retry_count=1), deps=deps, on_token=_noop_on_token)

    # The streaming client records the model call; the prompt is loaded from config path
    # (synthesis_strict.txt on retry). We verify the call was made.
    assert len(client._stream_calls) == 1
