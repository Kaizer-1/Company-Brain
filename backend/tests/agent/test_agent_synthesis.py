"""Synthesis node: prompt formatting, structured-output validation, strict-prompt-on-retry,
and graceful fallback when the LLM call fails."""

from __future__ import annotations

import json

from app.agent.state import AgentState
from app.agent.synthesis import synthesize_answer

from .conftest import FakeClient, make_deps


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


async def test_prompt_includes_question_tool_output_and_ids() -> None:
    client = FakeClient(content=_answer_json("Payments Team owns it [evt:uuid-a].", ["uuid-a"]))
    deps = make_deps(client)
    await synthesize_answer(_state(), deps=deps)

    sent = client.calls[0]["messages"][0]["content"]
    assert "who owns payments-api?" in sent
    assert "Payments Team" in sent  # tool_output serialised in
    assert "uuid-a" in sent and "uuid-b" in sent  # available ids listed


async def test_valid_answer_passed_through() -> None:
    client = FakeClient(content=_answer_json("It is owned by X [evt:uuid-a].", ["uuid-a"], "medium"))
    deps = make_deps(client)
    out = await synthesize_answer(_state(), deps=deps)

    assert out["answer"] == "It is owned by X [evt:uuid-a]."
    assert out["citations"] == ["uuid-a"]
    assert out["confidence"] == "medium"
    assert out["cost_usd"] > 0


async def test_empty_citations_rejected_then_graceful_fallback() -> None:
    # min_length=1 on citations fails validation -> AgentLLMError(schema) -> graceful fallback.
    client = FakeClient(content=_answer_json("An answer with no citations at all.", []))
    deps = make_deps(client)
    out = await synthesize_answer(_state(), deps=deps)

    assert out["citations"] == []
    assert out["confidence"] == "low"
    assert "couldn't compose" in out["answer"]


async def test_retry_uses_strict_prompt() -> None:
    client = FakeClient(content=_answer_json("Strict answer [evt:uuid-a].", ["uuid-a"]))
    deps = make_deps(client)
    await synthesize_answer(_state(retry_count=1), deps=deps)

    sent = client.calls[0]["messages"][0]["content"]
    assert "FAILED provenance verification" in sent  # marker unique to synthesis_strict.txt


async def test_llm_exception_falls_back_gracefully() -> None:
    client = FakeClient(raise_exc=RuntimeError("boom"))
    deps = make_deps(client)
    out = await synthesize_answer(_state(), deps=deps)

    assert out["citations"] == []
    assert out["confidence"] == "low"
