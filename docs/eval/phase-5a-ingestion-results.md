# Phase 5A — Live Ingestion Eval

_Generated: 2026-06-07T09:15:13+00:00_

Ran **11** hand-curated cases against the live populated graph, scoring each and reverting its effects (idempotent). Extraction uses `claude-3.5-haiku`; expectations are label-level (extraction is stochastic).

## Headline metrics

- **Ingestion success rate** (reconciled/partial): **100.00%** (target ≥ 0.90)
- **Case pass rate** (all checks): **100.00%**
- **Mean ingestion latency**: **5835 ms** (target ≤ 8000 ms)
- **Mean cost per ingestion**: **$0.0031**

## Per-case results

| Case | Kind | Pass | Status | Latency | Cost | Checks |
|------|------|------|--------|---------|------|--------|
| `doc-new-person` | new_doc | ✅ | reconciled | 15009 ms | $0.0029 | status=✓, node_label=✓, min_nodes=✓, structural=✓ |
| `doc-new-service` | new_doc | ✅ | reconciled | 8709 ms | $0.0041 | status=✓, node_label=✓, min_nodes=✓, structural=✓ |
| `doc-new-decision` | new_doc | ✅ | reconciled | 4343 ms | $0.0029 | status=✓, node_label=✓, min_nodes=✓, stages=✓ |
| `slack-contradiction-d0005` | new_slack | ✅ | reconciled | 6983 ms | $0.0039 | status=✓, contradiction=✓, stages=✓ |
| `slack-contradiction-auth` | new_slack | ✅ | reconciled | 4618 ms | $0.0032 | status=✓, contradiction=✓, stages=✓ |
| `slack-neutral` | new_slack | ✅ | reconciled | 2270 ms | $0.0023 | status=✓, contradiction=✓, stages=✓ |
| `resolve-existing-service` | resolution | ✅ | reconciled | 7143 ms | $0.0037 | status=✓, structural=✓ |
| `resolve-existing-person` | resolution | ✅ | reconciled | 4125 ms | $0.0030 | status=✓, structural=✓ |
| `idempotency` | idempotency | ✅ | reconciled | 2721 ms | $0.0023 | status=✓, idempotent=✓ |
| `empty-extraction` | failure | ✅ | reconciled | 1421 ms | $0.0021 | status=✓, max_nodes=✓, contradiction=✓ |
| `structural-new-person-acceptance` | structural | ✅ | reconciled | 6848 ms | $0.0036 | status=✓, node_label=✓, structural=✓ |

## Discussion

**All 11 cases pass; success rate and pass rate are both 100%.** Every case reconciled (none
fell to `partial`/`failed`), every node-creation expectation held at label level, both
contradiction cases produced a `CONTRADICTS` edge, the neutral and empty cases produced none, and
the structural acceptance moved the `Person` enumerate count from N to N+1 — the 4C↔5A claim,
verified mechanically.

**Latency: mean 5.8s, well under the 8s target, but the distribution is wide (1.4s–15.0s).** The
floor is the empty/neutral cases (1.4–2.3s: extraction returns little, no adjudication runs). The
ceiling is `doc-new-person` at 15.0s. That case is the honest worst case for resolution: a brand-
new `Person` fragment is paired against all 13 existing people, and several are textually similar
enough (shared "Software Engineer" role text) to cross the 0.75 similarity floor and trigger a
sequential Tier-2 adjudication each. Resolution adjudications are **not** parallelised (the batch
resolver is sequential and `_decide_and_apply` is reused verbatim for decision-parity), so a run
of similar candidates serialises. Contradiction adjudications *are* fanned out concurrently
(semaphore of 5), which is why the contradiction-heavy slack cases stay ~5–7s. The single biggest
remaining win is to parallelise resolution adjudication the same way; it is deliberately deferred
to keep the scoped resolver a faithful reuse of locked 3A logic. The mean is the honest headline;
the 15s tail is named, not hidden.

**Two design choices visibly pay off in these numbers.** (1) Scoping resolution to *newly-created*
fragments (sole-provenance nodes) means the resolution cases that merely re-mention existing
entities (`resolve-existing-service`, `resolve-existing-person`) create **zero** new nodes and do
**zero** adjudication for the re-mentioned entity — the structural delta is 0, exactly as a
self-updating graph should behave. (2) The extraction skip-guard + orchestration guard make the
`idempotency` case a 2.7s no-op on replay (`deduplicated=true`), and the per-case revert leaves the
graph at its exact baseline (13/10/89/14/5/4 verified after the run).

**Cost: mean $0.0031/ingestion**, in line with the ~$0.003 estimate. The spread ($0.0021–$0.0041)
tracks how much adjudication a case triggers: empty/neutral cases are essentially one extraction
call; service/decision/contradiction cases add resolution and/or contradiction adjudications. At a
fictional 10k events/day this is ~$30/day — the point where a cheaper extraction model
(gemini-flash-lite) and caching would matter; at portfolio scale, reliability (haiku) wins.

**What this does not test.** Concurrency (the single-writer lock serialises by construction, so
there is no interleaving to measure here), real corpus drift (cases run against the fixed demo
graph), and extraction-failure handling under a real LLM outage (the unit tests cover the
`partial` path with an injected failure; live, the model did not fail). These are named scope
limits, consistent with the project's scope-honesty value.

