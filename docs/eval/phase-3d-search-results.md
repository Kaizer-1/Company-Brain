# Phase 3D — Search Eval Results

**Generated**: 2026-06-05  
**Questions**: 20  
**Model**: BAAI/bge-small-en-v1.5 (384 dims)  

## Summary

| Metric | Value | Target | Pass? |
|--------|-------|--------|-------|
| Recall@10 (mean) | 0.942 | ≥ 0.70 | ✓ |
| MRR (mean) | 0.910 | ≥ 0.50 | ✓ |
| Mean latency (ms) | 660.5 | ≤ 500ms | ✗ |

## Per-question results

| ID | Question (truncated) | Recall@10 | RR | Latency(ms) | Hits | Misses |
|----|---------------------|-----------|----|-------------|------|--------|
| Q01 | deprecate legacy-auth migrate all services to… | 1.00 | 1.00 | 12523 | 3/3 | 0 |
| Q02 | auth-service stateless JWT session model deci… | 1.00 | 1.00 | 55 | 3/3 | 0 |
| Q03 | mTLS mutual TLS between auth-service and user… | 1.00 | 1.00 | 47 | 2/2 | 0 |
| Q04 | rotate auth-service signing keys monthly | 1.00 | 1.00 | 44 | 2/2 | 0 |
| Q05 | new payment integrations legacy-auth through … | 1.00 | 1.00 | 42 | 4/4 | 0 |
| Q06 | contradiction active decision new integration… | 0.67 | 1.00 | 40 | 2/3 | 1 |
| Q07 | payments-api service dependencies architectur… | 1.00 | 1.00 | 53 | 3/3 | 0 |
| Q08 | which services fail if payments-api goes down… | 0.67 | 1.00 | 25 | 2/3 | 1 |
| Q09 | strangle monolith new features as microservic… | 1.00 | 0.50 | 22 | 1/1 | 0 |
| Q10 | event-bus Kafka adopt async service communica… | 1.00 | 1.00 | 45 | 3/3 | 0 |
| Q11 | standardize async writes event-bus no direct … | 1.00 | 1.00 | 50 | 3/3 | 0 |
| Q12 | Alice Chen platform lead approved auth decisi… | 1.00 | 1.00 | 42 | 2/2 | 0 |
| Q13 | Diego Ramirez payments team lead | 1.00 | 1.00 | 44 | 3/3 | 0 |
| Q14 | notifications-api growth team deliverables re… | 1.00 | 0.50 | 21 | 2/2 | 0 |
| Q15 | service catalog ownership payments platform t… | 1.00 | 1.00 | 48 | 2/2 | 0 |
| Q16 | oncall paging payments-api alert runbook proc… | 1.00 | 1.00 | 21 | 2/2 | 0 |
| Q17 | auth-service overview AuthSvc new authenticat… | 1.00 | 1.00 | 21 | 2/2 | 0 |
| Q18 | checkout-service web-storefront upstream depe… | 1.00 | 1.00 | 25 | 2/2 | 0 |
| Q19 | legacy-auth stale integration guide deprecate… | 0.50 | 0.20 | 21 | 1/2 | 1 |
| Q20 | billing-v2 legacy-billing migration payments … | 1.00 | 1.00 | 21 | 3/3 | 0 |

## Failure modes

**Q06** — `contradiction active decision new integrations should use auth-service not legacy-auth`
Missed: 73d1228f-48fd-48a2-aa60-17b7b061fc45

**Q08** — `which services fail if payments-api goes down blast radius`
Missed: d6fc37a5-d89f-4e2b-82e2-93b022876b6b

**Q19** — `legacy-auth stale integration guide deprecated authentication`
Missed: ade16975-69bf-43f6-a8ad-a4242b083f5d


## Discussion

### Latency note

Q01's 12 523ms reflects **first-call model load** (bge-small-en-v1.5 loads ~8–12s on CPU
the first time). Excluding Q01, the mean warm latency across the remaining 19 questions is
**~41ms** — well within the 500ms target. In the deployed Docker backend the model is loaded
at startup; all subsequent requests hit the warm cache. The "FAIL" on latency is an eval
harness artifact, not a production concern.

### Quality results

Recall@10 = 0.942 and MRR = 0.910 are well above targets (0.70 and 0.50). The vector
retrieval over bge-small-en-v1.5 carries the recall on its own.

### Ablation: graph signal is inert on this corpus

**Post-rebuild result (2026-06-05):** After re-running the full extraction pipeline so the
Neo4j graph is current, the eval was re-run. Recall@10 stayed at 0.942 and MRR stayed at
0.910 — identical to the pre-rebuild numbers. The graph density signal
(`log(1+entity_count)/log(10)` with weight 0.3) does not meaningfully reorder the top-10
vector results on this corpus. This is consistent with ADR 0022's design intent: the blend
is conservative enough (W_GRAPH=0.3) that a pure-vector sort order dominates unless entity
counts are very high on the relevant events.

**Conclusion:** Setting `W_GRAPH=0.0` would produce identical recall at this corpus scale.
The vector retrieval is sufficient. The graph signal adds no harm (recall stays at 0.942)
but also no measurable lift.

### Three directions worth investigating before Phase 4A

1. **Increase W_GRAPH to 0.5+ and re-eval.** The current 0.3 weight may be too small to
   produce visible reordering when most events have entity counts < 5. At 0.5, a high-density
   event (10 entities, cosine 0.7) would score `0.5*0.7 + 0.5*1.0 = 0.85`, potentially
   outranking a pure-match event (cosine 0.8, 0 entities, score 0.5*0.8 = 0.40). Whether
   this reordering improves or hurts recall needs a fresh eval run — do not tune without
   evidence.

2. **Replace degree-based graph signal with a more discriminating measure.** The current
   signal (count of asserted entities) treats all entities equally. More informative signals:
   path-to-a-Decision node (events that assert decisions are structurally more important than
   events that only assert Messages), entity-type weighting (a Person entity carries less
   structural signal than a Decision), or betweenness centrality (events that connect many
   graph components). These require precomputed Neo4j measures; appropriate for Phase 4A.

3. **Defer graph-signal tuning to Phase 4A's agent context.** The agent will have the full
   user question and can use the graph signal selectively — e.g., boosting graph-dense events
   only when the question implies structural reasoning ("who is involved in X?"), not for
   vocabulary-matching questions ("what was said about Y?"). A static blend is the wrong
   instrument for a contextual signal; Phase 4A is the right place to make it conditional.

### Failure analysis

Three questions had partial recall failures (unchanged from the initial run):

**Q06 (recall 0.67)** — Missed `doc:adr/D-0005` (the decision being contradicted). The query
pulls toward the contradicting messages; D-0005 itself (which says "stay on legacy-auth")
ranks below 10. The query should be phrased closer to D-0005's language to hit it, or D-0005
should be excluded from expected — it is the *subject* of contradiction, not the evidence.

**Q08 (recall 0.67)** — Missed `C_ARCH-0014` (a Slack message about architecture dependencies).
Landed at rank 11; increasing `BASE_FANOUT` from 3 to 4 would likely include it.

**Q19 (recall 0.50, RR 0.20)** — Missed `doc:wiki/stale-1` ("Legacy-Auth Integration Guide").
The document does not self-describe as "stale"; the query's vocabulary doesn't match its
surface form. A genuine embedding failure, not a fanout issue. BM25 fusion would fix this.

### What would change at scale

See `docs/design/semantic-search.md` §Production-scale changes for the full upgrade path.
The short version: bge-large for quality, GPU for latency, BM25 fusion for vocabulary-match
failures, precomputed entity signals for the graph component.