# ADR 0035 — Parallel Tier-2 Resolution Adjudication

## Status

Accepted

## Context

The scoped resolver (Phase 5A) adjudicated every Tier-2 candidate pair sequentially: for a node with
N look-alikes above the similarity floor, that is N back-to-back LLM calls. Phase 5A's eval named a
~15 s tail on `doc-new-person` and *hypothesised* it was this sequential adjudication. The
contradiction detector already fans its adjudications out concurrently (semaphore of 5); resolution
did not, deliberately, to keep the scoped resolver a faithful reuse of the locked 3A
`_decide_and_apply`. Phase 5B builds the metrics to *measure* the hypothesis, then acts on it.

**The measurement corrected the hypothesis.** Per-stage metrics and a controlled semaphore A/B
(concurrency 1 vs 5, warm model) showed `doc-new-person`'s warm resolve stage is ~100 ms and triggers
**zero** Tier-2 calls — its 16 candidates all fall below the 0.75 floor. The 15 s was the embedding
model's **cold-start** on the first eval case, not adjudication. So the optimisation's real-world
benefit on that specific case is negligible — but adjudication *does* serialise wherever fan-out is
genuinely high, and that is worth fixing correctly.

## Decision

**Parallelise Tier-2 adjudication in the scoped resolver with a `Semaphore(5)`, Tier-1 first.**
`_resolve_targets_against` runs in three passes: (1) serial — apply Tier-1 auto-merges and Tier-3
below-floor rows, collecting the surviving Tier-2 pairs; (2) parallel — adjudicate those pairs under
the semaphore via `asyncio.gather`; (3) serial — apply each verdict. Writes stay serial; only the
network-bound LLM call fans out. The batch `resolve_graph` is left sequential so eval-time behaviour
stays comparable across phases.

**Measured effect (controlled A/B, same warm event, only the semaphore changes):**

| Condition | Tier-2 calls | Resolve (sequential, sem=1) | Resolve (parallel, sem=5) | Speedup |
|---|---|---|---|---|
| Natural floor (0.75) | 0 | 109 ms | 82 ms | — (no fan-out) |
| Forced fan-out (floor 0.0) | 16 | 45 742 ms | 11 332 ms | **4.0×** |

The 4.0× matches the bound exactly: 16 calls at concurrency 5 is `ceil(16/5) = 4` batches, and
45.7 s / 4 ≈ 11.4 s.

## Alternatives Considered

### Option A — Semaphore-bounded `gather`, Tier-1 first, serial writes (chosen)

**What it is**: fan out only the Tier-2 LLM calls, capped at 5; apply Tier-1 before Tier-2 so a
folded target's pairs are skipped; apply all writes serially.

**Pros**: collapses the adjudication tail to the slowest batch; reuses the proven contradiction
pattern (defensible: "same bound, same reason"); safe — the shared Postgres session never sees
concurrent use; avoids wasted LLM calls on already-merged targets.

**Cons**: a thin restructure of the inner loop (decide/apply had to be split); the win is invisible
on this corpus because per-event fan-out is small.

### Option B — Unbounded `gather` over all Tier-2 pairs

**What it is**: fire every Tier-2 adjudication at once, no semaphore.

**Pros**: lowest latency in principle (one batch).

**Cons**: an N-look-alike node fires N simultaneous OpenRouter calls — straight into rate limits and
429s; no backpressure; the failure mode is worse than the latency it saves. Rejected.

### Option C — Per-task DB sessions instead of serialised writes

**What it is**: give each concurrent adjudication its own Postgres session so writes can also run
concurrently.

**Pros**: fully concurrent decide-and-write.

**Cons**: the merge writes are a read-modify-write on shared canonical nodes (provenance union,
tombstoning) that concurrency would race — the single-writer rationale (ADR 0033) applies *within* a
resolution pass too. Serialising the cheap writes and parallelising only the expensive LLM call is
both simpler and safer. Rejected.

## Consequences

**Enables**: a 4× faster resolve stage wherever a node has many look-alikes above the floor; the
same concurrency story as contradiction, so the two cost-bearing stages now behave alike.

**Constrains**: only the *scoped* (ingestion) resolver is parallel; the batch resolver stays
sequential by design. The Tier-1-first ordering is load-bearing — a target merged in pass 1 must be
excluded from pass 2, or a folded fragment could be double-adjudicated.

**Locked into**: `Semaphore(5)` (matched to contradiction and the OpenRouter rate budget); serial
writes through the single shared session.

**At larger scale / in production**: the bound becomes a function of the provider's rate limit and
candidate-generation moves to an ANN index (already named in the entity-resolution design), so a node
is paired against its few nearest neighbours rather than all-pairs-within-type — which also keeps
Tier-2 fan-out naturally small.

## Interview Defense

> "I parallelised the Tier-2 LLM adjudications with a semaphore of 5 — the same bound the
> contradiction detector uses, sized to the OpenRouter rate limit. The interesting part is *how I got
> there*: I built the metrics first, and they showed the 15-second case I was about to optimise was
> actually the embedding model's cold-start, not the adjudication — that case makes zero LLM calls.
> So I shipped the parallelisation as a correct, bounded improvement and proved it under a controlled
> high-fan-out experiment: 16 sequential adjudications were 45.7 s, parallel 11.3 s — a clean 4×,
> exactly the four batches the semaphore implies. Writes stay serial because they share one Postgres
> session and the merge is a read-modify-write; only the network call fans out. Measure first, then
> optimise — and be honest when the measurement says the thing you assumed was wrong."
