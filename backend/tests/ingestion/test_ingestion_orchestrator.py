"""Orchestrator tests: stage ordering, scope propagation, failure handling (Phase 5A)."""

from __future__ import annotations

import pytest

from app.ingestion.orchestrator import reconcile_event
from app.models.enums import SourceType

from .conftest import FakeClient, node_label_counts, person_extraction, seed_event

pytestmark = pytest.mark.asyncio

# The full stage timeline, in order, every run records (skips included).
_EXPECTED_STAGES = [
    "extract",
    "embed",
    "resolve",
    "consolidate",
    "project",
    "temporal",
    "materialize_message",
    "contradiction",
    "search_index",
]


async def test_runs_all_stages_in_order(session_factory: object, neo4j_driver: object) -> None:
    event = await seed_event(
        session_factory,  # type: ignore[arg-type]
        source_type=SourceType.doc,
        content="welcome aboard Nadia Okafor, joining as a Software Engineer",
    )
    fake = FakeClient(extraction=person_extraction("Nadia Okafor"))
    response = await reconcile_event(
        event.id, session_factory=session_factory, neo4j_driver=neo4j_driver, client=fake
    )
    assert [s.name for s in response.stages_run] == _EXPECTED_STAGES
    assert response.status == "reconciled"


async def test_person_doc_skips_decision_and_message_stages(
    session_factory: object, neo4j_driver: object
) -> None:
    event = await seed_event(
        session_factory,  # type: ignore[arg-type]
        source_type=SourceType.doc,
        content="welcome aboard Nadia Okafor, joining as a Software Engineer",
    )
    fake = FakeClient(extraction=person_extraction("Nadia Okafor"))
    response = await reconcile_event(
        event.id, session_factory=session_factory, neo4j_driver=neo4j_driver, client=fake
    )
    by_name = {s.name: s.status for s in response.stages_run}
    assert by_name["consolidate"] == "skipped"  # no Decision asserted
    assert by_name["temporal"] == "skipped"
    assert by_name["materialize_message"] == "skipped"  # not slack
    assert by_name["contradiction"] == "skipped"  # nothing to compare
    assert by_name["resolve"] in {"ok", "skipped"}


async def test_empty_extraction_reconciles_with_no_graph_changes(
    session_factory: object, neo4j_driver: object
) -> None:
    before = await node_label_counts(neo4j_driver)
    event = await seed_event(
        session_factory,  # type: ignore[arg-type]
        source_type=SourceType.doc,
        content="lgtm, shipping this — ambient chatter with no entities to extract",
    )
    fake = FakeClient(extraction={"entities": [], "relationships": []})
    response = await reconcile_event(
        event.id, session_factory=session_factory, neo4j_driver=neo4j_driver, client=fake
    )
    assert response.status == "reconciled"
    assert response.nodes_created == []
    # No fabricated stubs: the graph is unchanged for a doc that asserted nothing.
    assert await node_label_counts(neo4j_driver) == before


async def test_extraction_failure_yields_partial_but_records_a_run(
    session_factory: object, neo4j_driver: object
) -> None:
    class BrokenClient(FakeClient):
        async def complete(self, *, messages, model, **_):  # type: ignore[override,no-untyped-def]
            from app.extraction.client import CompletionResult

            system = messages[0]["content"] if messages else ""
            # Break only the extraction call; let resolution/contradiction fall through to the
            # well-formed fake verdicts so the downstream stages run normally.
            if "resolution adjudicator" in system or "contradicts a recorded engineering" in system:
                return await super().complete(messages=messages, model=model)
            self.calls.append(model)
            return CompletionResult(
                content="}{ broken", model=model, cost_usd=0.0,
                prompt_tokens=1, completion_tokens=1,
            )

    event = await seed_event(
        session_factory,  # type: ignore[arg-type]
        source_type=SourceType.slack_message,
        content="the team thinks the legacy-auth migration plan is now stale",
    )
    response = await reconcile_event(
        event.id, session_factory=session_factory, neo4j_driver=neo4j_driver, client=BrokenClient()
    )
    # Extraction failed, but the run still completed downstream stages → partial, not crashed.
    assert response.status == "partial"
    extract_stage = next(s for s in response.stages_run if s.name == "extract")
    assert extract_stage.status == "failed"
    # A slack event still gets its Message materialised even when extraction failed.
    assert next(s for s in response.stages_run if s.name == "materialize_message").status == "ok"
