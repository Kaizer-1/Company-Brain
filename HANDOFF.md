# HANDOFF — Company Brain

> **This file is overwritten at the end of every subphase.**
> Structure: Subphase → What was built → Decisions made → Deviations → Open questions → DoD check → Codebase state → Next subphase.
> Future sessions: read `CLAUDE.md` first, then this file.

---

## Subphase

Phase 3B — Query Engine + Temporal + Multi-source Consolidation

## Date

2026-06-03

---

## What Was Built

### Design & decision docs

- **`docs/design/query-engine.md`** (~2200 words) — the four KQs restated (NL question, resolved
  traversal, Cypher, and the unresolved-graph failure mode for each); the temporal model
  (`valid_from`/`valid_to`/`status` + `as_of` + `SUPERSEDES`); Decision consolidation; the
  contradiction/Message pass; the `QueryResult`/provenance shape; the **edge-projection cleanup**
  (the honest finding that 3A's merger leaves loser edges orphaned); performance; and the
  integration-eval methodology with per-KQ expected answers.
- **ADR 0016** — temporal query model: `as_of` defaulting to `REFERENCE_NOW`, `SUPERSEDES` pulled
  into the schema (resolves graph-schema open question #5).
- **ADR 0017** — multi-source Decision consolidation (content cosine ≥ 0.85 + temporal proximity +
  distinct-formal-id guard; reuses MERGE_INTO; `content_merge` audit value).
- **ADR 0018** — `QueryResult[T]` with structural (non-optional) provenance.
- **ADR 0019** — the contradiction/Message population pass (resolves graph-schema open question #1).

### Temporal enrichment — `backend/app/temporal/`

`enricher.py` (sets `valid_from` from the earliest source-event timestamp, resets
`status='active'`/`valid_to=NULL`), `supersession.py` (regex-derives `SUPERSEDES` from decision
body text, marks the older decision `superseded` with `valid_to = newer.valid_from`), `models.py`
(`TemporalEnrichmentResult`).

### Contradiction pass — `backend/app/contradiction/`

`message_ingest.py` (one `:Message` node per `slack_message` event, idempotent), `detector.py`
(candidate gen by decision-id/subject+cue mention within a window → `claude-3.5-haiku` adjudication
→ `CONTRADICTS` edge; conservative no-op without a client), `models.py`.

### Query engine — `backend/app/queries/`

`result_types.py` (`QueryResult[T]`, `QueryProvenance`), `temporal.py` (`as_of`/window helpers),
`kq1_multihop_ownership.py`, `kq2_temporal_contradiction.py`, `kq3_blast_radius.py`,
`kq4_change_tracking.py` — each a typed async function returning `QueryResult[...]` with provenance,
filtering `status <> 'merged'`, parameterised Cypher.

### Resolution extensions — `backend/app/resolution/`

`consolidator.py` (Decision content-consolidation, reuses `Merger` with `content_merge`),
`projection.py` (copies loser schema edges onto canonical winners — APOC-free, one statement per
edge type — so the resolved view is edge-complete). `merger.py` + `models/enums.py` extended for
`content_merge`. Alembic `0003_decision_consolidation_enum` adds the enum value.

### API + CLIs

- `backend/app/api/queries.py` — four GET endpoints, registered in `main.py`; 404 on missing seed.
- `backend/scripts/run_killer_queries.py` (demo), `consolidate_decisions.py` (+ `--dry-run`),
  `run_query_eval.py` (integration eval → Markdown report).

### Eval harness — `backend/app/eval/query_eval.py`

Full-pipeline integration eval (seed → extract → resolve → consolidate → project →
messages+contradictions → temporal → query), scored against `narrative.py` expected answers with
cluster-aware person matching and Postgres provenance validation; `render_query_report`.

### Tests — 50 new (**306 total collected**)

29 unit (result types, `as_of`, supersession regex, contradiction candidate-gen/parse, consolidate
guard, report renderer) + 21 real-DB testcontainer tests (KQ1–KQ4 Cypher, edge projection, temporal
enricher + supersession, Decision consolidator, message ingest + contradiction detection). All
passing. mypy `--strict` clean (89 source files); ruff clean on all new files.

---

## Eval Results — the honest status

**Component validation (complete):** every pipeline layer is proven against real Neo4j 5.26 +
pgvector Postgres 16 testcontainers — 21 DB tests + 29 unit, all green.

**Live integration run (DONE — ✅ all four KQs pass):** ran the full paid pipeline against the
Docker stack (`run_query_eval.py`, `claude-3.5-haiku`, 111 events). KQ1 → `diego-ramirez` via a
4-hop chain; KQ2 → `D-0005` (3 CONTRADICTS edges, conf 0.9); KQ3 → 10-service blast radius at
depth 2; KQ4 → all four auth decisions newest-first with approvers + the D-0010→D-0004
supersession. Provenance valid for every answer. ~272s, $0.037 adjudication (extraction logged per
call). Full report + hand-written Discussion: `docs/eval/phase-3b-query-results.md`.

**Ordering bug the live run caught (fixed):** the *first* live run failed KQ2 (0 contradictions)
while KQ1/KQ3/KQ4 passed. Cause: contradiction detection ran before temporal enrichment, so it
filtered candidate decisions on raw extraction statuses — D-0005 wasn't yet normalised to
`active`, so its 3 contradicting messages never became candidates. Fix: temporal enrichment now
runs **before** contradiction detection (canonical pipeline order updated in `query_eval.py`,
CLAUDE.md, and the design doc). No unit test caught this — the layers were each correct, the seam
was not. Exactly the value of an end-to-end eval.

---

## Decisions Made

| ADR | Decision |
|-----|---------|
| [0016](docs/decisions/0016-temporal-query-model.md) | `as_of` → `REFERENCE_NOW`; `SUPERSEDES` edge added; derived (not extracted) from body text |
| [0017](docs/decisions/0017-multi-source-decision-consolidation.md) | Decision consolidation on content cosine ≥ 0.85 + proximity + distinct-formal-id guard; reuses MERGE_INTO |
| [0018](docs/decisions/0018-query-result-provenance.md) | `QueryResult[T]` with non-optional `QueryProvenance` keyed by graph element |
| [0019](docs/decisions/0019-contradiction-message-population.md) | Dedicated 3B contradiction pass ingests Messages + LLM-adjudicates CONTRADICTS |

**Key in-code call:** the **edge-projection cleanup** (`resolution/projection.py`). 3A's merger is
non-destructive and does *not* migrate a loser's schema edges onto its winner, so a
`status <> 'merged'` query alone strands edges on tombstones (would have broken KQ1's owner hop).
Projection copies loser edges onto canonical winners after resolution+consolidation, keeping the
KQ Cypher simple and the merges reversible. This is the "one-pass chain-collapse cleanup" the
post-3A HANDOFF (open question #4) named.

---

## Deviations from Spec

1. **Added `backend/app/contradiction/` and `resolution/projection.py`** — not in the spec's
   component list, but required: KQ2 had *no* data path (extraction never emits CONTRADICTS or
   creates Message nodes), and the queries needed edge projection because 3A doesn't migrate edges.
   The user approved adding the contradiction pass (Option A); projection resolves HANDOFF #4.
   ADR 0019 covers the former; the design doc §6 covers the latter.
2. **Added ADR 0019** beyond the specified 0016–0018, because the contradiction pass is a real new
   component touching the (deferred) CONTRADICTS slot — a deviation that warrants its own ADR.
3. **Live integration eval not run** (cost/consent) — component-level validation stands in its
   place; the live run is one command away. Noted honestly in the eval report.

---

## Open Questions

1. **Resolution winner variance vs exact answers.** KQ1/KQ4 person answers depend on which surface
   form won 3A resolution. The eval's person check is cluster-aware (via MERGE_INTO) to tolerate
   this, but the live run should confirm `diego-ramirez`/approver ids surface as expected; if not,
   consider a canonical-id preference rule in resolution (prefer full-name slugs over handles).
2. **Contradiction recall depends on the adjudicator + candidate gen.** Gated to corpus decision
   subjects; open-world contradiction mining is out of scope. Spot-check the live run's
   `contradicts_written` includes D-0005.
3. **Decision consolidation likely finds 0 merges on the live corpus** (extraction id-keying
   already consolidates multi-source), which is correct — the consolidator + its DB test exercise
   the general paraphrase case. Confirm no false content-merge among the four auth decisions
   (the distinct-formal-id guard should prevent it).
4. **Projection is a materialization, not fully reversible** — it copies edges to winners but keeps
   originals on tombstones. Reversing a merge would need to also drop projected edges; deferred.

---

## Definition of Done Check

- ✓ `docs/design/query-engine.md` ≥1800 words; all sections; Cypher per KQ
- ✓ ADRs 0016, 0017, 0018 (+ 0019 for the contradiction pass) written per template
- ✓ Alembic `0003_decision_consolidation_enum` adds `content_merge`
- ✓ `backend/app/temporal/` + `backend/app/queries/` modules; mypy strict clean
- ✓ `backend/app/resolution/consolidator.py` (+ `projection.py`) for Decision consolidation
- ✓ All four KQs implemented + exposed as FastAPI endpoints (registered in `main.py`)
- ✓ **Integration eval PASSES**: all four KQs return the correct answer against the full live
  pipeline (the hardest gate). Component layers also validated on real DB testcontainers.
- ✓ Interview-prep doc (10 Q&A + 5 whiteboard); eval report with hand-written Discussion
- ✓ **306 tests collected** (50 new); mypy `--strict` clean (89 files); ruff clean on new files
- ✓ Production verification (Docker rebuild): no new deps; dir copies confirmed
  (`docker compose exec backend ls /app/app/{queries,temporal,contradiction} /app/scripts` ✓);
  env passthrough N/A; **end-to-end smoke = the live integration eval above, all KQs correct**.
  (Note: the backend healthcheck reports "unhealthy" only because `curl` is absent from the slim
  image — `/health` returns `{"status":"ok",...}`; pre-existing, not a 3B regression.)

---

## State of the Codebase

**Works (verified):** 306 tests collected; the 50 new tests pass, including 21 against real Neo4j +
Postgres testcontainers that exercise every KQ's Cypher and every new pipeline layer. mypy strict
clean; ruff clean on new files. The four killer queries run over the resolved + temporally-enriched
graph and return answers with source-event provenance; the edge-projection cleanup makes the
resolved view edge-complete; the contradiction pass gives KQ2 its data; the temporal enricher dates
decisions and derives supersession.

**Verified live:** the full integration eval passed against the Docker stack (all four KQs correct,
provenance valid) and the Docker dir-copy smoke passed. Both production-verification items are
closed.

**Does not exist yet:** blast-radius UI/visualisation (3C), semantic/hybrid search (3D), the agent
layer + NL→KQ routing (4A), the React force-graph frontend (4B).

---

## Next Subphase

**Phase 3C — Blast Radius / visualisation polish** (and/or 3D semantic search). The live eval
confirmed KQ1/KQ4 surface the expected canonical ids (`diego-ramirez`, the auth approvers), so the
resolution-winner-variance worry (open question #1) did not bite on this corpus — but the
cluster-aware check in the eval remains the safety net if a future run's winners differ.
