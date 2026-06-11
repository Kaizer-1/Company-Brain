# ADR 0032 — The Idempotency Contract for Live Ingestion

## Status

Accepted

## Context

Demos fail in predictable ways: the network drops, the user double-clicks submit, a worker hangs
and the request is retried. Replays are also routine — if reconciliation logic changes in a future
phase, we will want to re-process old events. So "ingesting the same event twice produces the same
end state" is not a nice-to-have; it is the property that lets every other guarantee hold. The
challenge is that the pipeline mixes idempotent graph writes (Neo4j `MERGE`) with **append-only**
audit logs (`merge_decisions` has no pair-dedup; `extraction_runs` appends a row per attempt), so
"identical state" needs a precise definition.

## Decision

**Define idempotency as a layered contract and enforce it primarily at the orchestration boundary,
not by making every append-only log dedup itself.**

1. **Endpoint dedup** — `POST /api/events` keys on `(source_type, source_external_id)`
   (the existing `uq_events_source`); a repeat short-circuits to the prior result. With no
   `external_id`, the id is derived from the content hash, so identical content still dedupes.
2. **Orchestration guard** — `reconcile_event` returns the existing `ingestion_runs` row (one per
   event, `UNIQUE(event_id)`, upserted) without re-running any stage, unless `force=True`.
3. **Extraction skip-guard** — if a successful `extraction_runs` row exists, skip the LLM; the
   graph already holds the MERGE-written nodes, and scope is re-derived from the graph.
4. **MERGE everywhere** — every graph write is idempotent on its key, so even a *forced* replay
   converges to identical graph state.

## Alternatives Considered

### Option A — Layered guard + MERGE (chosen)

**What it is**: dedup at endpoint + orchestrator; MERGE guarantees graph state under forced replay.

**Pros**: works with the append-only audit logs as they are; the common replay (double-submit) never
re-runs a stage, so `merge_decisions` cannot grow; the test asserts identical node counts *and* a
single `ingestion_runs` row.

**Cons**: "identical merge_decisions count" holds via the guard, not via stage-level dedup; a forced
replay (`force=True`) *can* append audit rows for re-adjudicated new fragments. Named, not hidden.

### Option B — Make every stage dedup its own audit writes

**What it is**: add pair-keyed dedup to `merge_decisions`, run-keyed dedup to `extraction_runs`.

**Pros**: idempotent even under forced replay with no guard.

**Cons**: changes locked 3A audit semantics (the audit is intentionally append-only — it records
*attempts*, including repeats); more surface area for a property the guard already gives us.

## Consequences

**Enables**: safe double-submit, safe retries, safe replay; the load-bearing
`test_ingestion_idempotency.py` asserts the contract three ways (guard short-circuit, forced-replay
node-count stability, exactly-one extraction call).

**Constrains**: the deep "stage-level idempotent cost" property only holds on the default
(non-forced) path; `force=True` is an operator escape hatch, not the demo path.

**Locked into**: `ingestion_runs` being upsert-keyed on `event_id`; extraction reuse meaning
"skip the LLM and re-derive scope from the graph," because the audit row stores counts, not the
extracted payload.

**At larger scale / in production**: an idempotency key on the *request* (not just the event) and an
outbox/inbox pattern would make exactly-once delivery explicit across worker restarts.

## Interview Defense

> "Idempotency is layered: the endpoint dedupes on the event's unique source key, the orchestrator
> skips re-running if a completed run exists, and every graph write is a MERGE so even a forced
> replay converges to identical graph state. The honest caveat is that our audit logs are
> append-only by design, so the 'unchanged audit count' guarantee comes from the guard, not from
> the logs deduping themselves. The idempotency test checks all three layers."
