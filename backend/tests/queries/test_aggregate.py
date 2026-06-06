"""Real-Neo4j tests for the structural tool ``aggregate_by_type`` (Phase 4C)."""

from __future__ import annotations

import pytest

from app.queries.aggregate import AggregateInput, aggregate_by_type

pytestmark = pytest.mark.asyncio

# Two teams; Payments owns 2 services, Growth owns 1; one service owned by a person; one
# deprecated service (excluded from active counts); two active + one superseded decision.
_SEED = """
CREATE (pay:Team {canonical_name:'Payments', id:'payments', source_event_ids:['et1']})
CREATE (grw:Team {canonical_name:'Growth', id:'growth', source_event_ids:['et2']})
CREATE (carol:Person {canonical_id:'carol', id:'carol', source_event_ids:['ep1']})
CREATE (s1:Service {canonical_name:'payments-api', id:'payments-api', source_event_ids:['es1']})
CREATE (s2:Service {canonical_name:'payouts-service', id:'payouts-service', source_event_ids:['es2']})
CREATE (s3:Service {canonical_name:'subscriptions', id:'subscriptions', source_event_ids:['es3']})
CREATE (s4:Service {canonical_name:'reporting', id:'reporting', source_event_ids:['es4']})
CREATE (s5:Service {canonical_name:'old-svc', id:'old-svc', status:'deprecated', source_event_ids:['es5']})
CREATE (d1:Decision {id:'D-1', title:'a', status:'active', source_event_ids:['ed1']})
CREATE (d2:Decision {id:'D-2', title:'b', status:'active', source_event_ids:['ed2']})
CREATE (d3:Decision {id:'D-3', title:'c', status:'superseded', source_event_ids:['ed3']})
CREATE (s1)-[:OWNED_BY {source_event_id:'o1'}]->(pay)
CREATE (s2)-[:OWNED_BY {source_event_id:'o2'}]->(pay)
CREATE (s3)-[:OWNED_BY {source_event_id:'o3'}]->(grw)
CREATE (s4)-[:OWNED_BY {source_event_id:'o4'}]->(carol)
"""


async def _seed(driver: object) -> None:
    async with driver.session() as s:  # type: ignore[attr-defined]
        await (await s.run(_SEED)).consume()


async def test_total_without_grouping(neo4j_driver: object) -> None:
    await _seed(neo4j_driver)
    decisions = await aggregate_by_type(
        neo4j_driver, AggregateInput(node_type="Decision", status="active")
    )
    assert decisions.value.total == 2  # D-3 superseded excluded
    assert decisions.value.groups is None
    # Aggregates carry no source events by design.
    assert decisions.provenance.all_event_ids == []


async def test_group_by_owned_by_ordering(neo4j_driver: object) -> None:
    await _seed(neo4j_driver)
    r = await aggregate_by_type(
        neo4j_driver, AggregateInput(node_type="Service", group_by="OWNED_BY")
    )
    assert r.value.groups is not None
    groups = {(g.group_name, g.group_type): g.count for g in r.value.groups}
    assert groups[("Payments", "Team")] == 2
    assert groups[("Growth", "Team")] == 1
    assert groups[("carol", "Person")] == 1  # person owner grouped via coalesced name
    # count_desc default: Payments (2) first.
    assert r.value.groups[0].group_name == "Payments"


async def test_group_order_name_asc(neo4j_driver: object) -> None:
    await _seed(neo4j_driver)
    r = await aggregate_by_type(
        neo4j_driver,
        AggregateInput(node_type="Service", group_by="OWNED_BY", order="name_asc"),
    )
    assert r.value.groups is not None
    names = [g.group_name for g in r.value.groups]
    assert names == sorted(names)


async def test_status_filter_affects_count(neo4j_driver: object) -> None:
    await _seed(neo4j_driver)
    active = await aggregate_by_type(neo4j_driver, AggregateInput(node_type="Service"))
    all_svc = await aggregate_by_type(
        neo4j_driver, AggregateInput(node_type="Service", status="all")
    )
    assert active.value.total == 4  # old-svc deprecated excluded
    assert all_svc.value.total == 5
