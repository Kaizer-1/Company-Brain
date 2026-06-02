"""Phase 3A — merge_decisions audit table for entity resolution.

Revision ID: 0002_merge_decisions
Revises: 0001_initial_schema
Create Date: 2026-06-02

Adds the ``merge_decisions`` table (ADR 0015): one row per resolution attempt — auto-merge,
LLM-resolved, LLM-rejected, or below-threshold — with full provenance (tier, rules matched,
embedding similarity, LLM reasoning). Two new Postgres enum types back the ``node_type`` and
``decision`` columns.

Idempotent on re-run: ``DO $$ ... IF NOT EXISTS`` guards on the enum types and
``IF NOT EXISTS`` on the table/index, consistent with the initial migration.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_merge_decisions"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Create Postgres enum types (idempotent DO blocks).
    # ------------------------------------------------------------------
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'nodetype') THEN
                CREATE TYPE nodetype AS ENUM ('Person', 'Service', 'System', 'Team', 'Decision');
            END IF;
        END
        $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'mergedecisiontype') THEN
                CREATE TYPE mergedecisiontype AS ENUM
                    ('auto_merge', 'llm_merge', 'llm_no_merge', 'below_threshold');
            END IF;
        END
        $$;
        """
    )

    # ------------------------------------------------------------------
    # 2. Create the table.
    # ------------------------------------------------------------------
    op.create_table(
        "merge_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_node_id", sa.String(), nullable=False),
        sa.Column("target_node_id", sa.String(), nullable=False),
        sa.Column(
            "node_type",
            postgresql.ENUM(
                "Person", "Service", "System", "Team", "Decision",
                name="nodetype", create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "decision",
            postgresql.ENUM(
                "auto_merge", "llm_merge", "llm_no_merge", "below_threshold",
                name="mergedecisiontype", create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("tier", sa.Integer(), nullable=False),
        sa.Column("embedding_similarity", sa.Float(), nullable=True),
        sa.Column("rules_matched", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("llm_reasoning", sa.Text(), nullable=True),
        sa.Column("llm_model", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_merge_decisions")),
    )
    op.create_index(
        "ix_merge_decisions_type_created",
        "merge_decisions",
        ["node_type", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_merge_decisions_type_created", table_name="merge_decisions")
    op.drop_table("merge_decisions")
    op.execute("DROP TYPE IF EXISTS mergedecisiontype")
    op.execute("DROP TYPE IF EXISTS nodetype")
