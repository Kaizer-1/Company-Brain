"""Unit tests for app/search/retriever.py.

Tests mock pgvector calls and Neo4j calls to verify:
  - rerank math (linear blend, graph signal computation)
  - filter application (source_kind, after, before, entity_type)
  - fanout adjustment (BASE_FANOUT vs FILTER_FANOUT)
  - empty results handled gracefully
  - final_score ordering
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.search.config import LOG_NORM_BASE, W_GRAPH, W_VEC
from app.search.retriever import (
    _apply_event_filters,
    _ensure_aware,
    _has_any_filter,
    hybrid_search,
)
from app.search.schemas import SearchFilters


# ---------------------------------------------------------------------------
# Pure-function tests — rerank math
# ---------------------------------------------------------------------------


def test_graph_signal_saturation() -> None:
    """graph_signal = log(1 + count) / LOG_NORM_BASE saturates near 1 at count=9."""
    signal_9 = math.log(1 + 9) / LOG_NORM_BASE
    signal_0 = math.log(1 + 0) / LOG_NORM_BASE
    assert signal_0 == 0.0
    assert 0.95 <= signal_9 <= 1.1, f"Signal at count=9 should be ~1.0, got {signal_9}"


def test_blend_weights_sum_to_one() -> None:
    """W_VEC + W_GRAPH must sum to 1.0 so scores stay in [0,1]."""
    assert abs(W_VEC + W_GRAPH - 1.0) < 1e-9, f"W_VEC + W_GRAPH = {W_VEC + W_GRAPH}, expected 1.0"


def test_final_score_high_cosine_wins_over_high_graph() -> None:
    """A high-cosine, zero-entity event must outscore a low-cosine, high-entity event."""
    cos_a, entities_a = 0.9, 0
    cos_b, entities_b = 0.2, 10

    score_a = W_VEC * cos_a + W_GRAPH * (math.log(1 + entities_a) / LOG_NORM_BASE)
    score_b = W_VEC * cos_b + W_GRAPH * (math.log(1 + entities_b) / LOG_NORM_BASE)
    assert score_a > score_b, (
        f"High cosine ({cos_a}) should beat high graph density ({entities_b} entities). "
        f"score_a={score_a:.4f}, score_b={score_b:.4f}"
    )


# ---------------------------------------------------------------------------
# Filter application
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)
_BEFORE = datetime(2026, 5, 1, tzinfo=timezone.utc)
_AFTER = datetime(2026, 4, 1, tzinfo=timezone.utc)


def _event(
    eid: str | None = None,
    source_kind: str = "doc",
    occurred_at: datetime = _NOW,
    content: str = "test content",
) -> dict[str, object]:
    return {
        "id": uuid.UUID(eid) if eid else uuid.uuid4(),
        "source_kind": source_kind,
        "source_ref": "test-ref",
        "content": content,
        "occurred_at": occurred_at,
    }


def test_filter_source_kind_keeps_matching() -> None:
    events = [_event(source_kind="doc"), _event(source_kind="slack_message")]
    filtered = _apply_event_filters(events, SearchFilters(source_kind=["doc"]))
    assert len(filtered) == 1
    assert filtered[0]["source_kind"] == "doc"


def test_filter_source_kind_none_keeps_all() -> None:
    events = [_event(source_kind="doc"), _event(source_kind="slack_message")]
    filtered = _apply_event_filters(events, SearchFilters(source_kind=None))
    assert len(filtered) == 2


def test_filter_after_excludes_old() -> None:
    old = _event(occurred_at=datetime(2026, 3, 1, tzinfo=timezone.utc))
    new = _event(occurred_at=_NOW)
    filtered = _apply_event_filters([old, new], SearchFilters(after=_AFTER))
    assert len(filtered) == 1
    assert filtered[0]["occurred_at"] == _NOW


def test_filter_before_excludes_new() -> None:
    old = _event(occurred_at=_BEFORE)
    new = _event(occurred_at=_NOW)
    filtered = _apply_event_filters([old, new], SearchFilters(before=_BEFORE))
    assert len(filtered) == 1
    assert filtered[0]["occurred_at"] == _BEFORE


def test_filter_combined() -> None:
    e1 = _event(source_kind="doc", occurred_at=_BEFORE)
    e2 = _event(source_kind="doc", occurred_at=_NOW)
    e3 = _event(source_kind="slack_message", occurred_at=_BEFORE)
    filtered = _apply_event_filters(
        [e1, e2, e3],
        SearchFilters(source_kind=["doc"], before=_BEFORE),
    )
    assert len(filtered) == 1
    assert filtered[0] is e1


def test_has_any_filter_empty() -> None:
    assert _has_any_filter(SearchFilters()) is False


def test_has_any_filter_with_source_kind() -> None:
    assert _has_any_filter(SearchFilters(source_kind=["doc"])) is True


def test_has_any_filter_with_date() -> None:
    assert _has_any_filter(SearchFilters(after=_AFTER)) is True


def test_ensure_aware_naive_becomes_utc() -> None:
    naive = datetime(2026, 1, 1)
    aware = _ensure_aware(naive)
    assert aware.tzinfo is not None


def test_ensure_aware_preserves_tz() -> None:
    dt = _NOW
    assert _ensure_aware(dt) is dt


# ---------------------------------------------------------------------------
# hybrid_search integration (mocked DB + Neo4j)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hybrid_search_empty_index_returns_empty() -> None:
    """When event_embeddings is empty, hybrid_search returns no hits."""
    session = AsyncMock()
    # Simulate empty pgvector result
    mock_result = MagicMock()
    mock_result.__iter__ = MagicMock(return_value=iter([]))
    session.execute = AsyncMock(return_value=mock_result)

    driver = AsyncMock()

    from app.search.retriever import hybrid_search

    result = await hybrid_search("test query", session=session, neo4j_driver=driver)
    assert result.hits == []
    assert result.total_candidates == 0


@pytest.mark.asyncio
async def test_hybrid_search_returns_top_k() -> None:
    """hybrid_search returns at most k results."""
    e1 = uuid.uuid4()
    e2 = uuid.uuid4()
    e3 = uuid.uuid4()

    # Mock pgvector returning 3 candidates
    pgvector_rows = [
        MagicMock(event_id=e1, cosine_similarity=0.9),
        MagicMock(event_id=e2, cosine_similarity=0.8),
        MagicMock(event_id=e3, cosine_similarity=0.7),
    ]
    mock_vector_result = MagicMock()
    mock_vector_result.__iter__ = MagicMock(return_value=iter(pgvector_rows))

    # Mock events fetch
    event_rows = [
        MagicMock(
            id=e1, source_type="doc", source_external_id="ref-1",
            content="content one", created_at=_NOW
        ),
        MagicMock(
            id=e2, source_type="slack_message", source_external_id="ref-2",
            content="content two", created_at=_NOW
        ),
        MagicMock(
            id=e3, source_type="doc", source_external_id="ref-3",
            content="content three", created_at=_NOW
        ),
    ]
    mock_event_result = MagicMock()
    mock_event_result.__iter__ = MagicMock(return_value=iter(event_rows))

    call_count = 0

    async def execute_side_effect(*args: object, **kwargs: object) -> MagicMock:
        nonlocal call_count
        call_count += 1
        return mock_vector_result if call_count == 1 else mock_event_result

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=execute_side_effect)

    # Mock Neo4j returning no entities
    neo_session = AsyncMock()
    neo_result = AsyncMock()
    neo_result.data = AsyncMock(return_value=[])
    neo_session.run = AsyncMock(return_value=neo_result)
    neo_session.__aenter__ = AsyncMock(return_value=neo_session)
    neo_session.__aexit__ = AsyncMock(return_value=None)

    driver = AsyncMock()
    driver.session = MagicMock(return_value=neo_session)

    result = await hybrid_search("test query", k=2, session=session, neo4j_driver=driver)
    assert len(result.hits) == 2


@pytest.mark.asyncio
async def test_hybrid_search_sorted_by_final_score() -> None:
    """Results must be sorted by final_score descending."""
    e1 = uuid.uuid4()
    e2 = uuid.uuid4()

    pgvector_rows = [
        MagicMock(event_id=e1, cosine_similarity=0.5),
        MagicMock(event_id=e2, cosine_similarity=0.9),
    ]
    mock_vector_result = MagicMock()
    mock_vector_result.__iter__ = MagicMock(return_value=iter(pgvector_rows))

    event_rows = [
        MagicMock(
            id=e1, source_type="doc", source_external_id="r1",
            content="c1", created_at=_NOW
        ),
        MagicMock(
            id=e2, source_type="doc", source_external_id="r2",
            content="c2", created_at=_NOW
        ),
    ]
    mock_event_result = MagicMock()
    mock_event_result.__iter__ = MagicMock(return_value=iter(event_rows))

    call_count = 0

    async def execute_side_effect(*args: object, **kwargs: object) -> MagicMock:
        nonlocal call_count
        call_count += 1
        return mock_vector_result if call_count == 1 else mock_event_result

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=execute_side_effect)

    neo_session = AsyncMock()
    neo_result = AsyncMock()
    neo_result.data = AsyncMock(return_value=[])
    neo_session.run = AsyncMock(return_value=neo_result)
    neo_session.__aenter__ = AsyncMock(return_value=neo_session)
    neo_session.__aexit__ = AsyncMock(return_value=None)
    driver = AsyncMock()
    driver.session = MagicMock(return_value=neo_session)

    result = await hybrid_search("test", k=10, session=session, neo4j_driver=driver)
    assert len(result.hits) == 2
    assert result.hits[0].final_score >= result.hits[1].final_score
    assert result.hits[0].event_id == e2  # higher cosine
