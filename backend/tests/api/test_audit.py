"""Tests for GET /api/audit/merge-decisions (Phase 3C).

Uses real Postgres testcontainer with seeded merge_decisions rows.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import FastAPI
from fastapi.testclient import TestClient
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from app.api.audit import router
from app.db.repositories.resolution import MergeDecisionRepository
from app.models.enums import MergeDecisionType, NodeType
from app.schemas.postgres import MergeDecisionCreate

pytestmark = pytest.mark.asyncio


async def _seed_decisions(session: AsyncSession) -> None:
    repo = MergeDecisionRepository(session)
    # Tier-1 auto-merge
    await repo.record(
        MergeDecisionCreate(
            source_node_id="alice",
            target_node_id="alice-alias",
            node_type=NodeType.Person,
            decision=MergeDecisionType.auto_merge,
            tier=1,
            embedding_similarity=None,
            rules_matched=["exact_email"],
        )
    )
    # Tier-2 LLM merge
    await repo.record(
        MergeDecisionCreate(
            source_node_id="payments-api",
            target_node_id="payments_api",
            node_type=NodeType.Service,
            decision=MergeDecisionType.llm_merge,
            tier=2,
            embedding_similarity=0.91,
            llm_reasoning="Same service — different naming convention.",
            llm_model="claude-3.5-haiku",
        )
    )
    # Tier-2 LLM no-merge
    await repo.record(
        MergeDecisionCreate(
            source_node_id="notifications-api",
            target_node_id="notification-worker",
            node_type=NodeType.Service,
            decision=MergeDecisionType.llm_no_merge,
            tier=2,
            embedding_similarity=0.73,
            llm_reasoning="Different services: API vs worker.",
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


def test_audit_returns_all_rows(db_session: AsyncSession) -> None:
    """Default (no filters) returns all seeded rows."""
    import asyncio
    asyncio.get_event_loop().run_until_complete(_seed_decisions(db_session))
    client = _make_app(db_session)

    resp = client.get("/api/audit/merge-decisions")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert len(data["items"]) == 3


def test_audit_filter_by_tier(db_session: AsyncSession) -> None:
    """tier=2 returns only Tier-2 rows."""
    import asyncio
    asyncio.get_event_loop().run_until_complete(_seed_decisions(db_session))
    client = _make_app(db_session)

    resp = client.get("/api/audit/merge-decisions?tier=2")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    for item in data["items"]:
        assert item["tier"] == 2


def test_audit_filter_by_decision(db_session: AsyncSession) -> None:
    """decision=llm_no_merge returns only that decision type."""
    import asyncio
    asyncio.get_event_loop().run_until_complete(_seed_decisions(db_session))
    client = _make_app(db_session)

    resp = client.get("/api/audit/merge-decisions?decision=llm_no_merge")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["decision"] == "llm_no_merge"


def test_audit_filter_by_node_type(db_session: AsyncSession) -> None:
    """node_type=Person returns only Person rows."""
    import asyncio
    asyncio.get_event_loop().run_until_complete(_seed_decisions(db_session))
    client = _make_app(db_session)

    resp = client.get("/api/audit/merge-decisions?node_type=Person")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["node_type"] == "Person"


def test_audit_pagination(db_session: AsyncSession) -> None:
    """limit and offset slice the result correctly."""
    import asyncio
    asyncio.get_event_loop().run_until_complete(_seed_decisions(db_session))
    client = _make_app(db_session)

    resp = client.get("/api/audit/merge-decisions?limit=2&offset=0")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 2
    assert data["total"] == 3  # total is the full unfiltered count

    resp2 = client.get("/api/audit/merge-decisions?limit=2&offset=2")
    data2 = resp2.json()
    assert len(data2["items"]) == 1


def test_audit_sorted_newest_first(db_session: AsyncSession) -> None:
    """Rows are returned newest-first (created_at DESC)."""
    import asyncio
    asyncio.get_event_loop().run_until_complete(_seed_decisions(db_session))
    client = _make_app(db_session)

    resp = client.get("/api/audit/merge-decisions")
    data = resp.json()
    dates = [item["created_at"] for item in data["items"]]
    assert dates == sorted(dates, reverse=True)
