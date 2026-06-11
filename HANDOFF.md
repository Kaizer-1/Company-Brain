# HANDOFF — Company Brain

> **This file is overwritten at the end of every subphase.**
> Structure: Subphase → What was built → Decisions made → Deviations → Open questions → DoD check → Codebase state → Next subphase.
> Future sessions: read `CLAUDE.md` first, then this file.

---

## Subphase

Phase 5A — Streaming Ingestion + Live Reconciliation Engine

## Date

2026-06-07

---

## What Was Built

The original-plan demo moment: a new event typed into a form is ingested through the
extraction → resolution → temporal → contradiction pipeline **incrementally** (not full rebuild),
the graph reconciles in ~6s, an audit row records the run, and the Phase-4C structural tools
confirm the change with an exact count ("list all employees" → 13 → 14). Verified end-to-end live
through the rebuilt Docker stack.

### Backend: incremental reconciliation (`app/ingestion/`)

- `orchestrator.py` — `reconcile_event(event_id, *, session_factory, neo4j_driver, client, model,
  force)`: runs the 8 stages in batch order, scoped to one event, idempotently; persists one
  `ingestion_runs` row; short-circuits via the orchestration guard on replay.
- `stages.py` — per-stage glue: provenance-derived `GraphScope`, the extraction **skip-guard**,
  embed/resolve/consolidate/project/temporal/materialize-message/contradiction/search-index, each
  returning a `StageResult`.
- `scoped_resolution.py` — true node-scoped resolution (new fragments × existing of their type),
  reusing the 3A tier machinery (`_decide_and_apply`); derives this event's `MergeRef`s.
- `scoped_temporal.py` — documented thin pass-through to `enrich_temporal` (idempotent + LLM-free).
- `scoped_contradiction.py` — adapter over `app.contradiction.scoped`.
- `schemas.py` — `IngestEventRequest`/`IngestEventResponse`/`StageResult`/`NodeRef`/`MergeRef`/
  `EdgeRef`/`ContradictionRef` + persistence DTOs.
- `api_router.py` — `POST /api/events`: idempotent insert, single-writer `asyncio.Lock`
  (30s → 503), awaited reconcile, registered in `main.py`.
- `db/repositories/ingestion_runs.py` + `models/ingestion_runs.py` + migration
  `0005_ingestion_runs.py` (upsert keyed on `event_id`).

### Backend: scoped contradiction + message materialise (`app/contradiction/`)

- `scoped.py` — **new** `detect_for_new_message` / `detect_for_new_decision` (concurrent
  adjudication, semaphore of 5), reusing the batch detector internals.
- `models.py` — added `WrittenContradiction`.
- `message_ingest.py` — added `ingest_one_message` (scoped single-Message MERGE).

### Frontend (`frontend/src/`)

- `pages/Ingest.tsx`, `components/ingest/IngestForm.tsx`, `components/ingest/ReconciliationView.tsx`,
  `api/ingest.ts`, ingestion types in `types.ts`.
- `App.tsx` `/ingest` route; `TopBar.tsx` nav + hint `g k/i/h/g/q/s/a`; `useKeyboardNav.ts` `g i`;
  `Graph.tsx` `refetchOnWindowFocus: true`.
- `__tests__/Ingest.test.tsx` (4 tests). Fixed a **pre-existing 4C build break** (`findLast`
  needs `es2023` lib; bumped `tsconfig.app.json` `lib` → ES2023).

### Eval + docs

- `data/ingestion_eval_cases.json` (11 cases), `app/eval/ingestion_eval.py`,
  `scripts/run_ingestion_eval.py`, `docs/eval/phase-5a-ingestion-results.md` (real numbers).
- `docs/design/incremental-reconciliation.md` (1598 words); ADRs 0031/0032/0033;
  `docs/interview-prep/phase-5a-readiness.md` (12 Q&A); demo Beat 4 (the live-inject climax);
  `docs/README.md` updated.

### Tests

- `tests/ingestion/` — idempotency (load-bearing), stages, orchestrator, api, structural-after
  (4C↔5A) — **15 tests, all pass**.

---

## Decisions Made

| ADR | Decision |
|-----|---------|
| [0031](docs/decisions/0031-incremental-reconciliation.md) | Per-event incremental reconciliation, **hybrid scoping**: reuse cheap idempotent batch stages as-is; truly scope only the cost-bearing stages (extraction skip-guard; resolution to newly-created fragments; scoped concurrent contradiction). Scope derived from the graph by provenance. |
| [0032](docs/decisions/0032-idempotency-contract.md) | Layered idempotency: endpoint dedup → orchestration guard → extraction skip-guard → MERGE-everywhere. "Extraction reuse" = skip LLM + re-derive scope from graph (the audit row stores counts, not the payload). |
| [0033](docs/decisions/0033-single-writer-lock.md) | One in-process `asyncio.Lock` serialises ingestions (MERGE doesn't make read-modify-write atomic); 503 on 30s timeout; production path = per-canonical-node locking + advisory/partitioned coordination. |

---

## Deviations from Spec

1. **`source_kind` restricted to `doc` / `slack_message`.** The Postgres `sourcetype` enum has only
   these two; the spec's `adr` / `meeting` would fail at the DB. Documented; `ALTER TYPE` deferred
   (the demo doesn't need them). Decided with the user before coding.
2. **Hybrid scoping, not strict per-node-id everywhere.** Decided with the user. `scoped_temporal.py`
   is a documented pass-through; only extraction + resolution + contradiction are truly scoped. The
   decisive optimisation was scoping resolution to *newly-created fragments* (sole-provenance nodes),
   which took the worst case 52s → 16s (a re-mention resolves nothing, as it should).
3. **Extraction "reuse" can't reload the extracted result** — `extraction_runs` stores counts only.
   So reuse = skip the LLM and re-derive scope from the graph by provenance (ADR 0032). This is the
   idempotency-correct interpretation of Decision 3.
4. **"Materialize Message node" is an extra stage (6b).** Message nodes are mechanical, not extracted;
   a new slack event needs its `:Message` node MERGEd before contradiction detection. The spec's 8
   stages omitted it.
5. **`reconcile_event` takes `session_factory`, not a single `session`** — stages open independent
   per-step sessions and commit per step (mirrors the extraction pipeline).
6. **`merge_decisions` is append-only (not pair-deduped).** Decision 3 assumed a pre-write pair check;
   the live resolver has none. Idempotency of the audit comes from the orchestration guard, not
   stage-level dedup (ADR 0032, named honestly).
7. **Fixed a pre-existing 4C frontend build break** (`findLast` / es2023 lib) so the stack rebuilds.

---

## Open Questions

1. **Resolution adjudication is still sequential** — the eval's 15s tail (`doc-new-person`: a new
   person vs 13 similar people). Contradiction already fans out concurrently; the same treatment for
   resolution is the next latency win. Deferred to keep the scoped resolver a faithful reuse of 3A.
2. **`force=True` replay can append audit rows** for re-adjudicated fragments — the deep stage-level
   idempotency holds for graph state (MERGE) but not for the append-only audit. The default path uses
   the guard, so this is an operator-escape-hatch caveat, not a demo concern.
3. **Best-effort merge attribution** — `_merges_for_event` matches either MERGE_INTO endpoint by
   provenance; for a brand-new event id this is exact, but it is attribution, not a ledger.
4. **Pre-existing failures/mypy errors remain** unchanged from 4C (DB-state test files; the 39
   pre-existing mypy errors in older modules). `app/ingestion/` is mypy-strict clean (0 new errors).

---

## Definition of Done Check

- ✓ `docs/design/incremental-reconciliation.md` — 1598 words
- ✓ Three ADRs (0031, 0032, 0033)
- ✓ `POST /api/events` works against the live backend; ingestion ≤ 8s mean (**5.8s measured**)
- ✓ `/ingest` page renders, form submits, `ReconciliationView` shows the per-stage timeline + what-changed
- ✓ Graph page refetches on focus
- ✓ All 8 stages work and are individually testable
- ✓ `merge_decisions` records resolution from ingestion; `ingestion_runs` one row per ingestion
- ✓ **Idempotency test passes** (guard short-circuit + forced-replay node stability + single LLM call)
- ✓ Ingestion eval ran on 11 cases — **100% success & pass, 5.8s mean, $0.0031/event**; results doc has real numbers + Discussion
- ✓ **Structural acceptance** verified live: ingest a hire → `enumerate` returns 14 (was 13); agent flow confirmed through HTTP
- ✓ KQs / structural tools / search / agent all still work after ingestion (live-checked: enumerate=14, agent answers)
- ✓ `mypy --strict` clean across `app/ingestion/` (8 files)
- ✓ New tests pass (15 ingestion + 4 frontend); regression subset green (57 passed: migrations/models/app/repos); pre-existing failures not grown
- ✓ `docker compose up` brings the full stack incl. the ingestion endpoint (rebuilt + verified live; baseline restored to 13/10/89/14/5/4)
- ✓ HANDOFF updated (4C reference commit `a867123`)

---

## State of the Codebase

**Backend:** new `app/ingestion/` package (orchestrator, stages, 3 scoped wrappers, schemas, api_router);
`app/contradiction/` gained `scoped.py` + `ingest_one_message` + `WrittenContradiction`;
`db/repositories/ingestion_runs.py`; `models/ingestion_runs.py` (+ registered in `models/__init__.py`);
`alembic/versions/0005_ingestion_runs.py`; `main.py` registers the ingestion router;
`app/eval/ingestion_eval.py` + `scripts/run_ingestion_eval.py`; `data/ingestion_eval_cases.json`.

**Frontend:** `pages/Ingest.tsx`, `components/ingest/*`, `api/ingest.ts`, ingestion types; `/ingest`
route + nav + `g i` shortcut + graph refetch-on-focus; `tsconfig.app.json` lib → ES2023.

**Docs:** incremental-reconciliation design, ADRs 0031–0033, phase-5a interview-prep, demo Beat 4,
phase-5a eval results, docs/README updated.

**Reference commit (4C baseline):** `a867123` — "4C complete".

---

## Next Subphase

**Phase 5B — Observability + Ops.** 5A's reconciliation runs but is only observable via structured
logs and the `ingestion_runs` table. 5B candidates: an ingestion-runs audit view on the frontend
(mirroring `/audit`); metrics (latency/cost/stage histograms); parallelising resolution adjudication
(the 15s tail); an SSE progress channel for the ingest page (Decision 7 Option B); and the production
concurrency path (per-node locking). The read+write paths are now both complete end-to-end.
