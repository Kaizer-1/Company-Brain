"""LangGraph assembly (Phase 4A; ADR 0024).

Wires the nodes into the route-then-execute-then-verify state machine:

    START → classify_route → (route) ─┬→ kq1_owner ──┐
                                      ├→ kq2_contra ─┤
                                      ├→ kq3_blast ──┼→ (has citable events?) ─┬→ synthesize_answer
                                      ├→ kq4_change ─┤                          └→ empty_answer → END
                                      ├→ general_search ┘
                                      └→ unknown → END

    synthesize_answer → verify_provenance → (verified or retries spent?) ─┬→ END
                                                                          └→ synthesize_answer (retry)

Dependencies (LLM client, config, DB handles) are bound into each node with
``functools.partial`` — LangGraph passes only the state, so everything else is closed over
at build time. LangGraph (not LangChain) is used directly: the abstraction is small enough
to read end-to-end, which is the point for a portfolio project (ADR 0024 discussion).
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from langgraph.graph import END, START, StateGraph

from app.agent.router import classify_route
from app.agent.state import STRUCTURAL_ROUTES, AgentState, RouteLiteral
from app.agent.synthesis import synthesize_answer
from app.agent.tools import (
    aggregate_tool,
    empty_answer,
    enumerate_tool,
    general_search,
    get_entity_tool,
    kq1_owner,
    kq2_contra,
    kq3_blast,
    kq4_change,
    neighbors_tool,
    unknown,
)
from app.agent.verification import route_after_verify, verify_provenance

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

    from app.agent.deps import AgentDeps

    # The compiled graph parametrised over our state. Context is unused (we bind deps via
    # partial, not via LangGraph's runtime context), so it is typed ``None``; input and
    # output channels are the same AgentState the nodes read and write.
    AgentGraph = CompiledStateGraph[AgentState, None, AgentState, AgentState]

# Maps the router's enum to the node name that handles it. The conditional edge from
# classify_route uses this 1:1 mapping — adding a route means adding a node and an entry.
_ROUTE_TO_NODE: dict[RouteLiteral, str] = {
    "kq1": "kq1_owner",
    "kq2": "kq2_contra",
    "kq3": "kq3_blast",
    "kq4": "kq4_change",
    "search": "general_search",
    "get_entity": "get_entity_tool",
    "neighbors": "neighbors_tool",
    "enumerate": "enumerate_tool",
    "aggregate": "aggregate_tool",
    "unknown": "unknown",
}

# The tool nodes that produce answerable output and therefore flow into synthesis.
_SYNTHESIS_TOOLS = (
    "kq1_owner",
    "kq2_contra",
    "kq3_blast",
    "kq4_change",
    "general_search",
    "get_entity_tool",
    "neighbors_tool",
    "enumerate_tool",
    "aggregate_tool",
)


def _select_tool(state: AgentState) -> str:
    """Conditional edge out of classify_route: map the route enum to its tool node."""
    return _ROUTE_TO_NODE.get(state.get("route", "search"), "general_search")


def _route_after_tool(state: AgentState) -> str:
    """Conditional edge out of a tool node: synthesise if there is an answerable result.

    Normally that means citable events were found. A structural tool (Phase 4C) is an
    exception: it can produce a meaningful answer (a count, an empty list, a not-found) with
    no source events. We detect a genuine structural result by its ``QueryResult`` shape
    (a ``value`` key — search output has ``hits`` instead, so a fallback-to-search empty
    result still correctly routes to ``empty_answer``).
    """
    if state.get("available_event_ids"):
        return "synthesize_answer"
    out = state.get("tool_output")
    if state.get("route") in STRUCTURAL_ROUTES and isinstance(out, dict) and "value" in out:
        return "synthesize_answer"
    return "empty_answer"


def build_agent_graph(deps: AgentDeps) -> AgentGraph:
    """Build and compile the agent StateGraph with dependencies bound into every node."""
    builder = StateGraph(AgentState)

    # Nodes — each bound to deps via partial so LangGraph can call it with just the state.
    builder.add_node("classify_route", partial(classify_route, deps=deps))
    builder.add_node("kq1_owner", partial(kq1_owner, deps=deps))
    builder.add_node("kq2_contra", partial(kq2_contra, deps=deps))
    builder.add_node("kq3_blast", partial(kq3_blast, deps=deps))
    builder.add_node("kq4_change", partial(kq4_change, deps=deps))
    builder.add_node("general_search", partial(general_search, deps=deps))
    builder.add_node("get_entity_tool", partial(get_entity_tool, deps=deps))
    builder.add_node("neighbors_tool", partial(neighbors_tool, deps=deps))
    builder.add_node("enumerate_tool", partial(enumerate_tool, deps=deps))
    builder.add_node("aggregate_tool", partial(aggregate_tool, deps=deps))
    builder.add_node("unknown", partial(unknown, deps=deps))
    builder.add_node("empty_answer", partial(empty_answer, deps=deps))
    builder.add_node("synthesize_answer", partial(synthesize_answer, deps=deps))
    builder.add_node("verify_provenance", partial(verify_provenance, deps=deps))

    # Entry → routing.
    builder.add_edge(START, "classify_route")
    builder.add_conditional_edges("classify_route", _select_tool, list(_ROUTE_TO_NODE.values()))

    # Tool nodes that can produce citations → synthesise-or-empty.
    for tool in _SYNTHESIS_TOOLS:
        builder.add_conditional_edges(
            tool, _route_after_tool, {"synthesize_answer": "synthesize_answer", "empty_answer": "empty_answer"}
        )

    # Terminals.
    builder.add_edge("unknown", END)
    builder.add_edge("empty_answer", END)

    # Synthesis → verification → (retry | end).
    builder.add_edge("synthesize_answer", "verify_provenance")
    builder.add_conditional_edges(
        "verify_provenance", route_after_verify, {"synthesize_answer": "synthesize_answer", "end": END}
    )

    return builder.compile()
