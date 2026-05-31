# ADR 0003 — pgvector over Dedicated Vector Database

## Status

Accepted

## Context

Company Brain needs vector storage for semantic search over messages and decision documents. In Phase 3D, we will embed text chunks and retrieve the top-k most semantically similar chunks for queries like "find messages conceptually related to the payments service outage." The question is whether to use a purpose-built vector database (Pinecone, Weaviate, Qdrant) or the pgvector extension on our existing Postgres 16 instance.

Key constraint: many of our most interesting queries combine semantic similarity with relational filters — "find messages semantically similar to X that were authored by the payments team in Q3." The choice of vector store directly affects whether these are single-query or multi-round-trip operations.

## Decision

pgvector extension on Postgres 16, over Pinecone, Weaviate, and Qdrant.

## Alternatives Considered

### Option A — Pinecone (managed SaaS)

**What it is**: Serverless managed vector database; store embeddings via API, query with `top_k` + optional metadata filters.

**Pros**:
- Zero infrastructure to operate — no Docker service, no index tuning
- Scales horizontally to billions of vectors with no config changes
- Built-in metadata filtering (though limited compared to SQL)

**Cons**:
- Cloud-only SaaS: requires an internet connection and API key even for local development; no offline demo
- The most interesting queries require a relational join *after* the vector search. With Pinecone, this is two round trips: (1) vector search → get IDs, (2) query Postgres with those IDs. Application code owns the join logic. This is more code, more latency, and more failure modes
- Adds a third managed external service to the stack (we already have Neo4j and Postgres)
- Cost at scale: Pinecone is free only up to ~100k vectors; our Phase 2 synthetic dataset may exceed that

### Option B — Weaviate

**What it is**: Open-source vector database with built-in hybrid search (BM25 + vector), a rich schema model, and a GraphQL API.

**Pros**:
- Hybrid search (keyword + vector) is first-class, not bolted on; good for Phase 3D
- Runs locally via Docker; no external API dependency
- Good Python client

**Cons**:
- Third Docker service in the Compose stack — Neo4j is already heavy; a third DB makes `docker compose up` slower and more fragile
- Weaviate's schema model duplicates what Postgres already provides. We'd maintain two representations of the same metadata (Weaviate schema + Postgres tables), which drift apart and add synchronisation bugs
- The relational join problem is the same as Pinecone: vector results come back from Weaviate, relational metadata comes from Postgres, application code joins them
- At demo scale, Weaviate's operational overhead is not justified by the performance gain

### Option C — Qdrant

**What it is**: Open-source vector database written in Rust; optimised for high-throughput vector search with low memory overhead.

**Pros**:
- Excellent raw performance — fastest among self-hosted options at comparable recall
- Good Python client; active development
- Runs locally via Docker

**Cons**:
- Same co-location argument as Weaviate: we'd have a third service and need application-level joins
- Qdrant's metadata filtering is good but not SQL — complex date range + team + service filters require its own query DSL, which is less expressive than SQL for relational data
- No incremental advantage over pgvector at demo scale (<100k vectors)

### Option D — pgvector on Postgres 16 (chosen)

**What it is**: Postgres extension that adds a `vector(n)` column type, cosine/L2/inner-product operators, and HNSW/IVFFlat indexes.

**Pros**:
- **Co-location**: embeddings live in the same database as their metadata. The query "find messages semantically similar to X authored by the payments team in Q3" is one SQL query with a `<=>` operator and a WHERE clause — no round trips, no application join, no synchronisation lag
- **Single operational unit**: one backup covers both relational data and vectors; one monitoring dashboard; one migration tool (Alembic in Phase 1C)
- **Sub-10ms at demo scale**: pgvector with HNSW indexing achieves >95% recall at <10ms for <100k vectors
- **No additional Docker service**: one less service to start, one less thing to break in `docker compose up`

**Cons**:
- Read scaling is limited to Postgres replication — at 10M+ vectors or >1000 QPS on pure vector search, Postgres is slower than purpose-built stores
- No built-in hybrid search (BM25 + vector); we'd need to implement this manually (e.g., via tsvector + pgvector combined query)
- HNSW index build time is slower than Qdrant for large corpora

## Consequences

**Enables**: Single-query hybrid (vector + relational) search. Simple `docker compose up` with only two databases. Unified migrations and backups.

**Constrains**: Vector search performance is bounded by Postgres's threading model. Cannot scale vector search independently of the relational schema.

**Locked into**: Postgres for vector storage. Migrating embeddings to a dedicated store later requires an ETL export + re-index.

**At larger scale / in production**: The co-location advantage disappears above ~10M vectors or ~1000 QPS on pure vector search. At that threshold, Qdrant (self-hosted, excellent resource efficiency) is the right choice — accept the two-round-trip join in exchange for horizontal scale. The application layer already abstracts the vector store, so the migration is isolated to the embedding pipeline.

## Interview Defense

> "We chose pgvector because our most interesting queries are relational-vector hybrids — find entities semantically similar to X *and* owned by team Y *and* created after date Z. With pgvector, that's one SQL query. With Pinecone or Weaviate, it's two round trips and application-level join logic. At demo scale, pgvector's performance is indistinguishable from dedicated systems. The tradeoff is that we can't scale vector search independently of Postgres, but we're explicitly outside the scale where that matters."
