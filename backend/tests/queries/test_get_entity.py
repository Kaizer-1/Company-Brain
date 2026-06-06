"""Real-Neo4j tests for the structural tool ``get_entity`` (Phase 4C)."""

from __future__ import annotations

import pytest

from app.queries.get_entity import GetEntityInput, get_entity

pytestmark = pytest.mark.asyncio

_SEED = """
CREATE (a:Person {canonical_id:'alice-chen', id:'alice-chen', handle:'@alice', email:'a@x.io', source_event_ids:['e1','e2']})
CREATE (pay:Team {canonical_name:'Payments', id:'payments', source_event_ids:['et1']})
CREATE (svc:Service {canonical_name:'payments-api', id:'payments-api', source_event_ids:['es1']})
CREATE (d:Decision {id:'D-0006', title:'Deprecate legacy-auth', status:'active', source_event_ids:['ed1']})
CREATE (sys:System {canonical_name:'legacy-auth', id:'legacy-auth', status:'deprecated', source_event_ids:['esys1']})
CREATE (mp:Person {canonical_id:'mallory', id:'mallory', status:'merged', source_event_ids:['em1']})
CREATE (a)-[:MEMBER_OF {source_event_id:'m1'}]->(pay)
CREATE (svc)-[:OWNED_BY {source_event_id:'o1'}]->(pay)
CREATE (svc)-[:DEPENDS_ON {source_event_id:'dep1'}]->(sys)
CREATE (d)-[:DEPRECATES {source_event_id:'dpr1'}]->(sys)
"""


async def _seed(driver: object) -> None:
    async with driver.session() as s:  # type: ignore[attr-defined]
        await (await s.run(_SEED)).consume()


async def test_lookup_by_decision_id(neo4j_driver: object) -> None:
    await _seed(neo4j_driver)
    r = await get_entity(neo4j_driver, GetEntityInput(entity_id="D-0006"))
    assert r.value.node_type == "Decision"
    assert r.value.properties["title"] == "Deprecate legacy-auth"
    assert r.value.outgoing_edges.get("DEPRECATES") == 1
    assert "ed1" in r.value.source_event_ids


async def test_lookup_person_by_handle_case_insensitive(neo4j_driver: object) -> None:
    await _seed(neo4j_driver)
    r = await get_entity(neo4j_driver, GetEntityInput(entity_id="@Alice"))
    assert r.value.node_type == "Person"
    assert r.value.properties["canonical_id"] == "alice-chen"
    assert r.value.outgoing_edges.get("MEMBER_OF") == 1


async def test_service_edge_summary(neo4j_driver: object) -> None:
    await _seed(neo4j_driver)
    r = await get_entity(neo4j_driver, GetEntityInput(entity_id="payments-api"))
    assert r.value.node_type == "Service"
    # Outgoing: OWNED_BY + DEPENDS_ON. Incoming: none.
    assert r.value.outgoing_edges.get("OWNED_BY") == 1
    assert r.value.outgoing_edges.get("DEPENDS_ON") == 1
    assert r.value.incoming_edges == {}


async def test_node_type_hint_disambiguates(neo4j_driver: object) -> None:
    await _seed(neo4j_driver)
    # The hint forces the Person label; a Team named 'payments' must not match.
    r = await get_entity(
        neo4j_driver, GetEntityInput(entity_id="payments", node_type_hint="Team")
    )
    assert r.value.node_type == "Team"


async def test_missing_entity_returns_not_found(neo4j_driver: object) -> None:
    await _seed(neo4j_driver)
    r = await get_entity(neo4j_driver, GetEntityInput(entity_id="does-not-exist"))
    assert r.value.node_type == "not_found"
    assert r.value.properties == {}
    assert r.value.source_event_ids == []


async def test_merged_node_excluded(neo4j_driver: object) -> None:
    await _seed(neo4j_driver)
    r = await get_entity(neo4j_driver, GetEntityInput(entity_id="mallory"))
    assert r.value.node_type == "not_found"
