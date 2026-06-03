# Phase 3B — Killer-Query Integration Eval

_Generated: 2026-06-03_

Full pipeline: seed → extract (anthropic/claude-3.5-haiku) → resolve → consolidate → project → temporal → messages+contradictions → query. Expected answers from `narrative.py` (ADR 0013); no partial credit. **111 events.**

## Result: ✅ ALL PASS

| KQ | Question | Pass | Expected | Actual | Provenance |
|----|----------|------|----------|--------|------------|
| KQ1 | Who owns the service depending on the system deprecated by D-0006? | ✅ | owner=diego-ramirez, chain≈4 hops | owners=['diego-ramirez', 'hassan-mehta'], max_hops=4 | valid |
| KQ2 | Which active decisions are contradicted by discussions in the last 30 days? | ✅ | ≥1 contradiction incl. D-0005 | contradicted decisions=['D-0005'] | valid |
| KQ3 | If payments-api fails, which services/people/decisions are affected? | ✅ | ≥10 services incl. web-storefront | 10 services, depth=2, people=4, decisions=1 | valid |
| KQ4 | What changed about auth-service in the last quarter, and who approved each? | ✅ | ⊇ ['D-0006', 'D-0007', 'D-0008', 'D-0010'], each with approvers | decisions=['D-0006', 'D-0007', 'D-0008', 'D-0010'] | valid |

## Cost & runtime

- Resolution (Tier-2 adjudication) cost: **$0.0270**
- Contradiction detection cost: **$0.0097**
- (Extraction cost is logged per call by the OpenRouter client; see run logs.)
- Total runtime: **272.5s**

## Discussion

**Headline: all four killer queries return the correct answer on the live, LLM-extracted graph,
with valid provenance for every answer.** This is the integration gate — the full chain (seed →
extract with `claude-3.5-haiku` over 111 events → resolve 519 candidate pairs into 25 merges →
consolidate decisions → project edges onto canonical winners → enrich temporal → ingest 89
messages + detect contradictions → query) — and it passes end to end in ~4.5 minutes for under
$0.04 of adjudication (extraction is the bulk of the cost, logged per call).

**What the first run caught.** The first live run failed KQ2 (0 contradictions) while KQ1/KQ3/KQ4
passed — exactly the value of an end-to-end eval over per-layer tests. The cause was an *ordering*
bug invisible to unit tests: contradiction detection ran before temporal enrichment, so it filtered
candidate decisions on raw extraction statuses. The extractor had not emitted a clean
`status='active'` for D-0005, so it was excluded from the active set and its three contradicting
messages never became candidates (19 candidates instead of 23). Re-ordering temporal enrichment
ahead of detection — so the detector sees normalised statuses — fixed it: 23 candidates, 3
`CONTRADICTS` edges written, KQ2 green. No unit test would have found this; the layers were each
correct, the seam between them was not.

**Which queries are most reliable.** KQ1, KQ3, KQ4 are robust because they traverse structural
edges asserted in authoritative documents with canonical names, which `haiku` extracts at ~0.9
entity F1. KQ1 returned `diego-ramirez` (and `hassan-mehta`, a legitimate second platform owner)
via a 4-hop chain; KQ3 found the full 10-service blast radius at depth 2; KQ4 recovered all four
auth decisions newest-first with approvers and the D-0010→D-0004 supersession. The edge-projection
cleanup is load-bearing here — 25 resolution merges left structural edges on tombstoned losers, and
projection (4 edges this run) is what keeps KQ1's owner hop reachable.

**Which depends most on extraction quality.** KQ2 is the fragile one: it is two LLM-mediated steps
(extraction of the decision, then contradiction adjudication) on top of message ingestion, and it
depends on temporal enrichment having normalised the decision's status first. Even with everything
correct, the adjudicator must judge three messages against D-0005 — it did, at confidence 0.9.
Decision consolidation found 0 merges, which is correct: extraction's id-keying already collapses
the multi-source decisions, so there is nothing left to content-merge, and the distinct-formal-id
guard ensured the four similar auth decisions were never wrongly fused (which would have broken
KQ4).

**Partial-failure posture.** One extraction call failed to parse (an unterminated JSON string) and
was logged and skipped, not retried — the corpus's structural redundancy (every KQ-critical edge
asserted in ≥1 doc and reinforced in Slack) absorbed it, and all four answers were still complete.
Provenance validation is the second net: every answer's event IDs resolved to Postgres rows, so no
KQ passed on an ungrounded answer. The remaining honest gap is a *wrong* extracted edge that
completes a chain — a precision concern deferred to a confidence-floor pass in a later phase.

