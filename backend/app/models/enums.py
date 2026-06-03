"""Python enums that mirror the Postgres enum types created in the Alembic migration.

Each enum here maps 1-to-1 to a ``CREATE TYPE ... AS ENUM`` statement in the
initial migration.  SQLAlchemy uses these via ``sqlalchemy.Enum(SourceType)``,
which serialises / deserialises the Python names to the Postgres type values.
"""

import enum


class SourceType(str, enum.Enum):
    """Discriminates the origin system for a raw event.

    Values must match the Postgres enum type ``sourcetype`` created in the
    initial Alembic migration.  To add a new source, write an
    ``ALTER TYPE sourcetype ADD VALUE '...'`` migration first.
    """

    doc = "doc"
    slack_message = "slack_message"


class ExtractionStatus(str, enum.Enum):
    """Terminal or intermediate status for an extraction run.

    Values must match the Postgres enum type ``extractionstatus`` created in
    the initial Alembic migration.
    """

    success = "success"
    failed = "failed"
    partial = "partial"


class NodeType(str, enum.Enum):
    """The closed set of graph node types entity resolution operates over (Phase 3A).

    A subset of the six graph labels: ``Message`` is never resolved (it is created
    mechanically from an event, one-to-one, so it cannot fragment). Values must match the
    Postgres enum type ``nodetype`` created in the Phase 3A Alembic migration.
    """

    Person = "Person"
    Service = "Service"
    System = "System"
    Team = "Team"
    Decision = "Decision"


class MergeDecisionType(str, enum.Enum):
    """The outcome of one resolution attempt (Phase 3A; see ADR 0015).

    Every candidate pair the resolver considers produces exactly one of these, recorded in
    ``merge_decisions``. ``auto_merge``/``llm_merge`` write a ``MERGE_INTO`` edge;
    ``llm_no_merge``/``below_threshold`` touch only the audit table. Values must match the
    Postgres enum type ``mergedecisiontype``.
    """

    auto_merge = "auto_merge"
    llm_merge = "llm_merge"
    llm_no_merge = "llm_no_merge"
    below_threshold = "below_threshold"
    # Phase 3B (ADR 0017): a multi-source Decision content-consolidation merge — same
    # MERGE_INTO mechanism as the entity merges, distinguished so the audit can tell a
    # content-similarity Decision merge from an identity-rule entity merge.
    content_merge = "content_merge"
