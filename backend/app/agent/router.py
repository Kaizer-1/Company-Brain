"""The ``classify_route`` node (Phase 4A).

Routing-before-generation is the agent's load-bearing safety decision (ADR 0024). Every
question first passes through this single LLM classification, constrained to the six-value
route enum. The classifier cannot emit arbitrary text — its output is validated into a
``RouteDecision`` — and if the call or validation fails, it falls back to general
``search`` rather than to "I don't know" (CLAUDE.md locked decision: routing failure must
never surface as a refusal).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import structlog

from app.agent.llm import AgentLLMError, complete_to_model
from app.agent.schemas import RouteDecision

if TYPE_CHECKING:
    from app.agent.deps import AgentDeps
    from app.agent.state import AgentState

log = structlog.get_logger(__name__)


def _build_messages(prompt_template: str, question: str) -> list[dict[str, str]]:
    """Render the router prompt with the question substituted in.

    The template carries the full system instruction + few-shot examples; we send it as a
    single user message (OpenRouter chat format) with the question interpolated. ``replace``
    rather than ``str.format`` because the template contains literal ``{...}`` JSON braces.
    """
    rendered = prompt_template.replace("{question}", question)
    return [{"role": "user", "content": rendered}]


async def classify_route(state: AgentState, *, deps: AgentDeps) -> dict[str, object]:
    """Classify the question into one of six routes via a single constrained LLM call.

    On any failure (LLM call, malformed JSON, schema mismatch) the node logs and falls
    back to ``route="search"`` with empty ``tool_input`` — general retrieval is always a
    safe default because every question reaching the agent is assumed to be about the graph.
    """
    t0 = time.monotonic()
    question = state["question"]
    template = deps.config.load_prompt(deps.config.router_prompt_path)
    messages = _build_messages(template, question)

    cost = state.get("cost_usd", 0.0)
    try:
        decision, call_cost = await complete_to_model(
            deps.client,
            model=deps.config.router_model,
            messages=messages,
            schema=RouteDecision,
            temperature=deps.config.router_temperature,
            max_tokens=deps.config.router_max_tokens,
        )
        cost += call_cost
        route = decision.route
        reasoning = decision.reasoning
        tool_input = decision.tool_input
    except AgentLLMError as exc:
        log.warning("router_fallback_to_search", stage=exc.stage, error=str(exc)[:200])
        route = "search"
        reasoning = "Router LLM call failed; falling back to general search."
        tool_input = {}

    elapsed_ms = (time.monotonic() - t0) * 1000
    timings = {**state.get("timings_ms", {}), "classify_route": round(elapsed_ms, 1)}

    log.info("route_classified", route=route, question_len=len(question))
    return {
        "route": route,
        "route_reasoning": reasoning,
        "tool_input": tool_input,
        "timings_ms": timings,
        "cost_usd": cost,
    }
