"""HTTP-layer tests for ``POST /api/events`` (Phase 5A).

The reconciliation itself is covered by the orchestrator/idempotency tests; here we monkeypatch
``reconcile_event`` so the test exercises only the endpoint's own logic: event insertion, the
idempotent-insert dedup path, response shaping, and the single-writer lock's 503.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.ingestion import api_router
from app.ingestion.schemas import IngestEventResponse
from app.main import app

if TYPE_CHECKING:
    import uuid

pytestmark = pytest.mark.asyncio

_BODY = {
    "source_kind": "slack_message",
    "source_ref": "#payments-eng",
    "content": "the team thinks the legacy-auth migration plan is now stale and should change",
    "occurred_at": "2026-06-10T00:00:00Z",
    "external_id": "api-test-1",
}


def _wire(session_factory: object, neo4j_driver: object) -> None:
    app.state.session_factory = session_factory
    app.state.neo4j = SimpleNamespace(driver=neo4j_driver)


async def _events_count(session_factory: object) -> int:
    async with session_factory() as session:  # type: ignore[operator]
        result = await session.execute(text("SELECT count(*) FROM events"))
        return int(result.scalar_one())


async def test_post_event_inserts_and_returns_reconciliation(
    session_factory: object, neo4j_driver: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_reconcile(event_id: uuid.UUID, **_: object) -> IngestEventResponse:
        return IngestEventResponse(event_id=event_id, status="reconciled", duration_ms=1.0)

    monkeypatch.setattr(api_router, "reconcile_event", fake_reconcile)
    _wire(session_factory, neo4j_driver)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/events", json=_BODY)

    assert response.status_code == 200
    assert response.json()["status"] == "reconciled"
    assert await _events_count(session_factory) == 1


async def test_duplicate_post_does_not_double_insert(
    session_factory: object, neo4j_driver: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_reconcile(event_id: uuid.UUID, **_: object) -> IngestEventResponse:
        return IngestEventResponse(event_id=event_id, status="reconciled")

    monkeypatch.setattr(api_router, "reconcile_event", fake_reconcile)
    _wire(session_factory, neo4j_driver)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post("/api/events", json=_BODY)
        second = await client.post("/api/events", json=_BODY)

    assert first.status_code == 200
    assert second.status_code == 200
    # The unique (source_type, external_id) constraint means the event is inserted exactly once.
    assert await _events_count(session_factory) == 1


async def test_lock_timeout_returns_503(
    session_factory: object, neo4j_driver: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_reconcile(event_id: uuid.UUID, **_: object) -> IngestEventResponse:
        return IngestEventResponse(event_id=event_id, status="reconciled")

    monkeypatch.setattr(api_router, "reconcile_event", fake_reconcile)
    monkeypatch.setattr(api_router, "_LOCK_TIMEOUT_S", 0.05)
    _wire(session_factory, neo4j_driver)

    await api_router._INGEST_LOCK.acquire()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/events", json={**_BODY, "external_id": "api-test-lock"}
            )
        assert response.status_code == 503
    finally:
        api_router._INGEST_LOCK.release()
        await asyncio.sleep(0)
