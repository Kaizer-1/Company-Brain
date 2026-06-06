"""Integration tests for POST /api/ask/stream (Phase 4B).

Uses the same testcontainer Postgres + mocked Neo4j pattern as test_agent_api.py.
The OpenRouter client is replaced with FakeStreamingClient (from test_streaming.py)
so no API key or network is needed.

We verify the SSE event sequence: route → tool_start → tool_done → synthesis_start →
synthesis_token(s) → synthesis_done → verify_start → verify_done → complete.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent import runner
from app.agent.api_router import router
from app.db.repositories.events import EventRepository
from app.db.session import build_engine, build_session_factory
from app.extraction.client import CompletionResult
from app.models.enums import SourceType
from app.schemas.postgres import EventCreate
from app.search.indexer import embed_events

from .test_streaming import FakeStreamingClient

if TYPE_CHECKING:
    import pytest


def _route(route: str, tool_input: dict | None = None) -> str:
    return json.dumps({"route": route, "reasoning": "test routing", "tool_input": tool_input or {}})


def _answer(answer: str, citations: list[str]) -> str:
    return json.dumps({"answer": answer, "citations": citations, "confidence": "high"})


class CombinedFakeClient(FakeStreamingClient):
    """FakeStreamingClient that also supports .complete() for the router call."""

    def __init__(
        self,
        *,
        router_json: str,
        stream_tokens: list[str],
        cost_usd: float = 0.001,
    ) -> None:
        super().__init__(stream_tokens=stream_tokens, cost_usd=cost_usd)
        self._script = [router_json]

    async def complete(  # type: ignore[override]
        self, *, messages, model, temperature=None, max_tokens=None, response_format=None
    ) -> CompletionResult:
        self.calls.append({"messages": messages, "model": model})
        idx = min(len(self.calls) - 1, len(self._script) - 1)
        return CompletionResult(
            content=self._script[idx],
            model=model,
            cost_usd=self._cost,
            prompt_tokens=10,
            completion_tokens=5,
        )


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


def _make_app(
    dsn: str,
    fake: CombinedFakeClient,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    # Patch OpenRouterClient in both runner and api_router modules so both
    # the JSON endpoint and the streaming endpoint use the fake client.
    import app.agent.api_router as api_mod

    monkeypatch.setattr(runner, "OpenRouterClient", lambda *a, **k: fake)
    monkeypatch.setattr(api_mod, "OpenRouterClient", lambda *a, **k: fake)

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
            content = "auth migration D-0006 deprecate legacy-auth"
            src_id = f"test:adr/stream-{uuid.uuid4()}"
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
            await embed_events(session)
    finally:
        await engine.dispose()
    return ids


def _parse_sse_stream(content: str) -> list[dict]:
    """Parse raw SSE text into a list of {type, data} dicts."""
    events = []
    for frame in content.split("\n\n"):
        frame = frame.strip()
        if not frame:
            continue
        evt_type = ""
        data_str = ""
        for line in frame.split("\n"):
            if line.startswith("event: "):
                evt_type = line[7:]
            elif line.startswith("data: "):
                data_str = line[6:]
        if evt_type and data_str:
            with contextlib.suppress(json.JSONDecodeError):
                events.append({"type": evt_type, **json.loads(data_str)})
    return events


def test_stream_search_emits_correct_event_sequence(
    pg_test_dsn: str, run_migrations: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = asyncio.run(_seed_and_embed(pg_test_dsn))
    eid = str(ids[0])
    answer_json = _answer(f"Auth is migrating [evt:{eid}].", [eid])

    fake = CombinedFakeClient(
        router_json=_route("search"),
        stream_tokens=list(answer_json),
    )
    client = _make_app(pg_test_dsn, fake, monkeypatch)

    resp = client.post(
        "/api/ask/stream",
        json={"question": "what is happening with auth?"},
        headers={"Accept": "text/event-stream"},
    )
    assert resp.status_code == 200
    events = _parse_sse_stream(resp.text)

    types = [e["type"] for e in events]
    assert "route" in types
    assert "tool_start" in types
    assert "tool_done" in types
    assert "synthesis_start" in types
    assert "synthesis_token" in types
    assert "synthesis_done" in types
    assert "verify_start" in types
    assert "verify_done" in types
    assert "complete" in types

    # route event has correct route
    route_evt = next(e for e in events if e["type"] == "route")
    assert route_evt["route"] == "search"

    # complete event mirrors the JSON endpoint's structure
    complete_evt = next(e for e in events if e["type"] == "complete")
    assert complete_evt["route"] == "search"
    assert complete_evt["error"] is None
    assert isinstance(complete_evt["citations"], list)


def test_stream_unknown_emits_complete_without_synthesis(
    pg_test_dsn: str, run_migrations: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = CombinedFakeClient(
        router_json=_route("unknown"),
        stream_tokens=[],
    )
    client = _make_app(pg_test_dsn, fake, monkeypatch)

    resp = client.post(
        "/api/ask/stream",
        json={"question": "what's the weather?"},
        headers={"Accept": "text/event-stream"},
    )
    assert resp.status_code == 200
    events = _parse_sse_stream(resp.text)
    types = [e["type"] for e in events]

    assert "route" in types
    assert "tool_start" in types
    assert "complete" in types
    assert "synthesis_start" not in types  # unknown skips synthesis

    complete_evt = next(e for e in events if e["type"] == "complete")
    assert complete_evt["route"] == "unknown"


def test_stream_synthesis_tokens_accumulate_to_full_answer(
    pg_test_dsn: str, run_migrations: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = asyncio.run(_seed_and_embed(pg_test_dsn))
    eid = str(ids[0])
    answer_json = _answer(f"Grounded answer [evt:{eid}].", [eid])

    fake = CombinedFakeClient(
        router_json=_route("search"),
        stream_tokens=list(answer_json),
    )
    client = _make_app(pg_test_dsn, fake, monkeypatch)

    resp = client.post(
        "/api/ask/stream",
        json={"question": "tell me about auth"},
        headers={"Accept": "text/event-stream"},
    )
    events = _parse_sse_stream(resp.text)

    tokens = [e["text"] for e in events if e["type"] == "synthesis_token"]
    accumulated = "".join(tokens)
    assert accumulated == answer_json
