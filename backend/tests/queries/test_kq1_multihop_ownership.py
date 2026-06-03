"""Real-Neo4j test for KQ1 — multi-hop ownership (Phase 3B)."""

from __future__ import annotations

import pytest

from app.queries.kq1_multihop_ownership import find_chain_owner

pytestmark = pytest.mark.asyncio

_SEED = """
CREATE (d:Decision {id:'D-0006', title:'Deprecate legacy-auth', status:'active', source_event_ids:['ed1']})
CREATE (sys:System {canonical_name:'legacy-auth', id:'legacy-auth', status:'active', source_event_ids:['es1']})
CREATE (svc:Service {canonical_name:'payments-api', id:'payments-api', status:'active', source_event_ids:['ev1']})
CREATE (sub:Service {canonical_name:'subscriptions-service', id:'subscriptions-service', status:'active', source_event_ids:['ev2']})
CREATE (pay:Team {canonical_name:'payments', id:'payments', status:'active', source_event_ids:['et1']})
CREATE (grw:Team {canonical_name:'growth', id:'growth', status:'active', source_event_ids:['et2']})
CREATE (diego:Person {canonical_id:'diego-ramirez', id:'diego-ramirez', display_name:'Diego Ramirez', status:'active', source_event_ids:['ep1']})
CREATE (priya:Person {canonical_id:'priya-nair', id:'priya-nair', display_name:'Priya Nair', status:'active', source_event_ids:['ep2']})
CREATE (d)-[:DEPRECATES {source_event_id:'e1'}]->(sys)
CREATE (svc)-[:DEPENDS_ON {source_event_id:'e2'}]->(sys)
CREATE (sub)-[:DEPENDS_ON {source_event_id:'e3'}]->(sys)
CREATE (svc)-[:OWNED_BY {source_event_id:'e4'}]->(pay)
CREATE (sub)-[:OWNED_BY {source_event_id:'e5'}]->(grw)
CREATE (diego)-[:MEMBER_OF {source_event_id:'e6'}]->(pay)
CREATE (priya)-[:MEMBER_OF {source_event_id:'e7'}]->(grw)
"""


async def _seed(driver: object) -> None:
    async with driver.session() as s:  # type: ignore[attr-defined]
        await (await s.run(_SEED)).consume()


async def test_kq1_returns_owner_and_full_chain(neo4j_driver: object) -> None:
    await _seed(neo4j_driver)
    result = await find_chain_owner(neo4j_driver, decision_id="D-0006")

    assert "diego-ramirez" in result.value.owner_people
    assert "priya-nair" in result.value.owner_people  # secondary dependent owner
    # The canonical chain Decision->System->Service->Team->Person is 4 hops.
    assert max(c.hops for c in result.value.chains) == 4
    # Provenance carries every edge's source event.
    assert {"e1", "e2", "e4", "e6"} <= set(result.provenance.all_event_ids)


async def test_kq1_excludes_merged_nodes(neo4j_driver: object) -> None:
    await _seed(neo4j_driver)
    # Tombstone Diego's node: the resolved view must not surface him via the merged node.
    async with neo4j_driver.session() as s:  # type: ignore[attr-defined]
        await (
            await s.run("MATCH (p:Person {canonical_id:'diego-ramirez'}) SET p.status='merged'")
        ).consume()
    result = await find_chain_owner(neo4j_driver, decision_id="D-0006")
    assert "diego-ramirez" not in result.value.owner_people


async def test_kq1_unknown_decision_returns_empty(neo4j_driver: object) -> None:
    await _seed(neo4j_driver)
    result = await find_chain_owner(neo4j_driver, decision_id="D-9999")
    assert result.value.owner_people == []
    assert result.value.chains == []
