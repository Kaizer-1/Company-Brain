"""System-metrics endpoint (Phase 5B, Decision 2).

GET /api/metrics
    Returns a JSON snapshot of the in-memory metrics registry: ingestion counters and
    duration/cost distributions, per-stage durations, and adjudication counters. JSON-only — no
    Prometheus exposition format (the demo wants the *shape* of metrics, not a scraper; ADR 0034).

The numbers are process-local and reset on restart; they reflect ingestions handled by *this*
backend process since it started. The persistent audit trail of every run lives in
``ingestion_runs`` (surfaced by ``GET /api/audit/ingestion-runs``); metrics and audit answer
different questions (rates/distributions vs. an inspectable per-run ledger).
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter

from app.observability import metrics
from app.observability.metrics import MetricsSnapshot

router = APIRouter(prefix="/api/metrics", tags=["metrics"])
log = structlog.get_logger(__name__)


@router.get(
    "",
    response_model=MetricsSnapshot,
    summary="In-memory reconciliation metrics: ingestion/stage distributions + adjudications.",
)
async def get_metrics() -> MetricsSnapshot:
    """Return the current metrics snapshot (percentiles computed at read time)."""
    snapshot = metrics.snapshot()
    log.info(
        "metrics_read",
        ingestion_total=snapshot.ingestion.total,
        resolution_adjudications=snapshot.adjudications.resolution_total,
    )
    return snapshot
