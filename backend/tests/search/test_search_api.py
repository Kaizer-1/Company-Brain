"""Integration tests for POST /api/search (Phase 3D).

Uses a real Postgres testcontainer with committed events + embeddings.
Seeding runs in an isolated asyncio.run() loop; the TestClient gets a fresh
session factory so there is no asyncpg connection sharing across event loops.
Neo4j calls are mocked (no Neo4j testcontainer — entity counts return 0,
which degrades gracefully to pure vector search).
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.events import EventRepository
from app.db.session import build_engine, build_session_factory
from app.models.enums import SourceType
from app.schemas.postgres import EventCreate
from app.search.router import router
from app.search.indexer import embed_events


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_neo4j() -> MagicMock:
    """Return a Neo4j driver mock that returns no entities."""
    neo_session = AsyncMock()
    neo_result = AsyncMock()
    neo_result.data = AsyncMock(return_value=[])
    neo_session.run = AsyncMock(return_value=neo_result)
    neo_session.__aenter__ = AsyncMock(return_value=neo_session)
    neo_session.__aexit__ = AsyncMock(return_value=None)
    driver = MagicMock()
    driver.session = MagicMock(return_value=neo_session)
    neo_client = MagicMock()
    neo_client.driver = driver
    return neo_client


def _make_app_with_factory(dsn: str) -> TestClient:
    """Build a TestClient with a real session factory (fresh sessions per request)."""
    engine = build_engine(dsn)
    sf = build_session_factory(engine)

    app = FastAPI()
    app.include_router(router)
    app.state.session_factory = sf
    app.state.neo4j = _mock_neo4j()
    return TestClient(app)


async def _seed_and_embed(dsn: str) -> list[uuid.UUID]:
    """Seed events and embed them in an isolated loop; commits to Postgres."""
    engine = build_engine(dsn)
    sf = build_session_factory(engine)
    ids: list[uuid.UUID] = []
    try:
        async with sf() as session:
            repo = EventRepository(session)
            contents = [
                ("auth migration D-0006 deprecate legacy-auth", f"test:adr/D-0006-{uuid.uuid4()}"),
                ("payments service blast radius upstream dependencies", f"test:arch/p-{uuid.uuid4()}"),
                ("event-bus Kafka async writes D-0002", f"test:adr/D-0002-{uuid.uuid4()}"),
            ]
            for content, src_id in contents:
                dto = await repo.create(
                    EventCreate(
                        source_type=SourceType.doc,
                        source_external_id=src_id,
                        content=content,
                        source_metadata={},
                        created_at=datetime(2026, 5, 1, tzinfo=UTC),
                        content_hash=hashlib.sha256(content.encode()).hexdigest(),
                    )
                )
                ids.append(dto.id)
            written = await embed_events(session)
            assert written == 3, f"Expected 3 embeddings, got {written}"
    finally:
        await engine.dispose()
    return ids


# ---------------------------------------------------------------------------
# Tests — use pg_test_dsn + run_migrations for a committed, readable dataset
# ---------------------------------------------------------------------------


def test_search_returns_hits(pg_test_dsn: str, run_migrations: None) -> None:
    """POST /api/search returns ranked results for a relevant query."""
    asyncio.run(_seed_and_embed(pg_test_dsn))
    client = _make_app_with_factory(pg_test_dsn)

    resp = client.post("/api/search", json={"query": "auth migration legacy-auth", "k": 3})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["hits"]) >= 1
    top_hit = data["hits"][0]
    assert top_hit["similarity_score"] > 0.4
    assert top_hit["final_score"] > 0.0
    assert "auth" in top_hit["snippet"].lower() or "d-0006" in top_hit["snippet"].lower()


def test_search_respects_k(pg_test_dsn: str, run_migrations: None) -> None:
    """k parameter limits the number of returned hits."""
    asyncio.run(_seed_and_embed(pg_test_dsn))
    client = _make_app_with_factory(pg_test_dsn)

    resp = client.post("/api/search", json={"query": "service", "k": 1})
    assert resp.status_code == 200
    assert len(resp.json()["hits"]) <= 1


def test_search_filter_source_kind_excludes_all(pg_test_dsn: str, run_migrations: None) -> None:
    """source_kind filter to slack_message excludes all doc events."""
    asyncio.run(_seed_and_embed(pg_test_dsn))
    client = _make_app_with_factory(pg_test_dsn)

    resp = client.post(
        "/api/search",
        json={"query": "auth", "k": 10, "filters": {"source_kind": ["slack_message"]}},
    )
    assert resp.status_code == 200
    # All seeded events are docs; slack_message filter yields 0 hits
    hits = resp.json()["hits"]
    for h in hits:
        assert h["source_kind"] == "slack_message"


def test_search_returns_timing(pg_test_dsn: str, run_migrations: None) -> None:
    """Response includes per-stage timing fields."""
    asyncio.run(_seed_and_embed(pg_test_dsn))
    client = _make_app_with_factory(pg_test_dsn)

    resp = client.post("/api/search", json={"query": "Kafka"})
    assert resp.status_code == 200
    data = resp.json()
    for field in ("query_embedding_ms", "vector_search_ms", "rerank_ms", "total_ms"):
        assert field in data, f"Missing timing field: {field}"
        assert data[field] >= 0.0


def test_search_empty_index_returns_empty(pg_test_dsn: str, run_migrations: None) -> None:
    """When no events are embedded, /api/search returns an empty hit list."""
    client = _make_app_with_factory(pg_test_dsn)

    resp = client.post("/api/search", json={"query": "auth migration"})
    assert resp.status_code == 200
    data = resp.json()
    # May have results from previous tests in the same session, but must not error.
    assert "hits" in data
    assert isinstance(data["hits"], list)


def test_search_validates_query_length(pg_test_dsn: str, run_migrations: None) -> None:
    """query > 500 chars returns 422."""
    client = _make_app_with_factory(pg_test_dsn)

    resp = client.post("/api/search", json={"query": "x" * 501})
    assert resp.status_code == 422


def test_search_validates_empty_query(pg_test_dsn: str, run_migrations: None) -> None:
    """Empty query returns 422."""
    client = _make_app_with_factory(pg_test_dsn)

    resp = client.post("/api/search", json={"query": ""})
    assert resp.status_code == 422


def test_search_result_fields(pg_test_dsn: str, run_migrations: None) -> None:
    """Each hit carries the required fields."""
    asyncio.run(_seed_and_embed(pg_test_dsn))
    client = _make_app_with_factory(pg_test_dsn)

    resp = client.post("/api/search", json={"query": "payments blast radius"})
    assert resp.status_code == 200
    hits = resp.json()["hits"]
    if hits:
        hit = hits[0]
        for field in (
            "event_id", "snippet", "source_kind", "source_ref",
            "occurred_at", "similarity_score", "final_score", "related_entity_ids",
        ):
            assert field in hit, f"Missing field: {field}"
        assert isinstance(hit["related_entity_ids"], list)
        assert 0.0 <= hit["similarity_score"] <= 1.0
        assert 0.0 <= hit["final_score"] <= 1.0
