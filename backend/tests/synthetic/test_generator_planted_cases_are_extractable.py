"""Every planted case must actually surface in the generated text.

This does NOT test extraction (that is Phase 2B). It tests that the raw event *content*
mentions the anchor entities of each adversarial case — so a planted trap can never
silently fail to make it into the corpus.
"""

from app.schemas.postgres import EventCreate
from app.synthetic import narrative as nv
from app.synthetic.company import COMPANY


def _any_event_contains(corpus: list[EventCreate], *needles: str) -> bool:
    return any(all(n in e.content for n in needles) for e in corpus)


def test_every_alias_surface_form_appears(corpus: list[EventCreate], blob: str) -> None:
    for group in nv.ALIAS_GROUPS:
        for form in group.surface_forms:
            assert form in blob, f"alias form {form!r} for {group.canonical} never appears"


def test_look_alike_pair_both_appear_and_are_distinguished(
    corpus: list[EventCreate], blob: str
) -> None:
    pair = nv.LOOK_ALIKE_PAIRS[0]
    assert pair.service_a in blob
    assert pair.service_b in blob
    # Some event must mention both and call them different.
    assert _any_event_contains(corpus, pair.service_a, pair.service_b, "different")


def test_deprecation_chain_links_are_present(corpus: list[EventCreate], blob: str) -> None:
    chain = nv.DEPRECATION_CHAINS[0]
    assert chain.decision_id in blob
    assert chain.deprecated_system in blob
    # The dependent service depends on the deprecated system — co-occurring in some event.
    assert _any_event_contains(corpus, chain.dependent_service, chain.deprecated_system)
    # Diego is referenced by his title (the alias trap) in the KQ1 context.
    diego = COMPANY.person(chain.owner_person)
    assert any(t in blob for t in diego.title_refs)
    for sec in chain.secondary_dependents:
        assert sec in blob


def test_contradiction_pair_is_present(corpus: list[EventCreate], blob: str) -> None:
    pair = nv.CONTRADICTION_PAIRS[0]
    assert pair.decision_id in blob
    # The contradicting discussion text appears, attributed to the contradicting handles.
    assert pair.contradiction_claim in blob
    for handle in pair.contradicting_handles:
        assert handle in blob


def test_every_dependency_edge_cooccurs_in_an_event(corpus: list[EventCreate]) -> None:
    for e in nv.DEPENDENCY_GRAPH.edges:
        assert _any_event_contains(corpus, e.upstream, e.downstream), (
            f"edge {e.upstream} -> {e.downstream} never co-occurs in one event"
        )


def test_deep_chain_endpoints_present(corpus: list[EventCreate], blob: str) -> None:
    for node in nv.DEPENDENCY_GRAPH.deep_chain:
        assert node in blob


def test_change_timeline_decisions_and_supersession_present(
    corpus: list[EventCreate], blob: str
) -> None:
    timeline = nv.CHANGE_TIMELINES[0]
    for did in timeline.decision_ids:
        assert did in blob, f"{did} never appears"
    superseding, superseded = timeline.supersession
    # The supersession is stated in some single event (decision doc or recap).
    assert _any_event_contains(corpus, superseding, superseded)


def test_change_timeline_approvers_present(corpus: list[EventCreate], blob: str) -> None:
    timeline = nv.CHANGE_TIMELINES[0]
    for did in timeline.decision_ids:
        d = COMPANY.decision(did)
        for approver_id in d.approvers:
            person = COMPANY.person(approver_id)
            # Name or an age-appropriate handle appears somewhere.
            assert person.display_name in blob or person.handle in blob or (
                person.former_handle is not None and person.former_handle in blob
            )


def test_ownership_ambiguity_present(corpus: list[EventCreate], blob: str) -> None:
    amb = nv.OWNERSHIP_AMBIGUITIES[0]
    assert amb.service in blob
    # Both the contested and the authoritative team are claimed somewhere for the service.
    assert _any_event_contains(corpus, amb.service, amb.contested_team)
    assert _any_event_contains(corpus, amb.service, amb.authoritative_team)


def test_stale_docs_present(corpus: list[EventCreate], blob: str) -> None:
    for doc in nv.STALE_DOCS:
        assert doc.stale_claim in blob


def test_departure_transfer_present(corpus: list[EventCreate], blob: str) -> None:
    transfer = nv.DEPARTURE_TRANSFERS[0]
    bob = COMPANY.person(transfer.person_left)
    carol = COMPANY.person(transfer.successor)
    # A single event states the transfer of the asset to the successor after departure.
    assert _any_event_contains(corpus, bob.handle, transfer.asset, carol.handle)


def test_handle_change_both_handles_present(blob: str) -> None:
    ben = COMPANY.person("ben-smith")
    assert ben.handle in blob
    assert ben.former_handle is not None and ben.former_handle in blob
