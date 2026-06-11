"""Create Message nodes from Slack-style events (Phase 3B; ADR 0019).

The graph schema's ``Message`` is "created mechanically from the event itself" — one node per
Slack event, never extracted. Nothing produced these before Phase 3B, so KQ2 had no discussion
corpus to compare against decisions. This module backfills them: it reads every
``slack_message`` event from Postgres and idempotently ``MERGE``s a ``:Message`` node keyed on
``id = "slack:<external_id>"`` (matching the schema's ``source_id:external_id`` identity).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from app.db.repositories.events import EventRepository
from app.models.enums import SourceType

if TYPE_CHECKING:
    from neo4j import AsyncDriver
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.schemas.postgres import EventDTO

log = structlog.get_logger(__name__)

_MERGE_MESSAGE = (
    "MERGE (m:Message {id: $id}) "
    "ON CREATE SET m.source_id = $source_id, m.external_id = $external_id, "
    "  m.content = $content, m.created_at = datetime($created_at), "
    "  m.source_event_ids = [$eid], m.status = 'active' "
    "ON MATCH SET m.content = $content, m.source_event_ids = "
    "  CASE WHEN $eid IN m.source_event_ids THEN m.source_event_ids "
    "       ELSE m.source_event_ids + $eid END"
)


async def ingest_messages(driver: AsyncDriver, session: AsyncSession) -> int:
    """MERGE one Message node per slack_message event; return the count processed."""
    events = EventRepository(session)
    slack_events = await events.list_by_source_type(SourceType.slack_message)
    async with driver.session() as s:
        for ev in slack_events:
            await (
                await s.run(
                    _MERGE_MESSAGE,
                    id=f"slack:{ev.source_external_id}",
                    source_id="slack",
                    external_id=ev.source_external_id,
                    content=ev.content,
                    created_at=ev.created_at.isoformat(),
                    eid=str(ev.id),
                )
            ).consume()
    log.info("messages_ingested", count=len(slack_events))
    return len(slack_events)


async def ingest_one_message(driver: AsyncDriver, event: EventDTO) -> str:
    """MERGE the single Message node for one slack_message event; return its node id.

    The scoped counterpart of ``ingest_messages`` used by live ingestion (Phase 5A): a new
    slack event's Message atom must exist before scoped contradiction detection can compare it
    against the active decisions. Uses the same idempotent ``MERGE`` keyed on
    ``slack:<external_id>``, so calling it then later running the batch pass is a no-op.
    """
    node_id = f"slack:{event.source_external_id}"
    async with driver.session() as s:
        await (
            await s.run(
                _MERGE_MESSAGE,
                id=node_id,
                source_id="slack",
                external_id=event.source_external_id,
                content=event.content,
                created_at=event.created_at.isoformat(),
                eid=str(event.id),
            )
        ).consume()
    log.info("message_ingested_one", message_id=node_id, event_id=str(event.id))
    return node_id
