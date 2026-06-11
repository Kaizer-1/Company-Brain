"""Observability for the live-reconciliation engine (Phase 5B).

A small in-memory metrics layer that records per-stage latency, per-event totals, and
per-adjudication counters as the pipeline runs, and exposes them as a JSON snapshot at
``GET /api/metrics``. Deliberately *not* a Prometheus/Grafana stack — the demo audience needs
to *see* the system is measured (and that the measurement grounds the resolution optimisation),
not a production observability platform. The metrics are process-local and reset on restart;
the production scaling path (Redis / Prometheus / OTel) is documented in
``docs/design/observability.md`` and ADR 0034.

The module-level singleton ``metrics`` is the single write seam; the structured logs
(``structlog``) stay exactly as they were — metrics complement them, they do not replace them.
"""

from app.observability.metrics import Metrics, metrics

__all__ = ["Metrics", "metrics"]
