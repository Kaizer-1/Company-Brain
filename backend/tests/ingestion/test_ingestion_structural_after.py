"""The 4C ↔ 5A integration test: ingestion moves the structural-tool counts (Phase 5A).

This is the load-bearing demo claim made into an assertion. Seed a graph with N Person nodes,
ingest a doc asserting a new hire, then call ``enumerate_by_type(Person)`` directly against Neo4j
(not via the agent — too slow for a test) and confirm the count went N → N+1. The structural
tools from Phase 4C are how the "self-updating knowledge graph" thesis is *verified*.
"""

from __future__ import annotations

import pytest

from app.ingestion.orchestrator import reconcile_event
from app.models.enums import SourceType
from app.queries.enumerate import EnumerateInput, enumerate_by_type

from .conftest import FakeClient, person_extraction, seed_event

pytestmark = pytest.mark.asyncio

_SEED_PEOPLE = ("alice-chen", "ben-smith", "diego-ramirez")


async def _seed_people(driver: object) -> None:
    query = (
        "UNWIND $ids AS pid "
        "MERGE (p:Person {canonical_id: pid}) "
        "ON CREATE SET p.id = pid, p.name = pid, p.status = 'active', "
        "  p.source_event_ids = ['seed']"
    )
    async with driver.session() as session:  # type: ignore[attr-defined]
        await (await session.run(query, ids=list(_SEED_PEOPLE))).consume()


async def test_enumerate_count_increments_after_ingesting_a_person(
    session_factory: object, neo4j_driver: object
) -> None:
    await _seed_people(neo4j_driver)
    before = (
        await enumerate_by_type(neo4j_driver, EnumerateInput(node_type="Person"))
    ).value
    assert before.total_count == len(_SEED_PEOPLE)

    event = await seed_event(
        session_factory,  # type: ignore[arg-type]
        source_type=SourceType.doc,
        content="Slack #general: welcome aboard Nadia Okafor, joining the platform team as a "
        "Software Engineer.",
    )
    fake = FakeClient(extraction=person_extraction("Nadia Okafor"))
    response = await reconcile_event(
        event.id, session_factory=session_factory, neo4j_driver=neo4j_driver, client=fake
    )
    assert response.status == "reconciled"

    after = (
        await enumerate_by_type(neo4j_driver, EnumerateInput(node_type="Person"))
    ).value
    assert after.total_count == len(_SEED_PEOPLE) + 1
    identifiers = {n.id.lower() for n in after.nodes} | {n.name.lower() for n in after.nodes}
    assert any("nadia" in ident for ident in identifiers)
