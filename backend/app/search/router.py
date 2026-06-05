"""FastAPI router for POST /api/search (Phase 3D).

Delegates all retrieval logic to ``hybrid_search`` in retriever.py.  The router's
only job is to extract DB handles from app.state and return the response.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Request

from app.search.retriever import hybrid_search
from app.search.schemas import SearchRequest, SearchResult

router = APIRouter(prefix="/api/search", tags=["search"])
log = structlog.get_logger(__name__)


@router.post(
    "",
    response_model=SearchResult,
    summary="Hybrid semantic + graph search over events.",
)
async def search(request: Request, body: SearchRequest) -> SearchResult:
    """Execute a hybrid vector + graph-signal search.

    Encodes ``body.query`` with BAAI/bge-small-en-v1.5, retrieves candidate
    events by cosine similarity, reranks with a linear blend of vector similarity
    and graph density, and returns the top ``body.k`` results with per-stage
    timing.

    Filters (source_kind, after, before, entity_type) are applied between
    vector search and reranking; when any filter is active the candidate pool
    is widened to ``FILTER_FANOUT * k`` to reduce post-filter top-k shortfall.
    """
    log.info("search_request", query_len=len(body.query), k=body.k, has_filters=body.filters is not None)
    async with request.app.state.session_factory() as session:
        result = await hybrid_search(
            body.query,
            k=body.k,
            filters=body.filters,
            session=session,
            neo4j_driver=request.app.state.neo4j.driver,
        )
    return result
