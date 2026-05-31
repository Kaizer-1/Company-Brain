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
