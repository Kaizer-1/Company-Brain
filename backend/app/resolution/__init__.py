"""Entity resolution for the Company Brain graph (Phase 3A).

Decides when two graph nodes refer to the same real-world entity and merges them with a
reversible ``MERGE_INTO`` edge, recording every decision in the ``merge_decisions`` audit
table. Three tiers of increasing cost: deterministic rules (Tier 1), an LLM adjudicator
(Tier 2), and no-merge (Tier 3). See docs/design/entity-resolution.md and ADRs 0014, 0015.

The public entry point is ``resolve_graph``; it is callable from a post-merge batch (this
phase) and, later, an at-write-time path (Phase 4).
"""

from app.resolution.models import (
    CandidatePair,
    LLMVerdict,
    ResolutionReport,
    ResolvableNode,
    TypeBreakdown,
)
from app.resolution.resolver import resolve_graph

__all__ = [
    "CandidatePair",
    "LLMVerdict",
    "ResolutionReport",
    "ResolvableNode",
    "TypeBreakdown",
    "resolve_graph",
]
