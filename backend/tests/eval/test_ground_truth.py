"""Tests for ground-truth derivation from the synthetic company."""

from app.eval.ground_truth import build_ground_truth
from app.schemas.graph import RelationshipType
from app.synthetic import narrative as nv
from app.synthetic.company import COMPANY


def test_every_company_entity_that_appears_is_in_ground_truth() -> None:
    gt = build_ground_truth()
    person_keys = {e.canonical_name for e in gt.entities if e.type == "Person"}
    service_keys = {e.canonical_name for e in gt.entities if e.type == "Service"}
    system_keys = {e.canonical_name for e in gt.entities if e.type == "System"}
    team_keys = {e.canonical_name for e in gt.entities if e.type == "Team"}
    decision_keys = {e.canonical_name for e in gt.entities if e.type == "Decision"}

    assert person_keys == {p.canonical_id for p in COMPANY.people}
    assert service_keys == {s.canonical_name for s in COMPANY.services}
    assert system_keys == {s.canonical_name for s in COMPANY.systems}
    assert team_keys == {t.canonical_name for t in COMPANY.teams}
    assert decision_keys == {d.id for d in COMPANY.decisions}


def test_entity_counts_match_locked_company() -> None:
    gt = build_ground_truth()
    assert len(gt.entities) == 13 + 12 + 5 + 5 + 10  # people+services+systems+teams+decisions


def test_no_spurious_entities() -> None:
    gt = build_ground_truth()
    all_known = (
        {p.canonical_id for p in COMPANY.people}
        | {s.canonical_name for s in COMPANY.services}
        | {s.canonical_name for s in COMPANY.systems}
        | {t.canonical_name for t in COMPANY.teams}
        | {d.id for d in COMPANY.decisions}
    )
    for e in gt.entities:
        assert e.canonical_name in all_known


def test_depends_on_matches_dependency_graph() -> None:
    gt = build_ground_truth()
    dep_edges = {
        (r.source_canonical_name, r.target_canonical_name)
        for r in gt.relationships
        if r.type == RelationshipType.DEPENDS_ON
    }
    expected = {(e.upstream, e.downstream) for e in nv.DEPENDENCY_GRAPH.edges}
    assert dep_edges == expected


def test_deprecates_edge_present() -> None:
    gt = build_ground_truth()
    deprecates = {
        (r.source_canonical_name, r.target_canonical_name)
        for r in gt.relationships
        if r.type == RelationshipType.DEPRECATES
    }
    assert ("D-0006", "legacy-auth") in deprecates


def test_approved_by_counts_match_decisions() -> None:
    gt = build_ground_truth()
    approved = [r for r in gt.relationships if r.type == RelationshipType.APPROVED_BY]
    expected_count = sum(len(d.approvers) for d in COMPANY.decisions)
    assert len(approved) == expected_count


def test_owned_by_includes_person_owner_for_billing() -> None:
    gt = build_ground_truth()
    owned = {
        (r.source_canonical_name, r.target_canonical_name)
        for r in gt.relationships
        if r.type == RelationshipType.OWNED_BY
    }
    assert ("billing-v2", "payments") in owned  # team owner
    assert ("billing-v2", "carol-nwosu") in owned  # individual owner (departure transfer)


def test_member_of_excludes_teamless_person() -> None:
    gt = build_ground_truth()
    members = {r.source_canonical_name for r in gt.relationships if r.type == RelationshipType.MEMBER_OF}
    assert "jordan-wells" not in members  # Director, no team
    assert "alice-chen" in members


def test_ground_truth_is_deterministic() -> None:
    assert build_ground_truth() == build_ground_truth()
