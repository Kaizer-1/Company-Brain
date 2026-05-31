# ADR 0009 — Postgres Event Store Design

## Status

Accepted

## Context

Phase 1C introduces the relational side of Company Brain: an immutable raw-event log in Postgres that serves as the provenance anchor for the Neo4j knowledge graph. Every graph node carries a `source_event_ids` property — a list of UUIDs pointing into the Postgres `events` table. Without a stable, well-designed Postgres schema, the graph's provenance claims are unverifiable. The core design questions are: (1) should events be mutable or immutable? (2) should embeddings live in the same table as events? (3) should source-specific metadata be typed or schemaless? (4) how do we track the extraction pipeline's work? (5) which approximate nearest-neighbour index algorithm should we use for vector similarity search?

The decisions here are binding for Phases 2–4. Changing the shape of the `events` table after graph nodes have been produced from it would require a provenance reconciliation migration, which is expensive and error-prone.

## Decision

Three tables: `events` (immutable raw-event log), `event_embeddings` (one embedding row per event, stored separately), and `extraction_runs` (audit log for every extraction attempt). JSONB for source-specific metadata. HNSW index for vector similarity search.

## Alternatives Considered

### Option A — Mutable events table

**What it is**: Allow `content` and `source_metadata` to be updated after insert, e.g., if the original ingestion contained encoding errors.

**Pros**:
- Simpler correction workflow: UPDATE the row, no new UUID needed
- Graph nodes can keep their `source_event_ids` pointing at the same row

**Cons**:
- Destroys provenance integrity: a graph node's claim "this knowledge came from event X" is now unfalsifiable because event X may have changed. If a node says "Decision A was made" and event X now says something different, we cannot know what the node was extracted from
- Forces either a full re-extraction of affected graph nodes or silent staleness
- Cannot serve as an audit log if the log is mutable

**Rejected**: immutability is the only design that gives provenance meaning. Corrections are handled by ingesting a new event (new UUID, new content hash) and re-running extraction.

### Option B — Combined `events_with_embeddings` table

**What it is**: Add an `embedding vector(1536)` column and `model_name` / `model_version` columns directly to the `events` table.

**Pros**:
- Fewer tables
- No join needed between events and embeddings

**Cons**:
- Every event insert either blocks on embedding computation or writes a row with a null embedding; nulls in a `vector` column break most pgvector index strategies
- Re-embedding (when a new model is adopted) requires UPDATE on the events table — violating immutability
- Cannot represent chunk-level embeddings (needed for long documents in Phase 3D) without a separate table anyway

**Rejected**: the two-table split is the only design that keeps the event insert path fast, preserves immutability, and allows re-embedding without schema coupling.

### Option C — Typed columns for source_metadata (one column per source field)

**What it is**: Add individual typed columns to `events` for every known source-specific field: `slack_channel_id text`, `slack_user_id text`, `doc_file_path text`, `doc_git_hash text`, etc.

**Pros**:
- Type-safe at the database level
- Standard SQL indexes (no GIN)
- Schema is self-documenting

**Cons**:
- A very wide table with mostly-null columns (only a few fields are relevant per source type)
- Every new source type requires an `ALTER TABLE events ADD COLUMN` migration — a schema migration for each new data source
- Puts source-specific structure in the wrong layer: source-specific typed structure belongs in the extraction output (graph nodes), not in the raw ingest layer

**Rejected**: JSONB keeps the ingest layer flexible. Source-specific typed structure is the extraction pipeline's job.

### Option D — No extraction_runs table; derive state from the graph

**What it is**: Instead of tracking extraction runs in Postgres, infer them from the graph (e.g., "if a graph node exists with `source_event_ids = [X]`, then event X was extracted").

**Pros**:
- One fewer table
- Simpler write path

**Cons**:
- Cannot track failed extractions (a failed extraction produces no graph nodes, so its state is invisible)
- Cannot distinguish "never extracted" from "extracted and produced zero entities" from "extraction failed"
- Cannot support the model-upgrade workflow ("re-extract all events processed by model version M") without querying the graph, which requires traversal logic
- Cannot capture per-run metadata: prompt hash, timing, node counts

**Rejected**: the extraction_runs table is the operational memory of the extraction pipeline. Without it, re-extraction, failure recovery, and model versioning are all blind.

### Option E — IVFFlat index for vector similarity

**What it is**: Use the IVFFlat approximate nearest-neighbour index (`USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)`) instead of HNSW.

**Pros**:
- Lower memory footprint than HNSW at very large scales (>1M vectors)
- Good QPS on large, static datasets when `lists` is tuned

**Cons**:
- Requires training: the index cannot be built on an empty table; a minimum of `lists * 3` rows must exist before `CREATE INDEX` succeeds. For a portfolio project that starts from zero and populates incrementally, this means the index cannot be created at migration time — it must be deferred and manually triggered after sufficient data is loaded
- Recall degrades as the dataset grows unless `probes` is re-tuned (changing `probes` at query time is possible but adds operational complexity)
- IVFFlat's advantage — better QPS per memory unit — only materialises at >1M vectors, which is far beyond the synthetic-demo scale

**Rejected**: HNSW builds incrementally (no training step), handles an empty table at migration time, and achieves >95% recall at <10ms for <100k vectors with default parameters. The operational simplicity is decisive for a portfolio project.

## Consequences

**Enables**: Immutable provenance anchoring for the entire graph. A single SQL query for hybrid (vector + relational) search. Clean re-embedding and re-extraction workflows. Failure detection and replay via extraction_runs. HNSW index usable from day one on an empty table.

**Constrains**: Events cannot be edited after insert (by design). The `sourcetype` enum requires an `ALTER TYPE` migration to add new source types. The embedding dimension (1536) is fixed in the HNSW index; changing it requires dropping and rebuilding the index.

**Locked into**: Postgres as the provenance store. JSONB for source metadata (acceptable until a source type's query patterns demand typed columns). HNSW for the embedding index. One embedding per event (revisit in Phase 3D if chunk-level embeddings are needed).

**At larger scale / in production**: At >10M events, partition `events` by `ingested_at` for archival. At >1M embeddings, revisit IVFFlat with a tuned `lists` parameter for memory efficiency. Add a background worker (Phase 4) to decouple embedding computation from the ingest hot path. Add a GIN index on `source_metadata` for typed JSONB path queries if source-specific filters become common.

## Interview Defense

> "Events are immutable because they are the provenance anchor for the entire graph. If you could edit an event, a graph node's claim 'I came from event X' would be unfalsifiable — you'd have no way to know what the node was originally extracted from. Corrections are handled by re-ingesting and re-extracting, not by patching the source. Embeddings are in a separate table so we can re-embed without touching events. HNSW is the right index here because it builds incrementally — IVFFlat can't be created on an empty table, which breaks migration-time index setup. The tradeoff is memory: HNSW uses more RAM per vector than IVFFlat at scale, but we're nowhere near that scale."
