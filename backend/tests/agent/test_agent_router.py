"""Route classifier node: correct enum extraction, tool_input passthrough, safe fallback."""

from __future__ import annotations

import json

import pytest

from app.agent.router import classify_route
from app.agent.state import AgentState

from .conftest import FakeClient, make_deps


def _route_json(route: str, tool_input: dict | None = None) -> str:
    return json.dumps(
        {
            "route": route,
            "reasoning": f"test reasoning for {route} route classification",
            "tool_input": tool_input or {},
        }
    )


@pytest.mark.parametrize(
    ("route", "tool_input"),
    [
        ("kq1", {"decision_id": "D-0006"}),
        ("kq2", {"window_days": 30}),
        ("kq3", {"service": "payments-api"}),
        ("kq4", {"target": "auth-service", "window_days": 90}),
        ("search", {}),
        ("unknown", {}),
    ],
)
async def test_each_route_parsed_from_llm(route: str, tool_input: dict) -> None:
    client = FakeClient(content=_route_json(route, tool_input))
    deps = make_deps(client)
    state: AgentState = {"question": "some question"}

    out = await classify_route(state, deps=deps)

    assert out["route"] == route
    assert out["tool_input"] == tool_input
    assert out["cost_usd"] == pytest.approx(0.001)
    assert "classify_route" in out["timings_ms"]


async def test_question_is_interpolated_into_prompt() -> None:
    client = FakeClient(content=_route_json("search"))
    deps = make_deps(client)
    await classify_route({"question": "what about the payments outage?"}, deps=deps)

    sent = client.calls[0]["messages"][0]["content"]
    assert "what about the payments outage?" in sent
    assert client.calls[0]["response_format"] == {"type": "json_object"}


async def test_malformed_json_falls_back_to_search() -> None:
    client = FakeClient(content="this is not json at all")
    deps = make_deps(client)

    out = await classify_route({"question": "q"}, deps=deps)

    assert out["route"] == "search"
    assert "fail" in out["route_reasoning"].lower() or "fall" in out["route_reasoning"].lower()


async def test_wrong_schema_falls_back_to_search() -> None:
    # Valid JSON but missing required fields / bad enum value.
    client = FakeClient(content=json.dumps({"route": "kq9", "reasoning": "x"}))
    deps = make_deps(client)

    out = await classify_route({"question": "q"}, deps=deps)

    assert out["route"] == "search"


async def test_llm_call_exception_falls_back_to_search() -> None:
    client = FakeClient(raise_exc=RuntimeError("boom"))
    deps = make_deps(client)

    out = await classify_route({"question": "q"}, deps=deps)

    assert out["route"] == "search"
    assert out["tool_input"] == {}


async def test_cost_accumulates_onto_existing() -> None:
    client = FakeClient(content=_route_json("kq1", {"decision_id": "D-1"}), cost_usd=0.002)
    deps = make_deps(client)
    out = await classify_route({"question": "q", "cost_usd": 0.005}, deps=deps)
    assert out["cost_usd"] == pytest.approx(0.007)
