"""Real-Neo4j test for KQ3 — blast radius (Phase 3B)."""

from __future__ import annotations

import pytest

from app.queries.kq3_blast_radius import compute_blast_radius

pytestmark = pytest.mark.asyncio

_SEED = """
CREATE (pa:Service {canonical_name:'payments-api', id:'payments-api', status:'active', source_event_ids:['e0']})
CREATE (co:Service {canonical_name:'checkout-service', id:'checkout-service', status:'active', source_event_ids:['e1']})
CREATE (ws:Service {canonical_name:'web-storefront', id:'web-storefront', status:'active', source_event_ids:['e2']})
CREATE (bv:Service {canonical_name:'billing-v2', id:'billing-v2', status:'active', source_event_ids:['e3']})
CREATE (pay:Team {canonical_name:'payments', id:'payments', status:'active'})
CREATE (diego:Person {canonical_id:'diego-ramirez', id:'diego-ramirez', status:'active'})
CREATE (dec:Decision {id:'D-0005', status:'active', source_event_ids:['ed']})
CREATE (co)-[:DEPENDS_ON {source_event_id:'r1'}]->(pa)
CREATE (bv)-[:DEPENDS_ON {source_event_id:'r2'}]->(pa)
CREATE (ws)-[:DEPENDS_ON {source_event_id:'r3'}]->(co)
CREATE (pa)-[:OWNED_BY {source_event_id:'r4'}]->(pay)
CREATE (diego)-[:MEMBER_OF {source_event_id:'r5'}]->(pay)
CREATE (dec)-[:ABOUT {source_event_id:'r6'}]->(pa)
"""


async def _seed(driver: object) -> None:
    async with driver.session() as s:  # type: ignore[attr-defined]
        await (await s.run(_SEED)).consume()


async def test_kq3_transitive_blast_radius(neo4j_driver: object) -> None:
    await _seed(neo4j_driver)
    result = await compute_blast_radius(neo4j_driver, service_name="payments-api", max_depth=5)
    services = set(result.value.affected_services)
    assert {"checkout-service", "billing-v2", "web-storefront"} <= services
    assert result.value.max_depth_reached == 2  # web-storefront -> checkout -> payments-api
    assert "diego-ramirez" in result.value.affected_people
    assert "D-0005" in result.value.affected_decisions


async def test_kq3_respects_max_depth(neo4j_driver: object) -> None:
    await _seed(neo4j_driver)
    result = await compute_blast_radius(neo4j_driver, service_name="payments-api", max_depth=1)
    services = set(result.value.affected_services)
    assert "checkout-service" in services
    assert "web-storefront" not in services  # depth 2, beyond the limit


async def test_kq3_provenance_carries_dependency_edges(neo4j_driver: object) -> None:
    await _seed(neo4j_driver)
    result = await compute_blast_radius(neo4j_driver, service_name="payments-api", max_depth=5)
    assert {"r1", "r2", "r3"} <= set(result.provenance.all_event_ids)
