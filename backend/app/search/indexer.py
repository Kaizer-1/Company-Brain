"""Embedding pipeline step for the search module (Phase 3D).

``embed_events()`` reads un-embedded events from Postgres, batches them through
``BAAI/bge-small-en-v1.5`` (same model as entity resolution), and writes the
result vectors to ``event_embeddings``.

Idempotent: re-running only embeds events that do not yet have an embedding row.
Batch size is ``EMBED_BATCH_SIZE`` (32) to match the resolver's batching approach
and stay within reasonable memory bounds on CPU inference.

Pipeline position: AFTER extraction (events must exist), BEFORE entity resolution
(so future at-write-time resolution can use embeddings as a retrieval signal).
"""

from __future__ import annotations

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.embeddings import EventEmbeddingRepository
from app.schemas.postgres import EventEmbeddingCreate
from app.search.config import EMBED_BATCH_SIZE, MODEL_NAME, MODEL_VERSION
from app.search.embedder import embed_batch

log = structlog.get_logger(__name__)


async def embed_events(session: AsyncSession) -> int:
    """Embed all un-embedded events; return the number of new embeddings written.

    Reads event ids that have no row in ``event_embeddings``, embeds them in
    batches of ``EMBED_BATCH_SIZE``, and upserts via ``EventEmbeddingRepository``.
    Already-embedded events are skipped (idempotent).
    """
    unembedded = await _fetch_unembedded(session)
    if not unembedded:
        log.info("embed_events_skip", reason="all events already embedded")
        return 0

    log.info("embed_events_start", count=len(unembedded))
    repo = EventEmbeddingRepository(session)
    written = 0

    for batch_start in range(0, len(unembedded), EMBED_BATCH_SIZE):
        batch = unembedded[batch_start : batch_start + EMBED_BATCH_SIZE]
        event_ids = [row[0] for row in batch]
        contents = [row[1] for row in batch]

        vectors = await embed_batch(contents)

        for event_id, vector in zip(event_ids, vectors, strict=True):
            await repo.upsert(
                EventEmbeddingCreate(
                    event_id=event_id,
                    embedding=vector.tolist(),
                    model_name=MODEL_NAME,
                    model_version=MODEL_VERSION,
                )
            )
            written += 1

        await session.flush()
        log.debug(
            "embed_events_batch",
            batch_start=batch_start,
            batch_size=len(batch),
            written_so_far=written,
        )

    await session.commit()
    log.info("embed_events_done", written=written)
    return written


async def _fetch_unembedded(
    session: AsyncSession,
) -> list[tuple[object, str]]:
    """Return (event_id, content) for events with no embedding row."""
    result = await session.execute(
        text(
            """
            SELECT e.id, e.content
            FROM events e
            LEFT JOIN event_embeddings ee ON ee.event_id = e.id
            WHERE ee.event_id IS NULL
            ORDER BY e.created_at ASC
            """
        )
    )
    return [(row.id, row.content) for row in result]
