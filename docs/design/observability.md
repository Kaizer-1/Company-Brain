# Observability (Phase 5B)

> How the live-reconciliation engine is measured: a small in-memory metrics layer, a JSON
> endpoint, and an audit tab — built to *motivate* the resolution optimisation with numbers, not to
> reproduce a production observability stack.

## 1. The problem

Through Phase 5A the reconciliation engine works but is observable only two ways: structured
`structlog` events (great for tracing one run, useless for a distribution) and one `ingestion_runs`
row per event (an audit record, not a metric). The Phase-5A eval named a 15-second tail on
`doc-new-person` and hypothesised it was sequential Tier-2 adjudication — but that was a guess from a
single number, not a measurement. Phase 5B's thesis is **measure, then optimise**: build the
observability that turns "it feels slow" into "the resolve stage's p95 is X", *then* change code with
a real before-number to compare against. The constraint is scale and audience — one process, tens of
ingestions, shown to an interviewer — so the observability must be proportionate, not a Grafana
deployment.

## 2. What we capture

A single in-memory `Metrics` registry (`app/observability/metrics.py`) accumulates three kinds of
signal as the pipeline runs:

- **Counters** — total ingestions and a per-status breakdown (`reconciled` / `partial` / `failed`).
- **Histograms** — per-stage durations, per-event total duration, and per-event cost, stored as
  plain lists of floats and reduced to percentiles (p50/p95/max) only when the endpoint reads them.
  At demo scale, keeping the raw samples is simpler to reason about than streaming-percentile
  sketches and keeps the percentiles exact.
- **Adjudication counters** — resolution adjudications by tier (1 auto / 2 LLM / 3 below-floor) and
  contradiction adjudications. This is the signal that distinguishes "an ingestion that made 13 LLM
  calls" from "one that made 0", and it is what the parallel-resolution work moves.

The orchestrator emits `record_stage(...)` per stage and `record_ingestion(...)` once per *worked*
reconciliation (the dedup short-circuit does no work and is intentionally not counted). The two
adjudicating stages emit a counter per adjudication. Every write is a synchronous counter bump or a
`list.append`, so under the single-process asyncio event loop there is no interleaving to guard
against — the metrics layer **complements** the structured logs, it does not replace them.

## 3. The read surfaces

Two surfaces answer two different questions:

- **`GET /api/metrics`** returns a JSON snapshot — ingestion totals + duration/cost distributions,
  per-stage durations, and adjudication counters. Percentiles are computed at read time. It answers
  *"what are the rates and distributions?"* A compact "System metrics" strip at the bottom of the
  new audit tab renders four of these numbers (total ingestions, median + p95 latency, mean cost).
- **`GET /api/audit/ingestion-runs`** returns the `ingestion_runs` rows, cursor-paginated and joined
  to their events. It answers *"what happened on each run?"* — a per-run ledger with the stage
  timeline, counts, cost, and duration, mirroring the existing merge-decisions audit tab.

Metrics are aggregate and volatile; the audit trail is per-run and durable. Keeping them separate is
deliberate: a distribution and an inspectable ledger are different tools.

## 4. Why in-memory (ADR 0034)

The registry is a module-level singleton; the numbers are process-local and reset on restart. This
is a named limitation, not an oversight. At one process and tens of ingestions, a real time-series
store (Prometheus + Grafana) or a tracing pipeline (OpenTelemetry + collector) would be
infrastructure with no workload to justify it — and worse, it would bury the one signal this phase
is about (the resolution before/after) under a dashboard. The design philosophy is explicitly
*anti-over-instrumentation*: the demo audience needs to *see that the system is measured*, not to
operate Datadog. `prometheus_client` is not even a dependency.

## 5. The production scaling path

The `record_*` call sites are the stable interface; only the registry's storage and the read path
change at scale:

- **Multiple workers / replicas** — a per-process registry double-counts or loses data. Move to
  per-worker registries aggregated at the backend, or push to a shared store.
- **Durable, queryable metrics** — back the counters with `prometheus_client` and a Prometheus
  server scraping `/metrics`, or an OpenTelemetry exporter to a collector (the upgrade route already
  named in ADR 0006). Grafana for the dashboard. Histograms become native Prometheus histograms with
  fixed buckets instead of raw-sample lists.
- **Cross-restart retention** — persist to Redis or a time-series DB so a restart doesn't zero the
  numbers; the audit trail (`ingestion_runs`) is already durable in Postgres and needs no change.

None of this changes where the metrics are *recorded* — the orchestrator and the adjudicating stages
stay exactly as instrumented.

## 6. Scope rationale (three items, no creep)

Phase 5B is exactly three things: the **ingestion-runs audit tab**, the **metrics layer**, and the
**parallel resolution** the metrics motivate. The HANDOFF listed two further candidates — an SSE
progress channel on `/ingest` and per-canonical-node locking — and both are explicitly **out of
scope** here. SSE is a UX nicety the awaited-in-handler response already covers for a single user
(deferred to 6A polish or future work); per-node locking is the production concurrency path behind
ADR 0033's single-writer lock, which the single-writer demo does not need. Naming them as deferred,
rather than quietly expanding, is the project's scope-honesty value applied to this phase.

## 7. What the measurement found

Building the metrics first paid off immediately and unexpectedly: the per-stage numbers and a
controlled semaphore A/B showed the Phase-5A "15-second `doc-new-person` tail" was the **embedding
model's cold-start on the first eval case**, not sequential Tier-2 adjudication — that case's warm
resolve stage is ~100 ms and triggers ~0 Tier-2 calls. The parallelisation is still correct and
bounded (it collapses the tail wherever Tier-2 fan-out is large, demonstrated under a forced
high-fan-out experiment), but the headline cause of the slow case was mis-attributed in 5A. That
correction *is* the measure-then-optimise philosophy working — see
[../eval/phase-5b-observability-results.md](../eval/phase-5b-observability-results.md) and ADR 0035.

---

## Related ADRs

- [ADR 0034](../decisions/0034-in-memory-metrics-for-demo-scale.md) — In-memory metrics registry: volatile by design, production path documented
- [ADR 0035](../decisions/0035-parallel-resolution-adjudication.md) — Parallel Tier-2 adjudication under Semaphore(5): measured 4.0× speedup
