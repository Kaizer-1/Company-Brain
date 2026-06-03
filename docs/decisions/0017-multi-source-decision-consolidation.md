# ADR 0017 — Multi-source Decision consolidation

## Status

Accepted

## Context

The same decision is often asserted by two sources — a decision-record doc and the Slack
thread that originated it. When both name the decision id (`D-0010`), extraction's `MERGE` on
`id` already collapses them. But a source that paraphrases without the id ("the JWT cutover
decision") produces a *second* Decision node. Phase 3A's resolver merges identity-bearing
entities (Person/Service, keyed on email/handle/slug) but deliberately skips Decisions, which
are content-bearing and have no stable surface key. Left unconsolidated, a duplicate Decision
splits KQ2's contradiction count and KQ4's timeline, and one copy can carry the wrong
`status`.

## Decision

Add `backend/app/resolution/consolidator.py`, run after entity resolution, that consolidates
un-merged Decision pairs using the **same `MERGE_INTO` + `status='merged'` + provenance-union
mechanism** as 3A. An exact `id` match auto-consolidates; otherwise we embed `title + body`
with the same local `bge-small` model and consolidate when cosine ≥ **0.85** *and* the
decisions are within 30 days of each other. The threshold is higher than the 0.75 entity floor
because the signal is content, not identity. Every attempt writes a `merge_decisions` row with
`node_type='Decision'` and a new enum value `content_merge` (Alembic `0003`).

## Alternatives Considered

### Option A — reuse the 3A entity resolver unchanged

**What it is**: run `resolve_graph` over `Decision` nodes with the existing rules.

**Pros**: zero new code.

**Cons**: the Tier-1 rules (email/handle/canonical-name) are meaningless for Decisions; the
0.75 floor is too loose for content and would false-merge distinct decisions about the same
subject (e.g. the four auth decisions all read alike). Wrong tool.

### Option B — content-similarity consolidator with a stricter threshold *(chosen)*

**What it is**: a Decision-specific pass: id-match Tier 1, else `title+body` embedding ≥ 0.85
with a temporal-proximity gate, reusing `MERGE_INTO`.

**Pros**: same audit trail and resolved-view semantics as 3A; the stricter threshold + temporal
gate protect against the "all auth decisions look similar" false-merge; provenance unions
correctly.

**Cons**: another threshold to justify; embedding `title+body` is coarser than a dedicated
decision encoder.

### Option C — defer; rely on extraction's id-`MERGE` only

**What it is**: trust that every source names the id.

**Pros**: nothing to build.

**Cons**: informal/paraphrased decisions fragment; KQ2/KQ4 silently under-count. Unacceptable
for the flagship queries.

## Consequences

**Enables**: one Decision node per real decision regardless of source mix; consistent
`merge_decisions` audit across entities and decisions.

**Constrains**: a new `content_merge` enum value is permanent (enum values cannot be dropped
cleanly in Postgres).

**Locked into**: the 0.85 content threshold as the demo's calibration point.

**At larger scale / in production**: blocking/ANN over decision embeddings instead of O(n²);
a learned threshold per decision-type; human review of `content_merge` rows before they apply.

## Interview Defense

> "Decisions don't have a stable key like a person's email, so we consolidate them on content
> similarity of title+body with a stricter 0.85 cosine and a 30-day proximity gate — strict
> because a false content-merge silently corrupts the timeline. We reused 3A's MERGE_INTO
> mechanism so the audit trail and the `status <> 'merged'` resolved view are identical across
> entities and decisions. At scale we'd block candidates and have a human approve content merges."
