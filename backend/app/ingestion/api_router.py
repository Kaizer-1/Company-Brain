"""FastAPI router for live event ingestion — ``POST /api/events`` (Phase 5A).

The endpoint inserts a new event, reconciles it into the graph synchronously (the user is
watching — visible reconciliation is the demo, not a fire-and-forget 202), and returns the full
reconciliation result. Idempotency is handled before any work: a repeat of the same event
(same ``(source_type, source_external_id)``) short-circuits to its existing result.

Concurrency is a single in-process ``asyncio.Lock`` (ADR 0033): ingestions run one at a time;
a second request waits up to ``_LOCK_TIMEOUT_S`` then returns 503. This is sufficient for the
demo's single-writer reality; the production path (per-canonical-node locking) is documented in
the design doc.
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from typing import TYPE_CHECKING

import structlog
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.exc import IntegrityError

from app.db.repositories.events import EventRepository
from app.db.repositories.ingestion_runs import IngestionRunRepository
from app.ingestion.orchestrator import reconcile_event
from app.ingestion.schemas import IngestEventRequest, IngestEventResponse
from app.models.enums import SourceType
from app.schemas.postgres import EventCreate

if TYPE_CHECKING:
    from neo4j import AsyncDriver
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

router = APIRouter(prefix="/api/events", tags=["ingestion"])
log = structlog.get_logger(__name__)

# Single-writer serialization (ADR 0033). Ingestions touching overlapping subgraphs must not
# interleave; at demo scale a process-wide lock is the simplest correct choice.
_INGEST_LOCK = asyncio.Lock()
_LOCK_TIMEOUT_S = 30.0


def _content_hash(content: str) -> str:
    """SHA-256 of the event content — the near-duplicate signal and the fallback id seed."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _external_id(request: IngestEventRequest, content_hash: str) -> str:
    """The idempotency key for ``uq_events_source``.

    Prefer the caller's ``external_id``; otherwise derive a stable id from the content hash so a
    double-submit of identical content still dedupes (ADR 0032).
    """
    return request.external_id or f"ingest-{content_hash[:24]}"


@router.post(
    "",
    response_model=IngestEventResponse,
    summary="Ingest a new event and reconcile it into the graph in real time.",
)
async def ingest_event(request: Request, body: IngestEventRequest) -> IngestEventResponse:
    """Insert + reconcile one new event; return the visible reconciliation artifact.

    Returns 200 with the prior result if the event was already ingested (idempotent), 503 if a
    concurrent ingestion holds the writer lock past the timeout.
    """
    session_factory = request.app.state.session_factory
    neo4j_driver = request.app.state.neo4j.driver

    source_type = SourceType(body.source_kind)
    content_hash = _content_hash(body.content)
    external_id = _external_id(body, content_hash)

    # ── Idempotency: has this event already been ingested? ────────────────────────────────
    async with session_factory() as session:
        existing = await EventRepository(session).get_by_source(source_type, external_id)
    if existing is not None:
        async with session_factory() as session:
            prior = await IngestionRunRepository(session).get_by_event(existing.id)
        if prior is not None:
            log.info("ingest_dedup", event_id=str(existing.id), status=prior.status)
            return await _reconcile_locked(
                existing.id, session_factory=session_factory, neo4j_driver=neo4j_driver
            )
        # Event row exists but never reconciled (prior crash) — reconcile it now.
        return await _reconcile_locked(
            existing.id, session_factory=session_factory, neo4j_driver=neo4j_driver
        )

    # ── Insert the new event row ──────────────────────────────────────────────────────────
    try:
        async with session_factory() as session:
            event = await EventRepository(session).create(
                EventCreate(
                    source_type=source_type,
                    source_external_id=external_id,
                    content=body.content,
                    source_metadata={"source_ref": body.source_ref},
                    created_at=body.occurred_at,
                    content_hash=content_hash,
                )
            )
            await session.commit()
    except IntegrityError:
        # Lost an insert race for the same (source_type, external_id) — fall back to dedup.
        async with session_factory() as session:
            existing = await EventRepository(session).get_by_source(source_type, external_id)
        if existing is None:  # pragma: no cover - integrity error implies the row exists
            raise
        return await _reconcile_locked(
            existing.id, session_factory=session_factory, neo4j_driver=neo4j_driver
        )

    return await _reconcile_locked(
        event.id, session_factory=session_factory, neo4j_driver=neo4j_driver
    )


async def _reconcile_locked(
    event_id: uuid.UUID,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    neo4j_driver: AsyncDriver,
) -> IngestEventResponse:
    """Acquire the single-writer lock (with timeout) and reconcile, then release."""
    try:
        await asyncio.wait_for(_INGEST_LOCK.acquire(), timeout=_LOCK_TIMEOUT_S)
    except TimeoutError as exc:
        log.warning("ingest_lock_timeout", event_id=str(event_id))
        raise HTTPException(
            status_code=503, detail="Ingestion busy; another reconciliation is in progress."
        ) from exc
    try:
        return await reconcile_event(
            event_id, session_factory=session_factory, neo4j_driver=neo4j_driver
        )
    finally:
        _INGEST_LOCK.release()
