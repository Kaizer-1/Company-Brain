"""The ``synthesize_answer`` node (Phase 4A).

Takes the tool output and writes a natural-language answer in which every factual claim
cites a Postgres event UUID. One LLM call, constrained to ``AnswerWithCitations`` — the
``min_length=1`` citation constraint is the first guard against an uncited answer; the
``verify_provenance`` node (verification.py) is the second.

On the first attempt this node uses ``synthesis.txt``. When the verifier sends control back
(``retry_count > 0``) it uses ``synthesis_strict.txt``, which lists the legal event ids and
explains that the previous attempt failed verification. On LLM failure it emits a graceful
fallback answer rather than crashing, so a question always gets *a* response.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

import structlog

from app.agent.llm import AgentLLMError, complete_to_model
from app.agent.schemas import AnswerWithCitations

if TYPE_CHECKING:
    from app.agent.deps import AgentDeps
    from app.agent.state import AgentState

log = structlog.get_logger(__name__)

# Returned when the synthesis LLM call itself fails (not a grounding failure). Honest about
# the failure and carries no citations — the verifier will mark it unverified.
_SYNTHESIS_FAILED_ANSWER = (
    "I retrieved relevant data from the graph but couldn't compose a grounded answer just "
    "now. Please try rephrasing the question."
)


def _build_messages(template: str, state: AgentState) -> list[dict[str, str]]:
    """Render a synthesis prompt with the question, tool output, and legal event ids."""
    tool_output = json.dumps(state.get("tool_output"), indent=2, default=str)
    available = "\n".join(state.get("available_event_ids", [])) or "(none)"
    rendered = (
        template.replace("{question}", state["question"])
        .replace("{tool_output}", tool_output)
        .replace("{available_event_ids}", available)
    )
    return [{"role": "user", "content": rendered}]


async def synthesize_answer(state: AgentState, *, deps: AgentDeps) -> dict[str, object]:
    """Generate a grounded NL answer with inline [evt:UUID] citations.

    Uses the strict prompt when retrying (``retry_count > 0``). Always returns ``answer``,
    ``citations``, and ``confidence``; on LLM failure returns a graceful fallback with no
    citations (the verifier then records it as unverified).
    """
    t0 = time.monotonic()
    retrying = state.get("retry_count", 0) > 0
    prompt_path = (
        deps.config.synthesis_strict_prompt_path if retrying else deps.config.synthesis_prompt_path
    )
    template = deps.config.load_prompt(prompt_path)
    messages = _build_messages(template, state)

    cost = state.get("cost_usd", 0.0)
    try:
        result, call_cost = await complete_to_model(
            deps.client,
            model=deps.config.synthesis_model,
            messages=messages,
            schema=AnswerWithCitations,
            temperature=deps.config.synthesis_temperature,
            max_tokens=deps.config.synthesis_max_tokens,
        )
        cost += call_cost
        answer = result.answer
        citations = result.citations
        confidence = result.confidence
    except AgentLLMError as exc:
        log.warning("synthesis_failed", stage=exc.stage, retrying=retrying, error=str(exc)[:200])
        answer = _SYNTHESIS_FAILED_ANSWER
        citations = []
        confidence = "low"

    log.info("answer_synthesized", retrying=retrying, citations=len(citations))
    return {
        "answer": answer,
        "citations": citations,
        "confidence": confidence,
        "timings_ms": {**state.get("timings_ms", {}), "synthesize_answer": round((time.monotonic() - t0) * 1000, 1)},
        "cost_usd": cost,
    }
