# Phase 3B — Interview Readiness: Query Engine + Temporal

Ten Q&A pairs and five whiteboard concepts for the query-engine subphase. Pair these with the
design doc (`docs/design/query-engine.md`) and ADRs 0016–0019.

---

## Q&A

### 1. Walk me through KQ1 step by step — Cypher pattern, output, provenance.

KQ1 answers "who owns the service that depends on the system deprecated by Decision X." The
Cypher seeds on `(:Decision {id})`, a constraint-backed point lookup, then follows three typed
hops: `-[:DEPRECATES]->(:System)`, `<-[:DEPENDS_ON]-(:Service)`, `-[:OWNED_BY]->(owner)`. If the
owner is a Team it expands one more hop, `(owner)<-[:MEMBER_OF]-(:Person)`, so the answer is
always at person granularity. Every hop is guarded by `WHERE n.status <> 'merged'`. The result
is `QueryResult[ChainOwnerAnswer]`: the owning people plus the full node chain, and provenance
keyed per chain holding each traversed edge's `source_event_id`. For D-0006 the answer is Diego
Ramirez via `D-0006 → legacy-auth → payments-api → payments → diego-ramirez` (4 hops).

### 2. Why does the `status <> 'merged'` filter matter for query correctness?

Phase 3A merges duplicates non-destructively: the loser is tombstoned `status='merged'` and
linked to its winner with `MERGE_INTO`, nothing is deleted. The resolved view is precisely the
graph minus the tombstones, so every query filters `status <> 'merged'` to avoid double-counting
an entity that appears as several fragments. Drop the clause and you see the fragmented pre-3A
graph — useful for a demo contrast, wrong for an answer. The subtlety we had to fix in 3B: the
3A merger does not migrate the loser's *edges* onto the winner, so the filter alone strands edges
on tombstones; our edge-projection cleanup copies those edges onto canonical winners first.

### 3. What does `as_of` enable, and why is `datetime.now()` the wrong default?

`as_of` is the injectable "now" every temporal query takes. KQ2 ("last month") and KQ4 ("last
quarter") compute their window as `as_of - window`. The synthetic corpus is frozen at
`REFERENCE_NOW = 2026-06-01`, with the planted contradiction tail deliberately at 16–22 days
before it. If queries used wall-clock `datetime.now()`, every run after mid-2026 would slide the
window past that data and return nothing — a silent, time-dependent eval failure that rots the
demo. So `as_of` defaults to `REFERENCE_NOW` for dev/eval and is overridden with real now in
production. It is one well-named seam that keeps the eval reproducible without special-casing.

### 4. How does multi-source Decision consolidation differ from entity resolution?

Persons and Services are identity-bearing: they have stable keys (email, handle, slug), so 3A's
Tier-1 rules merge them deterministically and embeddings only break ties. Decisions are
content-bearing: a doc and the Slack thread that originated it may produce two Decision nodes,
and there is no stable key when a source paraphrases without the id. So the consolidator merges
on `title + body` embedding cosine ≥ 0.85 — stricter than the 0.75 entity floor because a false
content-merge silently corrupts KQ2/KQ4 — gated by 30-day temporal proximity, with a hard guard
that two *distinct formal* `D-####` ids never merge. It reuses the same `MERGE_INTO` mechanism so
the audit trail is uniform, recording a `content_merge` row.

### 5. What's the worst-case complexity of KQ3, and how would you scale to 10K services?

KQ3 is a bounded variable-length traversal, `(affected)-[:DEPENDS_ON*1..max_depth]->(seed)`. Its
worst case is exponential in the dependency fan-in — a dense graph where many services depend on
many others blows up the path frontier. We bound it three ways: a hop limit (`max_depth`, default
5), an early `WITH collect(DISTINCT affected)` that collapses the frontier to a node set rather
than enumerating every path, and the per-node `status` guard. At 12 synthetic services it is
trivial. At 10K I'd keep the hop bound, push the distinct-collapse, and precompute a materialised
reachability/closure table refreshed on write so the query becomes a table lookup, not a live
traversal — the standard graph-at-scale fix.

### 6. The eval is end-to-end. Why is that the right shape vs testing each layer?

The demo's claim is that a question becomes a grounded answer, and that depends on *every* layer
being correct simultaneously: extraction must find the edges, resolution must merge the
fragments, projection must move edges to winners, consolidation must not over-merge, temporal
enrichment must date the decisions, and the contradiction pass must populate KQ2's edges. A
per-layer test can pass while the seam between two layers is broken — exactly the failure that
kills a demo. The integration eval runs seed → extract → resolve → consolidate → project →
messages+contradictions → temporal → query and checks the four planted answers. We still keep
unit + per-layer DB tests for fast diagnosis; the integration eval is the gate.

### 7. Show me a KQ result and trace where every event ID came from.

Take KQ4 for `auth-service`. The answer lists D-0006, D-0007, D-0008, D-0010 with approvers. The
`QueryProvenance.by_element` map has `node:Decision:D-0006 → [<the decision-record event UUID>]`
(from the node's `source_event_ids`), `edge:APPROVED_BY:D-0006 → [<the event that asserted the
approval>]` (from the edge's `source_event_id`), and `edge:SUPERSEDES:D-0010 → [<event>]`. Each
UUID is a foreign key into the Postgres `events` table; the eval validates every one resolves to
a real row. So the demo can render "D-0010 supersedes D-0004, approved by Alice — justified by
events X and Y," and clicking through shows the original ADR text.

### 8. What would break if you ran KQ4 on the unresolved graph?

Approver attribution fragments. Ben Smith approves early decisions as `@bsmith` and later ones as
`@ben`; Alice appears as `Alice Chen`, `@alice`, and the nickname `Al`. On the unresolved graph
those are separate Person nodes, so "who approved each change" returns several apparent approvers
for one human, and a count-by-approver is meaningless. KQ4 also depends on temporal enrichment:
without `valid_from` populated the quarter filter has nothing to compare against and returns
either everything or nothing. And without the `SUPERSEDES` edge the D-0010→D-0004 supersession —
the most interesting event in the timeline — is invisible.

### 9. How does provenance flow from Postgres event IDs to query result?

When extraction writes a node it stamps `source_event_ids` (the Postgres event UUIDs it came
from); when it writes an edge it stamps a single `source_event_id`. Resolution unions provenance
onto the winner; consolidation does the same for decisions; projection copies edges with their
`source_event_id` intact. At query time each KQ's Cypher returns those fields alongside the
answer, and the query function folds them into `QueryProvenance.add(element_key, event_ids)`,
de-duplicating. The result is `QueryResult[T]` with `value` and `provenance`. The eval then takes
`provenance.all_event_ids` and looks each one up in Postgres via `EventRepository.get_by_id`,
failing the query if any id is missing — provenance that can't be grounded is a bug.

### 10. If extraction missed an edge, what happens to KQ3's answer, and how would you surface it?

KQ3 would under-report: a missing `DEPENDS_ON` edge prunes a whole subtree of dependents, so the
blast radius shrinks silently — the most dangerous kind of wrong, because the answer still looks
plausible. The corpus mitigates this structurally: every KQ-critical edge is asserted in at least
one architecture doc *and* reinforced in a Slack message, so a single missed extraction rarely
removes an edge entirely. The integration eval surfaces it directly — KQ3's gate is "≥10 services
incl. web-storefront," so a dropped edge fails the gate and the report names the missing chain. In
production I'd add a confidence-weighted completeness check and flag services whose only inbound
dependency edge sits below a confidence floor.

---

## Whiteboard concepts

1. **The KQ1 chain.** Draw `(:Decision)-[:DEPRECATES]->(:System)<-[:DEPENDS_ON]-(:Service)
   -[:OWNED_BY]->(:Team)<-[:MEMBER_OF]-(:Person)`. Annotate each hop with the source document that
   asserts it (decision record / arch diagram / service catalog / org chart) to show why only a
   traversal — not RAG — can answer it.

2. **The Decision temporal state machine.** `active --(SUPERSEDES from newer)--> superseded`;
   `valid_from` = earliest source-event time, `valid_to` = NULL until a superseder sets it to the
   superseder's `valid_from`; `merged` is an orthogonal tombstone set by resolution, never touched
   by enrichment.

3. **`as_of` vs `REFERENCE_NOW`.** A timeline with `REFERENCE_NOW` fixed at 2026-06-01, the
   contradiction tail at −22d, and a window bracket `[as_of − 30d, as_of]`. Show wall-clock now
   sliding the bracket off the data, and `as_of = REFERENCE_NOW` keeping it on.

4. **`QueryResult[T]`.** A box with `value: T` and `provenance: QueryProvenance`, the latter a map
   `element_key → [event UUIDs]` plus `all_event_ids`. Arrows from each event UUID into the
   Postgres `events` table.

5. **The integration eval pipeline.** A left-to-right chain: seed → extract → resolve →
   consolidate → project-edges → ingest-messages + detect-contradictions → temporal-enrich → run
   4 KQs → compare to narrative answers. Mark which planted case each KQ checks.
