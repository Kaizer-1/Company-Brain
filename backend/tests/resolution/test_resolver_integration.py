"""End-to-end resolver against real Neo4j + Postgres: a seeded alias group is collapsed.

Seeds five Person nodes — Alice's four surface forms plus an unrelated person — runs
``resolve_graph`` (Tier 1 only; no LLM), and asserts the alias group collapses to one
canonical node, the unrelated person is untouched, and every decision is audited.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.db.repositories.resolution import MergeDecisionRepository
from app.models.enums import MergeDecisionType, NodeType
from app.resolution.resolver import resolve_graph

if TYPE_CHECKING:
    from neo4j import AsyncDriver
    from sqlalchemy.ext.asyncio import AsyncSession

# Alice's four graph-node slugs (one per surface form) plus an unrelated person.
_ALICE_FORMS = ["alice-chen", "alice-chen-northwind-io", "alice", "al"]
_OTHER = "ben"


async def _seed(driver: AsyncDriver) -> None:
    async with driver.session() as s:
        await (await s.run("MATCH (n) WHERE NOT n:_Migration DETACH DELETE n")).consume()
        for nid in [*_ALICE_FORMS, _OTHER]:
            await (
                await s.run(
                    "MERGE (n:Person {canonical_id: $id}) "
                    "SET n.id = $id, n.source_event_ids = [$evt], n.status = 'active'",
                    id=nid, evt=f"{nid}-evt",
                )
            ).consume()


async def _active_person_ids(driver: AsyncDriver) -> list[str]:
    async with driver.session() as s:
        result = await s.run(
            "MATCH (n:Person) WHERE coalesce(n.status,'active') <> 'merged' "
            "RETURN n.canonical_id AS id ORDER BY id"
        )
        return [record["id"] async for record in result]


async def test_resolve_collapses_alias_group_and_audits(
    neo4j_driver: AsyncDriver, db_session: AsyncSession
) -> None:
    await _seed(neo4j_driver)

    report = await resolve_graph(
        neo4j_driver, db_session, node_types=["Person"], client=None
    )
    await db_session.flush()

    # Four Alice forms collapse to exactly one active node; Ben is untouched. Two active total.
    active = await _active_person_ids(neo4j_driver)
    assert len(active) == 2
    assert _OTHER in active
    assert sum(1 for a in active if a in _ALICE_FORMS) == 1

    # Every Alice pair auto-merged (C(4,2) = 6); 10 candidate pairs in total (C(5,2)).
    person = report.by_type["Person"]
    assert person.node_count == 5
    assert person.candidate_pairs == 10
    assert person.auto_merges == 6

    # Audit rows: 6 auto-merges recorded; Ben never merged.
    rows = await MergeDecisionRepository(db_session).list_for_type(NodeType.Person)
    auto = [r for r in rows if r.decision == MergeDecisionType.auto_merge]
    assert len(auto) == 6
    assert all(_OTHER not in (r.source_node_id, r.target_node_id) for r in auto)


async def test_resolve_is_idempotent(
    neo4j_driver: AsyncDriver, db_session: AsyncSession
) -> None:
    await _seed(neo4j_driver)
    await resolve_graph(neo4j_driver, db_session, node_types=["Person"], client=None)
    await db_session.flush()
    first = await _active_person_ids(neo4j_driver)

    # Re-running must not merge already-merged nodes again (they are excluded by load_nodes).
    report2 = await resolve_graph(neo4j_driver, db_session, node_types=["Person"], client=None)
    await db_session.flush()
    second = await _active_person_ids(neo4j_driver)

    assert first == second
    assert report2.by_type["Person"].auto_merges == 0  # nothing left to merge
