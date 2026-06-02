"""Validation tests for the LLM-output Pydantic models."""

import pytest
from pydantic import ValidationError

from app.extraction.models import (
    ExtractedEntity,
    ExtractedRelationship,
    ExtractionResult,
)
from app.schemas.graph import RelationshipType


def test_valid_entity_parses() -> None:
    ent = ExtractedEntity(
        type="Service",
        canonical_name="auth-service",
        evidence_quote="auth-service is the new auth",
        confidence=0.9,
    )
    assert ent.type == "Service"
    assert ent.properties == {}


def test_entity_rejects_unknown_type() -> None:
    with pytest.raises(ValidationError):
        ExtractedEntity(
            type="Repository",  # type: ignore[arg-type]
            canonical_name="x",
            evidence_quote="x",
            confidence=0.5,
        )


def test_entity_requires_evidence_quote() -> None:
    with pytest.raises(ValidationError):
        ExtractedEntity(type="Person", canonical_name="Al", evidence_quote="", confidence=0.5)


def test_entity_rejects_blank_canonical_name() -> None:
    with pytest.raises(ValidationError):
        ExtractedEntity(type="Person", canonical_name="", evidence_quote="x", confidence=0.5)


@pytest.mark.parametrize("bad", [-0.1, 1.1, 2.0])
def test_confidence_must_be_in_unit_interval(bad: float) -> None:
    with pytest.raises(ValidationError):
        ExtractedEntity(
            type="Person", canonical_name="Al", evidence_quote="x", confidence=bad
        )


def test_extra_field_forbidden() -> None:
    with pytest.raises(ValidationError):
        ExtractedEntity.model_validate(
            {
                "type": "Person",
                "canonical_name": "Al",
                "evidence_quote": "x",
                "confidence": 0.5,
                "surprise": "boom",
            }
        )


def test_relationship_parses_with_enum_type() -> None:
    rel = ExtractedRelationship(
        type=RelationshipType.DEPENDS_ON,
        source_canonical_name="checkout-service",
        target_canonical_name="payments-api",
        evidence_quote="checkout depends on payments-api",
        confidence=0.8,
    )
    assert rel.type is RelationshipType.DEPENDS_ON


def test_relationship_rejects_unknown_type() -> None:
    with pytest.raises(ValidationError):
        ExtractedRelationship(
            type="CONSUMES",  # type: ignore[arg-type]
            source_canonical_name="a",
            target_canonical_name="b",
            evidence_quote="x",
            confidence=0.5,
        )


def test_empty_result_is_valid() -> None:
    result = ExtractionResult()
    assert result.entities == []
    assert result.relationships == []
