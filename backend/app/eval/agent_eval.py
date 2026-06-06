"""Phase 4A agent eval.

Runs each hand-curated question through ``run_agent`` and scores six things honestly:

* **route accuracy** — did the router pick the expected tool?
* **citation overlap** — Jaccard between the agent's actual citations and the *gold* set.
  For a KQ question the gold set is the typed query's own provenance: a correct grounded
  answer should cite exactly the events the typed traversal says justify the answer. The
  eval computes the gold on the fly (calling the same typed function the tool node calls)
  so it needs no brittle hard-coded UUIDs — event ids are random per seed.
* **provenance verification rate** — fraction of *synthesised* answers that passed
  ``verify_provenance`` on the first try (verified and retry_count == 0).
* **refusal correctness** — fraction of out-of-scope questions routed to ``unknown``.
* **mean cost / question** (USD) and **mean latency / question** (ms) — reported, not gated.

The eval reuses the deployed code path end-to-end (``run_agent``); it does not re-implement
the graph. Extraction/answer generation is stochastic, so numbers are reported honestly with
a failure-mode discussion (see docs/eval/phase-4a-agent-results.md).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import structlog

from app.agent.runner import run_agent
from app.queries import (
    AggregateInput,
    EnumerateInput,
    GetEntityInput,
    NeighborsInput,
    aggregate_by_type,
    enumerate_by_type,
    get_entity,
    neighbors_of_entity,
)
from app.queries.kq1_multihop_ownership import find_chain_owner
from app.queries.kq2_temporal_contradiction import find_contradictions
from app.queries.kq3_blast_radius import compute_blast_radius
from app.queries.kq4_change_tracking import track_changes

# Routes for which a gold citation set is derivable by re-running the typed query.
_CITABLE_ROUTES = frozenset(
    {"kq1", "kq2", "kq3", "kq4", "get_entity", "neighbors", "enumerate"}
)
# Structural routes whose results may legitimately carry no source events (ADR 0030).
_STRUCTURAL_ROUTES = frozenset({"get_entity", "neighbors", "enumerate", "aggregate"})

if TYPE_CHECKING:
    from pathlib import Path

    from neo4j import AsyncDriver
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.extraction.client import OpenRouterClient

log = structlog.get_logger(__name__)


@dataclass
class QuestionResult:
    """Per-question eval outcome."""

    id: str
    question: str
    expected_route: str
    actual_route: str
    route_correct: bool
    citations: list[str]
    gold_citations: list[str] | None  # None for search/unknown (no gold)
    citation_jaccard: float | None
    synthesized: bool  # an answer was generated (not unknown / not empty result)
    verified_first_try: bool
    retry_count: int
    error: str | None
    cost_usd: float
    latency_ms: float


@dataclass
class AgentEvalReport:
    """Aggregate metrics across all questions."""

    results: list[QuestionResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def route_accuracy(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.route_correct for r in self.results) / len(self.results)

    @property
    def citation_overlap_mean(self) -> float:
        scored = [r.citation_jaccard for r in self.results if r.citation_jaccard is not None]
        return sum(scored) / len(scored) if scored else 0.0

    @property
    def provenance_verification_rate(self) -> float:
        synth = [r for r in self.results if r.synthesized]
        if not synth:
            return 0.0
        return sum(r.verified_first_try for r in synth) / len(synth)

    @property
    def refusal_correctness(self) -> float:
        unknowns = [r for r in self.results if r.expected_route == "unknown"]
        if not unknowns:
            return 0.0
        return sum(r.actual_route == "unknown" for r in unknowns) / len(unknowns)

    @property
    def mean_cost_usd(self) -> float:
        return sum(r.cost_usd for r in self.results) / len(self.results) if self.results else 0.0

    @property
    def mean_latency_ms(self) -> float:
        return sum(r.latency_ms for r in self.results) / len(self.results) if self.results else 0.0

    def route_accuracy_for(self, routes: set[str]) -> float:
        """Route accuracy restricted to questions whose expected route is in ``routes``."""
        subset = [r for r in self.results if r.expected_route in routes]
        if not subset:
            return 0.0
        return sum(r.route_correct for r in subset) / len(subset)

    @property
    def new_tool_accuracy(self) -> float:
        """Route accuracy across just the four Phase 4C structural routes (target ≥ 0.90)."""
        return self.route_accuracy_for(set(_STRUCTURAL_ROUTES))

    def per_route_accuracy(self) -> dict[str, tuple[int, int]]:
        """Map each expected route to (correct, total) for a per-route breakdown table."""
        out: dict[str, tuple[int, int]] = {}
        for r in self.results:
            correct, total = out.get(r.expected_route, (0, 0))
            out[r.expected_route] = (correct + int(r.route_correct), total + 1)
        return out


def load_questions(path: Path) -> list[dict[str, Any]]:
    """Load the hand-curated question set."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data["questions"])


async def _gold_citations(
    route: str, tool_input: dict[str, Any], driver: AsyncDriver
) -> list[str]:
    """Compute the gold citation set for a KQ question by calling the typed query directly."""
    if route == "kq1":
        r1 = await find_chain_owner(driver, decision_id=str(tool_input["decision_id"]))
        return list(r1.provenance.all_event_ids)
    if route == "kq2":
        r2 = await find_contradictions(
            driver, window=timedelta(days=int(tool_input.get("window_days", 30)))
        )
        return list(r2.provenance.all_event_ids)
    if route == "kq3":
        r3 = await compute_blast_radius(driver, service_name=str(tool_input["service"]))
        return list(r3.provenance.all_event_ids)
    if route == "kq4":
        r4 = await track_changes(
            driver,
            target_name=str(tool_input["target"]),
            window=timedelta(days=int(tool_input.get("window_days", 90))),
        )
        return list(r4.provenance.all_event_ids)
    if route == "get_entity":
        rg = await get_entity(driver, GetEntityInput.model_validate(tool_input))
        return list(rg.provenance.all_event_ids)
    if route == "neighbors":
        rn = await neighbors_of_entity(driver, NeighborsInput.model_validate(tool_input))
        return list(rn.provenance.all_event_ids)
    if route == "enumerate":
        re_ = await enumerate_by_type(driver, EnumerateInput.model_validate(tool_input))
        return list(re_.provenance.all_event_ids)
    if route == "aggregate":
        # Aggregates have no source events by design (ADR 0030) — no citation gold.
        await aggregate_by_type(driver, AggregateInput.model_validate(tool_input))
        return []
    return []


def _jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard similarity. Two empty sets are defined as 1.0 (both correctly cite nothing)."""
    if not a and not b:
        return 1.0
    union = a | b
    return len(a & b) / len(union) if union else 1.0


async def evaluate_question(
    q: dict[str, Any],
    *,
    neo4j_driver: AsyncDriver,
    session_factory: async_sessionmaker[AsyncSession],
    client: OpenRouterClient,
) -> QuestionResult:
    """Run one question through the agent and score it."""
    t0 = time.monotonic()
    resp = await run_agent(
        q["question"],
        neo4j_driver=neo4j_driver,
        session_factory=session_factory,
        debug=True,
        client=client,
    )
    latency_ms = (time.monotonic() - t0) * 1000

    expected_route = q["expected_route"]
    actual_route = resp.route
    actual_citations = [c.event_id for c in resp.citations]

    gold: list[str] | None = None
    jaccard: float | None = None
    if expected_route in _CITABLE_ROUTES:
        gold = await _gold_citations(expected_route, q.get("expected_tool_input", {}), neo4j_driver)
        is_kq = expected_route in {"kq1", "kq2", "kq3", "kq4"}
        # KQs are always scored (an empty gold means "should cite nothing"); structural
        # routes are scored only when a gold set exists — an event-less structural answer
        # (e.g. an aggregate) is excluded from the citation-overlap metric (ADR 0030).
        if is_kq or gold:
            jaccard = _jaccard(set(actual_citations), set(gold))

    dbg = resp.debug
    synthesized = actual_route != "unknown" and bool(dbg and dbg.available_event_ids)

    return QuestionResult(
        id=q["id"],
        question=q["question"],
        expected_route=expected_route,
        actual_route=actual_route,
        route_correct=actual_route == expected_route,
        citations=actual_citations,
        gold_citations=gold,
        citation_jaccard=jaccard,
        synthesized=synthesized,
        verified_first_try=bool(dbg and dbg.verified and dbg.retry_count == 0),
        retry_count=dbg.retry_count if dbg else 0,
        error=resp.error,
        cost_usd=dbg.cost_usd if dbg else 0.0,
        latency_ms=latency_ms,
    )


async def run_agent_eval(
    questions: list[dict[str, Any]],
    *,
    neo4j_driver: AsyncDriver,
    session_factory: async_sessionmaker[AsyncSession],
    client: OpenRouterClient,
) -> AgentEvalReport:
    """Evaluate every question sequentially (cost-logged) and return the aggregate report."""
    report = AgentEvalReport()
    for q in questions:
        result = await evaluate_question(
            q, neo4j_driver=neo4j_driver, session_factory=session_factory, client=client
        )
        report.results.append(result)
        log.info(
            "agent_eval_q",
            id=result.id,
            expected=result.expected_route,
            actual=result.actual_route,
            correct=result.route_correct,
            jaccard=result.citation_jaccard,
            verified=result.verified_first_try,
            cost=round(result.cost_usd, 6),
            ms=round(result.latency_ms, 0),
        )
    return report


def render_agent_report(report: AgentEvalReport) -> str:
    """Render the eval report as Markdown with a per-question table and the headline metrics."""
    lines: list[str] = []
    lines.append("# Agent Eval Results\n")
    lines.append("> Generated by `backend/scripts/run_agent_eval.py`. Real numbers; no cherry-picking.\n")

    lines.append("## Headline metrics\n")
    lines.append("| Metric | Value | Target |")
    lines.append("|--------|-------|--------|")
    lines.append(f"| Route accuracy (all) | {report.route_accuracy:.3f} | ≥ 0.85 |")
    lines.append(f"| Route accuracy (structural tools only) | {report.new_tool_accuracy:.3f} | ≥ 0.90 |")
    lines.append(f"| Citation overlap (mean Jaccard, citable Qs) | {report.citation_overlap_mean:.3f} | ≥ 0.50 |")
    lines.append(f"| Provenance verification rate (1st try) | {report.provenance_verification_rate:.3f} | ≥ 0.80 |")
    lines.append(f"| Refusal correctness | {report.refusal_correctness:.3f} | ≥ 0.80 |")
    lines.append(f"| Mean cost / question (USD) | ${report.mean_cost_usd:.5f} | report |")
    lines.append(f"| Mean latency / question (ms) | {report.mean_latency_ms:.0f} | ≤ 4000 |")
    lines.append("")

    lines.append("## Per-route accuracy\n")
    lines.append("| route | correct / total |")
    lines.append("|-------|-----------------|")
    for route, (correct, total) in sorted(report.per_route_accuracy().items()):
        lines.append(f"| {route} | {correct} / {total} |")
    lines.append("")

    lines.append("## Per-question results\n")
    lines.append("| id | expected | actual | ✓ | jaccard | verified | retries | cost | ms |")
    lines.append("|----|----------|--------|---|---------|----------|---------|------|----|")
    for r in report.results:
        jac = f"{r.citation_jaccard:.2f}" if r.citation_jaccard is not None else "—"
        ver = "✓" if r.verified_first_try else ("—" if not r.synthesized else "✗")
        lines.append(
            f"| {r.id} | {r.expected_route} | {r.actual_route} | "
            f"{'✓' if r.route_correct else '✗'} | {jac} | {ver} | {r.retry_count} | "
            f"${r.cost_usd:.5f} | {r.latency_ms:.0f} |"
        )
    lines.append("")

    misroutes = [r for r in report.results if not r.route_correct]
    if misroutes:
        lines.append("## Misroutes\n")
        for r in misroutes:
            lines.append(f"- **{r.id}** expected `{r.expected_route}`, got `{r.actual_route}` — {r.question}")
        lines.append("")

    return "\n".join(lines)
