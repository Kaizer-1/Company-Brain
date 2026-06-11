"""Per-stage incremental glue for live reconciliation (Phase 5A).

Each function here runs one stage of the pipeline scoped to a single event and returns a
``StageResult`` (plus any payload the orchestrator needs). The stages mirror the batch order in
``app.eval.query_eval`` — extract → embed → resolve → consolidate → project → temporal →
(materialize message) → contradiction → search-index — but every write is idempotent and the
scope is derived from the graph by provenance rather than re-scanning everything (ADR 0031).

Design notes captured here so the call sites read cleanly:

- **Extraction reuse** (ADR 0032): ``extraction_runs`` stores *counts*, not the extracted
  payload, so "reuse" cannot reload a prior result. Instead, if a successful run already exists
  we skip the LLM entirely and derive the event's asserted nodes/edges from the graph by
  provenance — the graph already holds them (MERGE-idempotent), so the scope is identical.
- Cheap idempotent stages (embed/resolve/consolidate/project/temporal) call the existing batch
  functions; only extraction and contradiction are truly scoped, because only they cost money.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from app.contradiction.message_ingest import ingest_one_message
from app.db.repositories.extraction import ExtractionRunRepository
from app.extraction.graph_writer import write_extraction
from app.extraction.pipeline import run_extraction
from app.extraction.prompts import PROMPT_VERSION, prompt_fingerprint
from app.ingestion.schemas import EdgeRef, NodeRef, StageResult
from app.ingestion.scoped_contradiction import run_scoped_contradiction
from app.ingestion.scoped_resolution import run_scoped_resolution
from app.ingestion.scoped_temporal import run_scoped_temporal
from app.models.enums import ExtractionStatus
from app.resolution.consolidator import consolidate_decisions
from app.resolution.projection import project_resolved_edges
from app.schemas.postgres import ExtractionRunCreate
from app.search.indexer import embed_events

if TYPE_CHECKING:
    import uuid

    from neo4j import AsyncDriver
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.extraction.client import OpenRouterClient
    from app.ingestion.schemas import ContradictionRef, MergeRef, SourceKind, StageStatus
    from app.schemas.postgres import EventDTO

log = structlog.get_logger(__name__)

# Extraction model for live ingestion. Defaults to the same high-F1 model the batch query eval
# uses (claude-3.5-haiku) so demo ingestion is as reliable as the batch pipeline; configurable
# by the orchestrator if a cheaper model is acceptable.
EXTRACTION_MODEL = "anthropic/claude-3.5-haiku"

# Node labels entity resolution operates on (Message is materialised mechanically, not resolved).
_RESOLVABLE_LABELS = frozenset({"Person", "Service", "System", "Team", "Decision"})


def _now_ms() -> float:
    return time.monotonic() * 1000.0


@dataclass
class GraphScope:
    """What a single event asserted in the graph, derived by provenance.

    ``decision_ids`` is every Decision the event touched (used to gate the cheap, idempotent
    consolidate/temporal stages). ``new_decision_ids`` is the subset that is *newly created* by
    this event (sole provenance) — only those warrant decision-side contradiction detection,
    since a re-mentioned existing decision was already compared against the message corpus.
    """

    nodes: list[NodeRef] = field(default_factory=list)
    edges: list[EdgeRef] = field(default_factory=list)
    decision_ids: list[str] = field(default_factory=list)
    new_decision_ids: list[str] = field(default_factory=list)
    node_types: list[str] = field(default_factory=list)


@dataclass
class ExtractStageOut:
    """The extract stage's result, cost, scope, and whether downstream stages should run."""

    stage: StageResult
    cost_usd: float
    scope: GraphScope
    ok: bool


async def derive_graph_scope(driver: AsyncDriver, event_id: uuid.UUID) -> GraphScope:
    """Read back everything this event asserted: nodes, edges, decision ids, resolvable types.

    Provenance-keyed (``$eid IN n.source_event_ids`` / ``r.source_event_id = $eid``) so it is
    correct on both a fresh extraction and a skipped (replayed) one — the graph is the single
    source of truth for scope, never an in-memory result.
    """
    eid = str(event_id)
    node_query = (
        "MATCH (n) WHERE $eid IN n.source_event_ids AND NOT n:_Migration "
        "RETURN labels(n)[0] AS label, n.id AS id, "
        "  coalesce(n.canonical_name, n.name, n.title, n.id) AS display, "
        "  size(n.source_event_ids) = 1 AS newly_created"
    )
    edge_query = (
        "MATCH (a)-[r]->(b) WHERE r.source_event_id = $eid AND type(r) <> 'MERGE_INTO' "
        "RETURN type(r) AS type, a.id AS source_id, b.id AS target_id"
    )
    scope = GraphScope()
    types: set[str] = set()
    async with driver.session() as session:
        result = await session.run(node_query, eid=eid)
        async for record in result:
            label = str(record["label"])
            node_id = str(record["id"])
            scope.nodes.append(
                NodeRef(id=node_id, label=label, display_name=str(record["display"]))
            )
            if label == "Decision":
                scope.decision_ids.append(node_id)
                if bool(record["newly_created"]):
                    scope.new_decision_ids.append(node_id)
            if label in _RESOLVABLE_LABELS:
                types.add(label)
        edges = await session.run(edge_query, eid=eid)
        async for record in edges:
            scope.edges.append(
                EdgeRef(
                    type=str(record["type"]),
                    source_id=str(record["source_id"]),
                    target_id=str(record["target_id"]),
                )
            )
    scope.node_types = sorted(types)
    return scope


async def run_extract(
    event: EventDTO,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    driver: AsyncDriver,
    client: OpenRouterClient,
    model: str = EXTRACTION_MODEL,
) -> ExtractStageOut:
    """Stage 1 — extract entities/relationships into the graph (idempotent, skip on replay).

    Skip-guard: if a successful ``extraction_runs`` row already exists for this event, the graph
    already holds its MERGE-written nodes, so we skip the LLM call and just re-derive the scope.
    A hard extraction error marks the stage failed (and the run partial); zero entities is a
    successful stage with an empty scope (no fabricated nodes).
    """
    t0 = _now_ms()

    async with session_factory() as session:
        latest = await ExtractionRunRepository(session).latest_for_event(event.id)
    if latest is not None and latest.status == ExtractionStatus.success:
        scope = await derive_graph_scope(driver, event.id)
        stage = StageResult(
            name="extract",
            status="skipped",
            duration_ms=round(_now_ms() - t0, 1),
            detail="prior successful extraction reused (no LLM call)",
        )
        return ExtractStageOut(stage=stage, cost_usd=0.0, scope=scope, ok=True)

    try:
        result, completion = await run_extraction(client, event.content, model)
    except Exception as exc:  # noqa: BLE001 — record the failure, don't abort the whole run
        async with session_factory() as session:
            repo = ExtractionRunRepository(session)
            run = await repo.create_pending(
                ExtractionRunCreate(
                    event_id=event.id,
                    model_name=model,
                    model_version=PROMPT_VERSION,
                    prompt_hash=prompt_fingerprint(),
                    started_at=datetime.now(UTC),
                )
            )
            await repo.mark_failed(run.id, error_message=str(exc)[:1000])
            await session.commit()
        stage = StageResult(
            name="extract",
            status="failed",
            duration_ms=round(_now_ms() - t0, 1),
            detail=f"extraction failed: {str(exc)[:160]}",
        )
        return ExtractStageOut(stage=stage, cost_usd=0.0, scope=GraphScope(), ok=False)

    async with session_factory() as session:
        repo = ExtractionRunRepository(session)
        run = await repo.create_pending(
            ExtractionRunCreate(
                event_id=event.id,
                model_name=model,
                model_version=PROMPT_VERSION,
                prompt_hash=prompt_fingerprint(),
                started_at=datetime.now(UTC),
            )
        )
        summary = await write_extraction(
            driver,
            event.id,
            result,
            extracted_by=f"{model}@{PROMPT_VERSION}",
            event_created_at=event.created_at,
        )
        await repo.mark_success(
            run.id,
            extracted_node_count=summary.nodes_written,
            extracted_edge_count=summary.edges_written,
        )
        await session.commit()

    scope = await derive_graph_scope(driver, event.id)
    detail = (
        f"{summary.nodes_written} nodes, {summary.edges_written} edges"
        if summary.nodes_written
        else "no entities extracted (sparse/off-topic content)"
    )
    stage = StageResult(
        name="extract", status="ok", duration_ms=round(_now_ms() - t0, 1), detail=detail
    )
    return ExtractStageOut(stage=stage, cost_usd=completion.cost_usd, scope=scope, ok=True)


async def run_embed(session_factory: async_sessionmaker[AsyncSession]) -> StageResult:
    """Stage 2 — embed un-embedded events (idempotent; skips already-embedded)."""
    t0 = _now_ms()
    async with session_factory() as session:
        written = await embed_events(session)
    status: StageStatus = "ok" if written else "skipped"
    detail = f"{written} new embedding(s)" if written else "already embedded"
    return StageResult(
        name="embed", status=status, duration_ms=round(_now_ms() - t0, 1), detail=detail
    )


async def run_resolve(
    driver: AsyncDriver,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    node_types: list[str],
    event_id: uuid.UUID,
    client: OpenRouterClient | None,
) -> tuple[StageResult, list[MergeRef], float]:
    """Stage 3 — resolve the node types this event touched; return merges + adjudication cost."""
    t0 = _now_ms()
    if not node_types:
        stage = StageResult(
            name="resolve", status="skipped", duration_ms=round(_now_ms() - t0, 1),
            detail="no resolvable entities asserted",
        )
        return stage, [], 0.0
    async with session_factory() as session:
        report, merges = await run_scoped_resolution(
            driver, session, node_types=node_types, event_id=event_id, client=client
        )
        await session.commit()
    stage = StageResult(
        name="resolve", status="ok", duration_ms=round(_now_ms() - t0, 1),
        detail=f"types={node_types}; {len(merges)} merge(s) from this event",
    )
    return stage, merges, report.llm_cost_usd


async def run_consolidate(
    driver: AsyncDriver,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    has_decisions: bool,
) -> StageResult:
    """Stage 4 — consolidate duplicate Decisions (only if this event asserted a Decision)."""
    t0 = _now_ms()
    if not has_decisions:
        return StageResult(
            name="consolidate", status="skipped", duration_ms=round(_now_ms() - t0, 1),
            detail="no Decision asserted",
        )
    async with session_factory() as session:
        counts = await consolidate_decisions(driver, session)
        await session.commit()
    return StageResult(
        name="consolidate", status="ok", duration_ms=round(_now_ms() - t0, 1),
        detail=f"{counts['merges']} consolidation(s) over {counts['decisions']} decision(s)",
    )


async def run_project(driver: AsyncDriver, *, merges_happened: bool) -> StageResult:
    """Stage 5 — project loser edges onto canonical winners (only if a merge happened)."""
    t0 = _now_ms()
    if not merges_happened:
        return StageResult(
            name="project", status="skipped", duration_ms=round(_now_ms() - t0, 1),
            detail="no merges to project",
        )
    created = await project_resolved_edges(driver)
    return StageResult(
        name="project", status="ok", duration_ms=round(_now_ms() - t0, 1),
        detail=f"{created} canonical edge(s) projected",
    )


async def run_temporal(
    driver: AsyncDriver,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    has_decisions: bool,
) -> StageResult:
    """Stage 6 — enrich temporal fields + supersession (only if a Decision is in play)."""
    t0 = _now_ms()
    if not has_decisions:
        return StageResult(
            name="temporal", status="skipped", duration_ms=round(_now_ms() - t0, 1),
            detail="no Decision asserted",
        )
    async with session_factory() as session:
        result = await run_scoped_temporal(driver, session)
        await session.commit()
    return StageResult(
        name="temporal", status="ok", duration_ms=round(_now_ms() - t0, 1),
        detail=f"{result.valid_from_set} decision(s) enriched, "
        f"{result.supersedes_edges_written} supersession edge(s)",
    )


async def run_materialize_message(
    driver: AsyncDriver, event: EventDTO, *, source_kind: SourceKind
) -> tuple[StageResult, str | None]:
    """Stage 6b — materialise the Message node for a slack event (mechanical, idempotent).

    Not in the original 8-stage list but load-bearing: a Message node must exist before scoped
    contradiction detection can compare it against decisions. No-op for non-slack events.
    """
    t0 = _now_ms()
    if source_kind != "slack_message":
        return (
            StageResult(
                name="materialize_message", status="skipped",
                duration_ms=round(_now_ms() - t0, 1), detail="not a slack message",
            ),
            None,
        )
    message_id = await ingest_one_message(driver, event)
    return (
        StageResult(
            name="materialize_message", status="ok",
            duration_ms=round(_now_ms() - t0, 1), detail=f"Message {message_id}",
        ),
        message_id,
    )


async def run_contradiction(
    driver: AsyncDriver,
    *,
    source_kind: SourceKind,
    message_id: str | None,
    decision_ids: list[str],
    client: OpenRouterClient | None,
    as_of: datetime,
) -> tuple[StageResult, list[ContradictionRef], float]:
    """Stage 7 — scoped contradiction detection; return the edges written + adjudication cost."""
    t0 = _now_ms()
    if message_id is None and not decision_ids:
        return (
            StageResult(
                name="contradiction", status="skipped",
                duration_ms=round(_now_ms() - t0, 1), detail="no Message or Decision to compare",
            ),
            [],
            0.0,
        )
    refs, cost, candidates = await run_scoped_contradiction(
        driver,
        source_kind=source_kind,
        message_id=message_id,
        decision_ids=decision_ids,
        client=client,
        as_of=as_of,
    )
    stage = StageResult(
        name="contradiction", status="ok", duration_ms=round(_now_ms() - t0, 1),
        detail=f"{candidates} candidate(s), {len(refs)} contradiction(s) written",
    )
    return stage, refs, cost


def run_search_index() -> StageResult:
    """Stage 8 — search-index update. The embedding was written in Stage 2; nothing more to do."""
    return StageResult(
        name="search_index", status="skipped", duration_ms=0.0,
        detail="embedding written in embed stage; index is the pgvector table itself",
    )
