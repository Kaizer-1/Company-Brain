# Agent Streaming (Phase 4B)

> This document describes the SSE streaming protocol, the backend implementation, the
> frontend integration, and what is *not* changed by streaming. Read
> `docs/design/agent-architecture.md` first for the agent core.

## 1. The problem streaming solves

Phase 4A confirmed the agent works (route accuracy 1.000, verification 0.864, citation
overlap 0.608). The one miss was latency: 6645ms mean, which feels slow in the browser
even when the architecture is sound. The two sequential LLM calls — route classification
(~2s) and synthesis (~3.5s) — are the floor; no architecture change can go below their
sum. Streaming does not reduce the floor; it reduces **perceived latency** by showing
the user something useful at ~2.5s instead of waiting until ~6.5s for the complete
response.

## 2. What is streamed and what is not

| Stage | Streaming behaviour |
|-------|---------------------|
| Route classification | One `route` event emitted when complete (~2s) |
| Tool execution | `tool_start` emitted before; `tool_done` emitted after |
| Synthesis | `synthesis_token` emitted for each LLM output token |
| Provenance verification | `verify_start` / `verify_done` events |

**Only synthesis is token-streamed.** See ADR 0027 for the full rationale. The short
version: route/tool/verify produce structured objects or run instantly — streaming
partial JSON would be unusable, and there are no tokens to stream from a Cypher query.

## 3. The SSE protocol

`POST /api/ask/stream` accepts the same `AskRequest` body as `POST /api/ask` and
returns `Content-Type: text/event-stream`. The event sequence for a successful question
is:

```
event: route
data: {"route": "kq3", "reasoning": "blast radius question", "tool_input": {"service": "payments-api"}}

event: tool_start
data: {"tool": "kq3", "params": {"service": "payments-api"}}

event: tool_done
data: {"tool_output_summary": "10 events", "timings_ms": {...}}

event: synthesis_start
data: {"retry": false}

event: synthesis_token
data: {"text": "The blast radius of "}

event: synthesis_token
data: {"text": "payments-api includes "}

... (many more tokens)

event: synthesis_done
data: {"answer_final": "The blast radius of payments-api...", "citations_raw": ["uuid1", ...]}

event: verify_start
data: {}

event: verify_done
data: {"verified": true, "retry_count": 0}

event: complete
data: {"answer": "...", "citations": [...], "route": "kq3", "confidence": "high", ...}
```

The `complete` event carries the full response in the same shape as `POST /api/ask`,
including resolved citations. The frontend hydrates the full answer display from this
event.

If provenance verification fails and the agent retries, additional `synthesis_start` →
`synthesis_token`* → `synthesis_done` → `verify_start` → `verify_done` events are
emitted. The `synthesis_start` event's `retry: true` field signals the frontend to show
"Refining answer…" and clear the previous streaming text.

If an unrecoverable error occurs at any stage, an `error` event is emitted and the
stream ends:

```
event: error
data: {"error": "...", "stage": "synthesis"}
```

## 4. Backend implementation

### Why not LangGraph's astream?

LangGraph has `astream` and `astream_events` primitives that expose internal
state-machine transitions. We do not use them here. The reason is control: those
primitives expose LangGraph's internal vocabulary (node names, state keys, internal
graph events) through the API, coupling the SSE protocol to implementation details.
The Phase 4B streaming endpoint calls the agent node functions directly, giving
precise control over which events are emitted and when. See ADR 0027.

### Key files

| File | Change |
|------|--------|
| `backend/app/extraction/client.py` | Added `astream_completion` — yields text tokens from a streaming OpenRouter response, calls `on_complete` callback at stream end |
| `backend/app/agent/streaming.py` | New module: `format_sse`, event type constants |
| `backend/app/agent/synthesis.py` | Added `astream_synthesize(state, deps, on_token)` — same logic as `synthesize_answer` but streams tokens via callback |
| `backend/app/agent/api_router.py` | Added `POST /api/ask/stream` endpoint using `StreamingResponse` |

### The callback-to-queue bridge

`astream_synthesize` uses an `on_token: Callable[[str], Awaitable[None]]` callback
because async generators cannot `yield` from inside a nested callback. The streaming
endpoint bridges this with an `asyncio.Queue`:

1. Create a per-synthesis-attempt `asyncio.Queue[str | None]`
2. Create an `on_token` closure that puts chunks in the queue
3. Start `astream_synthesize` as an `asyncio.Task`
4. Add a done-callback that puts a `None` sentinel when the task finishes
5. Loop: `chunk = await queue.get()` → if not None, yield `synthesis_token` SSE event

This pattern is standard for bridging callback-based producers to generator-based
consumers in asyncio.

### The retry loop

If verification fails, the outer while loop increments `retry_count` and re-runs
synthesis with the strict prompt. Each pass emits a fresh `synthesis_start(retry=True)`
event and new `synthesis_token` events. The frontend clears its streaming text buffer
on `synthesis_start(retry=True)` and shows "Refining answer…".

## 5. Frontend integration

### Why fetch + ReadableStream, not EventSource

The browser's `EventSource` API only supports GET requests. Since the question is in
the POST body, `EventSource` cannot be used. See ADR 0026.

### Key files

| File | Change |
|------|--------|
| `frontend/src/api/askStream.ts` | New: async generator over `fetch` + ReadableStream reader |
| `frontend/src/types.ts` | Added `StreamEvent` discriminated union and per-event interfaces |
| `frontend/src/components/ask/StreamProgress.tsx` | New: per-stage progress display |
| `frontend/src/components/ask/AnswerView.tsx` | Added `streaming` prop; defers citation rendering until `complete` |
| `frontend/src/pages/Ask.tsx` | `USE_STREAMING = true`; streaming state machine replaces `useMutation` |

### The streaming state machine in Ask.tsx

The page maintains `StreamState = { status, events, streamingText, result, error }`.
Each SSE event updates the state:

- `route` → adds to `events`; `StreamProgress` renders route badge
- `tool_start`/`tool_done` → adds to `events`; `StreamProgress` renders tool status
- `synthesis_start(retry=true)` → clears `streamingText`
- `synthesis_token` → appends to `streamingText`; `StreamProgress` renders growing text
- `verify_*` → adds to `events`; `StreamProgress` renders verification status
- `complete` → sets `result`; page transitions to `AnswerView` + `CitationList`
- `error` → sets `error`; renders inline error message

The `USE_STREAMING = true` constant at the top of `Ask.tsx` can be flipped to `false`
to fall back to the JSON endpoint. This is the rollback mechanism described in ADR 0026.

### Citation rendering

`AnswerView` defers the `[evt:UUID]` → superscript transform until `streaming=false`
(i.e., until the `complete` event). During streaming, partial UUIDs could match the
regex mid-token and cause flicker. The full transform runs once on the finalized answer.

## 6. What is not changed

- `POST /api/ask` JSON endpoint — unchanged, all existing tests pass
- The agent's LangGraph graph (`graph.py`) — unchanged
- Routing logic, tool functions, verification — unchanged
- The agent eval (`run_agent_eval.py`) — still uses the JSON endpoint
- All Phase 4A tests — continue to pass

## 7. Perceived-latency eval

`backend/scripts/run_streaming_eval.py` measures time-to-first-synthesis-token for 10
questions sampled from the Phase 4A eval set. Target: mean ≤ 3000ms. See
`docs/eval/phase-4b-streaming-results.md` for results.

---

## Related ADRs

- [ADR 0026](../decisions/0026-sse-not-websockets.md) — SSE over WebSockets: why unidirectional push is sufficient for this use case
- [ADR 0027](../decisions/0027-stream-synthesis-only.md) — Why only the synthesis step streams, not the full agent trace
