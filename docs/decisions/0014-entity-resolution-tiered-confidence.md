# ADR 0014 — Tiered-confidence entity resolution with non-destructive merges

## Status

Accepted

## Context

The Phase 2B write path is best-effort on identity (Phase 1B locked this: "the v1 write path
is best-effort and may create duplicate nodes the schema is designed to later merge"). The
resulting graph fragments one real entity into several nodes — `@alice`, `Alice Chen`,
`alice.chen@northwind.io`, and `Al` become up to four Person nodes — and every killer query
breaks when traversal lands on a fragment that holds only part of the edges and provenance.
We need a resolver that decides when two nodes are the same entity and merges them. The
governing constraint is asymmetric risk: a **wrong merge fabricates a connection and corrupts
downstream queries (KQ3 blast radius especially), and is hard to detect**, whereas a missed
merge merely leaves two correct-but-partial nodes. So the design must drive the false-merge
rate toward zero first, recall second. A second constraint is cost: resolution embeds every
node on every run, so we cannot pay an API per embedding.

## Decision

Resolve each candidate pair through **three tiers of increasing cost and decreasing
certainty** — Tier 1 deterministic auto-merge, Tier 2 LLM (`anthropic/claude-3.5-haiku`)
adjudication, Tier 3 no-merge — using **local `sentence-transformers` (`BAAI/bge-small-en-v1.5`)**
embeddings for similarity, and record every merge as a reversible
`(loser)-[:MERGE_INTO {confidence, tier, created_at}]->(winner)` edge with
`loser.status = "merged"` rather than deleting anything.

## Alternatives Considered

### Option A — Single cosine-similarity threshold

**What it is**: embed every node, merge any pair above one fixed cosine threshold.

**Pros**:
- Trivial to implement; one number to tune.
- No LLM cost.

**Cons**:
- Cosine has no notion of *identity*. Two distinct critical services (`notifications-api` /
  `notification-worker`) sit above almost any threshold and would be wrongly merged; a
  nickname (`Al` vs `Alice Chen`) sits below it and would be missed. No single threshold
  separates "same entity" from "similar string."
- Gives no explanation for a decision — un-auditable.

### Option B — LLM adjudicates every pair

**What it is**: send all candidate pairs to an LLM and trust its same/different verdict.

**Pros**:
- Highest ceiling on nuanced judgement.

**Cons**:
- O(n²) LLM calls — expensive and slow even at demo scale, absurd at production scale.
- Pays full price for pairs a one-line rule (`exact_email`) decides with certainty.
- Non-determinism on the easy cases that should be deterministic.

### Option C — Three-tier confidence model *(chosen)*

**What it is**: deterministic exact-identity rules auto-merge (Tier 1); only the genuinely
ambiguous band (close embeddings, no decisive rule — or a rule contradicted by similarity)
goes to the LLM (Tier 2); everything below the similarity floor is left alone (Tier 3).

**Pros**:
- Decisions are explainable per tier: "merged because exact email matched," "merged because
  haiku judged the snippets describe the same service," "not merged — below threshold."
- Cheap: the LLM only sees the hard pairs; auto-merges and clear non-merges cost nothing.
- Tunable safety: the auto-merge gate is anchored on a *deterministic rule*, not raw cosine,
  which is what keeps the false-merge rate near zero.

**Cons**:
- More moving parts than a single threshold (rules + embeddings + LLM + orchestration).
- Two thresholds (0.95 intuition / 0.75 adjudication floor) to justify and tune.

## Why these specific choices

- **`MERGE_INTO` over deletion.** Merging by adding an edge and tombstoning the loser
  (`status = "merged"`) is reversible (delete the edge, reset status), provenance-preserving
  (the loser's `source_event_ids` union onto the winner), and demo-friendly (a one-line
  `WHERE n.status <> "merged"` toggles the fragmented vs resolved view). Deletion would
  destroy information and make a wrong merge unrecoverable — unacceptable given the asymmetric
  risk above.
- **Local sentence-transformers over a hosted embedding API.** Resolution embeds every node
  every run; a local model makes that free and byte-deterministic (reproducible eval numbers),
  at the cost of ~300 MB of PyTorch-CPU in the image. The only money we spend is Tier 2, and
  only on ambiguous pairs. This is the cost-honest production answer.
- **`claude-3.5-haiku` for adjudication.** Cheap, fast, and the strongest of the three Phase
  2B models on this corpus's relational judgement (entity/relation F1 0.91/0.78). The
  adjudicator falls back to "no merge" on any parse failure — the safe default.

## Consequences

**Enables**: an auditable, mostly-free resolver whose every decision carries a tier and a
reason; a reversible resolved view over the same graph; the eval to report false-merge and
missed-merge rates per type against `ALIAS_GROUPS`.

**Constrains**: the auto-merge tier is only as trustworthy as its deterministic rules — in
particular the curated `known_alias` dictionary (see ADR 0015 and the design doc's honest
limitations). Tier 2 introduces non-determinism on the ambiguous band.

**Locked into**: the `MERGE_INTO` edge + `status = "merged"` convention (queries across the
project now assume it), the three-tier routing, and the two thresholds.

**At larger scale / in production**: O(n²) candidate generation must become blocking +
ANN-index lookup (named in the design doc); the `known_alias` dictionary would be sourced from
a real SSO/HR/service-catalog rather than the synthetic narrative; and resolution would move
into the write path (Phase 4) for incremental, at-ingest resolution.

## Interview Defense

> "We route every candidate pair through three tiers: a deterministic rule auto-merges the
> certain cases for free, a cheap LLM adjudicates only the genuinely ambiguous ones, and
> everything below a similarity floor is left alone. We anchor auto-merge on an exact-identity
> rule rather than raw cosine, because cosine measures string similarity, not identity — two
> different critical services can look 0.96 similar. The trade-off is more moving parts than a
> single threshold, and a `known_alias` rule that's only as good as its dictionary — which in
> production is your HR/SSO directory, not synthetic data. Merges are reversible edges, never
> deletions, because a wrong merge corrupts blast-radius queries and must be undoable."
