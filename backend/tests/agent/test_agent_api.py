"""Integration tests for POST /api/ask (Phase 4A).

Uses a real Postgres testcontainer with committed + embedded events (so citations resolve
against real rows) and a mocked Neo4j (entity counts 0 — search degrades to pure vector,
which is enough to exercise the agent path). The OpenRouter client is replaced with a
scripted FakeClient via monkeypatch, so the router and synthesis calls are deterministic
and no API key is needed.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.agent import runner
from app.agent.api_router import router
from app.db.repositories.events import EventRepository
from app.db.session import build_engine, build_session_factory
from app.models.enums import SourceType
from app.schemas.postgres import EventCreate
from app.search.indexer import embed_events

from .conftest import FakeClient


def _route(route: str, tool_input: dict | None = None) -> str:
    return json.dumps({"route": route, "reasoning": "test reasoning text", "tool_input": tool_input or {}})


def _answer(answer: str, citations: list[str]) -> str:
    return json.dumps({"answer": answer, "citations": citations, "confidence": "high"})


def _mock_neo4j() -> MagicMock:
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


def _make_app(dsn: str, fake: FakeClient, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(runner, "OpenRouterClient", lambda *a, **k: fake)
    engine = build_engine(dsn)
    sf = build_session_factory(engine)
    app = FastAPI()
    app.include_router(router)
    app.state.session_factory = sf
    app.state.neo4j = _mock_neo4j()
    return TestClient(app)


async def _seed_and_embed(dsn: str) -> list[uuid.UUID]:
    engine = build_engine(dsn)
    sf = build_session_factory(engine)
    ids: list[uuid.UUID] = []
    try:
        async with sf() as session:
            repo = EventRepository(session)
            contents = [
                ("auth migration D-0006 deprecate legacy-auth move to auth-service", f"test:adr/D-0006-{uuid.uuid4()}"),
                ("payments service blast radius upstream dependencies", f"test:arch/p-{uuid.uuid4()}"),
                ("event-bus Kafka async writes decision D-0002", f"test:adr/D-0002-{uuid.uuid4()}"),
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
            assert written == 3
    finally:
        await engine.dispose()
    return ids


def test_ask_search_returns_grounded_answer(pg_test_dsn: str, run_migrations: None, monkeypatch: pytest.MonkeyPatch) -> None:
    ids = asyncio.run(_seed_and_embed(pg_test_dsn))
    eid = str(ids[0])
    fake = FakeClient(content=[_route("search"), _answer(f"Auth is migrating off legacy-auth [evt:{eid}].", [eid])])
    client = _make_app(pg_test_dsn, fake, monkeypatch)

    resp = client.post("/api/ask", json={"question": "what is happening with auth migration?"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["route"] == "search"
    assert data["error"] is None
    assert len(data["citations"]) == 1
    assert data["citations"][0]["event_id"] == eid
    assert "legacy-auth" in data["citations"][0]["snippet"]
    assert "total" in data["timings_ms"]


def test_ask_debug_mode_includes_trace(pg_test_dsn: str, run_migrations: None, monkeypatch: pytest.MonkeyPatch) -> None:
    ids = asyncio.run(_seed_and_embed(pg_test_dsn))
    eid = str(ids[0])
    fake = FakeClient(content=[_route("search"), _answer(f"Answer [evt:{eid}].", [eid])])
    client = _make_app(pg_test_dsn, fake, monkeypatch)

    resp = client.post("/api/ask", json={"question": "tell me about auth", "debug": True})
    assert resp.status_code == 200
    data = resp.json()
    assert data["debug"] is not None
    assert data["debug"]["route"] == "search"
    assert data["debug"]["verified"] is True
    assert "classify_route" in data["debug"]["timings_ms"]


def test_ask_unknown_route_refuses(pg_test_dsn: str, run_migrations: None, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeClient(content=_route("unknown"))
    client = _make_app(pg_test_dsn, fake, monkeypatch)

    resp = client.post("/api/ask", json={"question": "what's the weather in Bangalore?"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["route"] == "unknown"
    assert data["citations"] == []
    assert len(fake.calls) == 1  # synthesis never runs for unknown


def test_ask_validates_short_question(pg_test_dsn: str, run_migrations: None, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeClient(content=_route("search"))
    client = _make_app(pg_test_dsn, fake, monkeypatch)

    resp = client.post("/api/ask", json={"question": "x"})
    assert resp.status_code == 422
