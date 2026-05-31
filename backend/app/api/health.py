"""Health check endpoint.

Returns the connectivity status of Neo4j and Postgres. Both databases
are probed on every request so status reflects live state, not startup
state. Each response carries the request_id injected by RequestIDMiddleware.
"""

import structlog
from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()

log = structlog.get_logger(__name__)


class HealthResponse(BaseModel):
    """Shape returned by GET /health."""

    status: str
    neo4j: str
    postgres: str


@router.get("/health", response_model=HealthResponse)
async def health_check(request: Request) -> HealthResponse:
    """Probe Neo4j and Postgres and return their connectivity status."""
    neo4j_ok: bool = await request.app.state.neo4j.verify_connectivity()
    postgres_ok: bool = await request.app.state.postgres.verify_connectivity()
    overall = "ok" if neo4j_ok and postgres_ok else "degraded"
    log.info(
        "health_check",
        neo4j=neo4j_ok,
        postgres=postgres_ok,
        status=overall,
    )
    return HealthResponse(
        status=overall,
        neo4j="connected" if neo4j_ok else "disconnected",
        postgres="connected" if postgres_ok else "disconnected",
    )
