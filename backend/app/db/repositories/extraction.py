"""Repository for the ``extraction_runs`` table.

Tracks every extraction pipeline invocation so that failures are observable,
re-extraction is auditable, and model-upgrade workflows can identify stale runs.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.base import Repository
from app.models.extraction import ExtractionRun
from app.models.enums import ExtractionStatus
from app.schemas.postgres import ExtractionRunCreate, ExtractionRunDTO


def _to_dto(row: ExtractionRun) -> ExtractionRunDTO:
    return ExtractionRunDTO(
        id=row.id,
        event_id=row.event_id,
        model_name=row.model_name,
        model_version=row.model_version,
        prompt_hash=row.prompt_hash,
        started_at=row.started_at,
        completed_at=row.completed_at,
        status=row.status,
        extracted_node_count=row.extracted_node_count,
        extracted_edge_count=row.extracted_edge_count,
        error_message=row.error_message,
    )


class ExtractionRunRepository(Repository[ExtractionRun]):
    """Read and write operations for the ``extraction_runs`` table."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def create_pending(self, data: ExtractionRunCreate) -> ExtractionRunDTO:
        """Insert a new extraction run in the ``failed`` status.

        Status is set to ``failed`` at creation as a safe default — a process
        crash between ``create_pending`` and ``mark_success`` leaves a failed
        row rather than an in-flight row with no terminal state.
        """
        row = ExtractionRun(
            event_id=data.event_id,
            model_name=data.model_name,
            model_version=data.model_version,
            prompt_hash=data.prompt_hash,
            started_at=data.started_at,
        )
        self._session.add(row)
        await self._session.flush()
        return _to_dto(row)

    async def mark_success(
        self,
        run_id: uuid.UUID,
        *,
        extracted_node_count: int,
        extracted_edge_count: int,
    ) -> ExtractionRunDTO | None:
        """Mark an extraction run as successful and record counts.

        Returns the updated DTO, or None if the run ID does not exist.
        """
        result = await self._session.execute(
            select(ExtractionRun).where(ExtractionRun.id == run_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        row.status = ExtractionStatus.success
        row.completed_at = datetime.now(UTC)
        row.extracted_node_count = extracted_node_count
        row.extracted_edge_count = extracted_edge_count
        row.error_message = None
        await self._session.flush()
        return _to_dto(row)

    async def mark_failed(
        self,
        run_id: uuid.UUID,
        *,
        error_message: str,
        extracted_node_count: int = 0,
        extracted_edge_count: int = 0,
        partial: bool = False,
    ) -> ExtractionRunDTO | None:
        """Mark an extraction run as failed (or partial) with an error message.

        Returns the updated DTO, or None if the run ID does not exist.
        """
        result = await self._session.execute(
            select(ExtractionRun).where(ExtractionRun.id == run_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        row.status = ExtractionStatus.partial if partial else ExtractionStatus.failed
        row.completed_at = datetime.now(UTC)
        row.error_message = error_message
        row.extracted_node_count = extracted_node_count
        row.extracted_edge_count = extracted_edge_count
        await self._session.flush()
        return _to_dto(row)

    async def latest_for_event(self, event_id: uuid.UUID) -> ExtractionRunDTO | None:
        """Return the most recently started extraction run for an event, or None.

        Uses the composite index ``ix_extraction_runs_event_started`` for
        efficiency.
        """
        result = await self._session.execute(
            select(ExtractionRun)
            .where(ExtractionRun.event_id == event_id)
            .order_by(ExtractionRun.started_at.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        return _to_dto(row) if row is not None else None
