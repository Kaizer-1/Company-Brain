# Agent Architecture (Phase 4A)

> The agent turns a natural-language question into a grounded answer with clickable
> provenance. It is the phase that converts "I built a knowledge graph" into "I built an
> agent that grounds its answers in a knowledge graph." This document explains the design,
> walks the LangGraph state machine node by node, justifies the load-bearing decisions
> (typed tools, route-then-execute, provenance verification), and sketches the production
> scale path.

## 1. The shape of the problem

Every prior phase built infrastructure: a deterministic synthetic corpus (2A), an LLM
extraction pipeline with provenance (2B), entity resolution (3A), the four typed killer
queries (3B), a React frontend (3C), and hybrid semantic search at Recall@10 = 0.942 (3D).
Phase 4A is the layer that makes those usable from a single text box.

The agent must do three things, in order: **decide** what kind of question it is, **execute**
the right retrieval, and **answer** in prose where every claim is traceable to a Postgres
`events` UUID. The whole design is organised around making each of those three steps
legible, safe, and testable in isolation.

## 2. Why LangGraph (not LangChain, not a hand-rolled loop)

The agent is a small, fixed state machine: classify → execute one of six branches →
synthesise → verify → (retry or finish). That is exactly what LangGraph's `StateGraph`
models — typed state threaded through named nodes with explicit conditional edges. We use
LangGraph **directly** and avoid LangChain: LangChain's chains/agents abstractions add
layers (prompt templates, output parsers, agent executors) that obscure control flow for
marginal benefit at this scale. With raw LangGraph the entire graph fits in one readable
`build_agent_graph` function (`backend/app/agent/graph.py`), and an interviewer can trace
any request end to end. A hand-rolled `while` loop would also work, but LangGraph gives the
retry edge, the conditional routing, and a state contract for free, and makes the graph
diagrammable.

Dependencies (the LLM client, config, and the two DB handles) are bound into each node with
`functools.partial` at build time — LangGraph passes only the state to a node, so everything
else is closed over. The graph is compiled per request in `run_agent`; compilation is cheap
and this keeps per-run state (cost accumulation) free of shared mutability.

## 3. State

`AgentState` (`backend/app/agent/state.py`) is a `TypedDict(total=False)` — each node writes
only the keys it owns. The load-bearing field is `route: Literal["kq1","kq2","kq3","kq4",
"search","unknown"]`, which both selects the conditional edge and is echoed to the API
response. Other fields: `tool_input` (classifier-extracted params), `tool_output` (raw tool
result), `available_event_ids` (the flat citable set), `answer`, `citations`, `confidence`,
`verified`, `retry_count`, `error`, `timings_ms`, and `cost_usd`.

## 4. Node-by-node walkthrough

```
START → classify_route → (route) ─┬→ kq1_owner ──┐
                                  ├→ kq2_contra ─┤
                                  ├→ kq3_blast ──┼→ (citable?) ─┬→ synthesize_answer
                                  ├→ kq4_change ─┤              └→ empty_answer → END
                                  ├→ general_search ┘
                                  └→ unknown → END

synthesize_answer → verify_provenance → (verified or retries spent?) ─┬→ END
                                                                      └→ synthesize_answer
```

**`classify_route`** (`router.py`) makes one LLM call constrained to the six-value enum. The
prompt (`prompts/router.txt`) carries a description of each route plus 3–6 few-shot
examples. The response is validated into a `RouteDecision` Pydantic model; the classifier
cannot return free text. On any failure — bad JSON, schema mismatch, network error — it
falls back to `search`, never to a refusal (a question reaching the agent is assumed to be
about the graph). Target cost: < $0.001/call.

**Tool nodes** (`tools.py`) are thin glue. Each KQ node reads `tool_input`, validates the
parameters it needs, and calls the existing typed function in `app.queries` — no new query
logic. `general_search` calls `hybrid_search` with `k=8`. Each node writes `tool_output`
(serialised) and `available_event_ids` (from the KQ's `provenance.all_event_ids` or the
search hits' `event_id`s). If a KQ node lacks a required parameter it falls back to
`general_search` rather than to `unknown` (a deviation from the original spec, documented in
HANDOFF; a company question should degrade to grounded retrieval, not refuse). `unknown` is a
terminal that emits a polite capability-boundary message and skips synthesis.

**`empty_answer`** is the terminal for a tool that ran but found nothing citable (e.g. no
contradictions in the window). With no events to cite, synthesis is skipped and the absence
is stated honestly; `verified=True` because an empty result is a correct answer, not a
failure.

**`synthesize_answer`** (`synthesis.py`) makes one LLM call given the question, the tool
output, and the list of legal event ids. The constrained output is `AnswerWithCitations`,
whose `citations: list[str] = Field(min_length=1)` rejects an uncited answer before it ever
reaches verification. The prompt demands inline `[evt:UUID]` markers drawn only from the
supplied set. On retry it switches to `synthesis_strict.txt`, which explains that the prior
attempt failed verification and lists the legal ids again. Target cost: < $0.005/call.

**`verify_provenance`** (`verification.py`) is pure Python — no LLM. It extracts every
`[evt:UUID]` marker, confirms at least one exists and that every cited id is in
`available_event_ids`, and reconciles `state["citations"]` to exactly the inline references
(the inline markers are the source of truth). On failure it increments `retry_count` and,
while the budget remains, routes back to synthesis with the strict prompt.

## 5. Why typed tools, not generated Cypher (ADR 0023)

The agent calls Python functions — the four KQs plus `hybrid_search` — not LLM-authored
Cypher. This removes the entire query-injection / runtime-parse-error / silent-wrong-traversal
surface. The behaviour set is small and enumerable: an interviewer can probe all six routes.
The four KQs cover the demo-defining questions and `hybrid_search` covers the open-ended rest;
generated Cypher would add risk for marginal capability. The honest framing of the tradeoff —
"yes, I could generate Cypher, and here's why I chose not to" — is a stronger position than a
flaky generator. Full rationale in ADR 0023.

## 6. The provenance verification loop (ADR 0025)

Grounding is the project's thesis, so it is enforced mechanically, not hoped for. Three
guards stack: (1) the synthesis prompt instructs inline citation; (2) the Pydantic
`min_length=1` constraint rejects an empty citation list at the LLM boundary; (3)
`verify_provenance` rejects any answer that cites an id not present in the tool's provenance.
A rejected answer is regenerated with a stricter prompt, up to two retries. After two
retries the agent returns the best-effort answer flagged with `error="provenance_failed"`
rather than looping forever — this is rare and logged. There is no path by which a fabricated
citation reaches the user unflagged.

## 7. Cost, latency, and the single-model choice

The agent uses one model family in two roles — `anthropic/claude-3.5-haiku` for both routing
and synthesis (configurable in `agent/config.py`). One family keeps the cost model simple and
the voice consistent; the role split exists so the eval can diverge them. Two LLM calls plus
tool execution put a typical question in the low-single-digit-cents range and well under the
4 s latency target (the typed KQs are millisecond Cypher; search is ~150 ms warm). Every LLM
call is cost-logged via the shared `openrouter_completion` structlog event.

## 8. What is deliberately out of scope

Streaming (single JSON response only), multi-turn conversation memory (stateless per
request), and any side-effecting action (the agent is read-only by design — it answers, it
does not email, file tickets, or write files). These are named limitations, not unfinished
work; they map to Phase 4B and later.

## 9. Production scale path

- **Caching.** Route classification for repeated/similar questions and synthesis for
  identical (question, tool_output) pairs are cacheable; a semantic cache on the question
  embedding would cut cost and latency for the long tail of near-duplicate questions.
- **Streaming.** Token-level streaming of the synthesis step is a UX upgrade; the graph
  already isolates synthesis as the last generative node, so streaming is additive.
- **Multi-turn.** A conversation memory channel in the state plus a follow-up resolver node
  (rewriting "what about its owner?" into a standalone question) turns this into a chat agent
  without disturbing the route-then-execute core.
- **Access control.** Per-tenant graph scoping and row-level provenance filtering would gate
  what the agent can retrieve; the read-only boundary makes this tractable.
- **10× corpus.** The typed KQs are bounded-depth Cypher and scale with the graph index;
  search scales via the HNSW index (Phase 3D). The router and synthesis costs are per-question
  and independent of corpus size — the architecture does not change with scale, only the
  indices behind the tools do.
