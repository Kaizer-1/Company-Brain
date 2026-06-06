"""FastAPI router for POST /api/ask and POST /api/ask/stream (Phases 4A + 4B).

``POST /api/ask`` — the original JSON endpoint, unchanged from Phase 4A.
``POST /api/ask/stream`` — Phase 4B SSE endpoint: same agent logic, but the synthesis
step is streamed token by token and per-stage progress events are emitted.

Both endpoints share the same ``AskRequest`` body. The streaming endpoint never
replaces the JSON one; the frontend selects which to call via ``USE_STREAMING``.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.agent.config import AgentConfig
from app.agent.deps import AgentDeps
from app.agent.router import classify_route
from app.agent.runner import _resolve_citations, run_agent  # noqa: PLC2701 – shared private
from app.agent.schemas import AskRequest, AskResponse
from app.agent.streaming import (
    EVT_COMPLETE,
    EVT_ERROR,
    EVT_ROUTE,
    EVT_SYNTHESIS_DONE,
    EVT_SYNTHESIS_START,
    EVT_SYNTHESIS_TOKEN,
    EVT_TOOL_DONE,
    EVT_TOOL_START,
    EVT_VERIFY_DONE,
    EVT_VERIFY_START,
    format_sse,
)
from app.agent.synthesis import astream_synthesize
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

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable

    from app.agent.state import AgentState

router = APIRouter(prefix="/api/ask", tags=["agent"])
log = structlog.get_logger(__name__)

# Maps route enum values to tool node callables.
_ROUTE_TO_TOOL: dict[str, Callable[..., object]] = {
    "kq1": kq1_owner,
    "kq2": kq2_contra,
    "kq3": kq3_blast,
    "kq4": kq4_change,
    "search": general_search,
    "unknown": unknown,
}


def _make_on_token(q: asyncio.Queue[str | None]) -> Callable[[str], Awaitable[None]]:
    """Factory that binds a specific queue so each synthesis loop iteration gets its own."""
    async def on_token(chunk: str) -> None:
        await q.put(chunk)
    return on_token


@router.post(
    "",
    response_model=AskResponse,
    summary="Ask the agent a natural-language question about the company graph.",
)
async def ask(request: Request, body: AskRequest) -> AskResponse:
    """Route the question to a typed killer query or semantic search, synthesise a grounded
    answer, verify every citation against the graph's provenance, and return it resolved.

    Set ``debug=true`` to include the full agent trace (route, reasoning, per-node timings,
    retry count) in the response for inspection.
    """
    log.info("ask_request", question_len=len(body.question), debug=body.debug)
    return await run_agent(
        body.question,
        neo4j_driver=request.app.state.neo4j.driver,
        session_factory=request.app.state.session_factory,
        debug=body.debug,
    )


@router.post(
    "/stream",
    summary="Ask the agent a question; stream per-stage SSE events and synthesis tokens.",
)
async def ask_stream(request: Request, body: AskRequest) -> StreamingResponse:
    """SSE variant of POST /api/ask.

    Emits a ``route`` event after classification, ``tool_start``/``tool_done`` around
    tool execution, ``synthesis_token`` events for each LLM output token, and a final
    ``complete`` event carrying the full resolved answer. If verification fails and the
    agent retries, additional ``synthesis_start`` / ``synthesis_token`` / ``verify_*``
    events are emitted for each retry pass; the frontend renders these as "Refining...".

    Clients should use ``fetch`` + a ``ReadableStream`` reader (not ``EventSource``,
    which does not support POST bodies; see ADR 0026).
    """
    neo4j_driver = request.app.state.neo4j.driver
    session_factory = request.app.state.session_factory
    log.info("ask_stream_request", question_len=len(body.question))

    async def event_stream() -> AsyncGenerator[str, None]:
        t0 = time.monotonic()
        cfg = AgentConfig()
        llm = OpenRouterClient()
        try:
            deps = AgentDeps(
                client=llm,
                config=cfg,
                neo4j_driver=neo4j_driver,
                session_factory=session_factory,
            )
            state: AgentState = {"question": body.question, "retry_count": 0, "cost_usd": 0.0}

            # ── Stage 1: classify route ────────────────────────────────────────
            route_result = await classify_route(state, deps=deps)
            state = {**state, **route_result}  # type: ignore[assignment]
            yield format_sse(EVT_ROUTE, {
                "route": state.get("route", "search"),
                "reasoning": state.get("route_reasoning", ""),
                "tool_input": state.get("tool_input", {}),
            })

            # ── Stage 2: tool execution ────────────────────────────────────────
            route = str(state.get("route", "search"))
            tool_fn = _ROUTE_TO_TOOL.get(route, general_search)

            yield format_sse(EVT_TOOL_START, {
                "tool": route,
                "params": state.get("tool_input", {}),
            })
            tool_result = await tool_fn(state, deps=deps)
            state = {**state, **tool_result}  # type: ignore[assignment]

            available_ids: list[str] = state.get("available_event_ids", [])
            yield format_sse(EVT_TOOL_DONE, {
                "tool_output_summary": f"{len(available_ids)} events",
                "timings_ms": state.get("timings_ms", {}),
            })

            # ── Terminals: unknown or empty result ────────────────────────────
            if route == "unknown" or not available_ids:
                citations = await _resolve_citations(session_factory, state.get("citations", []))
                timings = dict(state.get("timings_ms", {}))
                timings["total"] = round((time.monotonic() - t0) * 1000, 1)
                yield format_sse(EVT_COMPLETE, {
                    "answer": state.get("answer", ""),
                    "citations": [c.model_dump() for c in citations],
                    "route": state.get("route", route),
                    "confidence": state.get("confidence", "low"),
                    "timings_ms": timings,
                    "error": state.get("error"),
                    "debug": None,
                })
                return

            # ── Stages 3 + 4: synthesis → verify loop (with optional retry) ───
            retry_count = 0
            while retry_count <= cfg.max_synthesis_retries:
                state = {**state, "retry_count": retry_count}  # type: ignore[assignment]

                yield format_sse(EVT_SYNTHESIS_START, {"retry": retry_count > 0})

                # Bridge on_token callback → async queue → SSE yield.
                token_queue: asyncio.Queue[str | None] = asyncio.Queue()
                on_token = _make_on_token(token_queue)

                synth_task: asyncio.Task[dict[str, object]] = asyncio.create_task(
                    astream_synthesize(state, deps=deps, on_token=on_token)
                )
                # Sentinel ensures the reader loop exits even if synthesis throws.
                synth_task.add_done_callback(lambda _, q=token_queue: q.put_nowait(None))

                while True:
                    chunk = await token_queue.get()
                    if chunk is None:
                        break
                    yield format_sse(EVT_SYNTHESIS_TOKEN, {"text": chunk})

                synth_state = await synth_task
                state = {**state, **synth_state}  # type: ignore[assignment]

                yield format_sse(EVT_SYNTHESIS_DONE, {
                    "answer_final": state.get("answer", ""),
                    "citations_raw": state.get("citations", []),
                })

                yield format_sse(EVT_VERIFY_START, {})
                verify_result = await verify_provenance(state, deps=deps)
                state = {**state, **verify_result}  # type: ignore[assignment]

                verified = bool(state.get("verified"))
                yield format_sse(EVT_VERIFY_DONE, {
                    "verified": verified,
                    "retry_count": state.get("retry_count", retry_count),
                })

                if verified or state.get("error") is not None:
                    break
                retry_count += 1

            # ── Stage 5: resolve citations + complete event ───────────────────
            citations = await _resolve_citations(session_factory, state.get("citations", []))
            timings = dict(state.get("timings_ms", {}))
            timings["total"] = round((time.monotonic() - t0) * 1000, 1)
            yield format_sse(EVT_COMPLETE, {
                "answer": state.get("answer", ""),
                "citations": [c.model_dump() for c in citations],
                "route": state.get("route", route),
                "confidence": state.get("confidence", "low"),
                "timings_ms": timings,
                "error": state.get("error"),
                "debug": None,
            })

        except Exception as exc:  # noqa: BLE001 – surface any error to the client as SSE
            log.exception("ask_stream_error", error=str(exc)[:500])
            yield format_sse(EVT_ERROR, {"error": str(exc)[:500], "stage": "unknown"})
        finally:
            await llm.aclose()

    return StreamingResponse(event_stream(), media_type="text/event-stream")
