# Phase 1B Interview Readiness

Q&A covering the graph schema design (ADR 0007), the migration strategy (ADR
0008), and the Pydantic models. Each answer is deliverable in under 90 seconds.
Honest answers; named weaknesses. Long-form rationale lives in
[`docs/design/graph-schema.md`](../design/graph-schema.md).

---

## Q&A

### 1. Why these six node types and not more or fewer?

Because six is exactly what the four locked killer queries traverse, and nothing in the queries demands a seventh. The queries touch a deprecated *System*, a dependent *Service*, an owning *Person* or *Team*, a *Decision*, and a *Message* — that is the whole set. We designed backward from the queries rather than forward from a generic model of "a company," so every label has to name the query that justifies it. We rejected `Project`, `Channel`, `Repository`, and `Incident` for exactly this reason: each is plausible, but none is traversed by a killer query or required by a near-term phase. Fewer than six would force two distinct roles (e.g. the deprecated asset and the dependent unit) onto one label and make the flagship ownership query read awkwardly. Six is the minimum that keeps every query natural.

### 2. Why is confidence on edges, not nodes?

Because the uncertain thing an LLM extractor produces is the *assertion of a relationship*, not the existence of an entity. That a service called `payments` was mentioned is near-certain; that `checkout DEPENDS_ON payments` is the inferential leap that can be wrong, and that is what we want to score and threshold. There is also a structural reason: nodes get *merged* across many source events during entity resolution, so a single `Person` node aggregates dozens of mentions — a scalar confidence on that node is undefined ("confidence in what, aggregated how?"). An edge, by contrast, is one extracted assertion from one event, so its confidence is well-defined. Edge-level confidence also enables query-time precision control: `WHERE r.confidence > 0.7` trades recall for precision on the relationships actually being traversed, which a node-level score could not do.

### 3. How do you handle the same entity appearing under different names?

Honestly: we mostly don't yet — full entity resolution is Phase 3, and I am not pretending otherwise. The schema *accommodates* eventual merging without performing it now. Each node has a canonical key (`canonical_name` for Service/System/Team, `canonical_id` for Person) that is the merge target. Today the write path keys on the most stable signal available — email for a person if present, else a deterministic hash of the display name, and a slug for service names — so `@alice`, `Alice Chen`, and `alice@company.com` may become two or three nodes if those signals disagree. Phase 3 resolution will rewrite edges onto the surviving canonical node and delete the losers. The important schema property is that nothing we do now makes that merge impossible; the canonical-key design leaves the door open. This is the single biggest honesty caveat in the schema, and I flag it as such.

### 4. How does your schema represent "what was true at time T"? What's the limitation?

With validity intervals on the things that change. Every `Decision` carries `valid_from`, `valid_to` (null means still in force), and a `status` of active/superseded/rejected, so "currently active" is a one-predicate filter. Every relationship that can lapse — `DEPENDS_ON`, `OWNED_BY`, `MEMBER_OF` — carries `created_at` and an optional `deprecated_at`; a removed dependency is not deleted, its `deprecated_at` is set, preserving history. The limitation, named: this is a *single* validity axis, not bitemporal. We can answer "what was actually true on date T" but not "what did we *believe* was true on date T given only what we knew then." Bitemporal modelling — separate transaction time and valid time — is the gold standard for audit systems, but it doubles every temporal property and complicates every query, which is pure overhead for a synthetic demo. We deliberately gave up the "as-we-believed-it" axis.

### 5. Walk me through how killer query 2 (temporal contradiction) executes.

KQ2 asks which currently-active decisions are contradicted by discussions in the last month. The key design move is that contradiction is a *materialised edge* — `(:Message)-[:CONTRADICTS]->(:Decision)` — written by extraction or a detection job, not computed at query time. So the query is: match `(m:Message)-[c:CONTRADICTS]->(d:Decision)`, filter `d.status = 'active'` and `m.created_at >= datetime() - duration({months: 1})`, then collect the contradicting messages per decision. Execution-wise, the `Decision.status` index narrows to active decisions, the `Message.created_at` range index serves the one-month window, and `CONTRADICTS` is a native pointer-follow. The alternative — comparing every message's text against every decision's text at query time — is O(messages × decisions) and has no index to lean on. By paying the contradiction-detection cost once at write time, we turn KQ2 into a cheap filter-and-traverse. How that edge gets populated (inline extraction vs. a dedicated pass) is a deliberately open Phase 2/3 question.

### 6. Why Cypher migrations instead of creating constraints on write?

Because the schema should be a single reviewable artefact, not something scattered across application code. With migrations, the constraints and indexes live in four small numbered `.cypher` files you can read in one sitting and review as a unit; creating them lazily on first write spreads the schema definition across the write path, gives you no single source of truth for "what is the schema," and races under concurrent writers. Migrations also run once at startup with idempotency guaranteed by Cypher's `IF NOT EXISTS` plus a `_Migration` ledger node, so `docker compose up` brings up a fully-constrained graph with no manual step. The cost is a homemade runner we own, but at this scope — six constraints, three indexes — that runner is sixty lines and trivially unit-tested against a mocked driver, which is far less than pulling a JVM tool like neo4j-migrations or Liquibase into a pure-Python stack.

### 7. What happens if extraction produces a relationship between two nodes that don't exist yet?

It depends on the write path's `MERGE` discipline, and this is a real ordering hazard I want to be explicit about. The intended write path (Phase 2E) `MERGE`s both endpoint nodes on their canonical keys *before* creating the edge, so an edge never dangles — if the node isn't there, `MERGE` creates a stub keyed on the canonical identifier, and a later event enriches it with properties. The Pydantic models support this: a `Relationship` only references `source_id` and `target_id` (the canonical keys), not full node objects, so the edge can be asserted independently of when the nodes are fully populated. The risk is a stub node that never gets enriched — a referenced service that no event ever describes. That's acceptable (it's a real "we heard about X but know nothing else" signal) and is cleaned up by entity resolution. What we never do is create an edge to a node by internal Neo4j id, which *would* break under re-ingestion.

### 8. Why are the extraction Pydantic models separate from the migration files?

Because they serve different layers and different lifecycles, and coupling them would be a category error. The migration files are infrastructure: they provision constraints and indexes in Neo4j and run once at startup; they know nothing about extraction. The Pydantic models are application contracts: the extraction pipeline produces them and the write path consumes them; they enforce required fields, value ranges, and the closed relationship vocabulary at the Python boundary, with `frozen=True` and `extra="forbid"`. The migration runner has no business importing a `Service` model, and the `Service` model has no business knowing how the graph is provisioned. They agree on the *contract* — same labels, same required properties — but enforce it at different points: the database enforces uniqueness, Pydantic enforces shape. Keeping them separate means I can evolve the extraction models (add an optional field) without touching migrations, and vice versa.

### 9. If you had to migrate this schema in production with live data, what's your strategy?

The current runner is forward-only, idempotent, and runs in application startup — fine for a demo, not for live multi-instance production. Three changes. First, an advisory lock so exactly one instance runs migrations; today two instances starting together could both attempt the same DDL. Second, separate the migrate step from the deploy step — run migrations as a distinct job before rolling out new application code, so the schema is ready before any instance depends on it. Third, for a *breaking* change (renaming a label, splitting Service/System differently), use an expand-contract pattern: add the new structure, dual-write both shapes, backfill the existing data with an APOC batch job, cut reads over, then drop the old structure in a later migration. I'd also add checksum validation to detect an edited already-applied file. At that point a tool like neo4j-migrations earns its weight; I chose the homemade runner specifically because we're at demo scale.

### 10. What's the single biggest weakness of this schema, and what would you change in v2?

The Service-versus-System boundary. I kept them as separate labels because the flagship ownership query distinguishes the deprecated *system* from the dependent *service*, and that distinction is the point of the query — but the boundary is genuinely fuzzy ("is auth a service or a system?"), and I've pushed that classification burden onto the extractor, where inconsistent calls will create subtly wrong graphs. I mitigated it three ways — the synthetic data we control keeps it coarse, `DEPENDS_ON` accepts a `System` target so a boundary misclassification degrades gracefully instead of breaking traversal, and Phase 3 resolution can reclassify — but it's still the softest spot. In v2, having seen real extractor behaviour, I'd seriously revisit collapsing them into one `Component` label with a `kind` property and modelling "deprecatable" as a lifecycle status rather than a label, which would make `DEPENDS_ON` perfectly homogeneous and remove the classification call entirely. I'd only do it once I had evidence the two-label semantics weren't pulling their weight.

---

## Key Concepts to Whiteboard

1. **Backward-from-queries design**: draw the four killer-query traversal paths; circle every node label and edge type they touch; show that the union is exactly the six labels and nine edges — nothing orphaned, nothing missing.

2. **Confidence on edges**: draw one `Person` node with five `MENTIONS` edges coming in from five messages; ask "what's the node's confidence?" (undefined) vs. "what's each edge's confidence?" (well-defined). That picture *is* the argument.

3. **Validity intervals vs. bitemporal**: draw a `Decision` with `valid_from`/`valid_to` on a single timeline; then draw the bitemporal 2-D grid (transaction time × valid time) and label the quadrant we deliberately gave up.

4. **Materialised `CONTRADICTS` edge**: draw messages and decisions as two columns; show the O(m×n) text-comparison alternative as a full bipartite mesh, then the single pre-computed `CONTRADICTS` edge that replaces it. Cost moves from query time to write time.

5. **Migration idempotency**: draw the `_Migration` ledger node and the `IF NOT EXISTS` guard; trace two runs — first applies and records, second reads the ledger and skips. Show why `docker compose up` is safe to run repeatedly.
