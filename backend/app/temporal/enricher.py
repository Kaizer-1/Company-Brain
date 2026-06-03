"""Populate the schema-reserved temporal fields on Decision nodes (Phase 3B; ADR 0016).

Extraction leaves ``valid_from``/``valid_to`` empty. This module walks every non-merged
Decision, sets ``valid_from`` to the earliest of its source events' timestamps (the issue date),
resets ``status='active'`` and ``valid_to=NULL``, then runs supersession detection to mark the
superseded decisions. The whole pass is idempotent: re-running recomputes the same values.

``valid_from`` provenance order: the earliest Postgres ``events.created_at`` among the
decision's ``source_event_ids`` (authoritative issue date). If none of the ids resolve to a
Postgres event (e.g. a hand-seeded test graph), it falls back to the node's own ``created_at``
property, which the graph writer set from the event timestamp.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import structlog

from app.db.repositories.events import EventRepository
from app.temporal.models import TemporalEnrichmentResult
from app.temporal.supersession import apply_supersessions

if TYPE_CHECKING:
    from datetime import datetime

    from neo4j import AsyncDriver
    from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)


async def enrich_temporal(driver: AsyncDriver, session: AsyncSession) -> TemporalEnrichmentResult:
    """Set valid_from/valid_to/status on all non-merged Decision nodes; return a report."""
    events = EventRepository(session)
    decisions = await _load_decisions(driver)
    result = TemporalEnrichmentResult(decisions_seen=len(decisions))

    for d in decisions:
        decision_id = str(d["id"])
        raw_ids = d.get("source_event_ids") or []
        source_ids = [str(x) for x in raw_ids] if isinstance(raw_ids, (list, tuple)) else []
        earliest = await _earliest_event_time(events, source_ids)
        if earliest is not None:
            await _set_valid_from(driver, decision_id, earliest.isoformat())
            result.valid_from_from_events += 1
        else:
            await _set_valid_from_from_node(driver, decision_id)
            result.valid_from_from_node += 1
            result.missing_provenance.append(decision_id)
        result.valid_from_set += 1

    edges, marked = await apply_supersessions(driver, events, decisions)
    result.supersedes_edges_written = edges
    result.superseded_marked = marked

    log.info(
        "temporal_enrichment_complete",
        decisions=result.decisions_seen,
        valid_from_set=result.valid_from_set,
        supersedes_edges=result.supersedes_edges_written,
        superseded=result.superseded_marked,
    )
    return result


async def _load_decisions(driver: AsyncDriver) -> list[dict[str, object]]:
    """Return ``{id, source_event_ids}`` for every non-merged Decision node."""
    query = (
        "MATCH (d:Decision) WHERE coalesce(d.status,'active') <> 'merged' "
        "RETURN d.id AS id, d.source_event_ids AS source_event_ids"
    )
    out: list[dict[str, object]] = []
    async with driver.session() as session:
        result = await session.run(query)
        async for record in result:
            out.append({"id": record["id"], "source_event_ids": record["source_event_ids"]})
    return out


async def _earliest_event_time(
    events: EventRepository, source_event_ids: list[str]
) -> datetime | None:
    """Earliest ``created_at`` among the decision's source events, or None if none resolve."""
    earliest: datetime | None = None
    for raw in source_event_ids:
        try:
            event_uuid = uuid.UUID(raw)
        except (ValueError, AttributeError):
            continue
        event = await events.get_by_id(event_uuid)
        if event is None:
            continue
        if earliest is None or event.created_at < earliest:
            earliest = event.created_at
    return earliest


async def _set_valid_from(driver: AsyncDriver, decision_id: str, valid_from_iso: str) -> None:
    """Set valid_from from the resolved issue date; reset status='active', valid_to=NULL."""
    query = (
        "MATCH (d:Decision {id: $id}) "
        "SET d.valid_from = datetime($vf), d.status = 'active', d.valid_to = NULL"
    )
    async with driver.session() as session:
        await (await session.run(query, id=decision_id, vf=valid_from_iso)).consume()


async def _set_valid_from_from_node(driver: AsyncDriver, decision_id: str) -> None:
    """Fallback: derive valid_from from the node's own created_at (no resolvable events)."""
    query = (
        "MATCH (d:Decision {id: $id}) "
        "SET d.valid_from = coalesce(d.valid_from, d.created_at), "
        "    d.status = 'active', d.valid_to = NULL"
    )
    async with driver.session() as session:
        await (await session.run(query, id=decision_id)).consume()
