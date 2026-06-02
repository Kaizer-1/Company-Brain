"""Repository for the ``merge_decisions`` audit table (Phase 3A).

Every entity-resolution attempt is recorded here (ADR 0015). The repository is deliberately
thin: an append-only ``record`` plus the read paths the eval and a future review UI need.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from app.db.repositories.base import Repository
from app.models.resolution import MergeDecision
from app.schemas.postgres import MergeDecisionCreate, MergeDecisionDTO

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.enums import NodeType


def _to_dto(row: MergeDecision) -> MergeDecisionDTO:
    return MergeDecisionDTO(
        id=row.id,
        source_node_id=row.source_node_id,
        target_node_id=row.target_node_id,
        node_type=row.node_type,
        decision=row.decision,
        tier=row.tier,
        embedding_similarity=row.embedding_similarity,
        rules_matched=list(row.rules_matched),
        llm_reasoning=row.llm_reasoning,
        llm_model=row.llm_model,
        created_at=row.created_at,
    )


class MergeDecisionRepository(Repository[MergeDecision]):
    """Append and read operations for the ``merge_decisions`` table."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def record(self, data: MergeDecisionCreate) -> MergeDecisionDTO:
        """Append one resolution decision. The log is append-only — never updated."""
        row = MergeDecision(
            source_node_id=data.source_node_id,
            target_node_id=data.target_node_id,
            node_type=data.node_type,
            decision=data.decision,
            tier=data.tier,
            embedding_similarity=data.embedding_similarity,
            rules_matched=list(data.rules_matched),
            llm_reasoning=data.llm_reasoning,
            llm_model=data.llm_model,
        )
        self._session.add(row)
        await self._session.flush()
        return _to_dto(row)

    async def list_for_type(self, node_type: NodeType) -> list[MergeDecisionDTO]:
        """Every decision for one node type, newest first (uses the composite index)."""
        result = await self._session.execute(
            select(MergeDecision)
            .where(MergeDecision.node_type == node_type)
            .order_by(MergeDecision.created_at.desc())
        )
        return [_to_dto(r) for r in result.scalars().all()]

    async def count_since(self, since: datetime) -> int:
        """Number of decisions recorded at or after ``since`` (audit/smoke checks)."""
        result = await self._session.execute(
            select(MergeDecision).where(MergeDecision.created_at >= since)
        )
        return len(result.scalars().all())