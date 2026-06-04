"""Merge-decision audit endpoint (Phase 3C).

GET /api/audit/merge-decisions
    ?tier=1|2|3                                               optional tier filter
    &decision=auto_merge|llm_merge|llm_no_merge|...           optional decision-type filter
    &node_type=Person|Service|System|Team|Decision            optional node-type filter
    &limit=50
    &offset=0

Returns paginated merge_decisions rows, newest first. This page lets an interviewer
inspect every AI resolution decision with its tier, similarity score, and LLM reasoning —
the "I can defend every choice the system made" claim made real.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from app.db.repositories.resolution import MergeDecisionRepository
from app.models.enums import MergeDecisionType, NodeType
from app.schemas.postgres import MergeDecisionDTO

router = APIRouter(prefix="/api/audit", tags=["audit"])
log = structlog.get_logger(__name__)


class MergeDecisionPage(BaseModel):
    """A paginated slice of the merge_decisions log."""

    items: list[MergeDecisionDTO]
    total: int
    limit: int
    offset: int


@router.get(
    "/merge-decisions",
    response_model=MergeDecisionPage,
    summary="Paginated merge-decision audit log with optional tier/decision/node_type filters.",
)
async def list_merge_decisions(
    request: Request,
    tier: int | None = Query(None, ge=1, le=3, description="Resolution tier (1/2/3)."),
    decision: MergeDecisionType | None = Query(None, description="Decision outcome type."),
    node_type: NodeType | None = Query(None, description="Node type being resolved."),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> MergeDecisionPage:
    """Return merge decisions sorted newest-first with optional filters.

    The full unfiltered log is loaded once per request (the table is small for the
    demo corpus) and sliced in Python so the total count is always accurate even with
    filters applied. A production system would push the pagination into SQL.
    """
    async with request.app.state.session_factory() as session:
        repo = MergeDecisionRepository(session)
        all_rows = await repo.list_all_filtered(
            tier=tier, decision=decision, node_type=node_type
        )

    total = len(all_rows)
    page = all_rows[offset : offset + limit]
    log.info(
        "audit_fetched",
        total=total,
        tier=tier,
        decision=str(decision) if decision else None,
        offset=offset,
        returned=len(page),
    )
    return MergeDecisionPage(items=page, total=total, limit=limit, offset=offset)
