"""SQLAlchemy ORM model for the ``merge_decisions`` table (Phase 3A).

Every entity-resolution attempt — auto-merge, LLM-resolved, LLM-rejected, or
below-threshold — writes one row here. This is the audit backbone that lets us answer
"show me exactly how you decided these two nodes were (not) the same entity," and the seed
for a future human-review UI. See ADR 0015 and docs/design/entity-resolution.md.

The table lives in Postgres rather than as a Neo4j relationship deliberately: a rejected
pair has no edge to attach to, and this is append-only time-series audit data — the same
role Postgres already plays for ``events`` and ``extraction_runs``.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utc_now
from app.models.enums import MergeDecisionType, NodeType


class MergeDecision(Base):
    """One record per resolution attempt against a candidate pair of graph nodes.

    Multiple rows per node are expected (a node is compared against many others, and
    resolution may be re-run). The log is append-only: re-running resolution appends new
    rows rather than mutating old ones — the table is history, not current state.

    Constructor requires: source_node_id, target_node_id, node_type, decision, tier. All
    other fields have sensible defaults.
    """

    __tablename__ = "merge_decisions"
    __table_args__ = (Index("ix_merge_decisions_type_created", "node_type", "created_at"),)

    # ------------------------------------------------------------------
    # Required fields (no defaults) — must come before fields with defaults
    # (MappedAsDataclass dataclass ordering rule).
    # ------------------------------------------------------------------
    source_node_id: Mapped[str] = mapped_column(String, nullable=False)
    target_node_id: Mapped[str] = mapped_column(String, nullable=False)
    node_type: Mapped[NodeType] = mapped_column(
        Enum(NodeType, name="nodetype", create_type=False),
        nullable=False,
    )
    decision: Mapped[MergeDecisionType] = mapped_column(
        Enum(MergeDecisionType, name="mergedecisiontype", create_type=False),
        nullable=False,
    )
    tier: Mapped[int] = mapped_column(Integer, nullable=False)

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
    embedding_similarity: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        default=None,
    )
    rules_matched: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        nullable=False,
        default_factory=list,
    )
    llm_reasoning: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
    )
    llm_model: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default_factory=utc_now,
    )
