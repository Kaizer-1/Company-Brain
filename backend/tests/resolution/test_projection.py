"""Real-Neo4j test: edge projection onto canonical winners (Phase 3B)."""

from __future__ import annotations

import pytest

from app.resolution.projection import project_resolved_edges

pytestmark = pytest.mark.asyncio


async def _run(driver: object, cypher: str, **params: object) -> None:
    async with driver.session() as s:  # type: ignore[attr-defined]
        await (await s.run(cypher, **params)).consume()


async def test_projection_moves_loser_edge_to_winner(neo4j_driver: object) -> None:
    # Winner 'diego' (more events) wins; loser 'diego-ramirez' carries the MEMBER_OF edge.
    await _run(
        neo4j_driver,
        """
        CREATE (w:Person {canonical_id:'diego', id:'diego', status:'active', source_event_ids:['e1','e2']})
        CREATE (l:Person {canonical_id:'diego-ramirez', id:'diego-ramirez', status:'merged', source_event_ids:['e3']})
        CREATE (t:Team {canonical_name:'payments', id:'payments', status:'active'})
        CREATE (l)-[:MERGE_INTO {tier:1}]->(w)
        CREATE (l)-[:MEMBER_OF {source_event_id:'e3'}]->(t)
        """,
    )
    created = await project_resolved_edges(neo4j_driver)
    assert created >= 1

    async with neo4j_driver.session() as s:  # type: ignore[attr-defined]
        rec = await (
            await s.run(
                "MATCH (w:Person {canonical_id:'diego'})-[:MEMBER_OF]->(t:Team {canonical_name:'payments'}) "
                "RETURN count(*) AS c"
            )
        ).single()
    assert rec["c"] == 1


async def test_projection_canonicalises_far_endpoint(neo4j_driver: object) -> None:
    # Edge on a loser pointing at another loser must land on winner->winner.
    await _run(
        neo4j_driver,
        """
        CREATE (sw:Service {canonical_name:'payments-api', id:'payments-api', status:'active', source_event_ids:['e1','e2']})
        CREATE (sl:Service {canonical_name:'payments', id:'payments', status:'merged', source_event_ids:['e3']})
        CREATE (syw:System {canonical_name:'legacy-auth', id:'legacy-auth', status:'active', source_event_ids:['e4','e5']})
        CREATE (syl:System {canonical_name:'the-legacy-auth-system', id:'the-legacy-auth-system', status:'merged', source_event_ids:['e6']})
        CREATE (sl)-[:MERGE_INTO {tier:1}]->(sw)
        CREATE (syl)-[:MERGE_INTO {tier:1}]->(syw)
        CREATE (sl)-[:DEPENDS_ON {source_event_id:'e6'}]->(syl)
        """,
    )
    await project_resolved_edges(neo4j_driver)
    async with neo4j_driver.session() as s:  # type: ignore[attr-defined]
        rec = await (
            await s.run(
                "MATCH (a:Service {canonical_name:'payments-api'})-[:DEPENDS_ON]->"
                "(b:System {canonical_name:'legacy-auth'}) RETURN count(*) AS c"
            )
        ).single()
    assert rec["c"] == 1


async def test_projection_is_idempotent(neo4j_driver: object) -> None:
    await _run(
        neo4j_driver,
        """
        CREATE (w:Person {canonical_id:'diego', id:'diego', status:'active', source_event_ids:['e1']})
        CREATE (l:Person {canonical_id:'diego-ramirez', id:'diego-ramirez', status:'merged', source_event_ids:['e2']})
        CREATE (t:Team {canonical_name:'payments', id:'payments', status:'active'})
        CREATE (l)-[:MERGE_INTO {tier:1}]->(w)
        CREATE (l)-[:MEMBER_OF {source_event_id:'e2'}]->(t)
        """,
    )
    await project_resolved_edges(neo4j_driver)
    second = await project_resolved_edges(neo4j_driver)
    assert second == 0  # nothing new on the second pass
