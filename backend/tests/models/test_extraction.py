"""Unit tests for the ExtractionRun ORM model."""

import uuid

import pytest
from sqlalchemy import inspect, types

from app.models.extraction import ExtractionRun
from app.models.enums import ExtractionStatus


def test_extraction_run_tablename() -> None:
    assert ExtractionRun.__tablename__ == "extraction_runs"


def test_extraction_run_primary_key() -> None:
    mapper = inspect(ExtractionRun)
    pk_cols = [col.key for col in mapper.primary_key]
    assert pk_cols == ["id"]


def test_extraction_run_columns_present() -> None:
    mapper = inspect(ExtractionRun)
    col_names = {col.key for col in mapper.columns}
    expected = {
        "id",
        "event_id",
        "model_name",
        "model_version",
        "prompt_hash",
        "started_at",
        "completed_at",
        "status",
        "extracted_node_count",
        "extracted_edge_count",
        "error_message",
    }
    assert expected <= col_names


def test_completed_at_is_nullable() -> None:
    mapper = inspect(ExtractionRun)
    col = mapper.columns["completed_at"]
    assert col.nullable is True


def test_error_message_is_nullable() -> None:
    mapper = inspect(ExtractionRun)
    col = mapper.columns["error_message"]
    assert col.nullable is True


def test_started_at_is_timezone_aware() -> None:
    mapper = inspect(ExtractionRun)
    col = mapper.columns["started_at"]
    assert isinstance(col.type, types.DateTime)
    assert col.type.timezone is True


def test_status_enum_values() -> None:
    assert set(ExtractionStatus) == {
        ExtractionStatus.success,
        ExtractionStatus.failed,
        ExtractionStatus.partial,
    }


def test_fk_references_events() -> None:
    """event_id must be a FK to events.id (no cascade — audit records survive)."""
    table = ExtractionRun.__table__
    fks = list(table.foreign_keys)
    assert len(fks) == 1
    fk = fks[0]
    assert "events.id" in str(fk.target_fullname)
    # No CASCADE on extraction_runs — audit trail must survive event deletion.
    assert fk.ondelete is None
