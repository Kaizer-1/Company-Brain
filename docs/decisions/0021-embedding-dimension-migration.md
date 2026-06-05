# ADR 0021 — Embedding Dimension Migration: 1536 → 384

## Status

Accepted

## Context

The `event_embeddings` table was created in Phase 1C with `vector(1536)`, a dimension chosen
for OpenAI's `text-embedding-3-small` model. That choice was made before the project selected
an embedding strategy, as a placeholder sized to the most capable hosted embedding API at the
time.

Phase 3A (entity resolution) adopted `BAAI/bge-small-en-v1.5` via sentence-transformers for
all embedding work. The rationale in ADR 0014 is unambiguous: local, free, deterministic,
384-dimensional. Entity resolution runs hundreds of embed calls per pipeline invocation at
zero cost. The model has been live in the codebase since Phase 3A with no issues.

Phase 3D (semantic search) embeds every event's content and queries by cosine similarity. The
dimension the search system uses must match the dimension in `event_embeddings`. Two options:

1. **Keep vector(1536) and use a second, 1536-dim model** — e.g., OpenAI
   `text-embedding-3-small`. Requires an API key, costs money per call, introduces a hosted
   dependency, and violates the single-model principle in the Phase 3D design doc.
2. **Migrate to vector(384) and use the existing bge-small model** — the table is empty
   (Phase 3D is the first writer), the migration is drop-and-recreate, and the codebase has
   a live working instance of the model already.

The choice is not close.

## Decision

Migrate `event_embeddings.embedding` from `vector(1536)` to `vector(384)` via Alembic
migration `0004_embedding_dimension_fix`. The migration:

1. Performs a defensive row-count check (refuses if the table is non-empty, protecting
   future runs after the table is populated).
2. Drops the existing HNSW index and table.
3. Recreates the table with `vector(384)`.
4. Recreates the HNSW index with the same parameters (`m=16, ef_construction=64`).

The `EMBEDDING_DIM` constant in `app/models/embeddings.py` is updated from `1536` to `384`.
All callers that reference `EMBEDDING_DIM` (the ORM column type and the `similar_to` bind
param in `EventEmbeddingRepository`) pick up the new value automatically.

## Alternatives Considered

### Option A — Add a second 1536-dim model for event search, keep 384 for entity resolution

Two models in the same pipeline means two load costs, two model-version pins, two sets of
embeddings with incompatible vector spaces, and a semantic gap in the data (entity-resolution
embeddings and event-content embeddings cannot be compared). The search system is designed
around a single model and a single vector space. Rejected.

### Option B — Migrate to a larger local model (e.g. bge-large-en-v1.5, 1024 dims)

bge-large-en-v1.5 would produce higher-quality embeddings at the cost of ~3× the model size
(~1.3 GB vs ~130 MB) and ~4× the inference time. Phase 3D's eval targets (Recall@10 ≥ 0.70,
MRR ≥ 0.50, latency ≤ 500ms) are achievable with bge-small at this corpus scale. Trading
image size and latency for marginal quality improvement on a ~100-event eval corpus is
premature optimisation. If eval numbers fall short, upgrading the model is a one-line
constant change and a new migration — it is the documented upgrade path, not a deferred
decision. Rejected for Phase 3D.

### Option C — Use pgvector's half-precision storage (vector HALFVEC)

pgvector 0.7+ supports `halfvec` which halves storage at the cost of precision. Interesting
at scale; irrelevant at demo scale (the full table will have ~100 rows). Not supported by
all pgvector versions and introduces a new codec concern. Rejected.

## Consequences

**Positive:**
- Single embedding model across the entire codebase. Entity resolution and semantic search
  use the same vectors and the same vector space. A single `embed_texts` call in
  `resolution/embeddings.py` serves both workloads.
- No API key or network dependency for embedding. Fully deterministic and reproducible
  across machines.
- Smaller index footprint. 384-dim HNSW is faster to build and query than 1536-dim.

**Negative / accepted:**
- bge-small-en-v1.5 is a 384-dim model; it is competitive but not state-of-the-art on
  general retrieval benchmarks. At the synthetic corpus scale this does not matter; at
  production scale the upgrade path (larger local model or hosted API) is the first lever.
- The `test_embeddings.py` constant check and several docstrings required updating. Minor.

## Production scaling path

At scale (millions of events), the HNSW parameters become more important:
- `ef_construction=64` is appropriate for recall-latency balance up to ~1M vectors; bump to
  128 or 200 for denser graphs.
- `m=16` is the default connection count; tuning range is 8–64 depending on recall targets.
- For multi-tenant deployments, separate HNSW indexes per tenant namespace are the standard
  pattern; pgvector 0.7's partitioned indexes support this.
- The model upgrade path is a new Alembic migration (change dimension) + re-embed pipeline
  pass. The defensive row-count guard in 0004 is the pattern for future re-embedding
  migrations.
