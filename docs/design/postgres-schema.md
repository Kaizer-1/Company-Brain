# Postgres Schema Design — Company Brain

> **Status**: Locked in Phase 1C. Do not modify table shapes without a new ADR.

**What this doc is.** This document describes the three Postgres tables that form the raw-event log, the embedding store, and the audit backbone for Company Brain. The graph (Neo4j) gets the query surface; Postgres gets everything that needs transactional guarantees, append-only semantics, or pgvector HNSW indexing. Read this to understand why `events` is immutable, what `event_embeddings` stores separately from `events`, and how the `extraction_runs` table enables failure detection and model-upgrade auditing.

---

## Design Philosophy

Two principles drive every column and constraint in this schema.

### Principle 1: Postgres is the Immutable Raw-Event Log

Every piece of company knowledge that enters Company Brain — a Slack-style message, an architecture decision record, a meeting note — becomes an `event`. Events are **append-only**. Once an event row is inserted, its `content` and `source_metadata` columns are never updated. If we later discover that the extraction logic misread the content, we re-run extraction (producing new graph nodes) rather than patching the original event. This is not just a convention enforced by application code — it is the semantic contract that makes the rest of the system coherent.

Why immutability? Because the `events` table is the provenance anchor for the entire knowledge graph. Every Neo4j node produced by the extraction pipeline carries a `source_event_ids` property: a list of UUIDs pointing into this table. If an event row could silently change its `content` after graph nodes had already been derived from it, those nodes would be silently lying about their provenance. The graph's claim "this knowledge came from event X" would be unfalsifiable. Immutability gives that claim meaning.

If correction is needed — for example, a document was ingested with encoding errors — the correct workflow is: fix the source, ingest again (which creates a *new* event with a new UUID and a different content hash), re-run extraction, and optionally deprecate the old graph nodes by tagging them with the replacement event's UUID. The old event stays in the table, unchanged, as a permanent record of what was ingested.

### Principle 2: The `events` Table Is the Foreign-Key Target for Every Graph Node's `source_event_ids`

The Neo4j graph and Postgres do not share a database engine, so cross-store foreign keys cannot be enforced by the database itself. Instead, they are enforced **by the extraction pipeline** (which writes the UUID into the graph only after the event row exists) and verified **by the provenance reconciliation check** in `backend/scripts/check_provenance.py` (Phase 4). The events table's stable, opaque UUIDs are the bridge between the two stores. Nothing in the graph layer needs to know what source type produced an event — it just needs to hold the UUID.

This design intentionally refuses to put raw events in the graph. Storing events as Neo4j nodes would couple the graph schema to source-system specifics (Slack channel IDs, document paths, etc.) and pollute graph traversals with non-entity data. The two-store split keeps the graph clean and the relational store authoritative.

---

## Tables

### `events` — The Core Raw-Event Log

This is the most important table in the Postgres schema. It is the source of truth for what raw knowledge Company Brain has ever ingested.

| Column | Type | Constraints | Purpose |
|--------|------|-------------|---------|
| `id` | `UUID` | PRIMARY KEY, not null, default `gen_random_uuid()` | Stable opaque identifier referenced by graph nodes' `source_event_ids` |
| `source_type` | `sourcetype` (Postgres enum) | not null | Discriminates the source system: `doc` or `slack_message`. Extensible via schema migration |
| `source_external_id` | `text` | not null | The ID used by the source system (e.g., a Slack message timestamp+channel, a document path) |
| `content` | `text` | not null | The full raw text of the event. Never truncated, never mutated after insert |
| `source_metadata` | `jsonb` | not null, default `'{}'` | Arbitrary source-specific metadata: channel name, author email, document version, etc. |
| `created_at` | `timestamptz` | not null | Timestamp from the source system — when the event was created in the origin |
| `ingested_at` | `timestamptz` | not null, default `now()` | When Company Brain ingested this event. Monotone, set at insert time |
| `content_hash` | `text` | not null | SHA-256 hex digest of `content`. Used to detect duplicate content across source types |

**Constraints**:
- `UNIQUE (source_type, source_external_id)` — prevents double-ingestion of the same event from the same source. Attempting to ingest a known `(source_type, source_external_id)` pair raises `IntegrityError` at the DB layer, so the ingestion pipeline can detect it cleanly without a prior SELECT
- `INDEX ON content_hash` — enables the `get_by_content_hash` lookup used to detect near-duplicate content (e.g., the same Slack message appearing in two channels or a document copy)
- `INDEX ON created_at` — supports `list_since(timestamp)` queries that feed the temporal contradiction query (Killer Query 2)

**Why `id` is generated, not derived**: The event's ID is intentionally opaque. It is not derived from the source ID or the content hash because we want the event's identity to be stable even if we discover the source ID scheme was wrong. Graph nodes hold this UUID forever; it must never need to change.

**Why both `created_at` and `ingested_at`**: `created_at` reflects the source system's notion of time (when the Slack message was posted; when the document was stamped). `ingested_at` reflects the pipeline's notion of time. For temporal queries ("decisions made in Q1"), we filter on `created_at`. For operational queries ("events we ingested in the last hour"), we filter on `ingested_at`. Conflating these would corrupt the temporal queries that are the project's centrepiece.

---

### `event_embeddings` — One Embedding Per Event (Per Model)

Embeddings are derived from event content but are expensive to compute and potentially produced by multiple model versions over the project's life. Separating them from the `events` table gives us three benefits: (1) inserting an event does not block on embedding computation; (2) we can re-embed all events with a new model without touching the events table; (3) we can store multiple embeddings per event in the future without altering the events table schema.

| Column | Type | Constraints | Purpose |
|--------|------|-------------|---------|
| `event_id` | `UUID` | PRIMARY KEY, FK → `events.id` ON DELETE CASCADE | 1:1 relationship (one embedding per event in v1) |
| `embedding` | `vector(1536)` | not null | The embedding vector. 1536 dimensions for text-embedding-3-small (OpenAI) and text-embedding-ada-002 |
| `model_name` | `text` | not null | e.g., `"text-embedding-3-small"` |
| `model_version` | `text` | not null | e.g., `"2024-02-01"`. Allows us to distinguish model vintages |
| `created_at` | `timestamptz` | not null, default `now()` | When this embedding was computed |

**Index on `embedding`**: HNSW using `vector_cosine_ops`. See the index rationale below.

**ON DELETE CASCADE**: If an event is ever deleted (which should not happen under the immutability contract, but the database cannot enforce that), its embedding is automatically removed. Stale embeddings pointing at non-existent events are worse than no embeddings.

**Why `event_id` is the primary key**: In v1 there is exactly one embedding per event. Using `event_id` as PK expresses this constraint at the database level. If a future phase requires multiple embeddings per event (e.g., chunk-level embeddings for long documents), this schema will need to evolve — but that is an explicit Phase 3+ concern.

**Dimension 1536**: Text-embedding-3-small produces 1536-dimensional vectors, which is also the dimension of the widely-used text-embedding-ada-002. Both are plausible model choices for Phase 3D. Fixing the dimension in the schema is a commitment; it is the right one given the model lineup.

---

### `extraction_runs` — Audit Table for Every Extraction Pass

The extraction_runs table is the operational memory of the extraction pipeline. Every time the extraction pipeline processes an event — whether that produces graph nodes or fails — a row is inserted here. This enables several capabilities that would otherwise require reading the graph or re-running the pipeline:

- **Re-extraction tracking**: know which events have been processed by which model version
- **Failure replay**: identify events whose extraction failed and retry them
- **Model upgrade workflow**: find all events extracted with an old model and queue them for re-extraction
- **Audit**: answer "when did extraction of this event complete, and what did it produce?"

| Column | Type | Constraints | Purpose |
|--------|------|-------------|---------|
| `id` | `UUID` | PRIMARY KEY, default `gen_random_uuid()` | Unique identifier for this run |
| `event_id` | `UUID` | not null, FK → `events.id` | Which event was being processed |
| `model_name` | `text` | not null | e.g., `"claude-opus-4"` |
| `model_version` | `text` | not null | Model version or snapshot ID |
| `prompt_hash` | `text` | not null | SHA-256 of the exact prompt used. Enables detecting when prompt changes require re-extraction |
| `started_at` | `timestamptz` | not null | When extraction was initiated |
| `completed_at` | `timestamptz` | nullable | Set on success or failure; null while in-flight |
| `status` | `extractionstatus` (Postgres enum) | not null, default `'failed'` | `success`, `failed`, or `partial` (partial = some nodes extracted, then error) |
| `extracted_node_count` | `integer` | not null, default `0` | How many graph nodes were produced |
| `extracted_edge_count` | `integer` | not null, default `0` | How many graph edges were produced |
| `error_message` | `text` | nullable | Error detail if status is `failed` or `partial` |

**Index on `(event_id, started_at)`**: supports `latest_for_event(event_id)` — the most common access pattern, which asks "what was the most recent extraction attempt for this event?"

**No FK cascade on delete**: unlike embeddings, extraction run records are audit data. If an event were ever deleted, we want the extraction run history to survive as a forensic record. This is a deliberate deviation from the embedding table.

---

## Why Two Tables for Events and Embeddings

The single most common question about this schema is why events and embeddings are not combined into one table. Three reasons:

1. **Hot path isolation**: Every ingest operation creates an event row. Not every ingest operation immediately creates an embedding — embedding computation is expensive (~100ms per call), asynchronous, and may be batched. A fat `events_with_embeddings` table would mean every ingest either blocks on embedding computation or writes a row with a null embedding column. The separate table makes the ingest path fast and the embedding lifecycle explicit.

2. **Re-embedding without event mutation**: When a new embedding model is released, we want to replace all embeddings without touching the events table. With a separate table, `DELETE FROM event_embeddings; <recompute and insert>` is clean and safe. With a combined table, re-embedding means an `UPDATE` on the events table — which violates the immutability contract and makes the history of the content ambiguous.

3. **Future extensibility**: Phase 3D may require chunk-level embeddings for long documents (sliding-window chunking). With a separate table, adding a `chunk_index` column to `event_embeddings` and dropping the PK constraint is straightforward. With a combined table, the schema change is entangled with the event's identity.

---

## JSONB vs. Typed Columns for `source_metadata`

**The case for typed columns**: typed columns allow SQL queries to filter on specific fields (`WHERE source_metadata->>'author_email' = 'alice@company.com'` vs. `WHERE author_email = 'alice@company.com'`), use indexes on individual fields, and enforce field-level constraints. They also make the schema self-documenting.

**The case for JSONB**: the Company Brain ingestion pipeline is designed to accept multiple source types — Slack messages, ADRs, meeting notes, and whatever future sources Phase 2+ introduces. Each source type has a radically different metadata shape. Slack messages have `channel_id`, `workspace_id`, `thread_ts`, `user_id`. ADR documents have `file_path`, `git_hash`, `last_modified`. Meeting notes have `attendees`, `agenda_items`, `action_items`. Forcing all of these into typed columns on a shared `events` table would require either: (a) a very wide table with many nullable columns, one group per source type, or (b) separate tables per source type, which fragments the provenance index.

**Decision: JSONB**. The source_type column discriminates the source, so queries that need source-specific metadata can use typed GIN indexes on JSONB paths. The `events` table's purpose is provenance anchoring, not structured query. Typed relational structure lives in the Neo4j graph nodes, which are produced by extraction. JSONB keeps the raw ingest layer flexible without requiring a schema migration every time a new source type is added.

---

## Why pgvector Here and Not a Separate Vector Database

See [ADR 0003](../decisions/0003-pgvector-vs-dedicated-vector-db.md) for the full decision. In summary: the most valuable queries in Company Brain are relational-vector hybrids — "find events semantically similar to X that were ingested after date Y and authored by team Z." With pgvector, this is a single SQL query using `<=>` (cosine distance) alongside a WHERE clause. With a dedicated vector DB (Pinecone, Weaviate, Qdrant), it is two round trips and application-level join logic. At the synthetic-data scale of this portfolio project (<100k vectors), pgvector's query performance is indistinguishable from dedicated systems. The operational simplicity — one DB, one backup, one migration tool — is a clear win.

---

## Indexes

| Table | Column(s) | Type | Rationale |
|-------|-----------|------|-----------|
| `events` | `(source_type, source_external_id)` | UNIQUE | Dedup enforcement at DB layer; also used by `get_by_source` lookups |
| `events` | `content_hash` | B-Tree | Enables O(log n) content-dedup checks in `get_by_content_hash` |
| `events` | `created_at` | B-Tree | Range queries for `list_since(timestamp)` used in temporal contradiction detection |
| `event_embeddings` | `embedding` | HNSW (`vector_cosine_ops`) | Approximate nearest neighbour search for `similar_to(vector, limit)` |
| `extraction_runs` | `(event_id, started_at)` | B-Tree (composite) | `latest_for_event(event_id)` ORDER BY started_at DESC LIMIT 1 |

**HNSW vs. IVFFlat for the embedding index**:

IVFFlat partitions the vector space into `lists` clusters, trained at index creation time. At query time, it searches only the nearest `probes` clusters. This produces good recall when the index has been trained on a representative sample, but it requires a `VACUUM ANALYZE` and retraining pass as the dataset grows, and it cannot be built on an empty table.

HNSW (Hierarchical Navigable Small World) builds a multi-layer graph of proximity relationships incrementally. Every insert extends the graph; no retraining is needed. Query time is sub-logarithmic. At demo scale (tens of thousands of events), HNSW builds in seconds and queries in <5ms at >95% recall with default `m=16, ef_construction=64` parameters.

**Decision: HNSW**. The portfolio project's embedding table will be populated incrementally over the life of the demo. HNSW's incremental-build property avoids a retraining step that would otherwise be needed every time the Phase 2A generator adds more synthetic events. IVFFlat's advantage — better QPS on very large static datasets — does not apply here. The index is created with `USING hnsw (embedding vector_cosine_ops)`.

---

## Foreign Key Strategy

`event_embeddings.event_id` and `extraction_runs.event_id` reference `events.id`:
- **`event_embeddings`**: `ON DELETE CASCADE`. An embedding without its parent event is meaningless and wasteful. Auto-remove.
- **`extraction_runs`**: No cascade. Extraction run records are audit history. Even if an event were somehow removed (which should not happen under the immutability contract), the audit trail should survive.

The Alembic migration creates these constraints explicitly. SQLAlchemy's ORM models declare them via `ForeignKey("events.id", ondelete="CASCADE")` and `ForeignKey("events.id")` respectively, so they are reflected in autogenerate.

---

## Provenance Contract

Graph nodes in Neo4j carry a `source_event_ids: list[UUID]` property. These UUIDs are IDs in the `events` table. The contract is:

1. **Write order**: the extraction pipeline writes an event row to Postgres *before* writing any graph nodes derived from it. This ensures the UUID exists in Postgres before the graph references it.
2. **Cross-store referential integrity**: the database cannot enforce this across Neo4j and Postgres. It is enforced by the extraction pipeline and verified by `backend/scripts/check_provenance.py` (Phase 4), which runs a reconciliation check: for every `source_event_ids` value found in the graph, does a row with that UUID exist in `events`?
3. **Orphan detection**: the same reconciliation check finds `events` rows that have no graph nodes derived from them — i.e., events that were ingested but never extracted. This is the normal state for newly ingested events; it becomes a warning after a configurable age.

The provenance contract is the bridge between the two stores. Without it, the graph's "where did this come from?" answer is unverifiable. With it, every graph node traces back to a specific, timestamped, immutable raw-text source.

---

## What Is Out of Scope

- **Table partitioning**: the `events` table could be range-partitioned by `ingested_at` for archival at billions of rows. Omitted. At synthetic-demo scale, a single table is correct.
- **Read replicas**: vector search and graph traversal are the hot paths; read replicas would help at production scale. Out of scope.
- **Archival policy**: there is no TTL on events. All events are retained indefinitely. This is appropriate for an audit-anchored system at demo scale.
- **Multi-tenancy**: all data is for a single synthetic company. No `tenant_id` column.
- **Full-text search**: the `content` column is not tsvector-indexed. Full-text search on events is deferred to Phase 3D, where the hybrid query combines the vector index with a GIN tsvector index if needed.

---

## Open Questions for Phase 2+

1. **Chunk-level embeddings**: Phase 3D may require chunking long documents before embedding. The current schema assumes one embedding per event. If chunking is needed, `event_embeddings` will need a `chunk_index` integer column and a composite PK `(event_id, chunk_index)`.
2. **Source type extensibility**: new source types (email threads, GitHub issues, Confluence pages) require an `ALTER TYPE sourcetype ADD VALUE` migration on the Postgres enum. This is safe in Postgres 12+ but requires careful Alembic handling.
3. **Re-embedding strategy**: Phase 3D will pick the embedding model. When the model changes, all existing embeddings become stale. The `model_name` + `model_version` columns on `event_embeddings` make staleness detectable; the actual re-embedding workflow (batch job, background worker) is deferred.
4. **Deduplication semantics**: `content_hash` detects exact-duplicate content. Near-duplicate detection (e.g., a message that was slightly edited before re-sending) is not implemented. Phase 3D's embedding similarity search could serve as a near-dup detector if needed.
5. **`extraction_runs` retention**: audit rows accumulate indefinitely. A pruning strategy (keep only the latest N runs per event) may be needed at scale.

---

## Related ADRs

- [ADR 0009](../decisions/0009-postgres-event-store-design.md) — Event store design: append-only, UUID-keyed, cross-store provenance contract
- [ADR 0010](../decisions/0010-alembic-migrations.md) — Alembic migration strategy for Postgres schema changes
