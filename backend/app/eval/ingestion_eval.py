"""Ingestion eval for Phase 5A (ADR 0031).

Runs each hand-curated case in ``data/ingestion_eval_cases.json`` against the live populated
graph: insert the event, reconcile it, score the outcome against tolerant expectations
(extraction is stochastic, so we assert *label-level* node creation and status rather than exact
ids), and — for ``structural`` cases — confirm a Phase-4C structural tool's count moved in the
expected direction. Every case is **reverted** afterwards (its graph nodes/edges and Postgres
rows removed) so the eval is idempotent and the demo baseline (13 people, …) is preserved.

This is the "self-updating knowledge graph" thesis made measurable: ingest → the count changes →
the structural tool confirms it.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from app.db.repositories.events import EventRepository
from app.ingestion.api_router import _content_hash, _external_id  # noqa: PLC2701 — reuse id derivation
from app.ingestion.orchestrator import reconcile_event
from app.ingestion.schemas import IngestEventRequest
from app.models.enums import SourceType
from app.queries.enumerate import EnumerateInput, enumerate_by_type
from app.schemas.postgres import EventCreate

if TYPE_CHECKING:
    from neo4j import AsyncDriver
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.extraction.client import OpenRouterClient

log = structlog.get_logger(__name__)

_CASES_PATH = Path(__file__).resolve().parents[2] / "data" / "ingestion_eval_cases.json"


@dataclass
class CaseOutcome:
    """The scored result of one ingestion eval case."""

    case_id: str
    kind: str
    passed: bool
    status: str
    checks: dict[str, bool] = field(default_factory=dict)
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    notes: str = ""


@dataclass
class IngestionEvalResult:
    """Aggregate result across all cases."""

    outcomes: list[CaseOutcome] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        ok = sum(1 for o in self.outcomes if o.status in {"reconciled", "partial"})
        return ok / len(self.outcomes) if self.outcomes else 0.0

    @property
    def pass_rate(self) -> float:
        return (
            sum(1 for o in self.outcomes if o.passed) / len(self.outcomes)
            if self.outcomes
            else 0.0
        )

    @property
    def mean_latency_ms(self) -> float:
        runs = [o.latency_ms for o in self.outcomes if o.latency_ms > 0]
        return sum(runs) / len(runs) if runs else 0.0

    @property
    def mean_cost_usd(self) -> float:
        runs = [o.cost_usd for o in self.outcomes if o.cost_usd > 0]
        return sum(runs) / len(runs) if runs else 0.0


def load_cases(path: Path = _CASES_PATH) -> list[dict[str, Any]]:
    """Load the curated ingestion eval cases."""
    payload = json.loads(path.read_text())
    cases: list[dict[str, Any]] = payload["cases"]
    return cases


async def _person_count(driver: AsyncDriver, node_type: str) -> int:
    result = await enumerate_by_type(driver, EnumerateInput(node_type=node_type))  # type: ignore[arg-type]
    return result.value.total_count


async def _insert_event(
    session_factory: async_sessionmaker[AsyncSession], request: IngestEventRequest
) -> Any:
    source_type = SourceType(request.source_kind)
    content_hash = _content_hash(request.content)
    external_id = _external_id(request, content_hash)
    async with session_factory() as session:
        repo = EventRepository(session)
        existing = await repo.get_by_source(source_type, external_id)
        if existing is not None:
            return existing
        event = await repo.create(
            EventCreate(
                source_type=source_type,
                source_external_id=external_id,
                content=request.content,
                source_metadata={"source_ref": request.source_ref},
                created_at=request.occurred_at,
                content_hash=content_hash,
            )
        )
        await session.commit()
        return event


async def _revert_event(
    driver: AsyncDriver, session_factory: async_sessionmaker[AsyncSession], event_id: Any
) -> None:
    """Undo a case's graph + Postgres effects so the eval is idempotent and the baseline holds."""
    eid = str(event_id)
    async with driver.session() as session:
        await (
            await session.run("MATCH ()-[r {source_event_id: $eid}]->() DELETE r", eid=eid)
        ).consume()
        await (
            await session.run(
                "MATCH (n) WHERE n.source_event_ids = [$eid] DETACH DELETE n", eid=eid
            )
        ).consume()
        await (
            await session.run(
                "MATCH (n) WHERE $eid IN n.source_event_ids "
                "SET n.source_event_ids = [x IN n.source_event_ids WHERE x <> $eid]",
                eid=eid,
            )
        ).consume()
    from sqlalchemy import text

    async with session_factory() as session:
        for table in ("ingestion_runs", "extraction_runs", "event_embeddings"):
            await session.execute(text(f"DELETE FROM {table} WHERE event_id = :e"), {"e": event_id})
        await session.execute(text("DELETE FROM events WHERE id = :e"), {"e": event_id})
        await session.commit()


def _score(case: dict[str, Any], response: Any, structural_delta: int | None) -> CaseOutcome:
    """Apply a case's tolerant expectations to the reconciliation response."""
    expect = case["expect"]
    checks: dict[str, bool] = {}

    checks["status"] = response.status == expect.get("status", "reconciled")

    if "expect_label" in expect:
        labels = {n.label for n in response.nodes_created}
        checks["node_label"] = expect["expect_label"] in labels
    if "min_nodes" in expect:
        checks["min_nodes"] = len(response.nodes_created) >= expect["min_nodes"]
    if "max_nodes" in expect:
        checks["max_nodes"] = len(response.nodes_created) <= expect["max_nodes"]
    if "expect_contradiction" in expect:
        has = len(response.contradictions_detected) > 0
        checks["contradiction"] = has == expect["expect_contradiction"]
    if "stage_ok" in expect:
        by_name = {s.name: s.status for s in response.stages_run}
        checks["stages"] = all(by_name.get(n) == "ok" for n in expect["stage_ok"])
    if "structural" in expect and structural_delta is not None:
        checks["structural"] = structural_delta == expect["structural"]["delta"]

    passed = all(checks.values())
    return CaseOutcome(
        case_id=case["id"],
        kind=case["kind"],
        passed=passed,
        status=response.status,
        checks=checks,
        latency_ms=response.duration_ms,
        cost_usd=response.cost_usd,
    )


async def run_ingestion_eval(
    session_factory: async_sessionmaker[AsyncSession],
    driver: AsyncDriver,
    *,
    client: OpenRouterClient,
    cases: list[dict[str, Any]] | None = None,
) -> IngestionEvalResult:
    """Run every case against the live graph, scoring and reverting each."""
    cases = cases if cases is not None else load_cases()
    result = IngestionEvalResult()

    for case in cases:
        request = IngestEventRequest(**case["request"])
        structural = case["expect"].get("structural")
        node_type = structural["node_type"] if structural else None
        before = await _person_count(driver, node_type) if node_type else None

        event = await _insert_event(session_factory, request)
        try:
            t0 = time.monotonic()
            response = await reconcile_event(
                event.id, session_factory=session_factory, neo4j_driver=driver, client=client
            )
            wall = (time.monotonic() - t0) * 1000.0

            delta = None
            if node_type is not None and before is not None:
                after = await _person_count(driver, node_type)
                delta = after - before

            outcome = _score(case, response, delta)
            outcome.latency_ms = round(wall, 1)

            if case["kind"] == "idempotency":
                replay = await reconcile_event(
                    event.id, session_factory=session_factory, neo4j_driver=driver, client=client
                )
                outcome.checks["idempotent"] = bool(replay.deduplicated)
                outcome.passed = outcome.passed and outcome.checks["idempotent"]

            result.outcomes.append(outcome)
            log.info(
                "ingestion_eval_case",
                case=case["id"],
                passed=outcome.passed,
                status=outcome.status,
                checks=outcome.checks,
            )
        finally:
            await _revert_event(driver, session_factory, event.id)

    return result


_DISCUSSION_MARKER = "<!-- DISCUSSION: replace this block with hand-written analysis -->"


def render_report(result: IngestionEvalResult, *, generated_at: str | None = None) -> str:
    """Render a Markdown report of one ingestion-eval run."""
    parts: list[str] = ["# Phase 5A — Live Ingestion Eval\n"]
    if generated_at:
        parts.append(f"_Generated: {generated_at}_\n")
    parts.append(
        f"Ran **{len(result.outcomes)}** hand-curated cases against the live populated graph, "
        "scoring each and reverting its effects (idempotent). Extraction uses "
        "`claude-3.5-haiku`; expectations are label-level (extraction is stochastic).\n"
    )
    parts.append("## Headline metrics\n")
    parts.append(
        f"- **Ingestion success rate** (reconciled/partial): **{result.success_rate:.2%}** "
        "(target ≥ 0.90)\n"
        f"- **Case pass rate** (all checks): **{result.pass_rate:.2%}**\n"
        f"- **Mean ingestion latency**: **{result.mean_latency_ms:.0f} ms** (target ≤ 8000 ms)\n"
        f"- **Mean cost per ingestion**: **${result.mean_cost_usd:.4f}**\n"
    )
    parts.append("## Per-case results\n")
    parts.append("| Case | Kind | Pass | Status | Latency | Cost | Checks |")
    parts.append("|------|------|------|--------|---------|------|--------|")
    for o in result.outcomes:
        mark = "✅" if o.passed else "❌"
        checks = ", ".join(f"{k}={'✓' if v else '✗'}" for k, v in o.checks.items())
        parts.append(
            f"| `{o.case_id}` | {o.kind} | {mark} | {o.status} | "
            f"{o.latency_ms:.0f} ms | ${o.cost_usd:.4f} | {checks} |"
        )
    parts.append("")
    parts.append("## Discussion\n")
    parts.append(_DISCUSSION_MARKER + "\n")
    return "\n".join(parts) + "\n"
