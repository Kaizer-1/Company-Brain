"""Real-Neo4j test for KQ2 — temporal contradiction (Phase 3B)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.queries.kq2_temporal_contradiction import find_contradictions
from app.synthetic.company import REFERENCE_NOW

pytestmark = pytest.mark.asyncio


async def _seed(driver: object) -> None:
    recent = (REFERENCE_NOW - timedelta(days=22)).isoformat()
    old = (REFERENCE_NOW - timedelta(days=100)).isoformat()
    async with driver.session() as s:  # type: ignore[attr-defined]
        await (
            await s.run(
                """
                CREATE (d5:Decision {id:'D-0005', title:'stay on legacy-auth', status:'active', source_event_ids:['ed5']})
                CREATE (d9:Decision {id:'D-0099', title:'old policy', status:'active', source_event_ids:['ed9']})
                CREATE (d4:Decision {id:'D-0004', title:'superseded thing', status:'superseded', source_event_ids:['ed4']})
                CREATE (mr:Message {id:'slack:mr', status:'active', content:'re D-0005 we use auth-service now', created_at:datetime($recent), source_event_ids:['emr']})
                CREATE (mo:Message {id:'slack:mo', status:'active', content:'re D-0099 disagree', created_at:datetime($old), source_event_ids:['emo']})
                CREATE (ms:Message {id:'slack:ms', status:'active', content:'re D-0004 nope', created_at:datetime($recent), source_event_ids:['ems']})
                CREATE (mr)-[:CONTRADICTS {source_event_id:'ec1', confidence:0.9}]->(d5)
                CREATE (mo)-[:CONTRADICTS {source_event_id:'ec2', confidence:0.9}]->(d9)
                CREATE (ms)-[:CONTRADICTS {source_event_id:'ec3', confidence:0.9}]->(d4)
                """,
                recent=recent,
                old=old,
            )
        ).consume()


async def test_kq2_returns_active_decision_with_recent_contradiction(neo4j_driver: object) -> None:
    await _seed(neo4j_driver)
    result = await find_contradictions(neo4j_driver, window=timedelta(days=30))
    decisions = {c.decision_id for c in result.value}
    assert "D-0005" in decisions
    assert {"ec1", "emr"} <= set(result.provenance.all_event_ids)


async def test_kq2_excludes_out_of_window(neo4j_driver: object) -> None:
    await _seed(neo4j_driver)
    result = await find_contradictions(neo4j_driver, window=timedelta(days=30))
    assert "D-0099" not in {c.decision_id for c in result.value}  # contradicted 100d ago


async def test_kq2_excludes_superseded_decision(neo4j_driver: object) -> None:
    await _seed(neo4j_driver)
    result = await find_contradictions(neo4j_driver, window=timedelta(days=30))
    assert "D-0004" not in {c.decision_id for c in result.value}  # not active
