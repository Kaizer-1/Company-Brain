"""Idempotency — the load-bearing ingestion test (Phase 5A, ADR 0032).

Ingesting the same event twice must converge to identical state. We assert it three ways:
the default replay short-circuits at the orchestration guard (no new work, no audit growth); a
*forced* replay still yields identical graph node counts (MERGE-level idempotency); and the
extraction skip-guard means the LLM is called exactly once across all three passes.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.ingestion.orchestrator import reconcile_event
from app.ingestion.stages import EXTRACTION_MODEL
from app.models.enums import SourceType

from .conftest import FakeClient, node_label_counts, person_extraction, seed_event

pytestmark = pytest.mark.asyncio


async def _scalar_count(factory: object, table: str) -> int:
    async with factory() as session:  # type: ignore[operator]
        result = await session.execute(text(f"SELECT count(*) FROM {table}"))
        return int(result.scalar_one())


async def test_double_ingest_is_idempotent(session_factory: object, neo4j_driver: object) -> None:
    event = await seed_event(
        session_factory,  # type: ignore[arg-type]
        source_type=SourceType.doc,
        content="Onboarding: welcome aboard Nadia Okafor, joining as a Software Engineer.",
    )
    fake = FakeClient(extraction=person_extraction("Nadia Okafor"))

    r1 = await reconcile_event(
        event.id, session_factory=session_factory, neo4j_driver=neo4j_driver, client=fake
    )
    assert r1.status == "reconciled"
    assert any(n.label == "Person" for n in r1.nodes_created)

    counts1 = await node_label_counts(neo4j_driver)
    md1 = await _scalar_count(session_factory, "merge_decisions")

    # Default replay → guard short-circuit: no stages run, no state change.
    r2 = await reconcile_event(
        event.id, session_factory=session_factory, neo4j_driver=neo4j_driver, client=fake
    )
    assert r2.deduplicated is True
    assert await node_label_counts(neo4j_driver) == counts1
    assert await _scalar_count(session_factory, "merge_decisions") == md1
    assert await _scalar_count(session_factory, "ingestion_runs") == 1

    # Forced replay → MERGE-level idempotency: graph node counts still identical.
    await reconcile_event(
        event.id,
        session_factory=session_factory,
        neo4j_driver=neo4j_driver,
        client=fake,
        force=True,
    )
    assert await node_label_counts(neo4j_driver) == counts1
    assert await _scalar_count(session_factory, "ingestion_runs") == 1  # upsert, not append

    # Extraction skip-guard: the LLM was called exactly once across all three passes.
    assert fake.calls.count(EXTRACTION_MODEL) == 1
