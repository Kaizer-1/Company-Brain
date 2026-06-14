# Company Brain — Query Engine + Temporal Model (Phase 3B)

> **Status**: Locked in Phase 3B. Summarised in [ADR 0016](../decisions/0016-temporal-query-model.md)
> (temporal model), [ADR 0017](../decisions/0017-multi-source-decision-consolidation.md)
> (Decision consolidation), [ADR 0018](../decisions/0018-query-result-provenance.md)
> (provenance shape), and [ADR 0019](../decisions/0019-contradiction-message-population.md)
> (the Message/CONTRADICTS population pass).
> Python: `backend/app/queries/`, `backend/app/temporal/`, `backend/app/contradiction/`,
> `backend/app/resolution/consolidator.py`. Eval: `backend/app/eval/query_eval.py`.

**What this doc is.** This document describes how the four killer queries are implemented as typed Cypher traversals over the resolved, temporally-enriched knowledge graph. It covers the `as_of` convention that makes queries reproducible against the synthetic timeline, how Decision consolidation handles multi-source assertions of the same decision, the `QueryResult` provenance shape that attaches source event UUIDs to every answer, and how contradiction detection and Message population fit into the pipeline order. Read this before looking at `backend/app/queries/` or running the killer queries against a live graph.

This is the payoff phase. The schema (1B), the synthetic corpus (2A), the extraction
pipeline (2B), and the entity resolver (3A) all existed to make **the four killer queries**
executable against a clean, resolved graph. This document locks the decisions that make
that execution defensible — *before* any Cypher is written — and then shows the Cypher.

---

## 1. The four killer queries, restated

For each query: the natural-language question, the resolved-graph traversal pattern, the
Cypher, and **the failure mode if the graph were unresolved** — i.e. why Phase 3A had to
happen first. Every traversal filters `WHERE n.status <> 'merged'` so it sees only the
resolved view; dropping that clause shows the fragmented pre-3A graph (the same convention
the resolver established).

### KQ1 — Multi-hop ownership

> *Who owns the service that depends on the system deprecated by Decision X?*

Traversal: `Decision -[:DEPRECATES]-> System <-[:DEPENDS_ON]- Service -[:OWNED_BY]-> Person|Team`.
The seed `D-0006` deprecates `legacy-auth`; `payments-api` still depends on `legacy-auth`
(the migration is incomplete); `payments-api` is owned by the `payments` team, led by
`diego-ramirez`. The canonical answer is **Diego Ramirez** via a 4-hop chain, with
`subscriptions-service` (owned by `growth`/`priya-nair`) a legitimate secondary dependent.

```cypher
MATCH (d:Decision {id: $decision_id})-[dep:DEPRECATES]->(sys:System)
WHERE coalesce(d.status,'active') <> 'merged' AND coalesce(sys.status,'active') <> 'merged'
MATCH (svc:Service)-[r1:DEPENDS_ON]->(sys)
WHERE coalesce(svc.status,'active') <> 'merged'
MATCH (svc)-[r2:OWNED_BY]->(owner)
WHERE coalesce(owner.status,'active') <> 'merged'
OPTIONAL MATCH (owner)<-[:MEMBER_OF]-(lead:Person) WHERE owner:Team
RETURN d, sys, svc, owner,
       labels(owner)[0] AS owner_type,
       collect(DISTINCT [dep.source_event_id, r1.source_event_id, r2.source_event_id]) AS edge_events
```

**Failure mode unresolved**: `payments-api` is referenced as `payments-api`, *"the Payments
team's API"*, *"@payments' service"*, and bare *"payments"*; Diego appears as `Diego Ramirez`,
`@diego`, and (in the KQ1 thread) only as *"the payments lead"*. Without resolution these are
four Service nodes and three Person nodes, and the `DEPENDS_ON`/`OWNED_BY` edges scatter
across them — the chain never connects end to end. KQ1 returns nothing (or a partial chain
that drops the owner). 3A collapses each onto one canonical node so the join closes.

### KQ2 — Temporal contradiction

> *Which currently-active decisions are contradicted by discussions in the last month?*

Traversal: `Message -[:CONTRADICTS]-> Decision`, filtered to `Decision.status = 'active'` and
`Message.created_at` inside the window. `D-0005` ("new integrations stay on legacy-auth
through year-end") is contradicted by a Slack thread ~22 days before `REFERENCE_NOW`
(`@alice`/`@iris`: "new work goes on auth-service now"). **No superseding decision exists** —
the gap is the point. KQ2 surfaces the live decision that the org has informally abandoned.

```cypher
MATCH (m:Message)-[c:CONTRADICTS]->(d:Decision)
WHERE coalesce(d.status,'active') = 'active'
  AND coalesce(m.status,'active') <> 'merged'
  AND m.created_at >= $window_start AND m.created_at <= $as_of
RETURN d, collect({message: m, confidence: c.confidence,
                   said_at: m.created_at, event: c.source_event_id}) AS contradictions
ORDER BY size(contradictions) DESC
```

**Failure mode unresolved**: see §5 — without the Phase-3B Message/CONTRADICTS population
pass there is *no data at all* for this query; the extraction pipeline never emits these
edges. Even with the edges, an unresolved `D-0005` (or a duplicate Decision node split across
its doc and its originating thread) would split the contradiction count and could hide the
active decision behind a `status='superseded'` duplicate.

### KQ3 — Blast radius

> *If the payments service fails, which services, decisions, and people are affected?*

Traversal: walk `DEPENDS_ON` *into* the seed (`(affected)-[:DEPENDS_ON*1..N]->(seed)`), then
expand each affected service to owners (`OWNED_BY`), team members (`MEMBER_OF`), and decisions
(`ABOUT|DEPRECATES`). `payments-api` has a 10-service transitive blast radius and a depth-4
chain (`web-storefront → checkout-service → payments-api → auth-service → user-store`).
"Affected" means *upstream dependents* — direction matters.

```cypher
MATCH (seed:Service {canonical_name: $service_name})
WHERE coalesce(seed.status,'active') <> 'merged'
OPTIONAL MATCH path = (affected:Service)-[:DEPENDS_ON*1..5]->(seed)
WHERE all(n IN nodes(path) WHERE coalesce(n.status,'active') <> 'merged')
WITH seed, collect(DISTINCT affected) AS deps
WITH [seed] + deps AS impacted UNWIND impacted AS svc
OPTIONAL MATCH (svc)-[:OWNED_BY]->(owner) WHERE coalesce(owner.status,'active') <> 'merged'
OPTIONAL MATCH (owner)<-[:MEMBER_OF]-(person:Person)
OPTIONAL MATCH (dec:Decision)-[:ABOUT|DEPRECATES]->(svc) WHERE coalesce(dec.status,'active') <> 'merged'
RETURN collect(DISTINCT svc.canonical_name) AS services,
       collect(DISTINCT dec.id) AS decisions,
       collect(DISTINCT coalesce(person.canonical_id, owner.canonical_id)) AS people
```

**Failure mode unresolved**: the look-alike trap. `notifications-api` (a request-accepting
API) and `notification-worker` (a delivery worker) are *different* services; a careless merge
folds them and corrupts the blast radius. 3A's Tier-2 adjudicator was specifically validated
to keep them apart. Conversely, an unmerged `billing-v2`/`legacy-billing` *splits* one service
in two and under-counts the radius. KQ3's answer is only correct on the resolved graph.

### KQ4 — Provenance + change tracking

> *What changed about the auth system in the last quarter, and who approved each change?*

Traversal: `Decision -[:ABOUT|DEPRECATES]-> auth-service`, filtered to `valid_from` inside the
quarter, with `APPROVED_BY` for attribution and `SUPERSEDES` to render the timeline. Four
decisions fall in the window: D-0006 (85d), D-0007 (60d), D-0008 (45d), D-0010 (25d), with
D-0010 superseding D-0004.

```cypher
MATCH (sys {canonical_name: $target_name})
WHERE (sys:System OR sys:Service) AND coalesce(sys.status,'active') <> 'merged'
MATCH (d:Decision)-[:ABOUT|DEPRECATES]->(sys)
WHERE coalesce(d.status,'active') <> 'merged'
  AND d.valid_from >= $window_start AND d.valid_from <= $as_of
OPTIONAL MATCH (d)-[:APPROVED_BY]->(approver:Person) WHERE coalesce(approver.status,'active') <> 'merged'
OPTIONAL MATCH (d)-[:SUPERSEDES]->(old:Decision)
RETURN d, collect(DISTINCT approver.canonical_id) AS approvers, collect(DISTINCT old.id) AS supersedes
ORDER BY d.valid_from DESC
```

**Failure mode unresolved**: approver attribution collapses. Ben Smith approves early decisions
as `@bsmith` and later ones as `@ben`; Alice appears as `Alice Chen`/`@alice`/`Al`. Without
3A merging these, the same human shows up as several approvers and the "who approved each
change" answer fragments. KQ4 also depends on temporal enrichment (next section): without
`valid_from` populated, the quarter filter has nothing to compare against.

---

## 2. Temporal model

The schema reserves `valid_from`/`valid_to`/`status` on `Decision` (1B), but extraction never
populates the dates — a Decision node lands with at most a `status` *property string* the LLM
copied from the doc header. Phase 3B's **temporal enricher** (`backend/app/temporal/`) fills
the reserved fields from authoritative provenance.

- **`valid_from`**: the `created_at` of the *earliest* source event in the Decision's
  `source_event_ids`. A decision's effect date is when it was issued, and the issuing event's
  timestamp is the ground-truth issue date (the synthetic generator dates each decision-record
  doc by `age_days` before `REFERENCE_NOW`). We read the Postgres `events` rows by UUID and
  take the min `created_at`.
- **`valid_to`**: `NULL` by default (still in force). Set to the *superseding* decision's
  `valid_from` when a `SUPERSEDES` edge points at this decision.
- **`status`**: `'active'` unless a newer decision supersedes it, in which case `'superseded'`.
  (`'rejected'` is reserved but unused by the synthetic corpus.) The enricher never overwrites
  `'merged'` — a tombstoned duplicate keeps its 3A status.

### `as_of` — evaluating "last month" / "last quarter"

KQ2 and KQ4 windows are relative to *now*. But the corpus is anchored to a fixed
`REFERENCE_NOW = 2026-06-01`; if a query used `datetime.now()`, "last month" would land months
past the data and the recent tail the generator deliberately placed at 16–22 days would fall
outside the window forever. Every temporal query therefore takes `as_of: datetime | None = None`
that **defaults to `synthetic.REFERENCE_NOW`** for dev/eval and can be overridden in
production. `window_start = as_of - window`. This is the Phase-2A open question, resolved here
([ADR 0016](../decisions/0016-temporal-query-model.md)).

### Supersession (`SUPERSEDES`)

graph-schema open question #5 deferred a dedicated `SUPERSEDES` edge; Phase 3B pulls it forward
because KQ4's timeline reads naturally with it and the enricher needs a graph-native signal to
set `valid_to`/`status`. `SUPERSEDES` is added to the closed `RelationshipType` vocabulary
(`Decision -> Decision`). The extractor cannot emit it (the supersession signal is free text in
the decision body — "supersedes D-0004"), so `supersession.py` derives it: it reads each
Decision's source-event text from Postgres, matches the `supersedes D-####` signal, and writes
`(newer)-[:SUPERSEDES]->(older)` idempotently, then sets `older.status='superseded'` and
`older.valid_to = newer.valid_from`. Deriving from authoritative source text (not an LLM guess)
keeps the eval deterministic.

---

## 3. Multi-source consolidation for Decisions

A Decision is asserted by both a decision-record doc and the Slack thread that originated it.
Extraction keys Decisions on the id the text names (`D-0006`), so when both sources name the id
they already `MERGE` onto one node — good. But informal decisions, or sources that paraphrase
without the id, can produce a second Decision node (`"the JWT cutover decision"` vs `D-0010`).
Phase 3A's resolver handles identity-bearing entities (Person/Service) but skips the
content-bearing case.

`backend/app/resolution/consolidator.py` extends the **same `MERGE_INTO` mechanism** to
Decisions so the audit trail is uniform:

- **Detect**: for each pair of un-merged Decision nodes, an exact `id` match is a Tier-1
  auto-consolidate; otherwise embed `title + body` with the same local `bge-small` model from
  3A and consolidate when cosine ≥ **0.85** — a *higher* threshold than the 0.75 entity floor,
  because the signal is content similarity, not stable identity, and false content-merges
  silently corrupt KQ2/KQ4. Temporal proximity (`|valid_from_a − valid_from_b| ≤ 30d`) is a
  corroborating gate so two unrelated decisions that happen to read alike are not merged.
- **Merge**: reuse `MERGE_INTO` + `status='merged'` + `source_event_ids` union (3A's `Merger`),
  so a consolidated Decision carries both sources' provenance and queries see it via the same
  `status <> 'merged'` filter.
- **Audit**: write a `merge_decisions` row with `node_type='Decision'` and a new decision enum
  value `content_merge` (Alembic `0003`). [ADR 0017](../decisions/0017-multi-source-decision-consolidation.md).

This differs from entity resolution: Persons/Services have stable keys (email, handle, slug);
Decisions do not, so the discriminating signal is the body embedding + temporal proximity, and
the threshold is deliberately stricter.

---

## 4. Provenance shape

Every KQ answer must tie back to the events that justify it — that is the demo. We use a
uniform annotated-result type ([ADR 0018](../decisions/0018-query-result-provenance.md)):

```python
@dataclass(frozen=True)
class QueryResult(Generic[T]):
    value: T
    provenance: QueryProvenance  # event_ids keyed by graph element + a flat union
```

`QueryProvenance` maps a stable element key (e.g. `"edge:DEPRECATES:D-0006->legacy-auth"`,
`"node:Decision:D-0006"`) to the list of Postgres event UUIDs that asserted it, plus an
`all_event_ids` flat set for quick validation. Provenance is **structural, not optional**:
every query populates it, and the eval validates that each id exists in the Postgres `events`
table. Per query:

- **KQ1**: the events for each edge in the chain (`DEPRECATES`, `DEPENDS_ON`, `OWNED_BY`) —
  every edge carries `source_event_id` from the writer.
- **KQ2**: the active decision's node events + each contradicting message's `CONTRADICTS` edge
  event.
- **KQ3**: the dependency-chain edge events for the impact set.
- **KQ4**: each decision's node events + the `APPROVED_BY` and `SUPERSEDES` edge events.

---

## 5. Contradiction + Message population (KQ2 data path)

The extraction prompt emits only 6 of the 9 edge types (`DEPENDS_ON`, `OWNED_BY`, `MEMBER_OF`,
`DEPRECATES`, `ABOUT`, `APPROVED_BY`); it never emits `CONTRADICTS`/`AUTHORED`/`MENTIONS`, and
**no component creates `Message` nodes**. So KQ2 has no data until Phase 3B builds it
(`backend/app/contradiction/`), resolving graph-schema open question #1.
[ADR 0019](../decisions/0019-contradiction-message-population.md).

- **`message_ingest.py`** — mechanically creates one `:Message` node per `slack_message` event
  (`id = "slack:<external_id>"`, `content`, `created_at = event.created_at`,
  `source_event_ids=[event_id]`), idempotent `MERGE` on `id`. Messages are not extracted;
  they mirror events one-to-one (graph-schema "Message" note).
- **`detector.py`** — candidate (Message, Decision) pairs are generated where a recent message
  (within the contradiction window of `as_of`) names a decision id *or* the subject the decision
  is `ABOUT`/`DEPRECATES`. Each candidate is adjudicated by the existing `OpenRouterClient`
  (claude-3.5-haiku, the 3A adjudicator model) with a focused verbatim prompt returning
  `{contradicts: bool, confidence, reasoning}`. A positive verdict writes
  `(m)-[:CONTRADICTS {confidence, extracted_by, source_event_id}]->(d)`. With no client
  configured the pass is a no-op (KQ2 returns empty) — the same conservative fallback the
  resolver uses.

This is a *detection job*, not extraction: it runs after extraction/resolution, is on-demand,
and is the dedicated contradiction pass the schema always anticipated.

---

## 6. MERGE_INTO chains at query time — the edge-projection cleanup

Phase 3A found 21 transitive `A → B → C` merge chains. The post-3A HANDOFF *hoped*
`WHERE n.status <> 'merged'` would suffice because every intermediate node is tombstoned —
but **that assumption does not hold as written**, and verifying it for every KQ surfaced why:
3A's merger is *non-destructive* (`MERGE_INTO` + tombstone) and **does not migrate the loser's
schema edges onto the winner**. The structural edges (`DEPENDS_ON`/`OWNED_BY`/`MEMBER_OF`/...)
are written by extraction on whichever surface form the text used; if that form later loses
resolution, its edges are stranded on a tombstoned node a `status <> 'merged'` query cannot see
(e.g. the `MEMBER_OF` edge that connects Diego to the payments team could be orphaned, breaking
KQ1). HANDOFF open question #4 explicitly left this to 3B: "follow `MERGE_INTO` transitively, or
a one-pass chain-collapse cleanup."

We chose the **one-pass cleanup**: `backend/app/resolution/projection.py` runs after resolution
and consolidation and, for every schema edge whose endpoints are not already canonical, `MERGE`s
an equivalent edge between the canonical winners (following `MERGE_INTO*` to each chain head).
The originals stay on the tombstoned losers, so resolution stays reversible; queries see only the
projected edges. This keeps the KQ Cypher simple — every KQ then operates purely on the resolved
view with `WHERE n.status <> 'merged'` and never traverses `MERGE_INTO` itself. The cleanup is
APOC-free (one statement per edge type, label from the closed vocabulary) so it runs on the
testcontainer Neo4j image too. A unit test seeds a winner+loser with the edge on the loser and
asserts projection makes it reachable from the winner.

---

## 7. Performance considerations

- **Seeds are constraint-backed point lookups** — `Decision.id`, `Service.canonical_name`,
  `System.canonical_name` are uniqueness constraints (1B), so KQ1/KQ3/KQ4 start from an
  index hit, not a scan.
- **Temporal filters need range indexes** — `Decision.valid_from`, `Decision.status`, and
  `Message.created_at` get b-tree indexes (added in this phase's Cypher migration) so the
  KQ2/KQ4 window filters are index-served, not full scans.
- **KQ3 is the scaling risk.** `DEPENDS_ON*1..5` is bounded variable-length traversal; worst
  case is exponential in fan-in. At synthetic scale (12 services) it is trivial. On 10K
  services the fix is (a) keep the hop bound, (b) `WITH DISTINCT` early to collapse the frontier
  (done), and (c) precompute a materialised reachability/closure table refreshed on write —
  named future work, not built here. The `max_depth` parameter is the tunable safety rail.
- Per-query cost is dominated by Cypher round-trips, all O(result size) at this scale.

---

## 8. Eval methodology

`backend/app/eval/query_eval.py` is an **integration eval**: it runs the whole pipeline —
wipe Neo4j → seed events (synthetic.seeder) → extract (Phase 2B) → resolve entities (3A) →
consolidate Decisions (3B) → project edges (3B) → enrich temporal (3B) → populate
Messages/CONTRADICTS (3B) → run each KQ → compare to expected. (Temporal enrichment precedes
contradiction detection so the detector filters on normalised decision statuses, not raw
extraction output — a real ordering bug the first live run caught.) Even one wrong answer fails the demo, so the eval tests the full
chain, not isolated layers. Expected answers are hand-derived from `narrative.py` (the same
single-source-of-truth discipline as 2B/3A, ADR 0013); **partial credit is not allowed**:

| KQ | Seed | Expected |
|----|------|----------|
| KQ1 | `decision_id=D-0006` | owner includes `diego-ramirez`; chain length 4 (`D-0006 → legacy-auth → payments-api → payments → diego-ramirez`) |
| KQ2 | `window=30d`, `as_of=REFERENCE_NOW` | ≥1 contradiction; `D-0005` present |
| KQ3 | `service=payments-api` | blast radius ≥ 10 services; includes a depth-4 chain member (`web-storefront`) |
| KQ4 | `target=auth-service`, `window=90d` | ≥4 decisions {D-0006, D-0007, D-0008, D-0010}; approvers match `company.py` |

Each result's provenance event IDs are validated against Postgres.

**Stochastic extraction.** Phase 2B measured gemini-2.5-flash-lite at 0.57 relation F1 on the
worst metric; any single extraction run may drop an edge. The eval pipeline therefore uses
**claude-3.5-haiku** (the highest-F1 model in the 2B comparison, 0.78 relation F1) rather than
the cheaper default, trading a few cents for a reliable demo. If a KQ still fails on a given
run, the report records the missing edge and which extraction event omitted it. (We do not
add majority-vote extraction; haiku's F1 plus the structural redundancy of the corpus — every
KQ edge is asserted in ≥1 doc *and* reinforced in Slack — is sufficient at this scale.)

---

## 9. What's deferred

- **Natural-language query input** — the agent that routes a question to a KQ is Phase 4A.
- **Query optimisation / caching / precomputed reachability** — Phase 3C / production.
- **Bitemporal validity** (transaction vs valid time) — out of scope (graph-schema temporal
  model); we keep a single validity axis.
- **`AUTHORED`/`MENTIONS` population** — only `CONTRADICTS` is populated in 3B (KQ2 needs it);
  the other two Message edges remain reserved schema slots.
- **The React force-graph visualisation** — Phase 3C/4B.
- **Open-world contradiction detection** — the detector is gated to the synthetic corpus's
  decision subjects; general contradiction mining is not claimed.

---

## Related ADRs

- [ADR 0016](../decisions/0016-temporal-query-model.md) — `as_of` convention, `valid_from/to`, and the `SUPERSEDES` edge for decision lifecycle
- [ADR 0017](../decisions/0017-multi-source-decision-consolidation.md) — Decision consolidation: why a Decision mentioned in multiple events needs deduplication
- [ADR 0018](../decisions/0018-query-result-provenance.md) — `QueryResult` provenance shape: structural provenance, not optional metadata
- [ADR 0019](../decisions/0019-contradiction-message-population.md) — Why contradiction detection and Message population run as a separate post-resolution pass
