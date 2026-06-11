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
from app.ingestion.schemas import IngestionRunDTO, IngestionRunUpsert
from app.models.ingestion_runs import IngestionRun

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


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


class IngestionRunRepository(Repository[IngestionRun]):
    """Read and upsert operations for the ``ingestion_runs`` table."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

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
