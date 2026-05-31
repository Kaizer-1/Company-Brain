"""Initial Postgres schema — events, event_embeddings, extraction_runs.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-05-31

Hand-edited after autogenerate to:
  1. Install the pgvector extension before creating the vector column.
  2. Create Postgres enum types explicitly (autogenerate emits them inline,
     which breaks idempotency on re-run and loses the type-level name).
  3. Add the HNSW index on event_embeddings.embedding via raw SQL (SQLAlchemy
     has no native HNSW DDL support).

The migration is idempotent: ``CREATE EXTENSION IF NOT EXISTS``,
``IF NOT EXISTS`` table creation, and ``DO $$ ... IF NOT EXISTS`` guards on the
enum types mean running this migration a second time is always a safe no-op.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Install pgvector extension
    # ------------------------------------------------------------------
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ------------------------------------------------------------------
    # 2. Create Postgres enum types
    #    Using DO blocks so the migration is idempotent on re-run.
    # ------------------------------------------------------------------
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'sourcetype') THEN
                CREATE TYPE sourcetype AS ENUM ('doc', 'slack_message');
            END IF;
        END
        $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'extractionstatus') THEN
                CREATE TYPE extractionstatus AS ENUM ('success', 'failed', 'partial');
            END IF;
        END
        $$;
        """
    )

    # ------------------------------------------------------------------
    # 3. Create tables
    # ------------------------------------------------------------------
    op.create_table(
        "events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "source_type",
            postgresql.ENUM("doc", "slack_message", name="sourcetype", create_type=False),
            nullable=False,
        ),
        sa.Column("source_external_id", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events")),
        sa.UniqueConstraint("source_type", "source_external_id", name="uq_events_source"),
    )
    op.create_index("ix_events_content_hash", "events", ["content_hash"])
    op.create_index("ix_events_created_at", "events", ["created_at"])

    op.create_table(
        "event_embeddings",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        # The vector column type comes from pgvector; we use Text as a
        # placeholder type for the column object and override the type
        # declaration via server_default / raw DDL.  The actual type is
        # applied via op.execute below because SQLAlchemy does not expose
        # a portable Vector DDL type at the op level.
        sa.Column("embedding", sa.Text(), nullable=False),
        sa.Column("model_name", sa.String(), nullable=False),
        sa.Column("model_version", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events.id"],
            name=op.f("fk_event_embeddings_event_id_events"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_event_embeddings")),
    )

    # Override the embedding column type to vector(1536) — ALTER COLUMN is
    # safe here because the table is empty at migration time.
    op.execute(
        "ALTER TABLE event_embeddings ALTER COLUMN embedding TYPE vector(1536) "
        "USING embedding::vector"
    )

    # HNSW index for cosine-distance approximate nearest-neighbour search.
    # m=16 (max connections per layer) and ef_construction=64 (build-time
    # search width) are the pgvector defaults and appropriate for demo scale.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_event_embeddings_embedding
        ON event_embeddings
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )

    op.create_table(
        "extraction_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_name", sa.String(), nullable=False),
        sa.Column("model_version", sa.String(), nullable=False),
        sa.Column("prompt_hash", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "success", "failed", "partial", name="extractionstatus", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("extracted_node_count", sa.Integer(), nullable=False),
        sa.Column("extracted_edge_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events.id"],
            name=op.f("fk_extraction_runs_event_id_events"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_extraction_runs")),
    )
    op.create_index(
        "ix_extraction_runs_event_started",
        "extraction_runs",
        ["event_id", "started_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_extraction_runs_event_started", table_name="extraction_runs")
    op.drop_table("extraction_runs")

    op.execute("DROP INDEX IF EXISTS ix_event_embeddings_embedding")
    op.drop_table("event_embeddings")

    op.drop_index("ix_events_created_at", table_name="events")
    op.drop_index("ix_events_content_hash", table_name="events")
    op.drop_table("events")

    op.execute("DROP TYPE IF EXISTS extractionstatus")
    op.execute("DROP TYPE IF EXISTS sourcetype")
    op.execute("DROP EXTENSION IF EXISTS vector")
