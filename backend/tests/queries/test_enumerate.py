"""Real-Neo4j tests for the structural tool ``enumerate_by_type`` (Phase 4C)."""

from __future__ import annotations

import pytest

from app.queries.enumerate import EnumerateInput, enumerate_by_type

pytestmark = pytest.mark.asyncio

# Heterogeneous identity, mirroring the live graph: Person→canonical_id (no status), Team/
# Service→canonical_name, Decision→id+title+status. One merged person, one deprecated service,
# one superseded + one active decision, one orphan service (no OWNED_BY).
_SEED = """
CREATE (a:Person {canonical_id:'alice-chen', id:'alice-chen', handle:'@alice', email:'a@x.io', source_event_ids:['e1']})
CREATE (b:Person {canonical_id:'bob', id:'bob', source_event_ids:['e2']})
CREATE (mp:Person {canonical_id:'mallory', id:'mallory', status:'merged', source_event_ids:['e3']})
CREATE (pay:Team {canonical_name:'Payments', id:'payments', source_event_ids:['et1']})
CREATE (s1:Service {canonical_name:'payments-api', id:'payments-api', source_event_ids:['es1']})
CREATE (s2:Service {canonical_name:'orphan-svc', id:'orphan-svc', source_event_ids:['es2']})
CREATE (s3:Service {canonical_name:'old-svc', id:'old-svc', status:'deprecated', source_event_ids:['es3']})
CREATE (d1:Decision {id:'D-1', title:'Active one', status:'active', valid_from: datetime('2026-01-01T00:00:00Z'), source_event_ids:['ed1']})
CREATE (d2:Decision {id:'D-2', title:'Superseded one', status:'superseded', valid_from: datetime('2026-03-01T00:00:00Z'), source_event_ids:['ed2']})
CREATE (a)-[:MEMBER_OF {source_event_id:'m1'}]->(pay)
CREATE (s1)-[:OWNED_BY {source_event_id:'o1'}]->(pay)
"""


async def _seed(driver: object) -> None:
    async with driver.session() as s:  # type: ignore[attr-defined]
        await (await s.run(_SEED)).consume()


async def test_active_excludes_merged_deprecated_superseded(neo4j_driver: object) -> None:
    await _seed(neo4j_driver)
    people = await enumerate_by_type(neo4j_driver, EnumerateInput(node_type="Person"))
    # mallory is merged → excluded; alice + bob remain.
    assert people.value.total_count == 2
    assert sorted(n.id for n in people.value.nodes) == ["alice-chen", "bob"]

    services = await enumerate_by_type(neo4j_driver, EnumerateInput(node_type="Service"))
    # old-svc is deprecated → excluded by the active default.
    assert sorted(n.id for n in services.value.nodes) == ["orphan-svc", "payments-api"]

    decisions = await enumerate_by_type(neo4j_driver, EnumerateInput(node_type="Decision"))
    assert [n.id for n in decisions.value.nodes] == ["Active one"]  # D-2 superseded excluded


async def test_status_all_and_deprecated(neo4j_driver: object) -> None:
    await _seed(neo4j_driver)
    all_svc = await enumerate_by_type(
        neo4j_driver, EnumerateInput(node_type="Service", status="all")
    )
    assert all_svc.value.total_count == 3  # includes the deprecated one, excludes none merged

    dep_svc = await enumerate_by_type(
        neo4j_driver, EnumerateInput(node_type="Service", status="deprecated")
    )
    assert [n.id for n in dep_svc.value.nodes] == ["old-svc"]


async def test_has_no_edge_finds_orphans(neo4j_driver: object) -> None:
    await _seed(neo4j_driver)
    orphans = await enumerate_by_type(
        neo4j_driver, EnumerateInput(node_type="Service", has_no_edge="OWNED_BY")
    )
    # payments-api has an owner; orphan-svc does not; old-svc is deprecated (filtered out).
    assert [n.id for n in orphans.value.nodes] == ["orphan-svc"]


async def test_team_filter_is_case_insensitive(neo4j_driver: object) -> None:
    await _seed(neo4j_driver)
    members = await enumerate_by_type(
        neo4j_driver, EnumerateInput(node_type="Person", team_filter="payments")
    )
    assert [n.id for n in members.value.nodes] == ["alice-chen"]


async def test_order_by_valid_from_desc(neo4j_driver: object) -> None:
    await _seed(neo4j_driver)
    result = await enumerate_by_type(
        neo4j_driver,
        EnumerateInput(node_type="Decision", status="all", order_by="valid_from_desc"),
    )
    # D-2 (2026-03) before D-1 (2026-01).
    assert [n.name for n in result.value.nodes] == ["Superseded one", "Active one"]


async def test_limit_and_total_count(neo4j_driver: object) -> None:
    await _seed(neo4j_driver)
    result = await enumerate_by_type(
        neo4j_driver, EnumerateInput(node_type="Person", status="all", limit=1)
    )
    assert result.value.total_count == 2  # pre-limit
    assert result.value.returned_count == 1  # post-limit
    assert len(result.value.nodes) == 1


async def test_extra_fields_and_provenance(neo4j_driver: object) -> None:
    await _seed(neo4j_driver)
    people = await enumerate_by_type(neo4j_driver, EnumerateInput(node_type="Person"))
    alice = next(n for n in people.value.nodes if n.id == "alice-chen")
    assert alice.extra_fields.get("email") == "a@x.io"
    assert alice.extra_fields.get("handle") == "@alice"
    assert "e1" in alice.source_event_ids
    assert "e1" in people.provenance.all_event_ids
