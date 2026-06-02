"""Merger against a real Neo4j + Postgres: the MERGE_INTO edge, tombstone, and provenance union."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.db.repositories.resolution import MergeDecisionRepository
from app.models.enums import MergeDecisionType, NodeType
from app.resolution.merger import Merger, pick_winner
from app.resolution.models import CandidatePair, ResolvableNode

if TYPE_CHECKING:
    from neo4j import AsyncDriver
    from sqlalchemy.ext.asyncio import AsyncSession


async def _seed_person(driver: AsyncDriver, node_id: str, events: list[str]) -> None:
    async with driver.session() as s:
        await (
            await s.run(
                "MERGE (n:Person {canonical_id: $id}) "
                "SET n.id = $id, n.source_event_ids = $events, n.status = 'active'",
                id=node_id, events=events,
            )
        ).consume()


async def _node(driver: AsyncDriver, node_id: str) -> dict[str, object]:
    async with driver.session() as s:
        result = await s.run(
            "MATCH (n:Person {canonical_id: $id}) RETURN properties(n) AS p", id=node_id
        )
        record = await result.single()
        return dict(record["p"]) if record else {}


def test_pick_winner_prefers_more_provenance_then_lexicographic() -> None:
    a = ResolvableNode(node_type=NodeType.Person, node_id="alice-chen", source_event_ids=("e1", "e2"))
    b = ResolvableNode(node_type=NodeType.Person, node_id="al", source_event_ids=("e3",))
    winner, loser = pick_winner(a, b)
    assert winner.node_id == "alice-chen" and loser.node_id == "al"
    # tie -> smaller id wins
    c = ResolvableNode(node_type=NodeType.Person, node_id="zed", source_event_ids=("x",))
    d = ResolvableNode(node_type=NodeType.Person, node_id="abe", source_event_ids=("y",))
    winner2, loser2 = pick_winner(c, d)
    assert winner2.node_id == "abe" and loser2.node_id == "zed"


async def test_merge_writes_edge_tombstones_loser_and_unions_provenance(
    neo4j_driver: AsyncDriver, db_session: AsyncSession
) -> None:
    await _seed_person(neo4j_driver, "alice-chen", ["e1", "e2"])
    await _seed_person(neo4j_driver, "al", ["e3"])

    a = ResolvableNode(node_type=NodeType.Person, node_id="alice-chen", source_event_ids=("e1", "e2"))
    b = ResolvableNode(node_type=NodeType.Person, node_id="al", source_event_ids=("e3",))
    pair = CandidatePair(node_a=a, node_b=b, similarity=0.81)

    repo = MergeDecisionRepository(db_session)
    merger = Merger(neo4j_driver, repo)
    await merger.apply_decision(
        pair, decision=MergeDecisionType.auto_merge, tier=1,
        confidence=0.99, rules_matched=["known_alias"],
    )

    # Winner accumulated provenance; loser tombstoned.
    winner = await _node(neo4j_driver, "alice-chen")
    loser = await _node(neo4j_driver, "al")
    assert sorted(winner["source_event_ids"]) == ["e1", "e2", "e3"]
    assert loser["status"] == "merged"

    # MERGE_INTO edge loser -> winner with tier/confidence.
    async with neo4j_driver.session() as s:
        result = await s.run(
            "MATCH (l:Person {canonical_id: 'al'})-[r:MERGE_INTO]->(w:Person {canonical_id: 'alice-chen'}) "
            "RETURN r.tier AS tier, r.confidence AS confidence"
        )
        edge = await result.single()
    assert edge is not None
    assert edge["tier"] == 1
    assert edge["confidence"] == 0.99

    # Audit row recorded.
    rows = await repo.list_for_type(NodeType.Person)
    assert len(rows) == 1
    row = rows[0]
    assert row.decision == MergeDecisionType.auto_merge
    assert row.source_node_id == "al"
    assert row.target_node_id == "alice-chen"
    assert row.rules_matched == ["known_alias"]


async def test_dry_run_writes_nothing(
    neo4j_driver: AsyncDriver, db_session: AsyncSession
) -> None:
    await _seed_person(neo4j_driver, "alice-chen", ["e1"])
    await _seed_person(neo4j_driver, "al", ["e2"])
    a = ResolvableNode(node_type=NodeType.Person, node_id="alice-chen", source_event_ids=("e1",))
    b = ResolvableNode(node_type=NodeType.Person, node_id="al", source_event_ids=("e2",))
    pair = CandidatePair(node_a=a, node_b=b, similarity=0.81)

    repo = MergeDecisionRepository(db_session)
    merger = Merger(neo4j_driver, repo, dry_run=True)
    await merger.apply_decision(
        pair, decision=MergeDecisionType.auto_merge, tier=1,
        confidence=0.99, rules_matched=["known_alias"],
    )

    loser = await _node(neo4j_driver, "al")
    assert loser["status"] == "active"  # untouched
    assert await repo.list_for_type(NodeType.Person) == []
