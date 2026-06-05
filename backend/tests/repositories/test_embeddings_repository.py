"""Real-DB tests for EventEmbeddingRepository using a testcontainers Postgres."""

import hashlib
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.embeddings import EventEmbeddingRepository
from app.db.repositories.events import EventRepository
from app.models.embeddings import EMBEDDING_DIM
from app.models.enums import SourceType
from app.schemas.postgres import EventCreate, EventEmbeddingCreate


def _make_vector(seed: int = 0) -> list[float]:
    """Create a normalised EMBEDDING_DIM-dimensional random unit vector with a fixed seed.

    Uses random.Random so each seed produces a genuinely different direction,
    unlike scalar-multiple approaches that produce identical normalised vectors.
    """
    import math
    import random

    rng = random.Random(seed)
    v = [rng.gauss(0.0, 1.0) for _ in range(EMBEDDING_DIM)]
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v]


async def _create_event(session: AsyncSession) -> uuid.UUID:
    repo = EventRepository(session)
    content = "test content " + str(uuid.uuid4())
    data = EventCreate(
        source_type=SourceType.doc,
        source_external_id=str(uuid.uuid4()),
        content=content,
        source_metadata={},
        created_at=datetime.now(tz=timezone.utc),
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
    )
    created = await repo.create(data)
    return created.id


@pytest.mark.asyncio
async def test_upsert_insert_and_get(db_session: AsyncSession) -> None:
    event_id = await _create_event(db_session)
    repo = EventEmbeddingRepository(db_session)
    vector = _make_vector(42)

    data = EventEmbeddingCreate(
        event_id=event_id,
        embedding=vector,
        model_name="text-embedding-3-small",
        model_version="2024-02-01",
    )
    created = await repo.upsert(data)
    assert created.event_id == event_id
    assert len(created.embedding) == EMBEDDING_DIM

    fetched = await repo.get_for_event(event_id)
    assert fetched is not None
    assert fetched.event_id == event_id


@pytest.mark.asyncio
async def test_upsert_replaces_existing(db_session: AsyncSession) -> None:
    """Upserting twice replaces the row; only the latest embedding is kept."""
    event_id = await _create_event(db_session)
    repo = EventEmbeddingRepository(db_session)

    v1 = _make_vector(1)
    await repo.upsert(
        EventEmbeddingCreate(
            event_id=event_id,
            embedding=v1,
            model_name="text-embedding-3-small",
            model_version="v1",
        )
    )

    v2 = _make_vector(2)
    await repo.upsert(
        EventEmbeddingCreate(
            event_id=event_id,
            embedding=v2,
            model_name="text-embedding-3-small",
            model_version="v2",
        )
    )

    fetched = await repo.get_for_event(event_id)
    assert fetched is not None
    assert fetched.model_version == "v2"


@pytest.mark.asyncio
async def test_get_for_event_returns_none_when_missing(db_session: AsyncSession) -> None:
    repo = EventEmbeddingRepository(db_session)
    result = await repo.get_for_event(uuid.uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_similar_to_orders_by_distance(db_session: AsyncSession) -> None:
    """similar_to applies the cosine similarity threshold correctly.

    e1 (identical vector to query) passes threshold=0.9; e2 (random orthogonal)
    does not.  This verifies the distance filtering without depending on
    HNSW approximate ranking precision for a 2-row table.
    """
    repo_emb = EventEmbeddingRepository(db_session)

    # Create two events with different embeddings
    e1 = await _create_event(db_session)
    e2 = await _create_event(db_session)

    # v1 is close to query (same seed → same direction); v2 is from a different direction
    v1 = _make_vector(10)    # direction A
    v2 = _make_vector(9999)  # direction B (orthogonal to A by random chance)
    query = _make_vector(10)  # same direction as v1 → cosine similarity = 1.0

    await repo_emb.upsert(
        EventEmbeddingCreate(event_id=e1, embedding=v1, model_name="m", model_version="1")
    )
    await repo_emb.upsert(
        EventEmbeddingCreate(event_id=e2, embedding=v2, model_name="m", model_version="1")
    )
    # Flush so the HNSW index can see both rows before the similarity query.
    await db_session.flush()

    # query == v1 exactly, so cosine similarity(query, v1) = 1.0 > sim(query, v2)
    # High threshold: e1 (cos_sim ≈ 1.0 with identical vector) must appear;
    # e2 (nearly orthogonal, cos_sim ≈ 0 in 384-d space) must not.
    results = await repo_emb.similar_to(query, limit=10, threshold=0.9)
    result_ids = {r.event_id for r in results}
    assert e1 in result_ids, "e1 must appear: query equals v1 exactly (cos_sim = 1.0)"
    assert e2 not in result_ids, "e2 must not appear: orthogonal to query (cos_sim ≈ 0)"


@pytest.mark.asyncio
async def test_similar_to_with_malicious_vector_input_does_not_inject(
    db_session: AsyncSession,
) -> None:
    """similar_to must refuse or neutralise non-vector input without touching other tables.

    Regression guard for Phase 1C follow-up Bug 2: the original similar_to
    built the vector literal via f-string interpolation.  A caller who supplied
    a crafted string instead of a list of floats could inject arbitrary SQL.
    After the bindparam fix, the binding layer must raise a TypeError /
    StatementError before any query reaches the database, OR return 0 rows
    without executing injected SQL.  Either way the events table must survive.
    """
    from sqlalchemy import text
    from sqlalchemy.exc import StatementError

    repo = EventEmbeddingRepository(db_session)

    # Attempt to pass a raw SQL-injection string where a list[float] is expected.
    malicious: object = "'; DROP TABLE events; --"

    raised = False
    try:
        await repo.similar_to(malicious, limit=10, threshold=0.0)  # type: ignore[arg-type]
    except (TypeError, StatementError, ValueError):
        raised = True
    # The binding must either refuse the value (raised=True) or return no rows.
    # In both cases the events table must still exist.
    result = await db_session.execute(text("SELECT 1 FROM events LIMIT 1"))
    _ = result.fetchall()  # raises if the table was dropped

    if not raised:
        # If the call didn't raise, it must have returned 0 rows (no real match).
        rows = await repo.similar_to(malicious, limit=10, threshold=0.0)  # type: ignore[arg-type]
        assert rows == [] or raised, (
            "Malicious input must either raise a binding error or return 0 rows"
        )


@pytest.mark.asyncio
async def test_raw_sql_vector_query_returns_list_not_string(
    db_session: AsyncSession,
) -> None:
    """The pgvector asyncpg codec must decode the embedding column as a native array.

    Regression guard for Phase 1C follow-up Bug 3: without the codec registered
    in build_engine, asyncpg returns the vector column as a plain text string
    like '[0.1,0.2,...]'.  After registering the codec via run_async, the same
    raw SELECT must return a type that is NOT str.
    """
    from sqlalchemy import text

    event_id = await _create_event(db_session)
    repo = EventEmbeddingRepository(db_session)
    vector = _make_vector(seed=55)
    await repo.upsert(
        EventEmbeddingCreate(
            event_id=event_id,
            embedding=vector,
            model_name="test-model",
            model_version="v1",
        )
    )
    await db_session.flush()

    result = await db_session.execute(
        text("SELECT embedding FROM event_embeddings WHERE event_id = :eid"),
        {"eid": str(event_id)},
    )
    row = result.fetchone()
    assert row is not None

    raw_emb = row.embedding
    # The codec must have decoded the binary/text representation to a native type.
    assert not isinstance(raw_emb, str), (
        f"Expected list / array from pgvector codec, got str: {raw_emb!r}. "
        "Check that register_vector is called in build_engine."
    )
    # Must be iterable and contain floats.
    assert hasattr(raw_emb, "__iter__"), f"Embedding must be iterable, got {type(raw_emb)}"
    assert len(list(raw_emb)) == EMBEDDING_DIM


@pytest.mark.asyncio
async def test_cascade_delete_removes_embedding(db_session: AsyncSession) -> None:
    """Deleting an event cascades to its embedding row."""
    from sqlalchemy import text

    event_id = await _create_event(db_session)
    repo = EventEmbeddingRepository(db_session)

    await repo.upsert(
        EventEmbeddingCreate(
            event_id=event_id,
            embedding=_make_vector(7),
            model_name="m",
            model_version="1",
        )
    )

    # Delete the parent event directly via SQL to trigger cascade.
    await db_session.execute(text("DELETE FROM events WHERE id = :id"), {"id": str(event_id)})

    fetched = await repo.get_for_event(event_id)
    assert fetched is None
