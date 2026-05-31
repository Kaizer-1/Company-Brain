"""Declarative base for all SQLAlchemy ORM models.

The naming convention is applied to all constraints so that Alembic's
autogenerate produces stable, deterministic migration names regardless of
column order or table creation order.  Without this, Alembic generates names
like ``fk_a1b2c3`` that change between runs and produce noisy diffs.

See: https://alembic.sqlalchemy.org/en/latest/naming.html
"""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase, MappedAsDataclass

NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# backend/app/models/base.py
from datetime import datetime, UTC

def utc_now() -> datetime:
    """Timezone-aware UTC now. Used as default for timestamp columns."""
    return datetime.now(UTC)

class Base(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM models.

    Inherits from both ``MappedAsDataclass`` (so models are Python dataclasses
    with typed ``Mapped`` fields) and ``DeclarativeBase`` (SQLAlchemy 2.x
    declarative mapping).  The ``metadata`` carries the naming convention so
    Alembic-generated migrations have stable constraint names.
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
