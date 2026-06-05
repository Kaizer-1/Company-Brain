"""FastAPI router for POST /api/ask (Phase 4A).

The headline endpoint: a natural-language question in, a grounded answer with resolved
citations out. Mirrors the search router's pattern — it pulls DB handles off ``app.state``
and delegates all logic to ``run_agent``. Returns a single JSON response (streaming is out
of scope for 4A; CLAUDE.md locked decision).
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Request

from app.agent.runner import run_agent
from app.agent.schemas import AskRequest, AskResponse

router = APIRouter(prefix="/api/ask", tags=["agent"])
log = structlog.get_logger(__name__)


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
