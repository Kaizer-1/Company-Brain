# Phase 5A Readiness — Live Ingestion & Incremental Reconciliation

Twelve Q&A pairs for defending the streaming-ingestion subphase. Each answer is interview-length
(~100–160 words). Backing docs: [incremental-reconciliation.md](../design/incremental-reconciliation.md),
ADRs [0031](../decisions/0031-incremental-reconciliation.md) /
[0032](../decisions/0032-idempotency-contract.md) / [0033](../decisions/0033-single-writer-lock.md),
eval [phase-5a-ingestion-results.md](../eval/phase-5a-ingestion-results.md).

---

### Q1. Why incremental reconciliation instead of just re-running the batch pipeline per event?

The batch pipeline wipes and rebuilds the whole graph from the whole event corpus — extraction,
resolution, contradiction, all of it. That's correct for reproducible evaluation, but for a *live*
ingest it's the wrong shape three ways: it's slow (seconds to minutes), it re-pays for every event's
LLM calls each time, and it can't run inside a request handler the user is watching. The product
thesis is a self-updating graph, so a new event should touch only what its assertions affect.
Incremental reconciliation runs the same eight stages in the same order, but scoped to one event,
idempotently. The result is a `POST /api/events` that reconciles in ~6 seconds and returns a visible
per-stage timeline — the demo's climax — instead of a multi-minute rebuild nobody can watch.

### Q2. You said "scoped," but the existing modules scan globally. How did you actually scope them?

Hybrid scoping — I scope only where adjudication cost demands it. The pre-implementation check found
`resolve_graph` is all-pairs-within-type, temporal walks all decisions, and the contradiction
detector scans all recent messages × all active decisions. The cheap, idempotent, LLM-free stages
(embed, consolidate, project, temporal) I just call as-is; at ≤14 nodes per type they're milliseconds
and re-running them is a no-op. The two stages that cost money I genuinely scoped: extraction skips
when a prior successful run exists, and resolution + contradiction scope to the nodes the event
introduced. Resolution specifically scopes to *newly-created fragments* — nodes whose only provenance
is this event — because a re-mentioned entity was MERGEd onto its canonical node already and needs no
re-resolving. That last refinement took the heavy case from 52 to 16 seconds.

### Q3. What does idempotency mean here, concretely, and how do you verify it?

It means ingesting the same event twice produces the same end state. I enforce it in layers: the
endpoint dedupes on the event's unique `(source_type, source_external_id)` key (derived from the
content hash if no external id is given); the orchestrator returns the existing `ingestion_runs` row
without re-running stages; extraction skips if a successful run exists; and every graph write is a
`MERGE`, so even a forced replay converges to identical graph state. The load-bearing test asserts all
three: a default replay short-circuits with `deduplicated=true` and unchanged graph and audit counts;
a forced replay leaves node counts identical; and the LLM is called exactly once across all passes.
The honest caveat is that our audit logs are append-only by design, so the unchanged-audit guarantee
comes from the guard, not from the logs deduping themselves.

### Q4. MERGE vs CREATE — why does it matter so much?

`MERGE` is idempotent on the matched key: "find this node by its canonical key, or create it." Running
it twice is a no-op. `CREATE` always inserts, so running it twice duplicates the node. In a streaming
pipeline that re-processes events on retry or replay, `CREATE` would silently fragment the graph —
two `payments-api` nodes, two `D-0005`s — which then corrupts every traversal. So every write in the
incremental path is `MERGE` on the node's canonical key or the edge's `(type, endpoints)`, and the
graph writer unions `source_event_ids` as a set rather than overwriting. This is what lets the
extraction skip-guard work: if a prior run already MERGEd the nodes, re-deriving scope from the graph
gives the identical set, so skipping the LLM is safe. MERGE-everywhere is the foundation the whole
idempotency contract sits on.

### Q5. Walk me through the demo moment.

On `/ingest`, you paste a Slack message — say "welcome aboard Nadia, joining the platform team as a
Software Engineer" — and hit Reconcile. The endpoint inserts the event, acquires the writer lock, and
runs the eight stages: extraction pulls out a Person, embedding indexes the text, resolution checks
her against the existing 13 people and finds no match (new fragment), the decision/message stages
skip, and it returns a per-stage timeline plus a "what changed" panel showing the new Person node.
Then you switch to `/ask` and type "list all employees" — the agent routes to the `enumerate`
structural tool and returns 14, not 13. You point at the changed number. The graph at `/graph`
re-fetches on focus and the new node is there. The whole thing is under ten seconds and every step is
visible — that's the difference between a static-graph screenshot and a memorable demo.

### Q6. How do the Phase 4C structural tools verify reconciliation?

They make the "self-updating" claim *countable*. Before 4C, verifying an ingest meant eyeballing the
graph canvas for a new dot — unconvincing. The structural tools give exact integers: `enumerate_by_type`
returns a `total_count`, `aggregate_by_type` returns group counts. So the acceptance test is arithmetic:
seed N people, ingest a hire, assert `enumerate(Person)` returns N+1. Ingest a new service ownership,
assert the `aggregate(Service, group_by=OWNED_BY)` counts shift in the expected direction. I encoded
this as both an eval case and an integration test (`test_ingestion_structural_after.py`) that calls
the tool directly against Neo4j. The count *is* the proof — no screenshot interpretation. This is the
4C↔5A tie: the read-path tools built in 4C become the write-path verification mechanism in 5A, which is
also exactly how you'd convince a skeptical interviewer the graph really updated.

### Q7. A stage fails mid-reconciliation — what happens?

A stage failure is recorded, not fatal. Each stage returns a `StageResult` of `ok`/`skipped`/`failed`,
and the orchestrator keeps going. If extraction's LLM call fails, that stage is marked `failed` and
the event's `extraction_runs` row records the error — but downstream stages still run. A slack event
whose entity extraction failed still gets its Message node materialised and compared against the active
decisions, because those stages don't depend on the extracted entities. The run's overall status
becomes `partial` (any failed stage) rather than `reconciled`, and that's surfaced honestly on the
frontend banner ("Partial reconciliation: 1 stage failed"). This matters for a live demo: a transient
model hiccup degrades gracefully to a partial result instead of throwing a 500 and looking broken. The
unit test injects a broken extraction client and asserts exactly this — `partial`, extract `failed`,
message materialised `ok`.

### Q8. What happens when a new event contradicts an existing decision?

The pipeline records the tension; it does not silently resolve it. A new slack message materialises a
Message node, then scoped contradiction detection compares it against the decisions it names — or whose
subjects it mentions with an opposition cue like "stale," "should not," "deprecated" — and an LLM
adjudicator decides whether it genuinely opposes the decision. If so, it writes a `CONTRADICTS` edge.
Crucially, the decision's own status is untouched: a contradiction is *evidence*, surfaced by KQ2, not
an automatic state change. Re-running KQ2 after the ingest returns one more contradicting message for
that decision. I made this deliberate — flipping a decision to "deprecated" off a single Slack message
would be the kind of overconfident automation that corrupts a knowledge graph. The graph's job is to
make the conflict *visible* to a human, with provenance, not to adjudicate org decisions on its own.

### Q9. Why a single lock? Doesn't that kill throughput?

It does, and for this system that's the right trade. Reconciliation is a read-modify-write across the
shared graph — resolution reads a type's nodes and writes merge edges, consolidation tombstones,
projection copies edges. `MERGE` makes individual writes idempotent but doesn't make those *sequences*
atomic, so two overlapping ingestions could still produce a wrong merge. A single in-process
`asyncio.Lock` serialises ingestions, which is trivially correct, and the demo has exactly one writer,
so there's no throughput being left on the table. A second concurrent request waits up to 30 seconds
then gets a clean 503 — honest backpressure. The cost is named, not hidden: no parallelism, and the
lock is per-process so it wouldn't coordinate across replicas. But spending a week on a lock manager
for a workload that's one-event-at-a-time would be machinery without a job.

### Q10. So how would the concurrency story scale in production?

Two changes. First, per-canonical-node locking instead of one global lock: an ingestion locks only the
canonical nodes its event touches, so two ingestions on disjoint subgraphs run in parallel. The
wrinkle is you need to know an event's node set before extraction, which means either a cheap
pre-pass or optimistic locking with retry. Second, cross-replica coordination: the in-process lock
doesn't span processes, so multiple backend replicas would need an external lock — a Postgres advisory
lock keyed on the node, or a Kafka-style partitioned model where each partition has a single writer and
events are partitioned by entity, giving you ordered, exactly-once-ish processing per entity. At that
point reconciliation likely moves behind a queue with a streamed progress channel rather than being
awaited in the request. For the demo, synchronous-in-handler with one lock is the honest, correct
choice; I can articulate the exact upgrade path without having over-built it.

### Q11. What does an ingestion cost, and why?

Mean $0.0031 per event, measured across the 11 eval cases. The spread is $0.0021–$0.0041 and tracks
how much LLM adjudication a case triggers. Every event pays for one extraction call (~$0.002 on
claude-3.5-haiku). On top of that, a new fragment that resembles existing entities triggers resolution
adjudications, and a slack message that names or opposes a decision triggers contradiction adjudications
— each a small haiku call. An empty or off-topic message is basically just the extraction call; a
service or contradiction case adds a few more. I deliberately use haiku, the highest-F1 model from the
2B comparison, rather than the cheaper gemini-flash-lite, because demo reliability beats a fraction of a
cent. At a fictional 10k events/day that's ~$30/day — the point where you'd switch extraction to a
cheaper model and add prompt caching. At portfolio scale, reliability wins and the number is honest.

### Q12. How does this subphase actually deliver the "self-updating knowledge graph" claim?

Every prior phase was infrastructure for two payoffs: the agent (4A–4C) and this. "Self-updating" means
new knowledge enters and the graph reorganises itself — new entities resolve against existing ones, new
discussions surface contradictions with existing decisions, and queries immediately reflect the change,
all without a human editing the graph by hand. 5A delivers exactly that loop: a raw event in one end,
and out the other a reconciled graph plus a re-answerable question, in seconds, idempotently. The proof
isn't rhetorical — it's the structural acceptance test (ingest a hire, the employee count goes up by
one) and the KQ2 flow (ingest a dissenting message, the contradiction query returns it). The honest
boundary is scope: synthetic data, single writer, one extraction model. But the *mechanism* — extract,
resolve at write time, detect contradictions incrementally, verify with countable structural tools — is
the real thing, and it's what makes the demo land.
