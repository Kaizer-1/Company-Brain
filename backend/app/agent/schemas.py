"""Agent API + LLM-boundary schemas (Phase 4A).

Two groups of models:

* **LLM-boundary models** (``RouteDecision``, ``AnswerWithCitations``) — the validated
  shapes the router and synthesis LLM calls must produce. Pydantic constraints are the
  first line of defence: an empty citation list or an out-of-range enum fails validation
  and triggers a retry rather than reaching the user.
* **HTTP models** (``AskRequest``, ``AskResponse``, ``Citation``, ``AgentStateDump``) —
  the request/response contract for ``POST /api/ask``. Citations are *resolved* server-side
  so the frontend never has to make N follow-up requests.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# RouteLiteral is a Pydantic *field type* on RouteDecision/AskResponse/AgentStateDump, so it
# must be importable at runtime (not under TYPE_CHECKING) for model building to succeed.
from app.agent.state import RouteLiteral  # noqa: TC001

# ---------------------------------------------------------------------------
# LLM-boundary models
# ---------------------------------------------------------------------------


class RouteDecision(BaseModel):
    """The route classifier's structured output (validated post-hoc from json_object).

    ``tool_input`` is the classifier's best-effort parameter extraction — e.g.
    ``{"service": "payments-api"}`` for a blast-radius question. Tool nodes validate it
    against their own needs and fall through to ``unknown`` if it is unusable.
    """

    route: RouteLiteral
    reasoning: str = Field(min_length=10, max_length=300)
    tool_input: dict[str, Any] = Field(default_factory=dict)


class AnswerWithCitations(BaseModel):
    """The synthesis LLM call's structured output.

    ``citations`` must be non-empty: the ``min_length=1`` constraint rejects an answer that
    cites nothing before it ever reaches ``verify_provenance``. ``confidence`` is the
    model's self-report, surfaced in the UI but never used to gate the answer.
    """

    answer: str = Field(min_length=20, max_length=2000)
    citations: list[str] = Field(min_length=1)
    confidence: Literal["high", "medium", "low"]


# ---------------------------------------------------------------------------
# HTTP models
# ---------------------------------------------------------------------------


class AskRequest(BaseModel):
    """Request body for POST /api/ask."""

    question: str = Field(min_length=3, max_length=500)
    debug: bool = False  # if true, include the full AgentState dump in the response


class Citation(BaseModel):
    """A resolved citation: the event UUID plus enough of the source row to render it."""

    event_id: str
    source_kind: str  # SourceType value: "doc" | "slack_message"
    source_ref: str  # source_external_id from the events row
    snippet: str  # first 200 chars of the event content


class AgentStateDump(BaseModel):
    """Debug-only snapshot of the terminal AgentState (populated when request.debug)."""

    question: str
    route: RouteLiteral
    route_reasoning: str
    tool_input: dict[str, Any]
    available_event_ids: list[str]
    answer: str
    citations: list[str]
    verified: bool
    retry_count: int
    error: str | None
    timings_ms: dict[str, float]
    cost_usd: float


class AskResponse(BaseModel):
    """Response body for POST /api/ask. Citations are resolved server-side."""

    answer: str
    citations: list[Citation]
    route: RouteLiteral
    confidence: Literal["high", "medium", "low"]
    timings_ms: dict[str, float]
    error: str | None = None
    debug: AgentStateDump | None = None
