"""Shape tests for the locked company definition.

These assert the company matches the counts and identities promised in
docs/design/synthetic-company.md. Their job is to catch accidental scope drift — if
someone adds a 13th service or renames a team, a test fails loudly rather than the
design doc silently going stale.
"""

from app.synthetic.company import COMPANY, HANDLE_CHANGE_AGE_DAYS, REFERENCE_NOW


def test_entity_counts_match_design_doc_bounds() -> None:
    assert 10 <= len(COMPANY.people) <= 15
    assert 4 <= len(COMPANY.teams) <= 6
    assert 8 <= len(COMPANY.services) <= 12
    assert 4 <= len(COMPANY.systems) <= 6
    assert 6 <= len(COMPANY.decisions) <= 10


def test_exact_counts_are_locked() -> None:
    # Exact locked numbers from the design doc — change deliberately, with the doc.
    assert len(COMPANY.people) == 13
    assert len(COMPANY.teams) == 5
    assert len(COMPANY.services) == 12
    assert len(COMPANY.systems) == 5
    assert len(COMPANY.decisions) == 10


def test_all_canonical_ids_unique() -> None:
    assert len({p.canonical_id for p in COMPANY.people}) == len(COMPANY.people)
    assert len({t.canonical_name for t in COMPANY.teams}) == len(COMPANY.teams)
    assert len({s.canonical_name for s in COMPANY.services}) == len(COMPANY.services)
    assert len({s.canonical_name for s in COMPANY.systems}) == len(COMPANY.systems)
    assert len({d.id for d in COMPANY.decisions}) == len(COMPANY.decisions)


def test_service_and_system_namespaces_do_not_collide() -> None:
    service_names = {s.canonical_name for s in COMPANY.services}
    system_names = {s.canonical_name for s in COMPANY.systems}
    assert service_names.isdisjoint(system_names)


def test_every_person_team_is_a_real_team_or_none() -> None:
    team_names = {t.canonical_name for t in COMPANY.teams}
    for p in COMPANY.people:
        assert p.team is None or p.team in team_names


def test_every_team_lead_is_a_member_of_that_team() -> None:
    for t in COMPANY.teams:
        lead = COMPANY.person(t.lead)
        assert lead.team == t.canonical_name


def test_every_service_and_system_owned_by_real_team() -> None:
    team_names = {t.canonical_name for t in COMPANY.teams}
    for s in COMPANY.services:
        assert s.owning_team in team_names
    for s in COMPANY.systems:
        assert s.owning_team in team_names


def test_individual_service_owner_is_a_real_person() -> None:
    person_ids = {p.canonical_id for p in COMPANY.people}
    for s in COMPANY.services:
        if s.owner_person is not None:
            assert s.owner_person in person_ids


def test_decision_references_resolve() -> None:
    person_ids = {p.canonical_id for p in COMPANY.people}
    entity_names = {s.canonical_name for s in COMPANY.services} | {
        s.canonical_name for s in COMPANY.systems
    }
    decision_ids = {d.id for d in COMPANY.decisions}
    for d in COMPANY.decisions:
        assert d.approvers, f"{d.id} has no approver"
        for approver in d.approvers:
            assert approver in person_ids
        for subject in d.about:
            assert subject in entity_names
        if d.deprecates is not None:
            assert d.deprecates in {s.canonical_name for s in COMPANY.systems}
        if d.supersedes is not None:
            assert d.supersedes in decision_ids


def test_at_least_one_deprecated_system() -> None:
    assert any(s.status == "deprecated" for s in COMPANY.systems)


def test_exactly_one_departed_person() -> None:
    departed = [p for p in COMPANY.people if p.left_company]
    assert len(departed) == 1
    assert departed[0].canonical_id == "bob-tanaka"


def test_handle_change_is_age_dependent() -> None:
    ben = COMPANY.person("ben-smith")
    assert ben.former_handle == "@bsmith"
    # Old events use the former handle; recent events use the current one.
    assert ben.handle_at_age(HANDLE_CHANGE_AGE_DAYS + 1) == "@bsmith"
    assert ben.handle_at_age(HANDLE_CHANGE_AGE_DAYS - 1) == "@ben"


def test_reference_now_is_timezone_aware_and_fixed() -> None:
    assert REFERENCE_NOW.tzinfo is not None
    assert REFERENCE_NOW.year == 2026


def test_decisions_have_distinct_ages_in_window() -> None:
    ages = [d.age_days for d in COMPANY.decisions]
    assert len(set(ages)) == len(ages), "decision ages must be distinct for ordering"
    assert all(0 < a < 400 for a in ages)
