"""Verification node: extracts [evt:UUID] correctly, rejects fabricated ids, drives the
retry loop, gives up after the retry budget, and reconciles citations to inline refs."""

from __future__ import annotations

from app.agent.state import AgentState
from app.agent.verification import (
    _extract_inline_ids,
    route_after_verify,
    verify_provenance,
)

from .conftest import make_deps


def test_extract_inline_ids_dedupes_and_orders() -> None:
    text = "A [evt:x] then B [evt:y] then A again [evt:x] and spaced [evt: z ]."
    assert _extract_inline_ids(text) == ["x", "y", "z"]


async def test_passes_when_all_cited_ids_available() -> None:
    deps = make_deps(client=None)
    state: AgentState = {
        "answer": "Owned by team [evt:a] and person [evt:b].",
        "available_event_ids": ["a", "b", "c"],
    }
    out = await verify_provenance(state, deps=deps)

    assert out["verified"] is True
    assert out["citations"] == ["a", "b"]  # reconciled to inline refs (not the unused "c")
    assert out["error"] is None


async def test_fabricated_id_fails_and_increments_retry() -> None:
    deps = make_deps(client=None)
    state: AgentState = {
        "answer": "Owned by team [evt:a] and a made-up source [evt:zzz].",
        "available_event_ids": ["a", "b"],
        "retry_count": 0,
    }
    out = await verify_provenance(state, deps=deps)

    assert out["verified"] is False
    assert out["retry_count"] == 1
    assert "error" not in out  # retries remain, no give-up yet


async def test_no_citation_fails() -> None:
    deps = make_deps(client=None)
    out = await verify_provenance(
        {"answer": "No citations here.", "available_event_ids": ["a"], "retry_count": 0}, deps=deps
    )
    assert out["verified"] is False


async def test_gives_up_after_max_retries() -> None:
    deps = make_deps(client=None)  # default max_synthesis_retries = 2
    state: AgentState = {
        "answer": "Bad cite [evt:nope].",
        "available_event_ids": ["a"],
        "retry_count": 2,  # this failure makes it 3 > 2
    }
    out = await verify_provenance(state, deps=deps)

    assert out["verified"] is False
    assert out["retry_count"] == 3
    assert out["error"] == "provenance_failed"


def test_route_after_verify_branches() -> None:
    assert route_after_verify({"verified": True}) == "end"
    assert route_after_verify({"verified": False, "error": "provenance_failed"}) == "end"
    assert route_after_verify({"verified": False, "error": None}) == "synthesize_answer"
