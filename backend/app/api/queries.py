"""Killer-query HTTP endpoints (Phase 3B).

Each of the four killer queries is exposed as a typed GET endpoint returning the query's
``QueryResult`` (answer + provenance) as JSON. Temporal windows evaluate against
``REFERENCE_NOW`` (the synthetic corpus's fixed clock) by default — see ADR 0016; a production
deployment would default ``as_of`` to wall-clock now. A 404 is returned when the seed entity
(decision/service/system) does not exist in the graph.
"""

from __future__ import annotations

from datetime import timedelta

import structlog
from fastapi import APIRouter, HTTPException, Query, Request

from app.queries.kq1_multihop_ownership import ChainOwnerAnswer, find_chain_owner
from app.queries.kq2_temporal_contradiction import Contradiction, find_contradictions
from app.queries.kq3_blast_radius import BlastRadius, compute_blast_radius
from app.queries.kq4_change_tracking import ChangeTimeline, track_changes
from app.queries.result_types import QueryResult

router = APIRouter(prefix="/api/queries", tags=["killer-queries"])

log = structlog.get_logger(__name__)


async def _node_exists(request: Request, cypher: str, **params: str) -> bool:
    driver = request.app.state.neo4j.driver
    async with driver.session() as session:
        record = await (await session.run(cypher, **params)).single()
    return record is not None


@router.get(
    "/multihop-ownership",
    response_model=QueryResult[ChainOwnerAnswer],
    summary="KQ1: who owns the service depending on the system deprecated by Decision X?",
)
async def multihop_ownership(
    request: Request,
    decision_id: str = Query(..., examples=["D-0006"]),
) -> QueryResult[ChainOwnerAnswer]:
    """KQ1 — multi-hop ownership. Returns the owner chain(s) with source-event provenance."""
    driver = request.app.state.neo4j.driver
    if not await _node_exists(
        request, "MATCH (d:Decision {id: $decision_id}) RETURN d LIMIT 1", decision_id=decision_id
    ):
        raise HTTPException(status_code=404, detail=f"Decision {decision_id!r} not found")
    return await find_chain_owner(driver, decision_id=decision_id)


@router.get(
    "/contradictions",
    response_model=QueryResult[list[Contradiction]],
    summary="KQ2: active decisions contradicted by discussions in the recent window.",
)
async def contradictions(
    request: Request,
    window_days: int = Query(30, ge=1, le=365),
) -> QueryResult[list[Contradiction]]:
    """KQ2 — temporal contradiction. Window evaluates against REFERENCE_NOW by default."""
    driver = request.app.state.neo4j.driver
    return await find_contradictions(driver, window=timedelta(days=window_days))


@router.get(
    "/blast-radius",
    response_model=QueryResult[BlastRadius],
    summary="KQ3: services, people, and decisions affected if a service fails.",
)
async def blast_radius(
    request: Request,
    service: str = Query(..., examples=["payments-api"]),
    max_depth: int = Query(5, ge=1, le=10),
) -> QueryResult[BlastRadius]:
    """KQ3 — blast radius. Walks DEPENDS_ON dependents up to ``max_depth`` hops."""
    driver = request.app.state.neo4j.driver
    if not await _node_exists(
        request, "MATCH (s:Service {canonical_name: $service}) RETURN s LIMIT 1", service=service
    ):
        raise HTTPException(status_code=404, detail=f"Service {service!r} not found")
    return await compute_blast_radius(driver, service_name=service, max_depth=max_depth)


@router.get(
    "/change-tracking",
    response_model=QueryResult[ChangeTimeline],
    summary="KQ4: what changed about a target in the recent window, and who approved each.",
)
async def change_tracking(
    request: Request,
    target: str = Query(..., examples=["auth-service"]),
    window_days: int = Query(90, ge=1, le=3650),
) -> QueryResult[ChangeTimeline]:
    """KQ4 — change tracking. Returns decisions about the target, newest first, with approvers."""
    driver = request.app.state.neo4j.driver
    if not await _node_exists(
        request,
        "MATCH (t {canonical_name: $target}) WHERE t:System OR t:Service RETURN t LIMIT 1",
        target=target,
    ):
        raise HTTPException(status_code=404, detail=f"Target {target!r} not found")
    return await track_changes(driver, target_name=target, window=timedelta(days=window_days))
