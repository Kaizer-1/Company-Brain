"""Pydantic schemas for live ingestion (Phase 5A).

Two groups of types:

- The **API surface** (``IngestEventRequest`` / ``IngestEventResponse`` and the ref types) —
  the request the frontend posts and the *visible demo artifact* it renders after a reconcile.
- The **persistence DTOs** (``IngestionRunUpsert`` / ``IngestionRunDTO``) — what crosses the
  ``IngestionRunRepository`` boundary, co-located here the way the Phase-4C query result types
  live with their tools.

``source_kind`` is restricted to ``doc`` / ``slack_message`` — the only two values in the
Postgres ``sourcetype`` enum (verified in the 5A pre-implementation check; ``adr`` / ``meeting``
from the original draft do not exist in the DB and are deferred, see ADR 0031).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SourceKind = Literal["doc", "slack_message"]
IngestionStatus = Literal["reconciled", "partial", "failed"]
StageStatus = Literal["ok", "skipped", "failed"]


# ---------------------------------------------------------------------------
# API request
# ---------------------------------------------------------------------------
class IngestEventRequest(BaseModel):
    """A new event to ingest live, in the shape the ``events`` table uses.

    ``external_id`` is optional but recommended: when present it becomes the event's
    ``source_external_id`` and the idempotency key (``uq_events_source``). When absent the
    endpoint derives a stable id from the content hash, so a double-submit of identical content
    still dedupes (ADR 0032).
    """

    model_config = ConfigDict(frozen=True)

    source_kind: SourceKind
    source_ref: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=10, max_length=10_000)
    occurred_at: datetime
    external_id: str | None = Field(default=None, max_length=200)


# ---------------------------------------------------------------------------
# API response (the visible reconciliation artifact)
# ---------------------------------------------------------------------------
class StageResult(BaseModel):
    """The outcome of one reconciliation stage, rendered as a timeline row on the frontend."""

    name: str
    status: StageStatus
    duration_ms: float
    detail: str | None = None


class NodeRef(BaseModel):
    """A node the ingestion asserted (created or touched), for the "what changed" panel."""

    id: str
    label: str
    display_name: str


class MergeRef(BaseModel):
    """A resolution merge the ingestion caused: ``loser`` absorbed into ``winner``."""

    loser_id: str
    winner_id: str
    label: str
    tier: int
    confidence: float


class EdgeRef(BaseModel):
    """A relationship the ingestion asserted between two canonical-key endpoints."""

    type: str
    source_id: str
    target_id: str


class ContradictionRef(BaseModel):
    """A CONTRADICTS edge the ingestion detected between a Message and a Decision."""

    message_id: str
    decision_id: str
    confidence: float


class IngestEventResponse(BaseModel):
    """The reconciliation result — what the frontend shows after a live ingest."""

    event_id: uuid.UUID
    status: IngestionStatus
    stages_run: list[StageResult] = Field(default_factory=list)
    nodes_created: list[NodeRef] = Field(default_factory=list)
    nodes_merged: list[MergeRef] = Field(default_factory=list)
    edges_created: list[EdgeRef] = Field(default_factory=list)
    contradictions_detected: list[ContradictionRef] = Field(default_factory=list)
    duration_ms: float = 0.0
    cost_usd: float = 0.0
    deduplicated: bool = False


# ---------------------------------------------------------------------------
# Persistence DTOs (IngestionRunRepository boundary)
# ---------------------------------------------------------------------------
class IngestionRunUpsert(BaseModel):
    """Everything needed to write (or overwrite) one ``ingestion_runs`` row."""

    model_config = ConfigDict(frozen=True)

    event_id: uuid.UUID
    status: IngestionStatus
    started_at: datetime
    completed_at: datetime | None
    stages_json: list[dict[str, object]]
    nodes_created_count: int
    nodes_merged_count: int
    edges_created_count: int
    contradictions_count: int
    cost_usd: float
    error: str | None = None


class IngestionRunDTO(BaseModel):
    """Full representation of a persisted ``ingestion_runs`` row."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    event_id: uuid.UUID
    status: str
    started_at: datetime
    completed_at: datetime | None
    stages_json: list[dict[str, object]]
    nodes_created_count: int
    nodes_merged_count: int
    edges_created_count: int
    contradictions_count: int
    cost_usd: float
    error: str | None


# ---------------------------------------------------------------------------
# Audit-tab read models (Phase 5B)
# ---------------------------------------------------------------------------
class IngestionRunSummary(BaseModel):
    """One ingestion run joined to its source event, for the ``/audit`` ingestion-runs tab.

    Mirrors the resolution tab's row shape (Decision 1, Phase 5B): everything the
    ``ingestion_runs`` table records, plus the event's ``source_kind`` and a short content
    snippet (joined from ``events``) so a reader has context without opening the modal.
    ``duration_ms`` is computed from ``completed_at - started_at`` at read time, not stored.
    """

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    event_id: uuid.UUID
    source_kind: str
    content_snippet: str
    status: str
    stages: list[StageResult]
    nodes_created_count: int
    nodes_merged_count: int
    edges_created_count: int
    contradictions_count: int
    cost_usd: float
    duration_ms: float | None
    started_at: datetime
    completed_at: datetime | None
    error: str | None


class IngestionRunPage(BaseModel):
    """A cursor-paginated slice of ingestion runs, newest first.

    ``next_cursor`` is the ``started_at`` of the row that would begin the *next* page (the
    frontend passes it back as ``before``); ``None`` means there are no more rows. Cursor
    pagination — not offset — because the audit feed grows from the head as new events ingest.
    """

    items: list[IngestionRunSummary]
    next_cursor: datetime | None = None
