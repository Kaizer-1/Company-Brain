# Phase 4B Streaming Eval — Perceived-Latency Results

> **Honest framing**: total end-to-end latency is unchanged from Phase 4A (two
> sequential LLM calls are the floor). What changes is *perceived* latency —
> the user sees the route badge and tool output before synthesis starts, then
> tokens stream in rather than the page sitting blank. This eval measures
> **time-to-first-synthesis-token** as the UX-relevant metric.

> **Note**: This document contains placeholder results. Run
> `uv run python backend/scripts/run_streaming_eval.py` against a live backend
> to populate real numbers.

## Summary

| Metric | Value |
|--------|-------|
| Questions | 10 (sample from 30-question agent eval set) |
| Mean time-to-first-token (ms) | *pending live run* |
| P50 time-to-first-token (ms) | *pending live run* |
| Mean total time (ms) | *pending live run* |

**Target**: mean time-to-first-token ≤ 3000ms.

## Expected Results (design estimate)

Based on Phase 4A timing data (mean total 6645ms, route ~2s, tool ~0.3–0.5s):

- **Time-to-first-token** = route classification (~2000ms) + tool execution (~400ms) ≈ **~2400ms**
- This is below the 3000ms target for KQ and search routes.
- `unknown` route has no synthesis; first-token time is reported as `—`.
- **Total time** unchanged: route (~2s) + tool (~0.4s) + synthesis (~3.5s) + verify (~0.3s) ≈ 6.2s.

## Discussion

Total latency is the sum of route classification + tool execution + synthesis + verification —
unchanged by streaming. The UX improvement is that the user sees the route badge appear ~2s
into the request, then token output begins streaming, rather than a blank screen for the full
duration.

The **perceived wait** reduces from ~6.6s (blank → complete) to ~2.4s (blank → first token),
which is the target. Remaining total time is amortised by the streaming text appearing
progressively.

First-token time = route + tool stages, which is typically 2–3s for KQ routes (Cypher is
fast) and ~2.5s for search (vector query + embedding). Unknown routes never reach synthesis
so have no first-token time.
