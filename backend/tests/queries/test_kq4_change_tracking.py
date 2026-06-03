"""Real-Neo4j test for KQ4 — change tracking (Phase 3B)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.queries.kq4_change_tracking import track_changes
from app.synthetic.company import REFERENCE_NOW

pytestmark = pytest.mark.asyncio


async def _seed(driver: object) -> None:
    vf_d6 = (REFERENCE_NOW - timedelta(days=85)).isoformat()
    vf_d10 = (REFERENCE_NOW - timedelta(days=25)).isoformat()
    vf_d4 = (REFERENCE_NOW - timedelta(days=150)).isoformat()  # outside the 90d window
    async with driver.session() as s:  # type: ignore[attr-defined]
        await (
            await s.run(
                """
                CREATE (aus:Service {canonical_name:'auth-service', id:'auth-service', status:'active', source_event_ids:['ea']})
                CREATE (d6:Decision {id:'D-0006', title:'Deprecate legacy-auth', status:'active', valid_from:datetime($vf6), source_event_ids:['e6']})
                CREATE (d10:Decision {id:'D-0010', title:'Move to JWT', status:'active', valid_from:datetime($vf10), source_event_ids:['e10']})
                CREATE (d4:Decision {id:'D-0004', title:'session model', status:'superseded', valid_from:datetime($vf4), source_event_ids:['e4']})
                CREATE (alice:Person {canonical_id:'alice-chen', id:'alice-chen', status:'active'})
                CREATE (jordan:Person {canonical_id:'jordan-wells', id:'jordan-wells', status:'active'})
                CREATE (d6)-[:DEPRECATES {source_event_id:'r6'}]->(:System {canonical_name:'legacy-auth', id:'legacy-auth', status:'active'})
                CREATE (d6)-[:ABOUT {source_event_id:'r6b'}]->(aus)
                CREATE (d10)-[:ABOUT {source_event_id:'r10'}]->(aus)
                CREATE (d4)-[:ABOUT {source_event_id:'r4'}]->(aus)
                CREATE (d6)-[:APPROVED_BY {source_event_id:'a6'}]->(jordan)
                CREATE (d10)-[:APPROVED_BY {source_event_id:'a10'}]->(alice)
                CREATE (d10)-[:SUPERSEDES {source_event_id:'s10'}]->(d4)
                """,
                vf6=vf_d6,
                vf10=vf_d10,
                vf4=vf_d4,
            )
        ).consume()


async def test_kq4_returns_quarter_decisions_newest_first(neo4j_driver: object) -> None:
    await _seed(neo4j_driver)
    result = await track_changes(neo4j_driver, target_name="auth-service", window=timedelta(days=90))
    ids = [c.decision_id for c in result.value.changes]
    assert ids == ["D-0010", "D-0006"]  # newest first; D-0004 (150d) excluded


async def test_kq4_includes_approvers_and_supersession(neo4j_driver: object) -> None:
    await _seed(neo4j_driver)
    result = await track_changes(neo4j_driver, target_name="auth-service", window=timedelta(days=90))
    by_id = {c.decision_id: c for c in result.value.changes}
    assert by_id["D-0010"].approvers == ["alice-chen"]
    assert by_id["D-0006"].approvers == ["jordan-wells"]
    assert by_id["D-0010"].supersedes == ["D-0004"]


async def test_kq4_provenance_has_node_and_edge_events(neo4j_driver: object) -> None:
    await _seed(neo4j_driver)
    result = await track_changes(neo4j_driver, target_name="auth-service", window=timedelta(days=90))
    events = set(result.provenance.all_event_ids)
    assert {"e6", "e10", "a10", "s10"} <= events
