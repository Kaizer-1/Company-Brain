"""The ``synthesize_answer`` node (Phase 4A); ``astream_synthesize`` added in Phase 4B.

Takes the tool output and writes a natural-language answer in which every factual claim
cites a Postgres event UUID. One LLM call, constrained to ``AnswerWithCitations`` — the
``min_length=1`` citation constraint is the first guard against an uncited answer; the
``verify_provenance`` node (verification.py) is the second.

On the first attempt this node uses ``synthesis.txt``. When the verifier sends control back
(``retry_count > 0``) it uses ``synthesis_strict.txt``, which lists the legal event ids and
explains that the previous attempt failed verification. On LLM failure it emits a graceful
fallback answer rather than crashing, so a question always gets *a* response.

Phase 4B adds ``astream_synthesize``: same logic, but the LLM response is streamed token
by token via an ``on_token`` callback, allowing the API layer to forward tokens over SSE
while still validating the full response at the end.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

import structlog
from pydantic import ValidationError

from app.agent.llm import AgentLLMError, complete_to_model
from app.agent.schemas import AnswerWithCitations
from app.extraction.client import CompletionResult, OpenRouterError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from app.agent.deps import AgentDeps
    from app.agent.state import AgentState

log = structlog.get_logger(__name__)

# Returned when the synthesis LLM call itself fails (not a grounding failure). Honest about
# the failure and carries no citations — the verifier will mark it unverified.
_SYNTHESIS_FAILED_ANSWER = (
    "I retrieved relevant data from the graph but couldn't compose a grounded answer just "
    "now. Please try rephrasing the question."
)

_FENCE_PREFIXES = ("```json", "```JSON", "```")


def _strip_fences(text: str) -> str:
    """Remove a leading/trailing markdown code fence if the model added one."""
    stripped = text.strip()
    for prefix in _FENCE_PREFIXES:
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix):]
            break
    if stripped.endswith("```"):
        stripped = stripped[:-3]
    return stripped.strip()


def build_synthesis_messages(template: str, state: AgentState) -> list[dict[str, str]]:
    """Render a synthesis prompt with the question, tool output, and legal event ids."""
    tool_output = json.dumps(state.get("tool_output"), indent=2, default=str)
    available = "\n".join(state.get("available_event_ids", [])) or "(none)"
    rendered = (
        template.replace("{question}", state["question"])
        .replace("{tool_output}", tool_output)
        .replace("{available_event_ids}", available)
    )
    return [{"role": "user", "content": rendered}]


def _parse_synthesis_json(full_text: str) -> dict[str, object]:
    """Fence-strip, parse, and validate accumulated synthesis text. Returns a state-slice dict."""
    candidate = _strip_fences(full_text)
    if not candidate:
        raise AgentLLMError("empty synthesis response", stage="json")
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise AgentLLMError(f"synthesis response was not valid JSON: {exc}", stage="json") from exc
    try:
        result = AnswerWithCitations.model_validate(data)
    except ValidationError as exc:
        raise AgentLLMError(
            f"synthesis response did not match AnswerWithCitations: {exc}", stage="schema"
        ) from exc
    return {"answer": result.answer, "citations": result.citations, "confidence": result.confidence}


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
    messages = build_synthesis_messages(template, state)

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


async def astream_synthesize(
    state: AgentState,
    *,
    deps: AgentDeps,
    on_token: Callable[[str], Awaitable[None]],
) -> dict[str, object]:
    """Streaming variant of ``synthesize_answer``.

    Calls the LLM via ``astream_completion``, invoking ``on_token`` for each text chunk
    so the caller (the SSE endpoint) can forward tokens in real time. After the stream
    ends, the full accumulated text is validated against ``AnswerWithCitations`` and the
    same dict shape as ``synthesize_answer`` is returned. Falls back gracefully on any
    error so the caller always gets a result to emit.
    """
    t0 = time.monotonic()
    retrying = state.get("retry_count", 0) > 0
    prompt_path = (
        deps.config.synthesis_strict_prompt_path if retrying else deps.config.synthesis_prompt_path
    )
    template = deps.config.load_prompt(prompt_path)
    messages = build_synthesis_messages(template, state)

    cost = state.get("cost_usd", 0.0)
    completion_results: list[CompletionResult] = []

    try:
        full_text = ""
        async for chunk in deps.client.astream_completion(
            model=deps.config.synthesis_model,
            messages=messages,
            temperature=deps.config.synthesis_temperature,
            max_tokens=deps.config.synthesis_max_tokens,
            on_complete=completion_results.append,
        ):
            full_text += chunk
            await on_token(chunk)

        if completion_results:
            cost += completion_results[0].cost_usd

        parsed = _parse_synthesis_json(full_text)
        answer = str(parsed["answer"])
        citations = list(parsed["citations"])  # type: ignore[arg-type]
        confidence = str(parsed["confidence"])

    except (AgentLLMError, OpenRouterError) as exc:
        stage = exc.stage if isinstance(exc, AgentLLMError) else "call"
        log.warning("astream_synthesize_failed", stage=stage, retrying=retrying, error=str(exc)[:200])
        answer = _SYNTHESIS_FAILED_ANSWER
        citations = []
        confidence = "low"

    log.info("answer_astreamed", retrying=retrying, citations=len(citations))
    return {
        "answer": answer,
        "citations": citations,
        "confidence": confidence,
        "timings_ms": {**state.get("timings_ms", {}), "synthesize_answer": round((time.monotonic() - t0) * 1000, 1)},
        "cost_usd": cost,
    }
