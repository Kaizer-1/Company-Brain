"""Live streaming ingestion + incremental reconciliation (Phase 5A).

This package turns the batch pipeline (``app.eval.query_eval``) into a per-event incremental
one. A new event arriving at ``POST /api/events`` is reconciled through the same stage order —
extract → embed → resolve → consolidate → project → temporal → contradiction — but scoped to
just that event, idempotently, with a full audit trail in ``ingestion_runs``.

Entry point: ``app.ingestion.orchestrator.reconcile_event``. Design: ADR 0031 (incremental
reconciliation), ADR 0032 (idempotency contract), ADR 0033 (single-writer lock).
"""
