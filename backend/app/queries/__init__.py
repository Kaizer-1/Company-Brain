"""The query engine.

Phase 3B: the four typed killer queries over the resolved, temporally-enriched graph, each
returning a ``QueryResult[T]`` with provenance (see docs/design/query-engine.md).

Phase 4C: four structural query tools — ``get_entity`` (single-node lookup),
``neighbors_of_entity`` (typed one-hop traversal), ``enumerate_by_type`` (filtered listing),
and ``aggregate_by_type`` (counting/grouping) — that answer graph-native questions the KQs and
semantic search cannot (see docs/design/structural-tools.md). They follow the same
typed-function + Pydantic-result pattern as the KQs.
"""

from app.queries.aggregate import (
    AggregateGroup,
    AggregateInput,
    AggregateResult,
    aggregate_by_type,
)
from app.queries.enumerate import (
    EnumeratedNode,
    EnumerateInput,
    EnumerateResult,
    enumerate_by_type,
)
from app.queries.get_entity import GetEntityInput, GetEntityResult, get_entity
from app.queries.kq1_multihop_ownership import ChainOwnerAnswer, find_chain_owner
from app.queries.kq2_temporal_contradiction import Contradiction, find_contradictions
from app.queries.kq3_blast_radius import BlastRadius, compute_blast_radius
from app.queries.kq4_change_tracking import ChangeTimeline, track_changes
from app.queries.neighbors import (
    Neighbor,
    NeighborsInput,
    NeighborsResult,
    neighbors_of_entity,
)
from app.queries.result_types import QueryProvenance, QueryResult

__all__ = [
    "AggregateGroup",
    "AggregateInput",
    "AggregateResult",
    "BlastRadius",
    "ChainOwnerAnswer",
    "ChangeTimeline",
    "Contradiction",
    "EnumerateInput",
    "EnumerateResult",
    "EnumeratedNode",
    "GetEntityInput",
    "GetEntityResult",
    "Neighbor",
    "NeighborsInput",
    "NeighborsResult",
    "QueryProvenance",
    "QueryResult",
    "aggregate_by_type",
    "compute_blast_radius",
    "enumerate_by_type",
    "find_chain_owner",
    "find_contradictions",
    "get_entity",
    "neighbors_of_entity",
    "track_changes",
]
