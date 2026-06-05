"""Hybrid retrieval engine (Phase 3D).

``hybrid_search`` implements the two-stage pipeline documented in ADR 0022:
  1. Encode the query with bge-small-en-v1.5 (via embedder.py — same model instance).
  2. pgvector cosine search: top N = BASE_FANOUT*k candidates (FILTER_FANOUT*k if filtered).
  3. Fetch the event rows and apply source_kind / after / before filters.
  4. Fetch canonical entity ids from Neo4j; apply entity_type filter.
  5. Linear-blend rerank: final_score = W_VEC*cosine + W_GRAPH*graph_signal.
  6. Return top k SearchHit objects with per-stage timing.

Stage timings are logged and included in the response for Phase 4A latency analysis.
"""

from __future__ import annotations

import math
import time
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from pgvector.sqlalchemy import Vector
from sqlalchemy import Integer, bindparam

from app.models.embeddings import EMBEDDING_DIM
from app.search.config import (
    BASE_FANOUT,
    FILTER_FANOUT,
    LOG_NORM_BASE,
    SNIPPET_CHARS,
    W_GRAPH,
    W_VEC,
)
from app.search.embedder import embed_query
from app.search.schemas import SearchFilters, SearchHit, SearchResult

if TYPE_CHECKING:
    from neo4j import AsyncDriver

log = structlog.get_logger(__name__)


async def hybrid_search(
    query: str,
    *,
    k: int = 10,
    filters: SearchFilters | None = None,
    session: AsyncSession,
    neo4j_driver: AsyncDriver,
) -> SearchResult:
    """Run hybrid retrieval and return a ranked SearchResult.

    Args:
        query:        Natural-language query string.
        k:            Number of results to return (1–50).
        filters:      Optional filter dimensions (source_kind, after, before, entity_type).
        session:      Async Postgres session (for embeddings + event rows).
        neo4j_driver: Neo4j driver (for entity counts + entity_type filter).
    """
    t_start = time.monotonic()

    # ------------------------------------------------------------------
    # Stage 1 — encode query
    # ------------------------------------------------------------------
    t0 = time.monotonic()
    query_vector = await embed_query(query)
    query_embedding_ms = (time.monotonic() - t0) * 1000

    # ------------------------------------------------------------------
    # Stage 2 — vector search: top N candidates
    # ------------------------------------------------------------------
    any_filter = filters is not None and _has_any_filter(filters)
    fanout = FILTER_FANOUT if any_filter else BASE_FANOUT
    candidate_limit = fanout * k

    t0 = time.monotonic()
    candidates = await _vector_search(session, query_vector.tolist(), limit=candidate_limit)
    vector_search_ms = (time.monotonic() - t0) * 1000

    if not candidates:
        return _empty_result(query, query_embedding_ms, vector_search_ms)

    # ------------------------------------------------------------------
    # Stage 3 — fetch event metadata + apply cheap filters
    # ------------------------------------------------------------------
    t0 = time.monotonic()
    event_ids = [c[0] for c in candidates]
    cosine_map: dict[uuid.UUID, float] = {c[0]: c[1] for c in candidates}
    events = await _fetch_events(session, event_ids)

    if filters is not None:
        events = _apply_event_filters(events, filters)

    if not events:
        return _empty_result(query, query_embedding_ms, vector_search_ms)

    # ------------------------------------------------------------------
    # Stage 4 — Neo4j entity lookup + entity_type filter + graph signal
    # ------------------------------------------------------------------
    filtered_ids = [e["id"] for e in events]
    entity_map = await _fetch_entity_map(neo4j_driver, filtered_ids)

    if filters is not None and filters.entity_type:
        allowed_types = {t.lower() for t in filters.entity_type}
        events = [
            e for e in events
            if any(
                lbl.lower() in allowed_types
                for lbl in entity_map.get(e["id"], {}).get("labels", [])
            )
        ]

    if not events:
        return _empty_result(query, query_embedding_ms, vector_search_ms)

    # ------------------------------------------------------------------
    # Stage 5 — linear-blend rerank, return top k
    # ------------------------------------------------------------------
    hits: list[SearchHit] = []
    for event in events:
        eid = event["id"]
        cosine = cosine_map.get(eid, 0.0)
        entity_info = entity_map.get(eid, {})
        entity_count = entity_info.get("count", 0)
        entity_ids = entity_info.get("ids", [])

        graph_signal = math.log(1 + entity_count) / LOG_NORM_BASE
        final_score = W_VEC * cosine + W_GRAPH * graph_signal
        final_score = min(1.0, max(0.0, final_score))

        hits.append(
            SearchHit(
                event_id=eid,
                snippet=event["content"][:SNIPPET_CHARS],
                source_kind=event["source_kind"],
                source_ref=event["source_ref"],
                occurred_at=event["occurred_at"],
                similarity_score=round(cosine, 6),
                final_score=round(final_score, 6),
                related_entity_ids=entity_ids,
            )
        )

    hits.sort(key=lambda h: h.final_score, reverse=True)
    hits = hits[:k]
    rerank_ms = (time.monotonic() - t0) * 1000
    total_ms = (time.monotonic() - t_start) * 1000

    log.info(
        "hybrid_search_done",
        query_len=len(query),
        candidates=len(candidates),
        returned=len(hits),
        query_embedding_ms=round(query_embedding_ms, 1),
        vector_search_ms=round(vector_search_ms, 1),
        rerank_ms=round(rerank_ms, 1),
        total_ms=round(total_ms, 1),
    )

    return SearchResult(
        query=query,
        hits=hits,
        total_candidates=len(candidates),
        query_embedding_ms=round(query_embedding_ms, 1),
        vector_search_ms=round(vector_search_ms, 1),
        rerank_ms=round(rerank_ms, 1),
        total_ms=round(total_ms, 1),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _has_any_filter(filters: SearchFilters) -> bool:
    return bool(
        filters.source_kind
        or filters.after is not None
        or filters.before is not None
        or filters.entity_type
    )


_VECTOR_SEARCH_STMT = text(
    """
    SELECT event_id,
           1.0 - (embedding <=> :query_vector) AS cosine_similarity
    FROM event_embeddings
    ORDER BY embedding <=> :query_vector
    LIMIT :limit
    """
).bindparams(
    bindparam("query_vector", type_=Vector(EMBEDDING_DIM)),
    bindparam("limit", type_=Integer()),
)


async def _vector_search(
    session: AsyncSession,
    vector: list[float],
    limit: int,
) -> list[tuple[uuid.UUID, float]]:
    """Return (event_id, cosine_similarity) pairs ordered by similarity desc."""
    result = await session.execute(
        _VECTOR_SEARCH_STMT,
        {"query_vector": vector, "limit": limit},
    )
    return [(row.event_id, float(row.cosine_similarity)) for row in result]


async def _fetch_events(
    session: AsyncSession,
    event_ids: list[uuid.UUID],
) -> list[dict[str, object]]:
    """Fetch event metadata for a list of event_ids."""
    if not event_ids:
        return []
    result = await session.execute(
        text(
            """
            SELECT id, source_type, source_external_id, content, created_at
            FROM events
            WHERE id = ANY(:ids)
            """
        ),
        {"ids": [str(e) for e in event_ids]},
    )
    # Preserve the order of the input (similarity descending).
    order = {eid: idx for idx, eid in enumerate(event_ids)}
    rows = [
        {
            "id": row.id,
            "source_kind": str(row.source_type),
            "source_ref": row.source_external_id,
            "content": row.content,
            "occurred_at": row.created_at,
        }
        for row in result
    ]
    rows.sort(key=lambda r: order.get(r["id"], 9999))
    return rows


def _apply_event_filters(
    events: list[dict[str, object]],
    filters: SearchFilters,
) -> list[dict[str, object]]:
    """Apply source_kind, after, before filters to the candidate event list."""
    out = events
    if filters.source_kind:
        allowed = {k.lower() for k in filters.source_kind}
        out = [e for e in out if str(e["source_kind"]).lower() in allowed]
    if filters.after is not None:
        after_aware = _ensure_aware(filters.after)
        out = [e for e in out if _ensure_aware(e["occurred_at"]) >= after_aware]  # type: ignore[arg-type]
    if filters.before is not None:
        before_aware = _ensure_aware(filters.before)
        out = [e for e in out if _ensure_aware(e["occurred_at"]) <= before_aware]  # type: ignore[arg-type]
    return out


def _ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def _fetch_entity_map(
    driver: AsyncDriver,
    event_ids: list[uuid.UUID],
) -> dict[uuid.UUID, dict[str, object]]:
    """Return a map of event_id → {count, ids, labels} for canonical entities.

    Uses a single batched Cypher query: UNWIND event_ids, match nodes whose
    source_event_ids array contains the event id, collect entity info.
    """
    if not event_ids:
        return {}

    str_ids = [str(eid) for eid in event_ids]

    cypher = """
    UNWIND $event_ids AS eid
    MATCH (n)
    WHERE eid IN n.source_event_ids
      AND coalesce(n.status, 'active') <> 'merged'
    RETURN eid AS event_id,
           coalesce(n.canonical_id, n.canonical_name, n.id) AS entity_id,
           labels(n)[0] AS label
    """

    entity_map: dict[uuid.UUID, dict[str, object]] = {
        eid: {"count": 0, "ids": [], "labels": []} for eid in event_ids
    }

    async with driver.session() as neo_session:
        result = await neo_session.run(cypher, event_ids=str_ids)
        records = await result.data()

    id_str_map = {str(eid): eid for eid in event_ids}
    for row in records:
        eid = id_str_map.get(row["event_id"])
        if eid is None:
            continue
        info = entity_map[eid]
        entity_id = row.get("entity_id")
        label = row.get("label", "")
        if entity_id and entity_id not in info["ids"]:  # type: ignore[operator]
            info["ids"].append(entity_id)  # type: ignore[union-attr]
            info["labels"].append(label)  # type: ignore[union-attr]
        info["count"] = len(info["ids"])  # type: ignore[assignment]

    return entity_map


def _empty_result(
    query: str,
    query_embedding_ms: float,
    vector_search_ms: float,
) -> SearchResult:
    return SearchResult(
        query=query,
        hits=[],
        total_candidates=0,
        query_embedding_ms=round(query_embedding_ms, 1),
        vector_search_ms=round(vector_search_ms, 1),
        rerank_ms=0.0,
        total_ms=round(query_embedding_ms + vector_search_ms, 1),
    )
