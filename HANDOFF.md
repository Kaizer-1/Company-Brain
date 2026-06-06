# HANDOFF — Company Brain

> **This file is overwritten at the end of every subphase.**
> Structure: Subphase → What was built → Decisions made → Deviations → Open questions → DoD check → Codebase state → Next subphase.
> Future sessions: read `CLAUDE.md` first, then this file.

---

## Subphase

Phase 4C — Structural Agent Tools

## Date

2026-06-07

---

## What Was Built

Four typed structural query tools that close the class of graph-native questions the four
KQs and semantic search could not answer correctly (lookups, typed traversals, enumeration,
counting). The agent now routes ten ways. The original failing question — "name all the
employees" — now routes to `enumerate` and returns all 13 people.

### Backend: four structural query tools (`app/queries/`)

- `structural_common.py` — **new** shared helpers: `NODE_TYPES`/`NodeTypeLiteral`,
  `StatusLiteral`, `node_display_name()` (uniform `coalesce` name), `identity_predicate()`
  (case-insensitive match across canonical_id/canonical_name/id/handle), `status_predicate()`
  (active/deprecated/all normalisation), `jsonable_props()` (neo4j temporal → JSON).
- `get_entity.py` — **new** `GetEntityInput`/`GetEntityResult` + `get_entity()`: single-node
  property lookup + neighbour edge-type summary; `not_found` sentinel.
- `neighbors.py` — **new** `NeighborsInput`/`Neighbor`/`NeighborsResult` +
  `neighbors_of_entity()`: typed one-hop traversal with edge/direction/limit; `total_count`.
- `enumerate.py` — **new** (load-bearing) `EnumerateInput`/`EnumeratedNode`/`EnumerateResult`
  + `enumerate_by_type()`: filtered listing with status/order_by/limit/has_no_edge/team_filter;
  pre-limit `total_count`. Absorbs recency (order_by) and find-orphans (has_no_edge).
- `aggregate.py` — **new** `AggregateInput`/`AggregateGroup`/`AggregateResult` +
  `aggregate_by_type()`: count + optional group_by; always-empty provenance by design.
- `__init__.py` — exports the four new functions + their input/result types.

All Cypher is parameterised — labels via `$type IN labels(n)`, edges via `type(r)=$edge`,
direction via `startNode(r)=n`, negative-existence via `EXISTS{…WHERE type(r)=$has_no_edge}`.
Only `ORDER BY` is interpolated, from a closed Literal→fragment map.

### Backend: agent wiring (`app/agent/`)

- `state.py` — `RouteLiteral`/`ROUTE_VALUES` extended to ten; added `STRUCTURAL_ROUTES`.
- `schemas.py` — re-exports the four `*Result` types; added `StructuralAnswer` (optional
  citations); added `tool_output` to `AskResponse`.
- `tools.py` — four new tool nodes (`get_entity_tool`, `neighbors_tool`, `enumerate_tool`,
  `aggregate_tool`) validating `*Input` and falling back to search on bad input; helpers
  `_first_err`, `_structural_to_state`.
- `graph.py` — four nodes wired into the StateGraph; `_route_after_tool` sends genuine
  structural results (QueryResult `value` shape) to synthesis even with no events.
- `verification.py` — skips the citation check when route is structural AND no events (ADR 0030).
- `synthesis.py` — `_synthesis_plan()` picks prompt+schema; structural-no-events uses
  `synthesis_structural.txt` + `StructuralAnswer`; `_parse_synthesis_json` takes a schema.
- `config.py` — added `synthesis_structural_prompt_path`.
- `runner.py` + `api_router.py` — populate `tool_output` for structural routes on both the
  JSON response and the streaming `complete` event; streaming terminal condition lets a
  genuine structural result flow into synthesis.
- `prompts/router.txt` — redesigned: two-stage conceptual routing (shape → route), 20
  few-shots, explicit KQ-vs-structural priority rule (ADR 0029).
- `prompts/synthesis.txt` — added structural-data citation guidance.
- `prompts/synthesis_structural.txt` — **new** citation-free structural prompt.

### Frontend (`frontend/src/`)

- `types.ts` — `AgentRoute` extended; `EntityResult`/`NeighborsResult`/`EnumerateResult`/
  `AggregateResult`/`ToolOutput`; `tool_output` on `AskResponse` + `StreamEventComplete`.
- `components/ask/results/` — **new** `EntityResult.tsx`, `NeighborsResult.tsx`,
  `EnumerateResult.tsx`, `AggregateResult.tsx`, and `index.tsx` (`StructuralResultView`
  dispatcher).
- `pages/Ask.tsx` — dispatches to `StructuralResultView` in both stream + JSON branches; new
  route labels.
- `components/ask/StreamProgress.tsx` — route labels for the four new routes.

### Eval + docs

- `data/agent_eval_questions.json` — 30 → 42 (q31–q42, 3 per new tool).
- `eval/agent_eval.py` — gold citations for structural routes; `new_tool_accuracy`,
  `route_accuracy_for`, `per_route_accuracy`; per-route table; generic report title.
- `docs/eval/phase-4c-structural-results.md` — real 42-question results + Discussion.
- `docs/design/structural-tools.md` (~1050 words); ADRs 0028/0029/0030;
  `docs/interview-prep/phase-4c-readiness.md` (10 Q&A); demo Beat 3.5 extended;
  `docs/README.md` updated.

### Tests

- `tests/queries/test_{enumerate,get_entity,neighbors,aggregate}.py` — 23 testcontainer tests.
- `tests/agent/test_agent_new_routes.py` — routing + tool nodes + fallback (real Neo4j).
- `tests/agent/test_agent_verification_structural.py` — the verification skip + that it does
  NOT fire for event-bearing structural answers or non-structural routes.
- `frontend/src/__tests__/Ask.structural.test.tsx` — one per renderer.

---

## Decisions Made

| ADR | Decision |
|-----|---------|
| [0028](docs/decisions/0028-structural-tools-scope.md) | Four structural tools not seven; recency/orphans/provenance fold into parameters; typed parameterised Cypher (no label interpolation); heterogeneous case-insensitive identity; status normalisation; path-finding/generated-Cypher deferred |
| [0029](docs/decisions/0029-router-redesign-two-stage-conceptual.md) | Router prompt redesigned as two-stage conceptual routing (shape → route) in one LLM call, 20 few-shots, explicit priority rule |
| [0030](docs/decisions/0030-verification-skip-for-structural.md) | Verification skips the inline-citation check only when route is structural AND no events were returned (e.g. aggregate count) |

---

## Deviations from Spec

1. **Cypher labels/edges are parameters, not interpolated.** The spec's pseudo-Cypher used
   `MATCH (n:$NodeLabel)` and `[:$has_no_edge]`. To honour CLAUDE.md's "parameterised queries
   only" rule with zero injection surface, the implementation uses `$node_type IN labels(n)`,
   `type(r) = $edge`, `startNode(r)=n`, and `EXISTS{…WHERE type(r)=$has_no_edge}`. Only
   `ORDER BY` (which Cypher cannot parameterise) is interpolated from a closed Literal map.

2. **Identity matching is heterogeneous + case-insensitive**, not `canonical_id`-only. The
   live graph keys Person by `canonical_id`, Service/System/Team by `canonical_name`, Decision
   and Message by `id`; team names are capitalised. A `canonical_id`-only match (spec draft)
   would only ever hit Person nodes. Caught in the pre-implementation schema check.

3. **Status semantics normalised** beyond the spec's literal "active/deprecated/all": `active`
   excludes merged+deprecated+superseded; `deprecated` is the ended-but-not-merged set; `all`
   excludes only merged. Real status values are inconsistent (Person/Team have none; one
   Service is `deployed`; Decision uses `superseded`), so the filter is defined on `coalesce`.

4. **Edge enum uses the real closed vocabulary**, not the spec's list (which had a typo
   `ASSERTS` and omitted `ABOUT`/`APPROVED_BY`/`AUTHORED`). `AUTHORED`/`MENTIONS` exist in the
   schema but have 0 instances (extraction sparsity) — valid enum members regardless.

5. **Result types live in the query modules (re-exported from `schemas.py`)**, mirroring the
   four KQ result models, rather than being defined in `schemas.py`. Cleaner co-location; the
   deliverable's "schemas.py adds the result types" is met via re-export.

6. **`tool_output` added to `AskResponse` + the streaming `complete` event.** The spec's
   frontend renderers need the structured output, which Phase 4A's response did not carry.
   Populated only for the four structural routes.

7. **New synthesis path for event-less structural answers** (`synthesis_structural.txt` +
   `StructuralAnswer`). Required because `AnswerWithCitations.citations` has `min_length=1`,
   which would reject a citation-free aggregate answer. Decision 8 described the verification
   skip but not this schema split, which is the mechanism that makes it work.

---

## Open Questions

1. **Path-finding is deferred** (documented in ADR 0028). "How is A connected to B?" needs
   variable-length traversal + a path result shape; bundled with the routing-scale upgrade.
2. **Graph sparsity is real, not a bug.** Only 2 `MEMBER_OF` edges exist (both → Payments), so
   "who's on the Growth team?" returns nobody. The tools are correct; the extracted data is
   sparse. Noted in the eval Discussion.
3. **Latency still misses the 4s target** (7499ms mean, inflated by one q37 retry). Unchanged
   from 4A — two sequential LLM calls. Streaming mitigates perceived latency; true reduction
   needs cached/parallel routing (agent-architecture production-scale section).
4. **Pre-existing failures remain** (`test_audit.py`, `test_events.py`, `test_graph.py`,
   `test_seeder.py` — 12 fail / 7 pass in those files, identical with and without 4C). DB-state
   / test-environment issues, not 4C-related; confirmed via stash comparison.
5. **Pre-existing mypy errors remain** (39, all in `search/retriever.py`, the streaming
   `api_router.py`, `streaming_eval.py`, etc.). Count is identical at HEAD and now — 4C added
   zero. All four new query modules + new agent code are mypy-strict clean.

---

## Definition of Done Check

- ✓ `docs/design/structural-tools.md` (~1050 words)
- ✓ Three ADRs (0028, 0029, 0030)
- ✓ Four typed Cypher functions in `app/queries/`, each with full testcontainer coverage (23 tests)
- ✓ Four agent tool nodes wired into the StateGraph
- ✓ Router prompt redesigned (two-stage conceptual, 20 few-shots, priority rule)
- ✓ Synthesis + verification updated; structural tools work without fabricating citations
- ✓ `POST /api/ask` and `POST /api/ask/stream` handle all 10 routes (smoke-tested live)
- ✓ `/ask` page renders all four new result types (4 renderer tests pass)
- ✓ Extended eval ran end-to-end on 42 questions; real numbers in the report
- ✓ Route accuracy 1.000 (≥ 0.85); structural-only 1.000 (≥ 0.90)
- ✓ All Phase 4A/4B tests still pass; new tests pass (422 passed in full suite; failures all pre-existing)
- ✓ `mypy --strict` clean across all new code (0 new errors vs HEAD)
- ✓ `docker compose up` stack live; new routes reachable through nginx (port 3000 smoke test)
- ✓ Acceptance test: "name of all the employees" → `enumerate` → all 13 Person nodes (live-verified)
- ✓ HANDOFF.md updated (4B reference commit `5bc27f2`)

---

## State of the Codebase

**Backend:** `app/queries/` gained `structural_common.py` + four tool modules. `app/agent/`
modified: `state.py`, `schemas.py`, `tools.py`, `graph.py`, `verification.py`, `synthesis.py`,
`config.py`, `runner.py`, `api_router.py`, `prompts/{router,synthesis}.txt` + new
`prompts/synthesis_structural.txt`. `app/eval/agent_eval.py` extended. `data/agent_eval_questions.json`
30 → 42.

**Frontend:** `components/ask/results/` (4 renderers + dispatcher) added; `pages/Ask.tsx`,
`components/ask/StreamProgress.tsx`, `types.ts` modified. New test `Ask.structural.test.tsx`.

**Docs:** structural-tools.md, ADRs 0028–0030, phase-4c-readiness, phase-4c eval results, demo
beat extended, docs/README updated.

**Reference commit (4B baseline):** `5bc27f2` — "Phase 4B complete: streaming synthesis + agent UX polish".

---

## Next Subphase

**Phase 5A — Streaming Ingestion.** The read path (extraction → resolve → query → agent) is
complete through 4C. 5A turns the batch pipeline into an incremental one: new events arrive,
get extracted, resolved against the existing graph at write time, and the graph reconciles in
near-real-time (the "self-updating knowledge graph" thesis). Candidate work: an ingestion
endpoint/worker, at-write-time entity resolution (the resolver was built standalone for this in
3A), incremental embedding, and a demo beat showing a new Slack message updating an answer live.
