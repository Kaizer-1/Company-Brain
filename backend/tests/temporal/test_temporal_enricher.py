"""Real Neo4j + Postgres test for temporal enrichment (Phase 3B; ADR 0016)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.db.repositories.events import EventRepository
from app.models.enums import SourceType
from app.schemas.postgres import EventCreate
from app.temporal.enricher import enrich_temporal

pytestmark = pytest.mark.asyncio


async def _make_event(session: object, *, ext_id: str, content: str, created_at: datetime) -> str:
    repo = EventRepository(session)  # type: ignore[arg-type]
    dto = await repo.create(
        EventCreate(
            source_type=SourceType.doc,
            source_external_id=ext_id,
            content=content,
            created_at=created_at,
            content_hash=ext_id,
        )
    )
    return str(dto.id)


async def test_valid_from_set_from_source_event(neo4j_driver: object, db_session: object) -> None:
    issued = datetime(2026, 3, 8, 12, 0, tzinfo=UTC)
    event_id = await _make_event(db_session, ext_id="adr/D-0006", content="ADR D-0006", created_at=issued)
    async with neo4j_driver.session() as s:  # type: ignore[attr-defined]
        await (
            await s.run(
                "CREATE (d:Decision {id:'D-0006', status:'active', created_at:datetime(), source_event_ids:[$e]})",
                e=event_id,
            )
        ).consume()

    result = await enrich_temporal(neo4j_driver, db_session)
    assert result.valid_from_from_events == 1

    async with neo4j_driver.session() as s:  # type: ignore[attr-defined]
        rec = await (
            await s.run("MATCH (d:Decision {id:'D-0006'}) RETURN toString(d.valid_from) AS vf, d.status AS st")
        ).single()
    assert rec["vf"].startswith("2026-03-08")
    assert rec["st"] == "active"


async def test_supersession_marks_older_and_writes_edge(neo4j_driver: object, db_session: object) -> None:
    older = datetime(2026, 1, 1, tzinfo=UTC)
    newer = datetime(2026, 5, 1, tzinfo=UTC)
    e_old = await _make_event(db_session, ext_id="adr/D-0004", content="ADR D-0004 session model", created_at=older)
    e_new = await _make_event(
        db_session, ext_id="adr/D-0010", content="ADR D-0010: move to JWT, superseding the D-0004 session model", created_at=newer
    )
    async with neo4j_driver.session() as s:  # type: ignore[attr-defined]
        await (
            await s.run(
                """
                CREATE (a:Decision {id:'D-0004', status:'active', created_at:datetime(), source_event_ids:[$eo]})
                CREATE (b:Decision {id:'D-0010', status:'active', created_at:datetime(), source_event_ids:[$en]})
                """,
                eo=e_old,
                en=e_new,
            )
        ).consume()

    result = await enrich_temporal(neo4j_driver, db_session)
    assert result.supersedes_edges_written == 1

    async with neo4j_driver.session() as s:  # type: ignore[attr-defined]
        rec = await (
            await s.run(
                "MATCH (b:Decision {id:'D-0010'})-[:SUPERSEDES]->(a:Decision {id:'D-0004'}) "
                "RETURN a.status AS st, a.valid_to IS NOT NULL AS has_valid_to"
            )
        ).single()
    assert rec is not None
    assert rec["st"] == "superseded"
    assert rec["has_valid_to"] is True
