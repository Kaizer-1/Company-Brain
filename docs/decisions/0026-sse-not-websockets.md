# ADR 0026 — SSE Not WebSockets for the Streaming Ask Endpoint

## Status

Accepted

## Context

Phase 4B adds real-time streaming to the `/ask` endpoint so that synthesis tokens
appear as they are generated rather than after the full LLM call completes. This
requires a server-push mechanism. The candidates are:

1. **Server-Sent Events (SSE)** over `POST /api/ask/stream`
2. **WebSockets** (`ws://` or `wss://`)
3. **Plain HTTP streaming** (chunked transfer encoding, no framing protocol)

## Decision

Use **Server-Sent Events** via a new `POST /api/ask/stream` endpoint returning
`Content-Type: text/event-stream`.

The frontend uses `fetch` + `ReadableStream` reader (not the browser's `EventSource`
API) because `EventSource` only supports `GET` requests and cannot send a JSON body.

## Rationale

**SSE is the right fit for this communication pattern.**

The agent interaction is strictly one-way server→client once the question is submitted.
The client sends one JSON body (the question) and then receives a stream of typed events.
There is no bidirectional need: the client never sends mid-stream messages, cancels are
handled by the `AbortController` on the HTTP connection, and session state is per-request
(not across requests). WebSockets are designed for bidirectional, long-lived sessions —
using them here would add handshake overhead, a stateful connection lifecycle, and a
more complex client implementation for no benefit.

SSE over `fetch` + reader gives:
- POST body support (the missing feature in native `EventSource`)
- `AbortController` cancellation (closes the underlying fetch connection)
- Standard `event: type\ndata: json\n\n` framing that is trivially parsed
- No persistent connection state to manage on the server
- Full compatibility with nginx reverse proxy (no special WS upgrade configuration)
- Fallback to JSON endpoint via a single constant flip (`USE_STREAMING = false`)

**WebSockets would add complexity with no benefit here.** The only advantage of WebSockets
would be if the client needed to send messages after the connection is established (e.g.
multi-turn, mid-stream follow-ups, or real-time collaborative editing). All of those are
out of scope for this phase.

**Plain chunked HTTP** (no SSE framing) was also considered. It works but loses the
`event:` type field, requiring the client to parse structure from the raw body. SSE's
framing is trivial overhead for a significant simplification in parsing.

## Consequences

- `POST /api/ask/stream` uses `StreamingResponse(media_type="text/event-stream")`.
- The original `POST /api/ask` JSON endpoint is unchanged and continues to pass all
  existing tests.
- The nginx proxy in Docker requires no changes (SSE is plain HTTP; no WS upgrade).
- The eval script (`run_streaming_eval.py`) uses the HTTP path directly, not SSE — it
  calls the Python streaming functions in-process to avoid starting an HTTP server.
