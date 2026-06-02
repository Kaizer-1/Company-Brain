"""Pydantic models for the LLM's *output* — not the graph schema.

These models define the exact JSON shape the extraction LLM must return. They are
intentionally **flatter and simpler** than ``app.schemas.graph``: the model emits
entities keyed by a single human-readable ``canonical_name`` and relationships keyed
by the *names* of their endpoints, because that is what an LLM can reliably produce
from a single event's text. The graph writer (``graph_writer.py``) is responsible for
translating these into the richer, key-disciplined graph nodes/edges.

Two design choices are load-bearing and worth defending in an interview:

1. **``evidence_quote`` is required on every extraction.** Forcing the model to quote
   the exact span of the event that justifies each entity/relationship (a) measurably
   improves precision — the model cannot assert what it cannot quote — and (b) gives
   the eval harness a debugging anchor: when an extraction is wrong, the quote shows
   *why* the model thought it was right. This is the single highest-leverage field in
   the schema.
2. **Strict validation (``extra="forbid"``).** An unexpected key is a malformed
   extraction, surfaced loudly rather than silently dropped — consistent with the
   project's fail-loud lesson from Phase 1B.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.graph import RelationshipType

# The closed set of entity labels the extractor may emit. A subset of the six graph
# node labels: ``Message`` is created mechanically from the event itself (one event =
# one message/doc), never *extracted*, so it is not an option the LLM can return.
EntityType = Literal["Person", "Service", "System", "Team", "Decision"]

# Shared config: reject unknown fields (a malformed extraction is a bug, not noise)
# but stay mutable — unlike graph nodes, these are transient parse targets that the
# pipeline may post-process before writing.
_OUTPUT = ConfigDict(extra="forbid")


class ExtractedEntity(BaseModel):
    """One entity the model claims is present in the event.

    ``canonical_name`` is the model's best single name for the entity (e.g.
    ``"auth-service"``, ``"Alice Chen"``, ``"D-0006"``); alias resolution onto a single
    graph node is Phase 3B, so two surface forms of one entity legitimately produce two
    ``ExtractedEntity`` objects here. ``properties`` carries any extra typed attributes
    the model surfaces (e.g. ``{"status": "deprecated"}``); it is free-form by design
    because the per-label property sets differ and the prompt asks only for what is
    explicit in the text.
    """

    model_config = _OUTPUT

    type: EntityType
    canonical_name: str = Field(min_length=1)
    properties: dict[str, object] = Field(default_factory=dict)
    evidence_quote: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


class ExtractedRelationship(BaseModel):
    """One directed, typed edge the model claims the event asserts.

    Endpoints are named by ``canonical_name`` (not graph IDs) because the model reasons
    over text, not the graph. The eval matcher and the graph writer both resolve these
    names; the model's only job is to name the two endpoints and the edge type from the
    closed ``RelationshipType`` vocabulary.
    """

    model_config = _OUTPUT

    type: RelationshipType
    source_canonical_name: str = Field(min_length=1)
    target_canonical_name: str = Field(min_length=1)
    evidence_quote: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("type", mode="before")
    @classmethod
    def _coerce_relationship_type(cls, value: object) -> object:
        """Accept the edge type as its string value (what the LLM emits) under strict mode.

        Strict validation otherwise demands a ``RelationshipType`` *instance*; the model
        returns the string ``"DEPENDS_ON"``. We coerce here (raising for an unknown member)
        so the rest of the model keeps strict scalar discipline (e.g. a stringified
        ``confidence`` still fails).
        """
        if isinstance(value, str):
            return RelationshipType(value)
        return value


class ExtractionResult(BaseModel):
    """The complete structured output for a single event.

    Empty lists are valid and meaningful: an event that asserts no extractable
    entities (e.g. an ambient "lgtm, shipping" message) must return
    ``{"entities": [], "relationships": []}``. Returning nothing-disguised-as-something
    is the failure mode the negative few-shot example is designed to prevent.
    """

    model_config = _OUTPUT

    entities: list[ExtractedEntity] = Field(default_factory=list)
    relationships: list[ExtractedRelationship] = Field(default_factory=list)
