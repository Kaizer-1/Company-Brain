# Phase 1C Interview Readiness — Postgres Event Store

## Q&A Pairs

---

**Q1: Why are events immutable and what would you do if you needed to fix bad data?**

Events are immutable because they are the provenance anchor for the entire knowledge graph. Every Neo4j node carries a `source_event_ids` property — a list of UUIDs pointing into the Postgres `events` table. If an event row could be updated after graph nodes were already extracted from it, then a graph node's claim "this decision was extracted from event X" would be unfalsifiable: event X might now contain something completely different. You would have no way to reproduce the extraction or audit the original source.

If bad data needs to be corrected — for example, a document was ingested with encoding errors — the workflow is: fix the source, ingest the corrected version as a *new* event (which gets a new UUID and a different content hash), re-run extraction against the new event, and optionally tag the old graph nodes with the replacement event's UUID. The old event stays in the table permanently as a record of what was originally ingested. The extraction pipeline's `extraction_runs` table makes this traceable: you can see exactly which model version, which prompt, and which timestamp produced the current graph nodes, and that they were derived from the old (bad) event, not the corrected one.

---

**Q2: Why split events and embeddings into two tables?**

Three reasons, each independently decisive. First, hot path isolation: every ingest creates an event row, but embedding computation is expensive — roughly 100ms per call — and typically batched or async. A combined table forces every ingest to either block on embedding computation or write a null embedding column that breaks pgvector index strategies. The separate table makes the ingest path fast and the embedding lifecycle explicit.

Second, re-embedding without event mutation: when a new embedding model is released, you want to replace all embeddings without touching the events table. With a separate table, `DELETE FROM event_embeddings` followed by a bulk re-embed is clean and safe. With a combined table, re-embedding requires an `UPDATE` on the events table, which violates immutability — you lose the record of what the old embedding was and can no longer audit why graph results changed.

Third, future extensibility: Phase 3D may need chunk-level embeddings for long documents (sliding-window chunking). With a separate table, adding a `chunk_index` column and promoting it to a composite primary key is a straightforward migration. With a combined table, that change is entangled with the event's core identity columns and much harder to reason about.

---

**Q3: Walk me through what happens when the same Slack message gets ingested twice.**

The `events` table has a unique constraint on `(source_type, source_external_id)`. When the ingestion pipeline calls `EventRepository.create(event_data)`, SQLAlchemy issues an `INSERT` and the DB enforces this constraint. If the `(source_type='slack_message', source_external_id='CH001:ts123')` pair already exists, Postgres raises a `UniqueViolation` which SQLAlchemy surfaces as `sqlalchemy.exc.IntegrityError`.

The ingestion pipeline catches this at the repository call site. It has two sensible responses: (1) log a `duplicate_event_skipped` event and move on — the message was already processed; or (2) call `EventRepository.get_by_source(SourceType.slack_message, 'CH001:ts123')` to retrieve the existing event and return its ID to the caller without inserting.

Additionally, `content_hash` provides a secondary dedup signal. Before inserting, the pipeline can call `get_by_content_hash(sha256(content))` to detect semantically identical content even when the source ID differs — for example, the same message forwarded to two channels. This is a soft check; the hard constraint is the unique key.

---

**Q4: Why JSONB for source_metadata? When would that be wrong?**

JSONB is the right choice here because different source types have radically different metadata shapes. Slack messages have `channel_id`, `workspace_id`, `thread_ts`, `user_id`. ADR documents have `file_path`, `git_hash`, `last_modified`, `section`. Meeting notes have `attendees`, `agenda_items`, `action_items`. Forcing all of these onto typed columns in a shared `events` table would require either: a very wide table with mostly-null column groups, one per source type; or separate tables per source type, which fragments the provenance index and means every new source type requires new tables that `source_event_ids` in the graph would need to know about.

JSONB defers the typing decision to the extraction layer, where source-specific structure actually belongs. The `source_type` column discriminates the source, and a GIN index on JSONB paths can support typed queries if a specific path becomes a common filter.

When would this be wrong? Three cases: (1) if a specific metadata field becomes a very high-frequency filter (e.g., `WHERE source_metadata->>'author_email' = $1` runs millions of times per day), a typed column with a B-Tree index would be faster; (2) if you need strict schema enforcement at the database level — JSONB is permissive and lets any shape in; (3) if you're building a data warehouse or analytical store where column-oriented access is the primary access pattern — JSONB doesn't compress or scan as efficiently as typed columns.

---

**Q5: How does provenance work across two databases that don't share foreign keys?**

It works through a combination of write-order contract, runtime enforcement, and a reconciliation check. The write-order contract says: the extraction pipeline writes an event row to Postgres *before* writing any graph nodes derived from it. This ensures the UUID exists in Postgres before the graph references it. The runtime enforcement is in the extraction pipeline itself — it passes the event's `id` (a UUID from the `events` table) to the graph write path, which embeds it in the node's `source_event_ids` property.

The reconciliation check — `check_provenance.py` (Phase 4 stub) — periodically scans the graph for all `source_event_ids` values and verifies that a row with that UUID exists in the `events` table. If a graph node references a UUID that has no corresponding event, it is flagged as an orphan. The reverse check — events with no graph nodes derived from them — identifies unextracted or failed extractions.

What you cannot do is enforce this at the database level. Postgres and Neo4j are separate processes; there is no FOREIGN KEY across them. The two-phase write (Postgres first, then Neo4j) and the reconciliation script are the engineering discipline that makes provenance trustworthy.

---

**Q6: HNSW vs IVFFlat — which did you pick and why?**

HNSW. The primary reason is build-time semantics: IVFFlat requires a training pass to determine cluster centres — it cannot be built on an empty table. The Postgres documentation states you need at least `lists * 3` rows before `CREATE INDEX` succeeds. For a portfolio project where the database starts empty and is populated incrementally by the synthetic data generator and extraction pipeline, that means the IVFFlat index cannot be created at migration time — it must be deferred and manually triggered after sufficient data is loaded. This breaks the "migration brings up a correct schema" contract.

HNSW builds incrementally. Every INSERT extends the graph structure. No retraining is needed. You can create the HNSW index on an empty table in the initial Alembic migration, and it works correctly from the first row inserted.

Performance: at demo scale (<100k vectors), HNSW with default `m=16, ef_construction=64` achieves >95% recall at <10ms query time. IVFFlat's advantage — better queries-per-second per unit of memory — only materialises at >1M vectors with a tuned `lists` parameter. At that scale, I'd revisit, but we're not there.

The tradeoff: HNSW uses more memory per vector than IVFFlat, and its build time is O(n log n) rather than O(n). For a large, static dataset, IVFFlat is more efficient. For an incrementally populated demo, HNSW is correct.

---

**Q7: Why do repositories return Pydantic DTOs instead of SQLAlchemy model instances?**

Two reasons: async safety and boundary clarity. SQLAlchemy ORM instances are bound to a session. After the session closes, accessing any relationship or unloaded attribute on the ORM instance triggers a lazy load — which in an async context raises `MissingGreenlet`, because lazy loading requires a sync greenlet that doesn't exist. You'd have to explicitly `await session.refresh(instance)` before closing the session, or use `selectinload` on every query, or keep the session open longer than you want. Returning Pydantic DTOs at the repository boundary means the caller gets a plain Python object with no session dependency. It can be passed to any layer, serialised, logged, or compared without risking a lazy-load error.

The second reason is boundary clarity. If ORM instances escaped the repository layer, service code could accidentally issue database queries by navigating relationships — `event.embeddings[0].model_name` — without the developer realising a SQL query is happening. DTOs make the DB boundary explicit: data flows out of the repository as a frozen Pydantic model and cannot trigger further queries.

The cost is that you have to write a `_to_dto()` function in each repository. For three tables, this is minimal ceremony.

---

**Q8: What does extraction_runs let you do that you couldn't do without it?**

Four things. First, failure visibility: a failed extraction produces no graph nodes. Without `extraction_runs`, there is no way to know whether an event was never extracted, was extracted and produced zero entities, or was extracted and the pipeline crashed. `extraction_runs` with `status=failed` and an `error_message` makes the difference visible.

Second, the model-upgrade workflow: when a new extraction model is deployed, you need to identify all events that were extracted by the old model and re-queue them. With `extraction_runs`, this is a query: `SELECT DISTINCT event_id FROM extraction_runs WHERE model_name = 'old-model'`. Without it, you'd have to scan the graph for `extracted_by` edge properties and hope they're complete.

Third, prompt change detection: `prompt_hash` records the SHA-256 of the exact extraction prompt used. If the prompt changes (e.g., a new entity type is added to the extraction instructions), you can identify all events that need re-extraction by finding runs with the old `prompt_hash`.

Fourth, timing and count audit: `started_at`, `completed_at`, `extracted_node_count`, and `extracted_edge_count` give you a timeline of extraction performance, which is valuable for debugging model latency and counting graph nodes produced per extraction pass.

---

**Q9: If you needed to re-extract every event with a new model, what's the workflow?**

Step one: deploy the new extraction model. Step two: query `extraction_runs` to find all events that were last extracted by the old model version: `SELECT DISTINCT event_id FROM extraction_runs WHERE model_name = 'old-model-name'`. Step three: for each such event, call `EventRepository.get_by_id(event_id)` to retrieve the original content, then run the new extraction pipeline — which calls `ExtractionRunRepository.create_pending()`, runs the LLM, writes graph nodes, then calls `mark_success()` or `mark_failed()`.

The graph write path (Phase 2E) will need to handle the case where graph nodes for this event already exist: either merge/update them or create new nodes and deprecate the old ones. Phase 2E's upsert semantics will govern this.

Step four: verify by querying `latest_for_event` for a sample of events and confirming the latest run has `status=success` and `model_name='new-model-name'`. The provenance reconciliation check in `check_provenance.py` can then verify that every graph node's `source_event_ids` still point to valid events.

The key insight is that none of this requires modifying the `events` table. The raw content is preserved immutably; the extraction layer produces new derived graph nodes; the audit table tracks the full history.

---

**Q10: What's the biggest weakness of this Postgres design and what would you change in v2?**

The biggest weakness is the `event_embeddings` primary key being `event_id` — one embedding per event. This is already named as an open question in the design doc. For Phase 3D, long documents (multi-page ADRs, meeting transcripts) need chunk-level embeddings: a document split into overlapping windows, each chunk embedded separately. With the current schema, that requires an `ALTER TABLE event_embeddings ADD COLUMN chunk_index integer, DROP CONSTRAINT pk_event_embeddings, ADD CONSTRAINT pk_event_embeddings PRIMARY KEY (event_id, chunk_index)` migration. That's not catastrophic, but it's an anticipated breaking schema change.

In v2, I'd design the `event_embeddings` table with a `chunk_index integer NOT NULL DEFAULT 0` column from the start, with a composite PK `(event_id, chunk_index)`. A document with a single embedding would have one row with `chunk_index=0`. A chunked document would have rows `chunk_index=0, 1, 2, ...`. The HNSW index remains the same. The `upsert` method in the repository becomes `upsert_chunk(event_id, chunk_index, vector, ...)`. The cost is one extra column that's always zero for the first version; the benefit is that Phase 3D's chunking requirement doesn't require a schema migration.

The second weakness is the lack of a GIN index on `source_metadata`. As source types multiply and metadata queries become common, the absence of a JSONB index will cause sequential scans. Adding `CREATE INDEX ON events USING GIN (source_metadata)` is a non-blocking operation in Postgres 12+ and should happen in Phase 2B when the first source type's metadata queries are profiled.

---

## Whiteboard Concepts

### 1. Immutable Event Log Pattern

Diagram showing the append-only `events` table with a UUID PK. Arrows from graph nodes (`Service`, `Decision`, `Message`) via `source_event_ids` pointing into the table. A separate `extraction_runs` table with `event_id` FK. An annotation: "Events are written once. Corrections create new events. Graph nodes reference event UUIDs. The provenance chain is always traceable."

### 2. Two-Store Provenance Bridge

Two boxes: "Postgres (events table)" and "Neo4j (knowledge graph)". A bidirectional arrow labelled "source_event_ids". Annotations: "Postgres: immutable, UUID-keyed, source of truth for raw content. Neo4j: derived, canonical-name-keyed, source of truth for structured knowledge. Cross-store referential integrity enforced by extraction pipeline write order and reconciliation script."

### 3. HNSW Index Structure

A layered graph diagram (three layers). Top layer: sparse connections, few nodes. Bottom layer: dense connections, all nodes. Query path: enter at top, descend greedily by cosine distance, exit at bottom layer with the k nearest neighbours. Annotation: "m=16 max connections per layer, ef_construction=64 build-time search width. No training step — insert-time index build, not batch-trained like IVFFlat."

### 4. Repository + DTO Pattern

A column diagram: `AsyncSession` → `EventRepository._session` → SQL query → `Event` ORM row → `_to_dto()` → `EventDTO` (Pydantic, frozen) → service layer. Annotation: "ORM instances never escape the repository. DTOs carry no session reference. Accessing a DTO after session close never raises MissingGreenlet."

### 5. Alembic Migration Idempotency

A timeline: "Fresh DB" → `alembic upgrade head` → schema created → `alembic_version` row inserted. Second call: `alembic upgrade head` → reads `alembic_version` → revision already applied → no-op. Annotation: "Idempotency is guaranteed by the alembic_version ledger. The initial migration itself is idempotent via CREATE EXTENSION IF NOT EXISTS and DO $$ IF NOT EXISTS $$ guards on enum types."
