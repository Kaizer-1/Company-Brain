"""Structural tool — ``get_entity`` (Phase 4C).

> Scalar property lookup for a single entity, plus a summary of its neighbour edge types.

Answers questions like "What's Diego's handle?" or "What's the status of D-0006?" — where
semantic search returns events *mentioning* the entity rather than the entity's own
properties. The match is identity-field-agnostic (see ``structural_common.identity_predicate``)
so the router can pass a canonical_id, canonical_name, decision id, or ``@handle``.

If nothing matches, a ``GetEntityResult`` with ``node_type="not_found"`` is returned; the
agent's empty/synthesis handling states the absence honestly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from app.queries.result_types import QueryProvenance, QueryResult
from app.queries.structural_common import (
    NodeTypeLiteral,
    identity_predicate,
    jsonable_props,
    node_display_name,
)

if TYPE_CHECKING:
    from neo4j import AsyncDriver

NOT_FOUND = "not_found"

_PROMOTED_KEYS = frozenset({"source_event_ids"})

_QUERY = f"""
MATCH (n)
WHERE {identity_predicate('n', 'entity_id')}
  AND coalesce(n.status, 'active') <> 'merged'
  AND ($node_type_hint IS NULL OR $node_type_hint IN labels(n))
RETURN n AS node,
       labels(n)[0] AS node_type,
       {node_display_name('n')} AS name,
       [(n)-[r]->(m) WHERE coalesce(m.status, 'active') <> 'merged' | type(r)] AS outgoing_edge_types,
       [(m)-[r]->(n) WHERE coalesce(m.status, 'active') <> 'merged' | type(r)] AS incoming_edge_types,
       coalesce(n.source_event_ids, []) AS source_event_ids
ORDER BY name
LIMIT 1
"""


class GetEntityInput(BaseModel):
    """Validated parameters for ``get_entity``."""

    entity_id: str = Field(min_length=1)
    node_type_hint: NodeTypeLiteral | None = None


class GetEntityResult(BaseModel):
    """A single entity's properties and its neighbour-edge-type summary."""

    entity_id: str
    node_type: str  # the matched label, or "not_found"
    properties: dict[str, Any] = Field(default_factory=dict)
    outgoing_edges: dict[str, int] = Field(default_factory=dict)  # edge_type -> count
    incoming_edges: dict[str, int] = Field(default_factory=dict)
    source_event_ids: list[str] = Field(default_factory=list)


def _count_types(edge_types: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for et in edge_types:
        counts[et] = counts.get(et, 0) + 1
    return counts


async def get_entity(
    driver: AsyncDriver, params: GetEntityInput
) -> QueryResult[GetEntityResult]:
    """Look up one entity by any identity field and summarise its properties + edges."""
    async with driver.session() as session:
        result = await session.run(
            _QUERY,
            entity_id=params.entity_id,
            node_type_hint=params.node_type_hint,
        )
        record = await result.single()

    if record is None:
        answer = GetEntityResult(entity_id=params.entity_id, node_type=NOT_FOUND)
        return QueryResult(value=answer, provenance=QueryProvenance())

    node_props = jsonable_props(
        {k: v for k, v in dict(record["node"]).items() if k not in _PROMOTED_KEYS}
    )
    event_ids = [str(e) for e in (record.get("source_event_ids") or [])]
    node_type = str(record["node_type"])
    display_id = str(record["name"])

    provenance = QueryProvenance()
    if event_ids:
        provenance.add(f"node:{node_type}:{display_id}", event_ids)

    answer = GetEntityResult(
        entity_id=params.entity_id,
        node_type=node_type,
        properties=node_props,
        outgoing_edges=_count_types(list(record.get("outgoing_edge_types") or [])),
        incoming_edges=_count_types(list(record.get("incoming_edge_types") or [])),
        source_event_ids=event_ids,
    )
    return QueryResult(value=answer, provenance=provenance)
