"""Graph data endpoint for the react-force-graph-2d visualisation (Phase 3C).

Returns nodes + edges shaped for react-force-graph-2d:
    GET /api/graph?view=resolved    # status != 'merged', no MERGE_INTO edges
    GET /api/graph?view=fragmented  # everything, MERGE_INTO edges flagged for dashed rendering
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/graph", tags=["graph"])
log = structlog.get_logger(__name__)


class GraphNode(BaseModel):
    """One node in the force graph."""

    id: str
    node_type: str
    label: str
    status: str
    source_event_ids: list[str]
    canonical_id: str | None = None


class GraphEdge(BaseModel):
    """One directed edge in the force graph."""

    id: str
    source: str
    target: str
    edge_type: str
    is_merge_into: bool = False
    confidence: float | None = None
    source_event_id: str | None = None


class GraphResponse(BaseModel):
    """Full graph payload for the visualisation."""

    nodes: list[GraphNode]
    edges: list[GraphEdge]
    view: str


# Only the schema-known node labels; _Migration is an internal migration marker.
_KNOWN_LABELS = frozenset(
    {"Decision", "Service", "System", "Person", "Team", "Message"}
)

_NODES_RESOLVED = """
MATCH (n)
WHERE NOT (n:_Migration)
  AND coalesce(n.status, 'active') <> 'merged'
RETURN elementId(n) AS eid, labels(n) AS node_labels, properties(n) AS props
"""

_NODES_FRAGMENTED = """
MATCH (n)
WHERE NOT (n:_Migration)
RETURN elementId(n) AS eid, labels(n) AS node_labels, properties(n) AS props
"""

_EDGES_RESOLVED = """
MATCH (a)-[r]->(b)
WHERE NOT (a:_Migration) AND NOT (b:_Migration)
  AND type(r) <> 'MERGE_INTO'
  AND coalesce(a.status, 'active') <> 'merged'
  AND coalesce(b.status, 'active') <> 'merged'
RETURN elementId(r) AS eid,
       elementId(a) AS source_eid,
       elementId(b) AS target_eid,
       type(r) AS rel_type,
       properties(r) AS props
"""

_EDGES_FRAGMENTED = """
MATCH (a)-[r]->(b)
WHERE NOT (a:_Migration) AND NOT (b:_Migration)
RETURN elementId(r) AS eid,
       elementId(a) AS source_eid,
       elementId(b) AS target_eid,
       type(r) AS rel_type,
       properties(r) AS props
"""


def _display_label(label_type: str, props: dict[str, Any]) -> str:
    if label_type == "Decision":
        return str(props.get("title") or props.get("id") or "?")
    if label_type == "Person":
        return str(props.get("display_name") or props.get("canonical_id") or "?")
    if label_type in ("Service", "System", "Team"):
        return str(props.get("canonical_name") or "?")
    if label_type == "Message":
        content = str(props.get("content", ""))
        return content[:48] + ("…" if len(content) > 48 else "")
    return str(props.get("id") or label_type)


def _canonical_id(label_type: str, props: dict[str, Any]) -> str | None:
    if label_type == "Decision":
        return props.get("id")
    if label_type == "Person":
        return props.get("canonical_id")
    if label_type in ("Service", "System", "Team"):
        return props.get("canonical_name")
    if label_type == "Message":
        return props.get("id")
    return None


def _str_list(val: Any) -> list[str]:
    if isinstance(val, list):
        return [str(v) for v in val if v is not None]
    return []


@router.get("", response_model=GraphResponse, summary="Full graph for the force-graph visualisation.")
async def get_graph(
    request: Request,
    view: str = Query("resolved", pattern="^(resolved|fragmented)$"),
) -> GraphResponse:
    """Return all nodes + edges shaped for react-force-graph-2d.

    Resolved view: only canonical nodes (status != 'merged'), no MERGE_INTO edges.
    Fragmented view: all nodes including tombstones; MERGE_INTO edges included and flagged
    so the frontend can render them as dashed lines to visualise entity-resolution work.
    """
    driver = request.app.state.neo4j.driver
    node_q = _NODES_RESOLVED if view == "resolved" else _NODES_FRAGMENTED
    edge_q = _EDGES_RESOLVED if view == "resolved" else _EDGES_FRAGMENTED

    async with driver.session() as session:
        node_result = await session.run(node_q)
        node_records = [r.data() async for r in node_result]
        edge_result = await session.run(edge_q)
        edge_records = [r.data() async for r in edge_result]

    nodes: list[GraphNode] = []
    for r in node_records:
        raw_labels: list[str] = r.get("node_labels") or []
        known = [lb for lb in raw_labels if lb in _KNOWN_LABELS]
        if not known:
            continue
        label_type = known[0]
        props: dict[str, Any] = r.get("props") or {}
        nodes.append(
            GraphNode(
                id=r["eid"],
                node_type=label_type,
                label=_display_label(label_type, props),
                status=str(props.get("status", "active")),
                source_event_ids=_str_list(props.get("source_event_ids")),
                canonical_id=_canonical_id(label_type, props),
            )
        )

    edges: list[GraphEdge] = []
    for r in edge_records:
        props = r.get("props") or {}
        rel_type: str = r["rel_type"]
        conf = props.get("confidence")
        src_evt = props.get("source_event_id")
        edges.append(
            GraphEdge(
                id=r["eid"],
                source=r["source_eid"],
                target=r["target_eid"],
                edge_type=rel_type,
                is_merge_into=(rel_type == "MERGE_INTO"),
                confidence=float(conf) if conf is not None else None,
                source_event_id=str(src_evt) if src_evt is not None else None,
            )
        )

    log.info("graph_fetched", view=view, node_count=len(nodes), edge_count=len(edges))
    return GraphResponse(nodes=nodes, edges=edges, view=view)
