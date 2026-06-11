"""Top-level live-reconciliation orchestrator (Phase 5A).

``reconcile_event`` runs the eight incremental stages in the batch pipeline's order, scoped to
one event, idempotently, and writes one ``ingestion_runs`` row recording the outcome. It is the
single seam the API endpoint, the eval, and the tests all call.

Idempotency (ADR 0032) is enforced at two levels:

1. **Orchestration guard** — if a completed ``ingestion_runs`` row already exists for the event,
   ``reconcile_event`` returns that result without re-running any stage (unless ``force=True``).
   This is what keeps a replay from re-paying for LLM calls and from appending to the
   append-only ``merge_decisions`` audit.
2. **Stage idempotency** — every graph write is a ``MERGE``, so even a forced replay converges to
   identical graph *state*; the guard is an optimisation and an audit-hygiene measure on top.

Stage failures do not abort the run: a failed stage is recorded and downstream stages still run
(a slack event whose entity extraction failed still gets its Message materialised and compared
against decisions). The run's status is ``reconciled`` if every stage was ok/skipped, else
``partial``; a guard/short-circuit returns the prior status.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import structlog

from app.db.repositories.events import EventRepository
from app.db.repositories.ingestion_runs import IngestionRunRepository
from app.extraction.client import OpenRouterClient
from app.ingestion.schemas import (
    IngestEventResponse,
    IngestionRunUpsert,
    StageResult,
)
from app.ingestion.scoped_resolution import _merges_for_event  # noqa: PLC2701 — intra-package reuse
from app.ingestion.stages import (
    EXTRACTION_MODEL,
    derive_graph_scope,
    run_consolidate,
    run_contradiction,
    run_embed,
    run_extract,
    run_materialize_message,
    run_project,
    run_resolve,
    run_search_index,
    run_temporal,
)

if TYPE_CHECKING:
    import uuid

    from neo4j import AsyncDriver
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.ingestion.schemas import IngestionRunDTO, IngestionStatus, SourceKind

log = structlog.get_logger(__name__)


async def reconcile_event(
    event_id: uuid.UUID,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    neo4j_driver: AsyncDriver,
    client: OpenRouterClient | None = None,
    model: str = EXTRACTION_MODEL,
    force: bool = False,
) -> IngestEventResponse:
    """Reconcile one already-persisted event into the graph; return the visible result.

    Args:
        event_id: the Postgres ``events`` row to reconcile (must already exist).
        session_factory: async session factory; stages open their own per-step sessions
            (mirrors the extraction pipeline — independent sessions, commit per step).
        neo4j_driver: connected Neo4j async driver.
        client: OpenRouter client for extraction + adjudication; constructed (and closed) here
            if not supplied.
        model: extraction model.
        force: re-run all stages even if a completed ingestion run already exists.
    """
    t0 = time.monotonic()
    started_at = datetime.now(UTC)

    if not force:
        async with session_factory() as session:
            prior = await IngestionRunRepository(session).get_by_event(event_id)
        if prior is not None and prior.status in {"reconciled", "partial"}:
            log.info("reconcile_short_circuit", event_id=str(event_id), status=prior.status)
            return await _response_from_prior(prior, neo4j_driver)

    async with session_factory() as session:
        event = await EventRepository(session).get_by_id(event_id)
    if event is None:
        msg = f"event {event_id} not found"
        raise ValueError(msg)

    source_kind: SourceKind = event.source_type.value
    as_of = event.created_at

    owns_client = client is None
    if client is None:
        client = OpenRouterClient()

    stages: list[StageResult] = []
    cost = 0.0
    try:
        extract_out = await run_extract(
            event, session_factory=session_factory, driver=neo4j_driver, client=client, model=model
        )
        stages.append(extract_out.stage)
        cost += extract_out.cost_usd
        scope = extract_out.scope
        has_decisions = bool(scope.decision_ids)

        stages.append(await run_embed(session_factory))

        resolve_stage, merges, resolve_cost = await run_resolve(
            neo4j_driver, session_factory,
            node_types=scope.node_types, event_id=event_id, client=client,
        )
        stages.append(resolve_stage)
        cost += resolve_cost

        stages.append(
            await run_consolidate(neo4j_driver, session_factory, has_decisions=has_decisions)
        )
        stages.append(
            await run_project(neo4j_driver, merges_happened=bool(merges) or has_decisions)
        )
        stages.append(
            await run_temporal(neo4j_driver, session_factory, has_decisions=has_decisions)
        )

        message_stage, message_id = await run_materialize_message(
            neo4j_driver, event, source_kind=source_kind
        )
        stages.append(message_stage)

        contra_stage, contradictions, contra_cost = await run_contradiction(
            neo4j_driver,
            source_kind=source_kind,
            message_id=message_id,
            decision_ids=scope.new_decision_ids,
            client=client,
            as_of=as_of,
        )
        stages.append(contra_stage)
        cost += contra_cost

        stages.append(run_search_index())
    finally:
        if owns_client:
            await client.aclose()

    status: IngestionStatus = (
        "partial" if any(s.status == "failed" for s in stages) else "reconciled"
    )
    duration_ms = round((time.monotonic() - t0) * 1000, 1)

    response = IngestEventResponse(
        event_id=event_id,
        status=status,
        stages_run=stages,
        nodes_created=scope.nodes,
        nodes_merged=merges,
        edges_created=scope.edges,
        contradictions_detected=contradictions,
        duration_ms=duration_ms,
        cost_usd=round(cost, 6),
    )
    await _persist_run(session_factory, response, started_at=started_at, stages=stages)
    log.info(
        "reconcile_complete",
        event_id=str(event_id),
        status=status,
        nodes=len(scope.nodes),
        merges=len(merges),
        contradictions=len(contradictions),
        duration_ms=duration_ms,
        cost_usd=round(cost, 6),
    )
    return response


async def _persist_run(
    session_factory: async_sessionmaker[AsyncSession],
    response: IngestEventResponse,
    *,
    started_at: datetime,
    stages: list[StageResult],
) -> None:
    """Upsert the ``ingestion_runs`` row for this reconcile (keyed on event_id)."""
    async with session_factory() as session:
        await IngestionRunRepository(session).upsert(
            IngestionRunUpsert(
                event_id=response.event_id,
                status=response.status,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                stages_json=[s.model_dump() for s in stages],
                nodes_created_count=len(response.nodes_created),
                nodes_merged_count=len(response.nodes_merged),
                edges_created_count=len(response.edges_created),
                contradictions_count=len(response.contradictions_detected),
                cost_usd=response.cost_usd,
                error=None,
            )
        )
        await session.commit()


async def _response_from_prior(
    prior: IngestionRunDTO, driver: AsyncDriver
) -> IngestEventResponse:
    """Rebuild a response for an already-reconciled event without re-running any stage.

    Read-only: the per-stage timeline comes from the stored ``stages_json``; the node/edge/merge
    refs are re-derived from the graph by provenance (cheap, no LLM, no writes). Contradiction
    refs are not re-derived — their count is preserved in the run — so the dedup response carries
    ``contradictions_detected=[]`` with the count visible in ``stages_run``.
    """
    scope = await derive_graph_scope(driver, prior.event_id)
    merges = await _merges_for_event(driver, prior.event_id)
    stages = [StageResult.model_validate(s) for s in prior.stages_json]
    return IngestEventResponse(
        event_id=prior.event_id,
        status=cast("IngestionStatus", prior.status),
        stages_run=stages,
        nodes_created=scope.nodes,
        nodes_merged=merges,
        edges_created=scope.edges,
        contradictions_detected=[],
        duration_ms=0.0,
        cost_usd=prior.cost_usd,
        deduplicated=True,
    )
