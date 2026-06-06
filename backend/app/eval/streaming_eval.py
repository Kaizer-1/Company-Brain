"""Perceived-latency eval for the streaming endpoint (Phase 4B).

Measures time-to-first-synthesis-token and total stream time for a sample of questions.
This is a UX eval, not a behaviour eval — it answers "does streaming make the experience
feel faster?" not "is the answer correct?".

The agent's existing behaviour eval (phase-4a-agent-results.md) is the source of truth
for correctness; this eval provides complementary latency numbers.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog

from app.agent.config import AgentConfig
from app.agent.deps import AgentDeps
from app.agent.router import classify_route
from app.agent.synthesis import astream_synthesize

if TYPE_CHECKING:
    from app.agent.state import AgentState
from app.agent.tools import (
    general_search,
    kq1_owner,
    kq2_contra,
    kq3_blast,
    kq4_change,
    unknown,
)
from app.agent.verification import verify_provenance
from app.extraction.client import OpenRouterClient

log = structlog.get_logger(__name__)

_ROUTE_TO_TOOL: dict[str, Any] = {
    "kq1": kq1_owner,
    "kq2": kq2_contra,
    "kq3": kq3_blast,
    "kq4": kq4_change,
    "search": general_search,
    "unknown": unknown,
}


@dataclass
class LatencyResult:
    """Timing measurements for one question."""

    question: str
    route: str
    first_token_ms: float | None  # None if synthesis never started (unknown/empty)
    total_ms: float
    verified: bool
    error: str | None


@dataclass
class StreamingEvalReport:
    """Aggregated results from the perceived-latency eval."""

    results: list[LatencyResult] = field(default_factory=list)

    @property
    def mean_first_token_ms(self) -> float | None:
        vals = [r.first_token_ms for r in self.results if r.first_token_ms is not None]
        return sum(vals) / len(vals) if vals else None

    @property
    def mean_total_ms(self) -> float:
        return sum(r.total_ms for r in self.results) / len(self.results) if self.results else 0.0

    @property
    def p50_first_token_ms(self) -> float | None:
        vals = sorted(r.first_token_ms for r in self.results if r.first_token_ms is not None)
        if not vals:
            return None
        return vals[len(vals) // 2]


async def _time_one_question(
    question: str,
    *,
    neo4j_driver: Any,
    session_factory: Any,
    config: AgentConfig,
    client: OpenRouterClient,
) -> LatencyResult:
    """Run one question through the streaming path and record latency metrics."""
    t0 = time.monotonic()
    first_token_ms: float | None = None

    deps = AgentDeps(
        client=client,
        config=config,
        neo4j_driver=neo4j_driver,
        session_factory=session_factory,
    )
    state: AgentState = {"question": question, "retry_count": 0, "cost_usd": 0.0}

    route_result = await classify_route(state, deps=deps)
    state = {**state, **route_result}  # type: ignore[assignment]
    route = str(state.get("route", "search"))

    tool_fn = _ROUTE_TO_TOOL.get(route, general_search)
    tool_result = await tool_fn(state, deps=deps)
    state = {**state, **tool_result}  # type: ignore[assignment]

    available_ids: list[str] = state.get("available_event_ids", [])
    verified = True
    error = None

    if route != "unknown" and available_ids:
        state = {**state, "retry_count": 0}  # type: ignore[assignment]

        async def on_token(chunk: str) -> None:
            nonlocal first_token_ms
            if first_token_ms is None:
                first_token_ms = (time.monotonic() - t0) * 1000

        synth_result = await astream_synthesize(state, deps=deps, on_token=on_token)
        state = {**state, **synth_result}  # type: ignore[assignment]

        verify_result = await verify_provenance(state, deps=deps)
        state = {**state, **verify_result}  # type: ignore[assignment]
        verified = bool(state.get("verified", False))
        error = state.get("error")

    total_ms = (time.monotonic() - t0) * 1000
    return LatencyResult(
        question=question,
        route=route,
        first_token_ms=first_token_ms,
        total_ms=total_ms,
        verified=verified,
        error=str(error) if error else None,
    )


async def run_streaming_eval(
    questions: list[str],
    *,
    neo4j_driver: Any,
    session_factory: Any,
    config: AgentConfig | None = None,
) -> StreamingEvalReport:
    """Run the perceived-latency eval against a list of questions."""
    cfg = config or AgentConfig()
    report = StreamingEvalReport()

    async with OpenRouterClient() as client:
        for q in questions:
            log.info("streaming_eval_question", question=q[:60])
            result = await _time_one_question(
                q,
                neo4j_driver=neo4j_driver,
                session_factory=session_factory,
                config=cfg,
                client=client,
            )
            report.results.append(result)
            log.info(
                "streaming_eval_result",
                route=result.route,
                first_token_ms=result.first_token_ms,
                total_ms=result.total_ms,
                verified=result.verified,
            )

    return report


def render_streaming_report(report: StreamingEvalReport, questions_source: str = "") -> str:
    """Render the eval results as a Markdown document."""
    lines: list[str] = [
        "# Phase 4B Streaming Eval — Perceived-Latency Results",
        "",
        "> **Honest framing**: total end-to-end latency is unchanged from Phase 4A (two",
        "> sequential LLM calls are the floor). What changes is *perceived* latency —",
        "> the user sees the route badge and tool output before synthesis starts, then",
        "> tokens stream in rather than the page sitting blank. This eval measures",
        "> **time-to-first-synthesis-token** as the UX-relevant metric.",
        "",
    ]
    if questions_source:
        lines += [f"Questions source: `{questions_source}`", ""]

    lines += ["## Summary", ""]

    mean_ft = report.mean_first_token_ms
    p50_ft = report.p50_first_token_ms
    mean_total = report.mean_total_ms

    lines += [
        "| Metric | Value |",
        "|--------|-------|",
        f"| Questions | {len(report.results)} |",
        f"| Mean time-to-first-token (ms) | {mean_ft:.0f} |" if mean_ft else "| Mean time-to-first-token (ms) | — |",
        f"| P50 time-to-first-token (ms) | {p50_ft:.0f} |" if p50_ft else "| P50 time-to-first-token (ms) | — |",
        f"| Mean total time (ms) | {mean_total:.0f} |",
        "",
        "**Target**: mean time-to-first-token ≤ 3000ms.",
        "",
    ]

    if mean_ft is not None:
        if mean_ft <= 3000:
            lines.append(f"✓ **Target met** — mean {mean_ft:.0f}ms ≤ 3000ms.")
        else:
            lines.append(f"✗ **Target missed** — mean {mean_ft:.0f}ms > 3000ms.")
    lines.append("")

    lines += ["## Per-Question Results", ""]
    lines += ["| Route | First token (ms) | Total (ms) | Verified | Error | Question |"]
    lines += ["|-------|-----------------|------------|----------|-------|----------|"]

    for r in report.results:
        ft = f"{r.first_token_ms:.0f}" if r.first_token_ms is not None else "—"
        lines.append(
            f"| {r.route} | {ft} | {r.total_ms:.0f} | {r.verified} | {r.error or ''} | {r.question[:50]} |"
        )

    lines += [
        "",
        "## Discussion",
        "",
        "Total latency is the sum of route classification + tool execution + synthesis + "
        "verification — unchanged by streaming. The UX improvement is that the user sees "
        "the route badge appear ~2s into the request, then token output begins streaming, "
        "rather than a blank screen for the full duration.",
        "",
        "First-token time = route + tool stages, which is typically 2–3s for KQ routes "
        "(Cypher is fast) and ~2.5s for search (vector query + embedding). Unknown routes "
        "never reach synthesis so have no first-token time.",
    ]

    return "\n".join(lines)
