"""In-memory metrics registry for the reconciliation engine (Phase 5B, ADR 0034).

The registry accumulates three kinds of signal as ingestion runs:

* **Counters** — total ingestions and a per-status breakdown (reconciled/partial/failed).
* **Histograms** — per-stage durations, per-event total duration, and per-event cost, kept as
  plain lists of floats and reduced to percentiles only when the ``/api/metrics`` endpoint reads
  them. At demo corpus scale (tens of ingestions) storing the raw samples is cheaper to reason
  about than maintaining streaming-percentile sketches, and it keeps the percentiles exact.
* **Adjudication counters** — how many resolution adjudications ran (by tier) and how many
  contradiction adjudications ran. This is what distinguishes "an ingestion that made 13 LLM
  calls" from "an ingestion that made 0", and it is the counter the parallel-resolution work
  (Decision 3) moves the needle on.

Why in-memory (ADR 0034): the writes happen in-process during reconciliation and the read path
is a single endpoint; a portfolio demo does not need a time-series database. The honest cost is
that the numbers reset on restart and do not aggregate across replicas — both documented, with
the Redis/Prometheus/OTel upgrade path, in ``docs/design/observability.md``.

Concurrency: every ``record_*`` method is synchronous (no ``await``), so under the app's
single-process asyncio event loop the read-modify-write of a counter or a ``list.append`` cannot
interleave with another coroutine. A multi-worker deployment would need per-worker registries
plus aggregation — part of the same production scaling path.
"""

from __future__ import annotations

import math

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Snapshot response models (the /api/metrics JSON shape, Decision 2)
# ---------------------------------------------------------------------------


class DurationStats(BaseModel):
    """Percentile summary of a duration histogram, in milliseconds."""

    p50: float
    p95: float
    max: float


class CostStats(BaseModel):
    """Summary of the per-ingestion cost histogram, in USD."""

    mean: float
    p95: float
    total: float


class IngestionMetrics(BaseModel):
    """Aggregate ingestion counters + duration/cost distributions."""

    total: int
    by_status: dict[str, int]
    duration_ms: DurationStats
    cost_usd: CostStats


class StageMetrics(BaseModel):
    """Per-stage call count + duration distribution."""

    count: int
    duration_ms: DurationStats


class AdjudicationMetrics(BaseModel):
    """LLM-adjudication counters for resolution (by tier) and contradiction."""

    resolution_total: int
    resolution_by_tier: dict[str, int]
    contradiction_total: int


class MetricsSnapshot(BaseModel):
    """The full metrics read model returned by ``GET /api/metrics``."""

    ingestion: IngestionMetrics
    stages: dict[str, StageMetrics]
    adjudications: AdjudicationMetrics


def _percentile(values: list[float], p: float) -> float:
    """Linear-interpolation percentile (numpy's default method), 0.0 for an empty list.

    ``p`` is in [0, 100]. With a single sample the percentile is that sample. The interpolation
    matches ``numpy.percentile(values, p)`` so the numbers are defensible and the unit tests can
    assert exact values against a hand-computed expectation.
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (p / 100.0)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[int(rank)]
    return ordered[low] * (high - rank) + ordered[high] * (rank - low)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _duration_stats(values: list[float]) -> DurationStats:
    return DurationStats(
        p50=round(_percentile(values, 50), 1),
        p95=round(_percentile(values, 95), 1),
        max=round(max(values), 1) if values else 0.0,
    )


class Metrics:
    """Process-local registry of reconciliation metrics.

    One module-level instance (``metrics``) is the single write seam; tests construct their own
    instances or call :meth:`reset`. All state is plain Python collections — see the module
    docstring for the in-memory/concurrency rationale.
    """

    def __init__(self) -> None:
        self.ingestion_total: int = 0
        self.ingestion_by_status: dict[str, int] = {}
        self.stage_duration_ms: dict[str, list[float]] = {}
        self.ingestion_duration_ms: list[float] = []
        self.ingestion_cost_usd: list[float] = []
        self.resolution_adjudications_total: int = 0
        self.resolution_adjudications_by_tier: dict[str, int] = {}
        self.contradiction_adjudications_total: int = 0

    # -- write path --------------------------------------------------------

    def record_stage(self, name: str, status: str, duration_ms: float) -> None:
        """Record one stage's duration. ``status`` is accepted for symmetry/future use.

        Every stage of every ingestion is recorded (ok/skipped/failed alike), so a stage's
        ``count`` equals the number of ingestions that reached it. ``status`` is not currently
        broken out in the snapshot — the per-stage status lives in the ``ingestion_runs`` audit
        row — but is part of the call so the histogram can be split by status later without a
        call-site change.
        """
        self.stage_duration_ms.setdefault(name, []).append(duration_ms)

    def record_ingestion(self, status: str, duration_ms: float, cost_usd: float) -> None:
        """Record one completed reconciliation's status, total duration, and cost.

        Called once per *worked* ingestion (the dedup/short-circuit path does no stages and is
        intentionally not recorded — it would skew the means toward zero).
        """
        self.ingestion_total += 1
        self.ingestion_by_status[status] = self.ingestion_by_status.get(status, 0) + 1
        self.ingestion_duration_ms.append(duration_ms)
        self.ingestion_cost_usd.append(cost_usd)

    def record_resolution(self, tier: int) -> None:
        """Record one resolution adjudication at the given tier (1 auto, 2 LLM, 3 below)."""
        self.resolution_adjudications_total += 1
        key = str(tier)
        self.resolution_adjudications_by_tier[key] = (
            self.resolution_adjudications_by_tier.get(key, 0) + 1
        )

    def record_contradiction(self) -> None:
        """Record one contradiction adjudication (a message×decision LLM judgement)."""
        self.contradiction_adjudications_total += 1

    def reset(self) -> None:
        """Clear all state. Used by tests and equivalent to a process restart."""
        self.ingestion_total = 0
        self.ingestion_by_status = {}
        self.stage_duration_ms = {}
        self.ingestion_duration_ms = []
        self.ingestion_cost_usd = []
        self.resolution_adjudications_total = 0
        self.resolution_adjudications_by_tier = {}
        self.contradiction_adjudications_total = 0

    # -- read path ---------------------------------------------------------

    def snapshot(self) -> MetricsSnapshot:
        """Reduce the accumulated samples to the JSON read model (percentiles computed here)."""
        ingestion = IngestionMetrics(
            total=self.ingestion_total,
            by_status=dict(self.ingestion_by_status),
            duration_ms=_duration_stats(self.ingestion_duration_ms),
            cost_usd=CostStats(
                mean=round(_mean(self.ingestion_cost_usd), 6),
                p95=round(_percentile(self.ingestion_cost_usd, 95), 6),
                total=round(sum(self.ingestion_cost_usd), 6),
            ),
        )
        stages = {
            name: StageMetrics(count=len(durations), duration_ms=_duration_stats(durations))
            for name, durations in sorted(self.stage_duration_ms.items())
        }
        adjudications = AdjudicationMetrics(
            resolution_total=self.resolution_adjudications_total,
            resolution_by_tier=dict(self.resolution_adjudications_by_tier),
            contradiction_total=self.contradiction_adjudications_total,
        )
        return MetricsSnapshot(ingestion=ingestion, stages=stages, adjudications=adjudications)


# The single process-wide registry. Imported as ``from app.observability import metrics``.
metrics = Metrics()
