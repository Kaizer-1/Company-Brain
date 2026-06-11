"""Audit endpoints (Phase 3C + 5B).

GET /api/audit/merge-decisions
    ?tier=1|2|3                                               optional tier filter
    &decision=auto_merge|llm_merge|llm_no_merge|...           optional decision-type filter
    &node_type=Person|Service|System|Team|Decision            optional node-type filter
    &limit=50
    &offset=0

Returns paginated merge_decisions rows, newest first. This page lets an interviewer
inspect every AI resolution decision with its tier, similarity score, and LLM reasoning —
the "I can defend every choice the system made" claim made real.

GET /api/audit/ingestion-runs (Phase 5B)
    ?limit=20
    &before=<ISO datetime cursor>

Returns cursor-paginated ingestion runs, newest first, joined to their source events. Mirrors
the merge-decisions tab on the frontend: every live reconciliation the engine performed, with
its per-stage timeline, counts, cost, and duration. Makes the ingestion engine's history
visible to the demo audience and operators (Decision 1).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from app.db.repositories.ingestion_runs import IngestionRunRepository
from app.db.repositories.resolution import MergeDecisionRepository
from app.ingestion.schemas import IngestionRunPage
from app.models.enums import MergeDecisionType, NodeType
from app.schemas.postgres import MergeDecisionDTO

if TYPE_CHECKING:
    from datetime import datetime

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


@router.get(
    "/ingestion-runs",
    response_model=IngestionRunPage,
    summary="Cursor-paginated live-ingestion run history, newest first (Phase 5B).",
)
async def list_ingestion_runs(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    before: datetime | None = Query(
        None, description="Exclusive cursor: the previous page's next_cursor (started_at)."
    ),
) -> IngestionRunPage:
    """Return ingestion runs newest-first, joined to their events, cursor-paginated.

    Mirrors the merge-decisions audit endpoint but uses cursor (not offset) pagination because
    the ingestion feed grows from the head — a new run prepended between page loads would shift
    every offset. The frontend renders this as the "Ingestion runs" tab and a "Load more" button
    that passes ``next_cursor`` back as ``before``.
    """
    async with request.app.state.session_factory() as session:
        repo = IngestionRunRepository(session)
        page = await repo.list_paginated(limit=limit, before=before)
    log.info("ingestion_runs_fetched", returned=len(page.items), has_more=page.next_cursor is not None)
    return page
