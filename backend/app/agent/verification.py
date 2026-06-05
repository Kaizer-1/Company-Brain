"""The ``verify_provenance`` node (Phase 4A; ADR 0025).

A pure-Python check — no LLM call — that is the agent's anti-hallucination guarantee. It
extracts every ``[evt:UUID]`` marker from the synthesised answer and confirms:

1. at least one citation exists;
2. every cited UUID actually appears in the tool's provenance
   (``available_event_ids``, derived from the tool output).

If verification fails it increments ``retry_count`` and (while retries remain) hands control
back to ``synthesize_answer`` with the stricter prompt. After ``max_synthesis_retries`` it
gives up, sets ``error="provenance_failed"``, and returns the best-effort answer with a
warning flag. ``state["citations"]`` is always reconciled to exactly the inline references —
the inline markers are the source of truth, not the LLM's separate citations array.
"""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING

import structlog

# AgentState must be importable at runtime: LangGraph calls get_type_hints() on the
# conditional-edge function ``route_after_verify`` at graph-compile time, which evaluates its
# ``state: AgentState`` annotation. Under TYPE_CHECKING it would raise NameError at compile.
from app.agent.state import AgentState  # noqa: TC001

if TYPE_CHECKING:
    from app.agent.deps import AgentDeps

log = structlog.get_logger(__name__)

# Matches [evt:<uuid>] markers. The capture is permissive (anything up to the closing
# bracket, trimmed) so a malformed UUID is *caught* by the membership check below rather
# than silently skipped by an over-strict regex — a fabricated id must fail verification.
_EVT_PATTERN = re.compile(r"\[evt:\s*([^\]]+?)\s*\]")


def _extract_inline_ids(answer: str) -> list[str]:
    """Return the de-duplicated, order-stable list of event ids cited inline in the answer."""
    seen: list[str] = []
    for match in _EVT_PATTERN.findall(answer):
        if match and match not in seen:
            seen.append(match)
    return seen


async def verify_provenance(state: AgentState, *, deps: AgentDeps) -> dict[str, object]:
    """Verify every inline citation against the tool's provenance; drive the retry loop."""
    t0 = time.monotonic()
    answer = state.get("answer", "")
    available = set(state.get("available_event_ids", []))
    inline_ids = _extract_inline_ids(answer)

    has_citation = len(inline_ids) > 0
    all_grounded = all(eid in available for eid in inline_ids)
    fabricated = [eid for eid in inline_ids if eid not in available]
    verified = has_citation and all_grounded

    timings = {**state.get("timings_ms", {}), "verify_provenance": round((time.monotonic() - t0) * 1000, 1)}

    if verified:
        log.info("provenance_verified", citations=len(inline_ids))
        return {"verified": True, "citations": inline_ids, "error": None, "timings_ms": timings}

    retry_count = state.get("retry_count", 0) + 1
    exhausted = retry_count > deps.config.max_synthesis_retries
    log.warning(
        "provenance_failed",
        has_citation=has_citation,
        fabricated=fabricated[:5],
        retry_count=retry_count,
        exhausted=exhausted,
    )

    out: dict[str, object] = {
        "verified": False,
        "citations": inline_ids,
        "retry_count": retry_count,
        "timings_ms": timings,
    }
    if exhausted:
        out["error"] = "provenance_failed"
    return out


def route_after_verify(state: AgentState) -> str:
    """Conditional edge: loop back to synthesis on a recoverable verification failure.

    Returns ``"synthesize_answer"`` to retry, or ``"end"`` when the answer is verified or
    the retry budget is spent (``error`` set by ``verify_provenance``).
    """
    if state.get("verified") or state.get("error") is not None:
        return "end"
    return "synthesize_answer"
