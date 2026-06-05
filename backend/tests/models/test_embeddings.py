"""Unit tests for the EventEmbedding ORM model."""

import uuid

import pytest
from sqlalchemy import inspect, types

from app.models.embeddings import EventEmbedding, EMBEDDING_DIM


def test_embedding_tablename() -> None:
    assert EventEmbedding.__tablename__ == "event_embeddings"


def test_embedding_primary_key_is_event_id() -> None:
    mapper = inspect(EventEmbedding)
    pk_cols = [col.key for col in mapper.primary_key]
    assert pk_cols == ["event_id"]


def test_embedding_dim_constant() -> None:
    assert EMBEDDING_DIM == 384


def test_embedding_columns_present() -> None:
    mapper = inspect(EventEmbedding)
    col_names = {col.key for col in mapper.columns}
    expected = {"event_id", "embedding", "model_name", "model_version", "created_at"}
    assert expected <= col_names


def test_created_at_is_timezone_aware() -> None:
    mapper = inspect(EventEmbedding)
    col = mapper.columns["created_at"]
    assert isinstance(col.type, types.DateTime)
    assert col.type.timezone is True


def test_fk_references_events() -> None:
    """event_id must be a FK to events.id with CASCADE on delete."""
    table = EventEmbedding.__table__
    fks = list(table.foreign_keys)
    assert len(fks) == 1
    fk = fks[0]
    assert "events.id" in str(fk.target_fullname)
    assert fk.ondelete == "CASCADE"
