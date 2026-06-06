"""Real-Neo4j tests for the structural tool ``neighbors_of_entity`` (Phase 4C)."""

from __future__ import annotations

import pytest

from app.queries.neighbors import NeighborsInput, neighbors_of_entity

pytestmark = pytest.mark.asyncio

_SEED = """
CREATE (pay:Team {canonical_name:'Payments', id:'payments', source_event_ids:['et1']})
CREATE (a:Person {canonical_id:'alice-chen', id:'alice-chen', source_event_ids:['e1']})
CREATE (b:Person {canonical_id:'bob', id:'bob', source_event_ids:['e2']})
CREATE (svc:Service {canonical_name:'payments-api', id:'payments-api', source_event_ids:['es1']})
CREATE (dep:Service {canonical_name:'checkout-service', id:'checkout-service', source_event_ids:['es2']})
CREATE (sys:System {canonical_name:'legacy-auth', id:'legacy-auth', source_event_ids:['esys1']})
CREATE (mp:Person {canonical_id:'mallory', id:'mallory', status:'merged', source_event_ids:['em1']})
CREATE (a)-[:MEMBER_OF {source_event_id:'m1'}]->(pay)
CREATE (b)-[:MEMBER_OF {source_event_id:'m2'}]->(pay)
CREATE (mp)-[:MEMBER_OF {source_event_id:'m3'}]->(pay)
CREATE (svc)-[:OWNED_BY {source_event_id:'o1'}]->(pay)
CREATE (svc)-[:DEPENDS_ON {source_event_id:'dep1'}]->(sys)
CREATE (dep)-[:DEPENDS_ON {source_event_id:'dep2'}]->(svc)
"""


async def _seed(driver: object) -> None:
    async with driver.session() as s:  # type: ignore[attr-defined]
        await (await s.run(_SEED)).consume()


async def test_members_of_team_direction_in(neo4j_driver: object) -> None:
    await _seed(neo4j_driver)
    r = await neighbors_of_entity(
        neo4j_driver, NeighborsInput(entity_id="Payments", edge_type="MEMBER_OF", direction="in")
    )
    # alice + bob; mallory is merged and excluded.
    assert r.value.total_count == 2
    assert sorted(n.neighbor_id for n in r.value.neighbors) == ["alice-chen", "bob"]
    assert all(not n.outgoing for n in r.value.neighbors)  # edges point INTO the team


async def test_entity_id_case_insensitive(neo4j_driver: object) -> None:
    await _seed(neo4j_driver)
    r = await neighbors_of_entity(
        neo4j_driver, NeighborsInput(entity_id="payments", edge_type="MEMBER_OF", direction="in")
    )
    assert r.value.total_count == 2


async def test_depends_on_in_vs_out(neo4j_driver: object) -> None:
    await _seed(neo4j_driver)
    incoming = await neighbors_of_entity(
        neo4j_driver,
        NeighborsInput(entity_id="payments-api", edge_type="DEPENDS_ON", direction="in"),
    )
    assert [n.neighbor_id for n in incoming.value.neighbors] == ["checkout-service"]

    outgoing = await neighbors_of_entity(
        neo4j_driver,
        NeighborsInput(entity_id="payments-api", edge_type="DEPENDS_ON", direction="out"),
    )
    assert [n.neighbor_id for n in outgoing.value.neighbors] == ["legacy-auth"]


async def test_edge_type_filter_and_both_direction(neo4j_driver: object) -> None:
    await _seed(neo4j_driver)
    # All edges of payments-api, both directions: OWNED_BY(out), DEPENDS_ON(out to sys),
    # DEPENDS_ON(in from checkout).
    all_edges = await neighbors_of_entity(
        neo4j_driver, NeighborsInput(entity_id="payments-api", direction="both")
    )
    assert all_edges.value.total_count == 3
    edge_types = {n.edge_type for n in all_edges.value.neighbors}
    assert edge_types == {"OWNED_BY", "DEPENDS_ON"}


async def test_limit_caps_returned_not_total(neo4j_driver: object) -> None:
    await _seed(neo4j_driver)
    r = await neighbors_of_entity(
        neo4j_driver,
        NeighborsInput(entity_id="Payments", edge_type="MEMBER_OF", direction="in", limit=1),
    )
    assert r.value.total_count == 2
    assert len(r.value.neighbors) == 1


async def test_provenance_carries_edge_events(neo4j_driver: object) -> None:
    await _seed(neo4j_driver)
    r = await neighbors_of_entity(
        neo4j_driver, NeighborsInput(entity_id="Payments", edge_type="MEMBER_OF", direction="in")
    )
    assert {"m1", "m2"} <= set(r.provenance.all_event_ids)
