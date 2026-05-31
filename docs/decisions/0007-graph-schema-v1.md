# ADR 0007 — Graph Schema v1

## Status

Accepted

## Context

Phase 1B must lock the Neo4j graph schema for Company Brain. The schema drives every later phase — extraction (Phase 2), the query engine (Phase 3), and the agent (Phase 4) — so its node labels and relationship types are expensive to change once data exists. The forcing constraint is the four **locked killer queries** (`CLAUDE.md`): the schema's only job is to make those four queries natural, correct, and index-served. A schema that is generically "complete" but makes a killer query awkward is wrong. The long-form rationale, including each killer query written as validated Cypher, lives in [`docs/design/graph-schema.md`](../design/graph-schema.md); this ADR is the durable summary.

## Decision

A **closed set of 6 node labels and 9 relationship types**, designed backward from the killer queries, with confidence-on-edges, validity-interval temporal modelling on `Decision`, and property-based provenance into Postgres.

## Alternatives Considered

### Option A — Generic "enterprise knowledge" schema

**What it is**: model everything an org has — `Project`, `Channel`, `Repository`, `Incident`, `Tag`, plus the obvious entities — for future-proofing.

**Pros**:
- Anticipates queries we have not written yet.
- Looks impressively complete.

**Cons**:
- Most labels are traversed by no killer query, so they are untested dead weight that complicates extraction, write-path, and resolution for zero demo value.
- Violates the project's scope-honesty value: entity types are closed and minimal.

### Option B — Single `Component` label with a `kind` property (vs. distinct `Service`/`System`)

**What it is**: collapse `Service` and `System` into one label discriminated by `kind`, making `DEPENDS_ON` homogeneous.

**Pros**:
- Cleanest possible variable-length traversal for blast radius (KQ3).
- Avoids forcing the extractor to classify a fuzzy service/system boundary.

**Cons**:
- KQ1 — the flagship query — explicitly distinguishes the deprecated `System` from the dependent `Service`; collapsing them makes that traversal read as a self-referential `kind` filter instead of a typed path.
- Loses a demo-relevant semantic (decisions deprecate *systems*; *services* own and depend).

### Option C — 6 labels / 9 edges, backward-designed (chosen)

**What it is**: `Service`, `System`, `Person`, `Team`, `Decision`, `Message`; edges `DEPENDS_ON`, `OWNED_BY`, `MEMBER_OF`, `DEPRECATES`, `ABOUT`, `APPROVED_BY`, `AUTHORED`, `MENTIONS`, `CONTRADICTS`. Every element is justified by a named killer query or near-term phase.

**Pros**:
- All four killer queries are short, natural, and index-served (proven in the design doc).
- Small enough to reason about, extract into, and resolve.
- `Service`/`System` split makes KQ1 first-class.

**Cons**:
- The `Service`/`System` boundary is a classification burden on extraction and the schema's softest spot.
- `CONTRADICTS` and entity resolution defer real work to later phases.

## Consequences

**Enables**: Direct mapping of all four killer queries to single `MATCH` patterns. Per-edge confidence thresholding at query time. Idempotent re-ingestion via canonical-key `MERGE`. A clean cross-store provenance join (Neo4j `source_event_ids` → Postgres `events`).

**Constrains**: Extraction must classify each component as `Service` or `System`. `CONTRADICTS` must be materialised by a later phase, not computed at query time. Entity resolution (Phase 3) must merge duplicate nodes the v1 write path will create.

**Locked into**: This label/edge vocabulary. Renaming a label or edge after Phase 2 produces data means a data migration, not just a code change.

**At larger scale / in production**: `Project` and `Incident` are the first labels we would add for portfolio and reliability queries; a bitemporal model would replace the single validity axis if audit/regulatory requirements appeared; existence constraints (Enterprise) would enforce required properties at the database rather than only at the Pydantic boundary.

## Interview Defense

> "We designed the schema backward from four locked queries and refused to add anything a query didn't need — six labels, nine edges. The one genuinely hard call was Service versus System: we kept them as separate labels because the flagship ownership query distinguishes the deprecated *system* from the dependent *service*, and that distinction is the whole point of the query. The honest cost is that extraction now has to classify a sometimes-fuzzy boundary — that's the schema's named weak spot, and entity resolution in Phase 3 can reclassify. Confidence lives on edges, not nodes, because the uncertain thing an LLM produces is the *relationship*, not the entity, and nodes get merged across many events so a node-level confidence is undefined."
