"""Phase 4C — verification behaviour for structural routes (ADR 0030).

The citation check is skipped only when the route is structural AND no events were citable
(e.g. an aggregate). A structural tool that DID return events is still held to the normal
grounding contract — a fabricated citation must fail.
"""

from __future__ import annotations

import pytest

from app.agent.verification import verify_provenance

from .conftest import FakeClient, make_deps

pytestmark = pytest.mark.asyncio


async def test_structural_no_events_skips_citation_check() -> None:
    deps = make_deps(FakeClient())
    state = {
        "route": "aggregate",
        "answer": "There are 9 active decisions in the graph.",  # no [evt:] markers
        "available_event_ids": [],
    }
    out = await verify_provenance(state, deps=deps)
    assert out["verified"] is True
    assert out["citations"] == []
    assert out["error"] is None


async def test_structural_with_events_still_requires_grounding() -> None:
    deps = make_deps(FakeClient())
    # enumerate returned events, but the answer cites an id NOT in the available set.
    state = {
        "route": "enumerate",
        "answer": "The team owns payments-api [evt:fabricated-id].",
        "available_event_ids": ["real-1", "real-2"],
        "retry_count": 0,
    }
    out = await verify_provenance(state, deps=deps)
    assert out["verified"] is False
    assert out["retry_count"] == 1


async def test_structural_with_events_accepts_valid_citation() -> None:
    deps = make_deps(FakeClient())
    state = {
        "route": "enumerate",
        "answer": "The people include Alice [evt:real-1] and Bob [evt:real-2].",
        "available_event_ids": ["real-1", "real-2"],
    }
    out = await verify_provenance(state, deps=deps)
    assert out["verified"] is True
    assert set(out["citations"]) == {"real-1", "real-2"}  # type: ignore[arg-type]


async def test_non_structural_empty_events_is_not_skipped() -> None:
    # A search route with no available events and no citation must NOT be auto-verified.
    deps = make_deps(FakeClient())
    state = {
        "route": "search",
        "answer": "Some ungrounded claim.",
        "available_event_ids": [],
        "retry_count": 0,
    }
    out = await verify_provenance(state, deps=deps)
    assert out["verified"] is False
