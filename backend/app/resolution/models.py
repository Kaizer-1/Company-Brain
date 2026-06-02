"""Pydantic DTOs and shared constants for entity resolution (Phase 3A).

These types are the contract between the resolver's stages: candidate generation produces
``CandidatePair``s, the adjudicator produces ``LLMVerdict``s, and the orchestrator emits a
``ResolutionReport``. They are intentionally small and immutable — a resolution decision is a
fact, like a graph node. See docs/design/entity-resolution.md.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import NodeType

# The property each node label is keyed on (mirrors the uniqueness constraints in
# migrations/graph/001_constraints.cypher and graph_writer._KEY_FIELD). The resolver uses
# this to read a node's identity and to MATCH it when writing the MERGE_INTO edge.
KEY_FIELD: dict[NodeType, str] = {
    NodeType.Person: "canonical_id",
    NodeType.Service: "canonical_name",
    NodeType.System: "canonical_name",
    NodeType.Team: "canonical_name",
    NodeType.Decision: "id",
}


class ResolvableNode(BaseModel):
    """One graph node loaded for resolution, with the fields the tiers need.

    ``node_id`` is the value of the node's canonical-key property (``KEY_FIELD[node_type]``)
    — the stable handle used both as the ``merge_decisions`` source/target id and to MATCH
    the node in Cypher. ``properties`` carries everything else the node stores (display_name,
    handle, email, aliases, ...), used for embedding input and the Tier 1 rules.
    """

    model_config = ConfigDict(frozen=True)

    node_type: NodeType
    node_id: str
    properties: dict[str, object] = Field(default_factory=dict)
    source_event_ids: tuple[str, ...] = ()
    status: str = "active"

    @property
    def key_field(self) -> str:
        """The node-property name this node's ``node_id`` is keyed on."""
        return KEY_FIELD[self.node_type]

    def prop_str(self, name: str) -> str | None:
        """Return property ``name`` as a non-empty string, or None."""
        value = self.properties.get(name)
        if isinstance(value, str) and value.strip():
            return value
        return None


class CandidatePair(BaseModel):
    """An unordered pair of same-type nodes considered for merging, with their similarity."""

    model_config = ConfigDict(frozen=True)

    node_a: ResolvableNode
    node_b: ResolvableNode
    similarity: float


class LLMVerdict(BaseModel):
    """The structured output of the Tier 2 adjudicator (claude-3.5-haiku).

    ``extra="forbid"`` so a malformed LLM response fails validation and the adjudicator falls
    back to a safe no-merge, rather than silently accepting garbage.
    """

    model_config = ConfigDict(extra="forbid")

    same: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


class TypeBreakdown(BaseModel):
    """Per-entity-type resolution counts for the report."""

    model_config = ConfigDict(frozen=True)

    node_type: NodeType
    node_count: int
    candidate_pairs: int
    auto_merges: int
    llm_merges: int
    llm_no_merges: int
    below_threshold: int

    @property
    def total_merges(self) -> int:
        return self.auto_merges + self.llm_merges


class ResolutionReport(BaseModel):
    """The outcome of a ``resolve_graph`` run: per-type counts and the run mode."""

    model_config = ConfigDict(frozen=True)

    by_type: dict[str, TypeBreakdown] = Field(default_factory=dict)
    dry_run: bool = False
    llm_cost_usd: float = 0.0

    @property
    def total_merges(self) -> int:
        return sum(b.total_merges for b in self.by_type.values())

    @property
    def total_candidates(self) -> int:
        return sum(b.candidate_pairs for b in self.by_type.values())
