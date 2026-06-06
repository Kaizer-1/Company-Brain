"""Structural tool — ``neighbors_of_entity`` (Phase 4C).

> Typed one-hop traversal: who/what is connected to X via edge Y (and in which direction)?

Answers "who's on the payments team?" (``neighbors(payments, MEMBER_OF, in)``) or "what does
auth-service depend on?" (``neighbors(auth-service, DEPENDS_ON, out)``) — questions where
search surfaces *messages mentioning* the entity rather than the structural neighbours.

The edge type and direction are passed as parameters (``type(r) = $edge_type``,
``startNode(r) = n``), never interpolated, so there is no Cypher-injection surface. The
resolved-view filter (``m.status <> 'merged'``) also means ``MERGE_INTO`` edges — which always
point at a merged loser — never surface as neighbours. Disambiguation from KQ1/KQ3: those are
*transitive* multi-hop patterns; this is a single typed hop (router "prefer specific" rule).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from app.queries.result_types import QueryProvenance, QueryResult
from app.queries.structural_common import identity_predicate, node_display_name

if TYPE_CHECKING:
    from neo4j import AsyncDriver

NeighborEdgeLiteral = Literal[
    "DEPENDS_ON",
    "OWNED_BY",
    "MEMBER_OF",
    "DEPRECATES",
    "ABOUT",
    "APPROVED_BY",
    "AUTHORED",
    "MENTIONS",
    "SUPERSEDES",
    "CONTRADICTS",
]

DirectionLiteral = Literal["out", "in", "both"]

_DIRECTION_FILTER = """
    $direction = 'both'
    OR ($direction = 'out' AND startNode(r) = n)
    OR ($direction = 'in' AND endNode(r) = n)
"""

_MATCH = f"""
MATCH (n)
WHERE {identity_predicate('n', 'entity_id')} AND coalesce(n.status, 'active') <> 'merged'
MATCH (n)-[r]-(m)
WHERE coalesce(m.status, 'active') <> 'merged'
  AND ($edge_type IS NULL OR type(r) = $edge_type)
  AND ({_DIRECTION_FILTER})
"""

_COUNT_QUERY = f"{_MATCH}\nRETURN count(r) AS total"

_FETCH_QUERY = f"""{_MATCH}
RETURN {node_display_name('m')} AS neighbor_id,
       {node_display_name('m')} AS neighbor_name,
       labels(m)[0] AS neighbor_type,
       type(r) AS edge_type,
       (startNode(r) = n) AS outgoing,
       coalesce(r.source_event_id, '') AS source_event_id
ORDER BY edge_type, neighbor_name
LIMIT $limit
"""


class NeighborsInput(BaseModel):
    """Validated parameters for ``neighbors_of_entity``."""

    entity_id: str = Field(min_length=1)
    edge_type: NeighborEdgeLiteral | None = None
    direction: DirectionLiteral = "both"
    limit: int = Field(default=50, ge=1, le=200)


class Neighbor(BaseModel):
    """One neighbouring node reached in a single typed hop."""

    neighbor_id: str
    neighbor_name: str
    neighbor_type: str
    edge_type: str
    outgoing: bool
    source_event_id: str | None = None


class NeighborsResult(BaseModel):
    """``neighbors_of_entity`` answer: the entity plus its typed one-hop neighbours."""

    entity_id: str
    total_count: int
    neighbors: list[Neighbor] = Field(default_factory=list)


async def neighbors_of_entity(
    driver: AsyncDriver, params: NeighborsInput
) -> QueryResult[NeighborsResult]:
    """Return the typed one-hop neighbours of ``params.entity_id``.

    ``total_count`` is the pre-limit neighbour count so the agent can report truncation.
    Provenance is each traversed edge's ``source_event_id`` (absent on SUPERSEDES).
    """
    query_args: dict[str, Any] = {
        "entity_id": params.entity_id,
        "edge_type": params.edge_type,
        "direction": params.direction,
        "limit": params.limit,
    }

    async with driver.session() as session:
        count_rec = await (await session.run(_COUNT_QUERY, **query_args)).single()
        total_count = int(count_rec["total"]) if count_rec else 0

        result = await session.run(_FETCH_QUERY, **query_args)
        records = [record.data() async for record in result]

    provenance = QueryProvenance()
    neighbors: list[Neighbor] = []
    for row in records:
        raw_evt = row.get("source_event_id") or ""
        evt = str(raw_evt) if raw_evt else None
        neighbor_id = str(row["neighbor_id"])
        neighbors.append(
            Neighbor(
                neighbor_id=neighbor_id,
                neighbor_name=str(row["neighbor_name"]),
                neighbor_type=str(row["neighbor_type"]),
                edge_type=str(row["edge_type"]),
                outgoing=bool(row["outgoing"]),
                source_event_id=evt,
            )
        )
        if evt:
            provenance.add(
                f"edge:{row['edge_type']}:{params.entity_id}->{neighbor_id}", [evt]
            )

    answer = NeighborsResult(
        entity_id=params.entity_id, total_count=total_count, neighbors=neighbors
    )
    return QueryResult(value=answer, provenance=provenance)
