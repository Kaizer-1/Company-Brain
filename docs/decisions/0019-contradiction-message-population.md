# ADR 0019 — Contradiction + Message population pass (KQ2 data path)

## Status

Accepted

## Context

KQ2 ("active decisions contradicted by recent discussions") traverses
`Message -[:CONTRADICTS]-> Decision`. But the Phase-2B extraction prompt emits only 6 of the 9
edge types — it never produces `CONTRADICTS` (nor `AUTHORED`/`MENTIONS`), and **no component
creates `Message` nodes** (the eval docs note Messages are "created mechanically from events,
not extracted", but nothing actually did so). So KQ2 has no data at all. graph-schema.md open
question #1 explicitly anticipated this: "How is `CONTRADICTS` populated? ... a dedicated
contradiction-detection pass (Phase 3B)?" This ADR resolves it.

## Decision

Add `backend/app/contradiction/`: a `message_ingest.py` that mechanically `MERGE`s one
`:Message` node per `slack_message` event (idempotent on `id = "slack:<external_id>"`), and a
`detector.py` that generates candidate (Message, Decision) pairs — recent messages (within the
contradiction window of `as_of`) that name a decision id or the subject the decision is
`ABOUT`/`DEPRECATES` — and adjudicates each with the existing `OpenRouterClient`
(claude-3.5-haiku, the 3A adjudicator), writing `CONTRADICTS {confidence, extracted_by,
source_event_id}` on a positive verdict. With no client configured the pass is a conservative
no-op, exactly like the 3A resolver.

## Alternatives Considered

### Option A — dedicated 3B detection pass *(chosen)*

**Pros**: matches the schema's documented intent; reuses the resolver's adjudicator pattern and
client; keeps extraction (LOCKED IN) untouched; on-demand like extraction/resolution.

**Cons**: another module + another LLM cost line; candidate gen is gated to corpus decision
subjects (not open-world).

### Option B — extend the Phase-2B extraction prompt

**What it is**: add `CONTRADICTS`/`AUTHORED`/`MENTIONS` to the prompt and create Message nodes
in `graph_writer`.

**Pros**: one pipeline; contradictions extracted inline.

**Cons**: touches the LOCKED-IN extraction components and invalidates the published
phase-2b-results.md F1 baseline (requires re-running the 3-model eval); contradiction is a
*cross-document* judgement an inline single-event extractor cannot make well. Rejected.

### Option C — query-time text comparison

**What it is**: compare message text to decision text at KQ2 time.

**Pros**: no materialised edge.

**Cons**: O(messages × decisions) per query; the schema explicitly chose `CONTRADICTS` as a
materialised edge to make KQ2 a cheap filter-and-traverse (graph-schema.md). Rejected.

## Consequences

**Enables**: KQ2 end-to-end against the live pipeline; `Message` nodes available for future
`AUTHORED`/`MENTIONS` population.

**Constrains**: contradiction recall depends on the adjudicator and on candidate-gen coverage;
documented as corpus-scoped, not general.

**Locked into**: `CONTRADICTS` as a materialised, LLM-adjudicated edge.

**At larger scale / in production**: blocking/embeddings to bound candidate pairs; a confidence
floor + human review before an edge writes; periodic re-detection as new messages arrive.

## Interview Defense

> "KQ2 needs CONTRADICTS edges and Message nodes that extraction never produced — the schema
> always flagged this as a Phase-3B detection job. We built a dedicated pass that ingests Slack
> events as Message nodes and LLM-adjudicates whether a recent message contradicts a decision it
> references, reusing the resolver's adjudicator. We chose this over extending extraction because
> contradiction is a cross-document judgement and we didn't want to disturb the locked extraction
> baseline."
