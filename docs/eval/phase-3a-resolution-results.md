# Phase 3A — Entity-Resolution Eval Results

_Generated: 2026-06-02_

Fragmented graph seeded from `ALIAS_GROUPS` + `LOOK_ALIKE_PAIRS`: **25 nodes**. Ground truth is `narrative.py` (ADR 0013). Metrics are over unordered node pairs.

## Headline metrics

| Scope | Precision | Recall | F1 | False-merge | Missed-merge | TP | FP | FN |
|-------|-----------|--------|----|-------------|--------------|----|----|----|
| **Overall** | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 33 | 0 | 0 |
| Person | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 18 | 0 | 0 |
| Service | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 15 | 0 | 0 |

## Tier breakdown

| Tier | Merges | Mean confidence |
|------|--------|-----------------|
| 1 | 33 | 0.99 |

Decision counts (all attempts): `auto_merge`=33, `llm_merge`=0, `llm_no_merge`=5, `below_threshold`=106.

LLM (Tier 2) cost this run: **$0.0031** (sentence-transformers embeddings are free).

## Correct merges (examples)

- `diego` ⇄ `the-payments-lead`
- `diego` ⇄ `diego-ramirez`
- `payments-tech-lead` ⇄ `the-payments-lead`

## False merges (examples)

**Zero false merges.** No pair was merged that ground truth says is distinct.

## Missed merges (examples + diagnosis)

**Zero missed merges.** Every true alias pair was recovered.

## Discussion

**Headline read.** On the seeded fragmentation of `ALIAS_GROUPS` (25 nodes — six alias
groups plus the look-alike pair), the resolver recovers all 33 true merge-pairs with zero
false merges: precision, recall, and F1 are 1.00, and both the false-merge and missed-merge
rates are 0.00. Every merge happened at **Tier 1** (33 auto-merges, mean confidence 0.99);
**no merge required the LLM.** Tier 2 still ran on five pairs — cross-group and look-alike
pairs whose names embed above the 0.75 floor but carry no identity rule — and the adjudicator
correctly declined every one (`llm_no_merge`=5), at a total cost of **$0.0031**. The remaining
106 pairs fell below the similarity floor and were dismissed for free. The single metric I care
about most, the false-merge rate, is zero — including the deliberately-confusing
`notifications-api` / `notification-worker` look-alike, which has no alias-dictionary entry, so
no Tier 1 rule fires and it routes to Tier 2 where haiku keeps the two services apart on the
strength of their distinct descriptions.

**Which types resolve best, and why.** Person and Service are tied at 1.00/1.00 here because
both are fully covered by the curated alias dictionary: every Alice/Diego/Ben surface form and
every `auth-service`/`AuthSvc`/`legacy-billing` form normalises to a known canonical, so the
`known_alias` rule fires on every within-group pair regardless of how far apart the embeddings
sit ("Al" vs "Alice Chen" is a low-cosine pair that Tier 1 still merges). That is exactly the
design intent — exact-identity rules are authoritative over a 384-dim sentence embedding.

**The honest caveat.** This 1.00 is flattered by the fact that the `known_alias` dictionary is
built from the same `ALIAS_GROUPS` that defines ground truth. So what this eval really proves
is that the *machinery* is correct end-to-end — candidate generation, the tiered routing, the
non-destructive `MERGE_INTO` writer, provenance accumulation, the audit trail, and the LLM
tier's ability to reject look-alikes — not that the system discovers aliases it was never told
about. The recall that would generalise lives in Tiers 2 and 3, and the look-alike rejection is
the one genuinely adversarial signal here that the dictionary cannot trivially pass.

**A messier, complementary datapoint.** Run against the *real extracted graph* (gemini-2.5-flash-lite
over the full corpus: 234 nodes, 117 edges), `resolve_entities` made 39 merges across all five
types from 627 candidate pairs — 28 Tier 1 auto-merges, 11 Tier 2 LLM merges, 32 Tier 2
no-merges, 556 below-threshold — tombstoning 23 nodes for $0.03. That run is not scored here
(its ground truth would need the extractor's noisy output labelled), but it confirms the
resolver operates at realistic scale and that Tier 2 carries real weight once the dictionary
stops covering everything: 11 of 39 merges came from the LLM.

**Where it fails / what would close the gap.** The failure mode this eval cannot show is a
*missed* alias the dictionary does not know — a novel nickname or a misspelling whose embedding
sits below 0.75. To close that I would lower the adjudication floor (trading LLM spend for
recall), enrich the per-type embedding input with more node properties so true aliases cluster
tighter, and add phonetic/n-gram blocking so near-miss spellings still become candidates. To
harden precision in a noisier setting I would route a sample of Tier 1 auto-merges through the
`merge_decisions` review queue and require two corroborating signals before auto-merging on a
single dictionary hit.

