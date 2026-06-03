"""Apply a resolution decision: write the MERGE_INTO edge and the audit row (Phase 3A).

Merges are non-destructive (ADR 0014): the loser is tombstoned with ``status = "merged"`` and
linked to the canonical winner by ``(loser)-[:MERGE_INTO {confidence, tier, created_at}]->(winner)``;
nothing is deleted. The winner absorbs the union of both nodes' ``source_event_ids`` so it
carries the merged entity's full provenance. Every decision — merge or not — is recorded in
``merge_decisions`` (ADR 0015).

In ``dry_run`` mode nothing is written to Neo4j or Postgres; decisions are only logged.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from app.models.enums import MergeDecisionType
from app.schemas.postgres import MergeDecisionCreate

if TYPE_CHECKING:
    from neo4j import AsyncDriver

    from app.db.repositories.resolution import MergeDecisionRepository
    from app.resolution.models import CandidatePair, ResolvableNode

log = structlog.get_logger(__name__)

_MERGE_DECISIONS = frozenset(
    {
        MergeDecisionType.auto_merge,
        MergeDecisionType.llm_merge,
        # Phase 3B (ADR 0017): multi-source Decision content-consolidation also writes a
        # MERGE_INTO edge, via the same non-destructive mechanism as entity merges.
        MergeDecisionType.content_merge,
    }
)


def pick_winner(a: ResolvableNode, b: ResolvableNode) -> tuple[ResolvableNode, ResolvableNode]:
    """Return ``(winner, loser)``: more source_event_ids wins; ties broken by smaller node_id.

    Determinism matters — the same graph must resolve the same way every run — so the
    tie-break is lexicographic on the stable ``node_id``.
    """
    if len(a.source_event_ids) != len(b.source_event_ids):
        winner, loser = (a, b) if len(a.source_event_ids) > len(b.source_event_ids) else (b, a)
    else:
        winner, loser = (a, b) if a.node_id <= b.node_id else (b, a)
    return winner, loser


class Merger:
    """Writes merge edges + tombstones to Neo4j and decision rows to Postgres."""

    def __init__(
        self,
        driver: AsyncDriver,
        decision_repo: MergeDecisionRepository,
        *,
        dry_run: bool = False,
    ) -> None:
        self._driver = driver
        self._repo = decision_repo
        self._dry_run = dry_run

    async def apply_decision(
        self,
        pair: CandidatePair,
        *,
        decision: MergeDecisionType,
        tier: int,
        confidence: float,
        rules_matched: list[str],
        llm_reasoning: str | None = None,
        llm_model: str | None = None,
    ) -> None:
        """Effect one decision: merge the graph if applicable, then record the audit row."""
        if decision in _MERGE_DECISIONS:
            winner, loser = pick_winner(pair.node_a, pair.node_b)
            source_id, target_id = loser.node_id, winner.node_id
            if not self._dry_run:
                await self._write_merge_edge(
                    winner, loser, confidence=confidence, tier=tier
                )
        else:
            # No merge: preserve the pair's given order for the audit row.
            source_id, target_id = pair.node_a.node_id, pair.node_b.node_id

        log.info(
            "resolution_decision",
            node_type=pair.node_a.node_type.value,
            decision=decision.value,
            tier=tier,
            source=source_id,
            target=target_id,
            similarity=round(pair.similarity, 3),
            rules=rules_matched,
            dry_run=self._dry_run,
        )

        if self._dry_run:
            return

        await self._repo.record(
            MergeDecisionCreate(
                source_node_id=source_id,
                target_node_id=target_id,
                node_type=pair.node_a.node_type,
                decision=decision,
                tier=tier,
                embedding_similarity=pair.similarity,
                rules_matched=rules_matched,
                llm_reasoning=llm_reasoning,
                llm_model=llm_model,
            )
        )

    async def _write_merge_edge(
        self,
        winner: ResolvableNode,
        loser: ResolvableNode,
        *,
        confidence: float,
        tier: int,
    ) -> None:
        """MERGE the loser→winner edge, union provenance onto the winner, tombstone the loser.

        The provenance union reads the winner's *live* ``source_event_ids`` and appends only
        the loser's ids that are not already present, so a winner that absorbs several losers
        across the run accumulates correctly (computing the union from the in-memory snapshot
        would clobber earlier merges).
        """
        label = winner.node_type.value  # both nodes share a type
        key_field = winner.key_field
        created_at = datetime.now(UTC).isoformat()
        loser_event_ids = list(loser.source_event_ids)
        # label/key_field come from the closed NodeType vocabulary — safe to interpolate
        # where Cypher forbids parameters.
        query = (
            f"MATCH (winner:{label} {{{key_field}: $winner_id}}) "
            f"MATCH (loser:{label} {{{key_field}: $loser_id}}) "
            "SET winner.source_event_ids = coalesce(winner.source_event_ids, []) + "
            "    [x IN $loser_event_ids WHERE NOT x IN coalesce(winner.source_event_ids, [])] "
            "MERGE (loser)-[r:MERGE_INTO]->(winner) "
            "ON CREATE SET r.created_at = datetime($created_at) "
            "SET r.confidence = $confidence, r.tier = $tier, "
            "    loser.status = 'merged'"
        )
        async with self._driver.session() as session:
            await (
                await session.run(
                    query,
                    winner_id=winner.node_id,
                    loser_id=loser.node_id,
                    loser_event_ids=loser_event_ids,
                    created_at=created_at,
                    confidence=confidence,
                    tier=tier,
                )
            ).consume()
