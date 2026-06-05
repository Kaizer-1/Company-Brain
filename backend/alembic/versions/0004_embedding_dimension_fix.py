"""Phase 3D — migrate event_embeddings from vector(1536) to vector(384).

Revision ID: 0004_embedding_dimension_fix
Revises: 0003_decision_consolidation_enum
Create Date: 2026-06-05

The 1536-dimension column was a Phase 1C placeholder that assumed OpenAI
text-embedding-3-small.  Phase 3D uses BAAI/bge-small-en-v1.5 (384 dims), the same
model already live for entity resolution (ADR 0014).  Decision documented in ADR 0021.

Strategy: drop + recreate.  The table has never been written to (Phase 3D is the first
writer); the upgrade includes a defensive row-count assertion that refuses to proceed if
any rows exist, so we never silently destroy embeddings on a non-empty table.  Pass
``force=true`` in the Alembic context ``x`` config to override the guard if needed.

Downgrade restores vector(1536) and the original HNSW index — safe because the table
will be empty after the downgrade (if any writes happened post-upgrade they would have
used 384-dim vectors, which cannot be stored in a 1536-dim column; the downgrade
implicitly widens back to the schema the Phase 1C code expected).
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_embedding_dimension_fix"
down_revision: Union[str, None] = "0003_decision_consolidation_enum"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEX_NAME = "ix_event_embeddings_embedding"
_TABLE_NAME = "event_embeddings"


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 0. Defensive row-count guard.
    #    Refuse to proceed if the table already has rows, because
    #    dropping it destroys embeddings computed at the old dimension.
    #    This guard can be bypassed by running alembic with -x force=true.
    # ------------------------------------------------------------------
    bind = op.get_bind()
    config = op.get_context().config
    force = (config.attributes.get("force") or "").lower() in ("true", "1", "yes")

    row = bind.execute(
        sa.text(f"SELECT COUNT(*) FROM {_TABLE_NAME}")  # noqa: S608
    ).scalar_one()
    if row != 0 and not force:
        raise RuntimeError(
            f"Migration 0004 aborted: {_TABLE_NAME} has {row} row(s). "
            "This migration drops the table. Re-run with -x force=true to override."
        )

    # ------------------------------------------------------------------
    # 1. Drop the old HNSW index and the table.
    # ------------------------------------------------------------------
    op.execute(f"DROP INDEX IF EXISTS {_INDEX_NAME}")
    op.drop_table(_TABLE_NAME)

    # ------------------------------------------------------------------
    # 2. Recreate the table with the same constraints/FK as 0001.
    # ------------------------------------------------------------------
    op.create_table(
        _TABLE_NAME,
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
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

    # Override the placeholder Text column type to vector(384) — the table is empty.
    op.execute(
        f"ALTER TABLE {_TABLE_NAME} ALTER COLUMN embedding TYPE vector(384) "
        "USING embedding::vector"
    )

    # ------------------------------------------------------------------
    # 3. Recreate the HNSW index with the same build parameters.
    #    m=16 / ef_construction=64 are pgvector defaults; appropriate at
    #    demo scale (see ADR 0021 for the scaling path).
    # ------------------------------------------------------------------
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS {_INDEX_NAME}
        ON {_TABLE_NAME}
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_INDEX_NAME}")
    op.drop_table(_TABLE_NAME)

    op.create_table(
        _TABLE_NAME,
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
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

    op.execute(
        f"ALTER TABLE {_TABLE_NAME} ALTER COLUMN embedding TYPE vector(1536) "
        "USING embedding::vector"
    )

    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS {_INDEX_NAME}
        ON {_TABLE_NAME}
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )
