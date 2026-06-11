# HANDOFF — Company Brain

> **This file is overwritten at the end of every subphase.**
> Structure: Subphase → What was built → Decisions made → Deviations → Open questions → DoD check → Codebase state → Next subphase.
> Future sessions: read `CLAUDE.md` first, then this file.

---

## Subphase

Phase 5B — Observability + Parallel Resolution

## Date

2026-06-11

---

## What Was Built

The narrative thread: **build observability, use it to motivate the optimisation, ship the measured
before/after as proof.** The twist — and the strongest part of the story — is that the metrics,
built first, **corrected the optimisation's premise**: the Phase-5A "15 s `doc-new-person` tail" was
the embedding-model cold-start, not sequential adjudication (that case makes *zero* Tier-2 LLM
calls). The parallelisation shipped anyway and is proven correct + 4.0× faster under genuine fan-out.

### Backend: observability (`app/observability/`)

- `metrics.py` — `Metrics` registry (ingestion counters + per-status; per-stage / per-event /
  per-cost histograms as raw-sample lists; resolution-by-tier + contradiction adjudication
  counters), a numpy-default `_percentile`, and a typed `MetricsSnapshot` reduced on read. Module
  singleton `metrics`. `record_stage` / `record_ingestion` / `record_resolution` / `record_contradiction` / `reset`.
- `api/metrics.py` — `GET /api/metrics` (JSON snapshot), registered in `main.py`.

### Backend: ingestion-runs audit feed + instrumentation

- `db/repositories/ingestion_runs.py` — `list_paginated(limit, before)`: cursor pagination on
  `started_at`, joined to `events` for `source_kind` + content snippet, computes `duration_ms`.
- `ingestion/schemas.py` — `IngestionRunSummary` + `IngestionRunPage` DTOs.
- `api/audit.py` — `GET /api/audit/ingestion-runs?limit&before` (mirrors merge-decisions).
- `ingestion/orchestrator.py` — additive metrics loop after the stage timeline is assembled (no
  behavioural change); dedup short-circuit intentionally not counted.
- `ingestion/scoped_resolution.py` + `contradiction/scoped.py` — `record_resolution(tier)` /
  `record_contradiction()` per adjudication.

### Backend: parallel Tier-2 resolution (ADR 0035)

- `ingestion/scoped_resolution.py::_resolve_targets_against` rewritten as **three passes**: (1)
  serial — apply Tier-1 auto-merges + Tier-3 below-floor, collect surviving Tier-2 pairs; (2)
  parallel — `asyncio.gather` over `adjudicate()` under `Semaphore(5)`; (3) serial — apply verdicts.
  Tier-1-first so a folded target's Tier-2 pairs are dropped. Writes stay serial (shared Postgres
  session). Batch `resolve_graph` unchanged.

### Frontend (`frontend/src/`)

- `types.ts` — `IngestionRunSummary`, `IngestionRunPage`, `SystemMetrics` (+ `DurationStats`/`CostStats`).
- `api/audit.ts` — `fetchIngestionRuns(before, limit)`, `fetchSystemMetrics()`.
- `components/audit/AuditTabs.tsx` (new segmented control), `IngestionRunsTab.tsx` (table +
  `useInfiniteQuery` "Load more" + clickable Event → `EventModal` + stage-dot mini-timeline),
  `SystemMetrics.tsx` (compact strip).
- `pages/Audit.tsx` — tab shell; existing content → `ResolutionDecisionsTab`; tab mirrored to URL
  (`?tab=ingestion-runs`).

### Tests

- `tests/observability/test_metrics.py` (6), `tests/api/test_metrics_endpoint.py` (2),
  `tests/api/test_audit_ingestion_runs.py` (2, testcontainer), `tests/ingestion/test_parallel_resolution.py`
  (4, hermetic). Frontend `__tests__/Audit.tabs.test.tsx` (3) + `IngestionRunsTab.test.tsx` (3).

### Docs

- `design/observability.md`, ADR 0034 (in-memory metrics), ADR 0035 (parallel resolution),
  `interview-prep/phase-5b-readiness.md` (8 Q&A), demo Beat 4 addendum (audit-tab step),
  `eval/phase-5b-observability-results.md`, `docs/README.md` updated.

---

## Decisions Made

| ADR | Decision |
|-----|---------|
| [0034](docs/decisions/0034-in-memory-metrics-for-demo-scale.md) | In-memory metrics registry + JSON `/api/metrics`, not Prometheus/OTel. Proportionate to one process + tens of ingestions; the `record_*` call sites are the stable interface for the production scaling path. Process-local/volatile, named honestly. |
| [0035](docs/decisions/0035-parallel-resolution-adjudication.md) | Parallelise Tier-2 adjudication with `Semaphore(5)`, Tier-1-first, serial writes. Measured 4.0× under forced fan-out (45.7 s → 11.3 s on 16 calls). Bounded (rate limits) not unbounded; serial writes (shared session is read-modify-write) not per-task sessions. |

---

## Deviations from Spec / Key Findings

1. **The 15 s tail was cold-start, not adjudication (the headline finding).** A controlled semaphore
   A/B (concurrency 1 vs 5, warm model) showed `doc-new-person` makes **0** Tier-2 LLM calls — its 16
   candidates are all below the 0.75 floor — so its warm resolve is ~100 ms. The 5A 15 s was the
   embedding model loading on eval case 1. The Decision-3 premise ("15 s → 3–5 s via parallelisation")
   was therefore wrong; reported honestly. The parallelisation is still correct and 4.0× faster where
   fan-out is high (forced experiment). This is measure-then-optimise working as intended.
2. **Eval pass rate.** The clean re-run is **100% success / 100% pass** (mean 6072 ms). An earlier run
   hit `partial` on `doc-new-service` from a transient extraction LLM failure (cost $0.0000) — upstream
   of resolution, not a parallelisation regression; it passed on re-run.
3. **Integration pytest tests could not execute in this shell.** `testcontainers` needs raw Docker
   socket access, which this environment blocks (only the `docker` CLI is wired through; host TCP to
   the DB ports is also blocked). So `test_audit_ingestion_runs.py`, `test_parallel_resolution.py`'s
   integration sibling, and the load-bearing `test_ingestion_idempotency.py` are **written** and run in
   a Docker-socket/CI env, but here I verified the equivalent behaviour through other paths: the live
   ingestion eval (the `idempotency` case passes; the parallel resolver gives 100% pass), a live
   double-submit returning `deduplicated: true` in 0 ms, and the 4 hermetic parallel-resolution unit
   tests (which assert same-final-merge-set vs the sequential baseline, Tier-1-first skip, and the
   semaphore bound). The eval + A/B were run **inside the backend container** (`docker compose exec`),
   which reaches the DBs over the Docker network.
4. **Metrics snapshot in the eval doc shows total=2.** The in-memory metrics reset on the backend's
   `--reload`, so the snapshot reflects the two most-recent live ingestions — exactly the volatility
   ADR 0034 documents. The durable per-run record is `ingestion_runs` (7 rows, the audit tab).
5. **Demo graph baseline drifted by the 5B test ingests.** The audit tab needs ≥5 runs, and a run only
   exists while its event is un-reverted — so populating the tab necessarily leaves events in the
   graph. Current state carries: 3 pre-existing "Kaizer" slack runs (from a prior session), plus this
   phase's `priya-raman`, `marcus-webb`, a `fraud-scoring-api` service doc, and a D-0005 contradiction
   slack = **7 ingestion_runs**, Person ≈ 16 (was 13 clean). A demo operator restores the pristine
   killer-query baseline with `docker compose exec backend python -m app.synthetic.seeder` +
   `extract_all.py`. Named, not hidden.

---

## Open Questions

1. **Per-event Tier-2 fan-out is small on this corpus (0–4 calls)**, so the parallelisation's everyday
   benefit is small; it is insurance for high-fan-out. At production scale ANN candidate generation
   would pair a node against its few nearest neighbours, keeping fan-out small anyway — so the win
   stays situational. Honest, and documented in the eval Discussion + ADR 0035.
2. **A real PNG screenshot of the ingestion-runs tab** should be captured for the README/demo (frontend
   container rebuilt; tab live at `:3000/audit?tab=ingestion-runs`). The eval doc carries an ASCII
   stand-in for the layout.
3. **Cursor pagination uses `started_at` strictly-less**, which could skip a row on identical
   microsecond timestamps (essentially impossible at demo scale; a compound `(started_at, id)` cursor
   is the production fix). Noted in the repo method.

---

## Definition of Done Check

- ✓ `docs/design/observability.md` (≥ 800 words)
- ✓ Two ADRs (0034, 0035)
- ✓ `GET /api/metrics` returns the Decision-2 JSON shape (verified live)
- ✓ `GET /api/audit/ingestion-runs` returns a cursor-paginated list (verified live; 7 rows)
- ✓ `/audit` page has two tabs; switching works; URL query state preserved (tests + live)
- ✓ Ingestion-runs tab renders the Decision-1 table from real data (7 runs ≥ 5 target)
- ✓ System metrics strip renders at the bottom of the tab
- ✓ Parallel resolution **measured** before/after: 45.7 s → 11.3 s (4.0×) under forced fan-out;
  honest finding that `doc-new-person` itself is cold-start-bound (0 Tier-2). In the eval doc.
- ✓ Idempotency verified (eval `idempotency` case + live `deduplicated:true`); dedicated pytest needs a
  Docker-socket env (see Deviation 3)
- ✓ Full 11-case ingestion eval **100% pass** with the parallel resolver
- ✓ All new unit tests pass (12 backend hermetic + 6 frontend new; 47 frontend total); Phase 5A
  behaviour preserved (existing Audit tests green)
- ✓ `mypy --strict` clean across `app/observability/` and all new/changed backend files (15 files)
- ✓ `docker compose up` brings the full stack incl. `/api/metrics` + `/api/audit/ingestion-runs`
  (backend reloaded live; frontend image rebuilt with the new tab)
- ✓ Live verification: ingested events via `/api/events`; the new rows appear in the ingestion-runs
  tab with correct metrics; `/api/metrics` reflects them
- ✓ HANDOFF updated (5A reference commit `8d60c1d`)

---

## State of the Codebase

**Backend:** new `app/observability/` (`metrics.py` + `__init__.py`); `app/api/metrics.py`;
`app/api/audit.py` (+ ingestion-runs endpoint); `app/db/repositories/ingestion_runs.py` (+
`list_paginated`); `app/ingestion/schemas.py` (+ summary/page DTOs); `app/ingestion/orchestrator.py`
(+ metrics loop); `app/ingestion/scoped_resolution.py` (parallelised + metrics);
`app/contradiction/scoped.py` (+ metrics); `app/main.py` (metrics router). New tests under
`tests/observability/`, `tests/api/`, `tests/ingestion/`.

**Frontend:** `components/audit/{AuditTabs,IngestionRunsTab,SystemMetrics}.tsx`; `pages/Audit.tsx`
(tabbed); `api/audit.ts` + `types.ts` extended; `__tests__/{Audit.tabs,IngestionRunsTab}.test.tsx`.

**Docs:** observability design, ADRs 0034–0035, phase-5b interview-prep, demo Beat-4 addendum,
phase-5b eval results, docs/README updated.

**No schema migration** (the `ingestion_runs` table already exists from 5A; head revision
`0005_ingestion_runs`). **No new Python dependency** (metrics are in-memory).

**Reference commit (5A baseline):** `8d60c1d` — "5A Complete".

---

## Next Subphase

**Phase 6A — Demo recording + README + architecture diagram.** The read+write paths, observability,
and the audit/metrics surfaces are complete. 6A is polish-and-package: re-seed a pristine baseline,
capture the demo recording (incl. the Beat-4 audit-tab moment), a real screenshot of the ingestion-
runs tab, a top-level README refresh, and an architecture diagram. Deferred 5B candidates (SSE
progress on `/ingest`; per-canonical-node locking) remain future work, not 6A scope unless promoted.
