# ADR 0025 — Provenance Verification Loop (Verify-Then-Retry, Max 2)

## Status

Accepted

## Context

The project's thesis is grounded answers: every claim traceable to a Postgres `events` UUID.
An LLM synthesiser, however well prompted, can still cite an id that is not in the tool's
provenance, or make a claim with no citation at all. For a provenance-first project, a
confidently-grounded-looking but fabricated citation is the single worst failure. We need a
mechanical guarantee, not a hopeful prompt.

## Decision

A pure-Python `verify_provenance` node checks every `[evt:UUID]` marker in the answer against
the tool's `available_event_ids`. On failure it routes back to `synthesize_answer` with a
**stricter prompt**, up to **2 retries**; if still failing it returns the best-effort answer
flagged `error="provenance_failed"`. `state["citations"]` is always reconciled to exactly the
inline markers.

## Alternatives Considered

### Option A — Trust the prompt (no verification)

**What it is**: instruct the model to cite, validate the Pydantic shape, return it.

**Pros**: simplest; one LLM call; lowest latency.

**Cons**: no guarantee — a fabricated id reaches the user looking authoritative. Unacceptable
for a provenance-first project.

### Option B — Verify once, fail hard

**What it is**: check citations; if any is fabricated, return an error immediately.

**Pros**: simple; bounded to one call; no fabrication reaches the user.

**Cons**: throws away recoverable answers — LLMs often fix a single bad citation when told
exactly which ids are legal. Wastes the good retrieval on a fixable formatting slip.

### Option C — Verify-then-retry, max 2 (chosen)

**What it is**: verify; on failure, re-synthesise with a strict prompt listing the legal ids;
cap retries at 2, then return flagged best-effort.

**Pros**:
- No fabricated citation reaches the user unflagged.
- Recovers the common case (one stray id) without a human in the loop.
- Bounded: at most three synthesis attempts; the cap prevents infinite loops and cost blowups.

**Cons**:
- Retries add latency and cost on the failure path (the eval shows 10–17 s and ~$0.005–0.007
  for retry cases).
- A persistent failure (eval q10) still costs three calls before giving up.

## Consequences

**Enables**: a hard anti-hallucination guarantee that the eval measures (verification rate =
0.864 first-try; 0 unflagged fabrications); self-healing of transient citation slips.

**Constrains**: the failure path is the slowest and most expensive; the cap means a genuinely
hard question (q10) burns three synthesis calls.

**Locked into**: retries = 2. Higher would raise cost/latency for diminishing recovery; lower
would drop recoverable answers. Two is the measured sweet spot for this corpus.

**At larger scale / in production**: the verifier is O(answer length) Python and scales freely.
At higher volume the lever is *reducing the candidate set* the synthesiser sees (fewer legal
ids → fewer off-by-one citations → fewer retries), and adding a semantic cache so repeat
questions skip synthesis entirely.

## Interview Defense

> "Synthesis is an LLM, so it can cite an event that isn't in the provenance. I don't trust the
> prompt — I verify in Python: extract every [evt:UUID], check it against the tool's provenance,
> and if anything's fabricated I re-synthesise with a stricter prompt that lists the legal ids,
> up to twice. The common case (one stray id) self-heals; a persistent failure returns flagged,
> never silently wrong. The cost is latency on the failure path; the cap at two keeps it
> bounded. On the eval, 86% verify first try and zero fabrications reached the user."
