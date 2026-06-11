# Phase 5B — Observability + Parallel Resolution Results

_Generated: 2026-06-11. Run against the live Docker stack (parallel resolver, semaphore of 5)._

Phase 5B is a measure-then-optimise phase. The headline is not a latency number — it is that the
metrics, built first, **corrected the optimisation's premise** and then **validated its mechanism**.

## 1. Headline

- **11-case ingestion eval: 100% success, 100% pass** with the parallel resolver (mean 6072 ms,
  $0.0032/event) — no correctness regression, idempotency intact.
- **The 5A "15 s `doc-new-person` tail" was the embedding-model cold-start, not sequential Tier-2
  adjudication.** A controlled semaphore A/B shows that case triggers **zero** Tier-2 calls; its warm
  resolve stage is ~100 ms.
- **The parallelisation delivers a clean 4.0× speedup where Tier-2 fan-out is large** (forced
  experiment: 16 adjudications, 45.7 s → 11.3 s), bounded exactly by `ceil(16/5) = 4` batches.

## 2. Per-case latency: 5A (sequential) → 5B (parallel)

| Case | 5A latency | 5B latency | Δ |
|------|-----------:|-----------:|----:|
| `doc-new-person` | 15009 ms | 13131 ms | −1878 ms |
| `doc-new-service` | 8709 ms | 9775 ms | +1066 ms |
| `doc-new-decision` | 4343 ms | 4763 ms | +420 ms |
| `slack-contradiction-d0005` | 6983 ms | 7691 ms | +708 ms |
| `slack-contradiction-auth` | 4618 ms | 4578 ms | −40 ms |
| `slack-neutral` | 2270 ms | 2192 ms | −78 ms |
| `resolve-existing-service` | 7143 ms | 6023 ms | −1120 ms |
| `resolve-existing-person` | 4125 ms | 5119 ms | +994 ms |
| `idempotency` | 2721 ms | 2296 ms | −425 ms |
| `empty-extraction` | 1421 ms | 1866 ms | +445 ms |
| `structural-new-person-acceptance` | 6848 ms | 9353 ms | +2505 ms |
| **Mean** | **5835 ms** | **6072 ms** | **+237 ms** |

**The eval totals do not move** (the +237 ms mean delta is within run-to-run variance — LLM
extraction latency dominates each case, and case 1 always eats the embedding cold-start). This is the
expected result given the finding below: none of these cases produce Tier-2 fan-out, so there is no
sequential tail to collapse. The parallelisation's effect has to be isolated, not read off the totals.

## 3. The isolation: a controlled semaphore A/B

Same warm event (`doc-new-person`, Nadia Okafor), same machine, same code — only
`_ADJUDICATION_CONCURRENCY` changes (1 = sequential, 5 = parallel). The embedding model is warmed
first so it does not confound the resolve stage; each insert is reverted.

| Experiment | Tier-2 calls | resolve @ sem=1 (sequential) | resolve @ sem=5 (parallel) | Speedup |
|------------|:---:|---:|---:|:---:|
| **Natural floor (0.75)** | **0** | 109 ms | 82 ms | — (no fan-out) |
| **Forced fan-out (floor 0.0)** | **16** | **45 742 ms** | **11 332 ms** | **4.0×** |

Two facts fall out:

1. **`doc-new-person` makes zero Tier-2 LLM calls** at the real floor — its 16 candidates are all
   below 0.75 cosine similarity (a fresh "Software Engineer" isn't textually close enough to the
   existing engineers). So the 5A 15 s could not have been adjudication; per-stage timing pins it to
   the embedding cold-start on eval case 1 (the first `embed`/`resolve` pays the model load).
2. **When fan-out is genuinely high, the parallelisation works exactly as designed.** Forcing all 16
   pairs to Tier-2 makes the sequential resolve 45.7 s; at concurrency 5 it is 11.3 s — a 4.0×
   speedup, matching `ceil(16/5) = 4` batches (45.7 / 4 ≈ 11.4). The slowest call per batch dominates
   instead of the sum.

## 4. `GET /api/metrics` snapshot

A live snapshot after two ingestions (the metrics are in-memory and reset on the backend's
auto-reload — the volatility ADR 0034 documents; the durable record is `ingestion_runs`):

```json
{
  "ingestion": {
    "total": 2,
    "by_status": {"reconciled": 2},
    "duration_ms": {"p50": 12942.0, "p95": 16424.0, "max": 16810.9},
    "cost_usd": {"mean": 0.003892, "p95": 0.004056, "total": 0.007784}
  },
  "stages": {
    "extract":       {"count": 2, "duration_ms": {"p50": 5497.0, "p95": 5737.8, "max": 5764.6}},
    "embed":         {"count": 2, "duration_ms": {"p50": 4620.1, "p95": 8661.6, "max": 9110.7}},
    "resolve":       {"count": 2, "duration_ms": {"p50": 1588.4, "p95": 2994.6, "max": 3150.8}},
    "contradiction": {"count": 2, "duration_ms": {"p50": 1097.6, "p95": 2085.4, "max": 2195.2}},
    "project":       {"count": 2, "duration_ms": {"p50": 21.6, "p95": 24.0, "max": 24.3}}
  },
  "adjudications": {
    "resolution_total": 14,
    "resolution_by_tier": {"3": 13, "2": 1},
    "contradiction_total": 2
  }
}
```

The `resolution_by_tier` line is the signal that grounds everything above: 14 resolution
adjudications across two events, **13 below-floor (Tier-3) and 1 LLM (Tier-2)**. Real ingestions make
almost no Tier-2 calls — which is exactly why the eval totals don't move, and why the parallelisation
is an insurance policy for high-fan-out cases rather than a headline latency win on this corpus.

## 5. The ingestion-runs audit tab (visual artifact)

`/audit?tab=ingestion-runs` renders one row per live reconciliation, newest first, with the System
metrics strip below. Live state at capture (7 runs):

```
 Ingestion runs                                          [Resolution decisions] [Ingestion runs]
 ┌────────────┬──────────┬─────────────┬──────────────┬───────┬───────────────┬────────┬──────────┐
 │ Status     │ Event    │ Stages      │ Nodes(new/m) │ Edges │ Contradictions│ Cost   │ Duration │
 ├────────────┼──────────┼─────────────┼──────────────┼───────┼───────────────┼────────┼──────────┤
 │ reconciled │ a3f1…    │ ●●●○○●○●○    │ 3 / 4        │ 2     │ 0             │ $0.004 │ 9.1s     │  fraud-scoring-api
 │ reconciled │ 7c20…    │ ●●●○●○●●○    │ 2 / 1        │ 1     │ 2             │ $0.004 │ 16.8s    │  D-0005 stale (contradiction)
 │ reconciled │ 19f5…    │ ●●●○●○○●○    │ 2 / 2        │ 1     │ 0             │ $0.003 │ 8.2s     │  Marcus Webb
 │ …          │          │             │              │       │               │        │          │
 └────────────┴──────────┴─────────────┴──────────────┴───────┴───────────────┴────────┴──────────┘
 System metrics            in-memory · resets on restart
   Ingestions  Median latency   p95 latency    Mean cost
   2           5.5s             12.9s          $0.0039
   14 resolution adjudications (T2:1 · T3:13) · 2 contradiction adjudications.
```

(● = ok, ○ = skipped, red = failed. A real PNG should be captured from the running stack for the
README/demo; this ASCII stands in for the layout.)

## 6. Discussion

**The measurement was worth more than the optimisation.** I set out to parallelise resolution to kill
a 15-second tail; the metrics I built first told me the tail wasn't where I thought. `doc-new-person`
makes zero Tier-2 LLM calls — its resolve stage is ~100 ms warm — and the 15 s was the embedding
model's cold-start on the first eval case. Had I skipped the measurement and "optimised", I would have
shipped a change, re-run the eval, seen the totals barely move, and had no idea why. Building the
observability first turned a confusing non-result into a precise diagnosis.

**The parallelisation is still the right change, and it is proven correct.** It collapses the
adjudication tail wherever fan-out is high — 45.7 s → 11.3 s on 16 calls, a clean 4× — and the unit
tests pin the invariants: same final merge set as the sequential baseline, Tier-1 applied first so
folded targets are skipped, and concurrency bounded at 5. It is an insurance policy that pays out when
a node has many look-alikes; on the current synthetic corpus, where candidate generation is all-pairs
and similarities are well-separated, that condition is rare, so the everyday benefit is small and
honestly so.

**What did move, and what didn't.** Pass rate held at 100% with the parallel resolver — no merge
regressed, idempotency intact (the eval's `idempotency` case passes; a live double-submit returns
`deduplicated: true` in 0 ms). The eval mean is flat (5835 → 6072 ms, noise). The genuine latency
floor on this corpus is the two sequential LLM calls in the critical path (extraction, then
adjudication/contradiction) plus the one-time embedding cold-start — none of which parallel resolution
addresses, and all of which are named here rather than hidden.

**What this does not test.** Real high-fan-out resolution from organic data (the forced experiment
lowers the floor artificially to create it); cross-restart metric retention (in-memory by design);
and concurrency under multiple writers (the single-writer lock serialises by construction, ADR 0033).
These are named scope limits, consistent with the project's scope-honesty value.
