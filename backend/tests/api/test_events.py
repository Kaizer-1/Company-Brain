"""Tests for GET /api/events/{event_id} (Phase 3C).

Uses real Postgres testcontainer with a seeded event row.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from unittest.mock import MagicMock

from app.api.events import router
from app.models.events import Event
from app.models.enums import SourceType

pytestmark = pytest.mark.asyncio


def _make_app(session_factory: object) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.state.session_factory = session_factory
    return TestClient(app)


async def _seed_event(session: AsyncSession) -> uuid.UUID:
    eid = uuid.uuid4()
    event = Event(
        id=eid,
        source_type=SourceType.doc,
        source_external_id="test-doc-001",
        content="Auth service migration: from legacy-auth to auth-service.",
        source_metadata={"author": "alice"},
        created_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
        ingested_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
        content_hash="abc123",
    )
    session.add(event)
    await session.flush()
    return eid


def test_get_event_returns_content(db_session: AsyncSession) -> None:
    """GET /api/events/{id} returns the event content for a known ID."""
    import asyncio
    eid = asyncio.get_event_loop().run_until_complete(_seed_event(db_session))

    from sqlalchemy.ext.asyncio import async_sessionmaker
    from contextlib import asynccontextmanager
    from collections.abc import AsyncIterator

    @asynccontextmanager
    async def _factory() -> AsyncIterator[AsyncSession]:  # type: ignore[misc]
        yield db_session

    client = _make_app(_factory)
    resp = client.get(f"/api/events/{eid}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(eid)
    assert "auth service migration" in data["content"].lower()
    assert data["source_type"] == "doc"


def test_get_event_404_for_unknown_id() -> None:
    """GET /api/events/{id} returns 404 for an event that doesn't exist."""
    from contextlib import asynccontextmanager
    from collections.abc import AsyncIterator
    from unittest.mock import AsyncMock

    missing_id = uuid.uuid4()

    # Stub session that returns None from repo.get_by_id
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    @asynccontextmanager
    async def _factory() -> AsyncIterator:  # type: ignore[misc]
        yield mock_session

    app = FastAPI()
    app.include_router(router)
    app.state.session_factory = _factory

    from app.db.repositories.events import EventRepository
    original_get = EventRepository.get_by_id

    async def _mock_get(self: EventRepository, eid: uuid.UUID) -> None:
        return None

    import unittest.mock
    with unittest.mock.patch.object(EventRepository, "get_by_id", _mock_get):
        client = TestClient(app)
        resp = client.get(f"/api/events/{missing_id}")

    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_get_event_invalid_uuid_rejected() -> None:
    """A non-UUID path segment returns 422 (FastAPI parameter validation)."""
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    resp = client.get("/api/events/not-a-uuid")
    assert resp.status_code == 422
