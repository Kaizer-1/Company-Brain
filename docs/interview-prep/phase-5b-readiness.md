# Phase 5B — Interview Readiness (Observability + Parallel Resolution)

Eight question/answer pairs an interviewer is likely to probe, with the honest engineering behind
each. Phase 5B is the cleanest "engineering with rigor" story in the project: build observability,
use it to motivate an optimisation, and let the measured before/after — including a correction to a
prior hypothesis — be the proof.

---

### Q1. Why in-memory metrics instead of Prometheus or OpenTelemetry?

Scale and audience. This is one process handling tens of ingestions, shown to an interviewer — not a
fleet. A real time-series stack (Prometheus + Grafana) or a tracing pipeline (OTel + collector) would
be infrastructure with no workload to justify it, and worse, it would bury the one signal this phase
is about — the resolution before/after — under a dashboard. So metrics live in a module-level
`Metrics` registry: counters and raw-sample histograms accumulate during reconciliation, and
`GET /api/metrics` reduces them to percentiles on read. The honest cost is that the numbers are
process-local and reset on restart; that limitation is named in ADR 0034. The `record_*` call sites
are the stable interface — in production they'd feed `prometheus_client` or an OTel exporter without
moving, and a per-worker-registry-plus-aggregation model would handle multiple replicas. The durable
record of *what happened* already exists separately in the `ingestion_runs` table.

### Q2. Why a semaphore of 5 for the parallel adjudication, and not unbounded concurrency?

Two reasons, one practical and one principled. Practically, an unbounded `gather` over a node with N
look-alikes fires N simultaneous OpenRouter calls — straight into rate limits and 429s. The failure
mode of "save two seconds, then get throttled and retry" is worse than the latency it saves; a bound
gives backpressure. Principled: I'd already chosen 5 for the contradiction detector's concurrent
adjudication in Phase 5A, for exactly this rate-limit reason, so reusing it keeps one defensible
number across both cost-bearing stages ("same bound, same reason"). The measured effect confirms the
bound is the right mental model: 16 forced Tier-2 calls took 45.7 s sequentially and 11.3 s at
concurrency 5 — a 4.0× speedup, which is exactly `ceil(16/5) = 4` batches. The semaphore turns N
sequential calls into ⌈N/5⌉ batches where the slowest call in each batch dominates, instead of the
sum of all of them.

### Q3. Walk me through the Tier-1-first ordering. Why does it matter?

Resolution has three tiers: Tier-1 is a deterministic rule (shared handle/email/alias) that
auto-merges; Tier-3 is below the similarity floor and never adjudicated; Tier-2 is the ambiguous band
that asks the LLM. The parallel resolver runs in three passes, and the ordering is load-bearing: pass
1 applies Tier-1 merges *first* and records which targets got folded into a canonical node; pass 2
adjudicates only the Tier-2 pairs whose target was **not** folded; pass 3 applies the verdicts. If a
new fragment (`@nadia`) auto-merges into its canonical Person in pass 1, any remaining Tier-2 pair on
that same fragment is already resolved — adjudicating it would be a wasted LLM call, and in the worst
case a double-merge. So Tier-1-first is both a cost optimisation (fewer calls) and a correctness
guard. The unit test pins this: a target that auto-merges in pass 1 has zero adjudications in pass 2,
and the final merge set is identical to the sequential baseline.

### Q4. You built the metrics before the optimisation. What did that buy you?

It caught a wrong hypothesis before I wrote code against it. Phase 5A's eval named a 15-second tail on
`doc-new-person` and *guessed* it was sequential Tier-2 adjudication. With per-stage metrics and a
controlled semaphore A/B (concurrency 1 vs 5 on the same warm event), the data said otherwise: that
case's warm resolve stage is ~100 ms and triggers **zero** Tier-2 calls — its 16 candidates all fall
below the 0.75 floor. The 15 s was the embedding model's cold-start on the first eval case, paid in
the embed and resolve stages. So the parallelisation's real-world benefit on the case I set out to fix
is negligible. That's the whole point of measure-then-optimise: I shipped the optimisation anyway
(it's correct and helps wherever fan-out is genuinely high, proven by the forced-fan-out experiment),
but I didn't get to claim a 15→4 s win that the data doesn't support. Honest numbers over a tidy
narrative.

### Q5. What's the difference between the metrics endpoint and the ingestion-runs audit tab? Aren't they redundant?

No — they answer different questions and have different lifetimes. `GET /api/metrics` is *aggregate
and volatile*: rates and distributions (total ingestions, p50/p95 latency, mean cost, adjudications
by tier), computed over whatever this process has handled since it started. It answers "how is the
system behaving overall?" `GET /api/audit/ingestion-runs` is *per-run and durable*: one row per
reconciliation, read from the `ingestion_runs` table in Postgres, with the stage timeline, counts,
cost, and latency for *that specific event*. It answers "what happened on this run, and can I inspect
it?" A distribution and an inspectable ledger are different tools — you reach for the metrics strip to
see the p95, and the audit row to see why one particular ingestion went `partial`. Keeping them
separate also means a restart zeroing the metrics doesn't touch the audit history.

### Q6. Why cursor pagination for the ingestion-runs feed when the merge-decisions tab uses offset?

Because the two feeds grow differently. The merge-decisions table is effectively static between demo
runs, so offset/limit is fine — page 2 is always the same rows. The ingestion-runs feed grows *from
the head*: every new ingestion prepends a row. With offset pagination, a row inserted between loading
page 1 and page 2 shifts everything down by one, so the user sees a duplicate at the page boundary or
skips a row. A cursor — here the `started_at` of the next page's first row, passed back as `before` —
is stable against head insertions: "give me the 20 runs older than this timestamp" returns the same
answer regardless of what arrived since. It's the standard choice for an append-from-the-top feed. The
endpoint fetches `limit + 1` rows to decide whether a next cursor exists, and the frontend's "Load
more" button threads the returned cursor back in.

### Q7. The parallel resolver changes the order of writes. How do you know it's still correct?

The correctness claim is "same final merge set as the sequential baseline," and it's pinned by a
hermetic unit test that runs both the parallel `_resolve_targets_against` and the sequential
`_decide_and_apply` loop over the same fixture and asserts the set of MERGE decisions is identical.
Parallelism changes *when* the LLM is called and the *order* of the audit rows, not *what* gets
merged — merge identity is determined by the rule match and the verdict, both of which are independent
across pairs. The one intentional difference is that the parallel path skips Tier-2 pairs whose target
already auto-merged (Tier-1-first), which makes *fewer* calls but the same merges. Writes stay serial
through the single shared Postgres session, so there's no write race. End to end, the ingestion eval's
`idempotency` case still passes with the parallel resolver, and a live double-submit still returns
`deduplicated: true` in 0 ms — the idempotency contract (ADR 0032) is untouched.

### Q8. The HANDOFF listed SSE progress and per-node locking as 5B candidates. Why did you defer them?

Scope honesty. Phase 5B was scoped to exactly three things — the audit tab, the metrics layer, and the
parallel resolution the metrics motivate — and both deferred items fail the "does this phase need it?"
test. SSE progress on `/ingest` is a UX nicety: the reconciliation is already awaited inside the
request handler and returns the full per-stage timeline in the response, which a single demo user sees
immediately; streaming the stages as they complete is polish for 6A, not a 5B requirement. Per-
canonical-node locking is the *production* concurrency path behind ADR 0033's single-writer lock — it
lets disjoint ingestions parallelise across replicas — but the demo has exactly one writer, so the
lock is already correct and the machinery (a lock manager, deadlock avoidance, knowing an event's node
set before extraction) would be overhead with no workload. Naming them as deferred, rather than
quietly building them, is the same discipline as naming the synthetic-data and no-auth limitations:
deliberate scope, not unfinished work.
