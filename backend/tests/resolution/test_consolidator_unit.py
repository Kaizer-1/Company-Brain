"""Unit tests for the Decision consolidator's pure decision logic (Phase 3B; ADR 0017)."""

from __future__ import annotations

from app.models.enums import NodeType
from app.resolution.consolidator import (
    CONTENT_SIM_THRESHOLD,
    _is_formal_id,
    decision_embedding_input,
    should_consolidate,
)
from app.resolution.models import ResolvableNode


def _decision(node_id: str, *, title: str = "", body: str = "", created_at: str | None = None) -> ResolvableNode:
    props: dict[str, object] = {"title": title, "body": body}
    if created_at is not None:
        props["created_at"] = created_at
    return ResolvableNode(node_type=NodeType.Decision, node_id=node_id, properties=props)


def test_is_formal_id() -> None:
    assert _is_formal_id("D-0006")
    assert _is_formal_id("D-006")
    assert not _is_formal_id("the-jwt-cutover-decision")


def test_embedding_input_prefers_title_body() -> None:
    node = _decision("D-0010", title="Move to JWT", body="stateless tokens")
    assert decision_embedding_input(node) == "Move to JWT stateless tokens"


def test_embedding_input_falls_back_to_id() -> None:
    assert decision_embedding_input(_decision("D-0010")) == "D-0010"


def test_two_distinct_formal_ids_never_consolidate() -> None:
    # Authority guard protects KQ4: D-0007 and D-0008 must stay distinct even at sim 0.99.
    a = _decision("D-0007", title="Enforce mTLS")
    b = _decision("D-0008", title="Rotate keys")
    assert not should_consolidate(a, b, 0.99)


def test_paraphrase_consolidates_above_threshold() -> None:
    a = _decision("D-0010", title="Move auth-service to stateless JWT")
    b = _decision("the-jwt-cutover", title="Move auth-service to stateless JWT")
    assert should_consolidate(a, b, CONTENT_SIM_THRESHOLD)
    assert not should_consolidate(a, b, CONTENT_SIM_THRESHOLD - 0.01)


def test_proximity_gate_blocks_distant_decisions() -> None:
    a = _decision("d-a", title="same text", created_at="2026-01-01T00:00:00+00:00")
    b = _decision("d-b", title="same text", created_at="2026-05-01T00:00:00+00:00")  # ~120d apart
    assert not should_consolidate(a, b, 0.99)
