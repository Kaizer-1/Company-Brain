"""Semantic search module (Phase 3D).

Public surface:
    embed_events    — pipeline step; embeds un-embedded events into event_embeddings
    hybrid_search   — query-time retrieval; linear blend of vector + graph signal

Internal structure mirrors app/resolution/:
    config.py       — tunable constants (weights, fanout, batch sizes)
    embedder.py     — thin wrapper around resolution/embeddings.py (no new model)
    indexer.py      — embed_events() pipeline step
    retriever.py    — hybrid_search() + reranker
    schemas.py      — Pydantic request/response types
    router.py       — FastAPI router for POST /api/search
"""

from app.search.indexer import embed_events
from app.search.retriever import hybrid_search

__all__ = ["embed_events", "hybrid_search"]
