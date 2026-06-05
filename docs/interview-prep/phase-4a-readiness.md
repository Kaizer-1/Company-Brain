# Phase 4A — Interview Readiness (Agent Layer)

12 Q&A pairs (each ≥ 100 words) and 6 whiteboard concepts. The numbers cited are from the
2026-06-05 eval run (`docs/eval/phase-4a-agent-results.md`).

---

## Q&A

### 1. Why LangGraph and not LangChain?

The agent is a small, fixed state machine — classify, execute one of six branches, synthesise,
verify, maybe retry. LangGraph's `StateGraph` models exactly that: typed state threaded through
named nodes with explicit conditional edges. I used it directly and avoided LangChain because
LangChain layers chains, output parsers, and agent executors on top, which obscure control flow
for marginal benefit at this scale. With raw LangGraph the entire graph is one readable
`build_agent_graph` function, and I can trace any request end to end — which matters for a
portfolio project where the interviewer wants to follow the logic. A hand-rolled loop would
also work, but LangGraph gives me the retry edge, conditional routing, and a state contract for
free, and it's diagrammable. The cost is one dependency; the benefit is legibility.

### 2. Why typed tools instead of letting the LLM generate Cypher?

The agent calls five Python functions — the four killer queries and `hybrid_search` — never
generated Cypher. The project's whole value is grounded, defensible answers, and a generated-
query layer adds an injection-and-hallucination surface for marginal capability gain. The four
typed queries cover the demo-defining questions and semantic search covers the open-ended rest.
Typed tools mean no injection, no runtime parse errors, no surprise traversals, and a small
enumerable behaviour set I can fully unit-test and an interviewer can probe. The honest framing
is the strong one: "yes, I could generate Cypher, and here's why I chose not to" beats "I tried
it and it was flaky." The trade-off is I can't answer arbitrary structural questions; the fix is
adding more typed tools, not opening a Cypher console. This is ADR 0023.

### 3. How does provenance verification prevent hallucination?

Three guards stack. First, the synthesis prompt demands inline `[evt:UUID]` citations drawn only
from a supplied list. Second, the Pydantic output model has `citations: list[str] =
Field(min_length=1)`, so an empty-citation answer fails validation at the LLM boundary. Third,
and decisively, a pure-Python `verify_provenance` node extracts every `[evt:UUID]` marker and
confirms each one actually appears in the tool's provenance — the set of event ids the typed
query or search returned. If any citation is fabricated, the node routes back to synthesis with
a stricter prompt that re-lists the legal ids, up to two retries. After that it returns the
best-effort answer flagged `error="provenance_failed"` rather than looping. There is no path by
which a fabricated citation reaches the user unflagged. On the eval, 86% of answers verified on
the first try and zero fabrications reached the response.

### 4. Why a five-route enum? Why not more tools?

The route classifier outputs one of six values: kq1–kq4, search, unknown. I capped the toolbox
deliberately. The four killer queries are the schema's reason for existing and cover the demo's
structural questions; `hybrid_search` covers everything open-ended; `unknown` is the out-of-scope
terminal. Adding tools like `get_decision_details` or `list_services_by_team` would dilute the
router's classification accuracy (more classes, more confusable boundaries) and inflate the eval
surface for little gain — those needs are better served by adding filters to `hybrid_search`.
A small enumerable set means I can hand-curate few-shot examples per route, test each branch in
isolation, and report a single route-accuracy number. On the eval that number was 1.000 across
30 questions including colloquial phrasings. The constraint is the feature.

### 5. What happens when the router misclassifies?

Two cases. If the router picks the wrong KQ or sends a KQ question to search, the answer is still
*grounded* — it cites real events — but may be suboptimal (a search answer where a typed
traversal would have been crisper). That's a soft failure: degraded quality, not a wrong claim.
If the router's LLM call fails entirely — bad JSON, schema mismatch, network error — the node
falls back to `search`, never to a refusal, because any question reaching the agent is assumed to
be about the graph. The one hard rule is that routing failure must never surface as "I don't
know." Separately, if a KQ node gets routed correctly but lacks a required parameter (no decision
id), it falls back to general search rather than refusing — a company question should degrade to
grounded retrieval. So misrouting costs answer quality, never grounding or availability.

### 6. Walk me through the cost per question.

Each question makes at most two LLM calls: one routing call and one synthesis call, both to
`claude-3.5-haiku`. On the eval the mean was $0.00307 per question, below the $0.005–$0.02 band I
expected. The distribution is informative: `unknown` questions cost about $0.001 because they make
only the routing call — no tool, no synthesis. Full KQ or search answers cost about $0.003 (two
calls). Retry cases, where verification failed and synthesis re-ran, reach $0.005–$0.007 because
synthesis runs two or three times. The router prompt is the expensive input (it carries few-shot
examples), but the output is tiny (an enum plus reasoning). A thousand questions costs roughly $3
at this corpus and model. Every call is cost-logged via the shared `openrouter_completion`
structlog event, so the number is measured, not estimated.

### 7. How would this scale to a 10× corpus?

The architecture doesn't change with corpus size — only the indices behind the tools do. The four
killer queries are bounded-depth Cypher; they scale with Neo4j's indices, not with the agent.
Semantic search scales via the HNSW index built in Phase 3D, which is sublinear in corpus size.
The router and synthesis costs are per-question and *independent* of corpus size — a 10× larger
graph doesn't make routing harder or synthesis longer, because the agent only ever sees one
tool's bounded output, not the whole graph. What would need attention at 10× is the candidate set
the synthesiser sees for high-fanout queries like KQ2 (which can return many contradiction
events); a larger legal-id list raises the chance of an off-by-one citation and thus retries. The
fix is capping or ranking the events passed to synthesis, not changing the agent.

### 8. How is this different from a vanilla RAG chatbot?

A vanilla RAG chatbot embeds the question, retrieves the top-k chunks by similarity, stuffs them
into a prompt, and generates. It cannot follow typed relationships, has no temporal reasoning, and
its "citations" are usually just the retrieved chunks — there's no check that the generated text
actually used them. This agent does three things RAG can't. First, it *routes*: structural
questions ("who owns the service deprecated by D-0006") go to a typed multi-hop graph traversal,
not a similarity search, because RAG retrieves flat chunks and cannot follow edges. Second, it
returns *structured provenance* from the graph — the exact events that justify each node and edge
in the answer. Third, it *verifies* that every claim cites a real provenance event before
returning, so grounding is enforced, not hoped for. RAG is one of my six routes (`search`), not
the whole system.

### 9. What's missing for production?

Four things, all named as deliberate scope cuts. **Streaming**: the endpoint returns a single
JSON response; token-level streaming of synthesis would cut perceived latency from ~6 s to a
~2 s first token. **Multi-turn**: the agent is stateless per request — no conversation memory, so
"what about its owner?" can't resolve against a previous answer; that needs a memory channel and a
follow-up-rewriting node. **Access control**: there's no per-tenant scoping or row-level
provenance filtering — fine for a single synthetic company, required for real multi-tenant data.
**Observability**: structured logs only, no metrics or tracing (carried project-wide). None of
these change the route-then-execute core; they're additive. The read-only boundary is also a
deliberate limit — the agent answers, it never emails, files tickets, or writes files.

### 10. What's the safety boundary?

Read-only by design, on three levels. At the *query* level, the agent calls typed Python
functions, never generated Cypher, so there's no write path and no injection surface (ADR 0023).
At the *action* level, the toolbox has no side-effecting tools — no email, no ticket creation, no
file writes; an action request like "email the team and deploy" routes to `unknown` and is
refused (eval q30 confirms this). At the *answer* level, provenance verification guarantees no
fabricated citation reaches the user unflagged (ADR 0025). So the worst the agent can do is return
a suboptimal-but-grounded answer or an honest refusal. That bounded blast radius is what makes the
"could you generate Cypher / take actions?" questions easy to answer: yes, both are possible, and
both were deliberately excluded with a written rationale.

### 11. Why the verify-then-retry loop, and why cap at two retries?

LLMs fix a single bad citation reliably when told exactly which ids are legal, so failing hard on
the first bad citation throws away recoverable answers — that's why I retry rather than reject. But
retries cost latency and money, and an unbounded loop on a genuinely hard question would blow both,
so I cap at two (three synthesis attempts total). Two is the measured sweet spot for this corpus:
the eval shows most failures recover within one retry, and the one question that exhausted the
budget (q10) was a genuine hard case where more retries wouldn't have helped — its synthesiser kept
citing events outside the (large) KQ2 provenance set. Beyond two, the right lever isn't more
retries, it's shrinking the candidate set the synthesiser sees. This is ADR 0025.

### 12. How do you know it works?

I have a 30-question hand-curated eval spanning all five routes plus five out-of-scope refusals,
run end-to-end through the deployed code path against the live populated graph. It measures six
things honestly: route accuracy (1.000), citation overlap as Jaccard against the typed query's own
provenance (0.608), first-try provenance verification rate (0.864), refusal correctness (1.000),
mean cost ($0.00307), and mean latency (6645 ms). Five of six targets were met; latency missed its
generous 4 s target because the agent makes two sequential network LLM calls — I report that
honestly with a failure-mode breakdown and the streaming/caching mitigations. The eval also caught
one genuine hard failure (q10 exhausted retries) which I left documented rather than tuning it
away. The point of the eval is that the first interview question — "how do you know?" — has a number
behind it, not a vibe.

---

## Whiteboard concepts

1. **The route-then-execute graph.** Draw START → `classify_route` → six-way conditional →
   {kq1..kq4, search, unknown} → (citable? → synthesize | empty_answer) → `verify_provenance` →
   (verified/exhausted? → END | back to synthesize). Mark the two LLM calls (classify, synthesize)
   and the one pure-Python check (verify). This is the whole system on one board.

2. **The provenance guarantee, three layers.** Prompt asks for `[evt:UUID]`; Pydantic
   `min_length=1` rejects empty; Python verifier checks each id ∈ tool provenance, else retry.
   Draw the arrow from verify back to synthesize and the "max 2" cap with the flagged best-effort
   exit. The takeaway: grounding is mechanical, not prompted.

3. **Typed tool vs generated Cypher.** Two boxes. Left: LLM → Cypher string → validator → DB
   (injection/parse/wrong-traversal surface in red). Right: LLM → route enum + params → Python
   function → DB (surface eliminated). The toolbox is exactly five functions.

4. **State as a TypedDict channel set.** Show `AgentState` keys and which node writes each
   (`route` by classify, `tool_output`/`available_event_ids` by tools, `answer`/`citations` by
   synthesize, `verified`/`retry_count` by verify). Nodes write only their keys; deps are bound by
   `functools.partial`, not passed in state.

5. **Citation resolution at the edge.** Agent emits `[evt:UUID]` markers and a UUID list; the
   runner resolves each UUID → full `Citation` (source kind, ref, snippet) via one batched lookup,
   so the frontend renders clickable superscripts with zero follow-up requests. Draw answer text →
   superscript ¹²³ → numbered Sources list → EventModal.

6. **Why RAG fails the four KQs, and where search fits.** A 2×2: structural-vs-semantic question ×
   typed-query-vs-similarity. KQ1/KQ3 (multi-hop, blast radius) need edge traversal — RAG's flat
   similarity can't follow edges. KQ2/KQ4 need temporal set logic — RAG has no time index.
   Open-ended questions are where `search` (RAG) belongs — one of six routes, not the whole agent.
