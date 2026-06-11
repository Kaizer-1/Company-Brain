"""Scoped entity resolution for live ingestion (Phase 5A).

The 5A pre-implementation check established that Phase 3A's ``resolve_graph`` has a ``node_types``
filter but no node-*id* scope: it regenerates **all-pairs within a type** every call. The first
live smoke proved why that matters — re-resolving whole types per event adjudicated 61 pre-existing
pairs that had nothing to do with the new event, dominating latency. Because the graph writer
``MERGE``s a new event's entities onto their canonical key, a re-mentioned entity is already the
canonical node (no duplicate); only a genuinely new surface form needs resolving, and only
against the *existing* nodes of its type.

So this module does true node-scoped resolution: for each type the event touched, it pairs the
event's node(s) against the other existing nodes of that type and routes each pair through the
**same three-tier machinery** (``_decide_and_apply``) the batch resolver uses — identical
decisions and ``merge_decisions`` rows, a fraction of the work. This is the "scope where cost
demands" half of the hybrid decision (ADR 0031); the cheap idempotent stages still call their
batch functions unchanged.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

from app.db.repositories.events import EventRepository
from app.db.repositories.resolution import MergeDecisionRepository
from app.ingestion.schemas import MergeRef
from app.models.enums import NodeType
from app.resolution.adjudicator import Adjudicator
from app.resolution.candidates import load_nodes
from app.resolution.embeddings import cosine_similarity, embed_texts, node_embedding_input
from app.resolution.merger import Merger
from app.resolution.models import CandidatePair, ResolutionReport
from app.resolution.resolver import _decide_and_apply  # noqa: PLC2701 — reuse the tier machinery
from app.resolution.rules import AliasDictionary

if TYPE_CHECKING:
    import uuid

    from neo4j import AsyncDriver
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.extraction.client import OpenRouterClient
    from app.resolution.models import ResolvableNode

log = structlog.get_logger(__name__)


async def run_scoped_resolution(
    driver: AsyncDriver,
    session: AsyncSession,
    *,
    node_types: list[str],
    event_id: uuid.UUID,
    client: OpenRouterClient | None = None,
) -> tuple[ResolutionReport, list[MergeRef]]:
    """Resolve only the event's nodes against existing nodes of their type; return merges.

    ``node_types`` is the distinct set of labels the extraction asserted. For each type, the
    event's nodes (identified by provenance) are paired against every other non-merged node of
    that type; pairs run through the batch resolver's tier logic. With nothing to scope (empty
    types or no provenance nodes) it is a no-op.
    """
    if not node_types:
        return ResolutionReport(), []

    new_ids = await _event_node_ids_by_type(driver, event_id)
    repo = MergeDecisionRepository(session)
    events = EventRepository(session)
    merger = Merger(driver, repo)
    adjudicator = Adjudicator(client) if client is not None else None
    aliases = AliasDictionary()

    pairs_total = 0
    for type_name in node_types:
        node_type = NodeType(type_name)
        target_ids = new_ids.get(type_name, set())
        if not target_ids:
            continue
        nodes = await load_nodes(driver, node_type)
        targets = [n for n in nodes if n.node_id in target_ids]
        others = [n for n in nodes if n.node_id not in target_ids]
        if not targets or not others:
            continue
        pairs_total += await _resolve_targets_against(
            targets, others, merger=merger, aliases=aliases, adjudicator=adjudicator, events=events
        )

    cost = adjudicator.cost_usd if adjudicator is not None else 0.0
    report = ResolutionReport(llm_cost_usd=cost)
    merges = await _merges_for_event(driver, event_id)
    log.info(
        "scoped_resolution_complete",
        node_types=node_types,
        pairs=pairs_total,
        merges_this_event=len(merges),
        llm_cost_usd=round(cost, 4),
    )
    return report, merges


async def _resolve_targets_against(
    targets: list[ResolvableNode],
    others: list[ResolvableNode],
    *,
    merger: Merger,
    aliases: AliasDictionary,
    adjudicator: Adjudicator | None,
    events: EventRepository,
) -> int:
    """Route every (target, other) pair through the tier machinery; return the pair count."""
    involved = targets + others
    vectors = await asyncio.to_thread(embed_texts, [node_embedding_input(n) for n in involved])
    pos = {n.node_id: i for i, n in enumerate(involved)}

    count = 0
    for target in targets:
        for other in others:
            sim = cosine_similarity(vectors[pos[target.node_id]], vectors[pos[other.node_id]])
            pair = CandidatePair(node_a=target, node_b=other, similarity=sim)
            await _decide_and_apply(pair, merger, aliases, adjudicator, events)
            count += 1
    return count


async def _event_node_ids_by_type(
    driver: AsyncDriver, event_id: uuid.UUID
) -> dict[str, set[str]]:
    """Map ``label -> {node_id}`` for the **newly-created** nodes this event asserted.

    Scope is restricted to nodes whose *only* provenance is this event
    (``size(source_event_ids) = 1``) — i.e. genuine new fragments. A re-mentioned existing
    entity was ``MERGE``d onto its canonical node and carries prior provenance too, so it is
    already resolved and needs no adjudication; including it would re-adjudicate the whole type
    for nothing (the latency bug the first smoke exposed). Only a brand-new surface form (a new
    ``@handle``, a new service name) is worth resolving against the existing graph.
    """
    query = (
        "MATCH (n) WHERE $eid IN n.source_event_ids AND NOT n:_Migration "
        "  AND coalesce(n.status,'active') <> 'merged' AND size(n.source_event_ids) = 1 "
        "RETURN labels(n)[0] AS label, n.id AS id"
    )
    out: dict[str, set[str]] = {}
    async with driver.session() as session:
        result = await session.run(query, eid=str(event_id))
        async for record in result:
            out.setdefault(str(record["label"]), set()).add(str(record["id"]))
    return out


async def _merges_for_event(driver: AsyncDriver, event_id: uuid.UUID) -> list[MergeRef]:
    """Return the MERGE_INTO edges that involve a node carrying this event's provenance.

    Best-effort attribution for the "what changed" panel: the merger unions a loser's provenance
    onto its winner, so a merge this event caused leaves the event id on either endpoint;
    matching either side captures the event's merges without over-reporting old ones for a fresh
    event id.
    """
    query = (
        "MATCH (loser)-[r:MERGE_INTO]->(winner) "
        "WHERE $eid IN loser.source_event_ids OR $eid IN winner.source_event_ids "
        "RETURN loser.id AS loser_id, winner.id AS winner_id, labels(winner)[0] AS label, "
        "  r.tier AS tier, r.confidence AS confidence"
    )
    refs: list[MergeRef] = []
    async with driver.session() as session:
        result = await session.run(query, eid=str(event_id))
        async for record in result:
            refs.append(
                MergeRef(
                    loser_id=str(record["loser_id"]),
                    winner_id=str(record["winner_id"]),
                    label=str(record["label"]),
                    tier=int(record["tier"]) if record["tier"] is not None else 0,
                    confidence=(
                        float(record["confidence"]) if record["confidence"] is not None else 0.0
                    ),
                )
            )
    return refs
