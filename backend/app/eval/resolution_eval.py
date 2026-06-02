"""Entity-resolution eval harness (Phase 3A).

Ground truth is ``narrative.ALIAS_GROUPS`` — the same single-source-of-truth discipline as
Phase 2B (ADR 0013). Each ``AliasGroup`` is a set of surface forms that must collapse onto
one entity; ``LOOK_ALIKE_PAIRS`` is the negative case that must *not* merge.

The harness is deterministic and self-contained: it seeds a fragmented graph directly from
those surface forms (one node per normalised form, plus the look-alike services), runs
``resolve_graph``, reads back the ``MERGE_INTO`` edges, groups them with union-find, and
scores the predicted merge-pairs against the true merge-pairs — overall and per entity type.
A mock-perfect resolver scores 1.0/1.0; ``test_resolution_eval`` asserts that before any real
output is judged.

Metrics are computed over **unordered node pairs**: a "merge" is any pair the resolver placed
in the same group; a "true merge" is any within-group pair in ground truth. Precision, recall,
false-merge rate (= 1 − precision), and missed-merge rate (= 1 − recall) follow directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import TYPE_CHECKING

import structlog

from app.eval.matcher import normalize
from app.eval.metrics import Metrics, compute_metrics
from app.models.enums import NodeType
from app.resolution.models import KEY_FIELD, ResolutionReport
from app.resolution.resolver import resolve_graph
from app.synthetic import narrative as nv

if TYPE_CHECKING:
    from neo4j import AsyncDriver
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.extraction.client import OpenRouterClient

log = structlog.get_logger(__name__)

Pair = frozenset[str]


# ---------------------------------------------------------------------------
# Ground truth
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CanonicalGroup:
    """One real entity and the graph-node ids that should collapse onto it."""

    node_type: NodeType
    canonical: str
    node_ids: frozenset[str]

    def true_pairs(self) -> set[Pair]:
        return {frozenset(p) for p in combinations(sorted(self.node_ids), 2)}


@dataclass(frozen=True)
class ResolutionGroundTruth:
    """Expected merges (alias groups) and forbidden merges (look-alike pairs)."""

    groups: frozenset[CanonicalGroup]
    negatives: frozenset[Pair]

    def groups_for(self, node_type: NodeType) -> list[CanonicalGroup]:
        return [g for g in self.groups if g.node_type == node_type]

    def true_pairs_for(self, node_type: NodeType) -> set[Pair]:
        pairs: set[Pair] = set()
        for g in self.groups_for(node_type):
            pairs |= g.true_pairs()
        return pairs

    def node_ids_for(self, node_type: NodeType) -> set[str]:
        ids: set[str] = set()
        for g in self.groups_for(node_type):
            ids |= set(g.node_ids)
        if node_type == NodeType.Service:
            for pair in self.negatives:
                ids |= set(pair)
        return ids


def build_resolution_ground_truth() -> ResolutionGroundTruth:
    """Derive expected merges from ``ALIAS_GROUPS`` and forbidden merges from look-alikes.

    Node ids are the normalised surface forms, which is exactly what the graph writer keys
    nodes on and what ``seed_fragmented_graph`` creates — so ground-truth ids and graph ids
    are the same space by construction.
    """
    groups: set[CanonicalGroup] = set()
    for group in nv.ALIAS_GROUPS:
        node_type = NodeType.Person if group.entity_kind == "person" else NodeType.Service
        node_ids = frozenset(normalize(form) for form in group.surface_forms)
        groups.add(CanonicalGroup(node_type, group.canonical, node_ids))

    negatives: set[Pair] = set()
    for pair in nv.LOOK_ALIKE_PAIRS:
        negatives.add(frozenset({normalize(pair.service_a), normalize(pair.service_b)}))

    return ResolutionGroundTruth(frozenset(groups), frozenset(negatives))


# ---------------------------------------------------------------------------
# Seeding a deterministic fragmented graph
# ---------------------------------------------------------------------------
async def seed_fragmented_graph(driver: AsyncDriver, gt: ResolutionGroundTruth) -> int:
    """Wipe non-migration nodes and create one node per ground-truth surface form.

    Returns the number of nodes created. Each node carries a unique fake ``source_event_id``
    (so the winner tie-break is deterministic on node id) and a ``surface_form`` property for
    the report. Look-alike services additionally carry their distinct descriptions, so a Tier
    2 adjudicator (if configured) has the evidence to keep them apart.
    """
    descriptions = {
        "notifications-api": "Public API that accepts notification requests",
        "notification-worker": "Background worker that delivers notifications off event-bus",
    }
    specs: list[tuple[str, str, dict[str, object]]] = []  # (label, node_id, props)
    for group in nv.ALIAS_GROUPS:
        label = (NodeType.Person if group.entity_kind == "person" else NodeType.Service).value
        for form in group.surface_forms:
            node_id = normalize(form)
            specs.append((label, node_id, {"surface_form": form}))
    for pair in nv.LOOK_ALIKE_PAIRS:
        for name in (pair.service_a, pair.service_b):
            node_id = normalize(name)
            props: dict[str, object] = {"surface_form": name}
            if node_id in descriptions:
                props["description"] = descriptions[node_id]
            specs.append((NodeType.Service.value, node_id, props))

    async with driver.session() as session:
        await (
            await session.run("MATCH (n) WHERE NOT n:_Migration DETACH DELETE n")
        ).consume()
        for label, node_id, props in specs:
            key_field = KEY_FIELD[NodeType(label)]
            query = (
                f"MERGE (n:{label} {{{key_field}: $node_id}}) "
                "SET n.id = $node_id, n.source_event_ids = [$event_id], "
                "    n.status = 'active', n += $props"
            )
            await (
                await session.run(
                    query, node_id=node_id, event_id=f"{node_id}-evt", props=props
                )
            ).consume()
    log.info("seeded_fragmented_graph", nodes=len(specs))
    return len(specs)


# ---------------------------------------------------------------------------
# Reading back the resolved graph
# ---------------------------------------------------------------------------
async def _predicted_pairs(driver: AsyncDriver, node_type: NodeType) -> set[Pair]:
    """All within-group node pairs implied by the MERGE_INTO edges of one type.

    Union-find over the (undirected) MERGE_INTO edges yields connected components; each
    component contributes all of its pairs. Robust to star/chain/redundant edge shapes.
    """
    label = node_type.value
    query = (
        f"MATCH (a:{label})-[:MERGE_INTO]->(b:{label}) "
        "RETURN a.id AS a, b.id AS b"
    )
    async with driver.session() as session:
        result = await session.run(query)
        edges = [(record["a"], record["b"]) async for record in result]

    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: str, y: str) -> None:
        parent[find(x)] = find(y)

    for a, b in edges:
        union(a, b)

    components: dict[str, set[str]] = {}
    for node in parent:
        components.setdefault(find(node), set()).add(node)

    pairs: set[Pair] = set()
    for members in components.values():
        for p in combinations(sorted(members), 2):
            pairs.add(frozenset(p))
    return pairs


# ---------------------------------------------------------------------------
# Result type + metrics
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TierStat:
    """How many decisions landed in one tier and their mean MERGE_INTO confidence."""

    tier: int
    merges: int
    mean_confidence: float


@dataclass
class ResolutionEvalResult:
    """Everything the resolution report needs."""

    overall: Metrics
    by_type: dict[str, Metrics]
    tier_stats: list[TierStat]
    decision_counts: dict[str, int]
    correct_examples: list[tuple[str, str]] = field(default_factory=list)
    missed_examples: list[tuple[str, str]] = field(default_factory=list)
    false_examples: list[tuple[str, str]] = field(default_factory=list)
    llm_cost_usd: float = 0.0
    node_count: int = 0

    @property
    def false_merge_rate(self) -> float:
        return 1.0 - self.overall.precision if (self.overall.true_positives + self.overall.false_positives) else 0.0

    @property
    def missed_merge_rate(self) -> float:
        return 1.0 - self.overall.recall if self.overall.support else 0.0


async def run_resolution_eval(
    driver: AsyncDriver,
    session: AsyncSession,
    *,
    client: OpenRouterClient | None = None,
) -> ResolutionEvalResult:
    """Seed a fragmented graph, resolve it, and score the merges against ground truth."""
    gt = build_resolution_ground_truth()
    node_count = await seed_fragmented_graph(driver, gt)

    report = await resolve_graph(driver, session, client=client)
    await session.commit()

    types = [NodeType.Person, NodeType.Service]  # the only types ground truth covers
    by_type: dict[str, Metrics] = {}
    all_pred: set[Pair] = set()
    all_true: set[Pair] = set()
    correct_examples: list[tuple[str, str]] = []
    missed_examples: list[tuple[str, str]] = []
    false_examples: list[tuple[str, str]] = []

    for node_type in types:
        predicted = await _predicted_pairs(driver, node_type)
        expected = gt.true_pairs_for(node_type)
        by_type[node_type.value] = compute_metrics(predicted, expected)
        all_pred |= predicted
        all_true |= expected
        correct_examples.extend(_as_tuples(predicted & expected))
        missed_examples.extend(_as_tuples(expected - predicted))
        false_examples.extend(_as_tuples(predicted - expected))

    overall = compute_metrics(all_pred, all_true)

    tier_stats = await _tier_stats(driver)
    decision_counts = _decision_counts(report)

    result = ResolutionEvalResult(
        overall=overall,
        by_type=by_type,
        tier_stats=tier_stats,
        decision_counts=decision_counts,
        correct_examples=correct_examples[:5],
        missed_examples=missed_examples[:5],
        false_examples=false_examples[:5],
        llm_cost_usd=report.llm_cost_usd,
        node_count=node_count,
    )
    log.info(
        "resolution_eval_complete",
        precision=round(overall.precision, 3),
        recall=round(overall.recall, 3),
        f1=round(overall.f1, 3),
        false_merge_rate=round(result.false_merge_rate, 3),
        missed_merge_rate=round(result.missed_merge_rate, 3),
    )
    return result


def _as_tuples(pairs: set[Pair]) -> list[tuple[str, str]]:
    return [tuple(sorted(p)) for p in pairs]  # type: ignore[misc]


def _decision_counts(report: ResolutionReport) -> dict[str, int]:
    counts = {"auto_merge": 0, "llm_merge": 0, "llm_no_merge": 0, "below_threshold": 0}
    for b in report.by_type.values():
        counts["auto_merge"] += b.auto_merges
        counts["llm_merge"] += b.llm_merges
        counts["llm_no_merge"] += b.llm_no_merges
        counts["below_threshold"] += b.below_threshold
    return counts


async def _tier_stats(driver: AsyncDriver) -> list[TierStat]:
    """Mean MERGE_INTO confidence per tier, read from the resolved graph."""
    query = (
        "MATCH ()-[r:MERGE_INTO]->() "
        "RETURN r.tier AS tier, count(*) AS merges, avg(r.confidence) AS mean_conf "
        "ORDER BY tier"
    )
    async with driver.session() as session:
        result = await session.run(query)
        rows = [
            TierStat(
                tier=int(record["tier"]),
                merges=int(record["merges"]),
                mean_confidence=float(record["mean_conf"] or 0.0),
            )
            async for record in result
        ]
    return rows


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------
DISCUSSION_MARKER = "<!-- DISCUSSION: replace this block with hand-written analysis -->"


def _metrics_row(label: str, m: Metrics) -> str:
    fmr = 1.0 - m.precision if (m.true_positives + m.false_positives) else 0.0
    mmr = 1.0 - m.recall if m.support else 0.0
    return (
        f"| {label} | {m.precision:.2f} | {m.recall:.2f} | {m.f1:.2f} | "
        f"{fmr:.2f} | {mmr:.2f} | {m.true_positives} | {m.false_positives} | {m.false_negatives} |"
    )


def render_resolution_report(result: ResolutionEvalResult, *, generated_at: str | None = None) -> str:
    """Render a Markdown report of one resolution eval run.

    Headline metrics, per-type breakdown, tier breakdown, and concrete correct/missed/false
    merge examples — then a hand-written Discussion marker for the author to fill (per the
    Phase 2B convention: numbers must be interpreted, not just pasted).
    """
    parts: list[str] = []
    parts.append("# Phase 3A — Entity-Resolution Eval Results\n")
    if generated_at:
        parts.append(f"_Generated: {generated_at}_\n")
    parts.append(
        f"Fragmented graph seeded from `ALIAS_GROUPS` + `LOOK_ALIKE_PAIRS`: "
        f"**{result.node_count} nodes**. Ground truth is `narrative.py` (ADR 0013). "
        f"Metrics are over unordered node pairs.\n"
    )

    parts.append("## Headline metrics\n")
    parts.append(
        "| Scope | Precision | Recall | F1 | False-merge | Missed-merge | TP | FP | FN |\n"
        "|-------|-----------|--------|----|-------------|--------------|----|----|----|"
    )
    rows = [_metrics_row("**Overall**", result.overall)]
    for type_name in sorted(result.by_type):
        rows.append(_metrics_row(type_name, result.by_type[type_name]))
    parts.append("\n".join(rows) + "\n")

    parts.append("## Tier breakdown\n")
    parts.append("| Tier | Merges | Mean confidence |\n|------|--------|-----------------|")
    tier_rows = [
        f"| {t.tier} | {t.merges} | {t.mean_confidence:.2f} |" for t in result.tier_stats
    ]
    parts.append("\n".join(tier_rows) if tier_rows else "_No merges._")
    parts.append(
        "\nDecision counts (all attempts): "
        + ", ".join(f"`{k}`={v}" for k, v in result.decision_counts.items())
        + ".\n"
    )
    parts.append(f"LLM (Tier 2) cost this run: **${result.llm_cost_usd:.4f}** "
                 "(sentence-transformers embeddings are free).\n")

    parts.append("## Correct merges (examples)\n")
    if result.correct_examples:
        parts.append("\n".join(f"- `{a}` ⇄ `{b}`" for a, b in result.correct_examples[:3]) + "\n")
    else:
        parts.append("_None._\n")

    parts.append("## False merges (examples)\n")
    if result.false_examples:
        parts.append(
            "\n".join(f"- `{a}` ⇄ `{b}` (should NOT have merged)" for a, b in result.false_examples)
            + "\n"
        )
    else:
        parts.append("**Zero false merges.** No pair was merged that ground truth says is distinct.\n")

    parts.append("## Missed merges (examples + diagnosis)\n")
    if result.missed_examples:
        parts.append(
            "\n".join(
                f"- `{a}` ⇄ `{b}` — diagnose: no Tier 1 rule fired and embedding similarity "
                f"stayed below the 0.75 adjudication floor."
                for a, b in result.missed_examples[:3]
            )
            + "\n"
        )
    else:
        parts.append("**Zero missed merges.** Every true alias pair was recovered.\n")

    parts.append("## Discussion\n")
    parts.append(DISCUSSION_MARKER + "\n")
    return "\n".join(parts) + "\n"
