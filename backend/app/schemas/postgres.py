"""Pydantic DTOs for the Postgres event store.

These are the types that cross the repository boundary.  Callers receive these;
callers pass these in.  SQLAlchemy ORM instances never escape the repository
layer.  This prevents accidental lazy-loading in async contexts and gives the
service layer a stable, typed interface independent of the ORM mapping.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ExtractionStatus, MergeDecisionType, NodeType, SourceType


class EventCreate(BaseModel):
    """Fields required to create a new event row."""

    model_config = ConfigDict(frozen=True)

    source_type: SourceType
    source_external_id: str
    content: str
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    content_hash: str


class EventDTO(BaseModel):
    """Full representation of a persisted event row."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    source_type: SourceType
    source_external_id: str
    content: str
    source_metadata: dict[str, Any]
    created_at: datetime
    ingested_at: datetime
    content_hash: str


class EventEmbeddingCreate(BaseModel):
    """Fields required to upsert an embedding."""

    model_config = ConfigDict(frozen=True)

    event_id: uuid.UUID
    embedding: list[float]
    model_name: str
    model_version: str


class EventEmbeddingDTO(BaseModel):
    """Full representation of a persisted embedding row."""

    model_config = ConfigDict(frozen=True)

    event_id: uuid.UUID
    embedding: list[float]
    model_name: str
    model_version: str
    created_at: datetime


class ExtractionRunCreate(BaseModel):
    """Fields required to create a new extraction run row."""

    model_config = ConfigDict(frozen=True)

    event_id: uuid.UUID
    model_name: str
    model_version: str
    prompt_hash: str
    started_at: datetime


class ExtractionRunDTO(BaseModel):
    """Full representation of a persisted extraction run row."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    event_id: uuid.UUID
    model_name: str
    model_version: str
    prompt_hash: str
    started_at: datetime
    completed_at: datetime | None
    status: ExtractionStatus
    extracted_node_count: int
    extracted_edge_count: int
    error_message: str | None


class MergeDecisionCreate(BaseModel):
    """Fields required to record one resolution attempt (Phase 3A; see ADR 0015)."""

    model_config = ConfigDict(frozen=True)

    source_node_id: str
    target_node_id: str
    node_type: NodeType
    decision: MergeDecisionType
    tier: int
    embedding_similarity: float | None = None
    rules_matched: list[str] = Field(default_factory=list)
    llm_reasoning: str | None = None
    llm_model: str | None = None


class MergeDecisionDTO(BaseModel):
    """Full representation of a persisted merge-decision row."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    source_node_id: str
    target_node_id: str
    node_type: NodeType
    decision: MergeDecisionType
    tier: int
    embedding_similarity: float | None
    rules_matched: list[str]
    llm_reasoning: str | None
    llm_model: str | None
    created_at: datetime
