"""Real Neo4j (+ Postgres) tests for the contradiction/Message pass (Phase 3B; ADR 0019)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.contradiction.detector import detect_contradictions
from app.contradiction.message_ingest import ingest_messages
from app.db.repositories.events import EventRepository
from app.extraction.client import CompletionResult
from app.models.enums import SourceType
from app.schemas.postgres import EventCreate
from app.synthetic.company import REFERENCE_NOW

pytestmark = pytest.mark.asyncio


class _StubClient:
    """A stand-in OpenRouter client whose verdict is fixed (no network)."""

    def __init__(self, *, contradicts: bool) -> None:
        self._contradicts = contradicts

    async def complete(self, **_kwargs: object) -> CompletionResult:
        body = '{"contradicts": %s, "confidence": 0.92, "reasoning": "stub"}' % (
            "true" if self._contradicts else "false"
        )
        return CompletionResult(
            content=body, model="stub", cost_usd=0.0001, prompt_tokens=1, completion_tokens=1
        )


async def test_message_ingest_creates_one_node_per_slack_event(
    neo4j_driver: object, db_session: object
) -> None:
    repo = EventRepository(db_session)  # type: ignore[arg-type]
    for i in range(3):
        await repo.create(
            EventCreate(
                source_type=SourceType.slack_message,
                source_external_id=f"C_X-{i:04d}",
                content=f"message {i}",
                created_at=datetime(2026, 5, 1, tzinfo=UTC),
                content_hash=f"h{i}",
            )
        )
    count = await ingest_messages(neo4j_driver, db_session)
    assert count == 3
    async with neo4j_driver.session() as s:  # type: ignore[attr-defined]
        rec = await (await s.run("MATCH (m:Message) RETURN count(m) AS c")).single()
    assert rec["c"] == 3


async def test_detector_writes_contradicts_edge_on_positive_verdict(neo4j_driver: object) -> None:
    recent = (REFERENCE_NOW - timedelta(days=10)).isoformat()
    async with neo4j_driver.session() as s:  # type: ignore[attr-defined]
        await (
            await s.run(
                """
                CREATE (d:Decision {id:'D-0005', title:'stay on legacy-auth', status:'active', source_event_ids:['ed']})
                CREATE (s:System {canonical_name:'legacy-auth', id:'legacy-auth', status:'active'})
                CREATE (d)-[:ABOUT]->(s)
                CREATE (m:Message {id:'slack:m1', status:'active', content:'re D-0005 we use auth-service now', created_at:datetime($r), source_event_ids:['em']})
                """,
                r=recent,
            )
        ).consume()

    result = await detect_contradictions(neo4j_driver, client=_StubClient(contradicts=True))
    assert result.contradicts_written == 1
    async with neo4j_driver.session() as s:  # type: ignore[attr-defined]
        rec = await (
            await s.run("MATCH (:Message)-[c:CONTRADICTS]->(:Decision {id:'D-0005'}) RETURN c.confidence AS conf")
        ).single()
    assert rec is not None
    assert rec["conf"] == pytest.approx(0.92)


async def test_detector_no_client_is_noop(neo4j_driver: object) -> None:
    recent = (REFERENCE_NOW - timedelta(days=10)).isoformat()
    async with neo4j_driver.session() as s:  # type: ignore[attr-defined]
        await (
            await s.run(
                "CREATE (d:Decision {id:'D-0005', status:'active'}) "
                "CREATE (m:Message {id:'slack:m1', status:'active', content:'re D-0005 nope', created_at:datetime($r), source_event_ids:['em']})",
                r=recent,
            )
        ).consume()
    result = await detect_contradictions(neo4j_driver, client=None)
    assert result.contradicts_written == 0
