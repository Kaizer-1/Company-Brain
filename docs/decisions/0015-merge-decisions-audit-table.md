# ADR 0015 — Every merge decision recorded in a Postgres `merge_decisions` audit table

## Status

Accepted

## Context

The tiered resolver (ADR 0014) makes a same/different decision for every candidate pair it
considers. Entity resolution is the algorithmic centrepiece of the project, and its
interview-defensibility hinges on being able to answer, for any two nodes, "show me exactly
how you decided these were the same person" — including the cases where it decided *not* to
merge, and the cases it rejected before spending an LLM call. Without a durable record, that
answer is gone the moment the run ends: the `MERGE_INTO` edge records *that* a merge happened
and at what tier, but not the rejected pairs, the rules that fired, the embedding similarity,
or the LLM's reasoning. We need a persistent, queryable audit log of every resolution
*attempt*, not just the successful merges.

## Decision

Record **every resolution attempt** — `auto_merge`, `llm_merge`, `llm_no_merge`, and
`below_threshold` — as a row in a new Postgres table `merge_decisions`, with full provenance:
the two node ids, node type, decision, tier, embedding similarity, the list of rules matched,
and (for Tier 2) the LLM's reasoning and model id. The table is indexed on
`(node_type, created_at)` for time-windowed audit queries.

## Schema

```
merge_decisions(
    id                   UUID PK
    source_node_id       str            -- the node being absorbed (loser), or left node of a no-merge pair
    target_node_id       str            -- the canonical winner, or right node of a no-merge pair
    node_type            enum(Person, Service, System, Team, Decision)
    decision             enum(auto_merge, llm_merge, llm_no_merge, below_threshold)
    tier                 int            -- 1, 2, or 3
    embedding_similarity float | None
    rules_matched        list[str]      -- e.g. ["exact_email", "known_alias"]
    llm_reasoning        text  | None   -- haiku's explanation, Tier 2 only
    llm_model            str   | None   -- e.g. "anthropic/claude-3.5-haiku"
    created_at           timestamptz
)
-- index ix_merge_decisions_type_created on (node_type, created_at)
```

## Why Postgres, not a Neo4j relationship

A rejected pair (`llm_no_merge`, `below_threshold`) has **no edge to attach to** — there is no
merge, so there is nothing in the graph to carry the record. Modelling rejections as graph
edges would pollute the graph with non-structural bookkeeping and distort traversals. The
decision log is tabular, append-only, time-series audit data with heterogeneous nullable
columns (LLM fields only for Tier 2) — exactly what a relational store is for, and exactly the
role Postgres already plays in this project as the immutable event/provenance backbone
(alongside `events` and `extraction_runs`). The `MERGE_INTO` edge stays in Neo4j for the
*structural* fact of a merge; the *reasoning and the rejections* live in Postgres. The two are
complementary, not redundant.

## Alternatives Considered

### Option A — Only record successful merges, on the `MERGE_INTO` edge

**Pros**: no new table; the structural record already exists.

**Cons**: cannot answer "why did you *not* merge these two?" — losing exactly the cases an
interviewer probes and a human reviewer most needs. No record of below-threshold rejects at
all.

### Option B — Postgres `merge_decisions` table for every attempt *(chosen)*

**Pros**: complete audit (merges *and* rejections); supports time-windowed queries; reuses the
existing relational provenance store; is the natural backing table for a future human-review
UI.

**Cons**: a second write per decision (graph edge + Postgres row) on merges; one more table to
migrate and maintain.

## Consequences

**Enables**: the demo/interview answer ("here is the row that decided this merge, with the
rules and the LLM reasoning"); the eval's tier breakdown (counts and mean confidence per tier
come straight from these rows); and a ready-made queue for the Phase 6 human-review UI — a
reviewer pages through `llm_merge`/`llm_no_merge` rows ordered by confidence.

**Constrains**: resolution now writes to both stores; the resolver needs a Postgres session
alongside the Neo4j driver. Decisions are append-only — re-running resolution appends new
rows rather than mutating old ones (intended: the log is history).

**Locked into**: the four-value `decision` enum and the tier/rules/similarity columns; the
eval and any review UI read this shape.

**At larger scale / in production**: the table grows by O(candidate pairs) per run, so we would
add retention/partitioning by `created_at` and likely sample `below_threshold` rows rather than
storing every rejected pair at million-node scale.

## Interview Defense

> "Every resolution attempt — including the ones we rejected and the ones we never sent to the
> LLM — writes a `merge_decisions` row with the tier, the rules that fired, the embedding
> similarity, and the LLM's reasoning. So when you ask 'why did these two merge, and why did
> *those* two not?', I produce the row. It lives in Postgres, not Neo4j, because a non-merge
> has no edge to hang on and because it's append-only time-series audit data — the same role
> Postgres already plays as our provenance backbone. It's also the seed for a human-review UI:
> a reviewer just pages through the Tier-2 rows by confidence."
