"""SQLAlchemy ORM model for the ``extraction_runs`` table.

The extraction_runs table is the operational memory of the extraction pipeline.
Every extraction attempt — success or failure — produces a row here.  This
enables re-extraction workflows, failure replay, and model-upgrade auditing.
See docs/design/postgres-schema.md for the full rationale.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import ExtractionStatus


class ExtractionRun(Base):
    """One record per extraction pipeline invocation against a single event.

    Multiple rows per event are expected: initial extraction, re-extraction
    after a prompt change, re-extraction with a new model version, etc.
    ``latest_for_event`` returns the most recent row for a given event.

    Constructor requires: event_id, model_name, model_version, prompt_hash,
    started_at.  All other fields have sensible defaults.
    """

    __tablename__ = "extraction_runs"
    __table_args__ = (Index("ix_extraction_runs_event_started", "event_id", "started_at"),)

    # ------------------------------------------------------------------
    # Required fields (no defaults) — must come before fields with defaults.
    # ------------------------------------------------------------------
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id"),
        nullable=False,
    )
    model_name: Mapped[str] = mapped_column(String, nullable=False)
    model_version: Mapped[str] = mapped_column(String, nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    # ------------------------------------------------------------------
    # Auto-generated primary key (init=False — not a constructor parameter).
    # ------------------------------------------------------------------
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default_factory=uuid.uuid4,
        init=False,
    )

    # ------------------------------------------------------------------
    # Fields with defaults.
    # ------------------------------------------------------------------
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    status: Mapped[ExtractionStatus] = mapped_column(
        Enum(ExtractionStatus, name="extractionstatus", create_type=False),
        nullable=False,
        default=ExtractionStatus.failed,
    )
    extracted_node_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    extracted_edge_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
    )
