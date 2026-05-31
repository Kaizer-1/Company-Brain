"""SQLAlchemy ORM model for the ``events`` table.

The events table is the immutable raw-event log.  Every piece of company
knowledge ingested by Company Brain lands here first.  Graph nodes' ``source_event_ids``
are UUIDs in this table — see ADR 0009 and docs/design/postgres-schema.md.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utc_now
from app.models.enums import SourceType


class Event(Base):
    """An immutable raw event ingested from any source system.

    Once inserted, ``content`` and ``source_metadata`` are never modified.
    Corrections are handled by ingesting a new event and re-running extraction.
    See design doc: docs/design/postgres-schema.md.

    Constructor requires: source_type, source_external_id, content, created_at,
    content_hash.  Optional: source_metadata (defaults to empty dict).
    Auto-generated: id (UUID), ingested_at (current UTC time).
    """

    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("source_type", "source_external_id", name="uq_events_source"),
        Index("ix_events_content_hash", "content_hash"),
        Index("ix_events_created_at", "created_at"),
    )

    # ------------------------------------------------------------------
    # Required fields (no defaults) — must come before fields with defaults
    # in MappedAsDataclass due to Python dataclass ordering rules.
    # ------------------------------------------------------------------
    source_type: Mapped[SourceType] = mapped_column(
        Enum(SourceType, name="sourcetype", create_type=False),
        nullable=False,
    )
    source_external_id: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # ------------------------------------------------------------------
    # Auto-generated fields (init=False — not constructor parameters)
    # ------------------------------------------------------------------
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default_factory=uuid.uuid4,
        init=False,
    )
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default_factory=utc_now,
        init=False,
    )

    # ------------------------------------------------------------------
    # Optional field with default
    # ------------------------------------------------------------------
    source_metadata: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default_factory=dict,
    )
