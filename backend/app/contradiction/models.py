"""DTOs for the contradiction + Message population pass (Phase 3B; ADR 0019)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ContradictionVerdict(BaseModel):
    """The structured output of the contradiction adjudicator.

    ``extra="forbid"`` so a malformed LLM response fails validation and the detector falls back
    to a safe no-edge, rather than silently writing a wrong CONTRADICTS edge.
    """

    model_config = ConfigDict(extra="forbid")

    contradicts: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


class ContradictionResult(BaseModel):
    """Counts from one contradiction pass, for the CLI/eval report and logs."""

    messages_ingested: int = 0
    candidate_pairs: int = 0
    contradicts_written: int = 0
    llm_cost_usd: float = 0.0


class WrittenContradiction(BaseModel):
    """One CONTRADICTS edge written by a (scoped) detection pass.

    Returned by the Phase-5A scoped detectors so the ingestion layer can surface exactly which
    Message→Decision contradictions a live event produced, without reaching into Neo4j again.
    """

    model_config = ConfigDict(frozen=True)

    message_id: str
    decision_id: str
    confidence: float = Field(ge=0.0, le=1.0)
