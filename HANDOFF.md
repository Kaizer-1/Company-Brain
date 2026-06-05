# HANDOFF — Company Brain

> **This file is overwritten at the end of every subphase.**
> Structure: Subphase → What was built → Decisions made → Deviations → Open questions → DoD check → Codebase state → Next subphase.
> Future sessions: read `CLAUDE.md` first, then this file.

---

## Subphase

Phase 4A — The Agent Layer

## Date

2026-06-05

---

## What Was Built

A LangGraph agent that turns a natural-language question into a grounded answer with
clickable provenance. Routing → typed-tool execution → answer synthesis → provenance
verification, exposed at `POST /api/ask` and a new `/ask` frontend page.

### Backend: `app/agent/` module (new)

- `config.py` — `AgentConfig` dataclass: model names (`anthropic/claude-3.5-haiku` for both
  router + synthesis), temperatures, retry cap (2), `search_k=8`, prompt paths. Prompts are
  read per-request so a volume-mounted edit takes effect without restart.
- `state.py` — `AgentState` TypedDict (`total=False`) + `RouteLiteral`/`ROUTE_VALUES`. Added
  `cost_usd` channel for per-question cost accumulation.
- `schemas.py` — LLM-boundary models (`RouteDecision`, `AnswerWithCitations` with
  `citations: Field(min_length=1)`) + HTTP models (`AskRequest`, `AskResponse`, `Citation`,
  `AgentStateDump` incl. `cost_usd`). **`RouteLiteral` is imported at runtime** (`# noqa: TC001`)
  — it's a Pydantic field type, breaks model-building under TYPE_CHECKING.
- `deps.py` — `AgentDeps` (client, config, neo4j_driver, session_factory) bound into nodes via
  `functools.partial`.
- `llm.py` — `complete_to_model[T]`: shared call → strip-fences → `json.loads` → `model_validate`,
  raising typed `AgentLLMError` (stage call/json/schema). Broad call-boundary catch so the
  load-bearing router can always fall back.
- `router.py` — `classify_route` node. One enum-constrained LLM call; any failure falls back to
  `route="search"` (never a refusal).
- `tools.py` — `kq1_owner`/`kq2_contra`/`kq3_blast`/`kq4_change` (thin glue over `app.queries`),
  `general_search` (over `hybrid_search`, k=8), `empty_answer` terminal, `unknown` terminal.
- `synthesis.py` — `synthesize_answer`; strict prompt on retry; graceful fallback on LLM failure.
- `verification.py` — `verify_provenance` (pure Python) + `route_after_verify` conditional edge.
  **`AgentState` imported at runtime** (`# noqa: TC001`) — LangGraph calls `get_type_hints` on
  the edge function at compile time.
- `graph.py` — `build_agent_graph(deps)` assembles + compiles the StateGraph.
- `runner.py` — `run_agent(question, *, neo4j_driver, session_factory, debug, config, client)`;
  resolves citation UUIDs → full `Citation` objects (one batched lookup); owns/closes the LLM
  client unless injected.
- `api_router.py` — `POST /api/ask`, registered in `main.py` after `search_router`.
- `prompts/{router,synthesis,synthesis_strict}.txt`.

### Pyproject

- Added `langgraph>=0.2.0` (resolved to 1.2.4; pulled `langchain-core` 1.4.0 — **no langchain**).

### Frontend: `/ask` page (new)

- `pages/Ask.tsx` — single-column page; always queries with `debug=true`. ⌘↵ to ask.
- `components/ask/AnswerView.tsx` — renders `[evt:UUID]` markers as clickable superscripts.
- `components/ask/CitationList.tsx` — numbered Sources list → EventModal.
- `components/ask/AgentTrace.tsx` — `<details>` disclosure: route, reasoning, timings, verified.
- `api/ask.ts` — `runAsk(question, debug)`.
- `types.ts` — added `AskRequest`/`AskResponse`/`Citation`/`AgentStateDump`/`AgentRoute`/`AgentConfidence`.
- `App.tsx` — `/ask` route. `TopBar.tsx` — `ask` is the **first** nav item; hint `g k/h/g/q/s/a`.
- `hooks/useKeyboardNav.ts` — `g k` → `/ask`.

### Eval

- `backend/data/agent_eval_questions.json` — 30 hand-curated questions (5 per KQ, 5 search,
  5 out-of-scope). KQ questions carry `expected_tool_input`; the eval derives gold citations by
  calling the typed query directly (event UUIDs are random per seed, so no hard-coded ids).
- `backend/app/eval/agent_eval.py` — eval logic + `render_agent_report`.
- `backend/scripts/run_agent_eval.py` — runner.
- `docs/eval/phase-4a-agent-results.md` — **real numbers + hand-written Discussion**.

### Docs

- `docs/design/agent-architecture.md` (~1400 words).
- ADRs `0023` (typed tools not generated Cypher), `0024` (route-then-execute), `0025`
  (provenance verification loop).
- `docs/interview-prep/phase-4a-readiness.md` (12 Q&A + 6 whiteboard concepts).
- `docs/demo/3-minute-walkthrough.md` — added Beat 3.5 (`/ask`), updated closer + notes.
- `docs/README.md` — all new docs listed.

### Tests (`backend/tests/agent/`, 38 passing)

- `conftest.py` (FakeClient + make_deps), `test_agent_router.py` (11), `test_agent_tools.py`,
  `test_agent_synthesis.py`, `test_agent_verification.py`, `test_agent_runner.py`,
  `test_agent_api.py` (testcontainer Postgres + mocked Neo4j + scripted FakeClient).
- Frontend: `src/__tests__/Ask.test.tsx` (5 tests). All 26 frontend tests pass.

---

## Decisions Made

| ADR | Decision |
|-----|---------|
| [0023](docs/decisions/0023-typed-tools-not-generated-cypher.md) | Agent calls five typed Python functions, never LLM-generated Cypher |
| [0024](docs/decisions/0024-route-then-execute-architecture.md) | Constrained route classifier → fixed branch → synthesis, not an end-to-end tool-calling loop |
| [0025](docs/decisions/0025-provenance-verification-loop.md) | Verify-then-retry (max 2) Python check that every cited event id is in the tool's provenance |

**Model**: `anthropic/claude-3.5-haiku` for both router and synthesis (the existing
`ADJUDICATOR_MODEL` string), configurable via `AgentConfig`. One family, two roles.

---

## Deviations from Spec

1. **KQ nodes fall back to `general_search`, not `unknown`, on missing params.** Decision 3 in
   CLAUDE.md said "fall through to unknown if invalid". A question that routed to a KQ is about
   the company graph; refusing it violates the "never refuse a company question" rule. Missing a
   required param (e.g. no decision id) falls back to grounded search with a note appended to
   `route_reasoning`. `unknown` is reserved for genuinely out-of-scope questions the router flags.

2. **`cost_usd` added to `AgentState` and `AgentStateDump`** (not in the spec's state shape) so
   the eval can report per-question cost. Surfaced only in the debug dump, not the top-level
   `AskResponse`.

3. **Eval citation ground truth is computed, not stored.** Event UUIDs are `uuid4` (random per
   seed), so hard-coding `expected_citation_event_ids` would be brittle. For KQ questions the gold
   set is the typed query's own provenance, computed at eval time; search/unknown questions have no
   gold and are excluded from the citation-overlap metric.

4. **`docs/eval/phase-4a-agent-results.md` Discussion is hand-written**, appended to the
   script-generated table (same pattern as the 3D search eval). A re-run overwrites the table; the
   Discussion must be re-added (the run is stochastic + costs real $, so re-runs are deliberate).

---

## Open Questions

1. **Latency missed the 4s target (mean 6645ms).** Two sequential network LLM calls; retries push
   failure cases to 10–17s. Median ~6.4s; `unknown` (one call) is 1.4–2.3s. Fix is Phase 4B:
   stream synthesis (perceived first-token ~2s), cache routing, faster router model. Documented in
   the eval Discussion.

2. **One eval question (q10) exhausts the retry budget** (`error=provenance_failed`). KQ2 returns
   many contradiction events → larger legal-id set → higher chance of an off-by-one citation. The
   lever is shrinking the candidate set the KQ2 synthesiser sees, not more retries. Left honest.

3. **Pre-existing test failures, NOT from 4A** (confirmed by stashing 4A changes): `test_audit.py`,
   `test_graph.py`, `test_events.py` fail/error on the current checkout due to old test patterns
   (`asyncio.get_event_loop().run_until_complete()`, `Event(id=...)`). The KQ, search, and all 4A
   tests pass. These should be fixed in a cleanup pass but are out of 4A scope.

4. **Pre-existing frontend build was broken** (`ResultCard.tsx` unused `nodeTypeBadge` import, an
   error under `tsc -b` / `noUnusedLocals`). Fixed it (one-line) to unblock the frontend image
   build; the 3C/3D frontend had never been built in Docker (3D HANDOFF: "not yet confirmed in
   browser"). Frontend now builds and serves `/ask`.

5. **`backend/data/` is not volume-mounted or COPYed into the image.** Only the eval *script* reads
   `agent_eval_questions.json`, and the script is run via `uv` locally, so this is fine. If the eval
   ever needs to run inside the container, add a COPY.

---

## Definition of Done Check

- ✓ `docs/design/agent-architecture.md` ≥ 1200 words (~1400)
- ✓ Three ADRs written (0023, 0024, 0025)
- ✓ LangGraph StateGraph assembles + runs end-to-end against the live backend
- ✓ `POST /api/ask` works against the populated graph (verified in-container + via nginx proxy)
- ✓ `/ask` page renders; citations clickable to EventModal; agent trace expands
- ✓ Agent eval ran end-to-end; results doc has real numbers + Discussion
- ✓ Route accuracy 1.000 (≥ 0.85); refusal correctness 1.000 (≥ 0.80)
- ✓ Provenance verification rate 0.864 (≥ 0.80); citation overlap 0.608 (≥ 0.50)
- ✓ Mean cost reported honestly ($0.00307/question)
- ⚠ Mean latency 6645ms > 4000ms target — documented with failure-mode + mitigations (Open Q #1)
- ✓ All four KQs still pass; semantic search unaffected (no 3B/3D code paths touched)
- ✓ `mypy --strict` clean across `backend/app/agent/` (+ `eval/agent_eval.py`)
- ✓ 38 new agent tests pass; 26 frontend tests pass; pre-existing failures are pre-existing (Open Q #3)
- ✓ `docker compose up` brings full stack incl. agent; backend image rebuilt with langgraph; prompts shipped in image
- ✓ HANDOFF.md updated; 3D reference commit `f010384`

---

## State of the Codebase

**Backend:**
- `app/agent/` — 13 modules + 3 prompt files; mypy-strict clean; ruff clean.
- `app/main.py` — `agent_router` registered.
- `app/eval/agent_eval.py` + `scripts/run_agent_eval.py`.
- `pyproject.toml` — `langgraph>=0.2.0`; `uv.lock` updated.
- 38 agent tests in `backend/tests/agent/`.
- Docker image rebuilt: langgraph imports, prompts present at `/app/app/agent/prompts/`, `/api/ask` live.

**Frontend:**
- `/ask` page + 3 components + `api/ask.ts`; types extended; nav + shortcut updated.
- `ResultCard.tsx` unused-import fixed (unblocked the build).
- Builds clean (`tsc -b && vite build`); image rebuilt; serves `/` and `/ask`.

**Docs:** agent-architecture, ADRs 0023–0025, phase-4a-readiness, eval results, demo beat, README.

**Reference commit (3D baseline):** `f010384`

---

## Next Subphase

**Phase 4B — Frontend polish + agent UX.** Candidate work: streaming synthesis (the biggest
latency win — synthesis is already the isolated last node), conversation memory (a follow-up
resolver node + memory channel), routing cache, and demo polish. The agent core
(route → typed tool → synthesize → verify) is proven and should not need structural changes;
4B is additive on top of it.
