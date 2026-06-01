"""The adversarial planted cases, expressed as data.

Each case is a deliberate trap designed (by a human, before any generator code —
see ADR 0011) to stress a specific later phase. Every case carries a ``kq`` field
naming the killer query whose answer depends on it; the entity-resolution traps name
the killer query whose answer breaks if the entity is not resolved. The generator in
``generator.py`` renders these into varied natural-language events; it does not invent
them. ``backend/tests/synthetic/test_narrative.py`` asserts this inventory matches the
promises in ``docs/design/synthetic-company.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

KQ = Literal["KQ1", "KQ2", "KQ3", "KQ4"]
EntityKind = Literal["person", "service"]


# ---------------------------------------------------------------------------
# Entity-resolution traps (stress Phase 3B)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AliasGroup:
    """One entity, many surface forms — the canonical entity-resolution trap.

    ``surface_forms`` are the textual forms that MUST appear somewhere in the corpus;
    the generator picks among them when mentioning the entity. ``kq`` names the killer
    query whose answer depends on collapsing these forms onto one node.
    """

    kq: KQ
    entity_kind: EntityKind
    canonical: str
    surface_forms: tuple[str, ...]
    note: str


@dataclass(frozen=True)
class LookAlikePair:
    """Two genuinely-different services with confusingly-similar names.

    The trap is the opposite of an AliasGroup: a careless reader (or LLM) MERGES these,
    which corrupts KQ3's blast radius. The corpus must keep them distinct.
    """

    kq: KQ
    service_a: str
    service_b: str
    note: str


# ---------------------------------------------------------------------------
# KQ1 — multi-hop ownership
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class DeprecationChain:
    """Decision → System → Service → Team/Person, reconstructible only by traversal.

    Tests KQ1: who owns the service that depends on the system deprecated by Decision X?
    The links are deliberately spread across sources so no single document answers it.
    """

    kq: KQ
    decision_id: str
    deprecated_system: str
    dependent_service: str
    owning_team: str
    owner_person: str
    secondary_dependents: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# KQ2 — temporal contradiction
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ContradictionPair:
    """An active decision contradicted by a recent discussion, with no supersession.

    Tests KQ2: which active decisions are contradicted by discussions in the last month?
    The contradiction is real and detectable; the absence of a superseding decision is
    the whole point.
    """

    kq: KQ
    decision_id: str
    decision_claim: str
    contradiction_claim: str
    contradicting_handles: tuple[str, ...]
    decision_age_days: int
    discussion_age_days: int


# ---------------------------------------------------------------------------
# KQ3 — blast radius (depth + branching)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class DependencyEdge:
    """``upstream`` DEPENDS_ON ``downstream`` (upstream breaks if downstream breaks)."""

    upstream: str
    downstream: str
    downstream_is_system: bool = False


@dataclass(frozen=True)
class DependencyGraph:
    """The DEPENDS_ON graph plus the named depth-≥4 chain.

    Tests KQ3: blast radius from ``seed_service`` (its transitive upstream dependents) and
    a depth-≥4 dependency path. Each edge is asserted in at least one generated event.
    """

    kq: KQ
    seed_service: str
    edges: tuple[DependencyEdge, ...]
    deep_chain: tuple[str, ...]


def dependents_of(graph: DependencyGraph, node: str) -> frozenset[str]:
    """Direct upstreams: services that DEPEND_ON ``node``."""
    return frozenset(e.upstream for e in graph.edges if e.downstream == node)


def blast_radius(graph: DependencyGraph, seed: str) -> frozenset[str]:
    """All services that transitively depend on ``seed`` (the KQ3 answer set)."""
    found: set[str] = set()
    stack = [seed]
    while stack:
        current = stack.pop()
        for dependent in sorted(dependents_of(graph, current)):
            if dependent not in found:
                found.add(dependent)
                stack.append(dependent)
    return frozenset(found)


def max_dependency_depth(graph: DependencyGraph) -> int:
    """Longest DEPENDS_ON path length (in edges) across the whole DAG."""
    downstream: dict[str, list[str]] = {}
    for e in graph.edges:
        downstream.setdefault(e.upstream, []).append(e.downstream)

    memo: dict[str, int] = {}

    def depth(node: str) -> int:
        if node in memo:
            return memo[node]
        best = 0
        for nxt in downstream.get(node, []):
            best = max(best, 1 + depth(nxt))
        memo[node] = best
        return best

    nodes = {e.upstream for e in graph.edges} | {e.downstream for e in graph.edges}
    return max((depth(n) for n in nodes), default=0)


# ---------------------------------------------------------------------------
# KQ4 — provenance + change tracking
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ChangeTimeline:
    """A multi-month change timeline for one subject, with approvers and a supersession.

    Tests KQ4: what changed about the auth system this quarter, and who approved each?
    ``decision_ids`` reference decisions in ``company.py`` (single source of truth for
    approvers and dates); ``supersession`` is the (newer, older) pair carrying the
    textual ``supersedes`` signal.
    """

    kq: KQ
    subject: str
    decision_ids: tuple[str, ...]
    supersession: tuple[str, str]  # (superseding_id, superseded_id)


# ---------------------------------------------------------------------------
# Bonus messiness
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class OwnershipAmbiguity:
    """A service two sources assign to different teams; authority resolves it.

    Tests KQ1: ownership must still resolve correctly (decision/catalog beats stale Slack),
    but the ambiguity is detectable.
    """

    kq: KQ
    service: str
    authoritative_team: str
    contested_team: str


@dataclass(frozen=True)
class StaleDoc:
    """A wiki page whose content is now wrong; the old timestamp reveals the staleness."""

    kq: KQ
    topic: str
    stale_claim: str
    age_days: int
    contradicted_by: str


@dataclass(frozen=True)
class DepartureTransfer:
    """A person who left mid-history; ownership of an asset transferred to a successor."""

    kq: KQ
    person_left: str
    successor: str
    asset: str


# ---------------------------------------------------------------------------
# The locked planted-case inventory. Mirrors §6 of synthetic-company.md.
# ---------------------------------------------------------------------------

ALIAS_GROUPS: tuple[AliasGroup, ...] = (
    AliasGroup(
        "KQ4", "person", "alice-chen",
        ("Alice Chen", "alice.chen@northwind.io", "@alice", "Al"),
        "Full name, email, handle, and nickname 'Al' — KQ4 approver attribution.",
    ),
    AliasGroup(
        "KQ1", "person", "diego-ramirez",
        ("Diego Ramirez", "@diego", "the payments lead", "Payments' tech lead"),
        "Named in some events, title-only in others — KQ1 ownership answer.",
    ),
    AliasGroup(
        "KQ4", "person", "ben-smith",
        ("Ben Smith", "ben.smith@northwind.io", "@ben", "@bsmith"),
        "Handle changed @bsmith → @ben mid-history — KQ4 approver merge.",
    ),
    AliasGroup(
        "KQ4", "service", "auth-service",
        ("auth-service", "AuthSvc", "the auth service", "the auth system"),
        "Canonical, abbreviation, descriptive — KQ4 change-tracking subject.",
    ),
    AliasGroup(
        "KQ3", "service", "payments-api",
        ("payments-api", "the Payments team's API", "@payments' service", "payments"),
        "Team-coupled phrasings — KQ3 blast-radius seed.",
    ),
    AliasGroup(
        "KQ3", "service", "billing-v2",
        ("billing-v2", "legacy-billing", "the billing service"),
        "Renamed from legacy-billing — blast radius must not split it in two.",
    ),
)

LOOK_ALIKE_PAIRS: tuple[LookAlikePair, ...] = (
    LookAlikePair(
        "KQ3", "notifications-api", "notification-worker",
        "Request-accepting API vs delivery worker — different services, look-alike names.",
    ),
)

DEPRECATION_CHAINS: tuple[DeprecationChain, ...] = (
    DeprecationChain(
        "KQ1", "D-0006", "legacy-auth", "payments-api", "payments", "diego-ramirez",
        secondary_dependents=("subscriptions-service",),
    ),
)

CONTRADICTION_PAIRS: tuple[ContradictionPair, ...] = (
    ContradictionPair(
        "KQ2", "D-0005",
        "new payment integrations stay on legacy-auth through year-end",
        "new integrations must not use legacy-auth — it is deprecated; use auth-service now",
        ("@alice", "@iris"),
        decision_age_days=120,
        discussion_age_days=22,
    ),
)

DEPENDENCY_GRAPH = DependencyGraph(
    "KQ3",
    "payments-api",
    edges=(
        DependencyEdge("payments-api", "auth-service"),
        DependencyEdge("payments-api", "legacy-auth", downstream_is_system=True),
        DependencyEdge("payments-api", "primary-db", downstream_is_system=True),
        DependencyEdge("auth-service", "user-store", downstream_is_system=True),
        DependencyEdge("auth-service", "primary-db", downstream_is_system=True),
        DependencyEdge("checkout-service", "payments-api"),
        DependencyEdge("billing-v2", "payments-api"),
        DependencyEdge("payouts-service", "payments-api"),
        DependencyEdge("subscriptions-service", "payments-api"),
        DependencyEdge("subscriptions-service", "legacy-auth", downstream_is_system=True),
        DependencyEdge("notifications-api", "payments-api"),
        DependencyEdge("reporting-api", "payments-api"),
        DependencyEdge("web-storefront", "checkout-service"),
        DependencyEdge("merchant-dashboard", "billing-v2"),
        DependencyEdge("merchant-dashboard", "payouts-service"),
        DependencyEdge("invoicing-service", "billing-v2"),
        DependencyEdge("notification-worker", "notifications-api"),
        DependencyEdge("notification-worker", "event-bus", downstream_is_system=True),
        DependencyEdge("reporting-api", "primary-db", downstream_is_system=True),
    ),
    deep_chain=("web-storefront", "checkout-service", "payments-api", "auth-service", "user-store"),
)

CHANGE_TIMELINES: tuple[ChangeTimeline, ...] = (
    ChangeTimeline(
        "KQ4", "auth-service",
        decision_ids=("D-0004", "D-0006", "D-0007", "D-0008", "D-0010"),
        supersession=("D-0010", "D-0004"),
    ),
)

OWNERSHIP_AMBIGUITIES: tuple[OwnershipAmbiguity, ...] = (
    OwnershipAmbiguity("KQ1", "reporting-api", authoritative_team="data", contested_team="growth"),
)

STALE_DOCS: tuple[StaleDoc, ...] = (
    StaleDoc(
        "KQ2", "core-monolith billing",
        "build all new billing logic inside core-monolith",
        age_days=240, contradicted_by="D-0003",
    ),
    StaleDoc(
        "KQ1", "legacy-auth integration",
        "legacy-auth is the standard for service authentication",
        age_days=240, contradicted_by="D-0006",
    ),
)

DEPARTURE_TRANSFERS: tuple[DepartureTransfer, ...] = (
    DepartureTransfer("KQ1", "bob-tanaka", "carol-nwosu", "billing-v2"),
)


def all_planted_cases() -> tuple[object, ...]:
    """Every planted case as a flat tuple — used by tests to assert each has a kq."""
    return (
        *ALIAS_GROUPS,
        *LOOK_ALIKE_PAIRS,
        *DEPRECATION_CHAINS,
        *CONTRADICTION_PAIRS,
        DEPENDENCY_GRAPH,
        *CHANGE_TIMELINES,
        *OWNERSHIP_AMBIGUITIES,
        *STALE_DOCS,
        *DEPARTURE_TRANSFERS,
    )
