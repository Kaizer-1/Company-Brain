"""Event detail endpoint (Phase 3C).

GET /api/events/{event_id} — returns the full raw event row from Postgres.
Used by the frontend's source-event modals (provenance drilldown) so every
graph element can be traced back to the raw text that asserted it.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, HTTPException, Request

from app.db.repositories.events import EventRepository
from app.schemas.postgres import EventDTO

router = APIRouter(prefix="/api/events", tags=["events"])
log = structlog.get_logger(__name__)


@router.get(
    "/{event_id}",
    response_model=EventDTO,
    summary="Retrieve a single raw event by its UUID.",
)
async def get_event(request: Request, event_id: uuid.UUID) -> EventDTO:
    """Return the full Postgres events row for one UUID.

    Provides the raw source text the extraction pipeline read when it wrote
    the graph element whose provenance links here. Called by the frontend's
    event-detail modal; a 404 indicates a broken provenance link.
    """
    async with request.app.state.session_factory() as session:
        repo = EventRepository(session)
        event = await repo.get_by_id(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail=f"Event {event_id!s} not found")
    log.info("event_fetched", event_id=str(event_id))
    return event
