"""Phase 4C — agent routing + structural tool-node tests.

Three layers:
* ``classify_route`` maps each new question shape to the right route (mocked LLM).
* the four structural tool nodes validate ``tool_input`` and write ``tool_output`` +
  ``available_event_ids`` (real Neo4j via the shared testcontainer).
* a bad ``tool_input`` falls back to ``general_search`` rather than refusing.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.agent import tools
from app.agent.router import classify_route
from app.agent.tools import (
    aggregate_tool,
    enumerate_tool,
    get_entity_tool,
    neighbors_tool,
)

from .conftest import FakeClient, make_deps

pytestmark = pytest.mark.asyncio

_SEED = """
CREATE (a:Person {canonical_id:'alice-chen', id:'alice-chen', handle:'@alice', source_event_ids:['e1']})
CREATE (b:Person {canonical_id:'bob', id:'bob', source_event_ids:['e2']})
CREATE (pay:Team {canonical_name:'Payments', id:'payments', source_event_ids:['et1']})
CREATE (svc:Service {canonical_name:'payments-api', id:'payments-api', source_event_ids:['es1']})
CREATE (d:Decision {id:'D-0006', title:'Deprecate legacy-auth', status:'active', source_event_ids:['ed1']})
CREATE (a)-[:MEMBER_OF {source_event_id:'m1'}]->(pay)
CREATE (svc)-[:OWNED_BY {source_event_id:'o1'}]->(pay)
"""


async def _seed(driver: object) -> None:
    async with driver.session() as s:  # type: ignore[attr-defined]
        await (await s.run(_SEED)).consume()


def _route_json(route: str, tool_input: dict[str, Any]) -> str:
    return json.dumps(
        {"route": route, "reasoning": f"routes to {route} tool", "tool_input": tool_input}
    )


@pytest.mark.parametrize(
    ("route", "tool_input"),
    [
        ("get_entity", {"entity_id": "D-0006", "node_type_hint": "Decision"}),
        ("neighbors", {"entity_id": "Payments", "edge_type": "MEMBER_OF", "direction": "in"}),
        ("enumerate", {"node_type": "Person"}),
        ("aggregate", {"node_type": "Service", "group_by": "OWNED_BY"}),
    ],
)
async def test_classify_route_picks_structural_route(
    route: str, tool_input: dict[str, Any]
) -> None:
    deps = make_deps(FakeClient(content=_route_json(route, tool_input)))
    out = await classify_route({"question": "q"}, deps=deps)
    assert out["route"] == route
    assert out["tool_input"] == tool_input


async def test_enumerate_tool_lists_people(neo4j_driver: object) -> None:
    await _seed(neo4j_driver)
    deps = make_deps(FakeClient(), neo4j_driver=neo4j_driver)
    out = await enumerate_tool({"tool_input": {"node_type": "Person"}}, deps=deps)
    assert out["tool_output"] is not None
    assert out["tool_output"]["value"]["total_count"] == 2  # type: ignore[index]
    assert set(out["available_event_ids"]) >= {"e1", "e2"}  # type: ignore[operator]


async def test_get_entity_tool_writes_output(neo4j_driver: object) -> None:
    await _seed(neo4j_driver)
    deps = make_deps(FakeClient(), neo4j_driver=neo4j_driver)
    out = await get_entity_tool({"tool_input": {"entity_id": "D-0006"}}, deps=deps)
    assert out["tool_output"]["value"]["node_type"] == "Decision"  # type: ignore[index]


async def test_neighbors_tool_writes_output(neo4j_driver: object) -> None:
    await _seed(neo4j_driver)
    deps = make_deps(FakeClient(), neo4j_driver=neo4j_driver)
    out = await neighbors_tool(
        {"tool_input": {"entity_id": "Payments", "edge_type": "MEMBER_OF", "direction": "in"}},
        deps=deps,
    )
    assert out["tool_output"]["value"]["total_count"] == 1  # type: ignore[index]


async def test_aggregate_tool_no_events(neo4j_driver: object) -> None:
    await _seed(neo4j_driver)
    deps = make_deps(FakeClient(), neo4j_driver=neo4j_driver)
    out = await aggregate_tool({"tool_input": {"node_type": "Service"}}, deps=deps)
    assert out["tool_output"]["value"]["total"] == 1  # type: ignore[index]
    # Aggregates have no citable events.
    assert out["available_event_ids"] == []


async def test_bad_tool_input_falls_back_to_search(neo4j_driver: object, monkeypatch: pytest.MonkeyPatch) -> None:
    await _seed(neo4j_driver)
    called: dict[str, Any] = {}

    async def fake_search(state: Any, *, deps: Any) -> dict[str, object]:
        called["hit"] = True
        return {"tool_output": {"hits": []}, "available_event_ids": [], "timings_ms": {}}

    monkeypatch.setattr(tools, "general_search", fake_search)
    deps = make_deps(FakeClient(), neo4j_driver=neo4j_driver)
    # node_type is required + must be a valid Literal; "Employee" is invalid.
    out = await enumerate_tool({"tool_input": {"node_type": "Employee"}}, deps=deps)
    assert called.get("hit") is True
    assert "fell back to search" in str(out.get("route_reasoning", ""))
