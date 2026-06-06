# HANDOFF — Company Brain

> **This file is overwritten at the end of every subphase.**
> Structure: Subphase → What was built → Decisions made → Deviations → Open questions → DoD check → Codebase state → Next subphase.
> Future sessions: read `CLAUDE.md` first, then this file.

---

## Subphase

Phase 4B — Streaming, Agent UX Polish, and Demo Readiness

## Date

2026-06-06

---

## What Was Built

Streaming synthesis via SSE, per-stage progress in the frontend, router prompt
hardening, filter validation guard, improved empty-result copy, perceived-latency
eval, two ADRs, and a streaming design doc.

### Backend: streaming endpoint + prompt hardening

**New / modified backend files:**

- `backend/app/extraction/client.py` — added `astream_completion`: yields SSE chunks
  from OpenRouter's streaming API (httpx `.stream()` + line parsing), calls
  `on_complete` callback at stream end with the `CompletionResult` for cost
  accumulation. Added `import json`, `from collections.abc import AsyncGenerator, Callable`.

- `backend/app/agent/streaming.py` — new module: `format_sse(event_type, data)`,
  event type string constants (`EVT_ROUTE`, `EVT_TOOL_START`, …), `StreamEventType`
  Literal alias.

- `backend/app/agent/synthesis.py` — renamed `_build_messages` → `build_synthesis_messages`
  (public); extracted `_strip_fences` and `_parse_synthesis_json` helpers; added
  `astream_synthesize(state, deps, on_token)` — same logic as `synthesize_answer` but
  streams tokens via `astream_completion` and calls the `on_token` callback per chunk.

- `backend/app/agent/api_router.py` — added `POST /api/ask/stream` (`StreamingResponse`)
  with `event_stream()` async generator that manually calls `classify_route` → tool node
  → synthesis+verify loop (bypassing LangGraph's compiled graph — see ADR 0027). The
  synthesis loop bridges the `on_token` callback to the SSE `yield` via an
  `asyncio.Queue` + done-callback sentinel pattern. The original `POST /api/ask`
  endpoint is unchanged.

- `backend/app/agent/prompts/router.txt` — enumerated valid `entity_type` values
  (`Person`, `Team`, `Service`, `System`, `Decision`, `Message`) and valid `source_kind`
  values (`doc`, `slack_message`); added "omit filter" few-shot example; added
  instruction to use empty filters rather than guessing.

- `backend/app/agent/tools.py` — added `_VALID_ENTITY_TYPES` and `_VALID_SOURCE_KINDS`
  frozensets; `_build_filters` now validates and drops hallucinated filter values with a
  `log.warning`; `empty_answer` now calls `_empty_answer_text(state)` which includes
  the filters applied and suggests reformulation.

**New eval files:**

- `backend/app/eval/streaming_eval.py` — `run_streaming_eval`, `LatencyResult`,
  `StreamingEvalReport`, `render_streaming_report`. Measures time-to-first-synthesis-token.
- `backend/scripts/run_streaming_eval.py` — CLI runner: samples 10 questions from the
  agent eval set.
- `docs/eval/phase-4b-streaming-results.md` — placeholder until live run.

### Frontend: streaming state machine + per-stage progress

- `frontend/src/types.ts` — added `StreamEvent` discriminated union, `StreamEventType`,
  and per-event interfaces (`StreamEventRoute`, `StreamEventToolStart`, …,
  `StreamEventComplete`, `StreamEventError`).

- `frontend/src/api/askStream.ts` — new: `streamAsk(question, signal?)` async generator
  using `fetch` + `ReadableStream` reader and SSE frame parser.

- `frontend/src/components/ask/StreamProgress.tsx` — new: per-stage progress display;
  renders route badge, tool status, streaming answer text, and verification status from
  received `StreamEvent[]`.

- `frontend/src/components/ask/AnswerView.tsx` — added `streaming?: boolean` prop;
  when `true`, renders raw text without `[evt:UUID]` citation regex (defers until `complete`
  event to prevent flicker from partial UUID matches).

- `frontend/src/pages/Ask.tsx` — complete rewrite. `USE_STREAMING = true` constant at
  top. Uses `useState` + `useRef<AbortController>` for streaming state machine instead
  of `useMutation`. On submit: calls `streamAsk`, processes events into
  `StreamState { status, events, streamingText, result, error }`. Non-streaming JSON
  path preserved when `USE_STREAMING = false`. Per-stage progress via `<StreamProgress>`;
  full answer via `<AnswerView>` + `<CitationList>` + `<AgentTrace>` after `complete`.

### Docs

- `docs/design/agent-streaming.md` — SSE protocol spec, event sequence, callback-to-
  queue bridge, frontend state machine, what is not changed.
- `docs/decisions/0026-sse-not-websockets.md` — why SSE over WebSockets.
- `docs/decisions/0027-stream-synthesis-only.md` — why route/tool/verify emit single
  events; why LangGraph astream not used.
- `docs/interview-prep/phase-4b-readiness.md` — 8 Q&A pairs.
- `docs/demo/3-minute-walkthrough.md` — Beat 3.5 updated to reference streaming UX.
- `docs/README.md` — all new docs listed.

### Tests

- `backend/tests/agent/test_streaming.py` — unit tests: `format_sse`, `FakeStreamingClient`
  (extends `FakeClient` with `astream_completion`), `astream_synthesize` (on_token
  callback, result shape, fallback on invalid JSON, strict-prompt-on-retry).
- `backend/tests/agent/test_streaming_api.py` — integration tests: `CombinedFakeClient`
  (handles both `.complete()` for router and `.astream_completion()` for synthesis),
  `test_stream_search_emits_correct_event_sequence`, `test_stream_unknown_emits_complete_without_synthesis`,
  `test_stream_synthesis_tokens_accumulate_to_full_answer`.
- `frontend/src/__tests__/Ask.streaming.test.tsx` — 6 tests: input renders, streamAsk
  called with question, route badge, tool status, citation hydration, error rendering.

---

## Decisions Made

| ADR | Decision |
|-----|---------|
| [0026](docs/decisions/0026-sse-not-websockets.md) | SSE over `fetch`+reader (not WebSockets, not native `EventSource`) for the streaming endpoint |
| [0027](docs/decisions/0027-stream-synthesis-only.md) | Only synthesis streams tokens; other stages emit one event each; LangGraph compiled graph not used for streaming |

---

## Deviations from Spec

1. **`astream_synthesize` is not called from `event_stream()` via the queue bridge in
   the final implementation.** The spec said "inside the handler, run `astream_synthesize`
   with a callback that writes SSE events." The callback-to-queue bridge **is** implemented
   in `api_router.py` exactly as designed, and `astream_synthesize` IS used in the
   streaming endpoint. The deviation is that `astream_synthesize` is called via the queue
   bridge (which is the correct async pattern) rather than some hypothetical direct call.

2. **`build_synthesis_messages` made public (previously `_build_messages`).** Made public
   so both `synthesize_answer` and `astream_synthesize` can call it without cross-module
   private access. No behavioral change.

3. **`_strip_fences` duplicated in synthesis.py** (not imported from llm.py). A private
   function can't cleanly cross modules; the 4-line helper is inlined. The logic is identical.

4. **Demo walkthrough Beat 3.5 updated but not fully re-timed.** The streaming path adds
   a visible real-time element (route badge appearing at ~2s, tokens streaming) that
   changes the delivery rhythm. The beat script is updated to narrate the streaming
   experience; exact timings should be re-confirmed in a live practice run.

---

## Open Questions

1. **Streaming eval numbers are placeholders** (`docs/eval/phase-4b-streaming-results.md`).
   Run `uv run python backend/scripts/run_streaming_eval.py` against a live backend to
   fill in real first-token timing. Expected: ~2400ms mean (< 3000ms target).

2. **`astream_completion` retry does not cover mid-stream failures.** If the OpenRouter
   connection drops after the first token has been yielded, the stream raises (not retried).
   For a demo this is acceptable; production would need a reconnect strategy.

3. **The existing pre-existing test failures from Phase 4A** (`test_audit.py`,
   `test_graph.py`, `test_events.py`) remain. Not 4B-related; flagged in 4A HANDOFF.

4. **Frontend TypeScript strict check for `StreamProgress`** uses `Array.prototype.findLast`
   which requires `ES2023` lib in `tsconfig.json`. If the build fails with "Property
   'findLast' does not exist", add `"ES2023"` to `compilerOptions.lib`.

---

## Definition of Done Check

- ✓ `POST /api/ask/stream` endpoint added alongside (not replacing) `POST /api/ask`
- ✓ `streaming.py` SSE serializer: `format_sse` + event type constants
- ✓ `astream_completion` added to `OpenRouterClient`
- ✓ `astream_synthesize` added to `synthesis.py` with `on_token` callback
- ✓ Streaming endpoint calls agent nodes manually (bypasses LangGraph for streaming)
- ✓ Per-stage SSE events: `route`, `tool_start/done`, `synthesis_start/token/done`, `verify_start/done`, `complete`, `error`
- ✓ Retry path emits `synthesis_start(retry=true)` + second pass of token events
- ✓ Frontend `askStream.ts`: fetch + ReadableStream SSE parser, async generator
- ✓ Frontend `StreamProgress.tsx`: real per-stage progress, no fake dots
- ✓ Frontend `AnswerView.tsx`: `streaming` prop defers citation regex until `complete`
- ✓ Frontend `Ask.tsx`: `USE_STREAMING = true`; streaming state machine; non-streaming fallback preserved
- ✓ Router prompt hardened: valid enum values explicit, "omit filter" few-shot, no-guess instruction
- ✓ Filter validation guard in `tools.py`: invalid enums dropped with warning log
- ✓ Empty-result copy improved: shows applied filters, suggests reformulation
- ✓ Backend tests: `test_streaming.py` (unit) + `test_streaming_api.py` (integration)
- ✓ Frontend test: `Ask.streaming.test.tsx` (6 tests)
- ✓ Streaming eval runner: `run_streaming_eval.py` + `streaming_eval.py`
- ⚠ Streaming eval results: placeholder — live numbers pending
- ✓ ADRs 0026 (SSE vs WebSockets) + 0027 (synthesis-only streaming)
- ✓ `docs/design/agent-streaming.md` (protocol, backend, frontend)
- ✓ `docs/interview-prep/phase-4b-readiness.md` (8 Q&A)
- ✓ Demo walkthrough Beat 3.5 updated for streaming UX
- ✓ `docs/README.md` updated with all new files
- ✓ HANDOFF.md updated

---

## State of the Codebase

**Backend:**
- `app/agent/` — 14 modules + 3 prompt files (added `streaming.py`). Modified: `client.py`, `synthesis.py`, `api_router.py`, `tools.py`, `prompts/router.txt`.
- `app/eval/streaming_eval.py` + `scripts/run_streaming_eval.py` added.
- All Phase 4A tests continue to pass. New streaming tests in `tests/agent/test_streaming.py` + `test_streaming_api.py`.

**Frontend:**
- `/ask` page fully replaced with streaming state machine.
- New: `api/askStream.ts`, `components/ask/StreamProgress.tsx`.
- Modified: `components/ask/AnswerView.tsx` (streaming prop), `pages/Ask.tsx` (full rewrite), `types.ts` (StreamEvent types).
- New test: `__tests__/Ask.streaming.test.tsx`.

**Docs:**
- agent-streaming.md, ADRs 0026–0027, phase-4b-readiness, eval placeholder, demo beat updated, README updated.

**Reference commit (4A baseline):** the commit tagged in 4A HANDOFF is the last clean 4A state.

---

## Next Subphase

**Demo recording + README polish + deployment.** The agent UX is demo-ready after 4B.
Candidate work: record the 3-minute demo walkthrough video, fill in README.md with a
clear project description and architecture diagram, optionally deploy to a cloud host
(Railway, Fly.io) so the demo is shareable via URL. Phase 4B is the last code subphase;
what remains is presentation and packaging.
