"""Tests that each failure mode is classified from a hand-built mismatch."""

from app.eval.failure_modes import FailureMode, classify
from app.eval.ground_truth import ExpectedEntity, ExpectedRelationship, GroundTruth
from app.eval.matcher import EntityMention, MatchedExtraction, RelationshipMention
from app.schemas.graph import RelationshipType


def _gt() -> GroundTruth:
    return GroundTruth(
        entities=frozenset(
            {
                ExpectedEntity("Service", "auth-service"),
                ExpectedEntity("System", "legacy-auth"),
                ExpectedEntity("Person", "alice-chen"),
            }
        ),
        relationships=frozenset(
            {
                ExpectedRelationship(RelationshipType.DEPENDS_ON, "payments-api", "auth-service"),
                ExpectedRelationship(RelationshipType.APPROVED_BY, "D-0006", "alice-chen"),
            }
        ),
    )


def _ent(type_: str, key: str, raw: str, conf: float = 0.9) -> EntityMention:
    return EntityMention(
        type=type_,  # type: ignore[arg-type]
        canonical_key=key,
        raw_name=raw,
        confidence=conf,
        evidence_quote=f"...{raw}...",
        event_id="evt-1",
    )


def _rel(type_: RelationshipType, src: str, tgt: str, conf: float = 0.9) -> RelationshipMention:
    return RelationshipMention(
        type=type_,
        source_key=src,
        target_key=tgt,
        raw_source=src,
        raw_target=tgt,
        confidence=conf,
        evidence_quote="...",
        event_id="evt-1",
    )


def _matched() -> MatchedExtraction:
    return MatchedExtraction(
        entity_mentions=(
            _ent("Service", "auth-service", "auth-service"),  # correct
            _ent("Service", "auth-service", "AuthSvc"),  # alias-not-merged second form
            _ent("Service", "legacy-auth", "legacy-auth", conf=0.4),  # wrong type (expected System)
            _ent("Service", "ghost-service", "ghost", conf=0.3),  # spurious
            # alice-chen omitted -> missed entity
        ),
        relationship_mentions=(
            _rel(RelationshipType.DEPENDS_ON, "payments-api", "auth-service"),  # correct
            _rel(RelationshipType.OWNED_BY, "D-0006", "alice-chen", conf=0.4),  # wrong rel type
            _rel(RelationshipType.DEPENDS_ON, "ghost-a", "ghost-b", conf=0.3),  # spurious
        ),
    )


def test_each_failure_mode_classified() -> None:
    b = classify(_matched(), _gt())
    assert b.count(FailureMode.MISSED_ENTITY) == 1
    assert b.count(FailureMode.SPURIOUS_ENTITY) == 1
    assert b.count(FailureMode.WRONG_ENTITY_TYPE) == 1
    assert b.count(FailureMode.MISSED_RELATIONSHIP) == 0
    assert b.count(FailureMode.SPURIOUS_RELATIONSHIP) == 1
    assert b.count(FailureMode.WRONG_RELATIONSHIP_TYPE) == 1
    assert b.count(FailureMode.ALIAS_NOT_MERGED) >= 1


def test_examples_carry_evidence() -> None:
    b = classify(_matched(), _gt())
    spurious = b.examples[FailureMode.SPURIOUS_ENTITY]
    assert spurious
    assert "ghost" in spurious[0].evidence_quote


def test_confidence_calibration_ok_when_correct_more_confident() -> None:
    b = classify(_matched(), _gt())
    # Correct extractions (0.9) are more confident than wrong ones (0.3-0.4).
    assert not b.confidence.miscalibrated
    assert b.confidence.mean_confidence_correct > b.confidence.mean_confidence_incorrect


def test_perfect_extraction_has_no_failures() -> None:
    gt = _gt()
    perfect = MatchedExtraction(
        entity_mentions=tuple(
            _ent(e.type, e.canonical_name, e.canonical_name) for e in gt.entities
        ),
        relationship_mentions=tuple(
            _rel(r.type, r.source_canonical_name, r.target_canonical_name)
            for r in gt.relationships
        ),
    )
    b = classify(perfect, gt)
    assert sum(b.counts.values()) == 0
