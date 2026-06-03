"""The killer-query engine (Phase 3B).

Four typed Cypher queries over the resolved, temporally-enriched graph, each returning a
``QueryResult[T]`` with provenance. See docs/design/query-engine.md.
"""

from app.queries.kq1_multihop_ownership import ChainOwnerAnswer, find_chain_owner
from app.queries.kq2_temporal_contradiction import Contradiction, find_contradictions
from app.queries.kq3_blast_radius import BlastRadius, compute_blast_radius
from app.queries.kq4_change_tracking import ChangeTimeline, track_changes
from app.queries.result_types import QueryProvenance, QueryResult

__all__ = [
    "BlastRadius",
    "ChainOwnerAnswer",
    "ChangeTimeline",
    "Contradiction",
    "QueryProvenance",
    "QueryResult",
    "compute_blast_radius",
    "find_chain_owner",
    "find_contradictions",
    "track_changes",
]
