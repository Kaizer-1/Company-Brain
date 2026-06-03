"""Phase 3B — add ``content_merge`` to the mergedecisiontype enum.

Revision ID: 0003_decision_consolidation_enum
Revises: 0002_merge_decisions
Create Date: 2026-06-03

Multi-source Decision consolidation (ADR 0017) reuses the ``merge_decisions`` audit table
with a new decision outcome, ``content_merge`` — a Decision merged on content-embedding
similarity rather than an identity rule. This migration adds that value to the existing
``mergedecisiontype`` Postgres enum.

Idempotent on re-run: ``ALTER TYPE ... ADD VALUE IF NOT EXISTS``. Note that adding an enum
value cannot run inside a transaction block on older Postgres, so we commit first; on
Postgres 12+ ``ADD VALUE`` is transactional-safe, and Alembic's autocommit handling covers it.
There is no clean downgrade for an enum value in Postgres, so ``downgrade`` is a no-op.
"""

from collections.abc import Sequence

revision: str = "0003_decision_consolidation_enum"
down_revision: str | None = "0002_merge_decisions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ADD VALUE IF NOT EXISTS makes the migration safe to re-run; the value is appended to
    # the existing enum without rewriting the column.
    from alembic import op

    op.execute("ALTER TYPE mergedecisiontype ADD VALUE IF NOT EXISTS 'content_merge'")


def downgrade() -> None:
    # Postgres has no DROP VALUE for enums; removing it would require recreating the type
    # and rewriting every dependent column. A no-op downgrade is the honest choice.
    pass
