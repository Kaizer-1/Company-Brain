"""Structural tool — ``aggregate_by_type`` (Phase 4C).

> Count nodes of a type, optionally grouped by a relationship.

Answers "how many active decisions are there?" (total) and "which team owns the most
services?" (``group_by="OWNED_BY"``) — counting questions search cannot do at all. ``total``
is always populated (the ungrouped count); ``groups`` is populated only when ``group_by`` is
set. The group node's status is filtered to the resolved view and its display name is
coalesced across the heterogeneous identity fields (a service may be ``OWNED_BY`` either a
Team *or* a Person, so the grouping must name both).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from app.queries.result_types import QueryProvenance, QueryResult
from app.queries.structural_common import (
    NODE_TYPES,
    NodeTypeLiteral,
    StatusLiteral,
    node_display_name,
    status_predicate,
)

if TYPE_CHECKING:
    from neo4j import AsyncDriver

GroupByLiteral = Literal["OWNED_BY", "MEMBER_OF", "DEPENDS_ON"]
OrderLiteral = Literal["count_desc", "count_asc", "name_asc"]

# Cypher cannot parameterise ORDER BY; map the validated Literal to a fixed fragment.
_ORDER_CYPHER: dict[str, str] = {
    "count_desc": "count DESC, group_name ASC",
    "count_asc": "count ASC, group_name ASC",
    "name_asc": "group_name ASC",
}

_TOTAL_QUERY = f"""
MATCH (n)
WHERE $node_type IN labels(n) AND {status_predicate('n')}
RETURN count(n) AS total
"""


def _group_query(order: OrderLiteral) -> str:
    """Build the grouping query, interpolating only the validated ORDER BY fragment."""
    return f"""
MATCH (n)-[r]->(g)
WHERE $node_type IN labels(n) AND {status_predicate('n')}
  AND coalesce(g.status, 'active') <> 'merged'
  AND type(r) = $group_by
WITH {node_display_name('g')} AS group_name, labels(g)[0] AS group_type, count(n) AS count
RETURN group_name, group_type, count
ORDER BY {_ORDER_CYPHER[order]}
LIMIT $limit
"""


class AggregateInput(BaseModel):
    """Validated parameters for ``aggregate_by_type``."""

    node_type: NodeTypeLiteral
    status: StatusLiteral = "active"
    group_by: GroupByLiteral | None = None
    limit: int = Field(default=20, ge=1, le=100)
    order: OrderLiteral = "count_desc"


class AggregateGroup(BaseModel):
    """One group bucket: the connected node and how many ``node_type`` nodes link to it."""

    group_name: str
    group_type: str
    count: int


class AggregateResult(BaseModel):
    """``aggregate_by_type`` answer. ``total`` is always set; ``groups`` only when grouped."""

    node_type: str
    total: int
    groups: list[AggregateGroup] | None = None


async def aggregate_by_type(
    driver: AsyncDriver, params: AggregateInput
) -> QueryResult[AggregateResult]:
    """Count ``params.node_type`` nodes, optionally grouped by an outgoing relationship.

    Provenance is empty: an aggregate is a fact about the graph's structure, not about any
    single source event (ADR 0030 — verification skips the citation check for this).
    """
    if params.node_type not in NODE_TYPES:  # defence-in-depth; Pydantic already constrains
        msg = f"unknown node_type: {params.node_type}"
        raise ValueError(msg)

    args: dict[str, Any] = {
        "node_type": params.node_type,
        "status_mode": params.status,
        "group_by": params.group_by,
        "limit": params.limit,
    }

    async with driver.session() as session:
        total_rec = await (await session.run(_TOTAL_QUERY, **args)).single()
        total = int(total_rec["total"]) if total_rec else 0

        groups: list[AggregateGroup] | None = None
        if params.group_by is not None:
            result = await session.run(_group_query(params.order), **args)
            rows = [record.data() async for record in result]
            groups = [
                AggregateGroup(
                    group_name=str(row["group_name"]),
                    group_type=str(row["group_type"]),
                    count=int(row["count"]),
                )
                for row in rows
            ]

    answer = AggregateResult(node_type=params.node_type, total=total, groups=groups)
    return QueryResult(value=answer, provenance=QueryProvenance())
