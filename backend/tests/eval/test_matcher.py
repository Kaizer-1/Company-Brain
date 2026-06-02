"""Tests for alias-tolerant canonicalisation and matching."""

from app.eval.matcher import SurfaceIndex, canonicalize_extractions, normalize
from app.extraction.models import ExtractedEntity, ExtractedRelationship, ExtractionResult
from app.schemas.graph import RelationshipType


def _index() -> SurfaceIndex:
    return SurfaceIndex()


def test_normalize_basics() -> None:
    assert normalize("@alice") == "alice"
    assert normalize("Alice Chen") == "alice-chen"
    assert normalize("  the Auth Service ") == "the-auth-service"


def test_exact_name_matches_itself() -> None:
    idx = _index()
    assert idx.entity_key("Service", "auth-service") == "auth-service"


def test_person_aliases_collapse() -> None:
    idx = _index()
    for form in ("Alice Chen", "@alice", "alice.chen@northwind.io", "Al"):
        assert idx.entity_key("Person", form) == "alice-chen"


def test_service_alias_and_rename_collapse() -> None:
    idx = _index()
    assert idx.entity_key("Service", "AuthSvc") == "auth-service"
    assert idx.entity_key("Service", "the auth service") == "auth-service"
    # billing-v2 was renamed from legacy-billing; both must resolve to billing-v2.
    assert idx.entity_key("Service", "legacy-billing") == "billing-v2"


def test_title_reference_resolves_to_person() -> None:
    idx = _index()
    assert idx.entity_key("Person", "the payments lead") == "diego-ramirez"


def test_type_scoping_disambiguates_payments() -> None:
    idx = _index()
    # "payments" is a Service alias (payments-api) AND the Team canonical name.
    assert idx.entity_key("Service", "payments") == "payments-api"
    assert idx.entity_key("Team", "Payments") == "payments"


def test_unknown_name_falls_back_to_normalized() -> None:
    idx = _index()
    assert idx.entity_key("Service", "Totally Made Up") == "totally-made-up"


def test_endpoint_resolution_uses_schema_candidate_types() -> None:
    idx = _index()
    # OWNED_BY target candidate types are (Person, Team); "Payments" -> the team.
    src, tgt = (
        idx.endpoint_key("billing-v2", ("Service", "System")),
        idx.endpoint_key("Payments", ("Person", "Team")),
    )
    assert (src, tgt) == ("billing-v2", "payments")


def test_canonicalize_extractions_collapses_aliases_into_one_key() -> None:
    result = ExtractionResult(
        entities=[
            ExtractedEntity(type="Service", canonical_name="AuthSvc", evidence_quote="x", confidence=0.9),
            ExtractedEntity(type="Service", canonical_name="the auth service", evidence_quote="x", confidence=0.9),
        ],
        relationships=[
            ExtractedRelationship(
                type=RelationshipType.DEPENDS_ON,
                source_canonical_name="payments",
                target_canonical_name="AuthSvc",
                evidence_quote="x",
                confidence=0.9,
            )
        ],
    )
    matched = canonicalize_extractions([("evt-1", result)])
    # Two raw surface forms collapse to one canonical (Service, auth-service).
    assert matched.entity_keys == {("Service", "auth-service")}
    assert matched.relationship_keys == {
        (RelationshipType.DEPENDS_ON, "payments-api", "auth-service")
    }
