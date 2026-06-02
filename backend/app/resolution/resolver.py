"""The resolution orchestrator (Phase 3A).

``resolve_graph`` walks the graph one entity type at a time, generates candidate pairs,
routes each through the three tiers (ADR 0014), and effects the decision via the ``Merger``:

    Tier 1 (auto_merge)      a deterministic rule fired AND similarity ≥ SIM_FLOOR
    Tier 2 (llm_merge /      no decisive rule but similarity ≥ SIM_FLOOR, OR a rule fired but
            llm_no_merge)    similarity contradicts it — claude-3.5-haiku adjudicates
    Tier 3 (below_threshold) no rule and similarity < SIM_FLOOR — not worth asking

Built to be callable from both a post-merge batch (this phase) and an at-write-time path
(Phase 4): it takes a driver + a Postgres session and returns a ``ResolutionReport``.
Embedding runs off the event loop via ``asyncio.to_thread`` (sentence-transformers is sync).
"""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING

import structlog

from app.db.repositories.events import EventRepository
from app.db.repositories.resolution import MergeDecisionRepository
from app.models.enums import MergeDecisionType, NodeType
from app.resolution.adjudicator import Adjudicator
from app.resolution.candidates import generate_candidate_pairs, load_nodes
from app.resolution.embeddings import embed_texts, node_embedding_input
from app.resolution.merger import Merger
from app.resolution.models import CandidatePair, ResolutionReport, ResolvableNode, TypeBreakdown
from app.resolution.rules import AliasDictionary, apply_tier1_rules

if TYPE_CHECKING:
    from neo4j import AsyncDriver
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.extraction.client import OpenRouterClient

log = structlog.get_logger(__name__)

# The similarity floor below which a pair is never merged or adjudicated. A deterministic
# Tier 1 rule above this floor auto-merges; the canonical "embedding is decisive on its own"
# intuition sits higher (~0.95) but we never auto-merge on cosine alone — a corroborating
# rule is always required (ADR 0014).
SIM_FLOOR = 0.75
AUTO_MERGE_CONFIDENCE = 0.99

_MAX_SNIPPETS = 3


async def resolve_graph(
    driver: AsyncDriver,
    session: AsyncSession,
    *,
    node_types: list[str] | None = None,
    client: OpenRouterClient | None = None,
    dry_run: bool = False,
    alias_dict: AliasDictionary | None = None,
) -> ResolutionReport:
    """Resolve duplicate nodes in the graph and return a per-type report.

    Args:
        driver: connected Neo4j async driver.
        session: Postgres session for reading event snippets and writing merge_decisions.
        node_types: subset of {Person, Service, System, Team, Decision} to resolve; all if None.
        client: OpenRouter client for Tier 2 adjudication. If None, ambiguous pairs are
            conservatively left unmerged (recorded as llm_no_merge with a note) — so Tier 1
            -only runs need no API key.
        dry_run: run the full pipeline but write nothing (no graph mutation, no audit rows).
    """
    types = _resolve_node_types(node_types)
    aliases = alias_dict or AliasDictionary()
    repo = MergeDecisionRepository(session)
    events = EventRepository(session)
    merger = Merger(driver, repo, dry_run=dry_run)
    adjudicator = Adjudicator(client) if client is not None else None

    by_type: dict[str, TypeBreakdown] = {}
    for node_type in types:
        breakdown = await _resolve_type(
            node_type, driver, events, merger, aliases, adjudicator
        )
        by_type[node_type.value] = breakdown

    llm_cost = adjudicator.cost_usd if adjudicator is not None else 0.0
    report = ResolutionReport(by_type=by_type, dry_run=dry_run, llm_cost_usd=llm_cost)
    log.info(
        "resolve_graph_complete",
        dry_run=dry_run,
        total_candidates=report.total_candidates,
        total_merges=report.total_merges,
        llm_cost_usd=round(llm_cost, 4),
    )
    return report


def _resolve_node_types(node_types: list[str] | None) -> list[NodeType]:
    if node_types is None:
        return list(NodeType)
    return [NodeType(name) for name in node_types]


async def _resolve_type(
    node_type: NodeType,
    driver: AsyncDriver,
    events: EventRepository,
    merger: Merger,
    aliases: AliasDictionary,
    adjudicator: Adjudicator | None,
) -> TypeBreakdown:
    nodes = await load_nodes(driver, node_type)
    if len(nodes) < 2:
        return TypeBreakdown(
            node_type=node_type, node_count=len(nodes), candidate_pairs=0,
            auto_merges=0, llm_merges=0, llm_no_merges=0, below_threshold=0,
        )

    inputs = [node_embedding_input(n) for n in nodes]
    vectors = await asyncio.to_thread(embed_texts, inputs)
    pairs = generate_candidate_pairs(nodes, vectors=vectors)

    counts = {
        MergeDecisionType.auto_merge: 0,
        MergeDecisionType.llm_merge: 0,
        MergeDecisionType.llm_no_merge: 0,
        MergeDecisionType.below_threshold: 0,
    }
    for pair in pairs:
        decision = await _decide_and_apply(pair, merger, aliases, adjudicator, events)
        counts[decision] += 1

    return TypeBreakdown(
        node_type=node_type,
        node_count=len(nodes),
        candidate_pairs=len(pairs),
        auto_merges=counts[MergeDecisionType.auto_merge],
        llm_merges=counts[MergeDecisionType.llm_merge],
        llm_no_merges=counts[MergeDecisionType.llm_no_merge],
        below_threshold=counts[MergeDecisionType.below_threshold],
    )


async def _decide_and_apply(
    pair: CandidatePair,
    merger: Merger,
    aliases: AliasDictionary,
    adjudicator: Adjudicator | None,
    events: EventRepository,
) -> MergeDecisionType:
    """Route one pair through the three tiers and apply the resulting decision."""
    rules = apply_tier1_rules(pair.node_a, pair.node_b, aliases)
    sim = pair.similarity

    # Tier 1 — a deterministic exact-identity rule fired. These signals (shared email/handle,
    # a curated known-alias, an equal/former canonical name) are definitional, so we auto-merge
    # and do not let a 384-dim sentence embedding veto them (ADR 0014). Similarity is still
    # recorded on the audit row.
    if rules:
        await merger.apply_decision(
            pair, decision=MergeDecisionType.auto_merge, tier=1,
            confidence=AUTO_MERGE_CONFIDENCE, rules_matched=rules,
        )
        return MergeDecisionType.auto_merge

    # Tier 3 — no rule and the embeddings are not close enough to be worth adjudicating.
    if sim < SIM_FLOOR:
        await merger.apply_decision(
            pair, decision=MergeDecisionType.below_threshold, tier=3,
            confidence=0.0, rules_matched=rules,
        )
        return MergeDecisionType.below_threshold

    # Tier 2 — no decisive rule but the embeddings are close (sim ≥ SIM_FLOOR), the genuinely
    # ambiguous band (including look-alikes). Ask the LLM (or, with no adjudicator, decline).
    if adjudicator is None:
        await merger.apply_decision(
            pair, decision=MergeDecisionType.llm_no_merge, tier=2,
            confidence=0.0, rules_matched=rules,
            llm_reasoning="no adjudicator configured; conservative no-merge",
        )
        return MergeDecisionType.llm_no_merge

    snippets_a = await _fetch_snippets(events, pair.node_a)
    snippets_b = await _fetch_snippets(events, pair.node_b)
    verdict = await adjudicator.adjudicate(pair, snippets_a=snippets_a, snippets_b=snippets_b)
    if verdict.same:
        await merger.apply_decision(
            pair, decision=MergeDecisionType.llm_merge, tier=2,
            confidence=verdict.confidence, rules_matched=rules,
            llm_reasoning=verdict.reasoning, llm_model=adjudicator.model,
        )
        return MergeDecisionType.llm_merge

    await merger.apply_decision(
        pair, decision=MergeDecisionType.llm_no_merge, tier=2,
        confidence=verdict.confidence, rules_matched=rules,
        llm_reasoning=verdict.reasoning, llm_model=adjudicator.model,
    )
    return MergeDecisionType.llm_no_merge


async def _fetch_snippets(events: EventRepository, node: ResolvableNode) -> list[str]:
    """Up to 3 source-event contents for a node, for adjudicator context.

    Source event ids that are not valid UUIDs or not present in Postgres are skipped (the
    eval seeds synthetic nodes whose provenance ids are not in the event store).
    """
    snippets: list[str] = []
    for raw_id in node.source_event_ids[:_MAX_SNIPPETS]:
        try:
            event_uuid = uuid.UUID(raw_id)
        except (ValueError, AttributeError):
            continue
        event = await events.get_by_id(event_uuid)
        if event is not None:
            snippets.append(event.content)
    return snippets
