"""Repository for the ``ingestion_runs`` table (Phase 5A).

One row per live-ingested event. The write path is an **upsert keyed on ``event_id``** (not an
append): re-ingesting the same event overwrites its reconciliation record in place, which keeps
the audit trail consistent with the idempotency contract (a replayed event has exactly one run
row, reflecting its latest reconciliation — ADR 0032). All SQL for the table lives here; the
repository returns Pydantic DTOs, never ORM instances.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.db.repositories.base import Repository
from app.ingestion.schemas import (
    IngestionRunDTO,
    IngestionRunPage,
    IngestionRunSummary,
    IngestionRunUpsert,
    StageResult,
)
from app.models.events import Event
from app.models.ingestion_runs import IngestionRun

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

_SNIPPET_CHARS = 140


def _to_dto(row: IngestionRun) -> IngestionRunDTO:
    return IngestionRunDTO(
        id=row.id,
        event_id=row.event_id,
        status=row.status,
        started_at=row.started_at,
        completed_at=row.completed_at,
        stages_json=list(row.stages_json),
        nodes_created_count=row.nodes_created_count,
        nodes_merged_count=row.nodes_merged_count,
        edges_created_count=row.edges_created_count,
        contradictions_count=row.contradictions_count,
        cost_usd=float(row.cost_usd),
        error=row.error,
    )


def _duration_ms(row: IngestionRun) -> float | None:
    """Wall-clock reconciliation time in ms, or None if the run never completed."""
    if row.completed_at is None:
        return None
    return round((row.completed_at - row.started_at).total_seconds() * 1000.0, 1)


def _to_summary(row: IngestionRun, *, source_kind: str, content: str) -> IngestionRunSummary:
    """Build the audit-tab row from a run joined to its event (Phase 5B)."""
    snippet = content.strip().replace("\n", " ")
    if len(snippet) > _SNIPPET_CHARS:
        snippet = snippet[: _SNIPPET_CHARS - 1].rstrip() + "…"
    return IngestionRunSummary(
        id=row.id,
        event_id=row.event_id,
        source_kind=source_kind,
        content_snippet=snippet,
        status=row.status,
        stages=[StageResult.model_validate(s) for s in row.stages_json],
        nodes_created_count=row.nodes_created_count,
        nodes_merged_count=row.nodes_merged_count,
        edges_created_count=row.edges_created_count,
        contradictions_count=row.contradictions_count,
        cost_usd=float(row.cost_usd),
        duration_ms=_duration_ms(row),
        started_at=row.started_at,
        completed_at=row.completed_at,
        error=row.error,
    )


class IngestionRunRepository(Repository[IngestionRun]):
    """Read and upsert operations for the ``ingestion_runs`` table."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def list_paginated(
        self, *, limit: int = 20, before: datetime | None = None
    ) -> IngestionRunPage:
        """Return ingestion runs newest-first, joined to their events, cursor-paginated.

        Sorted by ``started_at`` descending. ``before`` is an exclusive cursor (the previous
        page's ``next_cursor``); pass ``None`` for the first page. One extra row is fetched to
        decide whether a next page exists; if so its ``started_at`` is returned as the cursor.
        The join to ``events`` supplies ``source_kind`` and the content snippet the tab shows.
        """
        stmt = (
            select(IngestionRun, Event.source_type, Event.content)
            .join(Event, Event.id == IngestionRun.event_id)
            .order_by(IngestionRun.started_at.desc())
            .limit(limit + 1)
        )
        if before is not None:
            stmt = stmt.where(IngestionRun.started_at < before)

        result = await self._session.execute(stmt)
        rows = result.all()

        has_more = len(rows) > limit
        page_rows = rows[:limit]
        items = [
            _to_summary(run, source_kind=source_type.value, content=content)
            for run, source_type, content in page_rows
        ]
        next_cursor = page_rows[-1][0].started_at if has_more and page_rows else None
        return IngestionRunPage(items=items, next_cursor=next_cursor)

    async def get_by_event(self, event_id: uuid.UUID) -> IngestionRunDTO | None:
        """Return the ingestion run for an event, or None if it has not been ingested."""
        result = await self._session.execute(
            select(IngestionRun).where(IngestionRun.event_id == event_id)
        )
        row = result.scalar_one_or_none()
        return _to_dto(row) if row is not None else None

    async def upsert(self, data: IngestionRunUpsert) -> IngestionRunDTO:
        """Insert a new run, or overwrite the existing one for this ``event_id`` in place.

        The ``UNIQUE (event_id)`` constraint guarantees at most one row per event; on a replay
        we update that row rather than appending, so the audit reflects the latest reconcile.
        """
        result = await self._session.execute(
            select(IngestionRun).where(IngestionRun.event_id == data.event_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            row = IngestionRun(
                event_id=data.event_id,
                status=data.status,
                started_at=data.started_at,
                stages_json=data.stages_json,
            )
            self._session.add(row)
        else:
            row.status = data.status
            row.started_at = data.started_at
            row.stages_json = data.stages_json

        row.completed_at = data.completed_at
        row.nodes_created_count = data.nodes_created_count
        row.nodes_merged_count = data.nodes_merged_count
        row.edges_created_count = data.edges_created_count
        row.contradictions_count = data.contradictions_count
        row.cost_usd = Decimal(str(data.cost_usd))
        row.error = data.error

        await self._session.flush()
        return _to_dto(row)
