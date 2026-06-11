# ADR 0031 — Per-Event Incremental Reconciliation (not Full Rebuild)

## Status

Accepted

## Context

The read path is complete through Phase 4C, but the graph is still built by a **batch** pipeline
(`app.eval.query_eval`): wipe → seed → extract → embed → resolve → consolidate → project →
temporal → contradictions → query. The original plan's killer moment is injecting a *new* event
live and watching the graph reconcile in real time. A wipe-and-rebuild on every event is the
wrong shape for that: it is slow, it re-pays for the whole corpus's LLM calls, and it cannot run
inside a request handler the user is watching. We need each new event to touch only the nodes its
assertions affect, while still running the same stages in the same order.

The 5A pre-implementation check found the per-stage modules **scan globally** (no node-id scope):
`resolve_graph` is all-pairs-within-type, `enrich_temporal` walks all decisions, the contradiction
detector scans all recent messages × all active decisions. So "scoped reconciliation" is a design
question, not a free import.

## Decision

**Reconcile each event through the eight batch stages in the same order, but scope by *cost*, not
uniformly — hybrid scoping.** The cheap, idempotent, LLM-free stages (embed, consolidate, project,
temporal) call the existing batch functions unchanged (milliseconds at ≤14 nodes/type). The two
stages that cost money are truly scoped: **extraction** is skipped when a prior successful run
exists, and **resolution + contradiction** are scoped to the nodes the event introduced —
resolution to *newly-created fragments* (sole-provenance nodes), contradiction to the new
Message/Decision. Scope is derived from the graph by provenance, never from an in-memory result.

## Alternatives Considered

### Option A — Hybrid scoping (chosen)

**What it is**: scope only where adjudication cost demands it; reuse batch functions elsewhere.

**Pros**:
- Smallest change to locked 3A/3B code; the scoped resolver reuses `_decide_and_apply` verbatim,
  so a scoped pass and a batch pass make byte-identical decisions.
- Mean latency 5.8s, cost $0.0031/event (measured) — under target without touching the cheap stages.

**Cons**:
- Two scoping disciplines to explain (cost-scoped vs reuse-as-is).
- `scoped_temporal.py` / `scoped_resolution.py` are thin wrappers, which can look like ceremony.

### Option B — Strict per-node-id scoping everywhere

**What it is**: refactor `candidates.py` and every stage to accept an explicit node-id set.

**Pros**: one uniform scoping story; in principle the least redundant work.

**Cons**: invasive refactor of locked 3A code for ~no benefit at this scale; the cheap stages gain
nothing because they are already milliseconds and idempotent.

### Option C — Full wipe-and-rebuild per event

**What it is**: re-run `query_eval`'s pipeline on every ingest.

**Pros**: trivially correct; one code path.

**Cons**: seconds-to-minutes per event, re-pays the whole corpus's LLM cost, can't run live. This is
the anti-pattern the subphase exists to avoid.

## Consequences

**Enables**: a synchronous `POST /api/events` that reconciles in ~6s and returns a visible per-stage
result; the live-inject demo; replay (scope is provenance-derived, so re-processing is safe).

**Constrains**: the scoped resolver only resolves *new* fragments — a re-mentioned existing entity
is assumed already-resolved (true because the graph writer MERGEs on canonical key).

**Locked into**: deriving scope from `source_event_ids` provenance; the graph is the source of truth
for "what this event asserted," not an in-memory extraction result.

**At larger scale / in production**: resolution adjudication is still sequential (the 15s tail in the
eval); the next win is fanning it out like contradiction already does. Beyond that, a real stream
needs per-canonical-node locking (ADR 0033) and an ANN candidate index instead of all-pairs.

## Interview Defense

> "We reconcile each event through the same stages as the batch pipeline, but we only pay to scope
> the stages that cost money — extraction (skip on replay) and the two LLM adjudication stages
> (scoped to the new node). The cheap, idempotent stages just re-run; at ≤14 nodes per type that's
> milliseconds. Mean ingest is 5.8s. The trade-off is two scoping disciplines instead of one; at
> 10× scale we'd parallelise resolution adjudication and add per-node locking."
