# Incremental Reconciliation (Phase 5A)

> The design behind live ingestion: turning the batch build pipeline into a per-event,
> idempotent, scoped one that reconciles a new event into the graph in real time — the original
> plan's "killer moment."

## 1. The problem

Through Phase 4C, the knowledge graph is built by a **batch** pipeline (`app.eval.query_eval`):
wipe the graph, seed the event corpus, then run extraction → embed → resolve → consolidate →
project → temporal → contradictions → query. That is the right shape for reproducible evaluation,
but the wrong shape for a demo. The product thesis is a *self-updating* knowledge graph: a recruiter
types a new Slack message into a form, hits "Reconcile," and watches the graph absorb it — a new
node appears, an answer changes, a contradiction lights up — in seconds, live, on screen.

Phase 5A makes that real with one constraint above all others: **idempotency-first**. Demos fail
(double-clicks, dropped connections, hung workers); replays are routine (logic changes, re-process).
A pipeline that corrupts state when an event is processed twice is unusable for a live demo. So
every stage must be safe to re-run, and the whole thing must be fast enough to await inside a
request handler the user is watching.

## 2. The per-stage incremental pattern

`reconcile_event(event_id)` runs the **same eight stages in the same order** as the batch pipeline,
scoped to one event:

| # | Stage | What it does for one event | Cost |
|---|-------|----------------------------|------|
| 1 | extract | LLM → entities/relationships → `MERGE` into Neo4j | 1 LLM call (skipped on replay) |
| 2 | embed | `embed_events()` — embed the new event's text | local, idempotent |
| 3 | resolve | scoped: new fragments × existing nodes of their type | 0–N LLM calls |
| 4 | consolidate | only if a Decision was asserted | 0–N LLM calls |
| 5 | project | copy loser edges onto canonical winners | none (Cypher) |
| 6 | temporal | enrich `valid_from`/`status` + supersession (if Decision) | none |
| 6b | materialize_message | `MERGE` the Message node (slack only) | none |
| 7 | contradiction | scoped: new Message × decisions, or new Decision × messages | 0–N LLM calls |
| 8 | search_index | no-op — the embedding *is* the index (written in stage 2) | none |

Each stage returns a `StageResult` (`ok` / `skipped` / `failed`, duration, a human detail). The
ordered list of `StageResult`s is the **visible demo artifact** — the per-stage timeline the
frontend renders. A stage failure does not abort the run: a slack event whose entity extraction
fails still gets its Message materialised and compared against decisions. The run is `reconciled`
if every stage was ok/skipped, else `partial`.

## 3. Scoped vs. batch — the hybrid decision (ADR 0031)

The pre-implementation check found the per-stage modules **scan globally**: `resolve_graph` is
all-pairs-within-type, `enrich_temporal` walks every decision, the contradiction detector scans all
recent messages × all active decisions. Naively reusing them per event would re-do the whole
corpus's work on every ingest — the first live smoke spent **52 seconds** doing exactly that,
re-adjudicating 61 pre-existing resolution pairs that had nothing to do with the new event.

The decision is **hybrid scoping: scope only where adjudication cost demands it.**

- **Cheap, idempotent, LLM-free stages** (embed, consolidate, project, temporal) call the existing
  batch functions unchanged. At ≤14 nodes per type they run in milliseconds and re-running them is a
  no-op. `scoped_temporal.py` is a one-line pass-through that documents *why* we don't scope it.
- **The two stages that cost money are truly scoped.** Resolution is scoped to **newly-created
  fragments** — nodes whose only provenance is this event (`size(source_event_ids) = 1`). A
  re-mentioned existing entity was MERGEd onto its canonical node at write time and is already
  resolved, so it is excluded; only a brand-new surface form (`@nadia`, a new service name) is
  paired against the existing graph. Contradiction is scoped to the new Message (× active decisions)
  or the new Decision (× recent messages), and its adjudications are fanned out concurrently
  (semaphore of 5).

Scoping by *newly-created fragments* (not just node types) was the decisive optimisation: it took the
heavy case from 52s → 16s, and it is the **correct** behaviour for a self-updating graph — a
re-mention should change nothing. The reused `_decide_and_apply` means a scoped resolution pass makes
byte-identical decisions and writes byte-identical `merge_decisions` rows to what the batch resolver
would.

**Scope is always derived from the graph by provenance**, never from an in-memory extraction result
(`MATCH (n) WHERE $eid IN n.source_event_ids`). This is what makes a replay correct: on a skipped
extraction the graph already holds the nodes, and the same query yields the same scope.

## 4. The idempotency contract (ADR 0032)

"Ingesting the same event twice produces the same end state" is enforced in layers, because the
pipeline mixes idempotent graph writes with **append-only** audit logs:

1. **Endpoint dedup** — `(source_type, source_external_id)` is unique; a repeat short-circuits.
   Without an `external_id`, the id is derived from the content hash, so identical content dedupes.
2. **Orchestration guard** — `reconcile_event` returns the existing `ingestion_runs` row (one per
   event, upserted) without re-running any stage, unless `force=True`.
3. **Extraction skip-guard** — a successful `extraction_runs` row means the LLM is skipped; the graph
   already holds the MERGE-written nodes.
4. **MERGE everywhere** — every graph write is idempotent on its key, so even a forced replay
   converges to identical graph *state*.

**Verification.** `test_ingestion_idempotency.py` asserts the contract three ways: the default replay
short-circuits (`deduplicated=true`, graph counts and `merge_decisions` count unchanged, exactly one
`ingestion_runs` row); a *forced* replay leaves node counts identical (MERGE-level); and the LLM is
called exactly once across all passes (skip-guard). The honest caveat: the "unchanged audit count"
guarantee comes from the guard, not from the append-only logs deduping themselves — a forced replay
can append rows for re-adjudicated fragments. `force=True` is an operator escape hatch, not the demo
path.

## 5. MERGE-everywhere policy

Every write in the incremental path is a Cypher `MERGE` on the node's canonical key (`canonical_id`
for Person, `canonical_name` for Service/System/Team, `id` for Decision/Message) or an edge's
`(type, endpoints)`. `MERGE` is idempotent on the matched key; `CREATE` is not. The graph writer
(verified in the pre-implementation check) already does this and unions `source_event_ids` as a set,
so re-extracting the same event never duplicates a node — it only accumulates provenance. The Message
materialiser, the supersession writer, the projection cleanup, and the contradiction writer are all
MERGE-based for the same reason.

## 6. Concurrency: one writer (ADR 0033)

Reconciliation is a read-modify-write across the shared graph (resolve reads a type's nodes, writes
`MERGE_INTO`; consolidate tombstones; project copies edges). `MERGE` makes individual writes
idempotent but does **not** make those sequences atomic, so two overlapping ingestions could still
produce a wrong merge. The demo has exactly one writer, so we serialise with a single in-process
`asyncio.Lock`: the endpoint acquires it before reconciling, waits up to 30s, then returns **503**.
Reconciliation is awaited inside the handler — no fire-and-forget 202 — because the visible result is
the point. The production path is per-canonical-node locking (disjoint ingestions parallelise) plus a
Postgres advisory lock or Kafka-style partitioning for cross-replica coordination.

## 7. Conflict resolution: when a new event contradicts existing state

The interesting case is not a new node — it is a new event that *opposes* an existing decision. The
pipeline handles this without special-casing: a new slack message materialises a Message node
(stage 6b), then scoped contradiction detection (stage 7) compares it against the active decisions it
names or whose subjects it mentions with an opposition cue, and writes a `CONTRADICTS` edge if the
adjudicator agrees. The decision's own state is untouched — a contradiction is *evidence*, surfaced by
KQ2, not an automatic status change. Re-running KQ2 after the ingest now returns one more contradicting
message. This is deliberate: the graph records the tension and lets a human (or a later phase) decide,
rather than silently flipping a decision to "deprecated" on one Slack message.

## 8. How the 4C structural tools verify reconciliation in real time

Phase 4C's structural tools turn the "self-updating" claim into something **countable**, which is the
strongest demo verification path. Ingest a doc asserting a new person → ask the agent "list all
employees" → `enumerate_by_type(Person).total_count` goes 13 → 14. Ingest a new service ownership →
"which team owns the most services?" → the `aggregate_by_type` group counts shift. The eval encodes
this as the `structural-new-person-acceptance` case and the `test_ingestion_structural_after.py`
integration test: seed N people, ingest a hire, assert `enumerate` returns N+1. The count *is* the
proof — no screenshot interpretation required.

## 9. What changes at 10× scale

- **Resolution adjudication is still sequential** (the eval's 15s tail). The next win is fanning it
  out like contradiction already does.
- **All-pairs candidate generation** within a type is O(n²); past a few thousand nodes it needs an ANN
  index (already named in the entity-resolution design).
- **The single-writer lock** becomes per-canonical-node locking for intra-process parallelism, and an
  external lock (Postgres advisory / Redis) or partitioned single-writer-per-partition for replicas.
- **Synchronous-in-handler** reconciliation would move behind a queue with a streamed progress channel
  once latency or fan-out outgrows a request timeout — but the demo wants the result in the response,
  so we keep it synchronous here, honestly.

## 10. Measured result

100% of the 11 eval cases pass; mean ingestion latency **5.8s** (target ≤ 8s), mean cost
**$0.0031/event**, idempotency verified, structural acceptance verified, and the demo graph baseline
(13/10/89/14/5/4) is preserved after the run because every case reverts itself. See
[../eval/phase-5a-ingestion-results.md](../eval/phase-5a-ingestion-results.md).

---

## Related ADRs

- [ADR 0031](../decisions/0031-incremental-reconciliation.md) — Hybrid scoping: scope resolution + contradiction, reuse cheap stages globally
- [ADR 0032](../decisions/0032-idempotency-contract.md) — Idempotency contract: MERGE everywhere, extraction skip-guard, dedup detection
- [ADR 0033](../decisions/0033-single-writer-lock.md) — Single-writer advisory lock: why not optimistic concurrency at demo scale
