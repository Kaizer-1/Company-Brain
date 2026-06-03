# Company Brain — Graph Schema v1

> **Status**: Locked in Phase 1B. Summarised in [ADR 0007](../decisions/0007-graph-schema-v1.md).
> Migration strategy in [ADR 0008](../decisions/0008-cypher-migration-strategy.md).
> Python representation in [`backend/app/schemas/graph.py`](../../backend/app/schemas/graph.py).

This document is the long-form rationale for the Neo4j graph schema. It is the most consequential design artefact in the project: the schema defined here is locked into `CLAUDE.md` and every later phase — extraction (Phase 2), query engine (Phase 3), agent (Phase 4) — builds on it.

---

## Design Philosophy

The schema is designed **backward from the four killer queries**, not forward from a generic model of "a company." Minimalism is a feature, not a limitation: every node label and every relationship type in this document exists because at least one killer query traverses it, or because a named near-term phase (2A–2E) directly requires it. Nothing is added "because a company has them." If a concept cannot name the query it serves, it does not enter the schema — it goes in the *Out of Scope* section instead. This discipline keeps the graph small enough to reason about, makes every traversal cheap, and means the schema's correctness is *checkable*: we prove it by writing each killer query as Cypher (see the [Killer Queries as Cypher](#the-four-killer-queries-as-cypher) section) and confirming the traversal is natural. A query that is awkward to express is a signal the schema is wrong, and we iterate the schema before writing migrations.

---

## Node Types

Six node labels. This is the complete, closed set (scope honesty: entity types are closed, per `CLAUDE.md`).

### `Service`

A **deployed, running software unit** that has owners and runtime dependencies — the operational atom of the architecture (e.g. `payments-api`, `checkout`, `auth-gateway`).

| Property | Type | Required | Notes |
|----------|------|----------|-------|
| `canonical_name` | `str` | yes, **unique** | Resolved slug; the uniqueness key |
| `id` | `str` | yes | Surrogate; mirrors `canonical_name` for name-keyed nodes |
| `language` | `str \| None` | no | e.g. `"Go"`, `"Python"` |
| `tier` | `"critical" \| "standard" \| "experimental" \| None` | no | Operational criticality |
| `status` | `"active" \| "deprecated"` | yes (default `active`) | Lifecycle, **not** identity |
| `source_event_ids` | `list[str]` | yes | Provenance — see below |
| `created_at` | `datetime` | yes | First-observed time |

**Required by**: KQ1 (the owned, dependent service), KQ3 (blast-radius seed and dependents), KQ4 (a decision can be *about* a service).
**Edge cases**: A service appears in messages as `payments`, `payments-api`, `the payments service`. Normalising these to one `canonical_name` is **entity resolution — Phase 3, not now**. The schema must *accommodate* eventual merging (one node per canonical name) without making it impossible; the write path (Phase 2E) does best-effort slugging until then.

### `System`

A **higher-level named asset or platform** that can be *deprecated by a decision* — the thing architecture decisions act on (e.g. `legacy-auth`, `the monolith`, `v1-billing-platform`). Distinct from `Service`; the distinction is argued in [Service vs. System](#the-service-vs-system-question).

| Property | Type | Required | Notes |
|----------|------|----------|-------|
| `canonical_name` | `str` | yes, **unique** | Uniqueness key |
| `id` | `str` | yes | Mirrors `canonical_name` |
| `status` | `"active" \| "deprecated"` | yes (default `active`) | Set to `deprecated` by a `DEPRECATES` edge |
| `description` | `str \| None` | no | Short human description |
| `source_event_ids` | `list[str]` | yes | Provenance |
| `created_at` | `datetime` | yes | First-observed time |

**Required by**: KQ1 (the deprecated system at the head of the ownership chain), KQ4 (the *auth system* whose change history we reconstruct).

### `Person`

An **individual** — engineer, approver, author, stakeholder.

| Property | Type | Required | Notes |
|----------|------|----------|-------|
| `canonical_id` | `str` | yes, **unique** | Assigned at resolution; uniqueness key |
| `id` | `str` | yes | Mirrors `canonical_id` |
| `display_name` | `str` | yes | Best-known human name |
| `email` | `str \| None` | no | Strong resolution signal when present |
| `source_event_ids` | `list[str]` | yes | Provenance |
| `created_at` | `datetime` | yes | First-observed time |

**Required by**: KQ1 (the owner), KQ3 (affected people), KQ4 (the approver).
**Edge cases**: The classic identity problem — one human appears as `@alice`, `Alice Chen`, `alice@company.com`. We **do not** solve this in Phase 1B. `canonical_id` is the merge target that Phase 3 entity resolution will assign; until then the write path keys on the most stable available signal (email if present, else a deterministic hash of the display name). This is named honestly, not hidden.

### `Team`

An **engineering team** that can own services and contain people.

| Property | Type | Required | Notes |
|----------|------|----------|-------|
| `canonical_name` | `str` | yes, **unique** | Uniqueness key |
| `id` | `str` | yes | Mirrors `canonical_name` |
| `display_name` | `str \| None` | no | e.g. `"Payments Platform"` |
| `source_event_ids` | `list[str]` | yes | Provenance |
| `created_at` | `datetime` | yes | First-observed time |

**Required by**: KQ1 (an owner can be a Team, not just a Person), KQ3 (a team-owned affected service expands to its members).

### `Decision`

A **choice that was made**, with provenance and temporal validity — an ADR or a decision captured in a meeting note. This is the temporal heart of the schema. A `Decision` is *a choice made*; a `System` is *a thing that exists*. The `DEPRECATES` edge is what links the two. They are never the same node.

| Property | Type | Required | Notes |
|----------|------|----------|-------|
| `id` | `str` | yes, **unique** | UUIDv4 generated at extraction; uniqueness key |
| `title` | `str` | yes | Short headline |
| `status` | `"active" \| "superseded" \| "rejected"` | yes | Temporal status |
| `valid_from` | `datetime` | yes | When the decision took effect |
| `valid_to` | `datetime \| None` | no | `None` = still in force |
| `body` | `str \| None` | no | Full decision text |
| `source_event_ids` | `list[str]` | yes | Provenance |
| `created_at` | `datetime` | yes | Extraction/ingestion time |

**Required by**: KQ1 (seed: *Decision X*), KQ2 (the contradicted active decisions), KQ4 (the changes with approvers).

### `Message`

A **Slack-style message** — an atom of discussion. Carries the *discussion* corpus that KQ2 compares against the *decision* corpus.

| Property | Type | Required | Notes |
|----------|------|----------|-------|
| `id` | `str` | yes, **unique** | `f"{source_id}:{external_id}"`; uniqueness key |
| `source_id` | `str` | yes | e.g. `"slack"` |
| `external_id` | `str` | yes | Source-native message id |
| `content` | `str` | yes | Message text |
| `source_event_ids` | `list[str]` | yes | Provenance |
| `created_at` | `datetime` | yes | **Message send time** (the temporal axis KQ2 filters on) |

**Required by**: KQ2 (the recent discussions that contradict decisions), KQ4 (discussion context around a change).
**Edge cases**: Threading, edits, and reactions are **out of scope** — a message is a flat atom. Re-ingesting the same Slack export must not duplicate nodes; the `source_id + external_id` composite key guarantees idempotent upsert.

---

## Relationship Types

Nine relationship types. UPPERCASE, verb-ish, directed. Every edge carries the **extraction metadata** block (`confidence`, `extracted_by`, `created_at`, `source_event_id`) — see [Confidence & Extraction Metadata](#confidence-and-extraction-metadata).

| Type | Source → Target | Extra properties | Cardinality | Killer query |
|------|-----------------|------------------|-------------|--------------|
| `DEPENDS_ON` | `Service` → `Service \| System` | `deprecated_at: datetime?` | N:M | KQ1, KQ3 |
| `OWNED_BY` | `Service \| System` → `Person \| Team` | `deprecated_at: datetime?` | N:1 (typically) | KQ1, KQ3 |
| `MEMBER_OF` | `Person` → `Team` | `deprecated_at: datetime?` | N:M | KQ3 |
| `DEPRECATES` | `Decision` → `System` | — | N:M | KQ1, KQ4 |
| `ABOUT` | `Decision` → `System \| Service` | — | N:M | KQ4 |
| `APPROVED_BY` | `Decision` → `Person` | — | N:M | KQ4 |
| `AUTHORED` | `Person` → `Message \| Decision` | — | 1:N | KQ2, KQ4 |
| `MENTIONS` | `Message` → `Service \| System \| Person \| Team \| Decision` | — | N:M | KQ2 (grounding) |
| `CONTRADICTS` | `Message` → `Decision` | — | N:M | KQ2 |
| `SUPERSEDES` *(3B)* | `Decision` → `Decision` | — | N:M | KQ4 |

Notes on the trickier choices:

- **`DEPENDS_ON` is homogeneous-ish on purpose.** A service depends on another service or on a system. Keeping `Service` as the only *source* means the variable-length blast-radius traversal (`DEPENDS_ON*1..N`) never has to special-case the source label. Targets may be `System` (a service depends on a platform) — Neo4j variable-length matching does not care about intermediate labels, so this stays clean.
- **`DEPRECATES` vs `ABOUT`.** `DEPRECATES` is the *lifecycle* edge (it drives KQ1 and flips `System.status`). `ABOUT` is the neutral *subject* edge (it drives KQ4's change history). A decision that deprecates a system is logically also *about* it, so KQ4 unions both edge types: `-[:ABOUT|DEPRECATES]->`. We keep them as distinct types rather than collapsing, because KQ1 needs the specific `DEPRECATES` semantics and a generic `ABOUT` would over-match (every commentary decision would appear in the deprecation chain).
- **`CONTRADICTS` is a materialised edge, not a query-time computation.** KQ2 asks which active decisions are contradicted by recent discussion. Rather than compare message text to decision text at query time, the schema represents contradiction as an explicit `Message → Decision` edge written by extraction (Phase 2D) or a dedicated detection job (Phase 3B). This turns KQ2 into a cheap filter-and-traverse instead of an O(messages × decisions) text comparison. The *population* of this edge is a later-phase concern; the *schema slot* for it exists now.
- **`MENTIONS` is the weak link; `CONTRADICTS` is the strong one.** `MENTIONS` records "this message references this entity" (low bar, used for grounding). `CONTRADICTS` records "this message logically opposes this decision" (high bar, computed). Both connect `Message` to the graph, at different confidence levels.

---

## The `Service` vs. `System` Question

The trickiest modelling call. Are `Service` and `System` two labels, or one label with a `kind` property?

**Argument for one label (`Component {kind}`):** `DEPENDS_ON` becomes perfectly homogeneous (`Component → Component`), so `DEPENDS_ON*1..N` blast radius and the ownership chain are label-agnostic and maximally simple. The service/system boundary is *genuinely fuzzy* in real orgs ("is auth a service or a system?"), and forcing the extractor to pick one risks inconsistent classification. Entity resolution operates in one namespace. Deprecation is a *lifecycle* concern (`status`), not a *type* concern — modelling it as a label conflates the two.

**Argument for two labels (`Service`, `System`):** KQ1's traversal — `Decision -[:DEPRECATES]-> System <-[:DEPENDS_ON]- Service -[:OWNED_BY]-> Person` — *explicitly distinguishes the two*: the thing that gets deprecated (a `System`) is a different role from the thing that has owners and depends on it (a `Service`). The distinction carries demo-relevant meaning: decisions deprecate platforms/assets; services are the operational units that own and depend. Two labels make that semantics first-class and queryable (`MATCH (s:System)` is an index-backed label scan).

**Decision: two labels.** KQ1 is the project's flagship query and it reads naturally only when the deprecated asset and the dependent unit are distinct types. The honest cost — the extractor must classify each component as Service or System, and the boundary is the schema's softest spot — is mitigated three ways: (1) the distinction is coarse and rarely ambiguous for the synthetic data we control (Phase 2A); (2) `DEPENDS_ON` accepts a `System` *target*, so a misclassification at the boundary degrades gracefully rather than breaking traversal; (3) Phase 3 entity resolution can reclassify. This is recorded as the schema's named weakness (see interview prep Q10).

---

## Temporal Model

The question: *how do we represent "what was true when"?*

**Chosen approach — validity intervals on the things that change:**

- Every `Decision` carries `valid_from: datetime`, `valid_to: datetime | None` (`None` = still in force), and `status ∈ {active, superseded, rejected}`. "Currently active" is `status = 'active'` (equivalently `valid_to IS NULL`). This is what makes KQ2 ("currently-active decisions") and KQ4 ("changes in the last quarter") expressible as simple range filters.
- Every relationship that can lapse — `DEPENDS_ON`, `OWNED_BY`, `MEMBER_OF` — carries `created_at` and an optional `deprecated_at`. A dependency or ownership that was removed is *not deleted*; its `deprecated_at` is set, preserving history for "what was true at time T" without versioning the whole graph.
- `Message.created_at` is the send time, the temporal axis KQ2 filters on.

**Rejected alternatives:**

- **Bitemporal model** (separate *transaction time* — when we recorded a fact — and *valid time* — when the fact was true in the world). This is the gold standard for audit/regulatory systems, but it doubles every temporal property and complicates every query with an extra time dimension. For a synthetic portfolio demo where ingestion time and a best-estimate event time are close enough, it is pure overhead. We keep a *single* validity axis (`valid_from/valid_to`) plus `created_at` as a coarse ingestion marker.
- **Separate temporal/version nodes** (a `Decision` points to immutable `DecisionVersion` snapshots). This is how you model a heavily-edited document with full revision history. Our decisions are append-mostly and superseded-by-new-decision, so `status = superseded` + a new `Decision` node captures the timeline without a second node type per entity. Adding version nodes would roughly double the node count to serve a history depth we do not need at demo scale.

The limitation, named: with a single validity axis we cannot answer "what did we *believe* the dependency graph looked like on date T, given what we knew at the time?" — only "what was actually true on date T." That is the bitemporal capability we deliberately gave up.

---

## Provenance Model

**Requirement:** every node and edge that comes from an ingested event must point back to its source.

Two options were considered:

- **Option A** — every node carries a `source_event_ids: list[str]` property.
- **Option B** — every node has an `EXTRACTED_FROM` edge to a dedicated `SourceEvent` node in Neo4j.

**Chosen: Option A (property-based provenance).** The raw ingested events — a Slack export blob, an ADR markdown file, a meeting-note document — are **immutable records that already live in Postgres** (the `events` ingest log, Phase 1C). Neo4j holds the *distilled* graph; Postgres holds the *raw* provenance. Putting a `SourceEvent` node in Neo4j (Option B) would duplicate, inside the graph, data that the relational store already owns immutably — and it would add a high-degree hub node (every entity edges to it) that pollutes traversals and blast-radius reachability. Instead, `source_event_ids` are **foreign keys into the Postgres `events` table**. To answer "where did this fact come from?", the agent (Phase 4) joins the Neo4j node's `source_event_ids` against Postgres and returns the original text.

**Trade-off, named:** Option A cannot be traversed *inside* Cypher — you cannot write `MATCH (n)-[:EXTRACTED_FROM]->(e)` to walk to sources graph-natively. We accept this because provenance lookups are *terminal* (you fetch the source to display it, you do not traverse *through* it), and because keeping provenance out of the graph topology keeps the killer-query traversals clean. The cross-store join is a Phase 4 concern with a single well-defined shape.

---

## Confidence and Extraction Metadata

Every **relationship** carries:

- `confidence: float` in `[0, 1]` — the extractor's confidence in *this asserted edge*.
- `extracted_by: str` — model name + version (e.g. `"claude-opus-4-8"`), so we can re-evaluate or purge edges from a model later found unreliable.
- `created_at: datetime` and `source_event_id: str` — when and from which event the edge was extracted.

**Why on edges, not nodes:** the uncertain thing in LLM extraction is the **assertion of a relationship**, not the existence of an entity. That a service named `payments` was mentioned is near-certain; that `checkout DEPENDS_ON payments` is the *inferential leap* that can be wrong. Furthermore, nodes are **merged across many events** during entity resolution — a single `Person` node aggregates dozens of mentions, so a scalar confidence on the node is ill-defined (confidence in *what*, aggregated *how*?). An edge, by contrast, is a single extracted assertion from a single event, so confidence is well-defined per edge. This also enables a confidence threshold at query time (`WHERE r.confidence > 0.7`) to trade recall for precision — a per-node confidence could not support that on the *relationships* being traversed.

---

## Uniqueness and Identity

How do we identify "the same" node across ingestions? Each label has a single **canonical identifier** carrying the uniqueness constraint:

| Label | Uniqueness key | How it is computed | Constraint in `001_constraints.cypher` |
|-------|----------------|--------------------|----------------------------------------|
| `Service` | `canonical_name` | slug of the resolved name | `REQUIRE s.canonical_name IS UNIQUE` |
| `System` | `canonical_name` | slug of the resolved name | `REQUIRE s.canonical_name IS UNIQUE` |
| `Team` | `canonical_name` | slug of the resolved name | `REQUIRE t.canonical_name IS UNIQUE` |
| `Person` | `canonical_id` | assigned at resolution (email or hash until then) | `REQUIRE p.canonical_id IS UNIQUE` |
| `Decision` | `id` | UUIDv4 at extraction | `REQUIRE d.id IS UNIQUE` |
| `Message` | `id` | `f"{source_id}:{external_id}"` | `REQUIRE m.id IS UNIQUE` |

The write path (Phase 2E) `MERGE`s on the canonical key, so re-ingestion is idempotent: the same service/message/decision never produces a duplicate node. The Pydantic base carries a uniform `id`; for name-keyed nodes `id` mirrors the canonical name so generic write-path and provenance code can treat every node via `.id`, while the human-readable `canonical_name`/`canonical_id` remains the constrained lookup key the killer queries seed on.

**Entity resolution is Phase 3.** Today, "the same" is best-effort: two spellings of a service name that do not slug identically will become two nodes. The schema *accommodates* eventual merging — resolution rewrites edges onto the surviving canonical node and deletes the loser — without requiring it now. This is the single biggest honesty caveat in the schema and is named as such.

---

## The Four Killer Queries as Cypher

This section **proves the schema works**. Each query below is the actual Cypher that answers it, annotated with the index/constraint that makes it fast. These were written *before* finalising the schema; the schema above is the result of iterating until each reads cleanly.

### KQ1 — Multi-hop ownership

> *Who owns the service that depends on the system deprecated by Decision X?*

```cypher
MATCH (d:Decision {id: $decision_id})-[:DEPRECATES]->(sys:System)
MATCH (svc:Service)-[:DEPENDS_ON]->(sys)
MATCH (svc)-[:OWNED_BY]->(owner)
RETURN d.title              AS decision,
       sys.canonical_name   AS deprecated_system,
       svc.canonical_name   AS dependent_service,
       labels(owner)[0]     AS owner_type,
       coalesce(owner.canonical_name, owner.canonical_id) AS owner
```

**Fast because:** the seed `(:Decision {id})` is a point lookup on the `Decision.id` **uniqueness constraint** (constraint-backed index); every subsequent hop is a native pointer-follow. To expand a `Team` owner to its people, append `OPTIONAL MATCH (owner)<-[:MEMBER_OF]-(p:Person) WHERE owner:Team`.

### KQ2 — Temporal contradiction

> *Which currently-active decisions are contradicted by discussions in the last month?*

```cypher
MATCH (m:Message)-[c:CONTRADICTS]->(d:Decision)
WHERE d.status = 'active'
  AND m.created_at >= datetime() - duration({months: 1})
RETURN d.id    AS decision_id,
       d.title AS decision,
       collect({
         message_id: m.id,
         said_at:    m.created_at,
         confidence: c.confidence
       }) AS contradicting_discussions
ORDER BY size(contradicting_discussions) DESC
```

**Fast because:** the `Decision.status` index narrows to active decisions; the `Message.created_at` **range index** serves the one-month window; `CONTRADICTS` is a pre-materialised edge, so the query is a filter-and-traverse, never a text comparison. *This is the design choice that makes KQ2 cheap* — see the `CONTRADICTS` note above.

### KQ3 — Blast radius

> *If the payments service fails, which services, decisions, and people are affected?*

```cypher
MATCH (seed:Service {canonical_name: $service_name})
OPTIONAL MATCH (affected:Service)-[:DEPENDS_ON*1..5]->(seed)
WITH seed, collect(DISTINCT affected) AS deps
WITH [seed] + deps AS impacted
UNWIND impacted AS svc
OPTIONAL MATCH (svc)-[:OWNED_BY]->(owner)
OPTIONAL MATCH (owner)<-[:MEMBER_OF]-(person:Person)
OPTIONAL MATCH (dec:Decision)-[:ABOUT|DEPRECATES]->(svc)
RETURN collect(DISTINCT svc.canonical_name) AS affected_services,
       collect(DISTINCT dec.id)             AS affected_decisions,
       collect(DISTINCT coalesce(person.canonical_id, owner.canonical_id)) AS affected_people
```

**Fast because:** the seed is a point lookup on the `Service.canonical_name` **uniqueness constraint**; the variable-length traversal is **bounded `*1..5`** to prevent exponential blow-up on a dense dependency graph (the bound is a tunable safety rail, not a semantic limit). Direction matters: we walk `DEPENDS_ON` *into* the seed, so "affected" = upstream dependents of payments.

### KQ4 — Provenance + change tracking

> *What has changed about the auth system in the last quarter, and who approved each change?*

```cypher
MATCH (sys {canonical_name: $system_name})
WHERE sys:System OR sys:Service
MATCH (d:Decision)-[:ABOUT|DEPRECATES]->(sys)
WHERE d.valid_from >= datetime() - duration({months: 3})
OPTIONAL MATCH (d)-[:APPROVED_BY]->(approver:Person)
RETURN d.id         AS decision_id,
       d.title      AS change,
       d.status     AS status,
       d.valid_from AS effective_date,
       collect(DISTINCT approver.canonical_id) AS approved_by
ORDER BY d.valid_from DESC
```

**Fast because:** the `canonical_name` uniqueness constraints serve the seed; the `Decision.valid_from` **range index** serves the quarter window; the `ABOUT|DEPRECATES` union captures both neutral-subject and lifecycle changes in one traversal; `APPROVED_BY` attributes each change to its approver.

All four queries are natural, short, and index-served. The schema is validated.

---

## What's Out of Scope, Deliberately

Naming non-decisions is as important as naming decisions. The following were considered and **rejected for v1** — none is traversed by a killer query or required by a near-term phase:

- **`Project`** — *considered seriously.* A project would group services and decisions for portfolio rollups. But no killer query traverses it, and the synthetic generator (Phase 2A) produces Services/Persons/Decisions/Messages, not Projects. It would be the **first** addition if we ever needed "what's the status of project X?" — a plausible v2 query — but adding it now would be speculative. Rejected, with a clear re-entry path.
- **`Channel`** — a Slack channel grouping messages. No killer query filters by channel; `Message.source_id` plus a future property would suffice if needed. Rejected.
- **`Repository` / `PullRequest` / `Commit`** — code-level provenance. Interesting, but the project ingests *messages, decisions, and notes*, not VCS history. Out of corpus scope. Rejected.
- **`Tag` / `Label`** — free-form categorisation. Premature; a property on the node serves any near-term need. Rejected.
- **`Incident`** — would make blast radius (KQ3) richer ("which incident touched payments?"). Genuinely tempting, but KQ3 is about *structural* reachability, not incident history, and no corpus source produces incidents. Rejected; noted as a v2 candidate alongside `Project`.

---

## Open Schema Questions for Phase 2+

Decisions that genuinely cannot be made without writing the extraction prompts first:

1. ~~**How is `CONTRADICTS` populated?**~~ **Resolved in Phase 3B (ADR 0019):** by a dedicated contradiction-detection pass (`backend/app/contradiction/`) run after extraction/resolution — not the inline extractor. It also creates the `Message` nodes (mechanically, one per Slack event), which nothing produced before. The edge carries `confidence`/`extracted_by`/`source_event_id` like any extracted edge; no `detection_method` property was needed.
2. **`DEPENDS_ON` target discipline.** Should a service ever depend on a `Person`/`Team` (an organisational dependency), or strictly on `Service`/`System`? Held to structural targets for now; revisit if extraction surfaces org dependencies.
3. **Confidence calibration.** What threshold separates a kept edge from a dropped one? Cannot be set until we see real extractor confidence distributions (Phase 2D).
4. **Multi-valued ownership.** `OWNED_BY` is modelled N:1 in the common case but allowed N:M. Do we need a `primary: bool` property to disambiguate the owner-of-record? Deferred until the generator (Phase 2A) shows how often co-ownership occurs.
5. **`Decision` supersession chain.** ~~Should a superseding decision link to the one it replaces via a `SUPERSEDES` edge?~~ **Resolved in Phase 3B (ADR 0016):** `SUPERSEDES` (`Decision -> Decision`) is now part of the closed vocabulary. KQ4's change timeline renders the supersession, and the temporal enricher uses the edge to set the superseded decision's `status='superseded'` and `valid_to`. The edge is derived (not extracted) from the decision body's "supersedes D-####" signal — see `backend/app/temporal/supersession.py`.
