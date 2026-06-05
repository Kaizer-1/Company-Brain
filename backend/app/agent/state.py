"""Agent state machine types (Phase 4A).

``AgentState`` is the TypedDict threaded through every LangGraph node. ``total=False`` so
nodes write only the keys they own; downstream nodes read what upstream produced. The
route enum is the load-bearing contract — it both selects the conditional edge and is
echoed in the API response.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

# The five execution paths plus the terminal "unknown". Kept as a Literal (not a Python
# enum) so it serialises cleanly and the router's Pydantic model can constrain to it
# directly. KQ routes map 1:1 to the four killer queries; "search" is general retrieval.
RouteLiteral = Literal["kq1", "kq2", "kq3", "kq4", "search", "unknown"]

ROUTE_VALUES: tuple[RouteLiteral, ...] = ("kq1", "kq2", "kq3", "kq4", "search", "unknown")


class AgentState(TypedDict, total=False):
    """State threaded through the LangGraph nodes. ``total=False``: each node writes its keys."""

    question: str  # the user's NL question (set at entry)
    route: RouteLiteral  # classifier decision; selects the tool edge
    route_reasoning: str  # the classifier's brief justification (shown in the trace)
    tool_input: dict[str, Any]  # parameters the classifier extracted for the chosen tool
    tool_output: dict[str, Any] | None  # raw tool result with provenance
    available_event_ids: list[str]  # flat set of citable event UUIDs from tool_output
    answer: str  # synthesised NL answer (with inline [evt:UUID] markers)
    citations: list[str]  # event_ids referenced in the answer
    confidence: Literal["high", "medium", "low"]  # synthesiser's self-reported confidence
    verified: bool  # provenance check passed
    retry_count: int  # synthesis retries used
    error: str | None  # set if the agent gives up (e.g. "provenance_failed")
    timings_ms: dict[str, float]  # per-node timing for debug + UI
    cost_usd: float  # accumulated LLM dollar cost across router + synthesis calls
