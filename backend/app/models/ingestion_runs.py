"""SQLAlchemy ORM model for the ``ingestion_runs`` table (Phase 5A).

One record per live-ingested event. Where ``extraction_runs`` audits the LLM extraction step
in isolation, ``ingestion_runs`` audits the *whole reconciliation pipeline* the ingestion
endpoint runs for an event: which stages ran, what they produced, how long it took, and what it
cost. See ADR 0031 (incremental reconciliation) and ADR 0032 (idempotency contract).

Keyed ``UNIQUE (event_id)``: re-ingesting the same event updates its row in place rather than
appending a second one. ``stages_json`` holds the serialised ``list[StageResult]`` so the audit
view and the ingestion response render from the same source of truth.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class IngestionRun(Base):
    """One reconciliation run against a single live-ingested event.

    Constructor requires: ``event_id``, ``status``, ``started_at``, ``stages_json``. All other
    fields default (counts to 0, cost to 0, ``completed_at``/``error`` to None). The PK and the
    ``UNIQUE (event_id)`` constraint mean an upsert keyed on ``event_id`` is the natural write
    path (see ``IngestionRunRepository.upsert``).
    """

    __tablename__ = "ingestion_runs"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_ingestion_runs_event_id"),
        Index("ix_ingestion_runs_started", "started_at"),
    )

    # ------------------------------------------------------------------
    # Required fields (no defaults) — must come before defaulted fields.
    # ------------------------------------------------------------------
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    stages_json: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)

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
    nodes_created_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    nodes_merged_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    edges_created_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    contradictions_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 6), nullable=False, default=Decimal("0")
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
