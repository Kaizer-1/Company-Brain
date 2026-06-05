"""SQLAlchemy ORM model for the ``event_embeddings`` table.

Embeddings live in a separate table from events so that:
  1. Event inserts are not blocked on embedding computation.
  2. Re-embedding with a new model does not require mutating the events table.
  3. Future chunk-level embeddings can be accommodated without schema coupling.

See docs/design/postgres-schema.md for the full rationale.
"""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utc_now

EMBEDDING_DIM = 384  # BAAI/bge-small-en-v1.5; migrated from 1536 in 0004 (ADR 0021)


class EventEmbedding(Base):
    """A vector embedding for a single event.

    ``event_id`` is both the primary key and the FK to ``events.id``.
    In v1 there is exactly one embedding per event.  The PK constraint
    expresses this; future chunk-level embeddings will require a schema
    migration to add a ``chunk_index`` column and composite PK.

    The HNSW index on ``embedding`` is created by the Alembic migration via
    raw SQL (``op.execute``), not by SQLAlchemy DDL, because SQLAlchemy has no
    native HNSW support.
    """

    __tablename__ = "event_embeddings"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        primary_key=True,
        init=True,
    )
    embedding: Mapped[list[float]] = mapped_column(
        Vector(EMBEDDING_DIM),
        nullable=False,
    )
    model_name: Mapped[str] = mapped_column(String, nullable=False)
    model_version: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default_factory=utc_now,
    )
