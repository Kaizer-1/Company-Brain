"""Tests for the adversarial planted-case inventory.

Test-first design for the part that matters (ADR 0011): these assert every planted case
ties to a killer query and that the inventory matches what docs/design/synthetic-company.md
promises — BEFORE the generator is written. The generator's job is then to satisfy these.
"""

from app.synthetic import narrative as nv
from app.synthetic.company import COMPANY

_VALID_KQS = {"KQ1", "KQ2", "KQ3", "KQ4"}


def test_every_planted_case_ties_to_a_killer_query() -> None:
    cases = nv.all_planted_cases()
    assert cases, "there must be planted cases"
    for case in cases:
        kq = getattr(case, "kq", None)
        assert kq in _VALID_KQS, f"{type(case).__name__} has invalid kq {kq!r}"


def test_planted_case_category_counts_match_design_doc() -> None:
    # §6 of the design doc: 6 alias groups (3 people + 3 services), 1 look-alike pair,
    # 1 deprecation chain, 1 contradiction, 1 dependency graph, 1 change timeline,
    # 1 ownership ambiguity, 2 stale docs, 1 departure.
    assert len(nv.ALIAS_GROUPS) == 6
    assert len(nv.LOOK_ALIKE_PAIRS) == 1
    assert len(nv.DEPRECATION_CHAINS) == 1
    assert len(nv.CONTRADICTION_PAIRS) == 1
    assert len(nv.CHANGE_TIMELINES) == 1
    assert len(nv.OWNERSHIP_AMBIGUITIES) == 1
    assert len(nv.STALE_DOCS) == 2
    assert len(nv.DEPARTURE_TRANSFERS) == 1


def test_three_people_and_three_services_have_alias_groups() -> None:
    people = [g for g in nv.ALIAS_GROUPS if g.entity_kind == "person"]
    services = [g for g in nv.ALIAS_GROUPS if g.entity_kind == "service"]
    assert len(people) == 3
    assert len(services) == 3
    # Each trap entity must carry at least three distinct surface forms.
    for g in nv.ALIAS_GROUPS:
        assert len(set(g.surface_forms)) >= 3


def test_alias_groups_reference_real_entities() -> None:
    person_ids = {p.canonical_id for p in COMPANY.people}
    service_names = {s.canonical_name for s in COMPANY.services}
    for g in nv.ALIAS_GROUPS:
        if g.entity_kind == "person":
            assert g.canonical in person_ids
        else:
            assert g.canonical in service_names


def test_person_alias_forms_are_consistent_with_company() -> None:
    """Alias surface forms must not drift from the company definition."""
    for g in nv.ALIAS_GROUPS:
        if g.entity_kind != "person":
            continue
        person = COMPANY.person(g.canonical)
        allowed = {
            person.display_name,
            person.handle,
            person.email,
            *( (person.nickname,) if person.nickname else () ),
            *( (person.former_handle,) if person.former_handle else () ),
            *person.title_refs,
        }
        for form in g.surface_forms:
            assert form in allowed, f"{form!r} not a known form for {g.canonical}"


def test_service_alias_forms_are_consistent_with_company() -> None:
    for g in nv.ALIAS_GROUPS:
        if g.entity_kind != "service":
            continue
        svc = COMPANY.service(g.canonical)
        allowed = {svc.canonical_name, *svc.aliases}
        if svc.former_name is not None:
            allowed.add(svc.former_name)
        for form in g.surface_forms:
            assert form in allowed, f"{form!r} not a known form for {g.canonical}"


def test_look_alike_pair_are_distinct_real_services() -> None:
    service_names = {s.canonical_name for s in COMPANY.services}
    for pair in nv.LOOK_ALIKE_PAIRS:
        assert pair.service_a != pair.service_b
        assert pair.service_a in service_names
        assert pair.service_b in service_names


def test_deprecation_chain_is_a_real_4_hop_path() -> None:
    chain = nv.DEPRECATION_CHAINS[0]
    decision = COMPANY.decision(chain.decision_id)
    # Decision DEPRECATES the system.
    assert decision.deprecates == chain.deprecated_system
    # The dependent service actually DEPENDS_ON the deprecated system.
    edges = nv.DEPENDENCY_GRAPH.edges
    assert any(
        e.upstream == chain.dependent_service and e.downstream == chain.deprecated_system
        for e in edges
    )
    # The service is owned by the named team, whose lead is the named owner.
    svc = COMPANY.service(chain.dependent_service)
    assert svc.owning_team == chain.owning_team
    assert COMPANY.team(chain.owning_team).lead == chain.owner_person
    # Secondary dependents also depend on the deprecated system.
    for sec in chain.secondary_dependents:
        assert any(
            e.upstream == sec and e.downstream == chain.deprecated_system for e in edges
        )


def test_contradiction_pair_decision_is_active_and_older_than_discussion() -> None:
    pair = nv.CONTRADICTION_PAIRS[0]
    decision = COMPANY.decision(pair.decision_id)
    assert decision.status == "active"
    # The discussion must be recent (last month) and the decision older than it.
    assert pair.discussion_age_days <= 30
    assert pair.decision_age_days > pair.discussion_age_days
    for handle in pair.contradicting_handles:
        assert any(p.handle == handle for p in COMPANY.people)


def test_dependency_graph_has_depth_at_least_4() -> None:
    assert nv.max_dependency_depth(nv.DEPENDENCY_GRAPH) >= 4


def test_named_deep_chain_edges_all_exist_and_is_depth_4() -> None:
    chain = nv.DEPENDENCY_GRAPH.deep_chain
    assert len(chain) >= 5  # 5 nodes = 4 edges
    edges = {(e.upstream, e.downstream) for e in nv.DEPENDENCY_GRAPH.edges}
    for upstream, downstream in zip(chain, chain[1:], strict=False):
        assert (upstream, downstream) in edges


def test_blast_radius_is_at_least_10_services() -> None:
    radius = nv.blast_radius(nv.DEPENDENCY_GRAPH, nv.DEPENDENCY_GRAPH.seed_service)
    assert len(radius) >= 10
    # The seed itself is not in its own blast radius.
    assert nv.DEPENDENCY_GRAPH.seed_service not in radius


def test_seed_has_at_least_4_direct_dependents() -> None:
    direct = nv.dependents_of(nv.DEPENDENCY_GRAPH, nv.DEPENDENCY_GRAPH.seed_service)
    assert len(direct) >= 4


def test_dependency_edges_reference_real_entities() -> None:
    service_names = {s.canonical_name for s in COMPANY.services}
    system_names = {s.canonical_name for s in COMPANY.systems}
    for e in nv.DEPENDENCY_GRAPH.edges:
        assert e.upstream in service_names, f"{e.upstream} is not a service"
        if e.downstream_is_system:
            assert e.downstream in system_names
        else:
            assert e.downstream in service_names


def test_change_timeline_has_4_in_quarter_decisions_and_a_supersession() -> None:
    timeline = nv.CHANGE_TIMELINES[0]
    in_quarter = [
        d
        for d in (COMPANY.decision(i) for i in timeline.decision_ids)
        if d.age_days <= 90 and timeline.subject in d.about
    ]
    assert len(in_quarter) >= 4, "KQ4 needs >=4 auth decisions in the last quarter"
    superseding, superseded = timeline.supersession
    assert COMPANY.decision(superseding).supersedes == superseded
    assert COMPANY.decision(superseded).status == "superseded"


def test_ownership_ambiguity_resolves_to_authoritative_team() -> None:
    amb = nv.OWNERSHIP_AMBIGUITIES[0]
    svc = COMPANY.service(amb.service)
    # The catalog/authoritative owner wins; the contested team is a different real team.
    assert svc.owning_team == amb.authoritative_team
    assert amb.contested_team != amb.authoritative_team
    assert amb.contested_team in {t.canonical_name for t in COMPANY.teams}


def test_stale_docs_are_contradicted_by_real_decisions() -> None:
    decision_ids = {d.id for d in COMPANY.decisions}
    for doc in nv.STALE_DOCS:
        assert doc.contradicted_by in decision_ids
        assert doc.age_days > 90  # stale = old


def test_departure_transfer_references_real_people_and_asset() -> None:
    transfer = nv.DEPARTURE_TRANSFERS[0]
    assert COMPANY.person(transfer.person_left).left_company
    assert not COMPANY.person(transfer.successor).left_company
    svc = COMPANY.service(transfer.asset)
    # Current owner is the successor (post-transfer state).
    assert svc.owner_person == transfer.successor
