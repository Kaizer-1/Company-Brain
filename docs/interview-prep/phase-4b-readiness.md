# Phase 4B Interview Readiness — Streaming, UX Polish, and Demo Readiness

## Q1: Why did you add streaming, and what problem does it actually solve?

The Phase 4A agent had mean latency of 6645ms — more than 6 seconds from question
submission to a rendered answer. That latency is the sum of two sequential LLM calls
(route classification ~2s, synthesis ~3.5s) plus tool execution. There is no
architectural shortcut below that sum; the model calls are the floor.

Streaming does not reduce actual latency. It reduces **perceived latency** — the
time from submission to "something useful appearing on screen." Without streaming,
the user sees a blank page for 6.5 seconds. With streaming, the route badge appears
at ~2 seconds (after the router returns), then synthesis tokens stream in starting at
~2.5 seconds. The user's psychological experience changes from "waiting for an answer"
to "watching an answer being formed."

This matters because the demo is what Phase 4B is optimizing for. A 6-second blank
pause kills a demo's energy; a streaming answer creates the same energy as watching
a capable system think.

---

## Q2: Why SSE and not WebSockets?

The communication pattern is strictly one-way after the question is submitted: the
server pushes events to the client; the client never sends mid-stream messages.
WebSockets are designed for bidirectional, long-lived sessions — they add handshake
overhead, connection state management, and nginx proxy configuration for no benefit
in this one-directional pattern.

SSE gives us: standard HTTP (no upgrade), POST body support via `fetch` + reader (the
native `EventSource` API only supports GET), `AbortController` cancellation, trivial
`event: type\ndata: json\n\n` framing, and instant fallback to the JSON endpoint by
flipping one constant. The evaluation is simple: if the client doesn't need to send
anything after the question is submitted, SSE is the right tool. Full rationale in
ADR 0026.

---

## Q3: Why stream only synthesis and not the other stages?

The route classification produces one structured JSON object (validated against a
Pydantic schema) and arrives in ~2 seconds. Streaming partial JSON would be unusable —
you can't render a route badge from half a JSON string, and the Pydantic validation
that enforces the route enum can't run on partial output. It's emitted as a single
`route` SSE event when it's ready.

Tool execution is Cypher queries and vector search — not LLM calls, no tokens to
stream. Fast (< 500ms warm), structured output. Emitting a `tool_done` event is the
right model.

Verification is pure Python (~10ms). `verify_start`/`verify_done` events are enough.

Synthesis is where the latency lives. ~3.5s of LLM output is long enough that
token-level streaming meaningfully changes the UX. The model's streaming API (`stream:
true` with SSE chunks in the OpenAI format) is designed exactly for this. Full
rationale in ADR 0027.

---

## Q4: How does the verification retry interact with streaming?

If verification fails (a citation in the answer doesn't appear in the tool's
provenance), the agent re-runs synthesis with the strict prompt. In the streaming
path, this means the SSE stream emits a second pass of events:

```
... synthesis_done (first attempt) ...
verify_start → verify_done(verified=false)
synthesis_start(retry=true)
synthesis_token... synthesis_token...
synthesis_done
verify_start → verify_done(verified=true)
complete
```

The `synthesis_start(retry=true)` event signals the frontend to clear its streaming
text buffer and show "Refining answer…" instead of appending to the first attempt's
text. The user sees the answer being reconsidered rather than two answers stacked.

The backend handles this with a `while retry_count <= max_synthesis_retries` loop in
the streaming handler. Each iteration creates a fresh `asyncio.Queue` and a fresh
`on_token` closure bound to that queue. The done-callback sentinel pattern ensures the
reader loop exits cleanly even if synthesis throws.

The callback-to-queue bridge is the key mechanism: `astream_synthesize` uses an
`on_token: Callable[[str], Awaitable[None]]` callback because async generators can't
`yield` from nested callbacks. The queue bridges the callback-based producer to the
yield-based SSE generator.

---

## Q5: What is the difference between perceived latency and actual latency?

**Actual latency**: the time from request submission to the final `complete` event.
This is unchanged by streaming — it's still the sum of route + tool + synthesis +
verify = ~6.5s for a typical question.

**Perceived latency**: the time from submission to "something useful appearing on
screen." With streaming: the route badge appears at ~2s; the first synthesis token
appears at ~2.5s; the answer builds progressively over the remaining ~4s.

The Phase 4B streaming eval measures **time-to-first-synthesis-token** as the
UX-relevant metric (target: ≤ 3000ms mean). Total time is reported honestly for
completeness but is not the target metric. This framing matters in interviews:
"streaming made it faster" is technically wrong; "streaming made it feel faster for
the same actual work" is correct.

---

## Q6: How does the filter validation guard work, and why did you add it?

Phase 4A's evaluation revealed the router hallucinating entity types and source kinds
not in the schema. For example, it produced `entity_type: ["Employee"]` (the correct
value is `"Person"`) and `source_kind: ["org chart"]` (which is not a valid source
type at all). These hallucinated values silently filtered out all results — a question
about employees returned nothing because the search layer tried to match `entity_type
= "Employee"` against a graph where all people are labelled `Person`.

The fix has two parts:

1. **Prompt-level**: `router.txt` now explicitly enumerates valid values for
   `entity_type` (`Person`, `Team`, `Service`, `System`, `Decision`, `Message`)
   and `source_kind` (`doc`, `slack_message`) and instructs the model to use an
   empty filter rather than guessing if a match isn't certain.

2. **Python-level guard**: `tools.py`'s `_build_filters` function now validates router-
   provided values against the known enum sets and drops invalid values with a warning
   log. An all-invalid filter collapses to no filter (safe; broad results better than
   zero results). This makes the prompt hardening defense-in-depth: even if the model
   ignores the instruction, the invalid value never reaches the search layer.

Defense-in-depth is the right pattern for an LLM boundary: prompt instructions reduce
the failure rate; Python guards enforce the invariant regardless of model behavior.

---

## Q7: Walk me through the empty-result UX change.

Before Phase 4B, when a search or KQ returned zero results the `empty_answer` node
returned:

> "I queried the graph but found no matching records for that question. There may be
> no relevant data in the corpus, or the entity named may not exist."

This copy is honest but not useful. The user doesn't know what the agent tried, whether
the filters were too narrow, or what to do next.

The updated copy includes:
1. The filters that were applied (if any), so the user can see "oh, I filtered to
   `entity_type=Person` which was too narrow"
2. A specific suggestion: rephrase without filters, or try the predefined KQ queries

Example for a question that applied an `entity_type: Person` filter:

> "I couldn't find specific information matching that question (filters applied:
> entity_type=Person). You might get more results by rephrasing without specific
> filters, or by trying one of the four predefined queries on the Queries page."

The improvement is behavioral: a user who sees what was tried can act on it. The
original copy only told them something wasn't found; the new copy shows them the
search's parameters so they can debug their question.

---

## Q8: What's the rollback plan if streaming causes production issues?

Two-line rollback: set `USE_STREAMING = false` in `Ask.tsx` and redeploy the frontend.
The `POST /api/ask` JSON endpoint is unchanged and tested; it never went away.

The streaming endpoint is strictly additive. No existing code paths changed. The
LangGraph graph, router, tools, synthesis, and verification nodes are identical to
Phase 4A. The streaming endpoint calls the same functions directly; if those functions
have bugs they would manifest in both endpoints identically.

The streaming-specific risk is the callback-to-queue bridge and the SSE serialization.
Both are tested in `test_streaming.py` and `test_streaming_api.py`. If an issue
appears in production that doesn't appear in tests (e.g. a FastAPI/uvicorn interaction
with the `StreamingResponse` generator), the fallback is immediate and requires no
backend deployment — only the frontend constant changes.
