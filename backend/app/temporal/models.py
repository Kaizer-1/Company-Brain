"""DTOs for temporal enrichment (Phase 3B)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TemporalEnrichmentResult(BaseModel):
    """Counts from one ``enrich_temporal`` run, for the CLI/eval report and logs."""

    decisions_seen: int = 0
    valid_from_set: int = 0
    valid_from_from_events: int = 0
    valid_from_from_node: int = 0
    supersedes_edges_written: int = 0
    superseded_marked: int = 0
    missing_provenance: list[str] = Field(default_factory=list)
