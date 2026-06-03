"""Repository for the ``events`` table.

All SQL for the events table lives here.  Returns Pydantic DTOs; never returns
raw SQLAlchemy ORM instances to callers.
"""

import uuid
from datetime import datetime

from click import DateTime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.base import Repository
from app.models.events import Event
from app.models.enums import SourceType
from app.schemas.postgres import EventCreate, EventDTO
from app.models.base import Base, utc_now

def _to_dto(row: Event) -> EventDTO:
    return EventDTO(
        id=row.id,
        source_type=row.source_type,
        source_external_id=row.source_external_id,
        content=row.content,
        source_metadata=row.source_metadata,
        created_at=row.created_at,
        ingested_at=row.ingested_at,
        content_hash=row.content_hash,
    )


class EventRepository(Repository[Event]):
    """Read and write operations for the ``events`` table."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def get_by_id(self, event_id: uuid.UUID) -> EventDTO | None:
        """Return the event with the given UUID, or None if not found."""
        result = await self._session.execute(
            select(Event).where(Event.id == event_id)
        )
        row = result.scalar_one_or_none()
        return _to_dto(row) if row is not None else None

    async def get_by_source(
        self, source_type: SourceType, source_external_id: str
    ) -> EventDTO | None:
        """Return the event matching the source pair, or None.

        Uses the unique index ``uq_events_source`` for a single-row lookup.
        """
        result = await self._session.execute(
            select(Event).where(
                Event.source_type == source_type,
                Event.source_external_id == source_external_id,
            )
        )
        row = result.scalar_one_or_none()
        return _to_dto(row) if row is not None else None

    async def get_by_content_hash(self, content_hash: str) -> EventDTO | None:
        """Return an event with the given SHA-256 content hash, or None.

        Used for near-duplicate detection before inserting a new event.
        """
        result = await self._session.execute(
            select(Event).where(Event.content_hash == content_hash)
        )
        row = result.scalar_one_or_none()
        return _to_dto(row) if row is not None else None

    async def create(self, event_data: EventCreate) -> EventDTO:
        """Insert a new event row and return the persisted DTO.

        Raises ``sqlalchemy.exc.IntegrityError`` if the (source_type,
        source_external_id) pair already exists — the caller must catch this
        to handle duplicate-ingest gracefully.
        """
        row = Event(
            source_type=event_data.source_type,
            source_external_id=event_data.source_external_id,
            content=event_data.content,
            source_metadata=event_data.source_metadata,
            created_at=event_data.created_at,
            content_hash=event_data.content_hash,
        )
        self._session.add(row)
        await self._session.flush()
        return _to_dto(row)

    async def list_by_source_type(self, source_type: SourceType) -> list[EventDTO]:
        """Return all events of a given source type, ordered by send time ascending.

        Used by the Phase-3B contradiction pass to ingest Slack-style events as Message
        nodes (the graph schema's Message atoms are created mechanically from events).
        """
        result = await self._session.execute(
            select(Event)
            .where(Event.source_type == source_type)
            .order_by(Event.created_at.asc())
        )
        return [_to_dto(row) for row in result.scalars().all()]

    async def list_since(self, since: datetime) -> list[EventDTO]:
        """Return all events with ``created_at >= since``, ordered ascending.

        Used by the temporal contradiction detection query (Killer Query 2) to
        find messages created in a recent time window.
        """
        result = await self._session.execute(
            select(Event)
            .where(Event.created_at >= since)
            .order_by(Event.created_at.asc())
        )
        return [_to_dto(row) for row in result.scalars().all()]
