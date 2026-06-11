"""Tests for GET /api/audit/ingestion-runs (Phase 5B).

Uses the real Postgres testcontainer: seed events + ingestion_runs (the endpoint joins them),
then assert newest-first ordering, the joined fields, and cursor pagination. Mirrors the
merge-decisions endpoint test (tests/api/test_audit.py).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import router
from app.db.repositories.events import EventRepository
from app.db.repositories.ingestion_runs import IngestionRunRepository
from app.ingestion.schemas import IngestionRunUpsert
from app.models.enums import SourceType
from app.schemas.postgres import EventCreate

_STAGES = [
    {"name": "extract", "status": "ok", "duration_ms": 3800.0, "detail": "1 nodes"},
    {"name": "resolve", "status": "ok", "duration_ms": 4200.0, "detail": "types=[Person]"},
    {"name": "consolidate", "status": "skipped", "duration_ms": 0.0, "detail": "no Decision"},
]


async def _seed_runs(session: AsyncSession) -> None:
    """Three events + their ingestion runs, with strictly increasing started_at."""
    events = EventRepository(session)
    runs = IngestionRunRepository(session)
    for i in range(3):
        ev = await events.create(
            EventCreate(
                source_type=SourceType.slack_message,
                source_external_id=f"ingest-test-{i}",
                content=f"New hire number {i} joined the platform team this week",
                source_metadata={"source_ref": "test"},
                created_at=datetime(2026, 6, 10, 12, 0, i, tzinfo=UTC),
                content_hash=f"hash-{i}",
            )
        )
        await runs.upsert(
            IngestionRunUpsert(
                event_id=ev.id,
                status="reconciled",
                started_at=datetime(2026, 6, 10, 12, 0, i, tzinfo=UTC),
                completed_at=datetime(2026, 6, 10, 12, 0, i, 500_000, tzinfo=UTC),
                stages_json=_STAGES,
                nodes_created_count=1,
                nodes_merged_count=0,
                edges_created_count=0,
                contradictions_count=0,
                cost_usd=0.0031,
                error=None,
            )
        )


def _make_app(session: AsyncSession) -> TestClient:
    @asynccontextmanager
    async def _factory() -> AsyncIterator[AsyncSession]:
        yield session

    app = FastAPI()
    app.include_router(router)
    app.state.session_factory = _factory
    return TestClient(app)


def test_ingestion_runs_newest_first_with_join(db_session: AsyncSession) -> None:
    """Returns all runs newest-first, with the joined source_kind, snippet, and typed stages."""
    asyncio.get_event_loop().run_until_complete(_seed_runs(db_session))
    client = _make_app(db_session)

    resp = client.get("/api/audit/ingestion-runs")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 3
    assert data["next_cursor"] is None

    started = [item["started_at"] for item in data["items"]]
    assert started == sorted(started, reverse=True)  # newest first

    row = data["items"][0]
    assert row["source_kind"] == "slack_message"  # joined from events
    assert "New hire" in row["content_snippet"]   # joined snippet
    assert len(row["stages"]) == 3                 # parsed into typed StageResult
    assert row["stages"][0]["name"] == "extract"
    assert row["duration_ms"] == 500.0             # computed completed_at - started_at


def test_ingestion_runs_cursor_pagination(db_session: AsyncSession) -> None:
    """limit + before cursor walk the feed without overlap."""
    asyncio.get_event_loop().run_until_complete(_seed_runs(db_session))
    client = _make_app(db_session)

    page1 = client.get("/api/audit/ingestion-runs?limit=2").json()
    assert len(page1["items"]) == 2
    assert page1["next_cursor"] is not None

    page2 = client.get(f"/api/audit/ingestion-runs?limit=2&before={page1['next_cursor']}").json()
    assert len(page2["items"]) == 1
    assert page2["next_cursor"] is None

    # No overlap between pages.
    ids1 = {item["id"] for item in page1["items"]}
    ids2 = {item["id"] for item in page2["items"]}
    assert ids1.isdisjoint(ids2)
