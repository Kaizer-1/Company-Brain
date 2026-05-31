"""Repository for the ``event_embeddings`` table.

The ``similar_to`` method uses pgvector's ``<=>`` cosine distance operator for
approximate nearest-neighbour search via the HNSW index.  See ADR 0003 and
ADR 0009 for the choice of pgvector and HNSW.
"""

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import Float, Integer, bindparam, delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.base import Repository
from app.models.embeddings import EMBEDDING_DIM, EventEmbedding
from app.schemas.postgres import EventEmbeddingCreate, EventEmbeddingDTO


def _to_dto(row: EventEmbedding) -> EventEmbeddingDTO:
    # row.embedding may be a list[float] (freshly constructed ORM object) or a
    # numpy.ndarray (value decoded by the pgvector asyncpg codec after a DB
    # round-trip).  Normalise to list[float] in both cases.
    embedding: list[float] = [float(x) for x in row.embedding]
    return EventEmbeddingDTO(
        event_id=row.event_id,
        embedding=embedding,
        model_name=row.model_name,
        model_version=row.model_version,
        created_at=row.created_at,
    )


class EventEmbeddingRepository(Repository[EventEmbedding]):
    """Read and write operations for the ``event_embeddings`` table."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def get_for_event(self, event_id: uuid.UUID) -> EventEmbeddingDTO | None:
        """Return the embedding for the given event, or None."""
        result = await self._session.execute(
            select(EventEmbedding).where(EventEmbedding.event_id == event_id)
        )
        row = result.scalar_one_or_none()
        return _to_dto(row) if row is not None else None

    async def upsert(self, data: EventEmbeddingCreate) -> EventEmbeddingDTO:
        """Insert or replace the embedding for an event.

        Because ``event_id`` is the primary key, an existing row is deleted
        first and re-inserted.  This is safe because embeddings are derived
        data — the event itself is immutable.  The delete + insert pattern is
        explicit and avoids ON CONFLICT complexity with vector columns.
        """
        await self._session.execute(
            delete(EventEmbedding).where(EventEmbedding.event_id == data.event_id)
        )
        from datetime import datetime

        row = EventEmbedding(
            event_id=data.event_id,
            embedding=data.embedding,
            model_name=data.model_name,
            model_version=data.model_version,
            created_at=datetime.utcnow(),
        )
        self._session.add(row)
        await self._session.flush()
        return _to_dto(row)

    async def similar_to(
        self,
        vector: list[float],
        limit: int = 10,
        threshold: float = 0.8,
    ) -> list[EventEmbeddingDTO]:
        """Return embeddings nearest to ``vector`` by cosine similarity.

        Uses pgvector's ``<=>`` cosine distance operator.  The HNSW index on
        ``event_embeddings.embedding`` (created in the initial migration) makes
        this sub-10ms at demo scale.

        Args:
            vector: The query embedding (must be 1536-dimensional).
            limit: Maximum number of results to return.
            threshold: Minimum cosine similarity (1 - cosine distance).
                       Rows with similarity < threshold are excluded.
        """
        # pgvector's <=> is cosine *distance* (0 = identical, 2 = opposite).
        # Convert the threshold similarity to a distance ceiling.
        distance_ceiling = 1.0 - threshold

        # query_vector is bound via SQLAlchemy's Vector TypeDecorator so the
        # value is never interpolated into the SQL text — no injection surface.
        # The pgvector codec registered in build_engine ensures the embedding
        # column comes back as a native array, not a raw string.
        stmt = text(
            """
            SELECT event_id, embedding, model_name, model_version, created_at
            FROM event_embeddings
            WHERE embedding <=> :query_vector <= :distance_ceiling
            ORDER BY embedding <=> :query_vector
            LIMIT :limit
            """
        ).bindparams(
            bindparam("query_vector", type_=Vector(EMBEDDING_DIM)),
            bindparam("distance_ceiling", type_=Float()),
            bindparam("limit", type_=Integer()),
        )

        result = await self._session.execute(
            stmt,
            {"query_vector": vector, "distance_ceiling": distance_ceiling, "limit": limit},
        )
        rows = result.fetchall()

        dtos: list[EventEmbeddingDTO] = []
        for row in rows:
            # row.embedding is a numpy.ndarray decoded by the pgvector asyncpg codec.
            emb = [float(x) for x in row.embedding]
            dtos.append(
                EventEmbeddingDTO(
                    event_id=row.event_id,
                    embedding=emb,
                    model_name=row.model_name,
                    model_version=row.model_version,
                    created_at=row.created_at,
                )
            )
        return dtos
