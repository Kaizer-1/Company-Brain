# ADR 0034 — In-Memory Metrics for Demo Scale

## Status

Accepted

## Context

Through Phase 5A the reconciliation engine is observable only through structured logs and one
`ingestion_runs` row per event. To motivate the resolution optimisation (Decision 3 of Phase 5B)
with a *measured* baseline rather than an estimate, we need per-stage latency, per-event cost, and
per-adjudication counters — exposed somewhere a reader can see them. The constraint is scale and
audience: this is a single-process, single-writer portfolio demo handling tens of ingestions, shown
to an interviewer, not a fleet serving production traffic. A real time-series stack (Prometheus +
Grafana, or OpenTelemetry + a collector) would be infrastructure with no workload to justify it, and
it would bury the one signal that matters (the before/after of the optimisation) under a dashboard.

## Decision

**Record metrics in a small in-process `Metrics` registry and expose a JSON snapshot at
`GET /api/metrics`.** Counters and raw-sample histograms accumulate in memory during reconciliation
(written from the orchestrator and the two adjudicating stages); percentiles are computed at read
time. The numbers are process-local and reset on restart. No Prometheus exposition format, no
external collector, no persistence.

## Alternatives Considered

### Option A — In-memory registry + JSON endpoint (chosen)

**What it is**: a module-level `Metrics` singleton with `record_*` methods; `/api/metrics` reduces
the raw samples to percentiles on read.

**Pros**: zero new dependencies or infrastructure; the write path is a synchronous counter bump
(safe under the single-process event loop); the read model is exactly the four numbers the demo
needs; trivially testable (the percentile maths is a pure function).

**Cons**: process-local (no aggregation across replicas) and volatile (resets on restart); not a
real time series — you cannot query "p95 last Tuesday".

### Option B — `prometheus_client` + `/metrics` exposition

**What it is**: the standard Python Prometheus client; expose counters/histograms in text format for
a Prometheus server to scrape.

**Pros**: the production-standard shape; histogram buckets and scraping come for free; would plug
into Grafana later.

**Cons**: not installed (a new dependency for demo value we don't need); still process-local without
an actual Prometheus server + Grafana, so to make it *useful* you must stand up the whole stack —
exactly the over-instrumentation this phase's design philosophy warns against.

### Option C — OpenTelemetry metrics + collector

**What it is**: instrument with the OTel SDK, export to a collector/backend.

**Pros**: vendor-neutral, the genuine production path (already named as the upgrade route in ADR
0006); traces and metrics under one API.

**Cons**: the heaviest option — SDK, exporter, collector, and a backend to see anything. Wildly
disproportionate to a single-process demo; pure ceremony at this scale.

## Consequences

**Enables**: a measured sequential baseline for the resolution work (ADR 0035), a "System metrics"
strip on the audit page, and an honest "the system is measured" story — without a dashboard.

**Constrains**: metrics are per-process and reset on restart; a multi-worker or multi-replica
deployment would double-count or lose data; the persistent audit trail of *what happened* lives
separately in `ingestion_runs` (metrics answer rates/distributions, the audit table answers
per-run inspection — two surfaces, two questions).

**Locked into**: synchronous in-process recording during reconciliation; the `/metrics` read path is
the only consumer.

**At larger scale / in production**: back the counters with a real store — `prometheus_client` +
a Prometheus server scraping `/metrics` (or an OTel exporter to a collector), with per-worker
registries aggregated at the backend, and Grafana for the dashboard. The `record_*` call sites stay;
only the registry's storage and the read path change.

## Interview Defense

> "Metrics are an in-memory registry behind `/api/metrics`, JSON only. I deliberately didn't stand
> up Prometheus and Grafana — at one process and tens of ingestions that's infrastructure with no
> workload, and it would hide the one number this phase is about: the resolution before/after. The
> honest cost is that the metrics are process-local and reset on restart; the durable audit trail is
> the `ingestion_runs` table, which the `/audit` tab reads. In production the same `record_*` calls
> feed `prometheus_client` or an OTel exporter — the call sites don't move, only the storage does."
