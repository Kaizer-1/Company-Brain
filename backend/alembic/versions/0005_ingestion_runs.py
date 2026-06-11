"""Phase 5A — ingestion_runs audit table for live reconciliation.

Revision ID: 0005_ingestion_runs
Revises: 0004_embedding_dimension_fix
Create Date: 2026-06-07

Adds the ``ingestion_runs`` table (ADR 0031/0032): one row per live-ingested event, recording
the reconciliation outcome — status, timing, per-stage results (JSONB), the counts the
frontend's "what changed" panel renders, and the cost. Mirrors ``extraction_runs`` from
Phase 1C, but keyed ``UNIQUE (event_id)``: re-ingesting the same event updates its row in place
rather than appending, which is part of the idempotency contract (Decision 3 / ADR 0032).

``status`` is a plain ``TEXT`` column (not a Postgres enum) so adding a future status value
needs no ``ALTER TYPE`` migration; the allowed values ('reconciled' | 'partial' | 'failed')
are enforced in the Pydantic/SQLAlchemy layer, not the database.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_ingestion_runs"
down_revision: str | None = "0004_embedding_dimension_fix"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ingestion_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stages_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("nodes_created_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("nodes_merged_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("edges_created_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("contradictions_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingestion_runs")),
        sa.ForeignKeyConstraint(
            ["event_id"], ["events.id"], name=op.f("fk_ingestion_runs_event_id_events")
        ),
        sa.UniqueConstraint("event_id", name="uq_ingestion_runs_event_id"),
    )
    op.create_index(
        "ix_ingestion_runs_started", "ingestion_runs", ["started_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_ingestion_runs_started", table_name="ingestion_runs")
    op.drop_table("ingestion_runs")
