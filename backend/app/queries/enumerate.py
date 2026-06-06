"""Structural tool — ``enumerate_by_type`` (Phase 4C).

> List all nodes of a type, with filters / ordering / limit / negative-edge constraints.

This is the load-bearing structural tool: it absorbs what would otherwise be separate
"recency" and "find-orphans" tools (see ADR 0028). "The most recent decision" is
``enumerate_by_type(Decision, order_by="valid_from_desc", limit=1)``; "services without an
owner" is ``enumerate_by_type(Service, has_no_edge="OWNED_BY")``.

Identity and naming are heterogeneous in the actual graph (Person→``canonical_id``,
Service/System/Team→``canonical_name``, Decision→``id``+``title``, Message→``id``), so a
single ``coalesce`` builds a uniform display name. The label, status mode, and negative
edge are all passed as **parameters** — ``$node_type IN labels(n)``, ``type(r) = $edge`` —
rather than interpolated into Cypher (CLAUDE.md: parameterised queries only). The single
exception is the ``ORDER BY`` clause, which Cypher cannot parameterise; it is mapped from a
closed ``order_by`` Literal to a fixed fragment in ``_ORDER_BY_CYPHER`` (no free text ever
reaches the query string). Full rationale: docs/design/structural-tools.md, ADR 0028.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from app.queries.result_types import QueryProvenance, QueryResult
from app.queries.structural_common import (
    NODE_TYPES,
    NodeTypeLiteral,
    StatusLiteral,
    jsonable_props,
    node_display_name,
    status_predicate,
)

if TYPE_CHECKING:
    from neo4j import AsyncDriver

# Edge types valid for the negative-existence filter. Mirrors the closed edge vocabulary
# (CLAUDE.md); MERGE_INTO is deliberately excluded (it is a resolution artefact, not a
# domain edge a user would filter on).
EnumerateEdgeLiteral = Literal[
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

OrderByLiteral = Literal[
    "canonical_name",
    "valid_from",
    "valid_from_desc",
    "created_at",
    "created_at_desc",
]

# Closed map from the validated order_by Literal to a safe Cypher ORDER BY fragment. Cypher
# cannot parameterise ORDER BY, so this is the one place a fragment is interpolated — and the
# key is guaranteed to be one of these by Pydantic before it ever reaches the query builder.
_ORDER_BY_CYPHER: dict[str, str] = {
    "canonical_name": "name ASC",
    "valid_from": "n.valid_from ASC",
    "valid_from_desc": "n.valid_from DESC",
    "created_at": "n.created_at ASC",
    "created_at_desc": "n.created_at DESC",
}

# Properties already surfaced as dedicated fields; everything else on the node becomes
# type-specific ``extra_fields`` (email/handle for Person, valid_from/valid_to/title for
# Decision, formerly for Service, content for Message, …).
_PROMOTED_KEYS = frozenset({"canonical_id", "canonical_name", "id", "status", "source_event_ids"})


class EnumerateInput(BaseModel):
    """Validated parameters for ``enumerate_by_type`` (the tool node validates ``tool_input``)."""

    node_type: NodeTypeLiteral
    status: StatusLiteral = "active"
    order_by: OrderByLiteral = "canonical_name"
    limit: int = Field(default=100, ge=1, le=500)
    has_no_edge: EnumerateEdgeLiteral | None = None
    team_filter: str | None = None


class EnumeratedNode(BaseModel):
    """One enumerated node: its id, display name, status, and type-specific extras."""

    id: str
    name: str
    status: str
    extra_fields: dict[str, Any] = Field(default_factory=dict)
    source_event_ids: list[str] = Field(default_factory=list)


class EnumerateResult(BaseModel):
    """``enumerate_by_type`` answer.

    ``total_count`` (the count *before* the limit) is load-bearing: synthesis distinguishes
    "all 13 people" from "the first 100 of 1247 messages".
    """

    node_type: str
    total_count: int
    returned_count: int
    nodes: list[EnumeratedNode] = Field(default_factory=list)
    filters_applied: dict[str, Any] = Field(default_factory=dict)


# Shared WHERE body. ``$status_mode`` drives the lifecycle filter (see ``status_predicate``);
# ``$has_no_edge`` is the negative-existence constraint that absorbs the would-be find-orphans
# tool; ``$team_filter`` scopes to nodes connected to a named team.
_WHERE = f"""
  $node_type IN labels(n)
  AND {status_predicate('n')}
  AND ($has_no_edge IS NULL OR NOT EXISTS {{ MATCH (n)-[hr]->() WHERE type(hr) = $has_no_edge }})
  AND (
    $team_filter IS NULL
    OR EXISTS {{ MATCH (n)-[:OWNED_BY|MEMBER_OF]->(tt:Team) WHERE toLower(tt.canonical_name) = toLower($team_filter) }}
  )
"""

_COUNT_QUERY = f"MATCH (n)\nWHERE{_WHERE}\nRETURN count(n) AS total"


def _fetch_query(order_by: OrderByLiteral) -> str:
    """Build the fetch query, interpolating only the validated ORDER BY fragment."""
    order_fragment = _ORDER_BY_CYPHER[order_by]
    return f"""
MATCH (n)
WHERE{_WHERE}
WITH n, {node_display_name('n')} AS name
RETURN n AS node,
       labels(n)[0] AS node_type,
       name AS name,
       coalesce(n.status, 'active') AS status,
       coalesce(n.source_event_ids, []) AS source_event_ids
ORDER BY {order_fragment}
LIMIT $limit
"""


async def enumerate_by_type(
    driver: AsyncDriver, params: EnumerateInput
) -> QueryResult[EnumerateResult]:
    """List nodes of ``params.node_type`` under the given filters, ordering, and limit.

    Returns both ``total_count`` (pre-limit) and ``returned_count`` so the agent can be
    honest about truncation. Provenance is the union of every returned node's
    ``source_event_ids``; for a pure listing this may be large but is always grounded.
    """
    if params.node_type not in NODE_TYPES:  # defence-in-depth; Pydantic already constrains
        msg = f"unknown node_type: {params.node_type}"
        raise ValueError(msg)

    query_args: dict[str, Any] = {
        "node_type": params.node_type,
        "status_mode": params.status,
        "has_no_edge": params.has_no_edge,
        "team_filter": params.team_filter,
        "limit": params.limit,
    }

    async with driver.session() as session:
        count_rec = await (await session.run(_COUNT_QUERY, **query_args)).single()
        total_count = int(count_rec["total"]) if count_rec else 0

        result = await session.run(_fetch_query(params.order_by), **query_args)
        records = [record.data() async for record in result]

    provenance = QueryProvenance()
    nodes: list[EnumeratedNode] = []
    for row in records:
        node_props = dict(row["node"])
        node_id = str(row["name"])
        extras = jsonable_props(
            {k: v for k, v in node_props.items() if k not in _PROMOTED_KEYS}
        )
        event_ids = [str(e) for e in (row.get("source_event_ids") or [])]
        nodes.append(
            EnumeratedNode(
                id=node_id,
                name=str(row["name"]),
                status=str(row["status"]),
                extra_fields=extras,
                source_event_ids=event_ids,
            )
        )
        if event_ids:
            provenance.add(f"node:{row['node_type']}:{node_id}", event_ids)

    answer = EnumerateResult(
        node_type=params.node_type,
        total_count=total_count,
        returned_count=len(nodes),
        nodes=nodes,
        filters_applied={
            "status": params.status,
            "order_by": params.order_by,
            "limit": params.limit,
            "has_no_edge": params.has_no_edge,
            "team_filter": params.team_filter,
        },
    )
    return QueryResult(value=answer, provenance=provenance)
