"""Tests for the graph Pydantic models (backend/app/schemas/graph.py).

For each model: valid data parses, domain-invalid data raises ValidationError.
Two parametrized suites assert the cross-cutting schema discipline — frozen
(mutation raises) and extra="forbid" (unknown field raises) — across every model.
"""

from datetime import datetime

import pytest
from pydantic import ValidationError

from app.schemas.graph import (
    Decision,
    Message,
    Node,
    Person,
    Relationship,
    RelationshipType,
    Service,
    System,
    Team,
)

NOW = datetime(2026, 5, 31, 12, 0, 0)

# One valid construction per model, reused by the parametrized discipline tests.
CASES = [
    (Node, {"id": "n-1", "source_event_ids": ["e1"], "created_at": NOW}),
    (Service, {"canonical_name": "payments-api", "source_event_ids": ["e1"], "created_at": NOW}),
    (System, {"canonical_name": "legacy-auth", "source_event_ids": ["e1"], "created_at": NOW}),
    (Team, {"canonical_name": "payments", "source_event_ids": ["e1"], "created_at": NOW}),
    (
        Person,
        {
            "canonical_id": "p-1",
            "display_name": "Alice Chen",
            "source_event_ids": ["e1"],
            "created_at": NOW,
        },
    ),
    (
        Decision,
        {
            "id": "d-1",
            "title": "Adopt event sourcing",
            "status": "active",
            "valid_from": NOW,
            "source_event_ids": ["e1"],
            "created_at": NOW,
        },
    ),
    (
        Message,
        {
            "source_id": "slack",
            "external_id": "123",
            "content": "we should reconsider that",
            "source_event_ids": ["e1"],
            "created_at": NOW,
        },
    ),
    (
        Relationship,
        {
            "type": "DEPENDS_ON",
            "source_id": "a",
            "target_id": "b",
            "confidence": 0.9,
            "extracted_by": "claude-opus-4-8",
            "created_at": NOW,
        },
    ),
]


# ---------------------------------------------------------------------------
# Cross-cutting discipline: frozen + extra="forbid" for every model.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model_cls, kwargs", CASES)
def test_frozen_blocks_mutation(model_cls: type, kwargs: dict) -> None:
    """Every model is immutable: assigning to a field raises ValidationError."""
    obj = model_cls(**kwargs)
    with pytest.raises(ValidationError):
        obj.created_at = datetime(2030, 1, 1)


@pytest.mark.parametrize("model_cls, kwargs", CASES)
def test_extra_field_forbidden(model_cls: type, kwargs: dict) -> None:
    """Every model rejects unknown fields rather than silently dropping them."""
    with pytest.raises(ValidationError):
        model_cls(**{**kwargs, "unexpected": "x"})


# ---------------------------------------------------------------------------
# Node (base)
# ---------------------------------------------------------------------------


def test_node_valid() -> None:
    node = Node(id="n-1", source_event_ids=["e1", "e2"], created_at=NOW)
    assert node.id == "n-1"
    assert node.source_event_ids == ["e1", "e2"]


def test_node_requires_provenance() -> None:
    with pytest.raises(ValidationError):
        Node(id="n-1", created_at=NOW)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


def test_service_valid_and_id_mirrors_name() -> None:
    svc = Service(
        canonical_name="payments-api",
        language="Go",
        tier="critical",
        source_event_ids=["e1"],
        created_at=NOW,
    )
    assert svc.canonical_name == "payments-api"
    assert svc.id == "payments-api"  # id mirrors the canonical name
    assert svc.status == "active"  # default lifecycle


def test_service_rejects_unknown_tier() -> None:
    with pytest.raises(ValidationError):
        Service(
            canonical_name="payments-api",
            tier="ultra",  # not in the Literal set
            source_event_ids=["e1"],
            created_at=NOW,
        )


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------


def test_system_valid_with_deprecated_status() -> None:
    sys = System(
        canonical_name="legacy-auth",
        status="deprecated",
        source_event_ids=["e1"],
        created_at=NOW,
    )
    assert sys.status == "deprecated"
    assert sys.id == "legacy-auth"


def test_system_rejects_unknown_status() -> None:
    with pytest.raises(ValidationError):
        System(
            canonical_name="legacy-auth",
            status="retired",  # not active|deprecated
            source_event_ids=["e1"],
            created_at=NOW,
        )


# ---------------------------------------------------------------------------
# Team
# ---------------------------------------------------------------------------


def test_team_valid_and_id_mirrors_name() -> None:
    team = Team(canonical_name="payments", source_event_ids=["e1"], created_at=NOW)
    assert team.id == "payments"


def test_team_requires_canonical_name() -> None:
    with pytest.raises(ValidationError):
        Team(source_event_ids=["e1"], created_at=NOW)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Person
# ---------------------------------------------------------------------------


def test_person_valid_and_id_mirrors_canonical_id() -> None:
    person = Person(
        canonical_id="p-1",
        display_name="Alice Chen",
        email="alice@company.com",
        source_event_ids=["e1"],
        created_at=NOW,
    )
    assert person.id == "p-1"
    assert person.email == "alice@company.com"


def test_person_requires_display_name() -> None:
    with pytest.raises(ValidationError):
        Person(canonical_id="p-1", source_event_ids=["e1"], created_at=NOW)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------


def test_decision_valid_open_validity_interval() -> None:
    decision = Decision(
        id="d-1",
        title="Adopt event sourcing",
        status="active",
        valid_from=NOW,
        source_event_ids=["e1"],
        created_at=NOW,
    )
    assert decision.valid_to is None  # None == still in force
    assert decision.status == "active"


def test_decision_rejects_unknown_status() -> None:
    with pytest.raises(ValidationError):
        Decision(
            id="d-1",
            title="Adopt event sourcing",
            status="draft",  # not active|superseded|rejected
            valid_from=NOW,
            source_event_ids=["e1"],
            created_at=NOW,
        )


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------


def test_message_valid_and_id_composed() -> None:
    msg = Message(
        source_id="slack",
        external_id="123",
        content="we should reconsider that",
        source_event_ids=["e1"],
        created_at=NOW,
    )
    assert msg.id == "slack:123"  # id composed from source_id:external_id


def test_message_requires_content() -> None:
    with pytest.raises(ValidationError):
        Message(
            source_id="slack",
            external_id="123",
            source_event_ids=["e1"],
            created_at=NOW,
        )  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Relationship
# ---------------------------------------------------------------------------


def test_relationship_valid_coerces_type_to_enum() -> None:
    rel = Relationship(
        type="DEPENDS_ON",
        source_id="checkout",
        target_id="payments-api",
        confidence=0.82,
        extracted_by="claude-opus-4-8",
        created_at=NOW,
    )
    assert rel.type is RelationshipType.DEPENDS_ON
    assert rel.properties is None


def test_relationship_rejects_confidence_out_of_range() -> None:
    with pytest.raises(ValidationError):
        Relationship(
            type="DEPENDS_ON",
            source_id="a",
            target_id="b",
            confidence=1.5,  # outside [0, 1]
            extracted_by="claude-opus-4-8",
            created_at=NOW,
        )


def test_relationship_rejects_unknown_type() -> None:
    with pytest.raises(ValidationError):
        Relationship(
            type="ENTANGLES",  # not in the closed RelationshipType set
            source_id="a",
            target_id="b",
            confidence=0.5,
            extracted_by="claude-opus-4-8",
            created_at=NOW,
        )
