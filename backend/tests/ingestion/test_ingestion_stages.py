"""Per-stage tests for the incremental pipeline (Phase 5A).

Exercises the stages whose logic is non-trivial in isolation: provenance-based scope derivation,
the extraction skip-guard, the mechanical Message materialisation, and the static search-index
stage. The heavier resolve/contradiction stages are covered through the orchestrator and
idempotency tests, which run them end-to-end against real Neo4j.
"""

from __future__ import annotations

import pytest

from app.ingestion.stages import (
    derive_graph_scope,
    run_embed,
    run_extract,
    run_materialize_message,
    run_search_index,
)
from app.models.enums import SourceType

from .conftest import FakeClient, person_extraction, seed_event

pytestmark = pytest.mark.asyncio


async def test_derive_graph_scope_reads_provenance(
    session_factory: object, neo4j_driver: object
) -> None:
    event = await seed_event(
        session_factory,  # type: ignore[arg-type]
        source_type=SourceType.doc,
        content="welcome aboard Priya Nair, a new Software Engineer",
    )
    fake = FakeClient(extraction=person_extraction("Priya Nair"))
    out = await run_extract(
        event, session_factory=session_factory, driver=neo4j_driver, client=fake  # type: ignore[arg-type]
    )
    assert out.ok is True
    assert out.stage.status == "ok"

    scope = await derive_graph_scope(neo4j_driver, event.id)  # type: ignore[arg-type]
    assert [n.label for n in scope.nodes] == ["Person"]
    assert scope.node_types == ["Person"]
    assert scope.decision_ids == []


async def test_extract_skip_guard_reuses_prior_extraction(
    session_factory: object, neo4j_driver: object
) -> None:
    event = await seed_event(
        session_factory,  # type: ignore[arg-type]
        source_type=SourceType.doc,
        content="welcome aboard Sam Lee, a new Software Engineer",
    )
    fake = FakeClient(extraction=person_extraction("Sam Lee"))
    first = await run_extract(
        event, session_factory=session_factory, driver=neo4j_driver, client=fake  # type: ignore[arg-type]
    )
    assert first.stage.status == "ok"
    calls_after_first = len(fake.calls)

    second = await run_extract(
        event, session_factory=session_factory, driver=neo4j_driver, client=fake  # type: ignore[arg-type]
    )
    assert second.stage.status == "skipped"
    assert "reused" in (second.stage.detail or "")
    # No further LLM call on the replay; scope is still re-derived from the graph.
    assert len(fake.calls) == calls_after_first
    assert [n.label for n in second.scope.nodes] == ["Person"]


async def test_extract_marks_failed_on_bad_json(
    session_factory: object, neo4j_driver: object
) -> None:
    class BrokenClient(FakeClient):
        async def complete(self, **_: object):  # type: ignore[override]
            from app.extraction.client import CompletionResult

            self.calls.append("broken")
            return CompletionResult(
                content="not json", model="x", cost_usd=0.0, prompt_tokens=1, completion_tokens=1
            )

    event = await seed_event(
        session_factory,  # type: ignore[arg-type]
        source_type=SourceType.doc,
        content="some content that fails to parse into entities",
    )
    out = await run_extract(
        event, session_factory=session_factory, driver=neo4j_driver, client=BrokenClient()  # type: ignore[arg-type]
    )
    assert out.ok is False
    assert out.stage.status == "failed"


async def test_materialize_message_only_for_slack(
    session_factory: object, neo4j_driver: object
) -> None:
    slack = await seed_event(
        session_factory,  # type: ignore[arg-type]
        source_type=SourceType.slack_message,
        content="the team thinks the legacy-auth plan is stale and should be revisited",
    )
    stage, message_id = await run_materialize_message(
        neo4j_driver, slack, source_kind="slack_message"  # type: ignore[arg-type]
    )
    assert stage.status == "ok"
    assert message_id == f"slack:{slack.source_external_id}"

    doc = await seed_event(
        session_factory,  # type: ignore[arg-type]
        source_type=SourceType.doc,
        content="an architecture decision document body with enough characters",
    )
    stage_doc, message_id_doc = await run_materialize_message(
        neo4j_driver, doc, source_kind="doc"  # type: ignore[arg-type]
    )
    assert stage_doc.status == "skipped"
    assert message_id_doc is None


async def test_embed_then_skip(session_factory: object, neo4j_driver: object) -> None:
    await seed_event(
        session_factory,  # type: ignore[arg-type]
        source_type=SourceType.doc,
        content="an event whose text we will embed once and then skip",
    )
    first = await run_embed(session_factory)  # type: ignore[arg-type]
    assert first.status == "ok"
    second = await run_embed(session_factory)  # type: ignore[arg-type]
    assert second.status == "skipped"


async def test_search_index_is_static_skip() -> None:
    stage = run_search_index()
    assert stage.name == "search_index"
    assert stage.status == "skipped"
