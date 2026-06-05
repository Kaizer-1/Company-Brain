"""Top-level agent entry point (Phase 4A).

``run_agent`` is the single function the API endpoint (and the eval) call. It builds the
dependency bundle, compiles the graph, runs the question through it, resolves every citation
UUID into a full ``Citation`` (so the frontend needs no follow-up requests), and packages
the result as an ``AskResponse``.

The OpenRouter client is created per call and closed in a ``finally`` unless one is injected
(the eval injects a shared client to amortise the connection; tests inject a fake).
"""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING

import structlog

from app.agent.config import AgentConfig
from app.agent.deps import AgentDeps
from app.agent.graph import build_agent_graph
from app.agent.schemas import AgentStateDump, AskResponse, Citation
from app.db.repositories.events import EventRepository
from app.extraction.client import OpenRouterClient

if TYPE_CHECKING:
    from neo4j import AsyncDriver
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.agent.state import AgentState

log = structlog.get_logger(__name__)

_SNIPPET_CHARS = 200


async def _resolve_citations(
    session_factory: async_sessionmaker[AsyncSession], event_ids: list[str]
) -> list[Citation]:
    """Look up each cited event UUID and build a resolved Citation. Skips unknown ids."""
    if not event_ids:
        return []
    citations: list[Citation] = []
    async with session_factory() as session:
        repo = EventRepository(session)
        for raw in event_ids:
            try:
                event = await repo.get_by_id(uuid.UUID(raw))
            except (ValueError, TypeError):
                continue
            if event is None:
                continue
            citations.append(
                Citation(
                    event_id=str(event.id),
                    source_kind=event.source_type.value,
                    source_ref=event.source_external_id,
                    snippet=event.content[:_SNIPPET_CHARS],
                )
            )
    return citations


def _to_dump(state: AgentState) -> AgentStateDump:
    """Project the terminal state into the debug dump model."""
    return AgentStateDump(
        question=state.get("question", ""),
        route=state.get("route", "unknown"),
        route_reasoning=state.get("route_reasoning", ""),
        tool_input=state.get("tool_input", {}),
        available_event_ids=state.get("available_event_ids", []),
        answer=state.get("answer", ""),
        citations=state.get("citations", []),
        verified=state.get("verified", False),
        retry_count=state.get("retry_count", 0),
        error=state.get("error"),
        timings_ms=state.get("timings_ms", {}),
        cost_usd=state.get("cost_usd", 0.0),
    )


async def run_agent(
    question: str,
    *,
    neo4j_driver: AsyncDriver,
    session_factory: async_sessionmaker[AsyncSession],
    debug: bool = False,
    config: AgentConfig | None = None,
    client: OpenRouterClient | None = None,
) -> AskResponse:
    """Run one question through the agent graph and return a resolved ``AskResponse``."""
    t0 = time.monotonic()
    cfg = config or AgentConfig()
    owns_client = client is None
    llm = client or OpenRouterClient()
    try:
        deps = AgentDeps(
            client=llm, config=cfg, neo4j_driver=neo4j_driver, session_factory=session_factory
        )
        graph = build_agent_graph(deps)
        initial: AgentState = {"question": question, "retry_count": 0, "cost_usd": 0.0}
        final: AgentState = await graph.ainvoke(initial)  # type: ignore[assignment]
    finally:
        if owns_client:
            await llm.aclose()

    citations = await _resolve_citations(session_factory, final.get("citations", []))

    timings = dict(final.get("timings_ms", {}))
    timings["total"] = round((time.monotonic() - t0) * 1000, 1)

    log.info(
        "agent_run_done",
        route=final.get("route"),
        verified=final.get("verified"),
        citations=len(citations),
        cost_usd=round(final.get("cost_usd", 0.0), 6),
        total_ms=timings["total"],
    )

    return AskResponse(
        answer=final.get("answer", ""),
        citations=citations,
        route=final.get("route", "unknown"),
        confidence=final.get("confidence", "low"),
        timings_ms=timings,
        error=final.get("error"),
        debug=_to_dump(final) if debug else None,
    )
