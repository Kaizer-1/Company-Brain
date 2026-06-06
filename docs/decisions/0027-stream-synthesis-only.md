# ADR 0027 — Stream Synthesis Only; Route and Tool Stages Emit One Event Each

## Status

Accepted

## Context

Phase 4B adds token-level streaming to improve perceived latency on the `/ask` page.
The agent has four stages: route classification, tool execution, synthesis, and
provenance verification. A natural question is: should all four stages stream their
output token by token?

## Decision

**Stream only the synthesis stage.** Route classification, tool execution, and
verification each emit a single SSE event when they complete; they do not stream
their internal computation.

## Rationale

**Streaming synthesis is the only stage where streaming provides a UX benefit.**

Route classification produces one structured JSON object (a `RouteDecision` with a
route enum, a short reasoning string, and a tool_input dict). This object is validated
against a Pydantic schema before it is used. Streaming the partial JSON would mean the
client receives unusable partial output — it cannot render a route badge from half a
JSON string. The route decision arrives in ~2s as a complete, validated object; emitting
it as a single `route` event when it is ready is both simpler and more useful.

Tool execution runs a typed Python function (a Cypher query or a vector search). These
are not LLM calls; they do not produce token streams. They are fast (Cypher: <100ms;
search: ~150ms) and return structured data. There is nothing to stream.

Provenance verification is pure Python — no LLM call, no external I/O. It runs in
milliseconds. A `verify_start` / `verify_done` event pair is sufficient.

Synthesis is where the latency lives. Two sequential LLM calls (router + synthesis) are
the floor — ~6.5s mean in Phase 4A. Of that, the synthesis call accounts for ~3.5s.
Streaming synthesis tokens means the user sees the first words of the answer after
~2.5s (route + tool time) rather than waiting 6.5s for the complete response. This is
the UX win that Phase 4B targets.

**Not streaming LangGraph internals is a deliberate choice (see also ADR 0024).**
LangGraph has `astream` and `astream_events` methods that expose internal state machine
transitions. Using these would couple the SSE protocol to LangGraph's internal event
vocabulary and make the streaming contract harder to reason about, test, and explain.
The Phase 4B streaming endpoint bypasses LangGraph's compiled graph and calls the agent
node functions directly — this gives precise control over which events are emitted and
when, without exposing implementation details through the API.

## Consequences

- The streaming endpoint (`POST /api/ask/stream`) does not use `graph.ainvoke` or
  `graph.astream`. It calls `classify_route`, the tool function, `astream_synthesize`,
  and `verify_provenance` directly.
- Existing tests against `POST /api/ask` (which does use `graph.ainvoke`) continue to
  pass unchanged. The streaming endpoint is additive, not a replacement.
- The LangGraph graph is unchanged. `build_agent_graph` still compiles and is still
  used by the JSON endpoint and the agent eval.
- If a future phase needs to stream a different stage (e.g. a reasoning-trace node),
  the same pattern applies: emit a start event, stream tokens via `astream_completion`,
  emit a done event.
