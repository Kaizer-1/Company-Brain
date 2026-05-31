"""Real-DB tests for ExtractionRunRepository using a testcontainers Postgres."""

import hashlib
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.events import EventRepository
from app.db.repositories.extraction import ExtractionRunRepository
from app.models.enums import ExtractionStatus, SourceType
from app.schemas.postgres import EventCreate, ExtractionRunCreate


async def _create_event(session: AsyncSession) -> uuid.UUID:
    repo = EventRepository(session)
    content = "extraction test " + str(uuid.uuid4())
    data = EventCreate(
        source_type=SourceType.doc,
        source_external_id=str(uuid.uuid4()),
        content=content,
        source_metadata={},
        created_at=datetime.now(tz=timezone.utc),
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
    )
    created = await repo.create(data)
    return created.id


def _run_create(event_id: uuid.UUID) -> ExtractionRunCreate:
    return ExtractionRunCreate(
        event_id=event_id,
        model_name="claude-opus-4",
        model_version="2026-05-01",
        prompt_hash="a" * 64,
        started_at=datetime.now(tz=timezone.utc),
    )


@pytest.mark.asyncio
async def test_create_pending_sets_failed_status(db_session: AsyncSession) -> None:
    """create_pending uses 'failed' as the safe default status."""
    event_id = await _create_event(db_session)
    repo = ExtractionRunRepository(db_session)

    run = await repo.create_pending(_run_create(event_id))
    assert run.status == ExtractionStatus.failed
    assert run.completed_at is None
    assert run.extracted_node_count == 0


@pytest.mark.asyncio
async def test_mark_success_updates_run(db_session: AsyncSession) -> None:
    event_id = await _create_event(db_session)
    repo = ExtractionRunRepository(db_session)

    run = await repo.create_pending(_run_create(event_id))
    updated = await repo.mark_success(
        run.id, extracted_node_count=5, extracted_edge_count=3
    )

    assert updated is not None
    assert updated.status == ExtractionStatus.success
    assert updated.extracted_node_count == 5
    assert updated.extracted_edge_count == 3
    assert updated.completed_at is not None
    assert updated.error_message is None


@pytest.mark.asyncio
async def test_mark_failed_updates_run(db_session: AsyncSession) -> None:
    event_id = await _create_event(db_session)
    repo = ExtractionRunRepository(db_session)

    run = await repo.create_pending(_run_create(event_id))
    updated = await repo.mark_failed(run.id, error_message="LLM timeout")

    assert updated is not None
    assert updated.status == ExtractionStatus.failed
    assert updated.error_message == "LLM timeout"
    assert updated.completed_at is not None


@pytest.mark.asyncio
async def test_mark_failed_partial(db_session: AsyncSession) -> None:
    event_id = await _create_event(db_session)
    repo = ExtractionRunRepository(db_session)

    run = await repo.create_pending(_run_create(event_id))
    updated = await repo.mark_failed(
        run.id,
        error_message="partial failure",
        extracted_node_count=2,
        extracted_edge_count=1,
        partial=True,
    )

    assert updated is not None
    assert updated.status == ExtractionStatus.partial
    assert updated.extracted_node_count == 2


@pytest.mark.asyncio
async def test_mark_success_returns_none_for_missing_id(db_session: AsyncSession) -> None:
    repo = ExtractionRunRepository(db_session)
    result = await repo.mark_success(uuid.uuid4(), extracted_node_count=0, extracted_edge_count=0)
    assert result is None


@pytest.mark.asyncio
async def test_latest_for_event_returns_most_recent(db_session: AsyncSession) -> None:
    import asyncio

    event_id = await _create_event(db_session)
    repo = ExtractionRunRepository(db_session)

    run1 = await repo.create_pending(_run_create(event_id))
    # Ensure a distinct started_at by using a slightly later timestamp.
    data2 = ExtractionRunCreate(
        event_id=event_id,
        model_name="claude-opus-4",
        model_version="2026-06-01",
        prompt_hash="b" * 64,
        started_at=datetime.now(tz=timezone.utc),
    )
    run2 = await repo.create_pending(data2)
    await repo.mark_success(run2.id, extracted_node_count=1, extracted_edge_count=0)

    latest = await repo.latest_for_event(event_id)
    assert latest is not None
    # The most recently started run should be returned.
    assert latest.id == run2.id


@pytest.mark.asyncio
async def test_latest_for_event_returns_none_for_unknown_event(db_session: AsyncSession) -> None:
    repo = ExtractionRunRepository(db_session)
    result = await repo.latest_for_event(uuid.uuid4())
    assert result is None
