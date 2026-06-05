"""Pydantic schemas for the search API (Phase 3D).

SearchRequest  — POST /api/search request body
SearchFilters  — optional filter dimensions
SearchHit      — one result in the ranked list
SearchResult   — full response including per-stage timing
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SearchFilters(BaseModel):
    """Optional filters applied between vector search and reranking."""

    model_config = ConfigDict(frozen=True)

    source_kind: list[str] | None = Field(
        default=None,
        description="Limit to these source types, e.g. ['slack_message', 'doc'].",
    )
    after: datetime | None = Field(
        default=None,
        description="Only events created after this timestamp (inclusive).",
    )
    before: datetime | None = Field(
        default=None,
        description="Only events created before this timestamp (inclusive).",
    )
    entity_type: list[str] | None = Field(
        default=None,
        description="Limit to events whose graph entities include this node label.",
    )


class SearchRequest(BaseModel):
    """POST /api/search request body."""

    model_config = ConfigDict(frozen=True)

    query: str = Field(..., min_length=1, max_length=500, description="Natural-language query.")
    k: int = Field(default=10, ge=1, le=50, description="Number of results to return.")
    filters: SearchFilters | None = Field(default=None)


class SearchHit(BaseModel):
    """A single ranked result.

    All fields are explicit (no computed Pydantic properties) — serialisation is
    straightforward, per HANDOFF Deviation #3 note on Pydantic and computed props.
    """

    model_config = ConfigDict(frozen=True)

    event_id: uuid.UUID
    snippet: str = Field(description="First SNIPPET_CHARS characters of the event content.")
    source_kind: str = Field(description="SourceType value: 'doc' or 'slack_message'.")
    source_ref: str = Field(description="source_external_id from the events row.")
    occurred_at: datetime
    similarity_score: float = Field(ge=0.0, le=1.0)
    final_score: float = Field(ge=0.0, le=1.0)
    related_entity_ids: list[str] = Field(
        default_factory=list,
        description="canonical_ids of graph entities this event asserted.",
    )


class SearchResult(BaseModel):
    """Full response from POST /api/search."""

    model_config = ConfigDict(frozen=True)

    query: str
    hits: list[SearchHit]
    total_candidates: int = Field(description="Candidate pool size before reranking.")
    query_embedding_ms: float
    vector_search_ms: float
    rerank_ms: float
    total_ms: float
