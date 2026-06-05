"""Integration eval for the four killer queries (Phase 3B; ADR 0013 discipline).

This is the *end-to-end* eval: it runs the whole pipeline — wipe → seed events → extract →
embed events (Phase 3D) → resolve entities → consolidate decisions → project edges →
enrich temporal → ingest messages + detect contradictions → run each KQ → compare to expected.
(Temporal enrichment runs before contradiction detection so the detector sees normalised
decision statuses.) Even one wrong answer fails the demo, so the eval tests the full chain,
not isolated layers. Expected answers are hand-derived from ``narrative.py`` (the single
source of truth); partial credit is not allowed.

Extraction is stochastic; the eval defaults to ``claude-3.5-haiku`` (the highest-F1 model in the
2B comparison) so the demo is reliable (see docs/design/query-engine.md §8). Person checks are
cluster-aware: a surviving Person whose ``MERGE_INTO`` cluster contains the expected canonical
surface form counts as present, so the eval is robust to which surface form won resolution.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog

from app.contradiction.detector import detect_contradictions
from app.contradiction.message_ingest import ingest_messages
from app.db.repositories.events import EventRepository
from app.extraction.pipeline import ExtractionPipeline
from app.queries.kq1_multihop_ownership import find_chain_owner
from app.queries.kq2_temporal_contradiction import find_contradictions
from app.queries.kq3_blast_radius import compute_blast_radius
from app.queries.kq4_change_tracking import track_changes
from app.resolution.consolidator import consolidate_decisions
from app.resolution.projection import project_resolved_edges
from app.resolution.resolver import resolve_graph
from app.search.indexer import embed_events
from app.synthetic.generator import SyntheticDataGenerator
from app.synthetic.seeder import seed_postgres
from app.temporal.enricher import enrich_temporal

if TYPE_CHECKING:
    from neo4j import AsyncDriver
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.extraction.client import OpenRouterClient
    from app.queries.result_types import QueryProvenance

log = structlog.get_logger(__name__)

EVAL_MODEL = "anthropic/claude-3.5-haiku"
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

# Expected answers, hand-derived from narrative.py (KQ eval table in the design doc).
KQ1_DECISION = "D-0006"
KQ1_EXPECTED_OWNER = "diego-ramirez"
KQ1_EXPECTED_HOPS = 4
KQ2_EXPECTED_DECISION = "D-0005"
KQ3_SERVICE = "payments-api"
KQ3_MIN_SERVICES = 10
KQ3_EXPECTED_MEMBER = "web-storefront"  # transitively reachable (depth-4 chain member)
KQ4_TARGET = "auth-service"
KQ4_EXPECTED_DECISIONS = frozenset({"D-0006", "D-0007", "D-0008", "D-0010"})


@dataclass
class KQOutcome:
    """The pass/fail outcome of one killer query against its expected answer."""

    name: str
    question: str
    passed: bool
    expected: str
    actual: str
    provenance_valid: bool
    notes: str = ""


@dataclass
class QueryEvalResult:
    """Everything the Phase-3B query report needs."""

    outcomes: list[KQOutcome] = field(default_factory=list)
    model: str = EVAL_MODEL
    resolution_cost_usd: float = 0.0
    contradiction_cost_usd: float = 0.0
    runtime_seconds: float = 0.0
    event_count: int = 0

    @property
    def all_passed(self) -> bool:
        return bool(self.outcomes) and all(o.passed for o in self.outcomes)

    @property
    def total_cost_usd(self) -> float:
        return self.resolution_cost_usd + self.contradiction_cost_usd


async def run_query_eval(
    driver: AsyncDriver,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    client: OpenRouterClient | None = None,
    model: str = EVAL_MODEL,
    seed: int = 42,
) -> QueryEvalResult:
    """Run the full pipeline and score every KQ; returns a structured result."""
    started = time.monotonic()
    result = QueryEvalResult(model=model)

    await _wipe_graph(driver)
    event_count = await _seed_events(session_factory, seed=seed)
    result.event_count = event_count

    if client is None:
        log.warning("query_eval_no_client", note="extraction/contradiction require an API key")
        result.runtime_seconds = time.monotonic() - started
        return result

    # 1. Extract events -> graph.
    async with session_factory() as session:
        events = await EventRepository(session).list_since(_EPOCH)
    pipeline = ExtractionPipeline(
        session_factory=session_factory, neo4j_driver=driver, client=client, model=model
    )
    await pipeline.extract_all(events)

    # 1b. Embed events (Phase 3D — after extraction, before resolution).
    async with session_factory() as session:
        await embed_events(session)

    # 2. Resolve entities, 3. consolidate decisions, 4. project edges onto canonical winners.
    async with session_factory() as session:
        report = await resolve_graph(driver, session, client=client)
        await consolidate_decisions(driver, session)
        await session.commit()
    result.resolution_cost_usd = report.llm_cost_usd
    await project_resolved_edges(driver)

    # 5. Enrich temporal (valid_from/valid_to/status + SUPERSEDES). Runs BEFORE contradiction
    # detection so the detector sees normalised decision statuses (extraction leaves status
    # raw/missing; the detector filters on active decisions).
    async with session_factory() as session:
        await enrich_temporal(driver, session)

    # 6. Ingest messages + detect contradictions (KQ2 data path).
    async with session_factory() as session:
        await ingest_messages(driver, session)
    contra = await detect_contradictions(driver, client=client)
    result.contradiction_cost_usd = contra.llm_cost_usd

    # 7. Run + score every KQ.
    async with session_factory() as session:
        events_repo = EventRepository(session)
        result.outcomes.append(await _score_kq1(driver, events_repo))
        result.outcomes.append(await _score_kq2(driver, events_repo))
        result.outcomes.append(await _score_kq3(driver, events_repo))
        result.outcomes.append(await _score_kq4(driver, events_repo))

    result.runtime_seconds = time.monotonic() - started
    log.info("query_eval_complete", all_passed=result.all_passed, runtime=result.runtime_seconds)
    return result


# ---------------------------------------------------------------------------
# Pipeline setup
# ---------------------------------------------------------------------------
async def _wipe_graph(driver: AsyncDriver) -> None:
    async with driver.session() as session:
        await (await session.run("MATCH (n) WHERE NOT n:_Migration DETACH DELETE n")).consume()


async def _seed_events(session_factory: async_sessionmaker[AsyncSession], *, seed: int) -> int:
    """Seed the corpus idempotently; return the total events available (not just new inserts)."""
    events = SyntheticDataGenerator(seed=seed).generate()
    async with session_factory() as session:
        repo = EventRepository(session)
        await seed_postgres(repo, events)
        await session.commit()
        total = await repo.list_since(_EPOCH)
    return len(total)


# ---------------------------------------------------------------------------
# Provenance validation
# ---------------------------------------------------------------------------
async def _provenance_valid(events: EventRepository, provenance: QueryProvenance) -> bool:
    """True if every event id in the provenance resolves to a Postgres event (and there is ≥1)."""
    import uuid

    ids = provenance.all_event_ids
    if not ids:
        return False
    for raw in ids:
        try:
            event_uuid = uuid.UUID(raw)
        except (ValueError, AttributeError):
            return False
        if await events.get_by_id(event_uuid) is None:
            return False
    return True


async def _person_represented(driver: AsyncDriver, people: list[str], expected: str) -> bool:
    """True if any surviving Person in ``people`` is the expected entity (cluster-aware)."""
    if expected in people:
        return True
    query = (
        "MATCH (p:Person) WHERE p.canonical_id IN $people "
        "OPTIONAL MATCH (loser:Person)-[:MERGE_INTO*]->(p) "
        "RETURN collect(DISTINCT loser.canonical_id) AS losers"
    )
    async with driver.session() as session:
        record = await (await session.run(query, people=people)).single()
    losers = record["losers"] if record else []
    return expected in [str(x) for x in losers if x]


# ---------------------------------------------------------------------------
# Per-KQ scoring
# ---------------------------------------------------------------------------
async def _score_kq1(driver: AsyncDriver, events: EventRepository) -> KQOutcome:
    res = await find_chain_owner(driver, decision_id=KQ1_DECISION)
    owner_ok = await _person_represented(driver, res.value.owner_people, KQ1_EXPECTED_OWNER)
    max_hops = max((c.hops for c in res.value.chains), default=0)
    prov_ok = await _provenance_valid(events, res.provenance)
    passed = owner_ok and max_hops >= KQ1_EXPECTED_HOPS - 1  # 3 (direct) or 4 (via team)
    return KQOutcome(
        name="KQ1",
        question=f"Who owns the service depending on the system deprecated by {KQ1_DECISION}?",
        passed=passed and prov_ok,
        expected=f"owner={KQ1_EXPECTED_OWNER}, chain≈{KQ1_EXPECTED_HOPS} hops",
        actual=f"owners={res.value.owner_people}, max_hops={max_hops}",
        provenance_valid=prov_ok,
        notes="" if owner_ok else "expected owner not represented in any chain",
    )


async def _score_kq2(driver: AsyncDriver, events: EventRepository) -> KQOutcome:
    res = await find_contradictions(driver, window=timedelta(days=30))
    decisions = {c.decision_id for c in res.value}
    found = KQ2_EXPECTED_DECISION in decisions
    prov_ok = await _provenance_valid(events, res.provenance)
    return KQOutcome(
        name="KQ2",
        question="Which active decisions are contradicted by discussions in the last 30 days?",
        passed=found and prov_ok,
        expected=f"≥1 contradiction incl. {KQ2_EXPECTED_DECISION}",
        actual=f"contradicted decisions={sorted(decisions)}",
        provenance_valid=prov_ok,
        notes="" if found else "expected D-0005 contradiction not detected",
    )


async def _score_kq3(driver: AsyncDriver, events: EventRepository) -> KQOutcome:
    res = await compute_blast_radius(driver, service_name=KQ3_SERVICE, max_depth=5)
    services = set(res.value.affected_services)
    count_ok = len(services) >= KQ3_MIN_SERVICES
    member_ok = KQ3_EXPECTED_MEMBER in services
    prov_ok = await _provenance_valid(events, res.provenance)
    return KQOutcome(
        name="KQ3",
        question=f"If {KQ3_SERVICE} fails, which services/people/decisions are affected?",
        passed=count_ok and member_ok and prov_ok,
        expected=f"≥{KQ3_MIN_SERVICES} services incl. {KQ3_EXPECTED_MEMBER}",
        actual=f"{len(services)} services, depth={res.value.max_depth_reached}, "
        f"people={len(res.value.affected_people)}, decisions={len(res.value.affected_decisions)}",
        provenance_valid=prov_ok,
        notes="" if member_ok else f"{KQ3_EXPECTED_MEMBER} missing from blast radius",
    )


async def _score_kq4(driver: AsyncDriver, events: EventRepository) -> KQOutcome:
    res = await track_changes(driver, target_name=KQ4_TARGET, window=timedelta(days=90))
    found = {c.decision_id for c in res.value.changes}
    have_all = found >= KQ4_EXPECTED_DECISIONS
    has_approvers = all(c.approvers for c in res.value.changes) and bool(res.value.changes)
    prov_ok = await _provenance_valid(events, res.provenance)
    return KQOutcome(
        name="KQ4",
        question=f"What changed about {KQ4_TARGET} in the last quarter, and who approved each?",
        passed=have_all and has_approvers and prov_ok,
        expected=f"⊇ {sorted(KQ4_EXPECTED_DECISIONS)}, each with approvers",
        actual=f"decisions={sorted(found)}",
        provenance_valid=prov_ok,
        notes="" if have_all else f"missing {sorted(KQ4_EXPECTED_DECISIONS - found)}",
    )


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------
DISCUSSION_MARKER = "<!-- DISCUSSION: replace this block with hand-written analysis -->"


def render_query_report(result: QueryEvalResult, *, generated_at: str | None = None) -> str:
    """Render a Markdown report of one integration-eval run."""
    parts: list[str] = ["# Phase 3B — Killer-Query Integration Eval\n"]
    if generated_at:
        parts.append(f"_Generated: {generated_at}_\n")
    parts.append(
        f"Full pipeline: seed → extract ({result.model}) → resolve → consolidate → project → "
        f"temporal → messages+contradictions → query. Expected answers from `narrative.py` "
        f"(ADR 0013); no partial credit. **{result.event_count} events.**\n"
    )

    status = "✅ ALL PASS" if result.all_passed else "❌ FAILURES"
    parts.append(f"## Result: {status}\n")
    parts.append(
        "| KQ | Question | Pass | Expected | Actual | Provenance |\n"
        "|----|----------|------|----------|--------|------------|"
    )
    for o in result.outcomes:
        mark = "✅" if o.passed else "❌"
        prov = "valid" if o.provenance_valid else "INVALID"
        q = o.question.replace("|", "\\|")
        parts.append(
            f"| {o.name} | {q} | {mark} | {o.expected} | {o.actual} | {prov} |"
        )
    parts.append("")

    failed = [o for o in result.outcomes if not o.passed]
    if failed:
        parts.append("## Failure notes\n")
        for o in failed:
            parts.append(f"- **{o.name}**: {o.notes or 'see expected vs actual above'}")
        parts.append("")

    parts.append("## Cost & runtime\n")
    parts.append(
        f"- Resolution (Tier-2 adjudication) cost: **${result.resolution_cost_usd:.4f}**\n"
        f"- Contradiction detection cost: **${result.contradiction_cost_usd:.4f}**\n"
        f"- (Extraction cost is logged per call by the OpenRouter client; see run logs.)\n"
        f"- Total runtime: **{result.runtime_seconds:.1f}s**\n"
    )

    parts.append("## Discussion\n")
    parts.append(DISCUSSION_MARKER + "\n")
    return "\n".join(parts) + "\n"
