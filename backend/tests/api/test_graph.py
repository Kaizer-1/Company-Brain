"""Tests for GET /api/graph (Phase 3C).

Uses real Neo4j testcontainer seeded with a small fixture to verify resolved/fragmented views,
MERGE_INTO edge inclusion, and node type filtering.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

pytestmark = pytest.mark.asyncio

# ── Fixture helpers ───────────────────────────────────────────────────────────

_SEED = """
CREATE (d:Decision {id:'D-0006', title:'Deprecate legacy-auth', status:'active', source_event_ids:['e1']})
CREATE (s:Service {canonical_name:'payments-api', id:'payments-api', status:'active', source_event_ids:['e2']})
CREATE (p1:Person {canonical_id:'alice', id:'alice', display_name:'Alice', status:'active', source_event_ids:['e3']})
CREATE (p2:Person {canonical_id:'alice-alias', id:'alice-alias', display_name:'alice', status:'merged', source_event_ids:['e4']})
CREATE (d)-[:DEPRECATES {source_event_id:'e5'}]->(s)
CREATE (p2)-[:MERGE_INTO {confidence:0.95, tier:2}]->(p1)
"""


async def _seed(driver: object) -> None:
    async with driver.session() as sess:  # type: ignore[attr-defined]
        await (await sess.run(_SEED)).consume()


# ── Unit tests (mock driver, no testcontainer) ────────────────────────────────

def _make_app(driver: object) -> object:
    """Build a minimal FastAPI test client with a mocked Neo4j driver."""
    from fastapi.testclient import TestClient
    from app.api.graph import router
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)

    neo4j_state = MagicMock()
    neo4j_state.driver = driver
    app.state.neo4j = neo4j_state
    return TestClient(app)


def test_graph_resolved_excludes_merged_nodes(neo4j_driver: object) -> None:
    """Resolved view must not include nodes with status='merged'."""
    import asyncio
    asyncio.get_event_loop().run_until_complete(_seed(neo4j_driver))
    client = _make_app(neo4j_driver)

    resp = client.get("/api/graph?view=resolved")
    assert resp.status_code == 200
    data = resp.json()

    node_statuses = [n["status"] for n in data["nodes"]]
    assert "merged" not in node_statuses, "Resolved view must exclude merged nodes"


def test_graph_resolved_excludes_merge_into_edges(neo4j_driver: object) -> None:
    """Resolved view must not include MERGE_INTO edges."""
    import asyncio
    asyncio.get_event_loop().run_until_complete(_seed(neo4j_driver))
    client = _make_app(neo4j_driver)

    resp = client.get("/api/graph?view=resolved")
    assert resp.status_code == 200
    data = resp.json()

    edge_types = [e["edge_type"] for e in data["edges"]]
    assert "MERGE_INTO" not in edge_types, "Resolved view must exclude MERGE_INTO edges"


def test_graph_fragmented_includes_merged_nodes(neo4j_driver: object) -> None:
    """Fragmented view includes tombstoned merged nodes."""
    import asyncio
    asyncio.get_event_loop().run_until_complete(_seed(neo4j_driver))
    client = _make_app(neo4j_driver)

    resp = client.get("/api/graph?view=fragmented")
    assert resp.status_code == 200
    data = resp.json()

    node_statuses = [n["status"] for n in data["nodes"]]
    assert "merged" in node_statuses, "Fragmented view must include merged nodes"


def test_graph_fragmented_includes_merge_into_edges(neo4j_driver: object) -> None:
    """Fragmented view flags MERGE_INTO edges with is_merge_into=True."""
    import asyncio
    asyncio.get_event_loop().run_until_complete(_seed(neo4j_driver))
    client = _make_app(neo4j_driver)

    resp = client.get("/api/graph?view=fragmented")
    assert resp.status_code == 200
    data = resp.json()

    merge_edges = [e for e in data["edges"] if e["is_merge_into"]]
    assert len(merge_edges) >= 1, "Fragmented view must include MERGE_INTO edges flagged"


def test_graph_invalid_view_rejected() -> None:
    """view parameter must be 'resolved' or 'fragmented'; anything else → 422."""
    from fastapi.testclient import TestClient
    from app.api.graph import router
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    resp = client.get("/api/graph?view=invalid")
    assert resp.status_code == 422


def test_graph_node_types_present(neo4j_driver: object) -> None:
    """Every returned node must have a node_type in the known closed set."""
    import asyncio
    asyncio.get_event_loop().run_until_complete(_seed(neo4j_driver))
    client = _make_app(neo4j_driver)

    resp = client.get("/api/graph?view=fragmented")
    assert resp.status_code == 200
    data = resp.json()

    known = {"Decision", "Service", "System", "Person", "Team", "Message"}
    for node in data["nodes"]:
        assert node["node_type"] in known, f"Unknown node_type: {node['node_type']}"
