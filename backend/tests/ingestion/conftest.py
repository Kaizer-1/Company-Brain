"""Fixtures for the ingestion tests: a committing session factory + a fake LLM client.

The ingestion orchestrator commits per stage, so the rollback-based ``db_session`` fixture is not
usable here; this module builds a real committing ``async_sessionmaker`` over the migrated test
Postgres and truncates the relevant tables around each test. The ``FakeClient`` duck-types the
``OpenRouterClient.complete`` surface so the whole pipeline runs deterministically with **no
network calls** — it returns canned extraction / resolution / contradiction JSON chosen by the
system prompt.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.repositories.events import EventRepository
from app.extraction.client import CompletionResult
from app.models.enums import SourceType
from app.schemas.postgres import EventCreate

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from app.schemas.postgres import EventDTO

_INGEST_TABLES = (
    "ingestion_runs",
    "extraction_runs",
    "event_embeddings",
    "merge_decisions",
    "events",
)


class FakeClient:
    """A no-network stand-in for ``OpenRouterClient``.

    Returns a fixed extraction payload, and decides resolution/contradiction verdicts from
    constructor flags. ``calls`` records the models invoked so tests can assert call counts
    (e.g. extraction was skipped on replay).
    """

    def __init__(
        self,
        *,
        extraction: dict[str, object] | None = None,
        contradicts: bool = False,
        same_entity: bool = False,
    ) -> None:
        self._extraction_json = json.dumps(extraction or {"entities": [], "relationships": []})
        self._contradicts = contradicts
        self._same = same_entity
        self.calls: list[str] = []

    async def complete(
        self, *, messages: list[dict[str, str]], model: str, **_: object
    ) -> CompletionResult:
        system = messages[0]["content"] if messages else ""
        self.calls.append(model)
        if "resolution adjudicator" in system:
            content = json.dumps(
                {"same": self._same, "confidence": 0.9 if self._same else 0.1, "reasoning": "fake"}
            )
        elif "contradicts a recorded engineering decision" in system:
            content = json.dumps(
                {"contradicts": self._contradicts, "confidence": 0.9, "reasoning": "fake"}
            )
        else:  # extraction
            content = self._extraction_json
        return CompletionResult(
            content=content, model=model, cost_usd=0.0001, prompt_tokens=10, completion_tokens=10
        )

    async def aclose(self) -> None:
        return None


@pytest_asyncio.fixture()
async def session_factory(
    pg_test_dsn: str, run_migrations: None
) -> AsyncIterator[async_sessionmaker]:
    """A committing session factory over the migrated test DB, truncated around each test."""
    from app.db.session import build_engine

    engine = build_engine(pg_test_dsn)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await session.execute(text(f"TRUNCATE TABLE {', '.join(_INGEST_TABLES)} CASCADE"))
        await session.commit()
    try:
        yield factory
    finally:
        await engine.dispose()


async def seed_event(
    factory: async_sessionmaker,
    *,
    source_type: SourceType,
    content: str,
    external_id: str | None = None,
    occurred_at: datetime | None = None,
) -> EventDTO:
    """Insert one raw event and return its DTO (the precondition for ``reconcile_event``)."""
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    ext = external_id or f"test-{content_hash[:12]}"
    async with factory() as session:
        event = await EventRepository(session).create(
            EventCreate(
                source_type=source_type,
                source_external_id=ext,
                content=content,
                source_metadata={"source_ref": "test"},
                created_at=occurred_at or datetime(2026, 6, 10, tzinfo=UTC),
                content_hash=content_hash,
            )
        )
        await session.commit()
    return event


def person_extraction(name: str) -> dict[str, object]:
    """A minimal extraction payload asserting one Person."""
    return {
        "entities": [
            {
                "type": "Person",
                "canonical_name": name,
                "properties": {"role": "Software Engineer"},
                "evidence_quote": f"welcome aboard {name}",
                "confidence": 0.95,
            }
        ],
        "relationships": [],
    }


async def node_label_counts(driver: object) -> dict[str, int]:
    """Non-merged node counts by label (the structural acceptance signal)."""
    query = (
        "MATCH (n) WHERE coalesce(n.status,'active') <> 'merged' AND NOT n:_Migration "
        "RETURN labels(n)[0] AS label, count(n) AS c"
    )
    out: dict[str, int] = {}
    async with driver.session() as session:  # type: ignore[attr-defined]
        result = await session.run(query)
        async for record in result:
            out[str(record["label"])] = int(record["c"])
    return out
