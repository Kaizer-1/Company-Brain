"""Real-DB tests for EventRepository using a testcontainers Postgres.

These tests require Docker.  They are skipped (not failed) if Docker is
unavailable.  They verify round-trip create+get, unique-constraint enforcement,
content-hash dedup, and list_since filtering.
"""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.events import EventRepository
from app.models.enums import SourceType
from app.schemas.postgres import EventCreate


def _make_event(
    source_type: SourceType = SourceType.doc,
    source_external_id: str | None = None,
    content: str = "test content",
    created_at: datetime | None = None,
) -> EventCreate:
    if source_external_id is None:
        source_external_id = str(uuid.uuid4())
    if created_at is None:
        created_at = datetime.now(tz=timezone.utc)
    return EventCreate(
        source_type=source_type,
        source_external_id=source_external_id,
        content=content,
        source_metadata={"test": True},
        created_at=created_at,
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
    )


@pytest.mark.asyncio
async def test_create_and_get_by_id(db_session: AsyncSession) -> None:
    repo = EventRepository(db_session)
    data = _make_event()
    created = await repo.create(data)

    assert created.id is not None
    assert created.source_type == SourceType.doc
    assert created.content == data.content

    fetched = await repo.get_by_id(created.id)
    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.content_hash == data.content_hash


@pytest.mark.asyncio
async def test_get_by_id_returns_none_for_missing(db_session: AsyncSession) -> None:
    repo = EventRepository(db_session)
    result = await repo.get_by_id(uuid.uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_get_by_source_returns_correct_event(db_session: AsyncSession) -> None:
    repo = EventRepository(db_session)
    data = _make_event(source_type=SourceType.slack_message, source_external_id="CH001:ts123")
    await repo.create(data)

    found = await repo.get_by_source(SourceType.slack_message, "CH001:ts123")
    assert found is not None
    assert found.source_external_id == "CH001:ts123"


@pytest.mark.asyncio
async def test_get_by_source_returns_none_when_missing(db_session: AsyncSession) -> None:
    repo = EventRepository(db_session)
    result = await repo.get_by_source(SourceType.doc, "nonexistent/path")
    assert result is None


@pytest.mark.asyncio
async def test_unique_constraint_raises_integrity_error(db_session: AsyncSession) -> None:
    """Inserting the same (source_type, source_external_id) twice raises IntegrityError."""
    repo = EventRepository(db_session)
    data = _make_event(source_external_id="duplicate-id")
    await repo.create(data)

    duplicate = _make_event(source_external_id="duplicate-id", content="different content")
    with pytest.raises(IntegrityError):
        await repo.create(duplicate)


@pytest.mark.asyncio
async def test_get_by_content_hash_finds_existing(db_session: AsyncSession) -> None:
    repo = EventRepository(db_session)
    content = "unique content for hash test"
    data = _make_event(content=content)
    await repo.create(data)

    found = await repo.get_by_content_hash(data.content_hash)
    assert found is not None
    assert found.content == content


@pytest.mark.asyncio
async def test_get_by_content_hash_returns_none_when_missing(db_session: AsyncSession) -> None:
    repo = EventRepository(db_session)
    result = await repo.get_by_content_hash("a" * 64)
    assert result is None


@pytest.mark.asyncio
async def test_list_since_filters_by_created_at(db_session: AsyncSession) -> None:
    repo = EventRepository(db_session)
    now = datetime.now(tz=timezone.utc)
    old = _make_event(content="old", created_at=now - timedelta(days=10))
    recent = _make_event(content="recent", created_at=now - timedelta(hours=1))

    await repo.create(old)
    await repo.create(recent)

    cutoff = now - timedelta(days=1)
    results = await repo.list_since(cutoff)

    contents = {r.content for r in results}
    assert "recent" in contents
    assert "old" not in contents
